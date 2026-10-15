"""Representação intermediária (IR) de gráficos — independente do renderizador (HTML hoje; PPTX/PDF na F07).

Contrato (ver `docs/PRESENTATION_CONTRACTS.md`):
- Consome SOMENTE pontos resolvidos de revisões aprovadas (`view.py`). Nenhum número é calculado, interpolado,
  somado ou inferido aqui: `y` é exatamente o número aprovado (ou o total por severidade/contagem já gravado).
- Ausência nunca vira zero: `y = None` com `state` (GAP, MISSING, NOT_NUMERIC, INCOMPATIBLE, NOT_APPLICABLE).
- Cores são tokens do tema (`series.N`, `severity.X`); o renderizador resolve. Cor fixa por série (ordem de
  vinculação), nunca por posição no ranking.
- Rótulos formatados em pt-BR com regra de arredondamento por tipo de valor; o número bruto é preservado.
- Estruturas de distribuição/ranking só são lidas por adaptador EXPLÍCITO por indicador; estrutura não reconhecida
  => gráfico indisponível com motivo (nunca adivinhar campos).
"""
from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from app.presentations.themes import SERIES_TOKENS

IR_VERSION = 1
SEVERITY_ORDER = ('VERY_HIGH', 'HIGH', 'MEDIUM', 'LOW', 'VERY_LOW', 'INFORMATIONAL', 'UNKNOWN')
SEVERITY_LABEL = {'VERY_HIGH': 'Muito alta', 'HIGH': 'Alta', 'MEDIUM': 'Média', 'LOW': 'Baixa',
                  'VERY_LOW': 'Muito baixa', 'INFORMATIONAL': 'Informativa', 'UNKNOWN': 'Desconhecida'}
UNIT_LABEL = {'applications': 'aplicações', 'findings': 'findings', 'lines_of_code': 'linhas de código',
              'components': 'componentes', 'projects': 'projetos'}

# Arredondamento por tipo de valor: contagens são inteiras (sem arredondamento); decimais e percentuais só são
# arredondados no RÓTULO (meio-par), nunca no valor.
NUMBER_FORMATS = {
    'count': {'decimals': 0, 'rounding': 'NONE', 'suffix': ''},
    'by_severity': {'decimals': 0, 'rounding': 'NONE', 'suffix': ''},
    'breakdown': {'decimals': 0, 'rounding': 'NONE', 'suffix': ''},
    'ranking': {'decimals': 0, 'rounding': 'NONE', 'suffix': ''},
    'decimal': {'decimals': 2, 'rounding': 'HALF_EVEN', 'suffix': ''},
    'percentage': {'decimals': 1, 'rounding': 'HALF_EVEN', 'suffix': '%'},
}

STATE_LABEL = {'GAP': 'lacuna', 'MISSING': 'ausente', 'NOT_NUMERIC': 'sem número', 'INCOMPATIBLE': 'incompatível',
               'NOT_APPLICABLE': '—'}

# Adaptadores explícitos (metric_id -> lista, campos do rótulo, campo do valor, colunas extras).
_CATEGORY_ADAPTERS: dict[str, dict] = {
    'apps.by_business_unit': {'list': 'items', 'label': ('name', 'business_unit_id'), 'value': 'applications'},
    'apps.by_team': {'list': 'items', 'label': ('name', 'team_id'), 'value': 'applications'},
    'apps.by_policy_compliance': {'list': 'items', 'label': ('status',), 'value': 'applications'},
    'sast.policy.open.by_first_found_month': {'list': 'items', 'label': ('month',), 'value': 'findings'},
    'sca.policy.open.by_dependency_mode': {'list': 'items', 'label': ('mode',), 'value': 'findings'},
    'sast.policy.open.by_cwe': {'list': 'top', 'label': ('cwe',), 'value': 'findings', 'others': 'others'},
    'sast.policy.open.top_applications': {'list': 'top', 'label': ('name', 'application_guid'), 'value': 'findings'},
    'sca.policy.open.top_components': {'list': 'top', 'label': ('component',), 'value': 'findings',
                                       'extra': (('applications', 'Aplicações'),)},
    'sca.policy.open.top_vulnerabilities': {'list': 'top', 'label': ('vulnerability_id',), 'value': 'applications',
                                            'extra': (('findings', 'Findings'), ('max_severity', 'Severidade máx.'))},
}
_FIXED_KEYS: dict[str, tuple[tuple[str, str], ...]] = {
    'scans.covered_apps': (('covered', 'Cobertas'), ('not_covered', 'Não cobertas'),
                           ('indeterminate', 'Indeterminadas')),
}


