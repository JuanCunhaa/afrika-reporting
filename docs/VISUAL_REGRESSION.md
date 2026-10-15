# Regressão e comparação visual dos slides (F06B.1)

Código: motor em `frontend/visual/` (TypeScript sem dependências: `png.ts`, `diff.ts`, `manifest.ts`, `report.ts`,
`capture.ts`), testes unitários `frontend/visual/engine.test.ts` (`npm run test:visual-unit`, imagens sintéticas),
regressão E2E `frontend/e2e/visual.spec.ts` (`npm run test:visual`, também roda dentro de `npm run test:e2e`), fixture
sintética `frontend/e2e/visual-fixture.ts` e tema sintético alternativo `frontend/e2e/visual-theme.ts`. Referências
versionadas: `frontend/visual/baselines/<plataforma>/<caso>/NN-slot.{png,json}`; tolerâncias: `frontend/visual/tolerances.json`.

## Captura determinística
- Rota `#/render/{id}[/{revisão}]` (`RenderPage.tsx`): todos os slides empilhados em **tamanho nativo** (escala 1), sem a
  interface do editor; `data-render-ready` só depois de `document.fonts.ready` e da decodificação das imagens do tema.
- Playwright/Chromium: viewport 1280×720, `deviceScaleFactor` 1, captura por elemento com `animations: 'disabled'`,
  `caret: 'hide'`, `scale: 'css'`.
- **Manifesto por slide** (elementos com `data-el`): caixa no slide, hash SHA-256 do texto normalizado (o texto não é
  gravado), fonte computada (família/tamanho/peso/estilo), **fontes reais de plataforma** usadas pelo Chromium (CDP
  `CSS.getPlatformFontsForNode`), cor e fundo. `data-provenance` (indicador|competência|estado|origem) acompanha KPIs,
  barras, pontos, linhas de tabela e severidades.
- Fixture: cliente de nome fixo, 12 competências aprovadas com duas lacunas (2026-04, 2026-07), valores manuais
  justificados, template com os **11 tipos × todos os layouts** (19 slides) + indisponível/ausente; dois casos:
  `neutral-demo` (tema da F06A) e `alt-fixed-4x3` (tema próprio sintético 960×720, regiões fixas, logotipo PNG
  sintético como ativo local, Georgia/Verdana/Consolas, legenda embaixo, rodapé com texto próprio).

## Comparação (implementação própria)
1. **Dimensões** diferentes ⇒ falha sem comparação por pixel.
2. **Pixel**: diferença perceptual YIQ (coeficientes de Kotsarenko & Ramos) com composição sobre branco; pixels de
   **antisserrilhado** identificados pela heurística de vizinhança (Vysniauskas) e contados À PARTE (`aa_pixels`), nunca
   escondidos. Limiar de cor 0 (qualquer diferença conta).
3. **Regiões**: células de 16 px com diferença agrupadas por vizinhança ⇒ caixas com contagens.
4. **Manifesto** (referência × candidato): elemento ausente/novo ou hash de texto diferente ⇒ **conteúdo**;
   família/tamanho/peso/estilo ou fonte de plataforma diferente ⇒ **fonte**; deslocamento/redimensionamento além da
   tolerância de geometria ⇒ **layout** (lista de desalinhados com dx/dy/dw/dh e alinhamentos rompidos entre elementos
   que compartilhavam borda); cor/fundo ⇒ **estilo**.
5. Cada região herda a categoria de maior prioridade dos elementos que a intersectam (conteúdo > fonte > layout >
   estilo); região sobre elemento sem diferença semântica ⇒ **rasterização** (antisserrilhado/subpixel/renderizador);
   fora de elementos mapeados ⇒ **não atribuída**.
6. Relatório: `test-results/visual/report.{json,md}` (ambiente, tolerâncias aplicadas, ruído medido na execução,
   veredito por slide, categorias, desalinhados, regiões) + PNG de diferença por slide divergente (vermelho =
   diferença, amarelo = antisserrilhado) + candidatas em `test-results/visual/candidates/`.

