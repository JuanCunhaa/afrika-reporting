# Fidelidade HTML × PPTX × PDF (F07 + F07.1)

Medição **local** (Windows 11 + PowerPoint Microsoft 365 16.0.20430), conteúdo **sintético equivalente** nas três
modalidades (o mesmo documento e as mesmas revisões aprovadas). Spec: `frontend/e2e/export-fidelity.spec.ts`
(`AFRIKA_EXPORT_FIDELITY=1`; pulada no CI). Saídas em `output/export-fidelity/` (ignorado pelo Git; nada versionado nem
enviado a serviços externos). Execuções depois das correções da F07.1: 2026-10-17 02:28 e 02:47 UTC — números
idênticos nas duas.

## Método
- **HTML**: captura `#/render` do motor visual (Chromium, escala 1). **PDF**: página rasterizada pela API do Windows
  (`scripts/render_pdf.ps1`). **PPTX**: slide exportado pelo PowerPoint via COM (`scripts/render_pptx.ps1`, somente
  leitura, sem janela), com as fontes OFL do tema registradas **só durante a renderização** (removidas no fim).
- Diferença por pixel = mesmo motor da regressão visual (YIQ, limiar 0,08 — o das comparações com a referência —,
  antisserrilhado contado à parte), regiões atribuídas por categoria (gráficos/tabelas/texto/formas) pelo manifesto.
- Posição do texto: caixa da "tinta" de cada elemento com texto no HTML × no PPTX/PDF (Δx/Δy em px, 1920×1080).
- Quebras de linha: nº de linhas de cada caixa/célula no HTML × `TextRange.Lines` do PowerPoint.
- Dimensões: 1920×1080 (16:9; 1280×720 no tema neutro) nas três modalidades — iguais em todos os slides.

## Resultados por slide
| Caso / slide | HTML×PDF dif. % | HTML×PDF texto máx px | HTML×PPTX dif. % | PPTX px: gráficos / tabelas / texto / formas | texto Δy/Δx mediana | texto p95 px | linhas ≠ |
|---|---|---|---|---|---|---|---|
| afrika-v2 / 01-capa | 0,02 | 1 | 0,04 | 0 / 0 / 861 / 0 | 0/0 | 1 | 0 |
| afrika-v2 / 02-secao-abertura | 0 | 1 | 0,12 | 0 / 0 / 2568 / 0 | 0/0 | 5 | 0 |
| afrika-v2 / 03-secao-indicadores | 0 | 1 | 0,09 | 0 / 0 / 1865 / 0 | 0/0 | 2 | 0 |
| afrika-v2 / 04-secao-detalhes | 0 | 1 | 0,10 | 0 / 0 / 2014 / 0 | −1/0 | 3 | 0 |
| afrika-v2 / 05-painel-kpis | 0,23 | 1 | 0,64 | 0 / 7389 / 5644 / 285 | 0/0 | 2 | 0 |
| afrika-v2 / 06-painel-graficos | 0,25 | 1 | 0,82 | 9731 / 3345 / 4019 / 0 | 0/0 | 6 | 0 |
| afrika-v2 / 07-painel-grupos | 0,23 | 1 | 0,72 | 5109 / 2041 / 7827 / 0 | 1/0 | 3 | 0 |
| afrika-v2 / 08-painel-severidades | 0,15 | 1 | 0,41 | 2082 / 1942 / 3053 / 1406 | 0/0 | 1 | 0 |
| afrika-v2 / 09-painel-severidades-dev | 0,11 | 1 | 0,32 | 2091 / 957 / 2111 / 1403 | 0/0 | 2 | 0 |
| afrika-v2 / 10-ranking-aplicacoes | 0,17 | 1 | 0,59 | 9137 / 0 / 3126 / 0 | 0/0 | 8 | 0 |
| afrika-v2 / 11-ranking-componentes | 0,16 | 1 | **0,66** (antes 1,77) | 10907 / 0 / 2810 / 0 | 0/0 | **8** (antes 24) | 0 |
| afrika-v2 / 12-destaque-vulnerabilidades | 0,19 | 1 | 0,69 | 11457 / 0 / 2816 / 0 | 0/0 | 2 | 0 |
| afrika-v2 / 13-secao-plano | 0 | 1 | 0,09 | 0 / 0 / 1807 / 0 | 1/0 | 4 | 0 |
| afrika-v2 / 14-matriz-acoes | 0,12 | 1 | **0,46** (antes 1,08) | 0 / 9043 / 412 / 0 | **0**/0 (antes 4) | **2** (antes 7) | 0 |
| afrika-v2 / 15-matriz-acompanhamento | 0,12 | 1 | **0,45** (antes 1,08) | 0 / 9043 / 366 / 0 | **0**/0 (antes 4) | **2** (antes 7) | 0 |
| afrika-v2 / 16-encerramento | 0,04 | 1 | 0,11 | 0 / 0 / 2302 / 0 | 0/0 | 1 | 0 |
| neutral-demo / 01–19 (faixa) | 0,12–0,39 | 1 | 0,75–2,45 | — | −3…1 / 0…1 | 1–12 (158 nos slides 11–12, ver abaixo) | 0 |

