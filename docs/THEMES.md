# Temas visuais versionados (F06B.1 + F06B + F06C)

Código: `backend/app/presentations/themes.py` (esquema Pydantic `ThemeDefinition`, `extra='forbid'`), ativos locais em
`backend/app/presentations/assets.py`, migration `0006_themes`, tradução para CSS em `frontend/src/presentation/theme.ts`
e renderizador `frontend/src/presentation/SlideView.tsx`.

> Nenhuma identidade visual oficial foi escolhida. O único tema embutido é o **demonstrativo neutro e PROVISÓRIO**
> `neutral-demo@1`. O tema oficial será criado a partir do PPTX de referência aprovado (ver "Fluxo para o tema oficial").

## Princípios
- **Componentes sem valores visuais**: cor, fonte, peso, tamanho, entrelinha, espaçamento, raio, borda, posição de
  regiões, cabeçalho/rodapé, capa/encerramento, fundos, imagens, formato dos gráficos e dimensões do slide vêm do tema.
  O CSS do slide só usa variáveis (`--c-*`, `--ff-*`, `--fs-*`, `--fw-*`, `--lh-*`, `--sp-*`, `--r-*`, `--b-*`, `--hdr-*`,
  `--cov-*`, `--clo-*`, `--ch-*`, `--lay-*`) geradas de `theme.ts`; o SVG dos gráficos lê `theme.charts`.
- **Versão imutável**: `{id, version}` + `definition_hash` (SHA-256 da definição canônica COMPLETA, com todos os tokens
  resolvidos). Mudança = nova versão. Temas próprios ficam em `presentation_themes` (append-only por gatilho); o hash
  de `neutral-demo@1` é fixado em teste (`test_themes.py`).
- **Tema por cliente**: o template referencia `{id, version}` do tema e cada cliente/subcliente escolhe seu template
  (F06A). Clientes diferentes ⇒ templates diferentes ⇒ temas diferentes (testado: `test_each_client_gets_its_own_theme…`).
  A apresentação continua ligada à versão de template (e portanto de tema) com que foi criada.
- **Recursos proprietários fora do Git**: o tema guarda só `{asset_id: sha256, media_type}`; o arquivo fica no
  armazenamento local de ativos (`AFRIKA_ASSET_DIR`, padrão `data/theme-assets/`, ignorado pelo Git).

