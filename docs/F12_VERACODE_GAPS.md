# F12 — Fechamento de lacunas Veracode (2026-10-19)

Execução real nesta fase: tenant de testes (região `commercial`), **somente GET — 2 requisições a
`/api/authn/v2/users/self`**, 0 POST (a Reporting API **não** foi chamada). Saída real, já minimizada, só em
`private/f12/self_diagnostic.json` (ignorado pelo Git). Valores de clientes: nenhum. Contagens do tenant não versionadas (repo público).

## 1. Diagnóstico das permissões da própria conta

**Hosts (documentação oficial "Region domains for Veracode services"):** REST = `api.veracode.com` (Commercial),
`api.veracode.eu` (European), `api.veracode.us` (US Federal) — os mesmos da trava `readonly.ALLOWED_HOSTS`. XML API e
portal ficam em `analysiscenter.veracode.{com,eu,us}` (fora da allowlist).

**Endpoint escolhido:** `GET /api/authn/v2/users/self` — a documentação da Identity API diz que contas sem papel de
administrador ainda acessam `/users/self` e `/users/api_credentials`. **`/principal` não foi usado:** não consta dessa
exceção, devolve mais dados pessoais (e-mail, nomes, organização) e não acrescenta papéis/permissões além dos de
`/users/self` ⇒ não "comprovadamente adequado". Nenhuma conta de outro usuário foi consultada; nada foi alterado.

**Implementação:** `backend/app/veracode/self_diagnostic.py` (minimização na leitura), allowlist com caminho EXATO
(`/users/{id}`, `/users/api_credentials`, `/principal`, `/roles` continuam bloqueados), `DiscoveryService.self_diagnostic`,
API local `POST /api/veracode/{clients|subclients}/{id}/self-diagnostic` (ação local; na Veracode só GET), rota no
tenant sintético e teste real opt-in `backend/tests_live/test_f12_self_diagnostic_live.py`. Guardado: tipo de conta,
flags booleanas, **quantidade** de Teams, nomes/descrições de papéis e nomes de permissões, validade da credencial.
Descartado na hora: user_id/legacy ids, nome de usuário, e-mail, nomes, IPs, `api_id`/`org_id`, nomes de Teams, datas de
login.

**Resultado real (tenant de testes):**

| Item | Observado |
|---|---|
| `account_type` / `api_user` | **ausentes na resposta** (a especificação os define) ⇒ tipo `UNKNOWN`; avaliados os dois critérios documentados |
| Papéis ativos | todos de **usuário de interface** (`ext*`, `vrm*`, `workSpace*`, `sandbox*`…) — nenhum papel "Reporting API" de conta de API |
| Papéis compatíveis com a Reporting API (UI) | **presentes:** Executive, Security Lead, Security Insights |
| Permissões | lista vazia (a resposta não expande permissões por papel) ⇒ permissões específicas da Reporting API **não retornadas** |
| Teams | conta vinculada a Teams; papéis com `ignore_team_restrictions` presentes ⇒ `team_restricted = false` |
| Credencial | válida |
| Privilégio mínimo | **papéis com escrita/administração** (ex.: Administrator, Delete Scans, Policy Administrator, Any Scan, Submitter) |

