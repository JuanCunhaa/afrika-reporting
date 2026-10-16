# Template de referência Afrika (F06B)

Status: **implementado no HTML, PROVISÓRIO** — a identidade visual (`afrika@1`, `provisional: true`) ainda depende de
homologação do PO. Exportação PPTX/PDF continua fora do escopo (F07).

## 1. Proteção do PowerPoint de referência
- Arquivo **só local** em `references/` (pasta ignorada; `.gitignore` também ignora `*.pptx *.potx *.pptm *.ppt *.ppsx
  *.pdf *.key`). Nunca foi rastreado; `scripts/check_repo.py` falha se qualquer arquivo desses tipos (ou algo em
  `references/`) for rastreado **e** se o nome do cliente/unidade da referência aparecer em arquivo versionado
  (verificação por SHA-256, sem o nome em texto).
- O original nunca é alterado: o SHA-256 foi conferido antes e depois de cada leitura e da renderização (igual).
- Nada foi enviado a serviços externos. A análise usou só a inspeção local em modo `strict` (geometria, cores, fontes,
  contagens — sem texto, números, nomes ou imagens; ver `docs/PPTX_INSPECTION.md`).
- A renderização da referência para comparação (`scripts/render_reference.ps1`, PowerPoint local via COM, somente
  leitura, sem janela, nunca salva) grava em `private/reference-render/` (ignorado). Esses PNGs contêm o conteúdo real:
  **não** são versionados, publicados nem anexados a relatórios. Saídas de comparação ficam em `output/` (ignorado) e
  só os números agregados entram na documentação.

## 2. O que a referência define (extraído estruturalmente)
| Aspecto | Valor usado no tema `afrika@1` |
|---|---|
| Canvas | 1920×1080 (16:9), layout fixo: cabeçalho `0,55,1920,106`, conteúdo `136,200,1732,830` |
| Paleta | roxo de marca `#4A1D6E`/`#5D2482`, tinta `#2B0B43`/`#280F44`, lilases `#F2EEF5 #DCBFEC #F6F3F8 #F7F2FA`, acentos `#8D1C81 #D72369 #FE6041` |
| Status/severidade | `#C00000 #DE425B #FE6041 #FFA600 #FFC000 #2E9E5B` (mapeamento por severidade **inferido** — decisão do PO) |
| Fontes | Montserrat (títulos, Black 50pt centralizado), Poppins (texto/capa), Be Vietnam Pro (números) — OFL, servidas localmente via `@fontsource/*@5.3.0` |
| Cabeçalho | título centralizado + filete 113×5 `#5D2482` abaixo + selo de competência (mês/ano) 133×104 no canto superior direito, lilás com borda roxa |
| Capa | fundo roxo, painel branco a 95% de opacidade com **borda direita curva** (contorno extraído da geometria personalizada), área de foto à direita |
| Seção | fundo roxo, título vertical (270°) grande, área de foto à direita |
| Painéis | cartões brancos com borda lilás e raio 32, faixas lilases de KPI, pílulas de variação, cartões de severidade com barra colorida, roscas, gráfico combinado |
| Encerramento | fundo roxo, painel branco superior com **borda inferior curva**, área de ilustração à direita, título + grupos de texto na base |

## 3. Mapeamento slide a slide (referência → template `afrika-modelo@1`)
| # | Tipo na referência | Slot | Tipo/layout | Componentes |
|---|---|---|---|---|
| 1 | capa | `capa` | `cover` | painel curvo, área de foto, sobretítulo (cliente), título, subtítulo, competência, apresentadores |
| 2–4 | divisores de seção | `secao-abertura`, `secao-indicadores`, `secao-detalhes` | `section` (novo) | título vertical, número/subtítulo, área de foto |
| 5 | painel de KPIs | `painel-kpis` | `dashboard`/`painel-kpis` | zonas `band` (faixa KPI), `cards` (cartões com variação), `table`, `text` |
| 6 | painel de gráficos | `painel-graficos` | `dashboard`/`painel-graficos` | `band`, `list`, `donut_a`, `donut_b`, `detail` (comparação), `chart` (combo) |
| 7 | painel de grupos | `painel-grupos` | `dashboard`/`painel-grupos` | `group_a`, `group_b`, `list`, `detail`, `chart` |
| 8–9 | painéis de severidade | `painel-severidades`, `painel-severidades-dev` | `dashboard`/`painel-severidades` | cartões de severidade ×2, comparação em colunas, tópicos |
| 10–11 | ranking + gráfico | `ranking-aplicacoes`, `ranking-componentes` | `dashboard`/`painel-tabela-grafico` | ranking (top N), observações, gráfico, legenda |
| 12 | destaque + tabela | `destaque-vulnerabilidades` | `dashboard`/`painel-destaque-tabela` | faixa de destaque, ranking |
| 13 | divisor de seção | `secao-plano` | `section` | — |
| 14–15 | matrizes 3 colunas | `matriz-acoes`, `matriz-acompanhamento` | `recommendations`/`matrix` (novo) | cabeçalho roxo, rótulos de linha, células editáveis (`a | b | c | d` por linha) |
| 16 | encerramento | `encerramento` | `closing` (campo `items` novo) | painel curvo, título, grupos “título \| texto” |

