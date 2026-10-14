# Devolutiva Claude → ChatGPT PO — F01.1

- **Fase / branch / commits:** F01.1 / `main` (local) / **`98270d4`** (hardening) + commit seguinte só com STATUS/handoff. Commits anteriores: `84d0fb4` (F01), `28734da` (docs F01).
- **Remote Git:** `git remote -v` → **nenhum** (verificado em 2026-10-14). Nada publicado.
- **Recomendação:** aceitar F01.1 após (a) o usuário validar e versionar `.env.example` e (b) o primeiro push **privado** com CI verde.
- Sessão executada com Opus 5.5 (a ordem F01 pedia Sonnet 5.5; troca de modelo é feita pelo usuário via `/model`). Sem subagentes.

## Alterações realizadas
| # | Tarefa | Resultado |
|---|---|---|
| 1 | `.env.example` | **BLOQUEADO para mim, por política do projeto.** `.claude/settings.json` nega `Read(**/.env.*)`; não contornei via shell. Criado `scripts/check_env_example.py`: lista **só nome, classificação e tamanho** (nunca valores), recusa ler `.env` real e sai com 0 = seguro / 1 = revisar. Coberto por 4 testes com dados sintéticos; roda no CI quando o arquivo estiver versionado. README: a cópia para `.env` passou a ser condicional (antes `Copy-Item` **sobrescrevia** um `.env` existente). |
| 2 | Auditoria repo + histórico | Ver "Segurança do repositório". `.gitignore` + `.claude/settings.local.json`, `*.pem`, `*.key`, `*.p12`, `*.pfx`. |
| 3 | Logs SQLAlchemy DEBUG | `app.db.DropSqlResultRows`, instalado (idempotente) no logger `sqlalchemy.engine.Engine` em todo `make_engine`: descarta registros DEBUG (linhas/colunas de resultado). Vale no logger, então sobrevive a `dictConfig`/`uvicorn --log-config` (verificado). SQL em INFO continua visível, com parâmetros ocultos. |
| 4 | Versões controladas | `backend/constraints.txt` com as **mesmas versões já instaladas e testadas (zero upgrades)**, + `uvloop==0.23.0` (só Linux, via uvicorn[standard]). `requirements.txt` aplica `-c constraints.txt`. Resolução `pip --dry-run --only-binary=:all:` para CPython **3.11 e 3.14 × Linux x86_64 e Windows amd64**: 33/32/33/32 pacotes, **nenhum fora do lock**. |
| 5 | CI | Job backend: `pip check`, checagem de `.env.example`, **migrations em banco novo** (`migrate` → `db-status` → `seed-demo` → `migrate` de novo), pytest. Job e2e: `pip check`; o webServer do Playwright faz migrate + seed + uvicorn + Vite. **Bug corrigido:** `PYTHON=python` (definido no job e2e) virava `<frontend>/python` em `playwright.config.ts`, e **o E2E quebraria no CI**. |
| 6 | API indisponível na UI | Observado na prática: com backend parado, o proxy do Vite responde **500 com corpo vazio**. `api.ts` passou a converter 5xx sem corpo da API em "API indisponível (HTTP 500). Verifique se o backend está em execução." Novo `e2e/api-unavailable.spec.ts` (4 testes): lista (proxy 500), falha de rede em lista/detalhe/conexões, queda durante envio de formulário (dados preservados, reenvio funciona) e ação de desativar com API fora (nada muda). |
| 7 | Testes | Todos rerodados (abaixo). |
| 8 | Remote | Nenhum. Comandos de conexão abaixo. |

## Testes e resultados (2026-10-14, Windows 11)
| Comando / ambiente | Resultado |
|---|---|
| `python -m pytest -q`, raiz e `backend/`, `.venv` Py 3.14.7 | **PASS 59/59** (+6 vs F01: 2 de logs SQL, 4 do verificador) |
| Venv **novo** só com `requirements-dev.txt` + lock: `pip check`, `check_repo`, migrate/db-status/seed/migrate, pytest | **PASS** (59/59) |
| `npm ci` limpo + `npm run build` | **PASS**, 0 vulnerabilidades |
| E2E Chromium v1248, venv novo no PATH + `PYTHON=python` (simula o job CI) | **PASS 9/9** |
| E2E Chromium, `.venv` + `PYTHON=..\.venv\Scripts\python.exe` (fluxo README) | **PASS 9/9** |
| Controle negativo: guarda de log desligada temporariamente | os 2 testes de log **FALHAM** (esperado); guarda restaurada |
| `ci.yml` (`yaml.safe_load`) | **PASS** — jobs backend, frontend, e2e |
| Python 3.11 em execução | **NOT_VERIFIED** (só 3.14 instalado; resolução do lock para 3.11 OK) |

