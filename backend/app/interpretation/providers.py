"""Adaptadores de provedor da interpretação (F08).

- `DeterministicProvider` (padrão): gera o texto por REGRAS a partir dos fatos do contexto — sem rede, sem modelo,
  mesma entrada => mesma saída. Serve de demonstração e de referência para o validador.
- `ExternalProvider`: base para provedores reais FUTUROS (nenhum fornecedor acoplado nesta fase). Concentra as travas:
  configuração explícita, credencial só no ambiente, consentimento por execução, minimização/sanitização do conteúdo,
  pré-visualização exata do que seria transmitido, limite diário e de tamanho, prazo e logs sem conteúdo. Subclasses
  implementam apenas `_send(payload) -> dict` (JSON com `statements[{text, fact_ids}]`).
O provedor NUNCA calcula, altera ou aprova indicadores: recebe fatos prontos e devolve afirmações que citam fatos;
a validação determinística (`validate.py`) decide se o texto pode seguir para aprovação humana.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from app.interpretation.contracts import Context, Kind, Level, ProviderOutput, Statement
from app.interpretation.settings import DEFAULT_PROVIDER, InterpretationSettings
from app.presentations import charts
from app.snapshots.values import canonical, sha256

logger = logging.getLogger('afrika.interpretation')


class ProviderError(Exception):
    """Falha do provedor (mensagem fixa, nunca ecoa conteúdo do contexto nem da resposta)."""

    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


# ---------------------------------------------------------------- prompt (versão registrada em cada interpretação)

PROMPT_TEMPLATE = (
    'Você redige textos para apresentações mensais de segurança de aplicações (pt-BR). Nível {level}: {tone}. '
    'Tipo: {kind}. Responda SOMENTE em JSON: {{"statements": [{{"text": "...", "fact_ids": ["M1"]}}]}}. Regras: '
    '{rules}'
)
TONE = {Level.EXECUTIVE: 'objetivo, consultivo e orientado à gestão; sem jargão desnecessário',
        Level.TECHNICAL: 'detalhado e preciso, citando indicadores (metric_id), estados de qualidade e práticas '
                         'DevSecOps'}


def prompt_text(ctx: Context) -> str:
    return PROMPT_TEMPLATE.format(level=ctx.level.value, tone=TONE[ctx.level], kind=ctx.kind.value,
                                  rules=' '.join(f'({i + 1}) {r}' for i, r in enumerate(ctx.rules)))


def prompt_hash(ctx: Context) -> str:
    return sha256({'version': ctx.prompt_version, 'template': PROMPT_TEMPLATE, 'tone': TONE[ctx.level],
                   'rules': ctx.rules})


# ---------------------------------------------------------------- provedor determinístico

ABSENCE = {'INCOMPLETE': 'coleta incompleta', 'SOURCE_UNAVAILABLE': 'fonte indisponível',
           'UNSUPPORTED': 'sem fonte que suporte o indicador', 'MISSING': 'sem coleta nem valor manual'}
STATE_ABSENCE = {'GAP': 'competência sem revisão aprovada (lacuna)', 'INCOMPATIBLE': 'contrato incompatível com o '
                 'template', 'MISSING': 'sem valor aprovado', 'NOT_NUMERIC': 'estrutura não reconhecida'}
REASON = {'gap': 'a competência anterior não tem revisão aprovada (lacuna)',
          'no_numeric_value': 'um dos valores não está aprovado como número',
          'value_type_changed': 'o tipo de valor do indicador mudou entre as competências',
          'contract_version_changed': 'o contrato do indicador mudou entre as competências',
          'previous_zero': 'a competência anterior registrou zero; variação percentual não se aplica'}


def _num(f: dict, value) -> str:
    return charts.fmt(value, f['value_type'])


SINGULAR = {'aplicações': 'aplicação', 'findings': 'finding', 'linhas de código': 'linha de código',
            'componentes': 'componente', 'projetos': 'projeto'}


def _unit(f: dict, value=None) -> str:
    if not f['unit_label']:
        return ''
    return f' {SINGULAR.get(f["unit_label"], f["unit_label"]) if value == 1 else f["unit_label"]}'


def _manual(f: dict, level: Level) -> str:
    return ' (valor manual aprovado)' if level is Level.TECHNICAL and f['origin'] == 'MANUAL' else ''


def _tech(f: dict, level: Level) -> str:
    return f' [{f["metric_id"]}]' if level is Level.TECHNICAL else ''


def _who(f: dict, level: Level, compact: bool = False) -> str:
    """Identificação do indicador: nome (+ metric_id no técnico); no técnico compacto, só o metric_id (mais curto)."""
    if compact and level is Level.TECHNICAL:
        return f'[{f["metric_id"]}]'
    return f'{f["name"]}{_tech(f, level)}'


def _absent(f: dict, comp: str, level: Level, compact: bool = False) -> str:
    if compact:
        return f'{_who(f, level, True)}: sem valor aprovado em {comp}.'
    fallback = STATE_ABSENCE.get(f['state'], 'sem valor aprovado')
    why = fallback if f['state'] in ('GAP', 'INCOMPATIBLE') else ABSENCE.get(f['value_state'] or '', fallback)
    tail = f' Estado técnico: {f["state"]}/{f["value_state"] or "—"}.' if level is Level.TECHNICAL else ''
    return f'{f["name"]}{_tech(f, level)}: sem valor aprovado em {comp} ({why}); o indicador não é interpretado.{tail}'


def _change(f: dict, level: Level, compact: bool = False) -> str:
    prev = f['previous']['competence']
    d = f['delta']
    if d is None:
        if compact:
            return f'sem comparação com {prev}'
        return f'sem comparação com {prev}: {REASON.get(f["delta_unavailable_reason"], "valores não comparáveis")}'
    if d == 0:
        return f'estável vs. {prev}' if compact else f'estável em relação a {prev}'
    word = 'aumento' if d > 0 else 'redução'
    if compact:
        pct = f', {f["delta_pct_label"]}' if f['delta_pct_label'] else ''
        return f'{word} de {_num(f, abs(d))}{pct} vs. {prev}'
    pct = f' ({f["delta_pct_label"]})' if f['delta_pct_label'] else ''
    out = f'{word} de {_num(f, abs(d))}{_unit(f, abs(d))}{pct} em relação a {prev}'
    if f['delta_unavailable_reason'] == 'previous_zero':
        out += f'; {REASON["previous_zero"]}'
    return out


def _trend(f: dict, level: Level) -> str:
    if f['trend'] == 'improvement':
        return ' Variação favorável segundo a direção desejável declarada para o indicador.'
    if f['trend'] == 'worsening':
        return ' Variação desfavorável segundo a direção desejável declarada para o indicador.'
    if level is Level.TECHNICAL and f['delta'] not in (None, 0) and f['trend_reason'] == 'direction_not_declared':
        return ' Sem direção desejável declarada: a variação não é classificada como melhora ou piora.'
    return ''


def _value_sentence(f: dict, comp: str, level: Level, compact: bool = False) -> str:
    cur = f['current']['value']
    if compact:  # tópicos de painel e legendas: frase curta, sem perder o sentido da variação
        trend = {'improvement': ' Favorável.', 'worsening': ' Desfavorável.'}.get(f['trend'], '')
        return (f'{_who(f, level, True)}: {f["current"]["label"]}{_unit(f, cur)} em {comp} '
                f'({_change(f, level, True)}).{trend}')
    return (f'{f["name"]}{_tech(f, level)}: {f["current"]["label"]}{_unit(f, cur)} em {comp}{_manual(f, level)}; '
            f'{_change(f, level)}.{_trend(f, level)}')


def _sev_label(key: str, labels: str) -> str:
    return charts.severity_label(key, labels)


def _severity_detail(f: dict, labels: str, keys=('VERY_HIGH', 'HIGH', 'MEDIUM', 'LOW')) -> str:
    sev = f['severity'] or {}
    parts = [f'{_sev_label(k, labels)} {charts.fmt(sev[k]["current"], "count")}' for k in keys if k in sev]
    return ', '.join(parts)


def _metric_facts(ctx: Context) -> list[dict]:
    return [f for f in ctx.facts if f['type'] == 'metric']


def _numeric(f: dict) -> bool:
    return f['state'] == 'VALUE'


class DeterministicProvider:
    name = DEFAULT_PROVIDER
    model = 'regras-f08@1'
    external = False

    def __init__(self, severity_labels: str = 'veracode'):
        self.labels = severity_labels
        self.compact = False

    def preview(self, ctx: Context) -> dict:
        return {'transmitted': False, 'reason': 'Provedor local determinístico: nada sai do servidor.'}

    def generate(self, ctx: Context, *, consent: bool = False) -> ProviderOutput:
        self.compact = ctx.slide['target_field'] in ('items', 'caption')
        builder = getattr(self, f'_k_{ctx.kind.value.lower()}')
        raw: list[tuple[str, list[str]]] = builder(ctx, ctx.level, ctx.competence)
        manual = [f['id'] for f in _metric_facts(ctx) if f['origin'] == 'MANUAL' and f['definitive']]
        must = []
        if manual:
            must.append(('Valores informados manualmente e aprovados na competência.' if self.compact else
                         'Parte dos valores foi informada manualmente e aprovada na competência (origem identificada '
                         'nos dados de origem).', manual))
        statements = self._fit(ctx, raw, must)
        return ProviderOutput(statements=statements, provider=self.name, model=self.model,
                              usage={'input_chars': len(canonical(ctx.model_dump(mode='json'))),
                                     'output_chars': sum(len(s.text) for s in statements)})

    # -------- limite de tamanho: o provedor só ESCOLHE quantas afirmações cabem (nunca corta frases)
    def _fit(self, ctx: Context, raw: list[tuple[str, list[str]]],
             must: list[tuple[str, list[str]]]) -> list[Statement]:
        """Escolhe as afirmações que cabem no campo, na ordem de prioridade (nunca corta frases). `must` (declaração
        de valores manuais) tem espaço reservado e vai ao final, citando só os fatos manuais efetivamente usados."""
        b = ctx.slide['budget']
        items = ctx.slide['target_field'] == 'items'
        reserve = sum(len(t) + 1 for t, _ in must)
        max_items = b['max_items'] - len(must)
        out: list[Statement] = []
        used = 0
        for text, ids in raw:
            if items:
                if len(out) >= max_items or len(text) > b['item_chars']:
                    continue
            elif out and used + 1 + len(text) + reserve > b['max_chars']:
                continue
            out.append(Statement(text=text, fact_ids=list(dict.fromkeys(ids))))
            used += len(text) + (1 if used else 0)
        if not out:  # nada cabe: entrega a 1ª afirmação e a validação acusa o excesso
            out = [Statement(text=raw[0][0], fact_ids=raw[0][1])]
            used = len(raw[0][0])
        cited = {i for st in out for i in st.fact_ids}
        for text, ids in must:
            ids = [i for i in ids if i in cited]
            if ids and (items or used + 1 + len(text) <= b['max_chars']):
                out.append(Statement(text=text, fact_ids=ids))
        return out

    # -------- tipos
    def _summary_lines(self, ctx: Context, level: Level, comp: str, limit: int) -> list[tuple[str, list[str]]]:
        out = []
        for f in _metric_facts(ctx)[:limit]:
            if _numeric(f):
                out.append((_value_sentence(f, comp, level, self.compact), [f['id']]))
            elif f['state'] == 'NOT_NUMERIC' and f['definitive']:
                continue
            else:
                out.append((_absent(f, comp, level, self.compact), [f['id']]))
        return out

    def _investigate(self, ctx: Context) -> list[tuple[str, list[str]]]:
        worse = [f['id'] for f in _metric_facts(ctx) if f['trend'] == 'worsening']
        if not worse:
            return []
        return [('Recomenda-se investigar os fatores associados às variações desfavoráveis antes de concluir sobre '
                 'suas causas, que não são identificáveis pelos dados aprovados.', worse)]

    def _k_executive_summary(self, ctx: Context, level: Level, comp: str):
        lines = self._summary_lines(ctx, level, comp, 4 if level is Level.EXECUTIVE else 8)
        head = (f'Resumo de {comp} com base exclusivamente nas revisões aprovadas da competência.', ['P1'])
        return [head, *lines, *self._investigate(ctx)]

    def _k_period_comparison(self, ctx: Context, level: Level, comp: str):
        out = []
        for f in _metric_facts(ctx):
            if not _numeric(f):
                out.append((_absent(f, comp, level, self.compact), [f['id']]))
                continue
            p = f['previous']
            if self.compact:
                out.append((_value_sentence(f, comp, level, True), [f['id']]))
                continue
            prev = f'{p["label"]}{_unit(f, p["value"])} em {p["competence"]}' if p['value'] is not None else \
                f'sem valor aprovado em {p["competence"]}'
            out.append((f'{f["name"]}{_tech(f, level)}: {f["current"]["label"]}{_unit(f, f["current"]["value"])} '
                        f'em {comp} contra {prev}; {_change(f, level)}.{_trend(f, level)}', [f['id']]))
        return out

    def _k_improvements(self, ctx: Context, level: Level, comp: str):
        out = []
        for f in _metric_facts(ctx):
            if f['trend'] == 'improvement':
                out.append((_value_sentence(f, comp, level, self.compact), [f['id']]))
            if f['desired_direction'] == 'LOWER_IS_BETTER' and f['severity']:
                for k in ('VERY_HIGH', 'HIGH'):
                    s = f['severity'][k]
                    if s['delta'] is not None and s['delta'] < 0:
                        out.append((f'Em {f["name"]}, a severidade {_sev_label(k, self.labels)} passou de '
                                    f'{charts.fmt(s["previous"], "count")} para {charts.fmt(s["current"], "count")} '
                                    f'entre {f["previous"]["competence"]} e {comp}.', [f['id']]))
        if not out:
            ids = [f['id'] for f in _metric_facts(ctx) if f['definitive']] or ['P1']
            out.append((f'Sem melhoria comprovada em {comp} entre indicadores com direção desejável declarada.'
                        if self.compact else
                        f'Não há melhoria comprovada em {comp}: nenhum indicador com direção desejável declarada '
                        'apresentou variação favorável entre competências aprovadas comparáveis.', ids))
        return out

    def _k_attention_points(self, ctx: Context, level: Level, comp: str):
        out = []
        for f in _metric_facts(ctx):
            if f['trend'] == 'worsening':
                out.append((_value_sentence(f, comp, level, self.compact), [f['id']]))
            if f['desired_direction'] == 'LOWER_IS_BETTER' and f['severity']:
                for k in ('VERY_HIGH', 'HIGH'):
                    s = f['severity'][k]
                    if s['delta'] is not None and s['delta'] > 0:
                        out.append((f'Em {f["name"]}, a severidade {_sev_label(k, self.labels)} passou de '
                                    f'{charts.fmt(s["previous"], "count")} para {charts.fmt(s["current"], "count")} '
                                    f'entre {f["previous"]["competence"]} e {comp}.', [f['id']]))
            if not f['definitive']:
                out.append((_absent(f, comp, level, self.compact), [f['id']]))
        out += self._investigate(ctx)
        if not out:
            ids = [f['id'] for f in _metric_facts(ctx) if f['definitive']] or ['P1']
            out.append((f'Não foram identificados pontos de atenção comprovados entre os indicadores analisados em '
                        f'{comp}.', ids))
        return out

    def _trends(self, ctx: Context, level: Level, comp: str):
        out = []
        for f in _metric_facts(ctx):
            h = f['history']
            if not _numeric(f) or not h:
                out.append((_absent(f, comp, level, self.compact), [f['id']]))
                continue
            w0, w1 = h['window']
            if self.compact:
                out.append((f'{_who(f, level, True)}: entre {_num(f, h["min"])} e {_num(f, h["max"])} '
                            f'de {w0} a {w1}; {f["current"]["label"]} em {comp}.', [f['id'], 'P1']))
                continue
            text = (f'{f["name"]}{_tech(f, level)}: {charts.fmt(h["months_with_value"], "count")} competência(s) com '
                    f'valor aprovado entre {w0} e {w1}, com mínimo de {_num(f, h["min"])} e máximo de '
                    f'{_num(f, h["max"])}{_unit(f)}; em {comp}, {f["current"]["label"]}{_unit(f)}{_manual(f, level)} '
                    f'({_change(f, level)}).{_trend(f, level)}')
            out.append((text, [f['id'], 'P1']))
            if h['gaps'] and level is Level.TECHNICAL:
                out.append((f'Competências sem aprovação no período de {f["name"]} (lacunas, não interpretadas): '
                            f'{", ".join(h["gaps"])}.', [f['id'], 'P1']))
            if level is Level.TECHNICAL and f['severity']:
                out.append((f'Distribuição atual de {f["name"]} por severidade: {_severity_detail(f, self.labels)}.',
                            [f['id']]))
        out += self._investigate(ctx)
        return out

    _k_sast_trends = _trends
    _k_sca_trends = _trends

    def _categories_sentence(self, f: dict, comp: str, level: Level, label_word: str) -> list[tuple[str, list[str]]]:
        cats = f['categories']
        if not cats or not cats.get('recognized'):
            return [(_absent({**f, 'state': 'NOT_NUMERIC' if cats else f['state']}, comp, level, self.compact),
                     [f['id']])]
        out = []
        prev = {r['label']: r for r in (f['previous_categories'] or {}).get('rows', []) if r['label']}
        for r in cats['rows'][:4 if level is Level.EXECUTIVE else 8]:
            if r['label'] is None or r['share_pct'] is None:
                continue
            text = (f'Em {comp}, {charts.fmt(r["share_pct"], "percentage")} {label_word} estão na situação '
                    f'"{r["label"]}" ({charts.fmt(r["value"], "count")}).')
            p = prev.get(r['label'])
            if p is not None and p['share_pct'] is not None:
                text += (f' Em {f["previous"]["competence"]}, eram {charts.fmt(p["share_pct"], "percentage")} '
                         f'({charts.fmt(p["value"], "count")}).')
            out.append((text, [f['id']]))
        return out

    def _k_compliance_evolution(self, ctx: Context, level: Level, comp: str):
        out = []
        for f in _metric_facts(ctx):
            if f['metric_id'] == 'apps.by_policy_compliance':
                out += self._categories_sentence(f, comp, level, 'das aplicações classificadas')
            elif _numeric(f):
                out.append((_value_sentence(f, comp, level, self.compact), [f['id']]))
            else:
                out.append((_absent(f, comp, level, self.compact), [f['id']]))
        return out

    def _k_scan_coverage_evolution(self, ctx: Context, level: Level, comp: str):
        out = []
        for f in _metric_facts(ctx):
            if f['metric_id'] == 'scans.covered_apps':
                out += self._categories_sentence(f, comp, level, 'das aplicações do escopo')
            elif _numeric(f):
                out.append((_value_sentence(f, comp, level, self.compact), [f['id']]))
            else:
                out.append((_absent(f, comp, level, self.compact), [f['id']]))
        return out

    def _k_chart_explanation(self, ctx: Context, level: Level, comp: str):
        out = []
        for f in _metric_facts(ctx):
            if f['severity']:
                out.append((f'O gráfico apresenta {_who(f, level, self.compact)} por severidade em {comp}: '
                            f'{_severity_detail(f, self.labels)} (total {f["current"]["label"]}).', [f['id']]))
            elif _numeric(f) and ctx.slide['type'] in ('line_chart', 'bar_chart') and f['history']:
                h = f['history']
                out.append((f'A série mostra {f["name"]} de {h["window"][0]} a {h["window"][1]}: '
                            f'{charts.fmt(h["months_with_value"], "count")} competência(s) com valor aprovado; '
                            f'em {comp}, {f["current"]["label"]}{_unit(f)}.', [f['id'], 'P1']))
            elif _numeric(f):
                out.append((_value_sentence(f, comp, level, self.compact), [f['id']]))
            elif f['categories'] and f['categories'].get('recognized'):
                c = f['categories']
                top = c['rows'][0]
                name = f'"{top["label"]}"' if top['label'] else 'a 1ª categoria'
                share = f' ({charts.fmt(top["share_pct"], "percentage")} do total listado)' if top['share_pct'] \
                    is not None else ''
                out.append((f'O gráfico distribui {f["name"]} em {charts.fmt(c["items"], "count")} categorias em '
                            f'{comp}; {name} soma {charts.fmt(top["value"], "count")}{_unit(f)}{share}.', [f['id']]))
            else:
                out.append((_absent(f, comp, level, self.compact), [f['id']]))
        return out

    def _k_ranking_highlights(self, ctx: Context, level: Level, comp: str):
        out = []
        for f in _metric_facts(ctx):
            c = f['categories']
            if not c or not c.get('recognized'):
                out.append((_absent(f, comp, level, self.compact), [f['id']]))
                continue
            top = c['rows'][0]
            who = f'"{top["label"]}"' if top['label'] else 'o 1º item'
            share = f' ({charts.fmt(top["share_pct"], "percentage")} do total listado)' if top['share_pct'] \
                is not None else ''
            out.append((f'O ranking de {f["name"]} lista {charts.fmt(c["items"], "count")} itens em {comp}; '
                        f'{who} concentra {charts.fmt(top["value"], "count")}{_unit(f)}{share}.', [f['id']]))
            if c['items'] >= 3 and c['top3_share_pct'] is not None:
                out.append((f'Os 3 primeiros somam {charts.fmt(c["top3_sum"], "count")}{_unit(f)} '
                            f'({charts.fmt(c["top3_share_pct"], "percentage")} do total listado).', [f['id']]))
            if c['labels_redacted']:
                out.append(('Os nomes dos itens do ranking não são usados na interpretação (dados identificáveis); '
                            'consulte o slide.', [f['id']]))
        return out

    def _k_technical_recommendations(self, ctx: Context, level: Level, comp: str):
        out = []
        tech = level is Level.TECHNICAL
        for f in _metric_facts(ctx):
            if not f['definitive']:
                out.append((f'Concluir a coleta de {f["name"]}{_tech(f, level)} para a próxima competência: sem valor '
                            f'aprovado em {comp}.', [f['id']]))
                continue
            sev = f['severity']
            if sev and f['desired_direction'] == 'LOWER_IS_BETTER':
                vh, hi = sev['VERY_HIGH']['current'], sev['HIGH']['current']
                if vh + hi > 0:
                    practice = ' (prática: prazos de tratamento por severidade e quality gate no pipeline)' if tech else ''
                    if self.compact:
                        out.append((f'Priorizar a triagem de {_sev_label("VERY_HIGH", self.labels)} '
                                    f'({charts.fmt(vh, "count")}) e {_sev_label("HIGH", self.labels)} '
                                    f'({charts.fmt(hi, "count")}) em {_who(f, level, True)}.', [f['id']]))
                    else:
                        out.append((f'Priorizar a triagem dos findings de severidade '
                                    f'{_sev_label("VERY_HIGH", self.labels)} ({charts.fmt(vh, "count")}) e '
                                    f'{_sev_label("HIGH", self.labels)} ({charts.fmt(hi, "count")}) em '
                                    f'{f["name"]}{_tech(f, level)}, conforme a política vigente{practice}.', [f['id']]))
            if f['trend'] == 'worsening':
                out.append((f'Investigar o aumento de {f["name"]} ({f["delta_label"]}) antes de definir ações.'
                            if self.compact else
                            f'Investigar os fatores associados ao aumento de {f["name"]} ({f["delta_label"]}) antes '
                            'de definir ações; a causa não é identificável pelos dados aprovados.', [f['id']]))
            if f['metric_id'] == 'scans.covered_apps' and f['categories'] and f['categories'].get('recognized'):
                miss = next((r for r in f['categories']['rows'] if r['label'] == 'Não cobertas'), None)
                if miss and miss['value'] > 0:
                    practice = ' (prática: varredura agendada e obrigatória antes da promoção)' if tech else ''
                    out.append((f'Confirmar a agenda de varreduras das aplicações sem scan estático publicado em {comp} '
                                f'({charts.fmt(miss["value"], "count")}){practice}.', [f['id']]))
        if not out:
            out.append(('Manter o acompanhamento mensal dos indicadores: os dados aprovados não indicam ação '
                        'específica adicional.', [f['id'] for f in _metric_facts(ctx) if f['definitive']] or ['P1']))
        return out


# ---------------------------------------------------------------- base para provedores externos (futuros)

_SENSITIVE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+|https?://\S+|\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
                        r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b|\b[0-9a-fA-F]{24,}\b|[A-Za-z0-9+/=_-]{40,}')


def minimize(ctx: Context) -> dict:
    """Só o necessário para redigir: sem hashes de conteúdo, sem ids de aprovação, sem nome de fonte técnica."""
    data = ctx.model_dump(mode='json')
    for f in data['facts']:
        prov = f.pop('provenance', None)
        if prov:
            f['competences'] = {k: v.get('competence') for k, v in prov.items()}
    return data


class ExternalProvider:
    """Base dos provedores externos. NÃO há fornecedor concreto na F08 (arquitetura preparada, sem acoplamento)."""
    name = 'external-base'
    external = True

    def __init__(self, settings: InterpretationSettings, used_today: Callable[[], int]):
        self.settings = settings
        self.used_today = used_today
        self.model = settings.model

    def payload(self, ctx: Context) -> dict:
        return {'instructions': prompt_text(ctx), 'context': minimize(ctx)}

    def preview(self, ctx: Context) -> dict:
        """O que SERIA transmitido (exatamente), para o operador decidir o consentimento."""
        body = canonical(self.payload(ctx))
        return {'transmitted': True, 'provider': self.name, 'model': self.model, 'chars': len(body),
                'max_input_chars': self.settings.max_input_chars, 'payload': self.payload(ctx)}

    def _gate(self, ctx: Context, consent: bool) -> dict:
        s = self.settings
        if not s.external_enabled:
            raise ProviderError('external_ai_disabled', 'Envio a provedor externo desligado na configuração do '
                                                         'servidor', 409)
        if s.api_key is None:
            raise ProviderError('external_ai_not_configured', 'Credencial do provedor externo ausente no ambiente '
                                                              'do servidor', 409)
        if not consent:
            raise ProviderError('external_ai_consent_required', 'Envio externo exige consentimento explícito do '
                                                                'operador para esta execução', 409)
        if self.used_today() >= s.max_requests_per_day:
            raise ProviderError('external_ai_budget_exceeded', 'Limite diário de pedidos ao provedor externo '
                                                               'atingido', 429)
        payload = self.payload(ctx)
        text = canonical(payload)
        if len(text) > s.max_input_chars:
            raise ProviderError('external_ai_payload_too_large', 'Conteúdo maior que o limite configurado para '
                                                                 'envio externo', 413)
        if _SENSITIVE.search(text):
            raise ProviderError('external_ai_payload_sensitive', 'Conteúdo com padrão sensível (e-mail, URL, '
                                                                 'identificador ou segredo) recusado para envio', 422)
        return payload

    def generate(self, ctx: Context, *, consent: bool = False) -> ProviderOutput:
        payload = self._gate(ctx, consent)
        logger.info('interpretação externa: provedor=%s tipo=%s nível=%s caracteres=%d', self.name, ctx.kind.value,
                    ctx.level.value, len(canonical(payload)))  # sem conteúdo
        try:
            raw = self._send(payload)
        except ProviderError:
            raise
        except TimeoutError:
            raise ProviderError('provider_timeout', 'O provedor externo não respondeu no prazo') from None
        except Exception:  # noqa: BLE001 — falha do fornecedor nunca vaza detalhes nem conteúdo
            raise ProviderError('provider_failed', 'Falha do provedor externo') from None
        try:
            return ProviderOutput.model_validate({**(raw if isinstance(raw, dict) else {}), 'provider': self.name,
                                                  'model': self.model})
        except ValidationError:
            raise ProviderError('provider_invalid_output', 'Resposta do provedor fora do contrato') from None

    def _send(self, payload: dict) -> dict:  # pragma: no cover - implementado por fornecedores futuros
        raise ProviderError('provider_not_implemented', 'Nenhum provedor externo implementado nesta versão', 501)


# ---------------------------------------------------------------- registro

EXTERNAL_PROVIDERS: dict[str, type[ExternalProvider]] = {}  # vazio na F08: nenhum fornecedor acoplado


def available() -> list[dict]:
    return [{'name': DEFAULT_PROVIDER, 'external': False, 'model': DeterministicProvider.model},
            *[{'name': n, 'external': True, 'model': None} for n in sorted(EXTERNAL_PROVIDERS)]]


def resolve(settings: InterpretationSettings, requested: str | None, used_today: Callable[[], int],
            severity_labels: str = 'veracode') -> Any:
    name = requested or settings.provider
    if name == DEFAULT_PROVIDER:
        return DeterministicProvider(severity_labels)
    cls = EXTERNAL_PROVIDERS.get(name)
    if cls is None:
        raise ProviderError('provider_not_available', 'Provedor de interpretação não disponível', 422)
    return cls(settings, used_today)
