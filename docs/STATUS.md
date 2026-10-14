# Estado do projeto

- F00: DONE_LOCAL (validada em Windows 11 em 2026-10-14; aceite implícito pela ordem F01 do PO)
- F01 — clientes/subclientes: **DONE_LOCAL — aguardando aceite do PO** (commit `84d0fb4`; CI GitHub NOT_RUN — sem remote)
- F02 — conectores Veracode: NOT_STARTED — **não iniciar sem ordem do PO**
- F03 — escopos: NOT_STARTED
- F04 — métricas: NOT_STARTED
- F05 — snapshots/auditoria: NOT_STARTED
- F06 — slides/templates: NOT_STARTED (template oficial pendente)
- F07 — exportação HTML/PPTX/PDF: NOT_STARTED
- F08 — interpretação por IA: NOT_STARTED
- F09 — homologação: NOT_STARTED

## Checkpoint F01 (2026-10-14)
- Backend: `python -m pytest -q` → **53 passed** (Python 3.14.7, SQLAlchemy 2.1.4, Alembic 1.20.0, SQLite 3.50.4). Python 3.11 NOT_VERIFIED localmente (matriz do CI, não executada).
- Frontend: `npm run build` → OK. E2E Playwright **Chromium** (v1248, Playwright 1.64.1) → **5 passed**.
- Migrations: banco novo → head; downgrade base → upgrade head; upgrade idempotente preserva dados; ORM == migration (`compare_metadata` vazio).
- API local **sem autenticação** — não expor publicamente.
- Detalhes: `docs/AGENT_HANDOFF.md`. Ordem da fase: `prompts/F01_CLIENTS.md`.

Próxima autorização esperada: aceite F01 + prompt F02 do PO. Não antecipar F02.
