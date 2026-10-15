# Motor de escopos e filtros — F03

Código: `backend/app/scopes/` (`rules.py` motor puro, `store.py` persistência versionada, `resolver.py` resolução),
`backend/app/api_scopes.py`, migration `0002_scopes`; UI: `frontend/src/pages/ScopesPage.tsx` (`#/scopes/clients/{id}`).

## Modelo
- **Escopo** = (dono, domínio). Dono: cliente principal **ou** subcliente. Domínios independentes:
  `applications`, `users`, `scans`, `sca`. Selecionar um Team em `users` **não** seleciona aplicações.
- `scope_definitions`: 1 por dono+domínio (`owner_key` = `client:<id>`/`subclient:<id>`), `status` `active`|`disabled`.
- `scope_versions`: **append-only**. `rule_json` canônico + `rule_hash` (SHA-256), `options_json`, `connection_mode`
  (`client`/`shared`/`separate`/`none`, gravado no momento do salvamento), `coverage_ack`, `note`, `created_at`.
  Status `active` → `superseded` (único sentido permitido). Gatilhos SQLite impedem alterar conteúdo, reativar
  versão substituída e excluir versões; índice único parcial garante 1 versão ativa por definição. FK `RESTRICT`
  impede excluir cliente/subcliente com escopos (histórico preservado).
- Nada de recursos Veracode no banco: a regra guarda só IDs e valores de filtro. Nomes vêm da descoberta (cache
  transitório em memória, isolado por escopo + conexão + impressão da credencial — F02).

## Regras (AST JSON)
```json
{"op": "or", "args": [
  {"op": "and", "args": [
    {"field": "business_unit.id", "cmp": "eq", "value": "<guid>"},
    {"op": "not", "arg": {"field": "tag", "cmp": "in", "values": ["web"]}}]},
  {"field": "custom_field", "key": "Ambiente", "cmp": "eq", "value": "Produção"}]}
```
- Grupos: `and`, `or` (1–40 condições), `not` (`arg`), `all` (universo disponível).
- Comparações: `eq`, `neq`, `contains`, `not_contains` (`value`); `in`, `not_in` (`values`);
  `is_missing`, `is_present`, `is_empty` (sem valor). Campos multivalorados (`team.id`, `tag`, `policy.id`,
  `custom_field`): `eq`/`in` = contém algum; `neq`/`not_in` = não contém nenhum.
- Campos por domínio (catálogo em `GET /api/scopes/fields`):

| Domínio | Campos |
|---|---|
| applications | `application.id`, `business_unit.id`, `team.id`, `name`, `tag`, `business_criticality`, `custom_field` (+`key`), `policy.id` |
| users | `user.id`, `team.id` (vínculo pelo detalhe do Team), `active` |
| scans | `application.id`, `application.in_scope`, `scan.context` (`policy`/`sandbox`), `scan.type` — só validação |
| sca | `application.id`, `application.in_scope`, `sca.dependency` (`direct`/`transitive`) — só validação |

- Relacionamentos **sempre por ID** (`*.id` exige GUID/UUID; nome no lugar de ID é recusado). `name` é critério
  textual, nunca identidade. Item sem ID na resposta Veracode (ex.: Team sem `guid`) torna a lista desconhecida.
- Canonização: IDs minúsculos, listas sem duplicatas e ordenadas, chaves ordenadas → hash estável.
- **Limites anti-abuso** (validação antes de qualquer avaliação): profundidade 6, 120 nós, 40 condições por grupo,
  500 valores por lista, 2000 valores por regra, 200 caracteres por texto, 64 KB por regra; chaves extras/ausentes,
  caracteres de controle e tipos errados → 422 com caminho (`rule.args[2].value`).

## Campos ausentes — lógica de 3 valores (Kleene)
Valor ausente (`null`) → comparação **indeterminada**; `AND` (falso decide), `OR` (verdadeiro decide), `NOT`
(indeterminado continua indeterminado). Lista vazia conhecida (`[]`) ≠ ausente. Indeterminado **não é incluído**:
é contado à parte com os campos que faltaram (`missing_fields`). Vínculo parcial (`Partial`, usuário em Team não
visível) prova presença, não ausência. Propriedades (equivalência com min/max sobre {0,½,1}, De Morgan, dupla
negação, `all` neutro/absorvente) testadas com 400 regras geradas deterministicamente.

