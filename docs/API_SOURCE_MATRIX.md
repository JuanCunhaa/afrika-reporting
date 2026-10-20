# Matriz de fontes Veracode — F04.1 (atualizada na F12)

Fontes consultadas em 2026-10-15: especificações oficiais publicadas pela Veracode no SwaggerHub (organização
`Veracode`: Applications 1.0, Findings 2.1, Summary Report v2, Reporting 1.12.0, SCA Agent 3.0, Policy 1.0,
Development Sandbox 2.0, Identity 1.5, Healthcheck 1.0) e páginas de docs.veracode.com (Findings, Reporting, Summary
Report). Referência de terceiros estudada (sem licença declarada ⇒ **nenhum código copiado**):
`ancient-cthulhu/Veracode-All-Findings-Extract`.

Classificação da fonte: **OFICIAL** = endpoint e método na especificação/documentação oficial; **INTERNO_UI** =
endpoint usado pela interface/terceiros, fora da documentação de API (nunca usado); **HIPÓTESE** = não verificado.
Homologação: `VERIFIED_REAL` (formato/comportamento conferido no tenant de testes, só GET) · `VERIFIED_MOCK_ONLY` ·
`NOT_VERIFIED` · `BLOCKED_POST` (exige POST; política GET-only) · `NOT_RUN` (comparação com dashboard não feita).
**Nenhum indicador tem correspondência comprovada com o dashboard** (exige conferência humana com os mesmos filtros).

## 1. Inventário de APIs
| API | Endpoints relevantes (método) | Autenticação / permissão | Uso no projeto |
|---|---|---|---|
| Applications 1.0 (OFICIAL) | `GET /appsec/v1/applications` (filtros `scan_type` STATIC/DYNAMIC/MANUAL, `scan_status`, `modified_after`, `policy_compliance`, `policy_compliance_checked_after`, `business_unit`, `team`, `tag`…; `size` ≤ 500, padrão 50); `GET …/{guid}/sandboxes` | HMAC; papel com leitura de aplicações | descoberta, população, `scans[]` (último scan por tipo), políticas — **VERIFIED_REAL** |
| Findings 2.1 (OFICIAL) | `GET /appsec/v2/applications/{guid}/findings` (`context`=sandbox, `scan_type`, `severity[_gte]`, `cwe`, `cve`, `new`, `violates_policy`, `sca_dep_mode`, `sca_scan_mode`, `mitigated_after`…) ; `GET /appsec/v1/cwes`, `/categories` | HMAC; *Results API* (ou Reviewer/Security Lead) | SAST/SCA por contexto — STATIC **VERIFIED_REAL**; SCA **VERIFIED_REAL na F10** (itens SCA sem `issue_id`; completude pelo total anunciado) |
| Summary Report v2 (OFICIAL) | `GET /appsec/v2/applications/{guid}/summary_report` (`context`, `build_id`; padrão = build mais recente) | HMAC; *Results API* | **novo (F04.1)**: severidade por build, LOC, componentes SCA, conformidade — **VERIFIED_REAL** |
| SCA Agent 3.0 (OFICIAL) | `GET /srcclr/v3/applications/{guid}/projects` (projetos vinculados); `GET /v3/workspaces`, `/v3/workspaces/{id}/projects`, `/…/projects/{p}/issues` (`status` open/fixed, `created_after/before`, `scans_after/before`), `/…/libraries`; PUT/DELETE/POST de vínculo e agentes | HMAC; acesso SCA/workspace | **novo**: só projetos vinculados por GUID — **VERIFIED_REAL** (amostra sem projetos); issues **NOT_VERIFIED** (fora da allowlist) |
| Reporting 1.12 (OFICIAL) | `POST /appsec/v1/analytics/report` + `GET /appsec/v1/analytics/report/{id}`; tipos FINDINGS, SCANS, DELETEDSCANS, AUDIT; filtros `last_updated_start/end_date` (máx. 6 meses), `policy_sandbox`, `status` Open/Closed, `scan_type` | HMAC; papel *Reporting API*; habilitação pela Veracode | **F05: adaptador implementado e testado em mock (FINDINGS/SCANS); POST de geração autorizado pelo PO, desligado por padrão; real ⇒ HTTP 403 (BLOCKED_EXTERNAL)** — fonte potencial de `resolved_date`, `fixed_date`, `reopened_date`, `found_date` e scans; nenhum indicador do catálogo depende dele |
| Policy 1.0 (OFICIAL) | `GET /appsec/v1/policies`, `/{guid}`, `/{guid}/versions[/{v}]`, `policy_settings*`, `policy_licenselist` | HMAC | não usado (conformidade vem do perfil); candidato para regras/prazos |
| Development Sandbox 2.0 (OFICIAL) | `GET …/sandboxes[/{guid}]`; POST `promote` | HMAC | lista de sandboxes (já usada) |
| Identity 1.5 (OFICIAL) | BUs, Teams, usuários (GET); **F12: `GET /api/authn/v2/users/self`** (própria conta; caminho exato); muitas operações POST/PUT/DELETE | HMAC; `/users/self` acessível sem papel de administrador | descoberta F02 — VERIFIED_REAL; **F12: diagnóstico de papéis VERIFIED_REAL** (resposta real sem `account_type`/`api_user`) |
| Healthcheck 1.0 (OFICIAL) | `GET /healthcheck/status` | — | não usado |
| `ui.analysiscenter…/container-scan-query` (INTERNO_UI) | usado pelo script de referência para IaC, com sessão da interface | cookies/sessão | **proibido** nesta fase (não documentado) |

