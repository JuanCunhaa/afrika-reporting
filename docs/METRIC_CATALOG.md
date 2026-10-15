# Catálogo de indicadores — F04

Fonte de verdade do código: `backend/app/metrics/registry.py` (contratos) e `GET /api/metrics/catalog`.
Contrato tipado (`backend/app/metrics/contracts.py`, enums): `metric_id`, versão, nome, descrição, domínio, fonte,
endpoint, escopo de aplicações, contexto Policy/Sandbox, tipo de scan, modo temporal, campo de data, critério de
status e de severidade, deduplicação + prova de identidade, unidade, forma, fórmula, arredondamento, regras de
completude, suporte, homologação e limitações. Resultado: status, valor (**só** se VALIDATED), `partial` (só se
INCOMPLETE), motivos, cobertura, filtros, temporalidade (competência, período, `as_of`, campo de data) e
proveniência da execução (run_id, versões de escopo, versões de contrato, `input_hash`).

## Status
| Status | Quando | Valor |
|---|---|---|
| VALIDATED | coleta completa e contrato atendido (zero é legítimo) | `value` |
| INCOMPLETE | coleta parcial, limite de requisições/prazo, indeterminados, campo ausente (severidade, status, data, Teams), identidade de dedup não comprovada, contexto parcialmente recusado | `partial` (não definitivo) |
| UNAVAILABLE | escopo/conexão/credencial ausente, subcliente sem escopo ou sem abrangência, estado histórico não reconstruível, não aplicável ao dono | — |
| UNSUPPORTED | fonte não homologada ou incapaz; contexto recusado pela Veracode (HTTP 400) | — |
| FAILED | todos os contextos exigidos falharam (nenhum dado) | — |

Convenções: "aberto" = `status=OPEN` e `resolution_status != APPROVED` (equivalência com o dashboard
**NOT_VERIFIED**); severidade 5 Very High … 0 Informational, ausente = `UNKNOWN` ⇒ INCOMPLETE; Policy = produção,
Sandbox = desenvolvimento; SAST e SCA nunca somados nem com a mesma identidade.

## Implementados (fonte homologada em formato; valores NÃO comparados ao dashboard)
| ID | Domínio | Contexto | Temporal | Dedup / identidade | Observação |
|---|---|---|---|---|---|
| apps.total | apps | — | estado atual | GUID | população = escopo F03 |
| apps.by_business_unit | apps | — | estado atual | GUID | BU ausente ⇒ INCOMPLETE |
| apps.by_team | apps | — | estado atual | GUID | soma por Team ≥ total; traz distintas e atribuições |
| apps.without_team | apps | — | estado atual | GUID | Teams ausentes ≠ vazio |
| apps.multiple_teams | apps | — | estado atual | GUID | |
| apps.unclassified | apps | — | estado atual | GUID | só cliente principal; bloqueios da F03 ⇒ INCOMPLETE |
| sast.policy.open.by_severity | SAST | Policy | estado atual | issue_id no contexto | |
| sast.sandbox.open.by_severity | SAST | Sandbox | estado atual | issue_id no contexto | **ocorrências** por sandbox |
| sast.sandbox.open.distinct | SAST | Sandbox | estado atual | (app, issue_id) entre contextos — **NOT_PROVEN** | sempre INCOMPLETE até prova |
| sast.open.distinct | SAST | Policy+Sandbox | estado atual | idem — **NOT_PROVEN** | idem |
| sast.policy.open.by_cwe | SAST | Policy | estado atual | — | top 10 + outros; desempate por id (não oficial) |
| sast.policy.open.top_applications | SAST | Policy | estado atual | — | top 10; desempate nome/GUID (não oficial) |
| sast.policy.new_in_period.by_severity | SAST | Policy | evento na competência | — | `first_found_date` ∈ [início, fim); qualquer status |
| sast.policy.open.by_first_found_month | SAST | Policy | estado atual | — | envelhecimento por mês de identificação |
| sca.policy.open.by_severity | SCA | Policy | estado atual | issue_id no contexto | upload + agente juntos |
| sca.sandbox.open.by_severity | SCA | Sandbox | estado atual | issue_id no contexto | suporte **SUPPORT_NOT_VERIFIED**; 400 ⇒ UNSUPPORTED |
| sca.open.distinct | SCA | Policy+Sandbox | estado atual | (app, component_id, cve.name) — **NOT_PROVEN** | identidade própria do SCA |
| sca.policy.open.top_components | SCA | Policy | estado atual | component_id | biblioteca + versão |
| sca.policy.open.top_vulnerabilities | SCA | Policy | estado atual | cve.name | pode não ser CVE |
| sca.policy.open.by_dependency_mode | SCA | Policy | estado atual | — | `metadata.sca_dep_mode` |
| **F04.1** apps.by_policy_compliance | apps | Policy | estado atual | GUID | perfil `policies[]`; 0 ou >1 política ⇒ INCOMPLETE |
| **F04.1** apps.loc.total | apps | Policy | estado atual (último build) | GUID | Summary Report; só apps com análise estática |
| **F04.1** sast.policy.summary.by_severity | SAST | Policy | estado atual (último build) | — | Summary Report — fonte alternativa à Findings |
| **F04.1** sast.policy.reconciliation | SAST | Policy | estado atual | — | Findings × Summary Report por app; divergência ⇒ INCOMPLETE (nenhuma fonte é corrigida) |
| **F04.1** sca.policy.summary.components | SCA | Policy | estado atual (último build) | — | componentes de terceiros e que violam política |
| **F04.1** sca.agent.linked_projects | SCA | — | estado atual | GUID | SCA Agent, projetos vinculados por GUID |
| **F04.1** scans.covered_apps | scans | (não documentado) | evento na competência | GUID | último scan STATIC publicado; scan posterior ao período ⇒ indeterminado |

