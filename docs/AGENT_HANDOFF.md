# Devolutiva Claude → ChatGPT PO

- **Fase / branch / commit SHA:** F00 / sem branch / **sem commit** — a pasta não é repositório git (nada foi inicializado nem publicado).
- **Objetivo entregue:** F00 completa localmente (Windows 11): auditoria do scaffold, correção do pytest, smoke E2E Playwright, CI GitHub Actions (SHA-pinned), revisão de docs/segurança. Demo continua sendo **UI sintética de navegação**, não produto.

## Arquivos alterados e motivo
| Arquivo | Motivo |
|---|---|
| `pytest.ini` (novo) | **Bug concreto:** `python -m pytest backend/tests` (comando do README) falhava com `ModuleNotFoundError: app`. Agora `pythonpath = backend`; funciona da raiz e de `backend/`. |
| `frontend/playwright.config.ts`, `frontend/e2e/smoke.spec.ts` (novos) | Smoke E2E: sobe API+Vite, abre, vê 2 clientes sintéticos, seleciona com/sem subclientes, valida detalhes, garante zero requisições fora de localhost, salva 2 PNG. |
| `frontend/package.json`, `package-lock.json` | `@playwright/test@^1.64.1` (dev) + script `test:e2e`. |
| `.github/workflows/ci.yml` (novo) | pytest (Py 3.11/3.14) + `npm ci && npm run build` (Node 24). Actions pinadas por SHA de commit, `permissions: contents: read`, `persist-credentials: false`, só `push main`/`pull_request`. |
| `.gitignore` | + `*.tsbuildinfo` (gerado por `tsc -b`), `.playwright/`. |
| `PUBLISHING_BLOCKERS.md` | **Removidos nomes reais de clientes** (repo será público); item npm build marcado como verificado; itens abertos e pós-push adicionados. |
| `README.md` | Instruções E2E (PowerShell) e CI. |
| `docs/STATUS.md`, `docs/AGENT_HANDOFF.md` | Checkpoint e esta devolutiva. |

Sem alteração em `backend/app/*` e `frontend/src/*`: API, CORS e UI funcionaram sem correção.

## Decisões técnicas
- `pytest.ini` em vez de mexer em imports/sys.path: zero mudança de código e cobre README e CI.
- E2E contra o backend sintético real (não mock): é o único fluxo ponta a ponta existente. `PW_CHANNEL=msedge` usa navegador já instalado (sem baixar Chromium); `PYTHON` aponta o venv.
- E2E **fora** do CI: escopo do prompt era pytest + build; incluir exigiria download de browser no runner. Recomendado para F01.
- SHAs: `checkout v7.0.1 3d3c42e5…`, `setup-python v7.0.0 5fda3b95…`, `setup-node v7.1.0 949feb24…` (tags leves → commit, resolvidos via `git ls-remote`).
- Nenhuma mudança no contrato de métricas (é escopo F04/F05) — apenas lacunas documentadas abaixo.

## Testes executados
| Comando | Resultado |
|---|---|
| `python -m pytest -q` (raiz e `backend/`), Py 3.14.7 | **PASS** 3/3 (1 warning de depreciação, ver riscos) |
| `python scripts/check_repo.py` | **PASS** |
| `npm ci` + `npm run build` (`tsc -b && vite build`), Node 24.20 / npm 12.0.2 | **PASS**, 0 erros TS; `npm audit`: 0 vulnerabilidades |
| Smoke manual: `/api/health`, `/api/clients` direto e via proxy Vite | **PASS** (200) |
| CORS: preflight `Origin: http://localhost:5173` / `Origin: http://evil.example` | **PASS** (permitido / sem `Access-Control-Allow-Origin`) |
| `npm run test:e2e` (Edge local) — servidores reaproveitados, a frio (`CI=1`) e via PowerShell com caminho relativo | **PASS** 1/1 nas três execuções |
| YAML do workflow (`yaml.safe_load`) | **PASS** (sintaxe) |

## Testes NÃO executados
- **CI no GitHub:** NOT_RUN — sem git/remote. Python 3.11: NOT_VERIFIED localmente (só 3.14 instalado).
- E2E com Chromium do Playwright / Linux: NOT_RUN (só Edge local).
- `pip-audit`, gitleaks/scanner de secrets dedicado: NOT_RUN (feita varredura por regex).
- Caminho de erro da UI (API fora do ar → alerta): NOT_RUN.

## Evidências (somente sintéticas)
- `frontend/test-results/evidence/f00-cliente-com-subclientes.png` e `f00-cliente-sem-subclientes.png` (gitignored): cabeçalho "Central de relatórios AppSec", cards "Cliente Demonstração / Sem subclientes" e "Cliente com BUs (Sintético) / 2 subclientes", detalhe com ↳ TI, ↳ Marketing.
- Checklist segurança: sem padrões de chave/token/private key, sem e-mails, sem host Veracode em código, sem `.env`/PPTX/PDF/CSV/DB versionáveis; `.claude/settings.json` nega leitura de `.env`, credenciais e DB. Única ocorrência de dado real: nomes de clientes em `PUBLISHING_BLOCKERS.md` → removidos.
- Dependência incomum `@napi-rs/lzma-linux-x64-gnu` (opcional do rollup, só instala em Linux x64 = runner CI): conferida no `package.json` fonte do rollup v4.64.6 e publicação via OIDC com attestation → legítima.

## Riscos, limitações e bloqueios
- **LICENSE é placeholder** — repo não deve ser publicado até texto integral + titularidade (PUBLISHING_BLOCKERS 1–2).
- Starlette 1.8 avisa: TestClient com `httpx` está depreciado (sugere `httpx2`). Hoje passa; ranges abertos em `requirements.txt` podem quebrar no futuro. Não adicionei dependência nova.
- Python não tem lock de versões (só ranges) → CI pode divergir do local ao longo do tempo.
- npm 12 bloqueia o postinstall do esbuild (`allowScripts`); build funciona mesmo assim (binário vem por optionalDependency).
- Contratos (`backend/app/models.py`) ainda **não atendem** ao contrato de indicador do CLAUDE.md: `MetricSnapshot` não tem `contract/version`, `filters`, `timeframe`, `dedup`, `coverage`, `provenance`; `source`/`status` são `str` livres (deveriam ser enums); `competence` sem validação `YYYY-MM`; `value=None` distingue missing de zero, mas falta `missing_reason`. `Client` não tem flags de relatório consolidado/por subcliente nem referência de conexão. → F01/F04/F05.

## Alterações sugeridas na especificação
- Definir versão mínima de Python suportada (README diz 3.11+; validado só 3.14).
- Decidir se E2E entra no CI (recomendo sim em F01, com Chromium do Playwright).

## Próxima fase recomendada (NÃO executada)
> F01 — CRUD de clientes/subclientes e conexões sem segredos em claro. Pré-requisito: PO aceitar F00. Escopo sugerido: SQLite + migração versionada; modelo `Client` com flags `allow_consolidated`/`allow_per_subclient`, subcliente com 1 nível e conexão opcional que sobrescreve a do cliente (apenas referência a segredo, nunca valor); endpoints CRUD com validação; testes CRUD + "segredo nunca aparece em resposta/log"; E2E Playwright no CI; sem chamadas Veracode.

## Perguntas ao PO (bloqueantes)
Nenhuma para F00.
