# Devolutiva Claude → ChatGPT PO — F06B.1: Preparação do Motor Visual Oficial (2026-10-15)

- **Fase / commits:** F06B.1 / `main` / **`4cc9c61`** (implementação + testes + docs técnicas + referências visuais
  win32) → `__COMMIT_LINUX__` (referências visuais Linux geradas no CI e revisadas; fim do modo bootstrap) → commit de
  checkpoint (STATUS/handoff). Push feito. **F06B (reprodução definitiva), F07 e F08 NÃO iniciadas.**
- **CI:** __CI_SUMMARY__
- Modelo: Opus 5.5 (ambiente). Nenhum subagente. **Nenhuma chamada à Veracode**; nenhuma credencial alterada.

## 1. Funcionalidades implementadas
- **Temas versionados** (`backend/app/presentations/themes.py`, migration `0006_themes`): esquema tipado e completo de
  tokens; versões imutáveis (append-only por gatilho, `definition_hash` sobre todos os valores, auditoria
  `theme.version_created`); temas embutidos no código (só `neutral-demo@1`, provisório) e próprios no banco local;
  API (`/api/presentation-themes…`) e CLI (`theme-create`). **Tema por cliente** via template (cada dono escolhe o seu).
- **Ativos locais** (`assets.py`): logos/fontes/fundos por SHA-256 em `AFRIKA_ASSET_DIR` (padrão `data/theme-assets/`,
  ignorado); tipo pela assinatura; SVG saneado; servido com CSP sandbox e conferência de hash; ativo ausente = aviso.
- **Renderizador sem valores codificados** (`SlideView.tsx` + `theme.ts` + CSS): ~120 variáveis de tema; regiões
  `flow`/`fixed`, sobreposição por layout, cabeçalho/rodapé configuráveis, capa/encerramento, fundos, imagens, `@font-face`
  de fontes locais, geometria SVG dos gráficos por token, canvas de qualquer proporção (testado 16:9 e 4:3).
- **Rota de captura** `#/render/{id}[/{rev}]` (escala 1, sinal `data-render-ready`) e marcadores `data-el` /
  `data-provenance` (indicador|competência|estado|origem) nos componentes.
- **Inspeção PPTX local** (`inspect-pptx`) + **PPTX sintético** (`synthetic-pptx`) + **rascunho de tema** não aprovado.
- **Motor de comparação visual** (`frontend/visual/`, TypeScript sem dependências) + regressão E2E com 2 temas × 19
  slides + relatório JSON/Markdown + PNG de diferença + tolerâncias medidas por plataforma.
- **Editor**: correções de confiabilidade (seção 6) e testes específicos.
- Revisão dos 11 tipos: período da capa legível (`period_label`, backend), legenda não invade mais o rodapé, gráfico no
  layout com texto em escala real, rótulos de mês rarefeitos em vez de truncados; unidades/lacunas/ausentes/manuais e
  proveniência preservados (proveniência agora também por elemento). Nada foi convertido em imagem.

## 2. Formato dos temas
`{name, description, provisional, notice, canvas{width,height}, colors{token:#hex}, fonts{heading,body,numeric:{stack[],
export_family, asset?}}, weights, sizes, line_heights, spacing, radii, borders, layout{mode flow|fixed, body, header,
content, footer{x,w,bottom,reserve}, visual_side_ratio, summary_ratio}, layouts{<layout>: overrides}, header, footer{show,
items[], separator, custom_text}, cover, closing, backgrounds{default,cover,closing}, images[{name, asset, box, slides,
fit, alt}], charts{viewBox, recuos, barras, linhas, lacunas, severidade, ranking, legenda…}}`. Validação: cores
obrigatórias e referências, caixas no canvas, **conteúdo não invade o rodapé**, fontes com genérica no fim e nomes
seguros, ativos do tipo certo, layouts conhecidos. Exemplo sintético completo: `frontend/e2e/visual-theme.ts`. Detalhes:
`docs/THEMES.md`. **Decisão:** o catálogo (`GET /api/presentation-catalog`) passou a listar **resumos** de temas (antes:
a definição do tema embutido); o tema completo continua em `view.theme` e em `GET /api/presentation-themes/{k}/versions/{v}`.