## Formato (`ThemeDefinition`)
| Grupo | Conteúdo | Observações |
|---|---|---|
| `name`, `description`, `provisional`, `notice` | identificação; `provisional=true` exibe "Tema provisório" no rodapé (item `provisional`) | texto sem `<`/`>`/controle |
| `canvas` | `width`, `height` em px CSS (96 dpi; 12192000 EMU = 1280 px) | `aspect_ratio` é derivado na saída (ex.: `16:9`, `4:3`) |
| `colors` | `token → #RRGGBB` | obrigatórios: `surface, page, band, text.primary/secondary/muted, grid, axis, border, accent, series.1–4, severity.VERY_HIGH…UNKNOWN, gap, manual, warning, delta.up/down`; tokens extras permitidos |
| `fonts` | `heading`, `body`, `numeric`: `{stack[], export_family, asset?}` | pilha termina em família genérica; nomes sem aspas/vírgulas (seguro p/ CSS e PPTX); `asset` = arquivo de fonte local (`@font-face`) |
| `weights`, `sizes`, `line_heights` | pesos (100–900), tamanhos (px) e entrelinhas por papel (título, capa, KPI, tabela, eixo, rótulo, legenda…) | ~30 tamanhos nomeados |
| `spacing`, `radii`, `borders` | espaçamentos, raios e espessuras nomeados | `kicker_letter_spacing_em` em em |
| `layout` | `mode` (`flow`/`fixed`), `body`, `header`, `content` (caixas `{x,y,w,h}`), `footer {x,w,bottom,reserve}`, `visual_side_ratio`, `summary_ratio` | `flow` = título+conteúdo empilhados em `body` (F06A); `fixed` = título e conteúdo em posições independentes (como placeholders de master PPTX) |
| `layouts` | sobreposição por layout do catálogo (`kpi-grid`, `chart-with-text`…): `mode`, caixas, `background`, `hide_footer` | chave precisa existir no catálogo |
| `header`, `footer` | barra de destaque (liga/desliga, largura, cor, recuo, alinhamento); itens do rodapé (`owner_competence`, `source`, `provisional`, `page`, `custom_text`), separador | |
| `cover`, `closing` | faixa da capa (`left`/`top`/`none`, tamanho, cor), recuos, espaçamentos, alinhamento, caixa alta do sobretítulo | |
| `backgrounds` | `default`, `cover`, `closing`: `{color token, image asset, fit}` | |
| `images` | logotipos/imagens: `{name, asset, box, slides: all/cover/closing/content, fit, alt}` | até 8 |
| `components` (F06B; F06C acrescenta `donut_separator`, `subtitle_color/font/weight/line_height`, `matrix_label_size`, omitidos no padrão) | aparência de componentes: cor do título, filete sob o título, selo de competência, cartão, faixa, pílula, tabela, seção, encerramento, capa (cores/fontes/alinhamento), formas decorativas `shapes[]` (`{name, box, fill, opacity, path?, radius, slides}`; `path` = contorno SVG absoluto M/L/C/Q/A/Z em px da caixa), alinhamento vertical do título por layout, moldura por zona (`zone_frames`), comparação de zona `table`/`columns`, caixas absolutas por zona de painel (`dashboards`) | omitido do hash quando igual ao padrão (o hash de `neutral-demo@1` não mudou) |
| `semantics` (F06C) | `severity {levels, mapping, unknown}` e `variation {improvement, worsening, neutral, tint_opacity}` — ver "Semântica de cores" | omitido do hash quando ausente |
| `asset_slots` (F06C) | encaixes de ativos autorizados da pasta local: `{name, box, slides, fit, alt}` (até 12) | omitido do hash quando vazio |
| `charts` | viewBox (largura cheia e com texto), recuos do gráfico, divisões do eixo, barras (largura máx., proporção, raio), lacunas (tracejado), linhas/pontos, deslocamentos de rótulos, severidade (colunas e altura), ranking, amostras de legenda, textura da severidade desconhecida, posição da legenda (`top`/`bottom`) | |

Validação além dos tipos (`theme_errors`): tokens de cor obrigatórios e referências existentes; caixas dentro do canvas;
conteúdo (`body`, ou `header`/`content` no modo fixo) **não invade a área reservada ao rodapé**
(`canvas.height − footer.bottom − footer.reserve`); pilhas de fonte com genérica no fim; ativos de fonte só em mídia de
fonte e imagens só em mídia de imagem; layouts conhecidos; `custom_text` exigido quando usado. Erro ⇒ 422
`invalid_theme` com a lista de campos.

Exemplo sintético completo (4:3, regiões fixas, logotipo, outras fontes): `frontend/e2e/visual-theme.ts` (`altTheme`).

## Semântica de cores (F06C)
- **Severidade por nível**: o tema declara a cor de cada nível semântico (`critical`, `high`, `medium`, `low`,
  `informational`) e o nível de cada severidade Veracode (5 Muito alta … 0 Informativa), mais a cor de "Desconhecida".
  Os tokens `severity.<CHAVE>` consumidos pela IR passam a ser **derivados** — declará-los também em `colors` é erro
  (fonte única). Trocar a cor de um nível ou o nível de uma severidade = nova versão do tema; nenhum componente muda.
- **Variação comprovada**: cores de melhora, piora e neutra + opacidade da tinta da pílula. O renderizador usa
  `variation.<tendência>` no marcador e no fundo da pílula (tinta sobre a superfície) e escreve "melhora"/"piora"/
  "estável" no texto — identidade nunca só por cor. A tendência vem da IR (`trend`), que só é `improvement`/`worsening`
  quando o indicador declara direção desejável e a variação é entre aprovados comparáveis.
- Sem `semantics`, nada muda (temas F06A/F06B: pílula neutra, rampa de severidade de um tom).
- **Paleta efetiva**: `themes.effective_colors()` resolve os derivados; é a paleta pública (`colors`) usada pelo HTML e
  pelo plano de exportação. `declared_colors` mostra só o declarado.

