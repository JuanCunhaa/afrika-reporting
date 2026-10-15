# Inspeção local de PPTX de referência (F06B.1)

Código: `backend/app/presentations/pptx_inspect.py` (somente biblioteca padrão: `zipfile` + `ElementTree`), gerador de
PPTX sintético `backend/app/presentations/synthetic_pptx.py`, CLI em `backend/app/cli.py`, testes em
`backend/tests/test_pptx_inspect.py` (só com o PPTX sintético).

## Uso
```bash
cd backend
python -m app.cli inspect-pptx /caminho/fora/do/repo/REFERENCIA.pptx                  # privacidade strict (padrão)
python -m app.cli inspect-pptx REFERENCIA.pptx --privacy structural --theme-draft      # com nomes de layouts/formas
python -m app.cli inspect-pptx REFERENCIA.pptx --out /tmp/inspecao                    # saída fora do repositório
python -m app.cli synthetic-pptx /tmp/sintetico.pptx                                    # arquivo sintético para testar
```
Saída: `report.json` (máquina), `report.md` (leitura) e, com `--theme-draft`, `theme-draft.json`. Padrão:
`output/pptx-inspection/<sha256[:12]>/` (ignorado pelo Git). Um `--out` dentro do repositório que não esteja sob
`output/`, `private/` ou `data/` é **recusado**. O terminal mostra só contagens. `*.pptx`, `*.pdf`, `output/`, `private/`
e `data/` estão no `.gitignore` (verificado em teste).

## Segurança e privacidade
- **Local**: nada é enviado a serviços externos; vínculos externos (imagens, vídeos, hiperlinks, dados de gráfico) são
  apenas **contados**, nunca acessados. Macros (`vbaProject.bin`), OLE e planilhas incorporadas não são executados nem
  lidos (só detectados). O arquivo não é extraído para o disco.
- **Limites**: ≤ 10.000 entradas no pacote; partes XML ≤ 50 MB e razão de compressão suspeita recusada (zip bomb);
  XML com DOCTYPE/entidades é recusado (registrado em `problems`, sem derrubar a inspeção); mídia > 300 MB não é
  hasheada; pacote sem `ppt/presentation.xml` ⇒ "não é PPTX".
- **Sem conteúdo**: nenhum texto de slide, nota, comentário, rótulo/valor de gráfico ou célula é copiado — só
  contagens (parágrafos, runs, caracteres, palavras), negrito, marcadores, campos (`slidenum`, `datetime`),
  alinhamentos, autoajuste, `digit_ratio` (indício de campo numérico/dados) e hiperlinks (quantidade).
- **`strict` (padrão)**: também omite nome do arquivo, do tema, de masters/layouts/formas/seções e de mídia (id +
  hash curto). **`structural`**: inclui nomes de masters/layouts/formas/tema (necessários para mapear placeholders),
  nunca conteúdo. Testes com sentinelas confirmam nos dois modos (JSON, Markdown e rascunho de tema).

## Conteúdo do relatório
| Seção | O que traz |
|---|---|
| `presentation` | nº de slides e ocultos, dimensões (EMU, polegadas, px a 96 dpi, proporção), masters, layouts, fontes incorporadas, seções, notas, comentários, vínculos externos |
| `theme` | esquema de cores (12 slots; `sysClr` ⇒ `lastClr`) e fontes major/minor |
| `masters` | fundo, estilos de texto (título/corpo/outros: tamanho, negrito, fonte resolvida), placeholders com caixas, elementos estáticos (logos, faixas) |
| `layouts` | tipo, fundo, placeholders com caixas, elementos estáticos, slides que usam |
| `slides` (em ordem) | id, layout, oculto, fundo, contagem por tipo de forma, placeholders, estatísticas de texto, gráficos, tabelas, imagens, animação, transição, notas, comentários, sinalizadores; formas com tipo, caixa em px (grupos convertidos para coordenadas do slide; placeholder sem posição herda do layout/master), geometria, preenchimento, linha, efeitos, rotação, texto (estatísticas) |
| gráficos | tipo(s) (barras col/bar, linhas, pizza…), agrupamento, nº de séries e pontos, formatos numéricos, rótulos de dados, largura de intervalo, legenda, eixos, planilha incorporada x dados vinculados, 3D — **sem valores nem categorias** |
| tabelas | linhas, colunas, larguras (px), células mescladas, estilo, flags (primeira linha, faixas), células com dígitos |
| `colors`, `fonts` | cores sRGB mais usadas, referências a cores do esquema, fontes usadas (com `web_safe`), histograma de tamanhos (pt) |
| `media` | formato, pixels (PNG/JPEG/GIF), bytes, SHA-256, onde é usada |
| `reusable` | elementos estáticos de master/layout, imagens repetidas ou de master (candidatas a logo), formas repetidas com a mesma geometria, tipos de placeholder |
| `not_directly_reproducible` | por código: classe (`not_reproducible` / `approximate`), ocorrências, slides e tratamento sugerido — SmartArt, OLE, vídeo/áudio, animações, gráficos modernos (chartex), macros, tinta, imagem vinculada, EMF/WMF/TIFF, fontes incorporadas, WordArt, 3D, sombra/brilho, geometria livre, gradiente/padrão/imagem em forma, texto vertical, rotação, slide oculto, gráfico 3D, planilha incorporada, dados vinculados |
| `problems` | partes ignoradas por segurança ou malformadas |

## Rascunho de tema (`--theme-draft`)
Converte o relatório em uma `ThemeDefinition` **provisória** ("Rascunho … — NÃO aprovado"): canvas pelo tamanho do
slide; cores do esquema (`dk1`→`text.primary`, `lt1`→`surface/page`, `lt2`→`band`, `dk2`→`text.secondary`,
`accent1..4`→`accent`/`series.1..4`); fontes major/minor (com `Arial`/`sans-serif` de reserva); regiões `fixed` a partir
dos placeholders título/corpo/rodapé do master. Lista `mapped_colors`, `needs_review` (tokens sem equivalente no PPTX —
ex.: rampa de severidade, grade, lacuna — e logos a enviar) e `validation_errors`. Nunca é instalado automaticamente.

## Limitações
- Herança de estilo de texto é resumida (estilos do master e tamanhos/fontes explícitos); não resolve cada propriedade
  efetiva por run nem `clrMap` por layout.
- SmartArt, chartex e OLE são detectados, não decompostos.
- Imagens: dimensões só de PNG/JPEG/GIF; EMF/WMF/SVG sem dimensão.
- Não renderiza o PPTX (para comparação visual, exportar slides do PowerPoint/LibreOffice localmente — ver
  `docs/VISUAL_REGRESSION.md`).
