"""Contratos tipados da interpretação de indicadores (F08).

- Entrada do provedor: `Context` (fatos fundamentados — só valores APROVADOS fixados na revisão da apresentação,
  variações calculadas pelo backend, estados de qualidade e notas editoriais declaradas pelo operador).
- Saída do provedor: `ProviderOutput` = afirmações (`Statement`), cada uma com os fatos que cita. O texto final é a
  junção das afirmações; a validação determinística confere cada afirmação contra os fatos citados.
- Nenhum contrato daqui carrega findings brutos, nomes de aplicações/usuários/BUs/Teams/componentes ou credenciais.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.presentations.catalog import SlideType

PROMPT_VERSION = 'f08-interp-1'
_NO_CONTROL = r'^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]*$'


class Kind(StrEnum):
    EXECUTIVE_SUMMARY = 'EXECUTIVE_SUMMARY'                # resumo executivo do mês
    IMPROVEMENTS = 'IMPROVEMENTS'                          # principais melhorias (comprovadas)
    ATTENTION_POINTS = 'ATTENTION_POINTS'                  # principais pontos de atenção
    SAST_TRENDS = 'SAST_TRENDS'                            # tendências de SAST (histórico aprovado)
    SCA_TRENDS = 'SCA_TRENDS'                              # tendências de SCA (histórico aprovado)
    PERIOD_COMPARISON = 'PERIOD_COMPARISON'                # competência × anterior
    COMPLIANCE_EVOLUTION = 'COMPLIANCE_EVOLUTION'          # conformidade de política
    SCAN_COVERAGE_EVOLUTION = 'SCAN_COVERAGE_EVOLUTION'    # cobertura de scans
    CHART_EXPLANATION = 'CHART_EXPLANATION'                # explicação do gráfico do slide
    RANKING_HIGHLIGHTS = 'RANKING_HIGHLIGHTS'              # destaques do ranking (sem nomes)
    TECHNICAL_RECOMMENDATIONS = 'TECHNICAL_RECOMMENDATIONS'  # recomendações fundamentadas


KIND_NAMES = {
    Kind.EXECUTIVE_SUMMARY: 'Resumo executivo do mês', Kind.IMPROVEMENTS: 'Principais melhorias',
    Kind.ATTENTION_POINTS: 'Principais pontos de atenção', Kind.SAST_TRENDS: 'Tendências de SAST',
    Kind.SCA_TRENDS: 'Tendências de SCA', Kind.PERIOD_COMPARISON: 'Comparação entre competências',
    Kind.COMPLIANCE_EVOLUTION: 'Evolução de conformidade', Kind.SCAN_COVERAGE_EVOLUTION: 'Evolução da cobertura de scans',
    Kind.CHART_EXPLANATION: 'Explicação do gráfico', Kind.RANKING_HIGHLIGHTS: 'Destaques do ranking',
    Kind.TECHNICAL_RECOMMENDATIONS: 'Recomendações técnicas fundamentadas',
}


class Level(StrEnum):
    EXECUTIVE = 'EXECUTIVE'   # objetivo, consultivo, orientado à gestão
    TECHNICAL = 'TECHNICAL'   # detalhado, preciso, métricas e práticas DevSecOps


class Status(StrEnum):
    GENERATED = 'GENERATED'
    IN_REVIEW = 'IN_REVIEW'
    APPROVED = 'APPROVED'
    REJECTED = 'REJECTED'


class Origin(StrEnum):
    GENERATED = 'GENERATED'   # texto do provedor
    EDITED = 'EDITED'         # texto editado por pessoa (autoria declarada)


# ---------------------------------------------------------------- slides de destino e limites

_SUMMARY = (Kind.EXECUTIVE_SUMMARY, Kind.IMPROVEMENTS, Kind.ATTENTION_POINTS, Kind.SAST_TRENDS, Kind.SCA_TRENDS,
            Kind.PERIOD_COMPARISON, Kind.COMPLIANCE_EVOLUTION, Kind.SCAN_COVERAGE_EVOLUTION,
            Kind.TECHNICAL_RECOMMENDATIONS)
_CHART = (Kind.CHART_EXPLANATION, Kind.PERIOD_COMPARISON, Kind.SAST_TRENDS, Kind.SCA_TRENDS)

# Tipos de interpretação aplicáveis por tipo de slide (o primeiro é o padrão). Capa, seção e encerramento não recebem.
KINDS_BY_SLIDE: dict[SlideType, tuple[Kind, ...]] = {
    SlideType.EXECUTIVE_SUMMARY: _SUMMARY,
    SlideType.DASHBOARD: (*_SUMMARY, Kind.CHART_EXPLANATION),
    SlideType.RECOMMENDATIONS: (Kind.TECHNICAL_RECOMMENDATIONS, Kind.ATTENTION_POINTS, Kind.IMPROVEMENTS),
    SlideType.KPIS: (Kind.CHART_EXPLANATION, Kind.PERIOD_COMPARISON),
    SlideType.METRIC_TABLE: (Kind.CHART_EXPLANATION, Kind.PERIOD_COMPARISON),
    SlideType.MONTH_COMPARISON: (Kind.PERIOD_COMPARISON, Kind.CHART_EXPLANATION),
    SlideType.BAR_CHART: _CHART,
    SlideType.LINE_CHART: _CHART,
    SlideType.SEVERITY_DISTRIBUTION: _CHART,
    SlideType.TOP10_RANKING: (Kind.RANKING_HIGHLIGHTS, Kind.CHART_EXPLANATION),
}


@dataclass(frozen=True)
class Budget:
    """Limite de tamanho do texto no campo de destino. `max_chars` vale para o texto inteiro (corpo/legenda) e
    `max_items`/`item_chars` para tópicos. Limites conservadores do espaço visual; a verificação REAL de corte continua
    sendo a do renderizador na exportação (F07), que bloqueia em vez de truncar."""
    field: str
    max_chars: int
    max_items: int = 0
    item_chars: int = 0


# Limites MEDIDOS com o motor real de exportação (F08; afrika@2 nos painéis, neutral-demo nos demais) — o que cabe sem
# corte: painel-graficos 3 tópicos × 150, painel-grupos/painel-severidades 5 × 150, painel-tabela-grafico 6 × 150,
# corpo do painel-kpis ~520, tópicos 8 × 220, duas colunas 8 × 160 (10 × 160 estoura), texto lateral de gráfico ~600
# (800 estoura), legenda 520, sumário 1400+. Os limites abaixo deixam margem (palavras longas quebram antes); a
# exportação continua sendo a verificação final (bloqueia em vez de truncar).
DASHBOARD_ITEMS = {'painel-graficos': (3, 130), 'painel-grupos': (4, 150), 'painel-severidades': (4, 150),
                   'painel-tabela-grafico': (5, 150)}


def budget_for(slide_type: SlideType, layout: str, field: str) -> Budget:
    if field == 'notes':
        return Budget('notes', 3000)
    if field == 'items':
        if slide_type is SlideType.DASHBOARD:
            n, chars = DASHBOARD_ITEMS.get(layout, (3, 130))
            return Budget('items', n * chars, n, chars)
        if layout == 'two-columns':
            return Budget('items', 8 * 160, 8, 160)
        return Budget('items', 8 * 220, 8, 220)
    if field == 'caption':
        return Budget('caption', 240)
    if slide_type is SlideType.DASHBOARD:
        return Budget('body', 420)
    if slide_type is SlideType.EXECUTIVE_SUMMARY:
        return Budget('body', 1400 if layout == 'text-only' else 700)
    if slide_type is SlideType.RECOMMENDATIONS:
        return Budget('body', 900)
    return Budget('body', 500)  # gráfico com texto lateral


def default_target(slide_type: SlideType, layout: str, dashboard_text_field: str | None) -> str | None:
    """Campo editorial que recebe o texto: corpo, tópicos ou legenda (conforme o que o layout exibe no canvas)."""
    if slide_type is SlideType.EXECUTIVE_SUMMARY:
        return 'body'
    if slide_type is SlideType.RECOMMENDATIONS:
        return None if layout == 'matrix' else 'items'
    if slide_type is SlideType.DASHBOARD:
        return dashboard_text_field  # zona de texto do layout (corpo ou tópicos); sem zona de texto => None
    if slide_type in (SlideType.BAR_CHART, SlideType.LINE_CHART, SlideType.SEVERITY_DISTRIBUTION,
                      SlideType.TOP10_RANKING):
        return 'body' if layout == 'chart-with-text' else 'caption'
    if slide_type in (SlideType.KPIS, SlideType.METRIC_TABLE, SlideType.MONTH_COMPARISON):
        return 'caption'
    return None


TARGET_FIELDS = ('body', 'items', 'caption', 'notes')


# ---------------------------------------------------------------- entrada/saída do provedor

class _Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


EditorialText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500,
                                                 pattern=_NO_CONTROL)]


class Context(_Strict):
    """Contexto fundamentado (o ÚNICO material entregue ao provedor)."""
    prompt_version: str = PROMPT_VERSION
    kind: Kind
    level: Level
    language: str = 'pt-BR'
    competence: str
    previous_competence: str
    history_window: list[str]
    slide: dict[str, Any]          # {slide_id, type, layout, target_field, budget}
    facts: list[dict[str, Any]]    # fatos M1.. (indicadores) e E1.. (notas editoriais do operador)
    rules: list[str]


class Statement(_Strict):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1500)]
    fact_ids: list[Annotated[str, StringConstraints(pattern=r'^[A-Z][0-9]{1,3}$')]] = Field(default_factory=list,
                                                                                          max_length=40)


class ProviderOutput(_Strict):
    statements: list[Statement] = Field(min_length=1, max_length=20)
    provider: str
    model: str | None = None
    usage: dict[str, int] = Field(default_factory=dict)
