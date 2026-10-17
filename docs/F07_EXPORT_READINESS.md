# Prontidão para a F07 — exportação editável PPTX/PDF (preparada na F06C)

> **Histórico.** A F07 implementou este contrato: ver `docs/EXPORT.md` (estratégia, matriz de editabilidade medida,
> fontes, segurança) e `docs/EXPORT_FIDELITY.md` (fidelidade HTML × PPTX × PDF). O texto abaixo é o estado da F06C.

Nenhum exportador foi escrito. A F06C entrega o **contrato** de exportação, derivado da mesma visualização que o HTML usa,
e os testes que garantem as propriedades que a F07 terá de preservar.

## 1. Contrato: plano de exportação
- Código: `backend/app/presentations/export_plan.py` · API: `GET /api/presentations/{id}/export-plan[?revision=n]`
  (somente leitura; `status: CONTRACT_ONLY`; nenhum arquivo gerado).
- Entrada: `view.build` (revisão da apresentação + revisões APROVADAS fixadas + tema). Nada é recalculado.
- Saída: canvas em px e EMU (`emu_per_px = 9525`; 1920×1080 px = 18.288.000×10.287.000 EMU), tema (`id`, `version`,
  `definition_hash`), **paleta efetiva** (tokens já resolvidos, inclusive `severity.*` e `variation.*` da semântica),
  fontes por papel (`html` × `export_family`), por slide a lista ordenada de elementos `{component, export_as, editable,
  binding, …}`, contagens por tipo, encaixes de ativo em fallback, política de lacunas, limitações e a matriz abaixo.
- `binding` aponta para o dado na visualização (ex.: `data.zones.chart.data`, `fields.title`): o exportador lê o valor
  aprovado e o rótulo já formatado da IR — não duplica nem recalcula números.

## 2. Tipos de saída
| `export_as` | Objeto PPTX previsto | Editável |
|---|---|---|
| `text` | `p:sp` com `txBody` (parágrafos, marcadores, `vert270` para título de seção) | sim |
| `shape` | `prstGeom` (rect/roundRect) ou `custGeom` (contorno M/L/C/Q/A/Z do tema), preenchimento com alpha | sim |
| `table` | `graphicFrame` + `a:tbl` | sim |
| `native_chart` | `c:chart` com planilha incorporada (`c:barChart`, `c:lineChart`, barras+linha no mesmo eixo, `c:doughnutChart`) | sim |
| `image` | `p:pic` — **só** ativos de marca autorizados e imagens do tema | não (inevitável) |

## 3. Matriz de editabilidade por tipo de slide (verificada pelo plano gerado a partir de dados sintéticos)
| Tipo / layout | Elementos e saída |
|---|---|
| `cover` | fundo (forma) · painel curvo e área de foto (forma; `custGeom` + alpha 0,95) · dono, título, subtítulo, período, apresentadores (texto) · `logo-capa`/`foto-capa` (imagem, só se o ativo autorizado existir) |
| `section` | fundo + área de foto (forma) · título vertical (texto `vert270`) · número/subtítulo (texto) · `foto-secao` (imagem, opcional) |
| `dashboard/painel-kpis` | título, filete (forma), selo (forma+texto) · faixa de KPIs (moldura forma + valores texto) · cartões com variação (forma + texto + pílula forma) · tabela de indicadores (tabela) · comentário (texto) |
| `dashboard/painel-graficos` | destaques (texto) · tópicos (texto) · 2 roscas (**gráfico nativo** doughnut, cor por severidade) · comparação em colunas (texto + seta forma + pílula) · série combinada (**gráfico nativo** barras + linha, mesmo eixo) |
| `dashboard/painel-grupos` | 2 grupos de KPIs (forma + texto) · tópicos (texto) · comparação (texto + pílula) · gráfico (**nativo**) |
| `dashboard/painel-severidades` | 2 blocos de cartões de severidade (forma da barra + texto) · comparação (texto + pílula) · tópicos (texto) |
| `dashboard/painel-tabela-grafico` | ranking (**tabela**) · observações (texto) · gráfico (**nativo**) · legenda (texto) |
| `dashboard/painel-destaque-tabela` | faixa de destaque (forma + texto) · ranking (**tabela**) |
| `recommendations/matrix` | matriz (**tabela**, 1ª linha = cabeçalho) |
| `recommendations/bullets`, `two-columns` | tópicos (texto) |
| `closing` | painel curvo + área de ilustração (forma) · título, subtítulo, corpo, apresentadores, grupos "título \| texto" (texto) · `ilustracao-encerramento`/`logo-capa` (imagem, opcional) |
| `kpis/kpi-grid`, `kpi-band` | cartões (forma + texto) / valores (texto) |
| `month_comparison` | tabela (**tabela**) / cartões (forma + texto) |
| `bar_chart`, `line_chart`, `severity_distribution` (barras) | **gráfico nativo** (cor por ponto na severidade) |
| `severity_distribution/severity-cards` / `donut` | forma + texto / **gráfico nativo** doughnut |
| `top10_ranking` | tabela / **gráfico nativo** de barras horizontais |
| `metric_table` | **tabela** |
| dado indisponível (qualquer zona) | texto com o motivo ("Dado indisponível" — nunca um número presumido) |
| rodapé, nº de página | texto (campo `slidenum`) |

