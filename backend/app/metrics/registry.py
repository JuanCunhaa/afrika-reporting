"""Registro dos indicadores da F04. Identificadores estáveis; mudança de definição => nova `version`.

Lacunas (fonte não homologada ou incapaz) ficam registradas como UNSUPPORTED/UNAVAILABLE com motivo explícito,
para nunca virarem zero ou estimativa.
"""
from __future__ import annotations

from app.metrics.contracts import (
    DateField, Dedup, Domain, Homologation, IdentityProof, MetricContract, ScanContext, ScanType, SeverityCriterion,
    Shape, Source, StatusCriterion, Support, TemporalMode, Unit,
)
from app.veracode import adapters

TOP_N = 10
_APPS_EP = f'GET {adapters.APPLICATIONS}'
_FINDINGS_EP = f'GET {adapters.FINDINGS}'
_SUMMARY_EP = f'GET {adapters.SUMMARY_REPORT}'
_SCA_AGENT_EP = f'GET {adapters.SCA_APP_PROJECTS}'
_REPORTING_EP = 'POST /appsec/v1/analytics/report + GET /appsec/v1/analytics/report/{id}'
_REPORTING_BLOCKED = ('Fonte oficial com o dado (Reporting API), mas a geração do relatório exige POST: bloqueada '
                      'pela política GET-only')

_CURRENT_STATE_NOTE = ('Estado ATUAL na data da coleta: não representa o fechamento da competência; o valor no '
                       'fechamento só existe por snapshot aprovado (F05) ou entrada manual')
_APP_RULES = ('coleta completa das aplicações', 'nenhuma aplicação indeterminada pelas regras de escopo',
              'escopo do dono definido e ativo (nunca o tenant inteiro implícito)')
_FINDING_RULES = _APP_RULES + ('todos os contextos exigidos coletados por completo (paginação, orçamento, prazo)',
                               'severidade presente em todos os findings contados',
                               'status do finding presente em todos os findings avaliados')
_OPEN_NOTE = ('"Aberto" = status OPEN e mitigação não aprovada (resolution_status != APPROVED); equivalência com o '
              'dashboard NÃO verificada')
_ZERO_NOTE = '0 findings pode significar aplicação sem scan no contexto (cobertura de scans não homologada)'
_ISSUE_ID_NOTE = ('issue_id é único "dentro do contexto da aplicação" (especificação): a mesma vulnerabilidade em '
                  'sandboxes/Policy diferentes NÃO tem identidade comprovada')


def _apps(metric_id: str, name: str, description: str, shape: Shape, formula: str, **kw) -> MetricContract:
    return MetricContract(
        metric_id=metric_id, version=1, name=name, description=description, domain=Domain.APPLICATIONS,
        source=Source.APPLICATIONS_API, endpoint=_APPS_EP, context=ScanContext.NOT_APPLICABLE,
        scan_type=ScanType.NOT_APPLICABLE, temporal_mode=TemporalMode.CURRENT_STATE, date_field=DateField.NONE,
        status_criterion=StatusCriterion.NOT_APPLICABLE, severity_criterion=SeverityCriterion.NOT_APPLICABLE,
        dedup=Dedup.APPLICATION_GUID, identity_proof=IdentityProof.NOT_REQUIRED, unit=Unit.APPLICATIONS,
        shape=shape, formula=formula, completeness_rules=_APP_RULES,
        limitations=(_CURRENT_STATE_NOTE,) + kw.pop('limitations', ()), **kw)


def _findings(metric_id: str, name: str, description: str, domain: Domain, context: ScanContext, shape: Shape,
              formula: str, **kw) -> MetricContract:
    defaults = dict(temporal_mode=TemporalMode.CURRENT_STATE, date_field=DateField.NONE,
                    status_criterion=StatusCriterion.OPEN_EXCLUDING_APPROVED_MITIGATIONS,
                    severity_criterion=SeverityCriterion.ALL_0_TO_5, dedup=Dedup.APP_CONTEXT_ISSUE_ID,
                    identity_proof=IdentityProof.NOT_REQUIRED)
    defaults.update(kw)
    limitations = defaults.pop('limitations', ())
    temporal = defaults['temporal_mode']
    base_limits = ((_CURRENT_STATE_NOTE,) if temporal == TemporalMode.CURRENT_STATE else ()) + (
        (_OPEN_NOTE,) if defaults['status_criterion'] == StatusCriterion.OPEN_EXCLUDING_APPROVED_MITIGATIONS else ())
    return MetricContract(
        metric_id=metric_id, version=1, name=name, description=description, domain=domain,
        source=Source.FINDINGS_API, endpoint=_FINDINGS_EP, context=context,
        scan_type=ScanType.STATIC if domain == Domain.SAST else ScanType.SCA, unit=Unit.FINDINGS, shape=shape,
        formula=formula, completeness_rules=_FINDING_RULES, limitations=base_limits + (_ZERO_NOTE,) + limitations,
        **defaults)


