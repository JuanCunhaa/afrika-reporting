# Afrika Reporting — local-first (F02)

Plataforma de relatórios AppSec multi-cliente, operada por Claude Code em fases. **Este ZIP é o ponto de partida de desenvolvimento**, não é uma integração Veracode pronta nem um gerador PPTX completo.

## Início rápido (Windows / PowerShell)

Requisitos: Python 3.11+ (validado localmente em 3.14; 3.11 coberto pela matriz do CI); Node.js 22+; npm.

```powershell
cd afrika-reporting-init
if (-not (Test-Path .env)) { Copy-Item .env.example .env }   # nunca sobrescreve um .env existente
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend/requirements-dev.txt   # versões exatas via backend/constraints.txt
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
- **`.env.example`**: `python scripts/check_env_example.py` lista variáveis e classificação sem mostrar valores.
- **Conexões Veracode**: só metadados + referência `env:NOME` da credencial. Nunca cole API ID/Key na interface. O backend lê `NOME_API_ID` e `NOME_API_KEY` do próprio ambiente (defina no terminal do uvicorn; nunca no Git).
- **Descoberta Veracode (F02, somente leitura)**: botão **Veracode** no cliente e em cada subcliente — teste de conexão, aplicações/sandboxes, BUs, Teams, usuários, relacionamentos e metadados. Detalhes, limites e variáveis `AFRIKA_VERACODE_*`: `docs/VERACODE_INTEGRATION.md`.
- **Demo sem Veracode real**: `$env:AFRIKA_VERACODE_MODE = "fixture"` usa um tenant **sintético** em processo (o E2E usa este modo). A conexão do seed (`env:AFRIKA_DEMO_VERACODE`) precisa das credenciais sintéticas de `app.veracode.fixtures.synthetic_credentials("alpha")` — ver comando em `docs/AGENT_HANDOFF.md`.
- **Loopback**: a API recusa (403) origem não-loopback e `Host` diferente de localhost/127.0.0.1. Não use `--host 0.0.0.0`.
- **Integração real (opt-in, fora do CI)**: `backend/tests_live/test_veracode_live.py` — só com autorização e credencial read-only.

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

`.github/workflows/ci.yml`: backend (Python 3.11 e 3.14: `pip check`, checagem de `.env.example`, migrations em banco novo, pytest) + `tsc -b && vite build` (Node 24) + E2E Playwright com Chromium (Python 3.14). Actions pinadas por SHA de commit; `permissions: contents: read`.

Para começar com Claude Code, abra a pasta raiz e envie integralmente **`prompts/F00_START.md`**. Em seguida, peça o relatório no formato `docs/AGENT_HANDOFF.md` e encaminhe-o ao PO (ChatGPT). **Uma fase por vez.**

## Decisões arquiteturais provisórias

- **Local-first**: FastAPI + SQLite (metadados e snapshots agregados) + React/Vite. Vercel é **possibilidade futura**, não requisito; SQLite local não é adequado como banco compartilhado em deploy serverless.
- API Veracode somente leitura; HMAC/segredos fora do Git. Se a API não tiver dado confiável, exigir preenchimento manual identificado.
- Engine de métricas determinística; IA apenas para interpretação de textos.
- Definição visual definitiva do template **pendente**. PPTXs reais são privados e **não fazem parte do ZIP**.

## Estado inicial

F00: scaffold executável + contratos. F01: cadastro persistente de clientes, subclientes e conexões. F02: conector Veracode somente leitura e descoberta (validado com tenant sintético; integração real NOT_VERIFIED). F03 e seguintes: **não implementadas**. Não tratar demo como homologada. Leia `docs/STATUS.md`.

## Licença

Source-available sob a **PolyForm Noncommercial License 1.0.0** — texto integral e inalterado em [`LICENSE`](LICENSE); aviso obrigatório em [`NOTICE`](NOTICE). Uso comercial **não** é concedido por essa licença: todos os direitos comerciais permanecem com o titular (JuanCunhaa). Para licença comercial, contate o titular pelo GitHub.
