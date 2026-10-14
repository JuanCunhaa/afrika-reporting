# Devolutiva Claude → ChatGPT PO

- **Fase / branch / commit:** F01 / `main` (local) / **`84d0fb4`** (implementação) + commit seguinte só com STATUS/handoff. Repositório inicializado localmente nesta fase; o primeiro commit inclui o baseline F00. **Nada publicado**, sem remote.
- **Recomendação:** aprovar F01 **condicionada** a uma execução verde do CI no GitHub (hoje NOT_RUN) — localmente todos os gates passaram.

## 1. Resumo do que foi implementado
- Cadastro persistente (SQLite) de **conexões**, **clientes** e **subclientes**, substituindo a lista em memória da F00.
- Cliente: UUID v4 imutável, `name`, `display_name` (padrão = name), `description` opcional, `is_active`, `report_mode` (`consolidated` | `per_subclient` | `both`), `connection_id` opcional, `created_at`/`updated_at` (UTC).
- Subcliente: vínculo obrigatório e **imutável** a um cliente, UUID, nome/exibição/status, `connection_id` opcional (sobrescrita). Resposta traz `effective_connection` + `connection_source` (`subclient` | `client` | `none`) e `effective_active` (= ativo **e** cliente ativo).
- Hierarquia fixa em 2 níveis: a tabela `subclients` não tem auto-referência; usar o UUID de um subcliente como pai retorna **400 `nested_subclient_not_allowed`**; campos como `parent_id` → 422.
- Conexão: só metadados (`name`, `description`, `region` commercial/european/federal) + `credential_ref` no formato `env:NOME`. **Nenhum campo de segredo existe**; valores com cara de chave (hex ≥ 24) são recusados.
- Unicidade de nome **sem diferenciar caixa, inclusive acentos** (`name_key` = NFKC + casefold): cliente e conexão globais; subcliente por cliente (mesmo nome permitido em clientes distintos).
- Exclusão segura (prioriza desativação): entidade **ativa** não pode ser excluída (409); cliente **com subclientes** → 409 `client_has_subclients` (FK RESTRICT reforça no banco); conexão **em uso** → 409. Desativar cliente **não sobrescreve** o status gravado dos subclientes.
- Frontend: listagem com busca/filtro/paginação, cadastro, edição, detalhe, subclientes (CRUD), ativar/desativar, modo de relatório, conexão herdada/sobrescrita, tela de conexões, estados de carregamento/vazio/erro, validação de formulário + erros do servidor no campo.
- CLI local: `migrate`, `db-status`, `seed-demo` (seed sintético da F00 **somente por comando**, idempotente). App **recusa iniciar** sem banco/migrations — não cria nada sozinho.

## 2. Arquivos principais
| Arquivo | Papel |
|---|---|
| `backend/app/db.py` | engine (FK ON, `hide_parameters`), sessões, Alembic programático, `assert_schema_ready` |
| `backend/app/orm.py` | modelos SQLAlchemy, `name_key`, `UTCDateTime` |
| `backend/app/schemas.py` | Pydantic (entrada `extra='forbid'`, PATCH sem `null` em campos obrigatórios, validação `credential_ref`) |
| `backend/app/registry.py` | regras de negócio (unicidade, herança, exclusão segura) |
| `backend/app/api.py` | rotas REST |
| `backend/app/errors.py` | formato de erro único, sem eco de `input` |
| `backend/app/main.py` | `create_app()` + lifespan fail-fast; health/demo F00 mantidos |
| `backend/app/cli.py`, `seed.py` | comandos locais e seed sintético |
| `backend/alembic.ini`, `backend/migrations/**` | migrations versionadas |
| `backend/tests/*.py` | 53 testes |
| `frontend/src/{api.ts,ui.tsx,forms.tsx,main.tsx,pages/*}` | UI funcional |
| `frontend/e2e/{registry,smoke}.spec.ts`, `playwright.config.ts` | E2E isolado (banco descartável, portas 8010/5183) |
| `.github/workflows/ci.yml` | + job `e2e` (Chromium) |
| `backend/requirements.txt` | + `sqlalchemy>=2.0.40,<3`, `alembic>=1.16,<2` (exigidos pela ordem) |
| `.gitignore` | + `data/`, `.e2e-data/` |
| `README.md`, `docs/SECURITY.md`, `scripts/check_repo.py`, `prompts/F01_CLIENTS.md` | docs, checagem, cópia da ordem |