def _alt(metric_id: str, name: str, description: str, domain: Domain, source: Source, endpoint: str, shape: Shape,
         unit: Unit, formula: str, *, status_criterion=StatusCriterion.NOT_APPLICABLE,
         severity_criterion=SeverityCriterion.NOT_APPLICABLE, temporal=TemporalMode.CURRENT_STATE,
         date_field=DateField.NONE, scan_type=ScanType.NOT_APPLICABLE, context=ScanContext.NOT_APPLICABLE,
         limitations=(), rules=()) -> MetricContract:
    """Indicadores de fontes alternativas (F04.1): Summary Report, perfil da aplicação (`scans[]`, políticas) e
    SCA Agent. População = escopo de aplicações do dono; agregação por aplicação (sem identidade de finding)."""
    return MetricContract(
        metric_id=metric_id, version=1, name=name, description=description, domain=domain, source=source,
        endpoint=endpoint, context=context, scan_type=scan_type, temporal_mode=temporal, date_field=date_field,
        status_criterion=status_criterion, severity_criterion=severity_criterion, dedup=Dedup.APPLICATION_GUID,
        identity_proof=IdentityProof.NOT_REQUIRED, unit=unit, shape=shape, formula=formula,
        completeness_rules=_APP_RULES + rules,
        limitations=((_CURRENT_STATE_NOTE,) if temporal == TemporalMode.CURRENT_STATE else ()) + limitations)


_SUMMARY_RULES = ('Summary Report coletado para todas as aplicações da população',)


def _gap(metric_id: str, name: str, domain: Domain, reason: str, *, temporal=TemporalMode.CURRENT_STATE,
         date_field=DateField.NONE, source=Source.NONE, endpoint=None, scan_type=ScanType.NOT_APPLICABLE,
         context=ScanContext.NOT_APPLICABLE, unit=Unit.FINDINGS) -> MetricContract:
    return MetricContract(
        metric_id=metric_id, version=1, name=name, description=reason, domain=domain, source=source,
        endpoint=endpoint, context=context, scan_type=scan_type, temporal_mode=temporal, date_field=date_field,
        status_criterion=StatusCriterion.NOT_APPLICABLE, severity_criterion=SeverityCriterion.NOT_APPLICABLE,
        dedup=Dedup.NONE, identity_proof=IdentityProof.NOT_REQUIRED, unit=unit, shape=Shape.SCALAR,
        formula='—', support=Support.UNSUPPORTED if temporal != TemporalMode.STATE_AT_PERIOD_END else Support.SUPPORTED,
        homologation=Homologation.SOURCE_NOT_HOMOLOGATED if source == Source.NONE else Homologation.NOT_VERIFIED,
        unsupported_reason=reason)


_HISTORY = ('A fonte expõe só o estado atual (sem data de resolução nem histórico de status): o estado no fechamento '
            'de uma competência anterior não pode ser reconstruído exatamente. Usar snapshot aprovado (F05) ou '
            'entrada manual — nunca estimativa')