## 2. Matriz por indicador
Colunas: fonte atual · alternativas · Policy/Sandbox · filtro de data na fonte · histórico · paginação · reproduz o
dashboard? · homologação. Todas as chamadas GET; autenticação HMAC (credencial de teste, somente leitura).

| ID | Fonte atual (endpoint) | Alternativas | P/S | Datas | Histórico | Pag. | Dashboard | Homologação |
|---|---|---|---|---|---|---|---|---|
| apps.total / by_business_unit / by_team / without_team / multiple_teams | Applications `GET /appsec/v1/applications` | Identity (BU/Team) | — | `modified_after` (não usado) | não (estado atual) | sim | provável (contagem por GUID) — NOT_RUN | VERIFIED_REAL (formato) |
| apps.unclassified | Applications + escopos F03 | — | — | — | não | sim | conceito próprio | VERIFIED_REAL (formato) |
| apps.by_policy_compliance (novo) | Applications `profile.policies[].policy_compliance_status` | Summary Report `policy_compliance_status`; filtro `policy_compliance` | Policy | `policy_compliance_checked_after` | não | sim | provável — NOT_RUN | VERIFIED_REAL (formato) |
| apps.loc.total (novo) | Summary Report `static_analysis.modules.module[].loc` | — | Policy (último build) | — | por `build_id` (não usado) | 1 req/app | NOT_RUN | VERIFIED_REAL (valor > 0 na amostra) |
| sast.policy.open.by_severity, by_cwe, top_applications, by_first_found_month | Findings `scan_type=STATIC` | Summary Report (severidade); Reporting FINDINGS (POST) | P | `first_found_date` só na resposta (sem filtro de data) | não | sim (`size` ≤ 500; usado 50) | depende da definição de "aberto" — NOT_RUN | STATIC VERIFIED_REAL; 500 intermitente |
| sast.policy.summary.by_severity (novo) | Summary Report `numflawssev0..5` | Findings | P (`context` p/ sandbox) | — | por `build_id` | 1 req/app | NOT_RUN | VERIFIED_REAL; igual à Findings onde ambas responderam |
| sast.policy.reconciliation (novo) | Findings × Summary Report | — | P | — | — | — | qualidade de dados, não dashboard | VERIFIED_REAL (1 app comparável: coincidiu; F04.1 diag: 2 apps coincidiram) |
| sast.sandbox.open.by_severity / distinct, sast.open.distinct | Findings `context=sandbox` | Summary Report `context`; Reporting `policy_sandbox=Sandbox` | S / P+S | idem | não | sim | distintos: identidade NOT_PROVEN | VERIFIED_REAL (formato); 500 frequentes em sandbox |
| sast.policy.new_in_period.by_severity | Findings `first_found_date` | Reporting `found_date` + `last_updated_*` (POST) | P | filtro local | só findings ainda visíveis | sim | NOT_RUN | VERIFIED_REAL (datas com `Z`) |
| sast.policy.resolved_in_period | — | Reporting `resolved_date`/`fixed_date` | P/S | `last_updated_*` | até 6 meses/consulta | sim | — | **BLOCKED_POST** |
| *.at_period_end | — | Reporting (POST) ou snapshot aprovado (F05) | — | — | Reporting: 6 meses | — | — | BLOCKED_POST / F05 |
| sca.policy.open.by_severity, top_components, top_vulnerabilities, by_dependency_mode, sca.open.distinct | Findings `scan_type=SCA` | Summary Report (componentes); SCA Agent issues | P (S: SUPPORT_NOT_VERIFIED) | sem filtro de data | não | sim | NOT_RUN | **F10: VERIFIED_REAL** — 200 com `page.total_elements`, itens SEM `issue_id` (a F04–F09 rejeitava a página: defeito nosso, corrigido); sem componentes: 200 vazio (antes 500) |
| sca.policy.summary.components (novo) | Summary Report `software_composition_analysis` | Findings SCA | P | — | por `build_id` | 1 req/app | NOT_RUN | VERIFIED_REAL |
| sca.agent.linked_projects (novo) | SCA Agent `GET /srcclr/v3/applications/{guid}/projects` | workspaces/projects (não usados) | — | — | não | não | NOT_RUN | VERIFIED_REAL (amostra: 0 projetos) |
| sca.agent.issues | — | `GET /srcclr/v3/workspaces/{id}/projects/{p}/issues` (`created_after/before`) | — | sim (na fonte) | parcial (`status=fixed`) | sim | — | NOT_VERIFIED (fora da allowlist) |
| sca.policy.new_in_period | — | Reporting `library_first_found`/`found_date` (POST) | — | — | — | — | — | UNSUPPORTED (data ambígua na Findings) |
| scans.covered_apps (novo) | Applications `scans[]` (último scan STATIC, `modified_date` = publicação) | Reporting SCANS (POST) | contexto não documentado | data só do ÚLTIMO scan | não (scan anterior fica oculto) | sim | NOT_RUN | VERIFIED_REAL (`scans[]` real só lista STATIC) |
| scans.count | — | Reporting SCANS `published`, `scan_type`, `policy_sandbox` | P/S | `last_updated_*` | 6 meses | sim | — | **BLOCKED_POST** |
| apps.scanned (F12) | Reporting SCANS (um item por scan: `app_id`, `scan_id`, `scan_type`, `policy_sandbox`, `published`) | XML `getbuildlist.do`+`getbuildinfo.do` (NOT_VERIFIED, fora da allowlist); perfil `scans[]` só para checar visibilidade | P/S (SCA sem tipo no relatório) | `published` "EDT" ⇒ intervalo; janela `last_updated_*` do início da competência à geração | 6 meses | sim | NOT_RUN | contrato v1 + mock PASS; real **BLOCKED_EXTERNAL** (403) |
| licenses.usage | — | nenhuma API identificada | — | — | — | — | — | UNSUPPORTED (entrada manual F05) |
| users.* (F03) | Identity | — | — | — | não | sim | — | VERIFIED_REAL |

