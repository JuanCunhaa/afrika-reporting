"""Validação DETERMINÍSTICA das interpretações (F08) — não depende do provedor nem de IA.

Para cada afirmação, contra os fatos que ela cita (texto editado por pessoa = uma afirmação que cita todos os fatos):
- números: todo número citado precisa existir nos fatos (valor aprovado, variação, percentual calculado pelo backend,
  histórico); arredondamento só no rótulo (meio-par) e só para menos casas;
- unidades: número com `%`/pontos percentuais só casa com percentual dos fatos, e número sem `%` não casa com percentual;
- período: competências citadas precisam estar no contexto (atual, anterior, janela do histórico);
- indicadores: ids de fatos citados existem; afirmação gerada sem fato citado é recusada;
- ausência: fato sem valor aprovado (ausente, lacuna, incompleto, indisponível, incompatível) não pode ganhar número e a
  afirmação que o cita precisa declarar a ausência;
- direção/tendência: "aumento"/"redução" e "favorável"/"desfavorável" coerentes com a variação e a direção declarada;
- afirmações sem evidência: causas, remediação/remoção, maturidade, risco de negócio e absolutos;
- tamanho do campo de destino; padrões sensíveis (e-mail, URL, identificadores, segredos).
Bloqueio (`blocker`) impede aprovação; aviso (`warning`) fica visível ao revisor.
"""
from __future__ import annotations

import re
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

from app.interpretation.contracts import Budget, Context, Origin, Statement
from app.presentations.document import ITEM_MAX

VALIDATOR_VERSION = 'f08-val-1'
MONTHS = {'janeiro': 1, 'fevereiro': 2, 'março': 3, 'abril': 4, 'maio': 5, 'junho': 6, 'julho': 7, 'agosto': 8,
          'setembro': 9, 'outubro': 10, 'novembro': 11, 'dezembro': 12}
_ISO = re.compile(r'\b(20\d{2})-(0[1-9]|1[0-2])\b')
_BR = re.compile(r'\b(0?[1-9]|1[0-2])/(20\d{2})\b')
_NAMED = re.compile(r'\b(' + '|'.join(MONTHS) + r')\s+(?:de\s+)?(20\d{2})\b', re.I)
_ORDINAL = re.compile(r'\b(\d{1,2})\s?[ºª°]')
_NUMBER = re.compile(r'(?<![\w.,])(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+))?(?![\w])'
                     r'(\s*%|\s*p\.\s?p\.|\s+pontos?\s+percentuais)?')
_SENSITIVE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+|https?://\S+|www\.\S+|\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-'
                        r'[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b|\b[0-9a-fA-F]{24,}\b|[A-Za-z0-9+/=_-]{40,}')
_ABSENCE = re.compile(r'sem valor aprovado|não é interpretad|não interpretad|lacuna|indisponív|incomplet|'
                      r'incompatív|ausente|não reconhecid', re.I)
_UP = re.compile(r'\b(aument\w*|cresc\w*|subi[ru]\w*|elev\w*|alta de)\b', re.I)
_DOWN = re.compile(r'\b(redu\w*|diminu\w*|caiu|caíram|queda\w*|recuou|recuaram)\b', re.I)
_STABLE = re.compile(r'\b(estáve\w*|estável|manteve|mantém|inalterad\w*|sem variação)\b', re.I)
_GOOD = re.compile(r'\b(favorável|melhor\w*|melhora\w*)\b', re.I)
_BAD = re.compile(r'\b(desfavorável|pior\w*)\b', re.I)
_NEGATED = re.compile(r'\b(não|sem|nenhum\w*)\b[^.;]{0,60}$', re.I)

