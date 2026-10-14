# Integração Veracode — F02 (descoberta, somente leitura)

Código: `backend/app/veracode/` + `backend/app/api_veracode.py`; UI: `frontend/src/pages/VeracodePage.tsx`.
Estado: **validada só com transporte simulado (tenant sintético)**. Integração real: **NOT_VERIFIED** (sem credenciais autorizadas nesta fase).

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
| Teams | `/api/authn/v2/teams?all_for_org=true&page&size` | `teams` | sem `all_for_org` só vêm os Teams do chamador ([suporte Veracode](https://community.veracode.com/s/question/0D53n00007d4TivCAE/identity-api-teams-endpoint-only-returns-teams-that-caller-is-a-member-of-)); conta restrita recebe 403 → reportado, sem recair para lista parcial |
| Detalhe do Team | `/api/authn/v2/teams/{team_id}` | — | `users[]` (UserTeam) → relação usuário↔Team; conferido com `user_count` |
| Usuários | `/api/authn/v2/users?page&size` | `users` | parâmetros padrão da API (`deleted`/`inactive` = false) |
| Teste de conexão | os 4 endpoints de lista com `size=1` | — | identifica permissão por domínio |

Campos mantidos após normalização (minimização): aplicações (guid, id legado, nome, BU, Teams, tags, criticidade,
custom fields, políticas, datas); usuários (user_id, user_name, nome, ativo, login habilitado, tipo de conta).
**E-mail, telefone, IP e dados de login são descartados no backend.** Campo ausente = `null` ("desconhecido"), nunca zero/lista vazia presumidos.

### Limitações conhecidas (NOT_VERIFIED contra tenant real)
- `page` da Identity API: especificação declara camelCase (`totalElements`/`totalPages`); Applications usa snake_case. Ambos aceitos.
- Chaves `_embedded` de Teams/BUs (`teams`, `business_units`) não aparecem na especificação 1.5; assumidas por padrão HAL. Chave inesperada ⇒ `invalid_response` (nunca lista vazia).
- Correspondência perfil-da-aplicação ↔ Identity API: `teams[].guid` == `team_id` e `business_unit.guid` == `bu_id` (ou IDs legados). **Nunca por nome.** Sem correspondência ⇒ `identity_match=false`, exibido na UI.
- `all_for_org` documentado só pelo suporte (não consta na especificação 1.5).
- Papéis mínimos da conta de API para cada endpoint: a confirmar na homologação (o teste de conexão mostra o 403 por domínio).
- Aplicação tem **uma** BU no perfil Veracode; "aplicação em várias BUs" só existe entre escopos (subclientes) — regra da F03.
- Relação usuário↔Team exige 1 requisição por Team (concorrência limitada).

## Cliente HTTP, paginação, retry e rate limit
- `httpx.AsyncClient` por região (conexões reutilizadas), TLS validado, sem redirects, sem cookies, **somente GET** (hook bloqueia outros métodos antes do envio). Páginas calculadas localmente; `_links` não são seguidos.
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
Integração real opt-in (fora do CI): `backend/tests_live/` — instruções no cabeçalho do arquivo; imprime só contagens.

## Fica para F03/F04
- F03: regras de escopo por domínio (applications/users/scans/SCA), AND/OR/NOT, sobreposição entre subclientes, `unclassified`, uso dos metadados descobertos.
- F04: scans, findings, SCA, Reporting/Analytics, métricas e dedup — nada disso é coletado na F02.
