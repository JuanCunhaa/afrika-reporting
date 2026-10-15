# Integração Veracode — F02 (descoberta, somente leitura)

Código: `backend/app/veracode/` + `backend/app/api_veracode.py`; UI: `frontend/src/pages/VeracodePage.tsx`.
Estado: **homologada contra tenant REAL de testes em 2026-10-14 (F02.1, somente GET)** — matriz em “Homologação real (F02.1) — resultado”.

## Autenticação (HMAC)
- Esquema `VERACODE-HMAC-SHA-256`, implementado a partir da documentação oficial
  ([Enabling HMAC](https://docs.veracode.com/r/c_enabling_hmac), [exemplo oficial de assinatura](https://docs.veracode.com/r/Example_SRM_script_for_HMAC_signing)):
  `data = id={api_id}&host={host}&url={path+query}&method={GET}`; cadeia HMAC-SHA256 `chave(hex) → nonce(16 bytes) → timestamp(ms) → "vcode_request_version_1" → data`;
  header `VERACODE-HMAC-SHA-256 id=…,ts=…,nonce=…,sig=…`. Nonce e timestamp novos a cada envio (inclusive retries).
- Referência da conexão (F01) `env:NOME` → variáveis de ambiente do backend `NOME_API_ID` e `NOME_API_KEY`.
  Validação explícita: formato da referência, presença dos dois valores, hexadecimal (chave com nº par de dígitos).
- Conexão efetiva: subcliente com conexão própria = **sobrescrita**; sem conexão própria = **herda** a do cliente.
- Nunca: credencial no SQLite, no frontend, em logs, em chaves/valores de cache ou em respostas — nem os nomes
  `NOME_API_ID`/`NOME_API_KEY`. `Credentials.__repr__` é mascarado.

## Endpoints Veracode usados (todos GET)
Especificações oficiais: [Applications API 1.0](https://app.swaggerhub.com/apis/Veracode/veracode-applications-api-specification/1.0),
[Identity API 1.5](https://app.swaggerhub.com/apis/Veracode/veracode-identity_api/1.5). Hosts por região: `api.veracode.com` (commercial), `api.veracode.eu` (european), `api.veracode.us` (federal).

| Recurso | Endpoint | Coleção HAL | Observações |
|---|---|---|---|
| Aplicações | `/appsec/v1/applications?page&size` | `applications` | `size` máx. 500. Perfil: `business_unit` (**uma** por aplicação), `teams[]`, `tags`, `custom_fields`, `business_criticality`, `policies` |
| Sandboxes | `/appsec/v1/applications/{guid}/sandboxes?page&size` | `sandboxes` | sob demanda, por aplicação |
| Business Units | `/api/authn/v2/business_units?page&size` | `business_units` | `teams[]` quando presente |
| Teams | `/api/authn/v2/teams?all_for_org=true&page&size` | `teams` | **sem `user_count` na API real**; sem `all_for_org` só vêm os Teams do chamador ([suporte Veracode](https://community.veracode.com/s/question/0D53n00007d4TivCAE/identity-api-teams-endpoint-only-returns-teams-that-caller-is-a-member-of-)); conta restrita recebe 403 → reportado, sem recair para lista parcial |
| Detalhe do Team | `/api/authn/v2/teams/{team_id}` | — | `users[]` (UserTeam) → relação usuário↔Team; `relationship` real = objeto `{name, display_name}` (spec: string; ambos aceitos); `user_count` ausente na API real ⇒ conferência só quando presente |
| Usuários | `/api/authn/v2/users?page&size` | `users` | parâmetros padrão da API (`deleted`/`inactive` = false); **sem `account_type` na lista real** |
| Teste de conexão | os 4 endpoints de lista com `size=1` | — | identifica permissão por domínio |

Campos mantidos após normalização (minimização): aplicações (guid, id legado, nome, BU, Teams, tags, criticidade,
custom fields, políticas, datas); usuários (user_id, user_name, nome, ativo, login habilitado, tipo de conta).
**E-mail, telefone, IP e dados de login são descartados no backend.** Campo ausente = `null` ("desconhecido"), nunca zero/lista vazia presumidos.

### Limitações conhecidas
- `page`: real = snake_case nas duas APIs (Identity inclusive, embora a spec 1.5 declare camelCase); camelCase segue aceito.
- Correspondência perfil-da-aplicação ↔ Identity API **somente por ID** (`teams[].guid` == `team_id`,
  `business_unit.guid` == `bu_id`; ou IDs legados). Nunca por nome. Sem correspondência ⇒ `identity_match=false`.
- `all_for_org` documentado só pelo suporte (não consta na especificação 1.5); aceito pela API real (sem 403).
- Aplicação tem **uma** BU no perfil Veracode; "aplicação em várias BUs" só existe entre escopos (subclientes) — regra da F03.
- Relação usuário↔Team exige 1 requisição por Team (concorrência limitada).
- Sem `user_count` na API real, a completude da relação usuário↔Team depende só do sucesso de cada detalhe de Team
  (o detalhe traz `team_count` por usuário — **F03: reconciliação implementada**, ver `docs/SCOPES.md`).
- F03 (validação real opt-in, `tests_live/test_scopes_live.py`): `team_count` presente em 100% dos membros de Team
  e ausente na lista de usuários; reconciliação `verified` para 100% dos usuários do tenant de testes; motor de
  escopos sem indeterminados em BU/Teams nas aplicações reais. Contagens só no relatório ao PO.

## Cliente HTTP, paginação, retry e rate limit
- `httpx.AsyncClient` por região (conexões reutilizadas), TLS validado, sem redirects, sem cookies, **somente GET** em host oficial e endpoint da allowlist (ver “Trava somente leitura”). Páginas calculadas localmente; `_links` não são seguidos.
- Paginação até `total_pages`; sem metadados, até página curta. Coleta **incompleta** se: erro em qualquer página, total mudou entre páginas, duplicatas, contagem ≠ `total_elements`, página vazia com itens pendentes, orçamento ou prazo esgotados.
- Retry: 429, 500, 502, 503, 504, timeout e erro de rede. Backoff exponencial com *full jitter* (`uniform(0, min(max, base·2^n))`). 429 com `Retry-After` (segundos ou data HTTP): espera o valor + jitter; acima de `max_retry_after` desiste sem esperar. 401/403/404/outros 4xx: sem retry.
- Limites (variáveis `AFRIKA_VERACODE_*`): `CONNECT_TIMEOUT`=5s, `READ_TIMEOUT`=30s, `MAX_RETRIES`=3, `BACKOFF_BASE`=0.5s, `BACKOFF_MAX`=8s, `MAX_RETRY_AFTER`=30s, `MAX_CONCURRENCY`=4 (processo), `MAX_REQUESTS_PER_COLLECTION`=300, `COLLECTION_TIMEOUT`=120s, `PAGE_SIZE`=100 (≤500), `CACHE_TTL`=300s, `CACHE_MAX_ENTRIES`=256, `MODE`=`live`|`fixture`.
- Cancelamento: `asyncio.CancelledError` propaga; semáforo e conexão liberados; nada é cacheado. Limitação: desconexão do navegador não interrompe uma coleta em andamento (ela termina dentro do prazo/orçamento).

## Cache de descoberta
Memória do processo (nada em disco). Chave = escopo (tipo+id) + conexão (id, região, referência) + impressão digital
da credencial (HMAC-SHA256 com sal aleatório do processo, truncado — irreversível) + recurso + parâmetros.
Só coletas **completas** entram; incompletas são refeitas. TTL configurável (0 desativa), LRU, single-flight,
invalidação manual por escopo (`DELETE …/cache`). Não substitui snapshots (F05).

## API interna (local, sem autenticação, só loopback)
Prefixo `/api/veracode/{clients|subclients}/{id}`:
`GET` (conexão efetiva + estado da credencial), `POST /test`, `DELETE /cache`, `GET /applications`,
`GET /applications/{guid}/sandboxes`, `GET /business-units`, `GET /teams`, `GET /users`,
`GET /relationships/applications`, `GET /relationships/users`, `GET /metadata`.
Listas: `q`, `limit` (≤200), `offset`; resposta com `complete` e `collections[]` (status, motivo, páginas, totais, requisições, retries, cache).
Erros: 409 (conexão/credencial), 502 (401/403/404/429/5xx/resposta inválida da Veracode), 504 (tempo), 404 (escopo).

## Modo fixture e testes
`AFRIKA_VERACODE_MODE=fixture` usa `app/veracode/fixtures.py`: tenants **sintéticos** em processo (alpha: 120 apps/4 BUs/8 Teams/45 usuários; beta; denied = 403 na Identity) que validam a assinatura HMAC. Usado pelos testes e pelo E2E. Nunca é o padrão.
Integração real opt-in (fora do CI): `backend/tests_live/` (16 testes) — instruções no cabeçalho do arquivo; imprime só contagens e nomes de chaves do schema.

## `.env` local e trava somente leitura (F02.1)
- `app/env_loader.py` carrega `<raiz>/.env` (caminho absoluto derivado do código, independente do cwd) no
  `app.main` e no `app.cli`, via `python-dotenv` sem interpolação. **Variável já definida no sistema (mesmo vazia)
  prevalece.** `AFRIKA_DOTENV_DISABLED=1` desativa (a suíte unitária e o E2E sempre desativam).
- Credenciais de teste: `AFRIKA_VC_TEST_API_ID`/`AFRIKA_VC_TEST_API_KEY`, referência `env:AFRIKA_VC_TEST`
  (`AFRIKA_VC_TEST_CONNECTION`). Modelo em `.env.example`; `.env` é ignorado pelo Git.
- **Trava somente leitura** (`app/veracode/readonly.py`), em duas camadas (event hook do httpx + transporte que
  envolve o transporte real): só `GET`, só `https` porta 443 em `api.veracode.{com,eu,us}`, só os caminhos da
  allowlist (applications, sandboxes de uma aplicação, business_units, teams, detalhe de Team, users). Qualquer
  outro método/host/caminho levanta `ReadOnlyViolation` antes da rede e não é repetido.
- `VERACODE_READ_ONLY`: ausente ou `true` → ok; qualquer outro valor (`false`, inválido) → `SettingsError` e o
  backend **não inicia**. Não existe configuração que habilite escrita. Privilégios mínimos na conta Veracode
  continuam obrigatórios (a trava do código não substitui o controle de acesso da plataforma).
- Limitação: se `HTTPS_PROXY` estiver definido, o httpx monta um transporte de proxy que não passa pela camada de
  transporte; o event hook continua aplicando a mesma política a toda requisição do cliente.

## Homologação real opt-in (F02.1)
Portão em `app/veracode/live_gate.py`; os testes só executam se **todas** valerem: `--run-veracode-live` na linha
de comando, `VERACODE_LIVE_TESTS_ENABLED=true`, `VERACODE_READ_ONLY` true/ausente e credenciais válidas na
referência. Caso contrário, todos são *skipped* com motivo que cita só nomes de variáveis.
```powershell
python -m pytest backend/tests_live -q -rs --run-veracode-live   # rodar SEPARADO da suíte unitária
```
Escopo: autenticação (`size=1`), formato de `page`/`_embedded`, descoberta (applications, business_units, teams,
users, membros de Team), paginação multipágina forçada, relações por ID, sandboxes de uma amostra de 3
aplicações e metadados de filtro. **Nenhum finding.** Execução completa ≈ 75 GETs. Orçamento padrão de 25 requisições por coleta (ajustável por
`AFRIKA_VERACODE_MAX_REQUESTS_PER_COLLECTION`). Região: `AFRIKA_VC_TEST_REGION` (padrão `commercial`).

## Homologação real (F02.1) — resultado
2026-10-14, região `commercial`, conta de API de TESTE; somente GET (trava read-only ativa); orçamento 25
req/coleta; flag `VERACODE_LIVE_TESTS_ENABLED=true` só no ambiente do processo (o `.env` não foi alterado).
Contagens do tenant **não** são versionadas (repo público): ficam no relatório ao PO.

| # | Domínio | Estado | Evidência (formato/consistência, sem valores) |
|---|---|---|---|
| 1 | Autenticação HMAC | VERIFIED_REAL | 200 com a credencial atual; assinatura idêntica (200/200) à implementação oficial da Veracode (`veracode-dast-action`). A 1ª credencial foi rejeitada (401 “API ID … is invalid for user”) e substituída pelo usuário — causa externa |
| 2 | Aplicações | VERIFIED_REAL | coleta completa; itens == `total_elements`; `_embedded.applications` |
| 3 | Paginação | VERIFIED_REAL (Applications) / VERIFIED_MOCK_ONLY (Identity multipágina) | Applications em várias páginas (tamanho padrão e forçado), sem duplicatas; Identity coube em 1 página |
| 4 | Business Units | VERIFIED_REAL | `_embedded.business_units`; `teams[]` presente |
| 5 | Teams | VERIFIED_REAL | `_embedded.teams`; `all_for_org=true` aceito (mesma contagem com e sem — efeito não distinguível neste tenant); `user_count` ausente |
| 6 | Usuários | VERIFIED_REAL | `_embedded.users`; `account_type` ausente; e-mail descartado na normalização |
| 7 | Aplicação → BU | VERIFIED_REAL | 100% das BUs do perfil casam com a Identity por `guid` |
| 8 | Aplicação → Teams | VERIFIED_REAL | 100% das referências casam por `guid`; aplicação com vários Teams: VERIFIED_MOCK_ONLY (inexistente no tenant) |
| 9 | Usuário → Teams | VERIFIED_REAL (após correção) | coleta completa; 0 membros fora da lista de usuários; `relationship` objeto ⇒ corrigido |
| 10 | Sandboxes | VERIFIED_REAL | amostra de 3 aplicações; `application_guid` confere em 100% |
| 11 | Metadados de filtro | VERIFIED_REAL | custom fields, tags, criticidade e políticas presentes; `account_type` removido dos filtros de usuários |
| — | 401/403/429/5xx, retry, região europeia/federal | VERIFIED_MOCK_ONLY | nenhum 403/429/5xx ocorreu; a europeia só recebeu 1 GET de diagnóstico (401, ID desconhecido) |

Diferenças mock × real corrigidas (commit `7c52d57`): `relationship` objeto; Team sem `user_count`; usuário sem
`account_type`; `page` snake_case na Identity. Campos reais não usados (não normalizados): `scim_team`,
`member_only`, `deleted`, `features`, `saml_user`, `scim_user`. `team_count` passou a ser normalizado na F03.

## Fica para F03/F04
- F03: **entregue** — `docs/SCOPES.md`. Nenhum endpoint novo na allowlist.
- F04: scans, findings, SCA, Reporting/Analytics, métricas e dedup — nada disso é coletado na F02.
