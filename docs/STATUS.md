# Estado do projeto

- F00: **DONE_LOCAL — aguardando aceite do PO** (validada em Windows 11 local em 2026-10-14; CI GitHub ainda não executado em runner real — repo sem git/remote)
- F01 — clientes/subclientes: BLOCKED até aceite F00 pelo PO
- F02 — conectores Veracode: NOT_STARTED
- F03 — escopos: NOT_STARTED
- F04 — métricas: NOT_STARTED
- F05 — snapshots/auditoria: NOT_STARTED
- F06 — slides/templates: NOT_STARTED (template oficial pendente)
- F07 — exportação HTML/PPTX/PDF: NOT_STARTED
- F08 — interpretação por IA: NOT_STARTED
- F09 — homologação: NOT_STARTED

## Checkpoint F00 (2026-10-14)
- Backend: `python -m pytest -q` → 3 passed (Python 3.14.7). Python 3.11 NOT_VERIFIED localmente (coberto pela matriz do CI, ainda não executado).
- Frontend: `npm ci` + `npm run build` (`tsc -b && vite build`) → sem erros (Node 24.20, npm 12.0.2).
- Smoke API/proxy/CORS manual → OK. E2E Playwright (Edge local) → 1 passed, a frio e reutilizando servidores.
- Demo = UI sintética de navegação; **não é produto**, sem métricas oficiais, sem Veracode.
- Bloqueios de publicação: ver `PUBLISHING_BLOCKERS.md` (LICENSE placeholder, titularidade).

Próxima autorização esperada: aceite F00 + prompt F01 do PO. Não antecipar F01.