## Segurança do repositório
- **Histórico completo (3 commits) e árvore atual**, todas as revisões: sem objetos `.env/.db/.sqlite/.pptx/.pdf/.csv/.jsonl/.xlsx/.docx/.png/.zip/.pem/.key/.p12`, `credentials` ou `.veracode`; sem padrões de chave (hex ≥ 40, private key, AKIA, ghp_/github_pat_, xox, sk-, atribuições `api_key/secret/password/token`); **nenhum e-mail** no conteúdo; sem CNPJ/CPF/telefone/razão social (único resultado: UUID sintético `00000000-…`, falso positivo). URLs: só localhost, `evil.example` (teste de CORS), github.com e polyformproject.org. Maior blob: `package-lock.json` (63 KB), apenas `registry.npmjs.org` e sem tokens.
- **Metadados dos commits:** autor/committer = e-mail pessoal do usuário (`git config` local). Aceitável em repositório privado; **antes de qualquer publicação pública**, decidir se troca pelo e-mail `noreply` do GitHub.
- `.gitignore` verificado com `git check-ignore`: `.env`, `data/`, `.e2e-data/`, `*.pem`, `.claude/settings.local.json` ignorados; `.env.example` não ignorado (proposital).
- Evidências PNG (sintéticas) em `frontend/test-results/evidence/` (gitignored). `frontend/.e2e-data/` acumula 1 banco sintético por execução (gitignored; pode ser apagado à vontade).

## Status real do CI
**NOT_RUN no GitHub** (sem remote). Equivalência local verificada (tabela acima), mas sem cobrir: runner Ubuntu, `playwright install --with-deps` (apt), execução em Python 3.11 e cache/rede do GitHub. Não declaro o CI aprovado.

## Commits criados nesta etapa
- `98270d4` — F01.1: hardening de logs, dependências fixadas, CI e API indisponível
- commit seguinte — docs: checkpoint F01.1 (STATUS e AGENT_HANDOFF)

## Pendências restantes
1. **`.env.example`** — no terminal do Claude Code, rodar `! python scripts/check_env_example.py`. Se a saída disser `SEGURO para versionar`: `git add .env.example; git commit -m "chore: versiona .env.example (somente placeholders)"`. Se houver `REVISAR`, corrigir manualmente (sem me mostrar valores) e repetir.
2. Primeiro push **privado** + CI verde (comandos abaixo).
3. **Publicação pública BLOQUEADA** até: licença (texto integral PolyForm + titularidade, PUBLISHING_BLOCKERS 1–2), titularidade do código e autenticação da aplicação.
4. Warning Starlette/httpx no TestClient (sem impacto hoje; não troquei a dependência).
5. Perguntas da F01 ainda abertas: exclusão física vs. arquivamento; convenção `env:NOME` → `NOME_API_ID/NOME_API_KEY` para a F02.

## Comandos para conectar ao GitHub privado (o usuário executa; nada foi criado por mim)
Pré-requisito: pendência 1 resolvida (ou decisão consciente de pushar sem `.env.example`).

**Opção A — GitHub CLI** (PowerShell, na raiz do repo):
```powershell
gh auth status
gh repo create afrika-reporting --private --source . --remote origin --description "Afrika Reporting (privado)"
git remote -v
gh repo view afrika-reporting --json visibility --jq .visibility     # deve imprimir PRIVATE
git push -u origin main
gh run list --limit 3
gh run watch                                                          # acompanha o CI
```

**Opção B — interface web:** em github.com/new, crie o repositório **Private**, **vazio** (sem README, .gitignore ou licença). Depois:
```powershell
git remote add origin https://github.com/<SEU_USUARIO>/afrika-reporting.git
git remote -v
git push -u origin main
```

Depois do push: confirmar os 3 jobs verdes (backend 3.11 e 3.14, frontend, e2e) e ativar Dependabot alerts. Branch protection/rulesets e secret scanning em repositório privado dependem do plano GitHub; ativar se disponível. Opcional, e só antes do primeiro push: `git config user.email "<id>+<usuario>@users.noreply.github.com"` vale para commits futuros; reescrever o autor dos commits existentes altera o histórico e só deve ser feito por decisão explícita.

## Próxima fase (NÃO iniciada)
F02 — conectores Veracode somente leitura. Pré-requisitos: aceite F01.1, CI verde no repositório privado, respostas às perguntas da F01.
