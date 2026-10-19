# F10 — Conciliação dos indicadores com a plataforma Veracode (2026-10-19)

Base: matriz de 35 indicadores da F09 (`docs/F09_METRIC_RECONCILIATION.md`), contratos em
`backend/app/metrics/registry.py`, guia de conferência em `backend/app/reconciliation/guide.py`.
Execução real nesta fase: tenant **de testes**, **somente GET** (diagnóstico SCA 31 + recoleta de métricas 37 = 68
pedidos; 0 POST). Valores e identificadores reais **só** em `private/f10/` (ignorado pelo Git).

## 1. Resultado em uma linha
**Indicadores homologados contra o dashboard: 0 de 35.** O agente não acessa o portal; a F10 entrega o fluxo de
conferência humana dentro do produto (§4) e **corrige o defeito que bloqueava o SCA** (§3): 5 indicadores SCA saem de
BLOCKED_EXTERNAL e passam a ter valor VALIDATED em real, aguardando conferência.

| Categoria (F10) | Qtde | Indicadores |
|---|---|---|
| Aplicável — **NOT_VERIFIED** (valor calculado, aguardando conferência humana) | 21 | apps ×7 (total, by_business_unit, by_team, without_team, multiple_teams, by_policy_compliance, loc.total), SAST ×7 (policy.open.by_severity, sandbox.open.by_severity, policy.open.by_cwe, policy.open.top_applications, policy.new_in_period.by_severity, policy.open.by_first_found_month, policy.summary.by_severity), SCA ×7 (policy.open.by_severity, sandbox.open.by_severity, policy.open.top_components, policy.open.top_vulnerabilities, policy.open.by_dependency_mode, policy.summary.components, agent.linked_projects) |
| **NOT_APPLICABLE** (não existe valor oficial com a mesma definição) | 12 | apps.unclassified, apps.total.at_period_end, sast.sandbox.open.distinct, sast.open.distinct, sast.policy.reconciliation, sast.policy.open.at_period_end, sca.open.distinct, sca.policy.open.at_period_end, sca.policy.new_in_period, sca.agent.issues, scans.covered_apps, licenses.usage |
| **BLOCKED_EXTERNAL** (fonte bloqueada fora do projeto) | 2 | sast.policy.resolved_in_period, scans.count (Reporting API, HTTP 403) |
| **Homologado (MATCH conferido)** | **0** | — |

Mudança em relação à F09: SCA ×5 BLOCKED_EXTERNAL → NOT_VERIFIED (coleta real completa após a correção);
`sca.open.distinct` BLOCKED_EXTERNAL → NOT_APPLICABLE (a coleta agora completa, mas a identidade de deduplicação entre
contextos continua NÃO comprovada por contrato — igual aos distintos SAST). Total 21 + 12 + 2 = 35.

## 2. Matriz por indicador
Convenções comuns: **escopo** = aplicações do escopo de aplicações do dono (cliente ou subcliente; regras por domínio,
F03); **competência** = mês fechado no fuso do cliente (padrão `America/Sao_Paulo`); **ATUAL** = estado na data da coleta
(não é fechamento); **EVENTO** = data do evento dentro da competência; **FECHAMENTO** = estado no fim do mês (só por
snapshot aprovado/entrada manual). "Aberto" = `finding_status.status = OPEN` e `resolution_status ≠ APPROVED`
(mitigação proposta/rejeitada segue aberta). Severidade 5 Very High … 0 Informational; ausente ⇒ INCOMPLETE.
**Policy = produção, Sandbox = desenvolvimento** (convenção autorizada). Endpoints: Applications
`GET /appsec/v1/applications`; Findings `GET /appsec/v2/applications/{guid}/findings` (`scan_type`, `context`);
Summary Report `GET /appsec/v2/applications/{guid}/summary_report`; SCA Agent `GET /srcclr/v3/applications/{guid}/projects`.