Resultado da verificação (`test_export_plan_*` e geração para `afrika-modelo@2` + 3 templates demonstrativos): **0
elementos de dado como imagem**; imagem só aparece para ativo autorizado presente na pasta local.

## 4. Lacunas continuam lacunas
- Pontos com estado `GAP`/`MISSING`/`INCOMPATIBLE`/`NOT_NUMERIC` viram `None` nos valores do gráfico nativo (célula
  vazia, `dispBlanksAs="gap"`) e o estado segue no rótulo/legenda ("lacuna", "ausente"); **nunca** 0, nunca interpolação
  (teste: `test_export_plan_maps_every_element_to_editable_kinds_and_keeps_gaps`).
- KPI sem valor aprovado: `value = None` + rótulo de estado; variação sem comparação aprovada: tendência `unknown`
  (neutra).

## 5. Limitações conhecidas (registradas no próprio plano, `limitations`)
| Código | Limitação | Proposta para a F07 |
|---|---|---|
| `adaptive_type` | zonas usam tamanho adaptativo (container queries por largura/caracteres) | calcular o mesmo tamanho no exportador (sem `normAutofit`) |
| `fonts` | PPTX referencia `export_family`; sem a fonte instalada, o PowerPoint substitui | incorporar as OFL no PPTX quando permitido; PDF sempre incorporado |
| `number_format_locale` | formato numérico do gráfico segue o locale de quem abre | usar o rótulo pt-BR já formatado da IR como texto do rótulo de dados |
| `chart_geometry` | escala/eixos do gráfico nativo são do PowerPoint | valores idênticos; geometria comparada por slide de controle |
| `unknown_texture` | textura da severidade "Desconhecida" | `pattFill dkUpDiag` (aproximação editável) |
| `svg_assets` | ativo SVG | `svgBlip` + PNG de reserva |
| matriz | linha da matriz ≤ 400 caracteres (item) | decidir com o PO se a matriz vira estrutura própria (células) — achado da comparação integral |

## 6. Testes que a F07 herda
- `backend/tests/test_f06c_homologation.py`: plano cobre todos os elementos com tipos permitidos; dado nunca vira
  imagem; lacuna → `None`; rosca → doughnut com cor por severidade; combinado → barras+linha; matriz → tabela; título
  de seção vertical; formas `custGeom`; imagem só para ativo autorizado.
- A F07 deverá acrescentar: geração real (`python-pptx` ou equivalente, a decidir), reabertura do PPTX e comparação
  elemento a elemento com o plano, render PPTX→PNG e comparação com o HTML pelo motor visual existente, PDF.