class StructureError(ValueError):
    """Valor aprovado sem a estrutura esperada pelo adaptador do indicador."""


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def fmt(value: Any, value_type: str) -> str:
    """Formatação pt-BR (milhar '.', decimal ','). Não altera o valor; só o rótulo."""
    if not _is_number(value):
        return '—'
    spec = NUMBER_FORMATS.get(value_type, NUMBER_FORMATS['count'])
    if spec['decimals'] == 0 and float(value).is_integer():
        text = f'{int(value):,}'.replace(',', '.')
    else:
        q = Decimal(str(value)).quantize(Decimal(1).scaleb(-max(spec['decimals'], 1)), rounding=ROUND_HALF_EVEN)
        whole, _, frac = f'{q:f}'.partition('.')
        sign = '-' if whole.startswith('-') else ''
        whole = f'{int(whole.lstrip("-")):,}'.replace(',', '.')
        text = f'{sign}{whole},{frac}' if frac else f'{sign}{whole}'
    return text + spec['suffix']


def number_format(value_type: str) -> dict:
    return {'locale': 'pt-BR', **NUMBER_FORMATS.get(value_type, NUMBER_FORMATS['count'])}


def unit_label(unit: str | None) -> str:
    return UNIT_LABEL.get(unit or '', unit or '')


# ---------------------------------------------------------------- pontos

def point(p: dict, x: str) -> dict:
    """Ponto da IR a partir de um ponto resolvido (view.resolve). `y` só existe com valor numérico aprovado."""
    state = p['state']
    y = p['headline'] if state == 'VALUE' else None
    return {'x': x, 'y': y, 'state': state, 'label': fmt(y, p.get('value_type') or 'count') if y is not None
            else STATE_LABEL.get(state, '—'), 'value_state': p.get('value_state'), 'origin': p.get('origin'),
            'competence': p.get('competence'), 'metric_id': p['metric_id']}


def _ref(p: dict) -> dict:
    a = p.get('approval') or {}
    return {'metric_id': p['metric_id'], 'competence': p.get('competence'), 'revision': a.get('revision'),
            'approval_sequence': a.get('sequence'), 'content_hash': a.get('content_hash')}


def unavailable(kind: str, reason: str, message: str, title: str | None = None) -> dict:
    return {'ir_version': IR_VERSION, 'kind': kind, 'available': False, 'title': title, 'reason': reason,
            'message': message}


def _base(kind: str, title: str | None, refs: list[dict]) -> dict:
    return {'ir_version': IR_VERSION, 'kind': kind, 'available': True, 'title': title, 'data_refs': refs,
            'warnings': []}


# ---------------------------------------------------------------- KPIs, comparação e tabela

def kpis(points: list[dict], title: str | None = None) -> dict:
    out = _base('kpi', title, [_ref(p) for p in points])
    out['items'] = [{**point(p, p['metric_id']), 'name': p['name'], 'unit': p.get('unit'),
                     'unit_label': unit_label(p.get('unit')), 'value_type': p.get('value_type')} for p in points]
    return out


def _signed(delta: int | float, value_type: str) -> str:
    return ('+' if delta > 0 else '−' if delta < 0 else '') + fmt(abs(delta), value_type)


def comparison(pairs: list[tuple[dict, dict]], title: str | None = None) -> dict:
    """Mês atual × anterior. Variação só quando ambos aprovados, numéricos, mesmo tipo e versão de contrato."""
    rows, refs = [], []
    for cur, prev in pairs:
        refs += [_ref(cur), _ref(prev)]
        delta, reason = None, None
        if cur['state'] == 'GAP' or prev['state'] == 'GAP':
            reason = 'gap'
        elif cur['state'] != 'VALUE' or prev['state'] != 'VALUE':
            reason = 'no_numeric_value'
        elif cur.get('value_type') != prev.get('value_type'):
            reason = 'value_type_changed'
        elif cur.get('contract_version') != prev.get('contract_version'):
            reason = 'contract_version_changed'
        else:
            delta = cur['headline'] - prev['headline']
        vt = cur.get('value_type') or 'count'
        rows.append({'metric_id': cur['metric_id'], 'name': cur['name'], 'unit_label': unit_label(cur.get('unit')),
                     'current': point(cur, cur.get('competence')), 'previous': point(prev, prev.get('competence')),
                     'delta': delta, 'delta_label': None if delta is None else _signed(delta, vt),
                     'delta_unavailable_reason': reason})
    out = _base('comparison', title, refs)
    out['rows'] = rows
    out['current_competence'] = pairs[0][0].get('competence') if pairs else None
    out['previous_competence'] = pairs[0][1].get('competence') if pairs else None
    return out


