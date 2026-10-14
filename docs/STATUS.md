# Estado do projeto

- F00: DONE_LOCAL
- F01 — clientes/subclientes: DONE_LOCAL — aprovada localmente pelo PO
- **F01.1 — hardening e CI: DONE_LOCAL — aguardando PO** (commit `98270d4`; CI GitHub NOT_RUN — sem remote)
- F02 — conectores Veracode: NOT_STARTED — **não iniciar sem ordem do PO**
- F03 — escopos: NOT_STARTED
- F04 — métricas: NOT_STARTED
- F05 — snapshots/auditoria: NOT_STARTED
- F06 — slides/templates: NOT_STARTED (template oficial pendente)
- F07 — exportação HTML/PPTX/PDF: NOT_STARTED
- F08 — interpretação por IA: NOT_STARTED
- F09 — homologação: NOT_STARTED

## Checkpoint F01.1 (2026-10-14)
- pytest **59 passed** (Py 3.14.7) no `.venv` e num venv novo instalado só pelo lock; E2E Chromium **9 passed** (inclui 4 de API indisponível); build OK; `pip check` OK.
- Lock `backend/constraints.txt` resolve com wheels para CPython 3.11 e 3.14 (Linux/Windows). Execução em 3.11: NOT_VERIFIED localmente.
- Sem remote Git. Publicação pública BLOQUEADA (licença, titularidade, autenticação).
- `.env.example` ainda NÃO versionado: aguarda verificação pelo usuário (ver handoff).

Próxima autorização esperada: aceite F01.1, push privado com CI verde e prompt F02 do PO.
