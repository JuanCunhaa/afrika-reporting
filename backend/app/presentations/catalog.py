"""Catálogo de tipos de slide (F06A + F06B): componentes DISPONÍVEIS, não slides obrigatórios.

Cada tipo declara layouts, campos editoriais, campos obrigatórios, quantos indicadores aceita, de que tipos de valor
(F05) e quais opções. Nenhum tipo guarda números: indicadores entram só por `metric_id` e o valor vem sempre de uma
revisão APROVADA (ver `view.py`).

F06B: `section` (divisor de seção) e `dashboard` (painel composto). O painel tem layouts formados por ZONAS tipadas
(faixa de KPIs, cartões com variação, cartões de severidade, rosca, gráfico, comparação, ranking, tabela e texto);
cada zona recebe seus próprios indicadores no documento (`zones`). As posições padrão das zonas são frações da área de
conteúdo (valem para qualquer tema); o tema pode fixar caixas absolutas (`theme.dashboards`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
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
    SECTION = 'section'
    DASHBOARD = 'dashboard'


# Tipos com número principal ("headline", F05): contagem, decimal, percentual e total por severidade.
HEADLINE_TYPES = (ValueType.COUNT, ValueType.DECIMAL, ValueType.PERCENTAGE, ValueType.BY_SEVERITY)
# Tipos com categorias desenháveis em barras (adaptador explícito por indicador em `charts.py`).
CATEGORY_TYPES = (ValueType.BREAKDOWN, ValueType.RANKING, ValueType.BY_SEVERITY)
ALL_TYPES = tuple(ValueType)

EDITORIAL_FIELDS = ('title', 'subtitle', 'body', 'items', 'chart_title', 'legend_title', 'caption', 'notes')
OPTION_NAMES = ('months', 'data_mode', 'show_legend', 'show_values', 'show_presenters', 'top_n')


# ---------------------------------------------------------------- zonas do painel composto (F06B)

class ZoneKind(StrEnum):
    KPI_BAND = 'kpi_band'          # faixa com números principais
    KPI_CARDS = 'kpi_cards'        # cartões com número principal e variação vs. competência anterior
    SEVERITY_CARDS = 'severity_cards'  # cartões por severidade (um indicador por severidade)
    DONUT = 'donut'                # rosca por severidade
    CHART = 'chart'                # barras/linhas/combinado (série mensal) ou barras por categoria
    COMPARISON = 'comparison'      # mês atual × anterior
    RANKING = 'ranking'            # ranking aprovado (ordem da fonte)
    TABLE = 'table'                # tabela de indicadores
    TEXT = 'text'                  # texto editorial (corpo ou tópicos do slide)


@dataclass(frozen=True)
class ZoneSpec:
    kind: ZoneKind
    name: str
    min_metrics: int
    max_metrics: int
    value_types: tuple[ValueType, ...] = ()
    frac: tuple[float, float, float, float] = (0, 0, 1, 1)  # x, y, w, h como fração da área de conteúdo
    text_field: str | None = None  # zonas de texto: 'body' ou 'items'
    charts: tuple[str, ...] = ()   # zonas de gráfico: 'bar', 'line', 'combo'

    def public(self, zone_id: str) -> dict:
        return {'zone': zone_id, 'kind': self.kind.value, 'name': self.name, 'min_metrics': self.min_metrics,
                'max_metrics': self.max_metrics, 'value_types': [v.value for v in self.value_types],
                'frac': list(self.frac), 'text_field': self.text_field, 'charts': list(self.charts)}


_SEV = (ValueType.BY_SEVERITY,)
_HEAD = HEADLINE_TYPES
_CHART_TYPES = (*CATEGORY_TYPES, *HEADLINE_TYPES[:3])

DASHBOARD_LAYOUTS: dict[str, dict[str, ZoneSpec]] = {
    'painel-kpis': {
        'band': ZoneSpec(ZoneKind.KPI_BAND, 'Faixa de indicadores', 1, 4, _HEAD, (0, 0, 1, 0.19)),
        'cards': ZoneSpec(ZoneKind.KPI_CARDS, 'Cartões com variação', 1, 4, _HEAD, (0, 0.24, 1, 0.33)),
        'table': ZoneSpec(ZoneKind.TABLE, 'Tabela de indicadores', 1, 6, ALL_TYPES, (0, 0.62, 0.56, 0.38)),
        'text': ZoneSpec(ZoneKind.TEXT, 'Comentário', 0, 0, (), (0.58, 0.62, 0.42, 0.38), text_field='body'),
    },
    'painel-graficos': {
        'band': ZoneSpec(ZoneKind.KPI_BAND, 'Destaques', 1, 3, _HEAD, (0.27, 0, 0.46, 0.24)),
        'list': ZoneSpec(ZoneKind.TEXT, 'Tópicos', 0, 0, (), (0, 0.32, 0.45, 0.28), text_field='items'),
        'donut_a': ZoneSpec(ZoneKind.DONUT, 'Rosca A', 1, 1, _SEV, (0.5, 0.31, 0.24, 0.3)),
        'donut_b': ZoneSpec(ZoneKind.DONUT, 'Rosca B', 1, 1, _SEV, (0.76, 0.31, 0.24, 0.3)),
        'detail': ZoneSpec(ZoneKind.COMPARISON, 'Comparação', 1, 4, _HEAD, (0, 0.65, 0.44, 0.35)),
        'chart': ZoneSpec(ZoneKind.CHART, 'Série mensal', 1, 2, _HEAD, (0.47, 0.65, 0.53, 0.35),
                          charts=('combo', 'bar', 'line')),
    },
    'painel-grupos': {
        'group_a': ZoneSpec(ZoneKind.KPI_BAND, 'Grupo A', 1, 3, _HEAD, (0, 0, 0.48, 0.3)),
        'group_b': ZoneSpec(ZoneKind.KPI_BAND, 'Grupo B', 1, 3, _HEAD, (0.52, 0, 0.48, 0.3)),
        'list': ZoneSpec(ZoneKind.TEXT, 'Tópicos', 0, 0, (), (0, 0.35, 0.45, 0.45), text_field='items'),
        'detail': ZoneSpec(ZoneKind.COMPARISON, 'Comparação', 1, 4, _HEAD, (0.47, 0.35, 0.53, 0.2)),
        'chart': ZoneSpec(ZoneKind.CHART, 'Gráfico', 1, 2, _CHART_TYPES, (0.47, 0.57, 0.53, 0.43),
                          charts=('bar', 'line', 'combo')),
    },
    'painel-severidades': {
        'group_a': ZoneSpec(ZoneKind.SEVERITY_CARDS, 'Severidades A', 1, 1, _SEV, (0, 0, 0.48, 0.34)),
        'group_b': ZoneSpec(ZoneKind.SEVERITY_CARDS, 'Severidades B', 1, 1, _SEV, (0.52, 0, 0.48, 0.34)),
        'detail': ZoneSpec(ZoneKind.COMPARISON, 'Comparação', 1, 4, _HEAD, (0, 0.4, 0.45, 0.45)),
        'list': ZoneSpec(ZoneKind.TEXT, 'Tópicos', 0, 0, (), (0.52, 0.4, 0.48, 0.45), text_field='items'),
    },
    'painel-tabela-grafico': {
        'table': ZoneSpec(ZoneKind.RANKING, 'Ranking', 1, 1, (ValueType.RANKING,), (0, 0, 1, 0.46)),
        'notes': ZoneSpec(ZoneKind.TEXT, 'Observações', 0, 0, (), (0, 0.52, 0.48, 0.48), text_field='items'),
        'chart': ZoneSpec(ZoneKind.CHART, 'Gráfico', 1, 1, _CHART_TYPES, (0.52, 0.52, 0.48, 0.48),
                          charts=('bar', 'line')),
    },
    'painel-destaque-tabela': {
        'highlight': ZoneSpec(ZoneKind.KPI_BAND, 'Destaque', 0, 1, _HEAD, (0, 0, 1, 0.24)),
        'table': ZoneSpec(ZoneKind.RANKING, 'Ranking', 1, 1, (ValueType.RANKING,), (0.2, 0.3, 0.6, 0.7)),
    },
}


def zone_compatible(spec: ZoneSpec, metric_id: str, chart: str | None = None, data_mode: str | None = None) -> bool:
    vt = metric_value_type(metric_id)
    if vt is None or vt not in spec.value_types:
        return False
    if spec.kind is ZoneKind.CHART:
        history = chart in ('line', 'combo') or data_mode == 'history'
        return vt in HEADLINE_TYPES if history else vt in CATEGORY_TYPES
    return True


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
    zones: dict[str, dict[str, ZoneSpec]] = field(default_factory=dict)  # layouts de painel composto

    def public(self) -> dict:
        out = {'type': self.type.value, 'name': self.name, 'description': self.description,
               'layouts': list(self.layouts), 'default_layout': self.layouts[0],
               'editable_fields': list(self.editable_fields), 'required_fields': list(self.required_fields),
               'min_metrics': self.min_metrics, 'max_metrics': self.max_metrics,
               'value_types': [v.value for v in self.value_types], 'options': list(self.options),
               'chart': self.chart}
        if self.zones:
            out['zones'] = {lay: [z.public(zid) for zid, z in zs.items()] for lay, zs in self.zones.items()}
        return out


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
    SlideTypeSpec(SlideType.KPIS, 'KPIs principais', 'Cartões (ou faixa) com o número principal de até 6 '
                  'indicadores.', ('kpi-grid', 'kpi-band'), _TEXT, ('title',), 1, 6, HEADLINE_TYPES, chart='kpi'),
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
                  'Informativa, Desconhecida) de um indicador por severidade: barras, cartões ou rosca.',
                  ('chart-full', 'chart-with-text', 'severity-cards', 'donut'),
                  _CHART_TEXT, ('title',), 1, 1, (ValueType.BY_SEVERITY,), ('show_values', 'show_legend'),
                  chart='severity'),
    SlideTypeSpec(SlideType.TOP10_RANKING, 'Ranking Top 10', 'Ranking aprovado (até 10 itens, ordem da fonte).',
                  ('ranking-table', 'ranking-bars'), _CHART_TEXT, ('title',), 1, 1, (ValueType.RANKING,),
                  ('top_n', 'show_values'), chart='ranking'),
    SlideTypeSpec(SlideType.METRIC_TABLE, 'Tabela de indicadores', 'Valor, estado, origem e fonte de até 12 '
                  'indicadores.', ('table',), _TEXT, ('title',), 1, 12, ALL_TYPES, chart='table'),
    SlideTypeSpec(SlideType.RECOMMENDATIONS, 'Recomendações e observações', 'Tópicos e texto editoriais (sem '
                  'números de indicadores). Matriz: cada tópico é uma linha "Rótulo | coluna 1 | coluna 2 | …"; o '
                  'primeiro tópico é o cabeçalho.', ('bullets', 'two-columns', 'matrix'),
                  ('title', 'subtitle', 'body', 'items', 'notes'), ('title',), 0, 0, ()),
    SlideTypeSpec(SlideType.CLOSING, 'Encerramento', 'Agradecimento, contato e apresentadores.', ('closing',),
                  ('title', 'subtitle', 'body', 'items', 'notes'), ('title',), 0, 0, (), ('show_presenters',)),
    SlideTypeSpec(SlideType.SECTION, 'Divisor de seção', 'Abertura de seção com título grande e sobretítulo '
                  '(ex.: número da seção); sem indicadores.', ('section',), ('title', 'subtitle', 'notes'),
                  ('title',), 0, 0, ()),
    SlideTypeSpec(SlideType.DASHBOARD, 'Painel composto', 'Vários componentes no mesmo slide, em zonas definidas '
                  'pelo layout; cada zona tem seus indicadores aprovados (faixa de KPIs, cartões com variação, '
                  'severidades, rosca, gráfico, comparação, ranking, tabela) ou texto editorial.',
                  tuple(DASHBOARD_LAYOUTS), ('title', 'subtitle', 'body', 'items', 'caption', 'notes'), ('title',),
                  0, 0, (), zones=DASHBOARD_LAYOUTS),
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
        if any(vt in z.value_types for zs in DASHBOARD_LAYOUTS.values() for z in zs.values()):
            slide_types.append(SlideType.DASHBOARD.value)
        metrics.append({'metric_id': mid, 'name': c.name, 'contract_version': c.version, 'value_type': vt.value,
                        'unit': c.unit.value, 'support': c.support.value, 'slide_types': slide_types,
                        'desired_direction': c.desired_direction.value})
    return {'slide_types': [s.public() for s in SLIDE_TYPES.values()], 'metrics': metrics,
            'editorial_fields': list(EDITORIAL_FIELDS), 'options': list(OPTION_NAMES),
            'zone_kinds': [k.value for k in ZoneKind]}
