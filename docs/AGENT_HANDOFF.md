# Devolutiva Claude → ChatGPT PO — F07 / F07.1: Exportação PPTX/PDF (retomada e finalização) (2026-10-17)

- **Fase / commits:** F07 (retomada pela F07.1 a partir do trabalho local não commitado — nada descartado) / `main` /
  **`23151ae`** (implementação + testes + docs + CI de exportação + bootstrap temporário de 1 referência Linux) →
  **`5d73c67`** (referência Linux de `afrika/11` revisada; fim do bootstrap) → commit de checkpoint (STATUS/handoff).
  Push feito. **F08 e F09 NÃO iniciadas.**
- **CI:** run `38996755783` (SHA `5d73c67`, **estrito**) — **success**: Backend 3.11 e 3.14 (558 passed + 21 skipped
  cada — os 21 com motor real rodam no job próprio), **Exportação PPTX/PDF** (54 passed, 0 skipped, modo obrigatório),
  Frontend typecheck + build + motor visual, E2E Chromium (38 passed + 3 skipped) com regressão visual Linux **62/62**
  (ruído 0). Bootstrap: run `38996490059` (`23151ae`) — success (61/62 comparados + 1 candidata revisada; ruído 0 em 3
  capturas).
- Modelo: Opus 5.5 (ambiente). Nenhum subagente. **Nenhuma chamada à Veracode.** Nenhum PPTX/PDF/fonte/dado real
  versionado; medições locais só em `output/` (ignorado). PowerPoint usado só localmente para medir (aberto somente
  leitura, sem janela; a instância do usuário não foi encerrada).

## 1. Estado final
**DONE — aguardando PO.** Todos os critérios obrigatórios passaram (testes locais e CI estrito). Limitação registrada:
Be Vietnam Pro incorporada não é aplicada pelo PowerPoint testado (§7) — decisão do PO.

## 2. Funcionalidades concluídas
- PPTX editável com objetos nativos e PDF impresso do **mesmo** HTML da pré-visualização (`docs/EXPORT.md` §1–2).
- API (`POST /api/presentations/{id}/exports`, status, lista, download), CLI `export`, painel **Exportar** no editor
  (só revisão salva; alterações não salvas desabilitam os botões até salvar; bloqueios exibidos).
- Somente revisões aprovadas fixadas como fonte; integridade conferida; nada recalculado; snapshots só lidos.
- Bloqueio com diagnóstico por slide: corte, vazamento, saída de zona/slide, reticências, rótulo de eixo abreviado
  (novo), fonte de reserva; matriz até 1000 caracteres com fonte reduzida até 60%.
- Determinismo (mesmo SHA-256 para a mesma revisão + template/tema + build); proveniência em `docProps/custom.xml`.
- Segurança: nomes/caminhos só do servidor, temporários próprios com limpeza, limites de fila/prazo/tamanho, navegador
  sem rede, validação anti-macro/OLE/relação externa/conteúdo ativo (`docs/EXPORT.md` §7, `docs/SECURITY.md`).

## 3. Objetos efetivamente editáveis (contados no PPTX reaberto)
| Deck sintético | Texto | Formas | Linhas | Tabelas | Gráficos nativos | Imagens | **Editáveis** |
|---|---|---|---|---|---|---|---|
| `afrika-modelo@2` (16 slides) | 301 | 146 | 10 | 6 | 6 | 0 | **469** |
| `neutral-demo@1` (19 slides) | 179 | 44 | 40 | 4 | 6 | 0 | **273** |

## 4. Gráficos e tabelas nativos — evidência
- `afrika`: 2 `c:doughnutChart`, 1 `c:barChart`+`c:lineChart` (combinado, mesmo eixo), 3 `c:barChart` (colunas);
  `neutral`: 2 colunas, 2 linhas, 2 barras horizontais. 6 planilhas `.xlsx` incorporadas por deck.
- O validador (`validate.content`) confere em CADA exportação: cache do gráfico **e** planilha = valores aprovados da IR;
  nº de gráficos/tabelas = plano de exportação; texto/células = layout; nenhum `p:pic` além de ativo autorizado.
- Inspeção independente dos decks finais: 44 pontos de gráfico com 12 lacunas **vazias** (afrika) e 60/8 (neutro) —
  nenhuma lacuna virou 0. Testes: `test_kpis_are_text_and_charts_are_native_with_embedded_exact_values`,
  `test_tables_are_native_with_the_approved_ranking`, `test_pptx_passes_independent_revalidation` etc.