## Semântica da resolução (`POST /api/scope-preview/clients/{id}`)
1. O cliente principal define o **universo** do domínio. Sem versão ativa → `universe_not_defined` (nunca
   "tenant inteiro" implícito). "Todo o tenant" só por regra explícita `{"op":"all"}`.
2. Subcliente com a **mesma conexão** (herdada ou a mesma conexão cadastrada): critérios próprios ∩ universo
   (`outside_universe` informado). Excluídos são medidos dentro do universo.
3. Subcliente com **conexão própria diferente** (`separate`): salvar exige `coverage_ack=true`; avaliado só no
   próprio tenant, sem interseção; fora das não classificadas e da sobreposição. Se a conexão mudar de/para
   `separate` depois do salvamento → `connection_changed` (exige nova versão). Tenants nunca são misturados.
4. Recursos podem estar em vários subclientes: sobreposição reportada (contagem, pares, amostra) e preservada.
5. **Não classificadas** = universo − ∪(subclientes **ativos** com a mesma conexão), por identificador.
   `complete=false` com motivos se houver: coleta incompleta, indeterminados (universo/subclientes), subclientes
   ativos sem escopo, abrangência não confirmada, conexão alterada. Sem subclientes: `no_subclients=true`.
6. Usuários: regra padrão **inativos excluídos** da contagem e reportados à parte (`inactive_excluded`);
   configurável por versão (`options.inactive_users`: `exclude`|`include`). `active` ausente com `exclude` →
   indeterminado. "Usuários únicos por Team": dedup por `user_id`; por Team só quando o detalhe do Team foi obtido;
   total só com coleta completa (senão `null` + motivo).
7. Coleta Veracode incompleta → `status=incomplete`, `complete=false`; a UI mostra "não validado".
8. Scans/SCA: `status=deferred_f04` — nenhuma consulta à Veracode.

## Reconciliação usuário–Team (correção F02.1)
`team_count` do membro do Team (API real: presente em 100% dos vínculos do tenant de testes; ausente na lista de
usuários — usado se vier) é comparado com os vínculos coletados por usuário:
`verified` (igual), `missing_teams` (maior: Teams não visíveis → vínculo `Partial`), `inconsistent`,
`unverifiable` (sem `team_count`, ex.: usuário sem Team visível), `collection_incomplete`.
Resumo: `verified` | `partial` | `unverifiable` | `mismatch` | `collection_incomplete`, com motivo. Limitação:
usuário que só pertence a Teams invisíveis aparece sem Team e `unverifiable` (nenhum membro visível traz o número).

## API interna (local, sem autenticação, só loopback)
`GET /api/scopes/fields` · `POST /api/scopes/validate` · `GET /api/scopes/clients/{id}` (visão geral) ·
`GET|PUT|PATCH /api/scopes/{clients|subclients}/{id}/{domain}` · `POST …/versions/{n}/restore` ·
`POST /api/scope-preview/clients/{id}` (`{domain, draft?, sample_limit≤200}`; rascunho não é gravado).
`PUT` exige `expected_version` (versão ativa atual; 0 se nenhuma) → 409 `version_conflict` se divergir; regra
canonicamente idêntica → 200 `created=false`; nova → 201. Erros: 422 `invalid_rule`/`invalid_options` (com
detalhes), 409 `coverage_ack_required`/`version_conflict`, 404, 400 `draft_owner_mismatch`.

## Interface
Modo simples (BU, Teams, criticidade, tags, aplicações; usuários por Teams; scans/SCA por contexto/dependência):
`(BU E Teams E criticidade E tags) OU aplicações`. Modo avançado: grupos E/OU, NÃO por nó, condições por campo,
validação antes de salvar (salvar fica desabilitado com regra inválida). Pré-visualização: incluídos, excluídos,
indeterminados, não classificados, sobreposição, usuários únicos por Team, avisos; estados carregando/erro/coleta
incompleta. Histórico de versões com "Restaurar como nova versão".