## Não suportados / indisponíveis (lacunas explícitas)
| ID | Status | Motivo |
|---|---|---|
| *.at_period_end (apps, SAST, SCA) | UNAVAILABLE | fonte só expõe estado atual; fechamento de competência = snapshot aprovado (F05) ou entrada manual |
| sast.policy.resolved_in_period | UNSUPPORTED | Findings API sem data de resolução; Reporting API tem `resolved_date`/`fixed_date` mas exige **POST** |
| sca.policy.new_in_period | UNSUPPORTED | `first_found_date` do SCA pode ser data de publicação da vulnerabilidade (spec) |
| sca.agent.issues | UNSUPPORTED | issues por projeto do agente existem (GET) mas não foram homologadas/allowlist |
| scans.count | UNSUPPORTED | perfil só traz o último scan; relatório SCANS da Reporting API exige **POST** |
| licenses.usage | UNSUPPORTED | nenhuma API de licenças homologada (provável entrada manual) |
| density.*, trend.monthly | não registrados | densidade exige definição oficial do denominador; tendência depende de snapshots F05 |

## Temporalidade
Competência `YYYY-MM`, sempre mês **fechado** no fuso do cliente (`[1º dia 00:00, 1º dia do mês seguinte)` local).
**F04.1:** fuso IANA por cliente (padrão `America/Sao_Paulo`; subclientes herdam; sobrescrita opcional por execução)
com regras históricas (`zoneinfo` + `tzdata`, ex.: horário de verão até 2019). Cada resultado distingue competência,
fuso, intervalo local, **intervalo UTC** efetivamente comparado, `as_of` (data da coleta), campo de data aplicado e
`historical_state=false`. Estado atual **não** representa o fechamento de competências anteriores.
Fontes e definições por indicador: `docs/API_SOURCE_MATRIX.md`.

> **F05:** existe adaptador da Reporting API (POST de geração autorizado pelo PO, desligado por padrão), mas a conta de testes recebeu HTTP 403 e nenhum contrato novo foi criado: os indicadores acima que dependem dela continuam **UNSUPPORTED** até contrato, testes e homologação. Ver `docs/VERACODE_INTEGRATION.md`.