## 5. Fidelidade HTML × PPTX × PDF (`docs/EXPORT_FIDELITY.md`; 2 execuções idênticas)
| | `afrika-modelo@2` | `neutral-demo` |
|---|---|---|
| HTML×PDF (pixels) | 0–0,25% por slide; texto ≤ 1 px | 0,12–0,39%; texto ≤ 1 px |
| HTML×PPTX (pixels) | 0,04–0,82% | 0,75–2,45% (HTML usa fonte de sistema; PPTX grava Arial) |
| Texto Δ mediano / p95 | 0 (\|Δ\| ≤ 1) / ≤ 8 px | ≤ 3 / ≤ 12 px (158 px na lista de severidade → barras nativas, representação) |
| Quebras de linha divergentes | 0 em 16 slides | 0 em 19 slides |
| Dimensões | idênticas (1920×1080) | idênticas (1280×720) |

## 6. Os dois desvios visuais
| Desvio | Causa comprovada | Correção | Antes → depois |
|---|---|---|---|
| Rótulo centralizado da matriz (~7 px) | linha do cabeçalho crescia **5 px** no PowerPoint (margens 21+20 + entrelinha 24 > 64 px; o PowerPoint usa a altura natural da fonte para o mínimo) e empurrava a matriz | `_cell`: zera a margem oposta à âncora (centro: reduz ambas igualmente) — texto não se move, linha não cresce; teste unitário novo | Δy mediano 4 → **0**; p95 7 → **2** px; 1,08% → **0,46%**. Residual 2 px = centralização do PowerPoint (aceitável) |
| Rótulos longos no eixo (slide 11) | o **HTML abreviava** ("Outros (fo…") — truncamento invisível no PDF —, enquanto o PPTX recebia o nome completo e o PowerPoint encolhia a área de plotagem | HTML/PDF quebram o rótulo (até 3 linhas, eixo reservado; o PPTX usa a mesma área); acima disso, bloqueio com diagnóstico; 2 testes com motor real | 1,77% → **0,66%**; p95 24 → **8** px; HTML×PDF texto 8 → **1** px. Só 1 de 62 slides da regressão mudou (revisado em win32 e Linux) |

## 7. Fontes incorporadas (registradas separadamente)
| Fonte | Declarada | Incorporada (estrutura) | Aplicada pelo PowerPoint sem instalação (local) | Outro computador |
|---|---|---|---|---|
| Montserrat / Montserrat Black | sim | sim (EOT + `embeddedFontLst`) | **sim** | NOT_VERIFIED |
| Poppins | sim | sim | **sim** | NOT_VERIFIED |
| Be Vietnam Pro / SemiBold (números: KPIs, cabeçalhos, rótulos da matriz, rótulos de dados) | sim | sim | **não** (substituída) | NOT_VERIFIED |

Evidência: render sem fontes na sessão × com fontes (capa 0 px de diferença); controle em que o **próprio PowerPoint**
incorporou as 5 faces → mesmo resultado (Be Vietnam Pro não aplicada), logo não é defeito do nosso EOT; `fsType 0` e
checksums corretos. `Font.Embedded` do COM retorna `False` até para fontes aplicadas (não é prova). PDF: todas
incorporadas. Ambiente: Windows 11, Microsoft 365 16.0.20430. Nenhum software instalado; nenhum serviço externo.

## 8. Resultados dos testes (validação final, sequencial)
| Verificação | Resultado |
|---|---|
| pytest completo (local, Py 3.14.7) | **PASS — 579 passed** (525 anteriores + 33 unidades + 21 motor real) |
| E2E Chromium completo (local) | **PASS — 38 passed + 3 skipped** (2 comparações locais com a referência + fidelidade opt-in) |
| Exportador real (`AFRIKA_EXPORT_TESTS=required`) | **PASS — 54 passed** (local e CI) |
| Fidelidade HTML×PPTX×PDF (local, PowerPoint) | **PASS** (1 falha na 1ª tentativa final: TTF bloqueado pela instância do PowerPoint do usuário; `export_fonts.py` passou a não regravar fonte idêntica; reexecutado: PASS, números idênticos) |
| Regressão visual | **PASS** — win32 62/62, Linux (CI) 62/62, tolerância 0, ruído 0 |
| Build frontend + motor visual | **PASS** (12/12) |
| `npm audit` | **PASS — 0 vulnerabilidades** |
| `pip check` (.venv e venv novo só pelo lock) | **PASS** |
| gitleaks (staged, 2 commits) | **PASS — 0 achados** |
| `check_repo` / `check_env_example` | **PASS** (agora também recusa arquivos de fonte rastreados) |
| Migrations (banco novo: migrate, status, seed, migrate) | **PASS** — `0006_themes`, nenhuma migration nova |
| Inspeção estrutural PPTX/PDF finais | **PASS** (OPC íntegro, 0 macro/relação externa, 6 planilhas, 8 fontes; PDF 16/19 páginas no canvas, fontes incorporadas, sem conteúdo ativo) |