Resumo `afrika-modelo@2`: **HTML×PDF ≤ 0,25%** e texto ≤ 1 px em todos os slides; **HTML×PPTX 0,04–0,82%**; Δ mediano
do texto 0 px (|Δ| ≤ 1); **0 divergência de quebra de linha** em 16/16 slides (e 19/19 no neutro); 0 elemento ausente.
Tema neutro: diferença maior no PPTX porque o HTML usa a fonte de sistema da plataforma (Segoe UI no Windows) e o PPTX
grava `Arial` (`export_family`) — mesmas quebras de linha, glifos diferentes.

## Desvios investigados na F07.1
| Desvio | Causa comprovada | Ação | Resultado |
|---|---|---|---|
| Rótulo centralizado da matriz ~7 px abaixo (slides 14–15) | o cabeçalho ficava **5 px mais alto** no PowerPoint (48 → 53 px): margem sup. 21 + entrelinha 24 + margem inf. 20 > linha de 64 px, e o PowerPoint ainda usa a altura natural da fonte para a altura mínima — a linha crescia e empurrava toda a matriz; +2 px da centralização vertical do PowerPoint | `pptx_builder._cell`: zera a margem do lado oposto à âncora (no centro, reduz as duas pelo mesmo valor) — posição do texto inalterada, a linha não cresce | Δy mediano 4 → 0; p95 7 → 2 px; 1,08% → 0,46%. Residual de 2 px nos rótulos centralizados = centralização interna do PowerPoint (limite do renderizador; sem perda de conteúdo) |
| Rótulos longos no eixo (slide 11) | o HTML **abreviava** a categoria ("Outros (fo…", nome completo só no `<title>`, invisível no PDF) e o PPTX recebia o nome completo, que o PowerPoint quebrava em 2 linhas encolhendo a área de plotagem (Δx −24 px) | HTML/PDF passam a **quebrar** o rótulo (até 3 linhas, área de plotagem reservada; a área nativa do PPTX segue a mesma); acima de 3 linhas o rótulo é marcado e a exportação é **bloqueada** com diagnóstico | 1,77% → 0,66%; p95 24 → 8 px; HTML×PDF texto 8 → 1 px; o PDF não perde mais texto. HTML quebra em 3 linhas e o PowerPoint em 2 (algoritmos próprios; conteúdo completo nos dois) |

Regressão visual: só `afrika/11-ranking-componentes` mudou (1 de 62 slides; rótulo completo + barras mais baixas pela
reserva do eixo) — revisado e referência win32 atualizada; Linux regenerada pelo CI (bootstrap temporário).

## Diferenças restantes classificadas (aceitáveis — mecanismo de renderização, sem perda de conteúdo)
| Diferença | Onde | Magnitude | Classificação |
|---|---|---|---|
| Antisserrilhado/rasterização (DirectWrite × Skia) | todos | maior parte do % de "texto" | renderizador |
| Rótulos do eixo Y posicionados pelo PowerPoint | gráficos (slides 06, 10–12) | Δx −8 px | renderizador (eixo nativo editável) |
| Rótulos de dados de pontos de linha | slide 06 (série combinada) | Δy 19 px | deslocamento do rótulo calculado pelo próprio PowerPoint (rótulo editável) |
| Cantos arredondados do cabeçalho da tabela/matriz | 05, 12, 14, 15 | só cantos | célula nativa não tem raio |
| Lista de severidade do neutro (marcador + trilho) → barras horizontais nativas | neutral 11–12 | Δx até 158 px nos rótulos | representação nativa (rótulos alinhados ao eixo, sem trilho); valores/ordem/cores iguais |
| Quebra do rótulo longo 3 linhas (HTML) × 2 (PowerPoint) | afrika 11 (casos com rótulo longo) | 1 linha | algoritmo de quebra do PowerPoint |

Nenhum defeito real remanescente identificado: 0 elemento ausente, 0 texto cortado, 0 quebra de linha divergente,
dimensões iguais, valores dos gráficos conferidos contra a IR aprovada (cache + planilha) em cada exportação.

## Fontes
O PowerPoint aplica as fontes incorporadas Montserrat/Montserrat Black/Poppins sem a fonte instalada; **Be Vietnam
Pro não** (reproduzido também com a incorporação feita pelo próprio PowerPoint) — detalhes e evidência em
`docs/EXPORT.md` §6. A medição acima registra as fontes na sessão para comparar layout, não a disponibilidade de fontes.
Outro computador: NOT_VERIFIED.

## Reproduzir
```
cd frontend && npm run build
AFRIKA_EXPORT_FIDELITY=1 PYTHON=../.venv/Scripts/python.exe npx playwright test e2e/export-fidelity.spec.ts
# relatório: output/export-fidelity/report.{md,json}
```
