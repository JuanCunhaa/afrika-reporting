# F09 — Matriz de aceite (homologação ponta a ponta, 2026-10-19)

Classificação: **PASS** · **FAIL** · **BLOCKED_EXTERNAL** · **NOT_VERIFIED** · **NOT_APPLICABLE**.

## Resumo (critérios desta matriz, exceto os 35 indicadores)
| Bloco | PASS | FAIL | BLOCKED_EXTERNAL | NOT_VERIFIED | NOT_APPLICABLE |
|---|---|---|---|---|---|
| §1 Fluxo sintético (22 etapas + isolamento + segurança) | 24 | 0 | 0 | 0 | 0 |
| §2 Integração real Veracode (14) | 11 | 0 | 2 | 1 | 0 |
| §4 Segurança (17, ver revisão própria) | 17 | 0 | 0 | 0 | 0 |
| §5 PowerPoint/PDF (13 itens) | 12 | 0 | 0 | 1 | 0 |
| §6 Interpretação (11) | 10 | 0 | 0 | 0 | 1 |
| §8 Estabilidade (14) | 13 | 0 | 0 | 1 | 0 |
| **Total (93)** | **87** | **0** | **2** | **3** | **1** |

O item "Fontes" (§5) conta como PASS local com ressalva (outro computador NOT_VERIFIED, contado na linha "Abertura em
outros computadores"); "Execução real" (§8) conta como PASS (os bloqueios externos estão em §2); a intermitência do
`f06c` conta como NOT_VERIFIED (não reproduzida, causa não provada).
Indicadores (§3, à parte): 0 PASS · 8 BLOCKED_EXTERNAL · 16 NOT_VERIFIED · 11 NOT_APPLICABLE.
Ambiente: Windows 11 Pro, Python 3.14.7, Node 24.20.0, Chromium headless do Playwright; CI Ubuntu (Python 3.11/3.14).
Evidência automatizada principal: `backend/tests/test_f09_acceptance.py` (um teste por etapa, mesmo banco SQLite em
arquivo, **reinício real** da aplicação na etapa 22) — tenants SINTÉTICOS `gamma`/`beta` em processo.

## 1. Fluxo completo sintético (ordem do PO §2)
| # | Etapa | Resultado | Evidência (teste → verificação) |
|---|---|---|---|
| 1 | Cadastro de cliente | PASS | `test_01`: 2 conexões (`env:`), cliente com conexão e fuso; cliente isolado sem subclientes |
| 2 | Cadastro de subclientes | PASS | `test_02`: subcliente herdado e independente; cliente sem subclientes funciona |
| 3 | Conexão herdada e independente | PASS | `test_03`: `connection_source` client × subcliente; teste de conexão `ok` em ambos; tenants distintos sem interseção; credenciais ausentes das respostas |
| 4 | Criação de escopos | PASS | `test_04`: universo por BU, subcliente por BU, usuários por Team; regra de outro domínio ⇒ 422; versão desatualizada ⇒ 409 |
| 5 | Seleção de aplicações e usuários | PASS | `test_05`: prévia = App 001/003 (valores-ouro); usuários = membros ativos do Team |
| 6 | Coleta simulada de indicadores | PASS | `test_06`: valores-ouro (apps 4/2; SAST Policy 5 por severidade); proveniência (`run_id`, `input_hash`, versões de escopo) |
| 7 | Indisponibilidade e incompletude | PASS | `test_07`: identidade não comprovada ⇒ INCOMPLETE sem valor; subcliente sem escopo ⇒ UNAVAILABLE; HTTP 500 persistente na Findings SCA ⇒ SCA sem valor, SAST segue VALIDATED |
| 8 | Criação de competência | PASS | `test_08`: rascunho a partir da coleta; importar coleta de outro dono recusado |
| 9 | Snapshot persistente | PASS | `test_09`: snapshots com origem/status preservados, lidos direto do arquivo SQLite |
| 10 | Preenchimento manual justificado | PASS | `test_10`: sem justificativa ⇒ 422; manual com fonte preservada; zero é valor (não ausência) |
| 11 | Aprovação da competência | PASS | `test_11`: lock otimista (409); aprovada imutável na API (409) e no banco (gatilho); integridade ok |
| 12 | Recuperação de histórico aprovado | PASS | `test_12`: série 6 meses = só aprovados, lacunas 04–06 sem interpolação; variação −1 vs. mês anterior; outro cliente só lacunas |
| 13 | Seleção do template Afrika | PASS | `test_13`: `afrika-modelo@2` por cliente; subcliente herda; cliente isolado não |
| 14 | Criação da apresentação | PASS | `test_14`: slides escolhidos pela disponibilidade; pronta (0 bloqueios); valores manuais sinalizados; lacunas de histórico como aviso |
| 15 | Edição de slides | PASS | `test_15`: nova revisão; edição concorrente ⇒ 409; revisão anterior intacta |
| 16 | Interpretação local | PASS | `test_16`: provedor `deterministic-demo`, externo desligado; executiva e técnica válidas |
| 17 | Validação e aprovação humana | PASS | `test_17`: rejeição exige motivo; regeneração = nova versão; só a mais recente avança; número inventado ⇒ bloqueio `unverified…`, aprovação 409; versão válida aprovada |
| 18 | Aplicação do texto ao slide | PASS | `test_18`: texto aprovado no campo do slide (nova revisão); nova revisão APROVADA da competência + rebind ⇒ pendente bloqueada (`interpretation_stale`); revisão 1 preservada; 2 aprovações auditadas |
| — | Isolamento entre clientes | PASS | `test_18b`: listas, interpretações (404 cruzado) e visualização sem dados do outro cliente; modelo neutro |
| 19 | Exportação PPTX | PASS | `test_19`: nº de slides = visualização; gráficos nativos = planilhas incorporadas; 0 imagem; textos (capa editada, interpretação) no PPTX |
| 20 | Exportação PDF | PASS | `test_20`: PDF válido; páginas = slides; texto da interpretação extraído; modelo neutro exporta PPTX e PDF |
| 21 | Download dos dois formatos | PASS | `test_21`: SHA-256 (cabeçalho = job = conteúdo), tamanho, `nosniff`, `no-store`, nome com extensão; 404 sem caminho; UI: `e2e/export.spec.ts` |
| 22 | Reabertura sem perda | PASS | `test_22`: nova instância da aplicação no mesmo arquivo — clientes, subclientes, escopos, competência, histórico, apresentação, visualização, interpretações e auditoria **idênticos**; integridades ok; coleta em memória ⇒ 404 explícito. `test_22b`: reexportação da mesma revisão = **mesmo SHA-256** do PPTX; PDF sem chamar provedor |
| 23 | Segurança do fluxo | PASS | `test_23`: logs (todo o fluxo), banco e arquivos exportados sem credenciais, usuário do SO, caminhos locais ou textos sensíveis; `Host` forjado ⇒ 403; PPTX sem macros/links externos |

**Resultado do fluxo: 22/22 etapas PASS** (+ isolamento e segurança). Execução local: 25 passed.

## 2. Homologação real Veracode (tenant de testes, somente GET)
| Requisito | Resultado | Evidência |
|---|---|---|
| Inventário de aplicações | PASS | 667 aplicações, 7 páginas, completo (`test_veracode_live`, `test_f09_live_flow`) |
| Business Units | PASS | 17, completo |
| Teams | PASS | 12, completo; vínculos 192 em 12 detalhes |
| Usuários | PASS | 87, completo; reconciliação `team_count` (`test_scopes_live`) |
| Escopos | PASS | 2 clientes com escopos disjuntos pela API local: prévia 2 e 1, interseção 0; `apps.total` = 2 e 1; subcliente por BU |
| Summary Report | PASS | VALIDATED; Findings × Summary 3/3 coincidentes (SAST Policy) |
| Findings SAST | PASS | Policy e Sandbox VALIDATED na amostra |
| Findings SCA | BLOCKED_EXTERNAL | 6/28 pedidos de findings falharam por transporte (sem HTTP 500 desta vez); SCA INCOMPLETE sem valor (correto) |
| Completude e paginação | PASS | todas as coletas `complete`; multipágina real |
| Tratamento de HTTP 500 | NOT_VERIFIED (real) / PASS (mock) | nenhum 500 ocorreu na F09; mock: F09 etapa 7 + `test_metrics_sources.py`; real na F04.1 |
| Isolamento entre clientes | PASS | interseção 0; populações e valores por cliente |
| Reporting API (POST) | BLOCKED_EXTERNAL | 403 na F05; sem mudança de permissão confirmada ⇒ POST **não repetido** |
| Nenhuma escrita na Veracode | PASS | 58/58 pedidos registrados = GET; ≈176 GET na fase; 0 POST/PUT/DELETE |
| Findings reais fora do repo | PASS | só agregados em `private/f09/` (ignorado) |

## 3. Indicadores (detalhe em `docs/F09_METRIC_RECONCILIATION.md`)
Homologados contra o dashboard: **0** (dashboard inacessível ⇒ NOT_VERIFIED 16; BLOCKED_EXTERNAL 8; NOT_APPLICABLE 11).

## 4. Segurança (detalhe em `docs/F09_SECURITY_REVIEW.md`)
17 requisitos: 17 PASS no modo local de uso. Limitação crítica: **sem autenticação real de usuários**.

## 5. PowerPoint e PDF
| Item | Afrika (`afrika-modelo@2`) | Neutro (`demo-executivo`/`neutral-demo`) | Evidência |
|---|---|---|---|
| Slides em ordem | PASS | PASS | F09 etapas 19/20; `test_export_engine.py` |
| Indicadores aprovados (só fonte aprovada fixada) | PASS | PASS | precheck de exportação; `test_export_engine.py` |
| Textos editáveis | PASS | PASS | texto nativo (capa editada e interpretação no PPTX) |
| Formas nativas | PASS | PASS | `test_export_engine.py` (`custGeom`, linhas) |
| Tabelas nativas | PASS | PASS | `test_export_engine.py` |
| Gráficos com planilha incorporada | PASS | PASS | F09 etapa 19 (gráficos = `.xlsx` incorporados); `test_export_engine.py` |
| Lacunas preservadas | PASS | PASS | célula vazia (`test_export_engine.py`); lacunas de histórico (F09 etapa 14) |
| HTML × PPTX × PDF | PASS (local) | PASS (local) | `export-fidelity.spec.ts` com PowerPoint (§8); outro computador NOT_VERIFIED |
| Fontes | PASS (PDF incorporadas) / NOT_VERIFIED (outro computador) | idem | `docs/EXPORT.md`; PowerPoint local não aplica Be Vietnam Pro incorporada (F07) |
| Overflow | PASS | PASS | exportação bloqueia corte; 0 bloqueio nos casos sintéticos |
| Download | PASS | PASS | F09 etapa 21; E2E `export.spec.ts` |
| Integridade dos arquivos | PASS | PASS | ZIP íntegro, SHA-256, PDF `%PDF`/`%%EOF`, reexportação determinística (PPTX) |
| Abertura em outros computadores/versões do Office | NOT_VERIFIED | NOT_VERIFIED | só PowerPoint local e LibreOffice não testados |

## 6. Interpretação (ordem do PO §7)
| Item | Resultado | Evidência |
|---|---|---|
| Texto executivo | PASS | F09 etapa 16; `test_interpretation.py` |
| Texto técnico | PASS | F09 etapa 16 |
| Validação numérica | PASS | F09 etapa 17 (número inventado bloqueado) |
| Ausência de causas inventadas | PASS | `test_interpretation.py` (causa/remediação sem nota citada ⇒ aviso/bloqueio) |
| Aprovação humana | PASS | F09 etapa 17 |
| Rejeição | PASS | F09 etapa 17 (motivo obrigatório) |
| Regeneração | PASS | F09 etapa 17 |
| Aplicação ao slide | PASS | F09 etapa 18 |
| Bloqueio de desatualizadas | PASS | F09 etapa 18 (`interpretation_stale`) |
| Exportação sem chamada de IA | PASS | F09 etapa 22b; `test_interpretation_export.py` |
| Dados reais a provedores externos | NOT_APPLICABLE | nenhum provedor externo implementado/habilitado |

## 7. Correções desta fase
Nenhum defeito de produto comprovado. Ajustes feitos só nos instrumentos de homologação (testes): ver handoff.

## 8. Estabilidade (execução sequencial, Windows local; CI no handoff)
| Verificação | Resultado | Detalhe |
|---|---|---|
| pytest completo | PASS | 679 passed (654 anteriores + 25 F09) — ver handoff para a contagem final |
| Exportação real obrigatória (`AFRIKA_EXPORT_TESTS=required`) | PASS | 82 passed (57 + 25 F09); arquivo F09 repetido 3× (25/25 cada) |
| E2E Chromium completo | PASS | 3 rodadas: 40 passed + 3 skipped em cada (skips = comparações locais com a referência real e fidelidade com PowerPoint, por desenho); `retries: 0`, `workers: 1` |
| Regressão visual | PASS | win32 dentro do E2E (3/3 rodadas); Linux no CI |
| Fidelidade HTML × PPTX × PDF (PowerPoint local) | PASS | `export-fidelity.spec.ts` 1 passed: Afrika HTML×PDF ≤ 0,25 %, HTML×PPTX 0,04–0,84 %; neutro ≤ 0,39 % / 0,75–2,45 %; texto HTML×PDF ≤ 1 px; 0 quebra de linha divergente — idêntico à F07 |
| Intermitência `f06c.spec.ts` (F08) | NOT_REPRODUCED | 3 rodadas completas + 10× isolado sem retry (40/40); causa segue NOT_PROVEN |
| Migrations | PASS | banco novo: `migrate` → `db-status` (0007 OK) → `seed-demo` → `migrate` idempotente |
| Build frontend + motor visual | PASS | `tsc -b && vite build`; testes do motor visual 12/12 |
| `npm audit` | PASS | 0 vulnerabilidades |
| `pip check` | PASS | sem dependências quebradas; nenhuma dependência nova |
| Gitleaks | PASS | histórico 51 commits 0 achados; arquivos novos 0; staged no commit (handoff) |
| `check_repo` / `check_env_example` | PASS | estrutura F09 OK; `.env.example` SEGURO |
| Persistência e reinício | PASS | F09 etapa 22 (nova instância, mesmo SQLite) + `test_persistence.py` (processo uvicorn real reiniciado) |
| Execução real Veracode (opt-in) | PASS com bloqueios externos | `test_f09_live_flow` 1 passed; live 18 passed + 1 skipped; métricas live 1 passed |