def table(points: list[dict], title: str | None = None) -> dict:
    out = _base('table', title, [_ref(p) for p in points])
    out['columns'] = [{'key': 'name', 'label': 'Indicador'}, {'key': 'value', 'label': 'Valor'},
                      {'key': 'value_state', 'label': 'Estado'}, {'key': 'origin', 'label': 'Origem'},
                      {'key': 'source', 'label': 'Fonte'}]
    out['rows'] = [{'metric_id': p['metric_id'], 'name': p['name'], 'state': p['state'],
                    'value': fmt(p['headline'], p.get('value_type') or 'count') if p['state'] == 'VALUE'
                    else (p.get('summary') or STATE_LABEL.get(p['state'], '—')),
                    'y': p['headline'] if p['state'] == 'VALUE' else None,
                    'unit_label': unit_label(p.get('unit')), 'value_state': p.get('value_state'),
                    'origin': p.get('origin'), 'source': p.get('source_name')} for p in points]
    return out


# ---------------------------------------------------------------- séries mensais

def monthly(kind: str, series_points: list[list[dict]], labels: list[str], title: str | None = None, *,
            legend_title: str | None = None, show_legend: bool = True) -> dict:
    """Linhas (até 4 séries) ou barras por mês. Lacunas preservadas (sem interpolação nem zero)."""
    series, refs, gaps = [], [], set()
    vts = set()
    for i, pts in enumerate(series_points):
        first = pts[0]
        vts.add(first.get('value_type'))
        series.append({'key': first['metric_id'], 'label': first['name'], 'metric_id': first['metric_id'],
                       'color': SERIES_TOKENS[i % len(SERIES_TOKENS)],
                       'points': [point(p, label) for p, label in zip(pts, labels)]})
        refs += [_ref(p) for p in pts if p['state'] != 'GAP']
        gaps |= {p['competence'] for p in pts if p['state'] == 'GAP'}
    vt = next(iter(vts)) if len(vts) == 1 else 'count'
    units = {p.get('unit') for pts in series_points for p in pts[:1]}
    out = _base(kind, title, refs)
    out.update({'x_axis': {'type': 'month', 'label': 'Competência'},
                'y_axis': {'label': unit_label(next(iter(units))) if len(units) == 1 else '', 'min': 0,
                           'integer': vt not in ('decimal', 'percentage')},
                'number_format': number_format(vt), 'categories': labels, 'series': series,
                'legend': {'show': show_legend and len(series) > 1, 'title': legend_title},
                'gaps': sorted(gaps)})
    if len(units) > 1:
        out['warnings'].append({'code': 'mixed_units', 'message': 'Séries com unidades diferentes no mesmo eixo'})
    if any(len({p.get('contract_version') for p in pts if p['state'] == 'VALUE'}) > 1 for pts in series_points):
        out['warnings'].append({'code': 'contract_version_changed',
                                'message': 'Versões de contrato diferentes na série: compare com cautela'})
    return out


# ---------------------------------------------------------------- categorias (distribuição, ranking, severidade)

def _label(row: dict, fields: tuple[str, ...]) -> str:
    if fields == ('cwe',):
        if not _is_number(row.get('cwe_id')):
            raise StructureError('cwe_id')
        return f"CWE-{row['cwe_id']}" + (f" {row['name']}" if row.get('name') else '')
    if fields == ('component',):
        name = row.get('filename') or row.get('component_id')
        if not name:
            raise StructureError('component')
        return f"{name} {row['version']}" if row.get('version') else str(name)
    for f in fields:
        if isinstance(row.get(f), str) and row[f].strip():
            return row[f]
    raise StructureError('label')


def categories_of(metric_id: str, value: Any) -> list[dict]:
    """[{label, y, extra}] na ORDEM da fonte. Levanta StructureError se o valor não tiver a forma esperada."""
    if metric_id in _FIXED_KEYS:
        if not isinstance(value, dict):
            raise StructureError('object')
        out = []
        for key, label in _FIXED_KEYS[metric_id]:
            if not _is_number(value.get(key)):
                raise StructureError(key)
            out.append({'label': label, 'y': value[key], 'extra': {}})
        return out
    adapter = _CATEGORY_ADAPTERS.get(metric_id)
    if adapter is None:
        raise StructureError('no_adapter')
    rows = value.get(adapter['list']) if isinstance(value, dict) else None
    if not isinstance(rows, list):
        raise StructureError(adapter['list'])
    out = []
    for row in rows:
        if not isinstance(row, dict) or not _is_number(row.get(adapter['value'])):
            raise StructureError(adapter['value'])
        extra = {label: row.get(key) for key, label in adapter.get('extra', ()) if key in row}
        out.append({'label': _label(row, adapter['label']), 'y': row[adapter['value']], 'extra': extra})
    others = adapter.get('others')
    if others and _is_number(value.get(others)) and value[others] > 0:
        out.append({'label': 'Outros (fora do top 10)', 'y': value[others], 'extra': {}, 'aggregate': True})
    return out