## Encaixes de ativos locais (F06C, `brand_assets.py`)
- Pasta configurável `AFRIKA_BRAND_ASSET_DIR` (padrão `data/brand-assets/`, ignorada pelo Git; `.gitignore` também
  ignora qualquer `brand-assets/`; `check_repo` falha se algo assim for rastreado). Estrutura:
  `<pasta>/<tema>/<encaixe>.<png|jpg|jpeg|svg>` — ex.: `data/brand-assets/afrika/logo-capa.png`.
- O tema declara só nome, caixa, slides e ajuste; o arquivo é procurado a cada visualização (cache por caminho+mtime+
  tamanho). Validação idêntica aos ativos de tema (assinatura, SVG sanitizado, ≤ 5 MB); link para fora da pasta e nomes
  fora de `[a-z0-9-]` são recusados. Inválido ⇒ ignorado + aviso; ausente ⇒ **fallback neutro** (o encaixe fica vazio e
  aparece a forma do tema por baixo) + aviso informativo. Nunca bloqueia.
- Servido por `GET /api/brand-assets/{tema}/{encaixe}` (revalidado a cada leitura, `nosniff`, CSP `sandbox`,
  `no-cache` + ETag). A URL da visualização leva `?v=<sha256>` para trocar de arquivo sem cache velho.
- Operador: `python -m app.cli brand-assets-status --theme afrika --version 2` (só metadados: situação, tipo, SHA-256).
- Diferença para os ativos de tema da F06B.1 (`images`, endereçados por SHA-256 dentro da definição): os encaixes não
  exigem nova versão de tema a cada troca de arquivo e funcionam sem o arquivo. Não enviar estes arquivos a serviços
  externos (inclusive de IA).

## Ativos locais (`assets.py`)
- `POST /api/theme-assets` (corpo = bytes; ≤ 5 MB) ou `python -m app.cli theme-asset-add ARQUIVO` ⇒
  `{asset_id: sha256, media_type, size_bytes}`. Endereçamento por conteúdo: mesmo arquivo ⇒ mesmo id; nome original não é
  guardado.
- Tipo pela **assinatura dos bytes**: PNG, JPEG, SVG, WOFF2, WOFF, TTF, OTF. SVG só bem formado, sem DOCTYPE/entidades,
  `<script>`, `foreignObject`, eventos `on*`, `href`/`url()` externos ou `@import`.
- `GET /api/theme-assets/{sha256}` confere o hash antes de servir (arquivo adulterado ⇒ 409), com `nosniff`,
  `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; sandbox` e cache imutável.
- Tema que referencia ativo inexistente é recusado na criação (422 `theme_asset_missing`); se o arquivo sumir depois
  (ex.: banco copiado sem os ativos), a visualização mostra o aviso `theme_asset_missing` e o elemento não aparece —
  **não bloqueia** dados.

## API e CLI
`GET /api/presentation-themes` (embutidos + próprios, com versões) · `GET /api/presentation-themes/{key}/versions/{v}`
(tema completo + `missing_assets`) · `POST /api/presentation-themes {key, definition, operator}` ·
`POST /api/presentation-themes/{key}/versions {definition, operator, expected_version}` (conflitos: `theme_exists`,
`theme_conflict`, `theme_unchanged`, `builtin_theme_readonly`). CLI: `python -m app.cli theme-create --key K --file
TEMA.json --operator NOME [--expected-version N]`. Auditoria: `theme.version_created` (cadeia F05). O catálogo
(`GET /api/presentation-catalog`) passou a listar **resumos** de temas; o tema completo segue embutido na visualização
de cada apresentação (`view.theme`).

## Compatibilidade com a F06A (evidência)
1. **Etapa A — conversão sem mudança visual**: com o renderizador já tokenizado, os 19 slides da fixture (11 tipos ×
   todos os layouts) ficaram **idênticos pixel a pixel e no manifesto** às capturas feitas antes da refatoração
   (tolerância 0; ruído medido 0). Isso inclui isolar o slide de regras globais da aplicação que vazavam (margem de
   30 px do `<footer>` global, tamanho base herdado), compensadas nos tokens.
