"""Contexto fundamentado da interpretação (F08): seleção de indicadores por slide/tipo e fatos determinísticos.

Fontes permitidas (e únicas): as revisões APROVADAS fixadas na revisão da apresentação (principal + histórico), lidas
pelos MESMOS resolvedores da visualização (`view.resolve`) e pela MESMA regra de variação da IR (`charts.comparison`).
Nada é consultado na Veracode, nada é gravado e nenhum número é estimado: variação percentual só entre aprovados
comparáveis com anterior ≠ 0; lacuna/ausente/incompleto vira fato SEM número.

Privacidade: rótulos de categorias só entram para estruturas sem identificação (status de conformidade, mês, tipo de
dependência, CWE, cobertura). Rankings e distribuições por aplicação, BU, Team, componente ou vulnerabilidade entram
SEM rótulos (posição e valor). O nome do cliente/subcliente não entra no contexto.
"""
from __future__ import annotations

import json
from decimal import ROUND_HALF_EVEN, Decimal

from sqlalchemy.orm import Session

from app.errors import ApiError, conflict
from app.interpretation.contracts import (
    KINDS_BY_SLIDE, PROMPT_VERSION, TARGET_FIELDS, Budget, Context, Kind, Level, budget_for, default_target,
)
from app.metrics.registry import REGISTRY
from app.orm import Competence, Presentation, PresentationRevision, PresentationTemplate
from app.presentations import charts, view
from app.presentations.catalog import DASHBOARD_LAYOUTS, HEADLINE_TYPES, SLIDE_TYPES, ZoneKind, metric_value_type
from app.presentations.document import Document, Slide, all_metrics, contract_versions
from app.presentations.templates import definition_of
from app.snapshots import history

# Estruturas cujos rótulos não identificam aplicação, pessoa, unidade, componente ou vulnerabilidade.
LABEL_SAFE = frozenset({'apps.by_policy_compliance', 'sast.policy.open.by_first_found_month',
                        'sca.policy.open.by_dependency_mode', 'sast.policy.open.by_cwe', 'scans.covered_apps'})
MAX_METRICS = 10
_HEADLINE = {v.value for v in HEADLINE_TYPES}

RULES = (
    'Use somente os fatos fornecidos; cite os ids dos fatos usados em cada afirmação.',
    'Não calcule números novos: use apenas valores, variações e percentuais presentes nos fatos.',
    'Não atribua causas a variações; quando a causa não estiver nos fatos, use linguagem neutra e proponha '
    'investigação.',
    'Não afirme remediação, correção, remoção de aplicações, ganho de maturidade nem risco de negócio específico sem '
    'fato que o comprove.',
    'Fatos sem valor aprovado (ausente, lacuna, incompleto, indisponível, incompatível) não têm número: declare a '
    'ausência, nunca um valor.',
    'Não use nomes de aplicações, pessoas, unidades, componentes ou vulnerabilidades.',
    'Respeite o limite de tamanho do campo de destino.',
)


def pct(numerator: int | float, denominator: int | float) -> float:
    """Percentual com 1 casa (meio-par) — mesma regra de rótulo da IR. Só chamado com denominador ≠ 0."""
    q = (Decimal(str(numerator)) / Decimal(str(denominator)) * 100).quantize(Decimal('0.1'), rounding=ROUND_HALF_EVEN)
    return float(q)


def fmt_pct(value: float) -> str:
    return charts.fmt(value, 'percentage')


def _text_zone_field(slide: Slide) -> str | None:
    for zid, spec in DASHBOARD_LAYOUTS.get(slide.layout, {}).items():
        if spec.kind is ZoneKind.TEXT:
            return spec.text_field
    return None


def target_of(slide: Slide, requested: str | None = None) -> tuple[str, Budget]:
    spec = SLIDE_TYPES[slide.type]
    field = requested or default_target(slide.type, slide.layout, _text_zone_field(slide))
    if field is None or field not in TARGET_FIELDS or field not in spec.editable_fields \
            or (slide.type.value == 'dashboard' and field in ('body', 'items') and field != _text_zone_field(slide)):
        raise ApiError(422, 'interpretation_target_not_supported',
                       'Este slide/layout não tem campo editorial que exiba a interpretação',
                       [{'field': 'target_field', 'message': f'{slide.slide_id}: {field or "nenhum"}',
                         'type': 'target_not_supported'}])
    return field, budget_for(slide.type, slide.layout, field)


# ---------------------------------------------------------------- seleção de indicadores

def _is_headline(mid: str) -> bool:
    vt = metric_value_type(mid)
    return vt is not None and vt.value in _HEADLINE