Novidades de catálogo (F06B, compatíveis com F06A): tipos `section` e `dashboard` (6 layouts com zonas tipadas);
layouts `kpi-band` (kpis), `severity-cards`/`donut` (severidade), `matrix` (recomendações); gráfico `combo`
(barras + linha); comparação em colunas nas zonas (token de tema `components.zone_comparison`). Detalhes em
`docs/PRESENTATION_CONTRACTS.md`.

## 4. Genérico para qualquer cliente/subcliente
- Textos do template são placeholders editoriais genéricos; nenhum nome, aplicação, número ou indicador da referência.
  A capa usa o nome do dono (cliente **ou** subcliente) vindo do cadastro; clientes sem subclientes funcionam.
- Indicadores entram só por `metric_id` do catálogo, validados por zona (tipo de valor, quantidade, gráfico, série).
  Valores vêm exclusivamente da revisão aprovada; ausente ≠ zero (estado e motivo explícitos).
- Quantidade de slides configurável: só `capa` e `encerramento` são obrigatórios; o editor remove, reordena e adiciona
  slides e edita zonas (título, indicadores, gráfico, dados, meses, top N). `painel-kpis` exige os indicadores do
  template (`required_metrics`).
- Testes: `backend/tests/test_afrika_template.py` (17), `frontend/e2e/afrika.spec.ts` (cliente qualquer → painéis →
  edição de zona → remoção de slide → persistência), caso `afrika` na regressão visual (16 slides sintéticos).

## 5. Fidelidade medida (comparação por slide, local)
Método (`frontend/e2e/reference.spec.ts`, pulado no CI): captura o template com dados **sintéticos** a 1920×1080 e
compara slide *i* com a renderização local do slide *i* da referência. Todo conteúdo (texto, tabela, gráfico, imagem)
é **mascarado dos dois lados** (caixas do relatório `strict` + elementos de texto/gráfico do manifesto HTML), pois é
diferente por definição (real × sintético). Mede-se a estrutura visível: fundos, faixas, cartões, formas, filetes.

| Slide | Tipo | Área mascarada | Dif. Δ>0,03 | Dif. Δ>0,08 | Dif. Δ>0,15 |
|---|---|---|---|---|---|
| 1 | capa | 71,2% | 0,1% | 0,1% | 0,0% |
| 2–4, 13 | seção | 56,9% | 0,3% | 0,3% | 0,3% |
| 5 | painel KPIs | 44,2% | 6,3% | 1,8% | 1,5% |
| 6 | painel gráficos | 51,4% | 5,0% | 1,0% | 0,7% |
| 7 | painel grupos | 58,6% | 2,3% | 0,9% | 0,8% |
| 8 | painel severidades | 43,2% | 5,2% | 1,3% | 1,0% |
| 9 | painel severidades (variação) | 56,2% | 7,4% | 1,2% | 1,1% |
| 10–11 | ranking + gráfico | 75,0% | 3,9% | 0,7% | 0,6% |
| 12 | destaque + tabela | 59,0% | 1,3% | 0,4% | 0,4% |
| 14 / 15 | matriz | 65,8% / 67,1% | 0,9% / 0,7% | 0,6% | 0,5% / 0,6% |
| 16 | encerramento | 55,4% | 0,9% | 0,7% | 0,6% |