## 3. Definições oficiais (sem misturar)
| Conceito | Definição na fonte | Onde |
|---|---|---|
| Aberto / fechado | `finding_status.status`: "open or closed" (sem enum na spec); real: `OPEN` | Findings |
| Mitigado | `resolution` (real: `UNRESOLVED`, …) e `resolution_status` (real: `NONE`, …; aprovado = `APPROVED`, não observado) | Findings |
| First Found Date | "Date when the finding was first found"; **SCA: pode ser a publicação da vulnerabilidade ou a detecção da biblioteca** | Findings |
| First Found in Application Date | **não encontrado** nas especificações/páginas consultadas | — |
| Resolved Date | `resolved_date`, `fixed_date`, `reopened_date` existem só no relatório FINDINGS | Reporting (POST) |
| Last Updated Date | `last_updated_date` (filtro `last_updated_start/end_date`, UTC) | Reporting (POST) |
| Last Seen Date | "date and time when the finding was last seen" — **não** é data de resolução | Findings |
| Finding único | `issue_id`: "Unique ID within the context of this application" ⇒ único só dentro do contexto. **F10: findings SCA reais não trazem `issue_id`** | Findings |
| Policy × Sandbox | Findings: sem `context` = Policy, `context`=GUID do sandbox; Reporting: `policy_sandbox` Policy/Sandbox | Findings/Reporting |
| Scans executados | relatório SCANS (`submitted`, `published`, `scan_type`, `policy_sandbox`); perfil só traz o último por tipo | Reporting (POST) / Applications |
| Aplicações com scan | `last_completed_scan_date`; `scans[].modified_date` = publicação do último scan | Applications |
| SCA Upload × Agent | `metadata.sca_scan_mode` (UPLOAD/AGENT; filtro `sca_scan_mode`); findings do agente só aparecem na Findings API se o projeto estiver **vinculado** à aplicação | Findings / SCA Agent |
| Contagens do Summary Report | `numflawssevN` por módulo; `flaws_not_mitigated`; `flaw_status` (chave real `flaw-status`); "build mais recente" por padrão | Summary Report |

## 4. Bloqueados por POST (não executados)
Reporting API: **F05** — POST de geração autorizado (só FINDINGS/SCANS, corpo validado, desligado por padrão); a
conta de testes recebeu HTTP 403 ⇒ habilitação/papel pendentes na Veracode. DELETEDSCANS e AUDIT: não habilitados.
Ver `docs/VERACODE_INTEGRATION.md` → "Reporting API (F05)".
Também exigem POST/PUT/DELETE (fora de escopo): vínculo de projetos do SCA Agent, criação de workspaces/agentes,
`/sbom/v1/manage/scan`, promoção de sandbox, Identity `by_permissions`/`notinteam`, tokens OAuth.