| ID | Definição exata (fórmula do contrato) | Fonte / filtros | P/S | Temporal | Mitigação · severidade · dedup | Categoria F10 | Evidência / divergência |
|---|---|---|---|---|---|---|---|
| apps.total | count(distinct guid) | Applications; escopo | — | ATUAL | — · — · GUID | NOT_VERIFIED | real VALIDATED (F09); = tamanho do escopo |
| apps.by_business_unit | count(distinct guid) por BU do perfil | Applications | — | ATUAL | — · — · GUID; BU ausente ⇒ INCOMPLETE | NOT_VERIFIED | |
| apps.by_team | count(distinct guid) por Team (multi-Team conta em cada) | Applications | — | ATUAL | GUID | NOT_VERIFIED | soma ≥ total por definição |
| apps.without_team | Teams conhecidos e vazios | Applications | — | ATUAL | GUID; Teams ausentes ≠ vazio | NOT_VERIFIED | |
| apps.multiple_teams | ≥ 2 Teams | Applications | — | ATUAL | GUID | NOT_VERIFIED | |
| apps.unclassified | universo − ∪ subclientes ativos | Applications + escopos | — | ATUAL | GUID | NOT_APPLICABLE | conceito do Afrika |
| apps.by_policy_compliance | count por `policies[0].policy_compliance_status` | Applications | P | ATUAL | 0/>1 política ⇒ INCOMPLETE | NOT_VERIFIED | |
| apps.loc.total | Σ `static_analysis.modules.module[].loc` | Summary Report (último build) | P | ATUAL | — | NOT_VERIFIED | |
| apps.total.at_period_end | — | — | — | FECHAMENTO | — | NOT_APPLICABLE | só snapshot aprovado/manual |
| sast.policy.open.by_severity | count(findings abertos) por severidade; `scan_type=STATIC`, sem `context` | Findings | P | ATUAL | aberto · 0–5 · `issue_id` no contexto | NOT_VERIFIED | **Findings × Summary Report 3/3 coincidentes** (recoleta F10) — coerência entre fontes oficiais, NÃO dashboard |
| sast.sandbox.open.by_severity | Σ por (app, sandbox) — ocorrências | Findings `context=sandbox` | S | ATUAL | aberto · 0–5 · `issue_id` no contexto | NOT_VERIFIED | ocorrências, não distintos |
| sast.sandbox.open.distinct | distinct (app, issue_id) entre sandboxes | Findings | S | ATUAL | identidade NOT_PROVEN | NOT_APPLICABLE | sempre INCOMPLETE por contrato |
| sast.open.distinct | distinct (app, issue_id) Policy ∪ sandboxes | Findings | P+S | ATUAL | NOT_PROVEN | NOT_APPLICABLE | idem |
| sast.policy.open.by_cwe | top 10 CWE + outros | Findings | P | ATUAL | aberto | NOT_VERIFIED | desempate não oficial |
| sast.policy.open.top_applications | top 10 aplicações | Findings | P | ATUAL | aberto | NOT_VERIFIED | desempate não oficial |
| sast.policy.new_in_period.by_severity | `first_found_date` ∈ competência, qualquer status | Findings | P | EVENTO | qualquer status · 0–5 | NOT_VERIFIED | só findings ainda visíveis |
| sast.policy.open.by_first_found_month | abertos por mês de `first_found_date` | Findings | P | ATUAL | aberto | NOT_VERIFIED | |
| sast.policy.summary.by_severity | Σ `numflawssev0..5` | Summary Report (último build) | P | ATUAL | mitigados: não documentado | NOT_VERIFIED | fonte alternativa |
| sast.policy.reconciliation | apps com Findings == Summary por severidade | ambas | P | ATUAL | — | NOT_APPLICABLE | qualidade de dados: 3/3 iguais |
| sast.policy.open.at_period_end | — | — | P | FECHAMENTO | — | NOT_APPLICABLE | histórico |
| sast.policy.resolved_in_period | `resolved_date`/`fixed_date` na competência | Reporting FINDINGS (POST) | P | EVENTO | — | BLOCKED_EXTERNAL | HTTP 403; POST não repetido |
| sca.policy.open.by_severity | count(findings SCA abertos) por severidade; `scan_type=SCA`, sem `context` | Findings | P | ATUAL | aberto · 0–5 · **sem dedup** (SCA não tem `issue_id`) | NOT_VERIFIED | **real VALIDATED após a correção F10** (antes INCOMPLETE) |
| sca.sandbox.open.by_severity | Σ por (app, sandbox) | Findings `context` | S | ATUAL | idem | NOT_VERIFIED | idem; suporte por sandbox respondeu 200 |
| sca.open.distinct | distinct (app, component_id, cve.name) | Findings | P+S | ATUAL | NOT_PROVEN | NOT_APPLICABLE | coleta completa; identidade não comprovada |
| sca.policy.open.top_components | top 10 component_id | Findings | P | ATUAL | aberto | NOT_VERIFIED | VALIDATED em real (F10) |
| sca.policy.open.top_vulnerabilities | top 10 cve.name por nº de aplicações | Findings | P | ATUAL | aberto | NOT_VERIFIED | VALIDATED em real (F10) |
| sca.policy.open.by_dependency_mode | por `metadata.sca_dep_mode` | Findings | P | ATUAL | aberto | NOT_VERIFIED | VALIDATED em real (F10) |
| sca.policy.summary.components | Σ third_party_components; Σ components_violated_policy | Summary Report | P | ATUAL | — | NOT_VERIFIED | **não é comparável** com a Findings SCA (componentes ≠ vulnerabilidades; na amostra os totais diferem) |
| sca.agent.linked_projects | apps com projetos; Σ projetos | SCA Agent | — | ATUAL | GUID | NOT_VERIFIED | |
| sca.policy.open.at_period_end | — | — | P | FECHAMENTO | — | NOT_APPLICABLE | histórico |
| sca.policy.new_in_period | — | Findings | P | EVENTO | — | NOT_APPLICABLE | `first_found_date` SCA ambígua |
| sca.agent.issues | — | SCA Agent workspaces (fora da allowlist) | — | ATUAL | — | NOT_APPLICABLE | não calculado |
| scans.count | relatório SCANS | Reporting (POST) | P/S | EVENTO | — | BLOCKED_EXTERNAL | HTTP 403 |
| scans.covered_apps | último scan STATIC publicado ∈ competência | Applications `scans[]` | — | EVENTO | — | NOT_APPLICABLE | scan posterior oculta o do período |
| licenses.usage | — | nenhuma API | — | ATUAL | — | NOT_APPLICABLE | entrada manual (F05) |