def select_metrics(kind: Kind, slide: Slide, doc: Document, snapshot_ids: list[str]) -> list[str]:
    own = all_metrics(slide)
    doc_ids = [m for s in doc.slides for m in all_metrics(s)]
    pool = list(dict.fromkeys([*own, *doc_ids, *snapshot_ids]))
    directional = [m for m in pool if m in REGISTRY and REGISTRY[m].desired_direction.value != 'NEUTRAL']
    if kind in (Kind.CHART_EXPLANATION, Kind.RANKING_HIGHLIGHTS):
        out = own
    elif kind is Kind.PERIOD_COMPARISON:
        out = [m for m in own if _is_headline(m)] or [m for m in dict.fromkeys(doc_ids) if _is_headline(m)]
    elif kind is Kind.EXECUTIVE_SUMMARY:
        out = [m for m in dict.fromkeys([*own, *doc_ids]) if _is_headline(m)]
    elif kind in (Kind.IMPROVEMENTS, Kind.ATTENTION_POINTS):
        out = [*directional, *[m for m in dict.fromkeys([*own, *doc_ids]) if _is_headline(m)]]
    elif kind is Kind.SAST_TRENDS:
        out = [m for m in pool if m.startswith('sast.') and _is_headline(m)]
    elif kind is Kind.SCA_TRENDS:
        out = [m for m in pool if m.startswith('sca.') and _is_headline(m)]
    elif kind is Kind.COMPLIANCE_EVOLUTION:
        out = ['apps.by_policy_compliance', 'apps.total']
    elif kind is Kind.SCAN_COVERAGE_EVOLUTION:
        out = ['scans.covered_apps', 'scans.count', 'apps.total']
    else:  # TECHNICAL_RECOMMENDATIONS
        out = [*directional, *[m for m in ('scans.covered_apps', 'apps.by_policy_compliance') if m in pool]]
    out = list(dict.fromkeys(m for m in out if m in REGISTRY))[:MAX_METRICS]
    if not out:
        raise ApiError(422, 'interpretation_no_metrics', 'Não há indicadores aprovados aplicáveis a esta '
                                                        'interpretação neste slide',
                       [{'field': 'kind', 'message': kind.value, 'type': 'no_metrics'}])
    return out


# ---------------------------------------------------------------- fatos

def _prov(p: dict) -> dict:
    a = p.get('approval') or {}
    return {'competence': p.get('competence'), 'revision': a.get('revision'), 'approval_sequence': a.get('sequence'),
            'content_hash': a.get('content_hash'), 'contract_version': p.get('contract_version'),
            'origin': p.get('origin'), 'source_name': p.get('source_name')}


def _side(p: dict) -> dict:
    vt = p.get('value_type') or 'count'
    y = p['headline'] if p['state'] == 'VALUE' else None
    return {'competence': p['competence'], 'state': p['state'], 'value_state': p.get('value_state'),
            'origin': p.get('origin'), 'value': y, 'label': None if y is None else charts.fmt(y, vt)}


def _categories(mid: str, p: dict) -> dict | None:
    if p['state'] != 'NOT_NUMERIC':
        return None
    try:
        cats = charts.categories_of(mid, p['value'])
    except charts.StructureError:
        return {'recognized': False}
    total = sum(c['y'] for c in cats)
    safe = mid in LABEL_SAFE
    rows = [{'position': i + 1, 'label': c['label'] if safe or c.get('aggregate') else None, 'value': c['y'],
             'share_pct': pct(c['y'], total) if total else None, 'aggregate': bool(c.get('aggregate'))}
            for i, c in enumerate(cats)]
    top3 = sum(c['y'] for c in cats[:3] if not c.get('aggregate'))
    return {'recognized': True, 'labels_redacted': not safe, 'items': len(cats), 'sum': total, 'rows': rows,
            'top3_sum': top3, 'top3_share_pct': pct(top3, total) if total else None}


def _severity(cur: dict, prev: dict, comparable: bool) -> dict | None:
    if cur['state'] != 'VALUE' or cur.get('value_type') != 'by_severity':
        return None
    out = {}
    for k in charts.SEVERITY_ORDER:
        c = cur['value'][k]
        p = prev['value'][k] if comparable else None
        out[k] = {'label': charts.SEVERITY_LABEL[k], 'current': c, 'previous': p,
                  'delta': None if p is None else c - p}
    return out


def _history(entries: dict, labels: list[str], mid: str, versions: list[int]) -> dict:
    pts = [view.resolve(entries, lbl, mid, versions) for lbl in labels]
    series = [{'competence': lbl, 'state': p['state'], 'value': p['headline'] if p['state'] == 'VALUE' else None}
              for lbl, p in zip(labels, pts)]
    values = [s for s in series if s['value'] is not None]
    return {'window': [labels[0], labels[-1]], 'series': series, 'months_with_value': len(values),
            'gaps': [s['competence'] for s in series if s['state'] == 'GAP'],
            'without_value': [s['competence'] for s in series if s['state'] not in ('VALUE', 'GAP')],
            'min': min((s['value'] for s in values), default=None),
            'max': max((s['value'] for s in values), default=None),
            'first': values[0] if values else None, 'last': values[-1] if values else None}