**Classificação (permissão ausente × habilitação não confirmada):** `ROLE_PRESENT_ENABLEMENT_NOT_CONFIRMED`. A conta TEM
papel de interface aceito pela documentação ("A UI user account with the Executive, Security Lead, or Security Insights
role"); logo o 403 da F05 **não** se explica por papel ausente. A habilitação da Reporting API para a organização
(pedido por e-mail ao suporte) **não é observável** por API ⇒ "não confirmada", nunca "habilitada". Licença **não** foi
presumida. Estados possíveis do classificador: `ROLE_NOT_FOUND` (lista recebida, nenhum papel compatível ⇒ permissão
ausente), `ROLE_PRESENT_ENABLEMENT_NOT_CONFIRMED`, `UNKNOWN` (sem lista de papéis).

Limitações: o `role_name` exato do papel "Reporting API" não é documentado (identificação por nome/descrição, declarada
no resultado); a ausência de `account_type` impede afirmar se a credencial é de usuário de interface ou de conta de API
— os papéis `ext*` indicam usuário de interface (indício, não campo).

**Risco novo (privilégio mínimo):** a credencial de testes pertence a um usuário com papéis de administração e escrita.
O Afrika continua só lendo (trava GET-only em duas camadas), mas a regra "credenciais mínimas" do projeto não é atendida.
Recomendação ao cliente: conta de API dedicada com papéis só de leitura (ex.: Results API) + Reporting API, e papel sem
restrição de Team apenas se o escopo exigir.

## 2. Reporting API — diagnóstico técnico para o suporte (POST NÃO repetido)

Texto pronto para o cliente/administrador enviar ao suporte Veracode (sem identificadores; anexar só o que o cliente
autorizar):

> Organização na região Commercial. Uma credencial de API (HMAC) aceita nas APIs REST de leitura (Applications,
> Findings, Summary Report, Identity — HTTP 200) recebeu **HTTP 403** em `POST /appsec/v1/analytics/report`
> (report_type FINDINGS, 1 aplicação, janela de 7 dias) em 2026-10-15. `GET /api/authn/v2/users/self` mostra papéis
> Executive, Security Lead e Security Insights ativos no usuário da credencial (nenhum papel de conta de API). Pedimos:
> (1) confirmar se a Reporting API está **habilitada** para a organização e, se não, habilitá-la; (2) confirmar se
> credenciais de API de um **usuário de interface** com esses papéis são aceitas ou se é necessária uma **conta de
> API** com o papel "Reporting API"; (3) informar o `role_name` desse papel na Identity API.

Depois da resposta: o PO autoriza **um** POST de teste (SCANS, janela mínima). Sem essa autorização, nada é repetido.

## 3. `apps.scanned` v1

**Definição (ordem do PO):** aplicações distintas do escopo com ao menos um scan publicado na competência.
Contrato `apps.scanned` **v1** (`registry.py`), cálculo `backend/app/metrics/scans_published.py`, motor `engine.py`.

| Requisito | Implementação |
|---|---|
| GUID | população do escopo; `app_id` do relatório = `id` numérico da Applications API (`legacy_id`); nome nunca é identidade |
| SAST / SCA | SAST = `scan_type` "Static Analysis"; **SCA = `null` + `sca_status: UNAVAILABLE`** (o relatório SCANS não tem tipo SCA) |
| Policy / Sandbox | `scanned_policy` / `scanned_sandbox` por `policy_sandbox`; total = distintas (uma app com ambos conta 1) |
| Competência e fuso | mês fechado no fuso do cliente; data `published` em "EDT" (especificação) ⇒ intervalo UTC−4/UTC−5 (data sem hora = dia inteiro); cruzou o limite ⇒ `indeterminate` + INCOMPLETE |
| Data efetiva | `published` (scan sem `published` = não publicado) |
| Deduplicação | itens por `scan_id`; aplicações por GUID |
| Proveniência | `coverage` (itens, duplicados, fora do escopo, outros tipos, não publicados, ambíguos) + pedido do relatório |
| Completude | relatório completo; janela `last_updated_*` do início da competência ao dia seguinte à geração; sem `most_recent_scan=true` nem filtro de app/contexto; `data_refresh_date` ≥ fim do período; **visibilidade**: aplicação com scan publicado no perfil e ausente do relatório ⇒ INCOMPLETE |

Valor: `{scanned, scanned_policy, scanned_sandbox, not_scanned, indeterminate, applications_in_scope, sca_scanned:
null, sca_status, sca_reason}`.

**Estado: UNAVAILABLE** (`scans_report_not_collected`). A coleta de métricas é GET-only e nunca gera o relatório; a
evidência só existe via `scans_published.collect_evidence` (1 POST SCANS, autorizado desde a F05, desligado por padrão
— `AFRIKA_VERACODE_REPORTING_ENABLED=false`), ainda **não ligado** a nenhuma tela/rota. Requer também
`AFRIKA_VERACODE_REPORTING_MAX_WINDOW_DAYS` ≥ dias do início da competência até a geração (padrão 31 é curto).
Conferência: `BLOCKED_EXTERNAL`.

**Fonte comprovada:** apenas **documentalmente** — relatório SCANS (especificação 1.12.0: um item por scan com
`app_id`, `scan_id`, `scan_type`, `policy_sandbox`, `published`, `last_updated_date`; filtro `last_updated_*` ≥
publicação). **Não verificada em real** (403). Fontes investigadas e insuficientes para o mês:

| Fonte | Por que não basta |
|---|---|
| Applications API `scans[]` / `last_completed_scan_date` | só o ÚLTIMO scan por tipo (é o `scans.covered_apps`, NOT_APPLICABLE); usado só para a checagem de visibilidade |
| Summary Report | só o build mais recente por contexto (`build_id` exige conhecer os builds) |
| XML `getbuildlist.do` (+ `getbuildinfo.do`) | lista builds, mas sem data de publicação na lista; host `analysiscenter` e XML fora da allowlist — candidata NOT_VERIFIED, exige autorização do PO |
| SCA Agent | scans do agente não aparecem por aplicação na allowlist atual |

## 4. Conferência com os dashboards

Motor da F10/F11 reutilizado. Cada linha da conferência ganhou o bloco `review` com os 10 itens da ordem: valor
coletado, definição (documentação Veracode ou contrato), escopo (dono + versões de escopo), competência/fuso, filtros,
origem (fonte, endpoint, estado, data da coleta), caminho oficial (tela indicativa + Analytics + links), campos para o
valor do dashboard, diferença (após registrar) e status; `missing` lista o que faltar. Teste:
`test_review_block_lists_the_ten_items_for_every_applicable_metric` (21/21 sem item faltante quando há valor).

**Homologados: 0 de 21** — nenhuma comparação real (o agente não acessa o portal). Nenhum valor real foi coletado
para a conferência nesta fase: os indicadores de estado atual exigem conferência **no mesmo dia** da coleta, então a
coleta é disparada pelo operador no dia em que abrir o portal. `apps.scanned` fica fora até ter fonte coletada.

## 5. Segurança e operação
Inalterados e cobertos por teste: backend em 127.0.0.1; trava GET-only (novo caminho exato + testes de allowlist);
POST só na geração de relatório e só habilitado; isolamento entre clientes; **falha de backup continua bloqueando a
aprovação** (`test_backup_failure_blocks_approval_and_manual_backup_still_works`,
`test_io_error_during_backup_blocks_approval`); snapshots imutáveis; IA externa desligada; dados reais só em
`private/`.