## Tolerâncias — medidas, não arbitrárias
- Cada execução captura cada slide **2×** (3× com `VISUAL_MEASURE=1`) em páginas independentes e mede o ruído
  (pixels, antisserrilhado, geometria). O teste falha se o ruído exceder o registrado para a plataforma ou se o
  manifesto variar entre capturas.
- Veredito: `diff_pixels ≤ max_diff_pixels` **e** `aa_pixels ≤ max_aa_pixels` **e** nenhuma diferença de manifesto
  (geometria com tolerância medida). Nenhuma porcentagem é usada como prova de fidelidade.

| Plataforma | Medição | Ruído (dif./antisserr./geometria) | Tolerância aplicada |
|---|---|---|---|
| win32 (Chromium 156.0.8078.4) | 3 capturas × 19 slides (2026-10-15) | 0 / 0 / 0 px | 0 / 0 / 0 |
| linux (CI) | *a medir no bootstrap do CI* | — | — |

Por que referências por plataforma: a rasterização de fontes difere entre sistemas (DirectWrite × FreeType/Skia) e as
famílias disponíveis também (ex.: `Segoe UI` no Windows); a diferença entre plataformas é justamente da categoria
"fonte/rasterização" e não deve contaminar a regressão de layout/conteúdo.

## Operação
- Atualizar referências (após revisar o relatório e as candidatas): `VISUAL_UPDATE=1 npm run test:visual`.
- Medir ruído e registrar tolerância da plataforma: `VISUAL_MEASURE=1 npm run test:visual`.
- Plataforma nova (ex.: CI Linux): `VISUAL_BOOTSTRAP=1` guarda as capturas como candidatas e **não falha** por falta de
  referência — usado só uma vez para criar a referência revisada (artefato `visual-regression` do CI); nunca permanente.

## Evidências desta fase
- Etapa A (conversão para tokens): 19/19 slides idênticos às capturas anteriores à refatoração (pixel e manifesto).
- Etapa B (correções deliberadas): o relatório isolou exatamente capa (conteúdo: período), sumário/KPIs (layout:
  legenda/cartões subiram 28 px, saindo do rodapé), gráficos com texto (escala) e mudanças **invisíveis** de geometria de
  contêiner (0 pixel, só manifesto) nos demais.
- Caso `alt-fixed-4x3`: rótulos de mês estreitos rarefeitos em vez de truncados — só o slide afetado mudou.

## Comparação futura com o PPTX oficial (pendente do arquivo aprovado)
1. Exportar cada slide do PPTX aprovado para PNG **localmente** (PowerPoint "Exportar → PNG" na resolução 1280×720, ou
   LibreOffice headless), fora do Git (`private/`).
2. Montar a apresentação equivalente com dados sintéticos/aprovados e o tema oficial; capturar via `#/render`.
3. Comparar com o mesmo motor (sem manifesto do lado PPTX, ou com manifesto derivado das caixas do relatório de
   inspeção): a tolerância entre **renderizadores diferentes** (PowerPoint × Chromium) precisa ser medida com slides de
   controle (formas e textos simples) antes de qualquer veredito; diferenças de fonte/rasterização serão reportadas como
   tal, não como fidelidade "percentual".
4. Verificação semântica obrigatória junto: nº de slides, textos (hash), valores e datas.

## Limitações
- Atribuição de categoria é heurística (efeito cascata: um elemento que cresce desloca os seguintes; o primeiro
  elemento alterado na ordem do documento costuma ser a causa).
- Antisserrilhado é detectado por vizinhança; texto muito pequeno pode gerar diferenças "reais" que são só
  rasterização — por isso a tolerância é medida por plataforma.
- Referências Linux dependem da imagem do runner (fontes do sistema); atualização do runner pode exigir nova
  referência (o relatório mostrará "fonte").
