"""Catálogo de tipos de slide (F06A): componentes DISPONÍVEIS, não slides obrigatórios.

Cada tipo declara layouts, campos editoriais, campos obrigatórios, quantos indicadores aceita, de que tipos de valor
(F05) e quais opções. Nenhum tipo guarda números: indicadores entram só por `metric_id` e o valor vem sempre de uma
revisão APROVADA (ver `view.py`).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.metrics.registry import REGISTRY
from app.orm import ValueType
from app.snapshots.values import value_type_for


class SlideType(StrEnum):
    COVER = 'cover'
    EXECUTIVE_SUMMARY = 'executive_summary'
    KPIS = 'kpis'
    MONTH_COMPARISON = 'month_comparison'
    BAR_CHART = 'bar_chart'
    LINE_CHART = 'line_chart'
    SEVERITY_DISTRIBUTION = 'severity_distribution'
    TOP10_RANKING = 'top10_ranking'
    METRIC_TABLE = 'metric_table'
    RECOMMENDATIONS = 'recommendations'
    CLOSING = 'closing'


# Tipos com número principal ("headline", F05): contagem, decimal, percentual e total por severidade.
HEADLINE_TYPES = (ValueType.COUNT, ValueType.DECIMAL, ValueType.PERCENTAGE, ValueType.BY_SEVERITY)
# Tipos com categorias desenháveis em barras (adaptador explícito por indicador em `charts.py`).
CATEGORY_TYPES = (ValueType.BREAKDOWN, ValueType.RANKING, ValueType.BY_SEVERITY)
ALL_TYPES = tuple(ValueType)

EDITORIAL_FIELDS = ('title', 'subtitle', 'body', 'items', 'chart_title', 'legend_title', 'caption', 'notes')
OPTION_NAMES = ('months', 'data_mode', 'show_legend', 'show_values', 'show_presenters', 'top_n')


@dataclass(frozen=True)
class SlideTypeSpec:
    type: SlideType
    name: str
    description: str
    layouts: tuple[str, ...]
    editable_fields: tuple[str, ...]
    required_fields: tuple[str, ...]
    min_metrics: int
    max_metrics: int
    value_types: tuple[ValueType, ...]
    options: tuple[str, ...] = ()
    chart: str | None = None  # tipo de IR produzido (charts.py)

    def public(self) -> dict:
        return {'type': self.type.value, 'name': self.name, 'description': self.description,
                'layouts': list(self.layouts), 'default_layout': self.layouts[0],
                'editable_fields': list(self.editable_fields), 'required_fields': list(self.required_fields),
                'min_metrics': self.min_metrics, 'max_metrics': self.max_metrics,
                'value_types': [v.value for v in self.value_types], 'options': list(self.options),
                'chart': self.chart}


_TEXT = ('title', 'subtitle', 'caption', 'notes')
_CHART_TEXT = ('title', 'chart_title', 'legend_title', 'caption', 'notes', 'body')

SLIDE_TYPES: dict[SlideType, SlideTypeSpec] = {s.type: s for s in (
    SlideTypeSpec(SlideType.COVER, 'Capa', 'Título, subtítulo, dono e competência (vindos da revisão aprovada) e '
                  'apresentadores.', ('cover',), ('title', 'subtitle', 'notes'), ('title',), 0, 0, (),
                  ('show_presenters',)),
    SlideTypeSpec(SlideType.EXECUTIVE_SUMMARY, 'Sumário executivo', 'Texto livre e tópicos com até 4 destaques '
                  'numéricos de indicadores aprovados.', ('text-with-highlights', 'text-only'),
                  ('title', 'subtitle', 'body', 'items', 'caption', 'notes'), ('title',), 0, 4, HEADLINE_TYPES,
                  chart='kpi'),
    SlideTypeSpec(SlideType.KPIS, 'KPIs principais', 'Cartões com o número principal de até 6 indicadores.',
                  ('kpi-grid',), _TEXT, ('title',), 1, 6, HEADLINE_TYPES, chart='kpi'),
    SlideTypeSpec(SlideType.MONTH_COMPARISON, 'Mês atual × anterior', 'Comparação com a competência anterior '
                  'aprovada; variação só entre aprovados comparáveis.', ('comparison-table', 'comparison-cards'),
                  (*_TEXT, 'chart_title'), ('title',), 1, 6, HEADLINE_TYPES, chart='comparison'),
    SlideTypeSpec(SlideType.BAR_CHART, 'Gráfico de barras', 'Barras por categoria (distribuição/ranking/severidade '
                  'da competência) ou por mês (série histórica aprovada).', ('chart-full', 'chart-with-text'),
                  _CHART_TEXT, ('title',), 1, 1, (*CATEGORY_TYPES, *HEADLINE_TYPES[:3]),
                  ('data_mode', 'months', 'show_values', 'show_legend'), chart='bar'),
    SlideTypeSpec(SlideType.LINE_CHART, 'Linhas / série histórica', 'Até 4 séries mensais (6 ou 12 meses) só de '
                  'competências aprovadas; lacunas aparecem como lacunas.', ('chart-full', 'chart-with-text'),
                  _CHART_TEXT, ('title',), 1, 4, HEADLINE_TYPES, ('months', 'show_values', 'show_legend'),
                  chart='line'),
    SlideTypeSpec(SlideType.SEVERITY_DISTRIBUTION, 'Distribuição por severidade', 'Severidades (Muito alta … '
                  'Informativa, Desconhecida) de um indicador por severidade.', ('chart-full', 'chart-with-text'),
                  _CHART_TEXT, ('title',), 1, 1, (ValueType.BY_SEVERITY,), ('show_values', 'show_legend'),
                  chart='severity'),
    SlideTypeSpec(SlideType.TOP10_RANKING, 'Ranking Top 10', 'Ranking aprovado (até 10 itens, ordem da fonte).',
                  ('ranking-table', 'ranking-bars'), _CHART_TEXT, ('title',), 1, 1, (ValueType.RANKING,),
                  ('top_n', 'show_values'), chart='ranking'),
    SlideTypeSpec(SlideType.METRIC_TABLE, 'Tabela de indicadores', 'Valor, estado, origem e fonte de até 12 '
                  'indicadores.', ('table',), _TEXT, ('title',), 1, 12, ALL_TYPES, chart='table'),
    SlideTypeSpec(SlideType.RECOMMENDATIONS, 'Recomendações e observações', 'Tópicos e texto editoriais (sem '
                  'números de indicadores).', ('bullets', 'two-columns'), ('title', 'subtitle', 'body', 'items',
                                                                          'notes'), ('title',), 0, 0, ()),
    SlideTypeSpec(SlideType.CLOSING, 'Encerramento', 'Agradecimento, contato e apresentadores.', ('closing',),
                  ('title', 'subtitle', 'body', 'notes'), ('title',), 0, 0, (), ('show_presenters',)),
)}


def metric_value_type(metric_id: str) -> ValueType | None:
    c = REGISTRY.get(metric_id)
    return None if c is None else value_type_for(c)


def compatible(spec: SlideTypeSpec, metric_id: str, data_mode: str | None = None) -> bool:
    """O indicador pode alimentar este tipo de slide? (barras por mês exigem número principal)."""
    vt = metric_value_type(metric_id)
    if vt is None or vt not in spec.value_types:
        return False
    if spec.type is SlideType.BAR_CHART:
        return vt in HEADLINE_TYPES if data_mode == 'history' else vt in CATEGORY_TYPES
    return True


def public_catalog() -> dict:
    metrics = []
    for mid, c in REGISTRY.items():
        vt = value_type_for(c)
        slide_types = [s.type.value for s in SLIDE_TYPES.values()
                       if compatible(s, mid) or (s.type is SlideType.BAR_CHART and compatible(s, mid, 'history'))]
        metrics.append({'metric_id': mid, 'name': c.name, 'contract_version': c.version, 'value_type': vt.value,
                        'unit': c.unit.value, 'support': c.support.value, 'slide_types': slide_types})
    return {'slide_types': [s.public() for s in SLIDE_TYPES.values()], 'metrics': metrics,
            'editorial_fields': list(EDITORIAL_FIELDS), 'options': list(OPTION_NAMES)}
