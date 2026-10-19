# F10 — Validação do piloto operacional assistido (2026-10-19)

Classificação: **PASS** · **FAIL** · **BLOCKED_EXTERNAL** · **NOT_VERIFIED** · **NOT_APPLICABLE**.
Ambiente: Windows 11 Pro, Python 3.14.7, Node 24.20.0, Chromium headless do Playwright; CI Ubuntu (Python 3.11/3.14).

## 1. Critérios de aceite (ordem do PO §8)
| Dimensão | Resultado | Fundamento |
|---|---|---|
| Funcionalidade | **PASS** | piloto sintético integral 12/12 (§2) + conferência 11/11 + E2E da conferência; F00–F09 sem regressão (§5) |
| Integração Veracode | **PASS parcial / BLOCKED_EXTERNAL** | descoberta, escopos, SAST, Summary Report e agora **SCA** em real (só GET); Reporting API **BLOCKED_EXTERNAL** (403, POST não repetido) |
| Correspondência dos indicadores | **NOT_VERIFIED** | 0/35 homologados: 21 aplicáveis aguardam conferência humana; 12 NOT_APPLICABLE; 2 BLOCKED_EXTERNAL (`docs/F10_METRIC_RECONCILIATION.md`) |
| Completude SCA | **PASS (real, amostra)** | defeito do paginador corrigido; 18/18 contextos completos; SCA Policy/Sandbox/top/dependência VALIDATED. `sca.open.distinct` NOT_APPLICABLE (identidade) |
| Qualidade visual | **PASS com ressalvas** | `afrika-modelo@2`/`afrika@2` revisados e genéricos (sem nova versão); regressão visual sem diferença; tema provisório, ativos de marca ausentes, fontes em outro computador NOT_VERIFIED |
| Segurança do piloto | **PASS (uso local)** | §3; limitação crítica herdada: sem autenticação ⇒ só `127.0.0.1`, uma estação |
| Prontidão operacional | **CONDICIONADA — piloto local assistido** | §4 |
| Prontidão para produção | **NÃO PRONTO** | sem autenticação/segregação de funções, indicadores não homologados, Reporting bloqueada, SQLite local sem criptografia |

## 2. Piloto sintético integral (`backend/tests/test_f10_pilot.py`, 12 testes, dados 100% sintéticos)
| # | Etapa | Resultado | Verificação de consistência |
|---|---|---|---|
| 1 | Cliente + subcliente + escopos | PASS | prévia: universo 4, subcliente = BU 0 (2 aplicações); fuso padrão São Paulo |
| 2 | Mês anterior coletado e aprovado | PASS | 2026-08 aprovado (histórico vem de snapshot aprovado) |
| 3 | Coleta → snapshots | PASS | os 35 indicadores: valor do snapshot = valor da coleta quando VALIDATED; sem valor quando não (nunca 0) |
| 4 | Conferência com a "plataforma" | PASS | oráculo **independente** (contado direto dos findings do tenant, não pelo motor): apps.total, SAST/SCA Policy e Sandbox por severidade = **MATCH** em todas as linhas (5 homologados no piloto) |
| 5 | Aprovação + histórico | PASS | integridade ok; conferência continua MATCH sobre a revisão aprovada; série 2026-08/2026-09 aprovada; Δ = 0 |
| 6 | Apresentação `afrika-modelo@2` | PASS | todo ponto com valor da visualização = snapshot aprovado (mês atual e anterior); modelo sem dado do dono |
| 6b | Subcliente herda o modelo | PASS | pontos = snapshot do SUBCLIENTE (nunca do cliente); nome vem do cadastro |
| 7 | Interpretação local revisada e aplicada | PASS | provedor local determinístico; IA externa desligada |
| 8 | PPTX e PDF | PASS | números de severidade do snapshot nos gráficos nativos do PPTX; texto aprovado no PPTX e no PDF; páginas = slides |
| 9 | Backup e restauração do SQLite | PASS | backup íntegro (revisão `0008`); recusas: pasta versionável, sem confirmação, arquivo corrompido; restauração desfaz mudança posterior, preserva o banco anterior e mantém **idênticos** os hashes de integridade e o resumo de conferência |
| 10 | Reexportação após restauração | PASS | mesmo SHA-256 do PPTX |
| 11 | Segredos | PASS | credenciais sintéticas ausentes dos logs (DEBUG) e do arquivo SQLite |

## 3. Segurança do piloto (ordem do PO §7)
| Requisito | Resultado | Evidência |
|---|---|---|
| Backend restrito a localhost | PASS | `LocalOnlyMiddleware` (Host/IP não-loopback ⇒ 403; testes F09); uvicorn/Vite em `127.0.0.1`; CORS só `localhost:5173` |
| Dados de clientes isolados | PASS | piloto 6b (subcliente só com os próprios números); F09 18b (404 cruzado) |
| Sem credenciais em logs | PASS | piloto 11 (DEBUG na raiz); F09 etapa 23 |
| `private/` fora do Git | PASS | `git check-ignore`: `.gitignore:19 private/`; `data/` (backups) `.gitignore:35`; 0 arquivos rastreados |
| Backups do SQLite com restauração testada | PASS | piloto 9–10 + smoke do CLI (`backup-db`, `restore-db` recusado sem `--confirm`, restauração com backup de segurança, saída em `docs/` recusada) |
| Segurança dos arquivos exportados | PASS | piloto 8/10 + F09 21/23 (`nosniff`, `no-store`, SHA-256, sem macros/links/usuário do SO) |
| Sem conteúdo confidencial no repositório | PASS | gitleaks (§5); 8 identificadores reais da amostra × 403 arquivos rastreados/novos = 0 ocorrências; `check_repo` (nome da referência por SHA-256); PPTX de `references/` não rastreado e **SHA-256 inalterado** |
| Provedores externos de IA desativados | PASS | piloto 7 (`external_enabled=false`, `deterministic-demo`) |

## 4. Prontidão operacional — condições do piloto assistido
1. Uma estação, um operador; backend e frontend só em `127.0.0.1`; nada exposto em rede.
2. Antes de usar qualquer número fora da equipe: conferência na página *Conferir com a Veracode* (mesmo dia da coleta),
   só indicadores com **MATCH** sobre valor de origem Veracode podem ser apresentados como conferidos.
3. Lacunas (Reporting, fechamento histórico, licenças) preenchidas manualmente com justificativa — nunca estimadas.
4. `python -m app.cli backup-db` antes de cada aprovação e ao fim do ciclo; guardar backups e CSVs só em `data/`,
   `private/` ou fora do repositório.
5. Revisão humana de todo texto (interpretação) antes de exportar.

## 5. Testes e verificações
Local: pytest 711 passed; exportação obrigatória 105 passed; E2E da conferência 1 passed; E2E completo local NOT_RUN
(interrompido pelo sistema por falta de memória). CI run `39301551936`: success (E2E 41 passed + 3 skipped, visual
Linux sem diferença). Tabela completa: `docs/AGENT_HANDOFF.md` §7.