def severity_categories(value: Any) -> list[dict]:
    if not isinstance(value, dict) or not all(_is_number(value.get(k)) for k in SEVERITY_ORDER):
        raise StructureError('by_severity')
    return [{'label': SEVERITY_LABEL[k], 'key': k, 'y': value[k], 'extra': {}} for k in SEVERITY_ORDER]


def _categorical(kind: str, p: dict, cats: list[dict], title: str | None, *, colors: list[str] | None = None,
                 show_values: bool = True) -> dict:
    out = _base(kind, title, [_ref(p)])
    out.update({'x_axis': {'type': 'category', 'label': ''},
                'y_axis': {'label': unit_label(p.get('unit')), 'min': 0, 'integer': True},
                'number_format': number_format('count'), 'categories': [c['label'] for c in cats],
                'show_values': show_values, 'value_state': p.get('value_state'), 'origin': p.get('origin'),
                'series': [{'key': p['metric_id'], 'label': p['name'], 'metric_id': p['metric_id'],
                            'color': SERIES_TOKENS[0],
                            'points': [{'x': c['label'], 'y': c['y'], 'state': 'VALUE', 'label': fmt(c['y'], 'count'),
                                        'color': None if colors is None else colors[i], 'extra': c.get('extra', {}),
                                        'aggregate': c.get('aggregate', False), 'value_state': p.get('value_state'),
                                        'origin': p.get('origin'), 'competence': p.get('competence'),
                                        'metric_id': p['metric_id']} for i, c in enumerate(cats)]}],
                'legend': {'show': False, 'title': None}, 'gaps': []})
    return out


def _point_unavailable(kind: str, p: dict, title: str | None) -> dict | None:
    if p['state'] in ('GAP', 'MISSING', 'INCOMPATIBLE'):
        return unavailable(kind, p['state'].lower(), {
            'GAP': 'Competência sem revisão aprovada', 'MISSING': 'Indicador sem valor na revisão aprovada',
            'INCOMPATIBLE': 'Versão do contrato do indicador incompatível com o template'}[p['state']], title)
    if p.get('value') is None:
        return unavailable(kind, 'missing', 'Indicador sem valor na revisão aprovada', title)
    return None


def bar_categories(p: dict, title: str | None = None, *, show_values: bool = True) -> dict:
    blocked = _point_unavailable('bar', p, title)
    if blocked:
        return blocked
    try:
        cats = (severity_categories(p['value']) if p.get('value_type') == 'by_severity'
                else categories_of(p['metric_id'], p['value']))
    except StructureError:
        return unavailable('bar', 'unrecognized_structure', 'Estrutura do valor aprovado não reconhecida para '
                                                            'gráfico de barras (nenhum número é presumido)', title)
    if not cats:
        return {**_categorical('bar', p, [], title), 'empty': True}
    return _categorical('bar', p, cats, title, show_values=show_values)


def severity(p: dict, title: str | None = None, *, show_values: bool = True) -> dict:
    blocked = _point_unavailable('severity', p, title)
    if blocked:
        return blocked
    try:
        cats = severity_categories(p['value'])
    except StructureError:
        return unavailable('severity', 'unrecognized_structure', 'Valor aprovado sem as severidades esperadas', title)
    out = _categorical('severity', p, cats, title, colors=[f'severity.{c["key"]}' for c in cats],
                       show_values=show_values)
    total = p['value'].get('total')
    out['total'] = {'y': total, 'label': fmt(total, 'count')} if _is_number(total) else None
    out['legend'] = {'show': True, 'title': None}
    return out


def ranking(p: dict, title: str | None = None, *, top_n: int = 10, show_values: bool = True) -> dict:
    blocked = _point_unavailable('ranking', p, title)
    if blocked:
        return blocked
    try:
        cats = categories_of(p['metric_id'], p['value'])
    except StructureError:
        return unavailable('ranking', 'unrecognized_structure', 'Estrutura do ranking aprovado não reconhecida '
                                                                '(nenhum item é presumido)', title)
    top = [c for c in cats if not c.get('aggregate')][:top_n]
    rest = [c for c in cats if c.get('aggregate')]
    out = _base('ranking', title, [_ref(p)])
    extra_cols = sorted({k for c in top for k in c['extra']})
    out.update({'columns': ['Posição', 'Item', unit_label(p.get('unit')).capitalize() or 'Valor', *extra_cols],
                'rows': [{'rank': i + 1, 'label': c['label'], 'y': c['y'], 'value': fmt(c['y'], 'count'),
                          'extra': c['extra']} for i, c in enumerate(top)],
                'aggregate_rows': [{'label': c['label'], 'y': c['y'], 'value': fmt(c['y'], 'count')} for c in rest],
                'source_order': True, 'show_values': show_values, 'top_n': top_n,
                'max_y': max((c['y'] for c in top), default=0), 'value_state': p.get('value_state'),
                'origin': p.get('origin'), 'color': SERIES_TOKENS[0], 'empty': not top})
    return out
