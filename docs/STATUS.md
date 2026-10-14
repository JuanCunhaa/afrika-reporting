# Estado do projeto

- F00: DONE_LOCAL
- F01 — clientes/subclientes: DONE_LOCAL — aprovada localmente pelo PO
- F01.1 — hardening e CI: DONE_LOCAL — aprovada localmente pelo PO (`.env.example` versionado em `5d41628`)
- **F02 — conector Veracode read-only + descoberta: DONE_LOCAL — aguardando PO** (commit `4339e27`; validado só com tenant sintético; integração real NOT_VERIFIED; CI GitHub **verde** em `7723846`)
- F03 — escopos: NOT_STARTED — **não iniciar sem ordem do PO**
- F04 — métricas: NOT_STARTED
- F05 — snapshots/auditoria: NOT_STARTED
- F06 — slides/templates: NOT_STARTED (template oficial pendente)
- F07 — exportação HTML/PPTX/PDF: NOT_STARTED
- F08 — interpretação por IA: NOT_STARTED
- F09 — homologação: NOT_STARTED

## Publicação pública (2026-10-14) — não é fase de produto
- Repo **público** https://github.com/JuanCunhaa/afrika-reporting (`origin`, branch `main`). Sem deploy.
- Licença: PolyForm Noncommercial 1.0.0 integral (blob `5ecc88c` = upstream tag `1.0.0`) + `NOTICE` (titular JuanCunhaa, declarado pelo usuário).
- Auditoria: gitleaks no histórico (8 commits) e na árvore HEAD — 0 achados; só dados sintéticos.
- CI GitHub run `38646957227` em `7723846`: **success** (Backend 3.11/3.14 144 passed cada; build OK; E2E 14 passed).

## Checkpoint F02 (2026-10-14)
- pytest **144 passed** (Py 3.14.7; `.venv` e venv novo só pelo lock) + 5 testes live opt-in SKIPPED; E2E Chromium **14 passed** (5 novos F02); build OK; `npm audit` 0 vulnerabilidades; `pip check` OK.
- Integração real com a Veracode: **NOT_VERIFIED** (sem credenciais autorizadas; nenhuma chamada real executada).
- Sem remote Git; CI GitHub NOT_RUN. Detalhes: `docs/AGENT_HANDOFF.md`, `docs/VERACODE_INTEGRATION.md`.

Próxima autorização esperada: aceite F02, smoke real autorizado (opt-in) e prompt F03 do PO.

## Checkpoint F01.1 (2026-10-14)
- pytest **59 passed** (Py 3.14.7) no `.venv` e num venv novo instalado só pelo lock; E2E Chromium **9 passed** (inclui 4 de API indisponível); build OK; `pip check` OK.
- Lock `backend/constraints.txt` resolve com wheels para CPython 3.11 e 3.14 (Linux/Windows). Execução em 3.11: NOT_VERIFIED localmente.
- Sem remote Git. Publicação pública BLOQUEADA (licença, titularidade, autenticação).
- `.env.example` ainda NÃO versionado na época — resolvido em `5d41628` (verificador: SEGURO).