## 3. Capacidades de inspeção PPTX
Local, só biblioteca padrão, sem rede, sem executar/ler macros, OLE ou planilhas, sem extrair arquivos; limites contra
zip bomb e XML com DOCTYPE. Relatório (`report.json`/`report.md`, em `output/` ou fora do repo — área versionável é
recusada): nº/ordem/ocultos, dimensões (EMU/pol/px/proporção), masters/layouts (placeholders com caixas, estilos de
texto, elementos estáticos, uso por slide), tema (12 slots de cor, fontes major/minor), cores e fontes usadas
(+ tamanhos), formas (caixa em px com grupos e herança de placeholder), textos (só estatísticas), gráficos (tipo,
séries, pontos, formatos — **sem valores/categorias**), tabelas (dimensões, mesclas, estilo), imagens (formato, pixels,
hash, uso), elementos reutilizáveis (estáticos de master/layout, imagens repetidas, geometrias repetidas) e **não
reproduzíveis** com classe e tratamento (SmartArt, OLE, vídeo, animação, chartex, macros, EMF/WMF, WordArt, 3D, efeitos,
geometria livre, gradiente, fontes incorporadas, dados vinculados…). Privacidade: nenhum texto/valor/nota/comentário;
`strict` (padrão) também sem nomes/arquivo/URLs; testado com sentinelas. `--theme-draft` gera tema provisório validado
(cores do esquema, fontes, regiões dos placeholders do master) com `needs_review`. Doc: `docs/PPTX_INSPECTION.md`.

## 4. Estratégia de comparação visual
Captura determinística (rota de render, escala 1, viewport do canvas, DPR 1, sem animação/cursor, espera de fontes e
imagens) + **manifesto** por elemento (caixa, hash do texto, fonte computada e **fonte real de plataforma** via CDP, cores)
→ comparação: dimensões; pixel (YIQ perceptual, limiar 0) com **antisserrilhado contado à parte**; regiões; diferenças de
manifesto classificadas em **conteúdo / fonte / layout / estilo** e regiões atribuídas (sem diferença semântica =
**rasterização**); lista de desalinhados (dx/dy/dw/dh) e alinhamentos rompidos. **Tolerâncias medidas**: cada execução
captura 2× (3× em medição) e falha se o ruído exceder o registrado; win32: 0/0/0; linux: __LINUX_TOL__. Referências por
plataforma (fontes/rasterização diferem entre SOs). Evidência de uso real nesta fase: a conversão do tema F06A foi
provada idêntica (19/19) e as correções deliberadas apareceram isoladas e corretamente categorizadas. Comparação com o
PPTX oficial: plano em `docs/VISUAL_REGRESSION.md` (exportar PNG localmente, medir tolerância entre renderizadores com
slides de controle antes de qualquer veredito). **Pendente** até o arquivo aprovado.

## 5. Testes
| Verificação | Resultado |
|---|---|
| `python -m pytest -q` (local) | **PASS 479** (438 + 41: temas 29, PPTX 9, confiabilidade backend 3) |
| E2E Chromium `npm run test:e2e` | **PASS 30/30** (24 + 6: regressão visual 1 [38 slides], confiabilidade 5) em **3 rodadas completas** locais |
| Repetições: `presentations` + `editor-reliability` + `scopes` ×5 | **PASS 50/50**; `editor-reliability` ×3 isolado 15/15 |
| Regressão visual (win32) | **38/38 PASS** (2 temas × 19 slides), ruído medido 0 em 3 capturas |
| Motor visual `npm run test:visual-unit` | **PASS 11/11** (PNG, diff, antisserrilhado, regiões, manifesto, veredito) |
| build; `npm audit` (total e prod); `pip check` | OK; 0 vulnerabilidades; OK |
| gitleaks (staged) | 0 achados |
| `check_repo`; `check_env_example` | OK (F06B.1); SEGURO |
| migrations CLI (migrate, db-status, seed ×2, migrate) em banco novo | OK (`0006_themes`); CLI inspect→draft→theme-create OK |
| CI GitHub | __CI_TABLE__ |
| `tests_live` | NOT_RUN (fase sem chamadas reais) |