def metric_fact(fid: str, mid: str, entries: dict, label: str, prev_label: str, labels: list[str],
                versions: list[int]) -> dict:
    c = REGISTRY[mid]
    cur = view.resolve(entries, label, mid, versions)
    prev = view.resolve(entries, prev_label, mid, versions)
    row = charts.comparison([(cur, prev)])['rows'][0]
    vt = cur.get('value_type') or metric_value_type(mid).value
    delta = row['delta']
    delta_pct = None
    reason = row['delta_unavailable_reason']
    if delta is not None:
        if prev['headline'] == 0:
            reason = 'previous_zero'
        else:
            delta_pct = pct(delta, prev['headline'])
    comparable = cur['state'] == prev['state'] == 'VALUE' and cur.get('contract_version') == prev.get(
        'contract_version') and cur.get('value_type') == prev.get('value_type')
    cats = _categories(mid, cur)
    prev_cats = _categories(mid, prev) if cats and cur.get('contract_version') == prev.get('contract_version') else None
    return {
        'id': fid, 'type': 'metric', 'metric_id': mid, 'name': c.name, 'unit': c.unit.value,
        'unit_label': charts.unit_label(c.unit.value), 'value_type': vt,
        'desired_direction': c.desired_direction.value, 'state': cur['state'], 'value_state': cur.get('value_state'),
        'origin': cur.get('origin'), 'definitive': cur['state'] in ('VALUE', 'NOT_NUMERIC')
        and cur.get('value_state') in ('VALIDATED', 'MANUAL'),
        'current': _side(cur), 'previous': _side(prev),
        'delta': delta, 'delta_label': row['delta_label'], 'delta_pct': delta_pct,
        'delta_pct_label': None if delta_pct is None else fmt_pct(abs(delta_pct)),
        'delta_unavailable_reason': reason, 'trend': row['trend'], 'trend_reason': row['trend_reason'],
        'severity': _severity(cur, prev, comparable),
        'categories': cats, 'previous_categories': prev_cats,
        'history': _history(entries, labels, mid, versions) if _is_headline(mid) else None,
        'provenance': {'current': _prov(cur), 'previous': _prov(prev)},
    }


def build(session: Session, p: Presentation, r: PresentationRevision, slide_id: str, kind: Kind, level: Level,
          notes: list[str], target_field: str | None = None) -> tuple[Context, dict]:
    """(contexto, metadados do destino). Recusa fontes com referência quebrada e slide/tipo não aplicáveis."""
    tmpl = session.get(PresentationTemplate, p.template_id)
    defn = definition_of(tmpl)
    doc = Document.model_validate(json.loads(r.document_json))
    sources = json.loads(r.sources_json)
    entries, problems = view.load_entries(session, sources)
    if problems:
        raise conflict('interpretation_sources_broken', 'Fontes aprovadas fixadas inconsistentes: '
                                                        + '; '.join(problems))
    slide = next((s for s in doc.slides if s.slide_id == slide_id), None)
    if slide is None:
        raise ApiError(404, 'interpretation_slide_not_found', 'Slide inexistente na revisão da apresentação')
    allowed = KINDS_BY_SLIDE.get(slide.type, ())
    if kind not in allowed:
        raise ApiError(422, 'interpretation_kind_not_applicable', 'Tipo de interpretação não aplicável a este slide',
                       [{'field': 'kind', 'message': f'{slide.type.value}: {", ".join(k.value for k in allowed) or "nenhum"}',
                         'type': 'kind_not_applicable'}])
    field, budget = target_of(slide, target_field)
    comp = session.get(Competence, p.competence_id)
    label = comp.label
    prev_label = view.shift(label, -1)
    months = (slide.options.months or 6) if slide.type.value in ('line_chart', 'bar_chart') else 6
    labels = history.month_range(view.shift(label, -(months - 1)), label)
    primary = entries.get(label)
    snapshot_ids = [] if primary is None else [s.metric_id for s in primary[1].snapshots]
    metrics = select_metrics(kind, slide, doc, snapshot_ids)
    facts = [metric_fact(f'M{i + 1}', m, entries, label, prev_label, labels, contract_versions(defn, m))
             for i, m in enumerate(metrics)]
    facts.append({'id': 'P1', 'type': 'period', 'competence': label, 'previous_competence': prev_label,
                  'window': labels, 'approved_months': [lbl for lbl in labels if lbl in entries]})
    facts += [{'id': f'E{i + 1}', 'type': 'editorial', 'text': n} for i, n in enumerate(notes)]
    ctx = Context(prompt_version=PROMPT_VERSION, kind=kind, level=level, competence=label,
                  previous_competence=prev_label, history_window=labels,
                  slide={'slide_id': slide.slide_id, 'type': slide.type.value, 'layout': slide.layout,
                         'target_field': field, 'budget': {'max_chars': budget.max_chars, 'max_items': budget.max_items,
                                                           'item_chars': budget.item_chars}},
                  facts=facts, rules=list(RULES))
    return ctx, {'slide': slide, 'field': field, 'budget': budget, 'competence': comp,
                 'severity_labels': doc.severity_labels}