2. **Etapa B — correções deliberadas** (relatório do motor visual lista exatamente os slides afetados):
   - região de conteúdo terminava **dentro do rodapé** (legenda sobreposta ao rodapé em KPIs/sumário): `body.h` 612→584,
     `footer.reserve` = 28 px medidos;
   - gráfico em `chart-with-text` era encolhido a ~69% (eixos ~9 px): `charts.plot_width_with_text` = 760;
   - capa mostrava o período como timestamp ISO: agora `period_label` (`01/09/2026 a 30/09/2026`) vem do backend.
   Em eixos de **meses** estreitos, rótulos passam a ser rarefeitos (um a cada N, sempre o último) em vez de truncados
   ("202…"). Nada disso altera dados, IR ou hashes de revisões; apresentações F06A abrem normalmente.

## Tema `afrika@1` (F06B, provisório)
Embutido em `themes.py` (`AFRIKA_V1`), derivado **estruturalmente** do PowerPoint de referência local (cores, fontes,
geometria, contornos — nenhum texto/imagem): canvas 1920×1080 em modo fixo, Montserrat/Poppins/Be Vietnam Pro (OFL,
`@fontsource/*@5.3.0`), filete e selo de competência, painéis com contorno curvo, caixas absolutas das zonas dos 6
painéis. `provisional: true` até homologação. Mapeamento, fidelidade medida e limitações: `docs/AFRIKA_TEMPLATE.md`.

## Tema `afrika@2` (F06C, provisório)
`afrika@2` = `afrika@1` (layout, fontes, contornos, zonas e caixas **inalterados**, copiados programaticamente) +
decisões do PO + achados da comparação integral (`docs/VISUAL_FIDELITY.md`):
| Item | Valor |
|---|---|
| Severidade | Crítica (Muito alta) `#C00000` · Alta `#F26B1D` · Média `#FFC000` · Baixa e Muito baixa `#2F6FD6` · Informativa `#8C8C8C` · Desconhecida `#B5B5B5` + textura |
| Variação | melhora `#2E9E5B` · piora `#C00000` · neutra `#7A7A7A` · tinta 18% |
| Paleta validada | validador de paleta (dataviz): separação CVD e de visão normal OK para severidade e variação; laranja/amarelo < 3:1 sobre branco ⇒ rótulos sempre visíveis (cartões, legenda, valores); cinza da Informativa é intencional (status, não série) |
| Rosca | filete de 3 px da cor da superfície entre fatias (`components.donut_separator`) — separa Baixa/Muito baixa (mesma cor) |
| Subtítulo | Montserrat 900, `brand.deep`, entrelinha 1,5 (`components.subtitle_*`) |
| Matriz | rótulo de linha 22 pt (`components.matrix_label_size`) |
| Encaixes | `logo-capa`, `foto-capa`, `foto-secao`, `ilustracao-encerramento`, `logo-conteudo`, `icones-laterais` (caixas medidas na inspeção local) |
`afrika-modelo@2` = os mesmos 16 slots/zonas da v1, apontando para `afrika@2`. Pendências: "Muito baixa" agrupada em
Baixa (confirmar), rótulos seguem a nomenclatura Veracode ("Muito alta", não "Crítica"), identidade ainda provisória.

## Fluxo para o tema oficial (quando o PPTX aprovado chegar)
1. `python -m app.cli inspect-pptx REFERENCIA.pptx --theme-draft` (local; relatório em `output/`) — ver
   `docs/PPTX_INSPECTION.md`.
2. Revisar `theme-draft.json` (cores do esquema, fontes, regiões dos placeholders do master; `needs_review` lista o que
   não tem equivalente no PPTX, ex.: rampa de severidade) e decidir com o PO.
3. Enviar logos/fontes licenciados como ativos locais; referenciar no tema.
4. `theme-create` (ou API) ⇒ `oficial@1`; nova versão de template apontando para ele; escolha por cliente.
5. Regressão visual contra renderizações do PPTX aprovado (`docs/VISUAL_REGRESSION.md`).

## Limitações
- Uma fonte por família (arquivo único; pesos sintetizados pelo navegador se faltarem variantes).
- Regiões cobrem cabeçalho/conteúdo/rodapé/imagens; posicionamento livre por elemento (cada caixa de texto do master)
  ainda não — virá com o mapeamento do template oficial, se necessário.
- Tema não muda a semântica dos componentes (quantidade de KPIs por linha, ordem de colunas de tabela).
- Sem editor visual de temas (JSON + validação).
