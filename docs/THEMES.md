# Temas visuais versionados (F06B.1)

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
| `charts` | viewBox (largura cheia e com texto), recuos do gráfico, divisões do eixo, barras (largura máx., proporção, raio), lacunas (tracejado), linhas/pontos, deslocamentos de rótulos, severidade (colunas e altura), ranking, amostras de legenda, textura da severidade desconhecida, posição da legenda (`top`/`bottom`) | |

Validação além dos tipos (`theme_errors`): tokens de cor obrigatórios e referências existentes; caixas dentro do canvas;
conteúdo (`body`, ou `header`/`content` no modo fixo) **não invade a área reservada ao rodapé**
(`canvas.height − footer.bottom − footer.reserve`); pilhas de fonte com genérica no fim; ativos de fonte só em mídia de
fonte e imagens só em mídia de imagem; layouts conhecidos; `custom_text` exigido quando usado. Erro ⇒ 422
`invalid_theme` com a lista de campos.

Exemplo sintético completo (4:3, regiões fixas, logotipo, outras fontes): `frontend/e2e/visual-theme.ts` (`altTheme`).

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
