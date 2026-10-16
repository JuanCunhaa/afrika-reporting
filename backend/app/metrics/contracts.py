"""Contratos tipados dos indicadores (F04). Enums impedem valores livres inconsistentes.

Um indicador = contrato (o que é, de onde vem, como filtra, deduplica e arredonda) + resultado de uma execução
(status, valor, motivos, temporalidade e proveniência). Zero ≠ ausente: valor só existe com status VALIDATED;
em INCOMPLETE os agregados observados ficam em `partial` (nunca apresentados como definitivos).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class MetricStatus(StrEnum):
    VALIDATED = 'VALIDATED'      # coleta completa, contrato atendido: valor publicável (zero é legítimo)
    INCOMPLETE = 'INCOMPLETE'    # coleta parcial, limite excedido, indeterminados ou identidade não comprovada
    UNAVAILABLE = 'UNAVAILABLE'  # pré-condição ausente (escopo/conexão/credencial) ou histórico não reconstruível
    UNSUPPORTED = 'UNSUPPORTED'  # fonte/API não homologada ou incapaz de sustentar o indicador
    FAILED = 'FAILED'            # erro da fonte impediu qualquer resultado


class Domain(StrEnum):
    APPLICATIONS = 'applications'
    SAST = 'sast'
    SCA = 'sca'
    SCANS = 'scans'
    LICENSES = 'licenses'


class Source(StrEnum):
    APPLICATIONS_API = 'Veracode Applications API 1.0'
    FINDINGS_API = 'Veracode Findings API 2.1'
    SUMMARY_REPORT_API = 'Veracode Summary Report API v2'
    SCA_AGENT_API = 'Veracode SCA Agent API 3.0'
    REPORTING_API = 'Veracode Reporting API 1.12 (POST + GET — bloqueada pela política GET-only)'
    NONE = 'nenhuma fonte homologada'


class ScanContext(StrEnum):
    POLICY = 'POLICY'                    # produção (convenção do produto)
    SANDBOX = 'SANDBOX'                  # desenvolvimento (convenção do produto)
    POLICY_AND_SANDBOX = 'POLICY_AND_SANDBOX'
    NOT_APPLICABLE = 'NOT_APPLICABLE'


class ScanType(StrEnum):
    STATIC = 'STATIC'
    SCA = 'SCA'
    NOT_APPLICABLE = 'NOT_APPLICABLE'


class TemporalMode(StrEnum):
    CURRENT_STATE = 'CURRENT_STATE'              # estado no momento da coleta (NÃO é o fechamento da competência)
    EVENT_IN_PERIOD = 'EVENT_IN_PERIOD'          # eventos cuja data cai dentro da competência
    STATE_AT_PERIOD_END = 'STATE_AT_PERIOD_END'  # estado no fechamento: exige histórico (snapshot aprovado, F05)


class DateField(StrEnum):
    NONE = 'NONE'
    FIRST_FOUND_DATE = 'finding_status.first_found_date'
    SCAN_PUBLISHED_DATE = 'applications[].scans[].modified_date (publicação do ÚLTIMO scan do tipo)'
    RESOLUTION_DATE = 'resolution_date (inexistente na Findings API)'


class StatusCriterion(StrEnum):
    NOT_APPLICABLE = 'NOT_APPLICABLE'
    # status OPEN e mitigação NÃO aprovada (resolution_status != APPROVED)
    OPEN_EXCLUDING_APPROVED_MITIGATIONS = 'OPEN_EXCLUDING_APPROVED_MITIGATIONS'
    ANY_STATUS = 'ANY_STATUS'
    # contagem do Summary Report do build mais recente (definição Veracode; tratamento de mitigados não documentado)
    SUMMARY_REPORT_LATEST_BUILD = 'SUMMARY_REPORT_LATEST_BUILD'
    PUBLISHED_SCAN = 'PUBLISHED_SCAN'


class SeverityCriterion(StrEnum):
    NOT_APPLICABLE = 'NOT_APPLICABLE'
    ALL_0_TO_5 = 'ALL_0_TO_5'  # 5 Very High … 0 Informational; ausente => UNKNOWN (torna INCOMPLETE)


class Dedup(StrEnum):
    APPLICATION_GUID = 'APPLICATION_GUID'
    # issue_id é "único dentro do contexto da aplicação" (especificação) => válido dentro de UM contexto
    APP_CONTEXT_ISSUE_ID = 'APP_CONTEXT_ISSUE_ID'
    # mesma aplicação + issue_id em contextos diferentes: identidade NÃO garantida pela especificação
    APP_ISSUE_ID_ACROSS_CONTEXTS = 'APP_ISSUE_ID_ACROSS_CONTEXTS'
    # SCA: mesma aplicação + component_id + identificador da vulnerabilidade, entre contextos
    APP_COMPONENT_VULNERABILITY_ACROSS_CONTEXTS = 'APP_COMPONENT_VULNERABILITY_ACROSS_CONTEXTS'
    NONE = 'NONE'


class IdentityProof(StrEnum):
    NOT_REQUIRED = 'NOT_REQUIRED'     # sem deduplicação entre contextos
    DOCUMENTED = 'DOCUMENTED'         # garantida pela especificação oficial
    NOT_PROVEN = 'NOT_PROVEN'         # candidata; sem prova => indicador não passa de INCOMPLETE
    VERIFIED_REAL = 'VERIFIED_REAL'   # comprovada contra dados reais (homologação)


class Unit(StrEnum):
    APPLICATIONS = 'applications'
    FINDINGS = 'findings'
    LINES_OF_CODE = 'lines_of_code'
    COMPONENTS = 'components'
    PROJECTS = 'projects'


class Shape(StrEnum):
    SCALAR = 'SCALAR'
    BY_SEVERITY = 'BY_SEVERITY'
    BREAKDOWN = 'BREAKDOWN'
    RANKING = 'RANKING'


class Support(StrEnum):
    SUPPORTED = 'SUPPORTED'
    SUPPORT_NOT_VERIFIED = 'SUPPORT_NOT_VERIFIED'  # endpoint documentado; suporte do contexto não homologado
    UNSUPPORTED = 'UNSUPPORTED'


class Homologation(StrEnum):
    NOT_VERIFIED = 'NOT_VERIFIED'                    # nenhuma comparação real com o dashboard
    FORMAT_VERIFIED_REAL = 'FORMAT_VERIFIED_REAL'    # formato/campos conferidos na API real; valor não comparado
    MATCHES_DASHBOARD = 'MATCHES_DASHBOARD'          # correspondência comprovada com o dashboard
    DEFINITION_DIVERGENCE = 'DEFINITION_DIVERGENCE'  # diverge por definição (documentada)
    SOURCE_NOT_HOMOLOGATED = 'SOURCE_NOT_HOMOLOGATED'


class Direction(StrEnum):
    """Direção desejável da variação (F06C). Metadado de APRESENTAÇÃO: não altera definição, cálculo nem valor do
    indicador — por isso não muda `version`. Padrão NEUTRAL: sem declaração, a variação nunca é colorida como melhora
    ou piora (não se presume que reduzir é bom nem que aumentar é ruim)."""
    LOWER_IS_BETTER = 'LOWER_IS_BETTER'
    HIGHER_IS_BETTER = 'HIGHER_IS_BETTER'
    NEUTRAL = 'NEUTRAL'


SEVERITY_LABELS = {5: 'VERY_HIGH', 4: 'HIGH', 3: 'MEDIUM', 2: 'LOW', 1: 'VERY_LOW', 0: 'INFORMATIONAL'}


@dataclass(frozen=True)
class MetricContract:
    metric_id: str
    version: int
    name: str
    description: str
    domain: Domain
    source: Source
    endpoint: str | None
    context: ScanContext
    scan_type: ScanType
    temporal_mode: TemporalMode
    date_field: DateField
    status_criterion: StatusCriterion
    severity_criterion: SeverityCriterion
    dedup: Dedup
    identity_proof: IdentityProof
    unit: Unit
    shape: Shape
    formula: str
    support: Support = Support.SUPPORTED
    homologation: Homologation = Homologation.NOT_VERIFIED
    application_scope: str = ('Aplicações do escopo `applications` do dono (F03): universo do cliente; subcliente '
                              'na mesma conexão = critérios ∩ universo; conexão própria = só o próprio tenant')
    rounding: str = 'inteiro (contagem; sem arredondamento)'
    top_n: int | None = None
    completeness_rules: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    unsupported_reason: str | None = None
    desired_direction: Direction = Direction.NEUTRAL  # F06C: ver Direction (metadado de apresentação)
    direction_rationale: str | None = None

    def public(self) -> dict[str, Any]:
        out = asdict(self)
        out['completeness_rules'] = list(self.completeness_rules)
        out['limitations'] = list(self.limitations)
        return out


@dataclass(frozen=True)
class Reason:
    code: str
    message: str

    def as_dict(self) -> dict:
        return {'code': self.code, 'message': self.message}


@dataclass
class MetricResult:
    """Resultado de um indicador numa execução. Serializável e autocontido (base do snapshot da F05)."""
    metric_id: str
    contract_version: int
    status: MetricStatus
    value: Any = None            # só quando VALIDATED
    partial: Any = None          # agregados observados quando INCOMPLETE (não definitivos)
    reasons: list[Reason] = field(default_factory=list)
    coverage: dict = field(default_factory=dict)
    filters: dict = field(default_factory=dict)
    temporal: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.status != MetricStatus.VALIDATED and self.value is not None:
            raise ValueError('valor só pode existir em indicador VALIDATED')
        if self.status not in (MetricStatus.INCOMPLETE,) and self.partial is not None:
            raise ValueError('agregado parcial só existe em INCOMPLETE')

    def as_dict(self) -> dict:
        return {'metric_id': self.metric_id, 'contract_version': self.contract_version, 'status': self.status.value,
                'publishable': self.status == MetricStatus.VALIDATED, 'value': self.value, 'partial': self.partial,
                'reasons': [r.as_dict() for r in self.reasons], 'coverage': self.coverage,
                'filters': self.filters, 'temporal': self.temporal}