# Afirmações que exigem evidência fora dos indicadores (nunca inferidas dos números).
CLAIMS: dict[str, re.Pattern] = {
    'causal': re.compile(r'\b(porque|pois|devido|em raz[ãa]o d[eoa]s?|em virtude|gra[çc]as a|causad\w*|provocad\w*|'
                         r'motivad\w*|decorr\w*|resultado d[eoa]s?|em fun[çc][ãa]o d[eoa]s?|por conta d[eoa]s?|'
                         r'deve-se|atribu[íi]\w*|ocasionad\w*|consequ[êe]ncia d[eoa]s?)\b', re.I),
    'remediation': re.compile(r'\b(corrigid\w*|remediad\w*|resolvid\w*|sanad\w*|mitigad\w*|eliminad\w*|'
                              r'zerad\w*|tratad[oa]s)\b', re.I),
    'removal': re.compile(r'\b(removid\w*|descontinuad\w*|desativad\w*|desligad\w*|retirad[oa]s? d[oa]s? escopo)\b',
                          re.I),
    'maturity': re.compile(r'\b(maturidade|amadurec\w*|cultura de seguran[çc]a|evolu[çc][ãa]o do programa)\b', re.I),
    'business_risk': re.compile(r'\b(risco (?:de|ao|para o) neg[óo]cio|impacto financeiro|preju[íi]zo|multa\w*|'
                                r'vazamento|viola[çc][ãa]o de dados|ataque\w*|explora[çcd]\w*|invas[ãa]o)\b', re.I),
    'absolute': re.compile(r'\b(garant\w*|certamente|sem d[úu]vida|comprova(?:damente)?|definitivamente|'
                           r'totalmente seguro|livre de vulnerabilidades|sempre|nunca|imune)\b', re.I),
}
CLAIM_LABEL = {'causal': 'causa atribuída', 'remediation': 'remediação/correção afirmada',
               'removal': 'remoção de aplicação afirmada', 'maturity': 'ganho de maturidade afirmado',
               'business_risk': 'risco de negócio específico', 'absolute': 'afirmação categórica'}
# Indicador cujo próprio nome é sobre resolução: citar "resolvidos" com ele é evidência.
_RESOLUTION_METRICS = ('sast.policy.resolved_in_period',)


def _dec(v) -> Decimal | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return abs(Decimal(str(v)))
    except InvalidOperation:
        return None


def _add(target: set[Decimal], *values) -> None:
    for v in values:
        d = _dec(v)
        if d is not None:
            target.add(d)


def allowed_numbers(f: dict) -> tuple[set[Decimal], set[Decimal]]:
    """(números sem unidade de percentual, percentuais) que uma afirmação pode citar a partir de um fato."""
    counts: set[Decimal] = set()
    pcts: set[Decimal] = set()
    t = f['type']
    if t == 'period':
        for lbl in [*f['window'], f['previous_competence']]:
            y, m = lbl.split('-')
            _add(counts, int(y), int(m))
        _add(counts, len(f['window']))
        return counts, pcts
    if t == 'editorial':
        nums = [m.group(0) for m in _NUMBER.finditer(f['text'])]
        for n in nums:
            d = _parse(n)
            if d is not None:
                counts.add(d)
                pcts.add(d)
        return counts, pcts
    is_pct = f['value_type'] == 'percentage'
    main = pcts if is_pct else counts
    if f['current']['value'] is not None:
        _add(main, f['current']['value'])
    if f['previous']['value'] is not None:
        _add(main, f['previous']['value'])
    _add(main, f['delta'])
    _add(pcts, f['delta_pct'])
    for s in (f['severity'] or {}).values():
        _add(counts, s['current'], s['previous'], s['delta'])
    for key in ('categories', 'previous_categories'):
        c = f.get(key)
        if c and c.get('recognized'):
            _add(counts, c['items'], c['sum'], c['top3_sum'], *range(1, c['items'] + 1))
            _add(pcts, c['top3_share_pct'])
            for r in c['rows']:
                _add(counts, r['value'])
                _add(pcts, r['share_pct'])
    h = f.get('history')
    if h:
        _add(main, *[s['value'] for s in h['series']], h['min'], h['max'])
        _add(counts, h['months_with_value'], len(h['gaps']), len(h['series']))
    return counts, pcts


def _parse(token: str) -> Decimal | None:
    m = _NUMBER.match(token.strip())
    if not m:
        return None
    whole = m.group(1).replace('.', '')
    return Decimal(f'{whole}.{m.group(2)}' if m.group(2) else whole)


def _matches(token: Decimal, decimals: int, candidates: set[Decimal]) -> bool:
    if token in candidates:
        return True
    q = Decimal(1).scaleb(-decimals)  # rótulo com MENOS casas que o fato: arredondamento meio-par, como na IR
    return any(c.quantize(q, rounding=ROUND_HALF_EVEN) == token for c in candidates)


def _labels(facts: list[dict]) -> list[str]:
    out = []
    for f in facts:
        if f['type'] != 'metric':
            continue
        out.append(f['name'])
        for key in ('categories', 'previous_categories'):
            c = f.get(key)
            if c and c.get('recognized'):
                out += [r['label'] for r in c['rows'] if r['label']]
    return sorted(set(out), key=len, reverse=True)


def _periods(text: str) -> list[str]:
    out = [f'{y}-{m}' for y, m in _ISO.findall(text)]
    out += [f'{y}-{int(m):02d}' for m, y in _BR.findall(text)]
    out += [f'{y}-{MONTHS[m.lower()]:02d}' for m, y in _NAMED.findall(text)]
    return out