## 3. SCA: causa real da incompletude e correção
**Diagnóstico (real, só GET — `backend/tests_live/test_f10_sca_diagnostics.py`, 31 pedidos, 0 retry):**
- Na aplicação da amostra com componentes, a 1ª página da Findings SCA (Policy e 2 sandboxes) respondeu **HTTP 200**
  em 0,8–1,5 s com `page.total_elements` e 50 itens — e **nenhum item tem `issue_id`** (campos reais:
  `context_guid, context_type, count, description, finding_details, finding_status, scan_type, violates_policy`).
- O paginador exigia `issue_id` em todo item e lançava `invalid_response` **depois** do 200: contexto `incomplete`, sem
  status HTTP. Era isso — e não transporte — que deixava todo SCA com componentes INCOMPLETE.
- Releitura da evidência F09: as 6 respostas `-1` (exceção de transporte) foram **recuperadas** pelas novas tentativas
  (6 retries = 6 falhas; 22 contextos = 22 respostas 200). A F09 atribuiu a incompletude ao transporte por engano.
- Aplicações sem componentes: Findings SCA respondeu 200 com `total_elements = 0` (na F04 respondia 500 —
  comportamento da plataforma mudou; o tratamento de 500 permanece e segue testado em mock).

**Correção (mínima):** `paginate(..., id_field=None)` para SCA — completude provada pelos metadados de paginação
(`total_elements` = itens recebidos; sem metadados ⇒ `invalid_response`); STATIC continua exigindo `issue_id` e
detectando repetição. Fixture sintético passou a reproduzir o formato real (SCA sem `issue_id`). Metadado de
deduplicação dos 5 contratos SCA de contexto único corrigido para `NONE` + limitação explícita (o cálculo nunca
deduplicou SCA por `issue_id`: **fórmula e valor inalterados**, por isso `version` continua 1 — decisão registrada para
o PO). Testes: `backend/tests/test_f10_sca_shape.py` (7).
**Evidência pós-correção (real, `test_metrics_live.py`, 37 GET):** 18/18 contextos `complete` (antes 15 + 3
incompletos); SCA policy/sandbox/top/dep_mode VALIDATED; reconciliação SAST 3/3.