## 6. Intermitência do editor
- **Defeitos reproduzidos e corrigidos (com teste de regressão):** **D1** — edição feita enquanto o PUT estava em
  andamento era sobrescrita pela releitura (reproduzido com resposta de salvamento retida); **D2** — após "Descartar",
  uma pré-visualização atrasada reexibia o conteúdo descartado. Também: voltar manualmente ao texto salvo deixava
  visualização/erro órfãos; falha na releitura após HTTP 200 aparecia como erro genérico (agora "a revisão N foi
  gravada, mas a releitura falhou", sem retry e sem "alterações não salvas" falso); duplo clique tem guarda síncrona
  (1 PUT). Concorrência entre abas e resposta antiga após edição mais recente já estavam corretas (agora testadas).
- **Intermitência F06A (GET sem resposta > 5 s após PUT 200): NOT_REPRODUCED.** Evidência: experimento de carga real
  (uvicorn + proxy do Vite, 6 editores concorrentes, 60 s, 4.335 requisições incluindo 489 releituras triplas logo
  após o 200): 0 erros reais, 0 requisições > 2 s, máx. 744 ms; backend: leitura imediata após 200 consistente com 4
  leitores/pré-visualizações concorrentes; E2E 50/50 em repetição. **Não há evidência de que o SQLite seja a causa**;
  nenhum retry foi adicionado. Com a correção de D1, o editor não depende mais da releitura para o estado salvo.

## 7. Limitações de elementos editáveis (PPTX futuro)
Matriz em `docs/PRESENTATIONS.md`: textos → caixas/placeholder editáveis; KPIs/tabelas/ranking/comparação → tabelas ou
caixas editáveis; barras/linhas/série → gráficos nativos (dados da IR; lacuna = ponto vazio); severidade → barras nativas
ou tabela; logos/fundos → imagem (não vetorial; SVG requer PNG de reserva); faixas/barras → formas nativas. Sem
equivalente editável exato: textura CSS repetida da severidade desconhecida, `object-fit: cover` (vira recorte),
rarefação de rótulos (decidida pelo PowerPoint), escala de eixo (geometria). Exportação NOT_STARTED (F07).

## 8. Riscos, decisões e observações
1. **Template oficial ausente**: nada de identidade visual foi inventado; tema neutro segue provisório.
2. `neutral-demo@1` convertido ao novo esquema com 3 correções visuais deliberadas (evidência de diff); hash fixado a
   partir de agora (mudança futura = v2).
3. Referências Linux dependem da imagem do runner do GitHub (fontes); atualização do runner pode exigir nova referência
   (o relatório categoriza como fonte/rasterização).
4. Observação para o PO (não alterado): o contrato F04 de `licenses.usage` usa unidade `findings` — provavelmente
   deveria ser "licenças"; mudar exige nova versão de contrato.
5. Identidade declarada (sem autenticação); SQLite local; upload de ativos só em loopback.

## 9. Dependências para concluir a F06B
1. **PPTX de referência aprovado** (fora do repo) e confirmação de quais slides/variações são oficiais.
2. Fontes oficiais **licenciadas** (arquivos ou nomes) e logos aprovados como ativos locais.
3. Decisões do PO sobre tokens sem equivalente no PPTX (rampa de severidade, cores de lacuna/manual) e sobre elementos
   não reproduzíveis apontados pela inspeção.
4. Mapeamento de cada bloco do template oficial a `metric_id` + versões de contrato e `required_metrics`.
5. Renderizações PNG de referência exportadas localmente do PPTX aprovado para a comparação visual.

**Prompt sugerido para a próxima fase (não executado):** "F06B.2 — Com o PPTX de referência aprovado (fora do repo),
rodar `inspect-pptx --theme-draft`, revisar o rascunho com o PO e criar o tema oficial versionado (ativos licenciados
locais); publicar as versões de template correspondentes mapeando cada bloco a `metric_id` + contrato e
`required_metrics`; exportar localmente os slides de referência em PNG, medir a tolerância PowerPoint×Chromium com slides
de controle e rodar a comparação visual + verificação semântica (nº de slides, textos, valores); manter o tema
demonstrativo; sem exportação PPTX/PDF (F07)."

---

## Versão compacta para o PO
F06B.1 concluída localmente (`4cc9c61` + referências Linux; __CI_SHORT__). Temas versionados com tokens completos e
ativos locais fora do Git (tema por cliente via template; componentes sem valores codificados; F06A preservada — 19/19
idêntico antes das 3 correções deliberadas), inspeção local de PPTX sem conteúdo confidencial (com rascunho de tema),
motor de comparação visual próprio com manifesto e tolerâncias medidas (win32 0; 38/38), e editor corrigido (2 defeitos
reproduzidos e cobertos). Testes: pytest 479, E2E 30 (×3), visual 38/38, unit 11, build/audit/pip/gitleaks OK.
Intermitência F06A não reproduzida (sem evidência contra SQLite; sem retry). F06B definitiva aguarda o PPTX aprovado.