def _strip_periods(text: str) -> str:
    for rx in (_NAMED, _ISO, _BR):
        text = rx.sub(' ', text)
    return text


def _issue(level: str, code: str, message: str, index: int | None = None, token: str | None = None) -> dict:
    out = {'level': level, 'code': code, 'message': message, 'statement': index}
    if token is not None:
        out['token'] = token
    return out


def _check_statement(i: int, st: Statement, facts: dict[str, dict], periods_ok: set[str], years_ok: set[int],
                     origin: Origin, justification: str | None) -> tuple[list[dict], int, int]:
    issues: list[dict] = []
    cited = [facts[fid] for fid in st.fact_ids if fid in facts]
    for fid in st.fact_ids:
        if fid not in facts:
            issues.append(_issue('blocker', 'unknown_fact', f'Fato citado inexistente no contexto: {fid}', i, fid))
    metrics = [f for f in cited if f['type'] == 'metric']
    editorial = any(f['type'] == 'editorial' for f in cited)
    text = st.text

    # período
    periods = _periods(text)
    for p in periods:
        if p not in periods_ok:
            issues.append(_issue('blocker', 'period_not_in_context', f'Competência citada fora do contexto: {p}', i, p))

    # números (sem rótulos de categoria, nomes de indicadores, competências, ordinais e ids de indicador)
    clean = _strip_periods(text)
    for lbl in _labels(cited):
        clean = clean.replace(lbl, ' ')
    clean = re.sub(r'\[[a-z0-9_.]+\]', ' ', clean)
    for m in _ORDINAL.finditer(clean):
        if int(m.group(1)) > 10:
            issues.append(_issue('blocker', 'unverified_number', f'Posição {m.group(0)} sem fato', i, m.group(0)))
    clean = _ORDINAL.sub(' ', clean)
    counts: set[Decimal] = set()
    pcts: set[Decimal] = set()
    for f in cited:
        c, p = allowed_numbers(f)
        counts |= c
        pcts |= p
    n_numbers = 0
    for m in _NUMBER.finditer(clean):
        n_numbers += 1
        tok = m.group(0).strip()
        value = _parse(m.group(0))
        decimals = len(m.group(2) or '')
        is_pct = bool(m.group(3))
        if not cited:
            issues.append(_issue('blocker', 'uncited_number', f'Número sem fato citado: {tok}', i, tok))
            continue
        if value is not None and value.to_integral_value() == value and int(value) in years_ok and not is_pct:
            continue  # ano de competência do contexto
        if is_pct:
            if _matches(value, decimals, pcts):
                continue
            code = 'unit_mismatch' if _matches(value, decimals, counts) else 'unverified_number'
        else:
            if _matches(value, decimals, counts):
                continue
            code = 'unit_mismatch' if _matches(value, decimals, pcts) else 'unverified_number'
        msg = (f'Unidade incoerente: {tok} (percentual × contagem)' if code == 'unit_mismatch'
               else f'Número não encontrado nos fatos citados: {tok}')
        issues.append(_issue('blocker', code, msg, i, tok))

    # ausência de valor aprovado
    if origin is Origin.GENERATED:
        missing = [f for f in metrics if not f['definitive']]
        if missing and not _ABSENCE.search(text):
            issues.append(_issue('blocker', 'missing_value_not_declared',
                                 'Afirmação cita indicador sem valor aprovado sem declarar a ausência: '
                                 + ', '.join(f['metric_id'] for f in missing), i))
        if missing and len(missing) == len(metrics) and n_numbers and not any(f['type'] == 'period' for f in cited):
            issues.append(_issue('blocker', 'number_for_missing_value',
                                 'Número atribuído a indicador sem valor aprovado', i))
        if not st.fact_ids:
            issues.append(_issue('blocker', 'statement_without_evidence', 'Afirmação gerada sem fato citado', i))

    # direção da variação e tendência (só quando a afirmação trata de UM indicador e não fala de severidades)
    if len(metrics) == 1 and 'severidade' not in text.lower():
        f = metrics[0]
        d = f['delta']
        up, down, stable = bool(_UP.search(text)), bool(_DOWN.search(text)), bool(_STABLE.search(text))
        if d is not None:
            if (d > 0 and down and not up) or (d < 0 and up and not down) or (d == 0 and (up or down) and not stable):
                issues.append(_issue('blocker', 'direction_mismatch', 'Sentido da variação incoerente com os fatos '
                                                                     f'({f["metric_id"]}: {f["delta_label"] or "0"})', i))
        good = [m for m in _GOOD.finditer(text) if not _NEGATED.search(text[:m.start()])]
        bad = [m for m in _BAD.finditer(text) if not _NEGATED.search(text[:m.start()])]
        trend = f['trend']
        if (good and trend != 'improvement' and not bad) or (bad and trend != 'worsening' and not good):
            issues.append(_issue('blocker', 'trend_not_proven', 'Melhora/piora afirmada sem tendência comprovada '
                                                               f'({f["metric_id"]}: {trend})', i))

    # afirmações sem evidência
    for cat, rx in CLAIMS.items():
        hit = rx.search(text)
        if not hit:
            continue
        if cat == 'remediation' and any(f['metric_id'] in _RESOLUTION_METRICS for f in metrics):
            continue
        if editorial:
            issues.append(_issue('warning', 'claim_from_operator_note', f'{CLAIM_LABEL[cat]} apoiada em nota '
                                 f'editorial do operador: "{hit.group(0)}"', i, hit.group(0)))
        elif origin is Origin.EDITED and justification:
            issues.append(_issue('warning', 'claim_justified_by_editor', f'{CLAIM_LABEL[cat]} mantida com '
                                 f'justificativa declarada: "{hit.group(0)}"', i, hit.group(0)))
        else:
            issues.append(_issue('blocker', f'unsupported_{cat}_claim', f'{CLAIM_LABEL[cat]} sem evidência nos fatos: '
                                 f'"{hit.group(0)}" — use linguagem neutra e proponha investigação', i, hit.group(0)))

    if _SENSITIVE.search(text):
        issues.append(_issue('blocker', 'sensitive_data', 'Texto com padrão sensível (e-mail, URL, identificador ou '
                                                          'segredo)', i))
    return issues, n_numbers, len(periods)