**Alternativas oficiais avaliadas para SCA:** Summary Report (`software_composition_analysis`): conta componentes,
não vulnerabilidades — complementar, não substituto; SCA Agent issues: fora da allowlist (não adicionado — integração
especulativa); Reporting FINDINGS com `scan_type` SCA: bloqueada (403). Nenhuma nova integração adicionada.

## 4. Conferência: automática × humana
**Automática por API oficial (sem dashboard):** só coerência entre fontes oficiais — SAST Policy Findings × Summary
Report (indicador `sast.policy.reconciliation`, 3/3). Não existe API pública que devolva "o número do dashboard"; não
foram usados endpoints internos, cookies nem automação de interface.

**Humana (novo no produto):** página **Conferir com a Veracode** (`#/conference/{competência}/{revisão}`, botão na
revisão) + API `GET|POST /api/competences/{cid}/revisions/{n}/conference[/{metric_id}]` e CSV. Para cada indicador:
valor calculado (lido do snapshot pelo servidor), caminho indicativo na Veracode, filtros obrigatórios, campo do valor
oficial por linha, Δ = calculado − oficial e Δ% automáticos, status, evidência local, data e conferente (declarado).
Regras: MATCH só com todas as linhas e Δ = 0; filtros não confirmados, estado ATUAL conferido em data diferente da
coleta, linhas faltando ou declaração do operador ⇒ NOT_COMPARABLE; valor MANUAL conferido não homologa o cálculo;
registro append-only (gatilhos) e desatualização automática se o snapshot mudar. NOT_APPLICABLE e BLOCKED_EXTERNAL são
recusados (409) e listados à parte. Migration `0008_metric_conferences`.

**Roteiro do operador (≈30 min, mesmo dia da coleta):** 1) coletar e criar o rascunho da competência; 2) abrir a
revisão → *Conferir com a Veracode*; 3) para cada indicador aplicável, seguir o caminho e os filtros, digitar o número
da plataforma, marcar "filtros conferidos", indicar onde salvou a captura (fora do repo) e registrar; 4) exportar o CSV
para `private/`; 5) devolver ao PO só status e Δ (nunca valores/nomes reais). Divergência = investigar a nossa consulta.

## 5. Reporting API (adaptador preservado; POST não repetido)
Sem mudança de autorização comprovada ⇒ nenhum POST nesta fase. Indicadores que se beneficiariam: **scans.count**
(relatório SCANS), **sast.policy.resolved_in_period** (`resolved_date`/`fixed_date`), **scans.covered_apps** (histórico
completo de scans em vez do último), **sca.policy.new_in_period** (`library_first_found`/`found_date` — se a definição
for aprovada) e, parcialmente, os `*.at_period_end` (reconstrução por `last_updated_*`, janela de 6 meses — exigiria
contrato novo). Nenhum contrato novo foi criado.