Percentuais sobre os pixels **não** mascarados; Δ = distância de cor YIQ normalizada. Evolução durante a fase: capa
8,9% → 0,1% (opacidade + contorno curvo), encerramento 6,8% → 0,7% (contorno curvo), painéis 1,7–3,4% → ≤1,8%.
Geometria: dos 67 pares de elementos não textuais mapeados (`frontend/visual/reference-map.json`), 41 coincidem em
≤2 px (centro e tamanho), 44 em ≤5 px e 51 em ≤15 px. Os demais estão explicados abaixo.
**Leitura correta:** isto mede a estrutura sob máscara; não é prova de fidelidade do conteúdo nem de tipografia.

## 6. Diferenças e limitações conhecidas
1. **Imagens de marca não reproduzidas:** fotos (capa/seções), ilustração do encerramento, logotipos e ícones do
   master (logo no canto superior esquerdo, texto vertical na borda esquerda, três ícones e texto de rodapé) viram áreas
   reservadas/ausentes. Exigem ativos **aprovados** pelo PO (o mecanismo de ativos locais da F06B.1 já os suporta).
2. Áreas de foto/ilustração da referência ultrapassam o canvas; no HTML são recortadas em 1920 px (diferença de caixa
   de 138–275 px sem diferença visível).
3. **Cor da pílula de variação:** a referência usa verde/âmbar/coral (status a ~30% de opacidade). O contrato de
   métrica não define direção desejável (subir é bom ou ruim?), então a pílula é neutra — decisão do PO.
4. Roscas do painel de gráficos: posição ~40–100 px diferente (as molduras da referência se sobrepõem); percentuais
   sobre a rosca não são exibidos (regra de dados da F06A: só valores aprovados, sem cálculo derivado).
5. Painel de severidades (variação, slide 9): a referência desloca o cartão de comparação; o template usa o mesmo
   layout do slide 8 (zona `detail`).
6. Matrizes: alturas de linha iguais no HTML; na referência variam com o texto.
7. Tipografia: as fontes da referência não estavam instaladas na máquina que renderizou o PowerPoint (substitutas do
   PowerPoint); o HTML usa as fontes reais (OFL). Isso afeta só as áreas de texto, que estão mascaradas.
8. Número de página: a referência centraliza no rodapé (master); o tema mostra no canto inferior direito.
9. Faixas de cor sutis (Δ entre 0,03 e 0,08) em painéis: antisserrilhado de bordas arredondadas e lilases muito
   próximos; sem impacto visível.

## 7. Decisões pendentes para o PO
- Homologar a identidade `afrika@1` (hoje `provisional`) e o mapeamento **cor × severidade**.
- Aprovar ativos de marca (logo, fotos, ilustração, ícones) como arquivos locais de tema; sem isso ficam ausentes.
- Definir direção desejável por indicador (para colorir variações) — ou manter neutro.
- Unidade/semântica de `licenses.usage` continua pendente (herdado da F06A; não usado no template Afrika).

## 8. Preparação para F07 (não implementada)
Todas as posições do tema são caixas absolutas em px de um canvas 1920×1080 (convertíveis 1:1 para EMU); formas com
contorno (`components.shapes[].path`, comandos absolutos M/L/C/Q/A/Z) mapeiam para `custGeom`; cada papel de fonte tem
`export_family`; gráficos saem da IR (dados aprovados) e podem virar gráficos nativos; zonas são independentes (cada
uma vira um grupo de formas). Nenhum exportador foi escrito.

## 9. Reproduzir a comparação localmente
```
powershell -ExecutionPolicy Bypass -File scripts/render_reference.ps1 -Pptx references\ARQUIVO.pptx
cd backend && python -m app.cli inspect-pptx ../references/ARQUIVO.pptx --privacy strict --out ../output/pptx-inspection/referencia
cd frontend && AFRIKA_REFERENCE_RENDER=<repo>/private/reference-render AFRIKA_REFERENCE_REPORT=<repo>/output/pptx-inspection/referencia/report.json npx playwright test e2e/reference.spec.ts
```
Saída: `output/reference-compare/report.{md,json}` (só números) e `diffs/` + `html/` (PNGs locais; os diffs contêm a
referência — não publicar).
