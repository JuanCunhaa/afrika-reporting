# Afrika Reporting — local-first (F05)

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
- **Escopos (F03)**: botão **Escopos** no cliente — universo do cliente e critérios por subcliente para aplicações, usuários, scans e SCA (AND/OR/NOT, modo simples e avançado, versões imutáveis, pré-visualização com não classificadas e sobreposição). Regras e semântica: `docs/SCOPES.md`.
- **Indicadores (F04)**: menu **Indicadores** (ou botão no cliente) — escolha cliente/subcliente e competência (mês fechado) e clique **Iniciar coleta**. Aplicações, SAST e SCA com status (Validado/Incompleto/Indisponível/Não suportado/Falhou), severidades, fonte, data da coleta, filtros e motivos. Catálogo: `docs/METRIC_CATALOG.md`. Valores **não** homologados contra o dashboard. F04.1: fuso por cliente (padrão America/Sao_Paulo), Summary Report e SCA Agent como fontes adicionais — `docs/API_SOURCE_MATRIX.md`.
- **Competências e histórico (F05)**: no resultado da coleta, informe o operador e clique **Criar rascunho da competência**; em **Competências** edite valores manuais (justificativa obrigatória), selecione os indicadores obrigatórios, envie para revisão e aprove (aprovador declarado, sem autenticação). **Histórico**: séries de 6/12 meses ou intervalo personalizado só com revisões aprovadas; lacunas aparecem como lacunas. **Reporting**: geração de relatório da Reporting API, desligada por padrão (`AFRIKA_VERACODE_REPORTING_ENABLED`). Detalhes: `docs/SNAPSHOTS.md`.
- **Demo sem Veracode real**: `$env:AFRIKA_VERACODE_MODE = "fixture"` usa um tenant **sintético** em processo (o E2E usa este modo). A conexão do seed (`env:AFRIKA_DEMO_VERACODE`) precisa das credenciais sintéticas de `app.veracode.fixtures.synthetic_credentials("alpha")` — ver comando em `docs/AGENT_HANDOFF.md`.
- **Loopback**: a API recusa (403) origem não-loopback e `Host` diferente de localhost/127.0.0.1. Não use `--host 0.0.0.0`.
- **Integração real (opt-in, fora do CI)**: `backend/tests_live/test_veracode_live.py` — só com autorização e credencial de TESTE read-only no `.env` da raiz (`AFRIKA_VC_TEST_*`), `VERACODE_LIVE_TESTS_ENABLED=true` e `python -m pytest backend/tests_live -q -rs --run-veracode-live`. O backend carrega o `.env` da raiz automaticamente (variáveis do sistema prevalecem) e `VERACODE_READ_ONLY` só aceita `true`. Ver `docs/VERACODE_INTEGRATION.md`.

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

F00: scaffold executável + contratos. F01: cadastro persistente de clientes, subclientes e conexões. F02/F02.1: conector Veracode somente leitura e descoberta (homologado em tenant real de testes). F03: motor de escopos e filtros versionados. F04: motor de indicadores (aplicações, SAST, SCA). F05: snapshots por competência, aprovação auditável, histórico e adaptador da Reporting API. F06 e seguintes: **não implementadas**. Não tratar demo como homologada. Leia `docs/STATUS.md`.

## Licença

Source-available sob a **PolyForm Noncommercial License 1.0.0** — texto integral e inalterado em [`LICENSE`](LICENSE); aviso obrigatório em [`NOTICE`](NOTICE). Uso comercial **não** é concedido por essa licença: todos os direitos comerciais permanecem com o titular (JuanCunhaa). Para licença comercial, contate o titular pelo GitHub.