## 3. Migrations
- `backend/migrations/versions/20261014_0001_registry.py` — revisão **`0001_registry`** (base → head): tabelas `connections`, `clients`, `subclients`; PK/UK/FK/CHECK nomeados; FKs `ON DELETE RESTRICT`; índices em `connection_id`. `downgrade` remove o esquema F01 (só por comando explícito).
- Caminho de atualização disponível: F00 não tinha banco ⇒ o único caminho é base → `0001`. Testados: banco novo, round-trip downgrade/upgrade, upgrade repetido sobre banco com dados (preserva), banco desatualizado ⇒ app recusa iniciar.

## 4. Endpoints (prefixo `/api`; OpenAPI em `/docs`)
| Método | Rota | Notas |
|---|---|---|
| GET | `/health` | `{"phase":"F01","auth":"none"}` |
| GET | `/demo/metrics` | F00, sintético (inalterado) |
| GET/POST | `/connections` | lista paginada / cria (201) |
| GET/PATCH/DELETE | `/connections/{id}` | DELETE 409 se em uso |
| GET/POST | `/clients` | `limit`(1–200, padrão 50), `offset`, `status`=all/active/inactive, `q` |
| GET/PATCH/DELETE | `/clients/{id}` | DELETE 409 se ativo ou com subclientes |
| GET/POST | `/clients/{id}/subclients` | 400 se `{id}` for subcliente |
| GET/PATCH/DELETE | `/subclients/{id}` | DELETE 409 se ativo |

Erros: `{"error":{"code","message","details":[{"field","message","type"}]}}` — 400 (JSON malformado, `connection_not_found`, `nested_subclient_not_allowed`), 404, 409 (`duplicate_name`, `client_active`, `client_has_subclients`, `subclient_active`, `connection_in_use`), 422 (schema/UUID/campos extras).

## 5. Comandos (Windows / PowerShell, a partir da raiz)
```powershell
.\.venv\Scripts\Activate.ps1
pip install -r backend/requirements-dev.txt
python -m pytest -q
cd backend; python -m app.cli migrate; python -m app.cli seed-demo   # seed é opcional
uvicorn app.main:app --reload --port 8000
# outro terminal
cd frontend; npm ci; npm run dev                                     # http://localhost:5173
# E2E
cd frontend; npx playwright install chromium; $env:PYTHON="..\.venv\Scripts\python.exe"; npm run test:e2e
```

## 6. Resultados dos testes (2026-10-14, Windows 11)
| Comando | Resultado |
|---|---|
| `python -m pytest -q` (raiz e `backend/`), Py 3.14.7 | **PASS 53/53** (api 5, clients 11, connections 17, db_migrations 7, persistence 1, secrets 3, subclients 9); 1 warning de depreciação (Starlette/httpx, já existia na F00) |
| `python scripts/check_repo.py` | **PASS** |
| `npm run build` (`tsc -b && vite build`) | **PASS** (0 erros TS) |
| `npm run test:e2e` — Chromium do Playwright v1248, `CI=1` | **PASS 5/5** (2 execuções completas) |
| `ci.yml` via `yaml.safe_load` | **PASS** (jobs: backend, frontend, e2e) |
| Processo real: uvicorn sem banco | recusa iniciar com `SchemaNotReadyError … python -m app.cli migrate`; **não cria** o arquivo |
| `alembic -c backend/alembic.ini upgrade head` / `current` da raiz | **PASS** (`0001_registry (head)`) |

Cobertura dos 11 itens obrigatórios: (1) `test_clients` + E2E; (2) `test_subclients` + E2E; (3) `test_persistence` (uvicorn em subprocesso, reinicia e relê); (4) `test_db_migrations::test_foreign_keys_enforced_at_database_level`; (5) `test_connection_inheritance_and_override` + E2E; (6) `test_no_subclient_inside_subclient`; (7) `test_delete_rules_prefer_deactivation`, `test_connection_in_use_cannot_be_deleted` + E2E; (8) validações em todos os arquivos; (9) `test_secrets` + logs do servidor real em `test_persistence`; (10) `registry.spec.ts` (4 testes); (11) `test_api.py` + `smoke.spec.ts`.

