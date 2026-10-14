# Afrika Reporting — local-first (F01)

Plataforma de relatórios AppSec multi-cliente, operada por Claude Code em fases. **Este ZIP é o ponto de partida de desenvolvimento**, não é uma integração Veracode pronta nem um gerador PPTX completo.

## Início rápido (Windows / PowerShell)

Requisitos: Python 3.11+ (validado localmente em 3.14; 3.11 coberto pela matriz do CI); Node.js 22+; npm.

```powershell
cd afrika-reporting-init
Copy-Item .env.example .env
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend/requirements-dev.txt
python -m pytest -q                       # testes do backend (bancos temporários; não toca no banco local)

cd backend
python -m app.cli migrate                 # cria/atualiza o esquema (Alembic). Nunca apaga dados.
python -m app.cli seed-demo               # OPCIONAL: dados sintéticos da demo F00 (idempotente)
python -m app.cli db-status               # revisão atual x esperada
uvicorn app.main:app --reload --port 8000
```

Em outro terminal:

```powershell
cd afrika-reporting-init/frontend
npm install
npm run dev
```

Acesse http://localhost:5173 (API http://localhost:8000/docs).

- **Banco**: `data/afrika-reporting.sqlite3` (ignorado pelo Git). Outro caminho: `$env:AFRIKA_DATABASE_URL = "sqlite:///C:/caminho/banco.sqlite3"`.
- O backend **recusa iniciar** se o banco não existir ou tiver migrations pendentes (mensagem indica `python -m app.cli migrate`). Não há `create_all()` nem seed automático.
- **API local sem autenticação**: não exponha a porta 8000 em rede/pública. CORS só aceita `http://localhost:5173` (ajustável por `CORS_ORIGINS`).
- **Conexões Veracode**: só metadados + referência `env:NOME` da credencial. Nunca cole API ID/Key na interface. Nenhuma chamada à Veracode nesta fase.

`pytest.ini` na raiz adiciona `backend/` ao `pythonpath`; `python -m pytest -q` funciona tanto da raiz quanto de `backend/`.

### E2E (Playwright)

Sobe API (porta 8010) + Vite (porta 5183) com um banco SQLite **novo e descartável** por execução em `frontend/.e2e-data/` (migrate + seed sintético). Não reaproveita servidores de dev nem toca no banco local. Evidências (PNG) em `frontend/test-results/evidence/` (ignorado pelo Git).

```powershell
cd frontend
npx playwright install chromium                  # uma vez (mesmo navegador do CI)
$env:PYTHON = "..\.venv\Scripts\python.exe"   # interpretador com backend instalado
npm run test:e2e
```

Opcional: `$env:PW_CHANNEL = "msedge"` usa o Edge instalado em vez do Chromium do Playwright.

### CI

`.github/workflows/ci.yml`: pytest (Python 3.11 e 3.14) + `tsc -b && vite build` (Node 24) + E2E Playwright com Chromium (Python 3.14). Actions pinadas por SHA de commit; `permissions: contents: read`.

Para começar com Claude Code, abra a pasta raiz e envie integralmente **`prompts/F00_START.md`**. Em seguida, peça o relatório no formato `docs/AGENT_HANDOFF.md` e encaminhe-o ao PO (ChatGPT). **Uma fase por vez.**

## Decisões arquiteturais provisórias

- **Local-first**: FastAPI + SQLite (metadados e snapshots agregados) + React/Vite. Vercel é **possibilidade futura**, não requisito; SQLite local não é adequado como banco compartilhado em deploy serverless.
- API Veracode somente leitura; HMAC/segredos fora do Git. Se a API não tiver dado confiável, exigir preenchimento manual identificado.
- Engine de métricas determinística; IA apenas para interpretação de textos.
- Definição visual definitiva do template **pendente**. PPTXs reais são privados e **não fazem parte do ZIP**.
- Repo público com uso comercial reservado: `LICENSE` PolyForm Noncommercial 1.0.0 **somente para código autoral cuja titularidade permita licenciamento**; verificar titularidade/validação jurídica antes de publicar.

## Estado inicial

F00: scaffold executável + contratos. F01: cadastro persistente de clientes, subclientes e conexões (sem Veracode). F02 e seguintes: **não implementadas**. Não tratar demo como homologada. Leia `docs/STATUS.md`.
