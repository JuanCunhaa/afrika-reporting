# Estado do projeto

- F00: DONE_LOCAL
- F01 — clientes/subclientes: DONE_LOCAL — aprovada localmente pelo PO
- F01.1 — hardening e CI: DONE_LOCAL — aprovada localmente pelo PO (`.env.example` versionado em `d71f39e`)
- **F02 — conector Veracode read-only + descoberta: DONE_LOCAL — aguardando PO** (commit `5fce8bf`; validado só com tenant sintético; integração real NOT_VERIFIED; CI GitHub **verde** em `7fcfc92`)
- **F02.1-prep — `.env` local + trava read-only + homologação opt-in: DONE_LOCAL — aguardando PO** (commit `d3fa15f`)
- **F02.1 — homologação real Veracode: DONE — aguardando PO** (commit `7c52d57` + docs; 11/11 domínios VERIFIED_REAL — paginação Identity multipágina e 403/429 só em mock; 1 incompatibilidade corrigida)
- F03 — escopos: NOT_STARTED — **não iniciar sem ordem do PO**
- F04 — métricas: NOT_STARTED
- F05 — snapshots/auditoria: NOT_STARTED
- F06 — slides/templates: NOT_STARTED (template oficial pendente)
- F07 — exportação HTML/PPTX/PDF: NOT_STARTED
- F08 — interpretação por IA: NOT_STARTED
- F09 — homologação: NOT_STARTED

## Checkpoint F02.1 (2026-10-14)
- Tenant REAL de testes (região `commercial`), somente GET; flag live só no ambiente do processo (`.env` intacto, `VERACODE_LIVE_TESTS_ENABLED=false` nele).
- 1ª credencial rejeitada pela Veracode (401 "API ID … is invalid for user") — causa externa; HMAC idêntico à implementação oficial (200/200). Usuário substituiu a credencial → 200.
- `tests_live` **16 passed** (real); pytest **213 passed** (201 + 12 regressões); E2E Chromium **14 passed**; build OK; `npm audit` 0; gitleaks (staged + histórico) 0.
- Correção: `relationship` do membro de Team é objeto na API real; fixture sintético alinhado ao formato real; `account_type` não é mais anunciado como filtro.
- Matriz por domínio: `docs/VERACODE_INTEGRATION.md` → "Homologação real (F02.1) — resultado". Contagens do tenant não versionadas (repo público).

Próxima autorização esperada: aceite da F02.1 pelo PO; depois prompt F03.

## Checkpoint F02.1-prep (2026-10-14)
- `.env` criado na raiz (ignorado pelo Git; nunca versionado — 0 commits no histórico); campos a preencher: `AFRIKA_VC_TEST_API_ID`, `AFRIKA_VC_TEST_API_KEY`.
- pytest **201 passed** (144 anteriores + 57 novos); `tests_live` 6 SKIPPED por padrão; E2E Chromium **14 passed**; build OK; `pip check` OK; gitleaks (staged) 0 achados.
- Testes reais: **NOT_RUN** (proibido nesta tarefa). Integração real: NOT_VERIFIED.

## Publicação pública (2026-10-14) — não é fase de produto
- Repo **público** https://github.com/JuanCunhaa/afrika-reporting (`origin`, branch `main`). Sem deploy.
- Licença: PolyForm Noncommercial 1.0.0 integral (blob `5ecc88c` = upstream tag `1.0.0`) + `NOTICE` (titular JuanCunhaa, declarado pelo usuário).
- Auditoria: gitleaks no histórico (8 commits) e na árvore HEAD — 0 achados; só dados sintéticos.
- CI GitHub run `38646957227` (SHA anterior à reescrita): **success**; histórico reescrito em 2026-10-14 só para remover trailers `Co-Authored-By` (árvores idênticas, SHAs novos) e CI reexecutado (Backend 3.11/3.14 144 passed cada; build OK; E2E 14 passed).

## Checkpoint F02 (2026-10-14)
- pytest **144 passed** (Py 3.14.7; `.venv` e venv novo só pelo lock) + 5 testes live opt-in SKIPPED; E2E Chromium **14 passed** (5 novos F02); build OK; `npm audit` 0 vulnerabilidades; `pip check` OK.
- Integração real com a Veracode: **NOT_VERIFIED** (sem credenciais autorizadas; nenhuma chamada real executada).
- Sem remote Git; CI GitHub NOT_RUN. Detalhes: `docs/AGENT_HANDOFF.md`, `docs/VERACODE_INTEGRATION.md`.


## Checkpoint F01.1 (2026-10-14)
- pytest **59 passed** (Py 3.14.7) no `.venv` e num venv novo instalado só pelo lock; E2E Chromium **9 passed** (inclui 4 de API indisponível); build OK; `pip check` OK.
- Lock `backend/constraints.txt` resolve com wheels para CPython 3.11 e 3.14 (Linux/Windows). Execução em 3.11: NOT_VERIFIED localmente.
- Sem remote Git. Publicação pública BLOQUEADA (licença, titularidade, autenticação).
- `.env.example` ainda NÃO versionado na época — resolvido em `d71f39e` (verificador: SEGURO).