def validate(ctx: Context, statements: list[Statement], *, origin: Origin, budget: Budget,
             justification: str | None = None) -> dict:
    facts = {f['id']: f for f in ctx.facts}
    window = set(ctx.history_window) | {ctx.previous_competence, ctx.competence}
    years = {int(lbl[:4]) for lbl in window}
    issues: list[dict] = []
    n_numbers = n_periods = 0
    if not statements or not any(s.text.strip() for s in statements):
        issues.append(_issue('blocker', 'empty_text', 'Texto vazio'))
    for i, st in enumerate(statements):
        found, nn, np_ = _check_statement(i, st, facts, window, years, origin, justification)
        issues += found
        n_numbers += nn
        n_periods += np_
    # tamanho no campo de destino
    texts = [s.text for s in statements]
    if budget.field == 'items':
        if len(texts) > budget.max_items:
            issues.append(_issue('blocker', 'too_many_items', f'{len(texts)} tópicos (máximo {budget.max_items} neste '
                                                              'slide)'))
        for i, t in enumerate(texts):
            if len(t) > min(budget.item_chars, ITEM_MAX):
                issues.append(_issue('blocker', 'too_long', f'Tópico com {len(t)} caracteres (máximo '
                                                            f'{budget.item_chars} neste slide)', i))
    else:
        total = len(join(texts, budget.field))
        if total > budget.max_chars:
            issues.append(_issue('blocker', 'too_long', f'Texto com {total} caracteres (máximo {budget.max_chars} '
                                                        'neste slide; a exportação também bloqueia cortes)'))
    # valores manuais: a origem manual precisa estar declarada em algum ponto do texto que cita o fato
    manual = [f for f in facts.values() if f['type'] == 'metric' and f['origin'] == 'MANUAL' and f['definitive']]
    disclosed = any('manual' in s.text.lower() for s in statements)
    for f in manual:
        citing = [s.text for s in statements if f['id'] in s.fact_ids and _NUMBER.search(_strip_periods(s.text))]
        if citing and not disclosed:
            issues.append(_issue('warning', 'manual_not_disclosed', f'{f["metric_id"]}: valor manual aprovado citado '
                                                                    'sem indicar a origem manual'))
    blockers = sum(1 for x in issues if x['level'] == 'blocker')
    return {'validator_version': VALIDATOR_VERSION, 'valid': blockers == 0, 'blockers': blockers,
            'warnings': sum(1 for x in issues if x['level'] == 'warning'), 'issues': issues,
            'checked': {'statements': len(statements), 'numbers': n_numbers, 'periods': n_periods,
                        'facts': len(facts)}}


def join(texts: list[str], field: str) -> str:
    return '\n'.join(texts) if field == 'items' else ' '.join(texts)