NOT_RUN: repetição ×3 da suíte E2E completa (feita 1× local + 2× no CI); validação em outro computador.

## 9. Commits e push
`23151ae` (F07 implementação), `5d73c67` (referência Linux + fim do bootstrap), checkpoint docs — todos em
`origin/main`. Arquivos principais: `backend/app/export/*` (novo), `backend/app/api_exports.py`, `cli.py`, `main.py`,
`presentations/{charts,document,export_plan,service,view}.py`, `requirements.txt`/`constraints.txt`, testes
`test_export_{units,engine}.py` + `export_fixtures.py`, frontend `ExportPanel.tsx`, `exportLayout.ts`, `SlideView.tsx`,
`render-stamp.mjs`, specs `export*.spec.ts`, `.github/workflows/ci.yml`, `scripts/check_repo.py`, scripts locais
`render_{pptx,pdf}.ps1`/`export_fonts.py`, docs `EXPORT.md`, `EXPORT_FIDELITY.md`, `PRESENTATION_CONTRACTS.md`,
`SECURITY.md`, `F07_EXPORT_READINESS.md`.

## 10. CI
- `38996490059` — `23151ae` — success (bootstrap temporário de `linux/afrika/11`).
- `38996755783` — `5d73c67` — **success, estrito** (sem bootstrap).
Novo no workflow: `npm run build` antes dos E2E; job **Exportação PPTX/PDF** (lock + build + Chromium do Playwright +
pytest de exportação obrigatório; sem PowerPoint, sem ativos proprietários, só dados sintéticos; nenhum PPTX/PDF sobe
como artefato).

## 11. Decisões tomadas (técnicas, reversíveis)
- PDF por impressão do HTML (não PPTX→PDF): mesmo renderizador, disponível no Windows e no CI, sem software proprietário.
- Rótulo de categoria longo quebra em até 3 linhas; acima disso bloqueia (regra "nunca truncar em silêncio").
- Margens de célula do PPTX ajustadas pela âncora (sem efeito visual onde a linha não crescia).
- Dependências novas apenas as do `python-pptx` (MIT; lxml BSD, Pillow MIT-CMU, XlsxWriter BSD), versões já testadas.

## 12. Riscos e limitações remanescentes
- **Be Vietnam Pro** não aplicada pelo PowerPoint testado quando não instalada (≈78 objetos + rótulos de 4 gráficos no
  `afrika@2` caem em fonte de reserva no PPTX; PDF não é afetado). Opções para o PO: instalar a fonte (OFL) nas
  máquinas que editam o PPTX, ou trocar a fonte numérica do tema (nova versão de tema).
- Compatibilidade em outro computador/PowerPoint para Mac/web: NOT_VERIFIED.
- Diferenças do renderizador documentadas: eixo Y −8 px, rótulos de pontos de linha, cantos de células, lista de
  severidade do tema neutro como barras nativas, quebra 3×2 linhas em rótulos longos.
- Rótulos de dados são texto personalizado (ao editar dados no PowerPoint, atualizar o rótulo).
- Fila em memória (reinício descarta jobs). Ativos de marca oficiais ainda não recebidos (fallback neutro).

## 13. Pendências para o PO
1. Aceite da F07. 2. Decisão sobre Be Vietnam Pro no PPTX (instalar × trocar fonte numérica). 3. Validação do PPTX
num segundo computador (fora do repositório) se desejado. 4. Ativos de marca autorizados (pasta local).

## 14. Prompt sugerido para a próxima fase (NÃO executado)
> **F08 — Interpretação assistida por IA (opcional, não bloqueante).** Ler `CLAUDE.md`, `docs/STATUS.md`,
> `docs/AGENT_HANDOFF.md`, `docs/PRESENTATION_CONTRACTS.md`, `docs/EXPORT.md`. Implementar sugestões de texto editorial
> (destaques, comentários, recomendações) a partir SOMENTE de revisões aprovadas e da IR já calculada, sem alterar
> números nem snapshots; toda sugestão é rascunho editável com proveniência (indicadores/competências usados), exige
> aceite explícito do operador e é gravada como nova revisão do documento. O core determinístico e a exportação devem
> funcionar com a IA desligada (padrão). Sem dados reais em prompts de teste; provedores e chaves só via ambiente,
> nunca no repositório; nenhuma chamada à Veracode. Testes: sugestão nunca muda valores, desligada por padrão, recusa
> fonte não aprovada, conteúdo sugerido passa pelo detector de overflow antes da exportação. Não iniciar F09.