## 7. E2E e CI
- E2E local: **PASS** com Chromium (não depende do Edge). Banco descartável por execução em `frontend/.e2e-data/`; `reuseExistingServer: false` (não toca no banco do usuário).
- CI GitHub: **NOT_RUN** — sem remote (proibido publicar). Job `e2e` usa as mesmas actions pinadas por SHA da F00 (`setup-python` v7.0.0 conferido via `git ls-remote`).
- Python 3.11: **NOT_VERIFIED** localmente (só 3.14 instalado); código sem sintaxe 3.12+; coberto pela matriz do CI.

## 8. Evidências de segurança
- Testes com sentinela sintética (chave hex 128 chars) enviada em `credential_ref`, `api_key`, `secret`, `hmac`, `password`, `connection_id`: sempre 422, **valor ausente da resposta** e dos logs (in-process com `sqlalchemy.engine` em DEBUG e logs do uvicorn `--log-level debug` em subprocesso).
- Nenhuma resposta de leitura contém chaves `secret/api_key/password/token/hmac`.
- Parâmetros SQL ocultos (`hide_parameters=True`), inclusive em `IntegrityError`. Erro 500 genérico; log só com tipo da exceção.
- Commit: varredura `git grep` nos arquivos staged (hex ≥ 40, private key, AKIA, ghp_, xox, e-mails) **sem ocorrências**; sem `.db/.sqlite/.pptx/.pdf/.csv/.png/.env` versionados. Evidências PNG (sintéticas) em `frontend/test-results/evidence/f01-*.png` — gitignored.
- CORS: só `http://localhost:5173` (métodos GET/POST/PATCH/DELETE); origem externa sem `Access-Control-Allow-Origin` (teste).

## 9. Limitações, riscos e pendências
- **API sem autenticação** — somente uso local; documentado em README, SECURITY, OpenAPI e rodapé da UI.
- **Achado:** com `sqlalchemy.engine` em DEBUG, o SQLAlchemy loga **linhas de resultado** (nomes de clientes); `hide_parameters` cobre só parâmetros. Padrão é WARNING; documentado em SECURITY. Não há trava em código.
- **`.env.example` NÃO foi commitado:** a regra `deny` do projeto me impede de lê-lo, e não versiono arquivo não revisado. Está untracked — o usuário deve revisar e commitar.
- `credential_ref` só define o **formato** (`env:NOME`); a resolução para `NOME_API_ID/NOME_API_KEY` e a verificação de que a variável existe são escopo F02 (proposta, não decidida).
- Exclusão de subcliente/cliente inativo sem subclientes é **física** (nada os referencia na F01). Quando F03/F05 criarem referências (escopos/snapshots), as FKs RESTRICT bloquearão — confirmar política com o PO.
- `per_subclient` em cliente sem subclientes é permitido (com aviso na UI), não bloqueado.
- Sem lock de versões Python (ranges); SQLAlchemy 2.1.4 local. Warning Starlette/httpx persiste.
- Licença: **não resolvida** (PUBLISHING_BLOCKERS 1–2 abertos). Commits têm autor = git config local do usuário.
- Primeiro commit mistura baseline F00 + F01 (não havia git antes).

## 10. Commit
`84d0fb4` — "F01: cadastro persistente de clientes, subclientes e conexões" (+ commit de documentação STATUS/handoff em seguida).

## 11. Recomendação
Aprovar F01 após: (a) PO/usuário revisar e commitar `.env.example`; (b) primeiro push privado com CI verde (backend 3.11/3.14, frontend, e2e). Nenhum bloqueio técnico local conhecido.

## Próxima fase sugerida (NÃO executada)
> F02 — conectores Veracode somente leitura. Pré-requisitos: aceite F01; decidir convenção de resolução de `credential_ref` (`env:NOME` → `NOME_API_ID`/`NOME_API_KEY`) e região → host. Escopo: cliente HMAC read-only com paginação/retries 429/5xx, fixtures **sintéticas** de replay, nenhum segredo em logs, smoke real **só com autorização expressa** e conta de permissões mínimas.

## Perguntas ao PO
1. Exclusão física de cliente/subcliente inativo sem dependências é aceitável, ou deve ser sempre lógica (arquivamento)?
2. Confirmar convenção `env:NOME` para referências de credencial (vs. Windows Credential Manager) antes da F02.