CONTRACTS: tuple[MetricContract, ...] = (
    # ------------------------------------------------------------------ aplicações
    _apps('apps.total', 'Aplicações no escopo', 'Aplicações distintas (por GUID) no escopo do dono',
          Shape.SCALAR, 'count(distinct application.guid)'),
    _apps('apps.by_business_unit', 'Aplicações por Business Unit',
          'Aplicações por BU do perfil (uma BU por aplicação); BU ausente em "unknown"', Shape.BREAKDOWN,
          'count(distinct guid) group by business_unit.guid'),
    _apps('apps.by_team', 'Aplicações por Team',
          'Aplicações por Team do perfil; aplicação com vários Teams conta em cada um (soma ≥ total)',
          Shape.BREAKDOWN, 'count(distinct guid) group by team.guid',
          limitations=('A soma por Team não é o total: use apps.total (distintas)',)),
    _apps('apps.without_team', 'Aplicações sem Team', 'Aplicações com lista de Teams conhecida e vazia',
          Shape.SCALAR, 'count(distinct guid) where teams == []',
          limitations=('Lista de Teams ausente (desconhecida) não conta como "sem Team": torna o indicador '
                       'INCOMPLETE',)),
    _apps('apps.multiple_teams', 'Aplicações em vários Teams', 'Aplicações distintas com 2 ou mais Teams',
          Shape.SCALAR, 'count(distinct guid) where len(teams) >= 2'),
    _apps('apps.unclassified', 'Aplicações não classificadas',
          'Universo do cliente menos as aplicações de subclientes ativos na mesma conexão (só cliente principal)',
          Shape.SCALAR, 'count(universe − ∪ subclientes ativos shared)'),
    _alt('apps.by_policy_compliance', 'Aplicações por conformidade de política',
         'Aplicações por policy_compliance_status do perfil (uma política por aplicação)', Domain.APPLICATIONS,
         Source.APPLICATIONS_API, _APPS_EP, Shape.BREAKDOWN, Unit.APPLICATIONS,
         'count(distinct guid) group by profile.policies[0].policy_compliance_status',
         limitations=('Aplicação sem política ou com várias políticas => indeterminada (INCOMPLETE)',)),
    _alt('apps.loc.total', 'Linhas de código (LOC) analisadas', 'Soma do LOC dos módulos da última análise estática '
         'da Policy (Summary Report)', Domain.APPLICATIONS, Source.SUMMARY_REPORT_API, _SUMMARY_EP, Shape.SCALAR,
         Unit.LINES_OF_CODE, 'Σ static_analysis.modules.module[].loc', rules=_SUMMARY_RULES,
         limitations=('Só aplicações com análise estática; demais são contadas à parte (não viram zero)',
                      'LOC por módulo pode ficar vazio para módulos não debug (especificação) => INCOMPLETE')),
    _gap('apps.total.at_period_end', 'Aplicações no fechamento da competência', Domain.APPLICATIONS,
         'O perfil de aplicações é estado atual (BU/Teams/exclusões mudam): ' + _HISTORY,
         temporal=TemporalMode.STATE_AT_PERIOD_END, source=Source.APPLICATIONS_API, endpoint=_APPS_EP,
         unit=Unit.APPLICATIONS),

    # ------------------------------------------------------------------ SAST
    _findings('sast.policy.open.by_severity', 'SAST abertos — Policy (produção)',
              'Findings SAST abertos no contexto Policy, por severidade', Domain.SAST, ScanContext.POLICY,
              Shape.BY_SEVERITY, 'count(findings) group by severity; scan_type=STATIC; sem context'),
    _findings('sast.sandbox.open.by_severity', 'SAST abertos — Sandboxes (ocorrências)',
              'Findings SAST abertos por sandbox, somados como OCORRÊNCIAS por contexto (não distintos)',
              Domain.SAST, ScanContext.SANDBOX, Shape.BY_SEVERITY,
              'Σ por (aplicação, sandbox) de count(findings) group by severity; context=sandbox_guid',
              limitations=('Ocorrências: o mesmo finding em 2 sandboxes conta 2 vezes; distintos em '
                           'sast.sandbox.open.distinct',)),
    _findings('sast.sandbox.open.distinct', 'SAST abertos — Desenvolvimento (distintos)',
              'Findings SAST abertos distintos entre os sandboxes de cada aplicação', Domain.SAST,
              ScanContext.SANDBOX, Shape.BY_SEVERITY, 'count(distinct (application.guid, issue_id)) em sandboxes',
              dedup=Dedup.APP_ISSUE_ID_ACROSS_CONTEXTS, identity_proof=IdentityProof.NOT_PROVEN,
              limitations=(_ISSUE_ID_NOTE,)),
    _findings('sast.open.distinct', 'SAST abertos — total distinto (Policy + Sandboxes)',
              'Findings SAST abertos distintos considerando Policy e sandboxes', Domain.SAST,
              ScanContext.POLICY_AND_SANDBOX, Shape.BY_SEVERITY,
              'count(distinct (application.guid, issue_id)) em Policy ∪ sandboxes',
              dedup=Dedup.APP_ISSUE_ID_ACROSS_CONTEXTS, identity_proof=IdentityProof.NOT_PROVEN,
              limitations=(_ISSUE_ID_NOTE,)),
    _findings('sast.policy.open.by_cwe', 'SAST abertos por CWE — Policy',
              f'Top {TOP_N} CWEs dos findings SAST abertos em Policy', Domain.SAST, ScanContext.POLICY,
              Shape.RANKING, 'count(findings) group by cwe.id order by count desc, cwe.id asc', top_n=TOP_N,
              limitations=('Desempate por id do CWE (não oficial)', 'Agrupamento por CWE, não pelas categorias '
                                                                    'do dashboard')),
    _findings('sast.policy.open.top_applications', 'Top aplicações por SAST aberto — Policy',
              f'Top {TOP_N} aplicações com mais findings SAST abertos em Policy', Domain.SAST, ScanContext.POLICY,
              Shape.RANKING, 'count(findings) group by application order by count desc, nome, guid', top_n=TOP_N,
              limitations=('Desempate por nome e GUID (não oficial)',)),
    _findings('sast.policy.new_in_period.by_severity', 'SAST identificados na competência — Policy',
              'Findings SAST em Policy cuja data de identificação cai na competência (qualquer status atual)',
              Domain.SAST, ScanContext.POLICY, Shape.BY_SEVERITY,
              'count(findings) where period_start <= first_found_date < period_end group by severity',
              temporal_mode=TemporalMode.EVENT_IN_PERIOD, date_field=DateField.FIRST_FOUND_DATE,
              status_criterion=StatusCriterion.ANY_STATUS,
              limitations=('Só findings ainda visíveis na API (aplicações/scans excluídos somem)',
                           'Inclusão de findings fechados pela API por padrão NÃO verificada',
                           'last_seen_date (atualização) não é data de identificação')),
    _findings('sast.policy.open.by_first_found_month', 'SAST abertos por mês de identificação — Policy',
              'Findings SAST abertos em Policy agrupados pelo mês (no fuso da competência) de first_found_date',
              Domain.SAST, ScanContext.POLICY, Shape.BREAKDOWN, 'count(findings) group by month(first_found_date)',
              date_field=DateField.FIRST_FOUND_DATE),
    _alt('sast.policy.summary.by_severity', 'SAST por severidade — Policy (Summary Report)',
         'Findings da última análise estática da Policy por severidade, segundo o Summary Report (fonte alternativa '
         'à Findings API)', Domain.SAST, Source.SUMMARY_REPORT_API, _SUMMARY_EP, Shape.BY_SEVERITY, Unit.FINDINGS,
         'Σ static_analysis.modules.module[].numflawssev0..5', scan_type=ScanType.STATIC, context=ScanContext.POLICY,
         status_criterion=StatusCriterion.SUMMARY_REPORT_LATEST_BUILD, severity_criterion=SeverityCriterion.ALL_0_TO_5,
         rules=_SUMMARY_RULES,
         limitations=('Definição do relatório: findings do build mais recente; tratamento de mitigados não '
                      'documentado (pode diferir de "aberto" da Findings API)',
                      'Aplicação sem análise estática conta à parte (não vira zero)')),
    _alt('sast.policy.reconciliation', 'Reconciliação SAST Policy: Findings API × Summary Report',
         'Por aplicação, compara os findings OPEN da Findings API (Policy, STATIC) por severidade com o Summary Report',
         Domain.SAST, Source.SUMMARY_REPORT_API, f'{_FINDINGS_EP} + {_SUMMARY_EP}', Shape.BREAKDOWN,
         Unit.APPLICATIONS, 'count(apps) where findings_open_by_severity == summary_static_by_severity',
         scan_type=ScanType.STATIC, context=ScanContext.POLICY, rules=_SUMMARY_RULES,
         limitations=('Concordância entre duas fontes oficiais NÃO é equivalência com o dashboard',
                      'Compara OPEN com qualquer estado de mitigação (o relatório não separa mitigados)')),
    _gap('sast.policy.open.at_period_end', 'SAST abertos no fechamento da competência', Domain.SAST, _HISTORY,
         temporal=TemporalMode.STATE_AT_PERIOD_END, source=Source.FINDINGS_API, endpoint=_FINDINGS_EP,
         scan_type=ScanType.STATIC, context=ScanContext.POLICY),
    _gap('sast.policy.resolved_in_period', 'SAST resolvidos na competência', Domain.SAST,
         'A Findings API não expõe data de resolução/fechamento (só first_found_date e last_seen_date; last_seen_date '
         'não é data de resolução). ' + _REPORTING_BLOCKED + ' (campos resolved_date/fixed_date)',
         temporal=TemporalMode.EVENT_IN_PERIOD, date_field=DateField.RESOLUTION_DATE, scan_type=ScanType.STATIC,
         context=ScanContext.POLICY, source=Source.REPORTING_API, endpoint=_REPORTING_EP),

    # ------------------------------------------------------------------ SCA
    _findings('sca.policy.open.by_severity', 'SCA abertos — Policy (produção)',
              'Findings SCA abertos no contexto Policy, por severidade', Domain.SCA, ScanContext.POLICY,
              Shape.BY_SEVERITY, 'count(findings) group by severity; scan_type=SCA; sem context',
              limitations=('SCA por upload e por agente vinculado à aplicação vêm juntos (sca_scan_mode); '
                           'separação não homologada',)),
    _findings('sca.sandbox.open.by_severity', 'SCA abertos — Sandboxes (ocorrências)',
              'Findings SCA abertos por sandbox, somados como ocorrências', Domain.SCA, ScanContext.SANDBOX,
              Shape.BY_SEVERITY, 'Σ por (aplicação, sandbox) de count(findings) group by severity',
              support=Support.SUPPORT_NOT_VERIFIED,
              limitations=('Suporte de SCA por sandbox na Findings API não homologado: resposta 400 => UNSUPPORTED',)),
    _findings('sca.open.distinct', 'SCA abertos — total distinto (Policy + Sandboxes)',
              'Vulnerabilidades SCA abertas distintas por aplicação, componente e identificador da vulnerabilidade',
              Domain.SCA, ScanContext.POLICY_AND_SANDBOX, Shape.BY_SEVERITY,
              'count(distinct (application.guid, component_id, cve.name))',
              dedup=Dedup.APP_COMPONENT_VULNERABILITY_ACROSS_CONTEXTS, identity_proof=IdentityProof.NOT_PROVEN,
              limitations=('Identidade SCA (componente + vulnerabilidade) é distinta da identidade SAST e não foi '
                           'comprovada com dados reais', 'Severidade do distinto = maior severidade observada')),
    _findings('sca.policy.open.top_components', 'Top bibliotecas vulneráveis — Policy',
              f'Top {TOP_N} componentes (component_id) com mais findings SCA abertos em Policy', Domain.SCA,
              ScanContext.POLICY, Shape.RANKING, 'count(findings) group by component_id order by count desc',
              top_n=TOP_N, limitations=('Desempate por nome do arquivo e component_id (não oficial)',)),
    _findings('sca.policy.open.top_vulnerabilities', 'Top vulnerabilidades (CVE) — Policy',
              f'Top {TOP_N} identificadores de vulnerabilidade (cve.name) em findings SCA abertos em Policy',
              Domain.SCA, ScanContext.POLICY, Shape.RANKING,
              'count(distinct application) group by cve.name order by count desc', top_n=TOP_N,
              limitations=('cve.name pode conter identificadores que não são CVE (especificação)',)),
    _findings('sca.policy.open.by_dependency_mode', 'SCA abertos por tipo de dependência — Policy',
              'Findings SCA abertos em Policy por sca_dep_mode (DIRECT/TRANSITIVE/BOTH/UNKNOWN)', Domain.SCA,
              ScanContext.POLICY, Shape.BREAKDOWN, 'count(findings) group by metadata.sca_dep_mode',
              limitations=('Formato de `metadata` (string na especificação) não homologado',)),
    _alt('sca.policy.summary.components', 'Componentes de terceiros — Policy (Summary Report)',
         'Componentes de terceiros e componentes que violam a política SCA, por aplicação, segundo o Summary Report',
         Domain.SCA, Source.SUMMARY_REPORT_API, _SUMMARY_EP, Shape.BREAKDOWN, Unit.COMPONENTS,
         'Σ software_composition_analysis.third_party_components; Σ components_violated_policy',
         scan_type=ScanType.SCA, context=ScanContext.POLICY, rules=_SUMMARY_RULES,
         limitations=('Especificação descreve third_party_components como "vulnerable third party components"; '
                      'semântica exata não homologada',)),
    _alt('sca.agent.linked_projects', 'Projetos do SCA Agent vinculados', 'Aplicações com projetos do SCA Agent '
         'vinculados (por GUID) e total de projetos', Domain.SCA, Source.SCA_AGENT_API, _SCA_AGENT_EP,
         Shape.BREAKDOWN, Unit.PROJECTS, 'count(apps) where linked_projects != []; Σ linked_projects',
         scan_type=ScanType.SCA, rules=('consulta de projetos vinculados completa para todas as aplicações',),
         limitations=('Projetos de workspace não vinculados a aplicação ficam fora (invisíveis por aplicação)',
                      'Issues do agente (workspaces/{id}/projects/{id}/issues) não coletadas')),
    _gap('sca.policy.open.at_period_end', 'SCA abertos no fechamento da competência', Domain.SCA, _HISTORY,
         temporal=TemporalMode.STATE_AT_PERIOD_END, source=Source.FINDINGS_API, endpoint=_FINDINGS_EP,
         scan_type=ScanType.SCA, context=ScanContext.POLICY),
    _gap('sca.policy.new_in_period', 'SCA identificados na competência', Domain.SCA,
         'Para SCA, first_found_date pode ser a data de publicação da vulnerabilidade OU a de detecção da '
         'biblioteca (especificação): semântica ambígua para "identificados no mês"',
         temporal=TemporalMode.EVENT_IN_PERIOD, date_field=DateField.FIRST_FOUND_DATE, source=Source.FINDINGS_API,
         endpoint=_FINDINGS_EP, scan_type=ScanType.SCA, context=ScanContext.POLICY),
    _gap('sca.agent.issues', 'Issues do SCA Agent', Domain.SCA,
         'Issues por projeto do agente (GET /srcclr/v3/workspaces/{id}/projects/{projectId}/issues) existem na '
         'especificação, mas não foram homologadas nem incluídas na allowlist; findings SCA de agente VINCULADO já '
         'aparecem na Findings API (sca_scan_mode=AGENT)', scan_type=ScanType.SCA, source=Source.SCA_AGENT_API),

    # ------------------------------------------------------------------ scans e licenças
    _gap('scans.count', 'Scans na competência', Domain.SCANS,
         'O perfil da aplicação só traz o ÚLTIMO scan por tipo. ' + _REPORTING_BLOCKED + ' (relatório SCANS)',
         temporal=TemporalMode.EVENT_IN_PERIOD, source=Source.REPORTING_API, endpoint=_REPORTING_EP),
    _alt('scans.covered_apps', 'Aplicações com scan estático publicado na competência',
         'Aplicações cujo último scan STATIC publicado cai na competência; se houver scan posterior ao período, o '
         'scan do período pode estar oculto (indeterminada)', Domain.SCANS, Source.APPLICATIONS_API, _APPS_EP,
         Shape.BREAKDOWN, Unit.APPLICATIONS, 'count(apps) where scans[STATIC,PUBLISHED].modified_date ∈ competência',
         temporal=TemporalMode.EVENT_IN_PERIOD, date_field=DateField.SCAN_PUBLISHED_DATE,
         status_criterion=StatusCriterion.PUBLISHED_SCAN, scan_type=ScanType.STATIC,
         limitations=('Só o último scan por tipo é visível: competências antigas tendem a INCOMPLETE '
                      '(limite inferior em partial)', 'Contexto (Policy/Sandbox) de scans[] não documentado',
                      'scans[] real não lista SCA (homologação F04.1)')),
    _gap('licenses.usage', 'Licenças consumidas', Domain.LICENSES,
         'Nenhuma API de licenças homologada; pode exigir entrada manual (F05)'),
)

REGISTRY: dict[str, MetricContract] = {c.metric_id: c for c in CONTRACTS}
assert len(REGISTRY) == len(CONTRACTS), 'metric_id duplicado'


def catalog() -> dict:
    return {'metrics': [c.public() for c in CONTRACTS],
            'statuses': ['VALIDATED', 'INCOMPLETE', 'UNAVAILABLE', 'UNSUPPORTED', 'FAILED']}
