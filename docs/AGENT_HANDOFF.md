# Devolutiva Claude → ChatGPT PO — F06C: Homologação visual e preparação para exportação (2026-10-16)

- **Fase / commits:** F06C / `main` / **`42a64e4`** (implementação + testes + docs + referências win32 + bootstrap temporário do CI) → **`80c6f17`** (referências Linux do caso `afrika-v2` revisadas, ruído medido, fim do bootstrap) → commit de checkpoint (STATUS/handoff). Push feito. **F07 e F08 NÃO iniciadas.**
- **CI:** run `38923537613` (SHA `80c6f17`, modo **estrito**) — **success**: Backend 3.11 e 3.14 (525 passed cada), Frontend typecheck+build + motor visual (12/12), E2E Chromium (35 passed + 2 skipped — as comparações locais com a referência), regressão visual Linux **62/62 PASS** (ruído 0, overflow 0, fontes de reserva 0). Bootstrap: run `38922993662` (`42a64e4`) — success (54/54 antigos idênticos; 8 candidatas do `afrika-v2` revisadas; ruído 0 em 3 capturas).
- Modelo: Opus 5.5 (ambiente). Nenhum subagente. **Nenhuma chamada à Veracode**; nenhuma credencial alterada; nenhuma
  dependência nova.
- **PowerPoint de referência:** só local (`references/`, ignorado; SHA-256 inalterado). Comparações usaram só o
  relatório `strict` e os PNGs locais **processados por código**; nenhuma renderização da referência nem PNG de diferença
  foi aberto por assistente de IA ou enviado a serviço externo — a análise usou só números agregados.

## 1. Contratos visuais finalizados
| Contrato | Onde | Resumo |
|---|---|---|
| Direção desejável por indicador | `metrics/contracts.py` (`Direction`), `registry.DESIRED_DIRECTIONS` | `LOWER_IS_BETTER`/`HIGHER_IS_BETTER`/`NEUTRAL` (padrão); metadado de apresentação — não muda `version` nem valores; exposto no catálogo |
| Tendência comprovada na IR | `charts.trend()` → `comparison.rows[].direction/trend/trend_reason/trend_color` | melhora/piora **só** com variação entre aprovados comparáveis **e** direção declarada; senão `unchanged`/`unknown` (neutra) |
| Semântica de cores no tema | `themes.Semantics` (`severity {levels, mapping, unknown}`, `variation {…, tint_opacity}`) | `severity.*` passam a ser derivados (fonte única); paleta efetiva pública; sem semântica = visual F06B |
| Encaixes de ativos locais | `themes.AssetSlot`, `brand_assets.py`, `GET /api/brand-assets/{tema}/{encaixe}`, CLI `brand-assets-status` | pasta ignorada configurável, validação de bytes/SVG, fallback neutro, nunca bloqueia |
| Seleção flexível de slides | `POST /api/presentations {slots}` + `GET …/availability?competence_id` + seletor na UI | obrigatórios sempre; sugestão por indicadores aprovados; nada removido automaticamente |
| Plano de exportação (F07) | `export_plan.py`, `GET /api/presentations/{id}/export-plan` | por elemento: texto/forma/tabela/gráfico nativo/imagem; contrato apenas |
| Tokens novos de componente | `components.donut_separator`, `subtitle_color/font/weight/line_height`, `matrix_label_size` | omitidos do hash no padrão |
Docs: `docs/PRESENTATION_CONTRACTS.md`, `docs/THEMES.md`, `docs/METRIC_CATALOG.md`.

**Preservação:** hashes de `neutral-demo@1`, `afrika@1`, `demo-executivo@1`, `demo-tecnico@1`, `demo-minimo@1` e
`afrika-modelo@1` **inalterados** (fixados em teste). Versões novas: `afrika@2` (tema) e `afrika-modelo@2` (mesmos 16
slots/zonas, copiados programaticamente — nada reimplementado). Regressão visual: os 54 slides antigos continuaram
idênticos (tolerância 0).

## 2. Semântica de cores (afrika@2, tokens; nenhum valor fixo em componente)
| Severidade Veracode | Nível do PO | Cor |
|---|---|---|
| Muito alta (5) | Crítica | `#C00000` vermelho |
| Alta (4) | Alta | `#F26B1D` laranja |
| Média (3) | Média | `#FFC000` amarelo |
| Baixa (2) e **Muito baixa (1)** | Baixa | `#2F6FD6` azul (filete de 3 px separa as fatias na rosca) |
| Informativa (0) | Informativa | `#8C8C8C` cinza |
| ausente | Desconhecida | `#B5B5B5` + textura |
Variação: melhora `#2E9E5B` verde · piora `#C00000` vermelho · neutra `#7A7A7A` (tinta 18% na pílula + palavra
"melhora"/"piora"/"estável" — nunca só cor). Paleta checada com o validador de paleta: separação CVD e de visão normal
OK; laranja/amarelo < 3:1 sobre branco ⇒ rótulos sempre visíveis (já são). Direções declaradas: só os 7 indicadores de
backlog de findings ABERTOS (`LOWER_IS_BETTER`); todos os demais neutros.

## 3. Comparações visuais completas (`docs/VISUAL_FIDELITY.md`)
- **A — estrutural mascarada (F06B)**, reexecutada: números idênticos (capa 0,1% · seções 0,3% · painéis 0,4–1,8% ·
  matrizes 0,6% · encerramento 0,7%).
- **B — integral por categoria (nova)**, `afrika-modelo@2` com conteúdo sintético **equivalente** (comprimentos/nº de
  tópicos tirados só das contagens do relatório strict), sem máscara: diferença total 2,6–13,5% por slide, concentrada
  em **texto** (glifos real × sintético: 40–97% da diferença) e **gráficos** (valores sintéticos); **estrutura ≤0,8%**
  da própria área; ativos ausentes = 19–26% da área de logo/ícones nos slides de conteúdo.
- Por categoria: geometria 93 pares (55 ok ≤5 px · 11 aprox. ≤15 px · 27 divergentes, todos classificados);
  **tipografia declarada 24/24 idêntica**; cores 33/39 (6 = tom do título que a própria referência varia); **tipos de
  gráfico 16/16**; overflow **0** no HTML mesmo com textos de comprimento real.
- **Defeitos de layout encontrados e corrigidos** (só em `afrika@2`): subtítulo dos painéis 10–12 (Poppins regular
  cinza → Montserrat Black roxo, como declarado na referência); rótulo de linha da matriz (14 pt → 22 pt); respiro do
  subtítulo até o filete (entrelinha 1,5).
- **Ausência de ativos** explica: área de foto/ilustração (6 pares divergentes; a imagem da referência ainda excede o
  canvas) e logo/ícones/textos do master. **Candidatos a ajuste** (não alterados sem o conteúdo oficial): coluna de
  texto da capa (734 px × caixas 960–1162 px com autofit), altura do gráfico nos slides 10–11, posição da lista no slide
  8. **Inconsistências da referência**: título deslocado 40 px só nos slides 5–7; três tons de título.

## 4. Estado dos ativos
Nenhum ativo oficial recebido/autorizado. Encaixes do `afrika@2`: `logo-capa`, `foto-capa`, `foto-secao`,
`ilustracao-encerramento`, `logo-conteudo`, `icones-laterais` (caixas medidas na inspeção local) — hoje vazios, com
fallback neutro (forma do tema) e aviso informativo. Para usar: copiar os arquivos autorizados para
`data/brand-assets/afrika/<encaixe>.png|jpg|svg` (ou `AFRIKA_BRAND_ASSET_DIR`) e conferir com
`python -m app.cli brand-assets-status --theme afrika --version 2`. Testes usam imagens sintéticas em pasta
descartável.

## 5. Matriz de editabilidade para PPTX (`docs/F07_EXPORT_READINESS.md`)
Textos/tópicos/títulos/rodapé → **texto editável**; painéis, faixas, filete, selo, cartões, pílulas, contornos curvos →
**forma vetorial** (`custGeom` + alpha); KPIs da tabela, comparação em tabela, ranking, matriz → **tabela editável**;
barras, linhas, combinado (mesmo eixo), severidade, roscas → **gráfico nativo** (lacuna = célula vazia, nunca 0);
**imagem só** para ativo de marca autorizado. Verificado no plano gerado para `afrika-modelo@2` + 3 demonstrativos:
0 elementos de dado como imagem. Limitações registradas: tamanho adaptativo, fontes no PPTX, locale do rótulo numérico,
geometria do gráfico nativo, textura, SVG, limite de 400 caracteres por linha de matriz.

## 6. Testes
| Verificação | Resultado |
|---|---|
| `python -m pytest -q` | **PASS 525** (498 + 27 novos em `test_f06c_homologation.py`) |
| E2E Chromium `npx playwright test` | **PASS 35 + 2 SKIPPED** (as 2 comparações com a referência pulam sem o arquivo — esperado) em **3 rodadas completas** locais (Windows) + CI Linux |
| Regressão visual (win32) | **62/62 PASS** (neutro 19 + alternativo 19 + afrika 16 idênticos às referências anteriores + `afrika-v2` 8 novos, revisados); ruído 0; overflow 0; fontes de reserva 0 |
| E2E F06C (`f06c.spec.ts`) | 4/4: seleção por sugestão + pílulas por tendência + cores dos tokens; ativo local × fallback; detector de overflow acha estouros injetados; resposta atrasada descartada (**mutação** sem a guarda ⇒ falha, confirmado) |
| Comparações com a referência (local) | A e B executadas; só números em `output/reference-compare/` |
| Motor visual `npm run test:visual-unit` | **PASS 12/12** |
| build; `npm audit`; `pip check` | OK; 0 vulnerabilidades; OK |
| gitleaks (staged) | 0 achados (em cada commit) |
| `check_repo`; `check_env_example` | OK (F06C: + bloqueio de `brand-assets/`/`data/` rastreados); SEGURO |
| migrations CLI em banco novo | OK (`0006_themes`; sem migration nova; seed cria 5 versões de template) |
| Confiabilidade | salvamentos rápidos, concorrência de revisões e respostas atrasadas: `editor-reliability` e `presentations` PASS nas 3 rodadas + backend (`test_editor_reliability`, integridade de snapshots/apresentações) PASS; novo E2E de resposta atrasada do seletor de slots (validade provada por mutação); overflow Windows × Linux 0; renderização só com fontes OFL empacotadas (0 de reserva); apresentação v1 íntegra após a v2. **Repetições extras (×5) interrompidas pelo Claude Code por falta de memória na máquina — NOT_RUN** (não reiniciadas, conforme orientação) |
| `tests_live` | NOT_RUN (fase sem chamadas reais) |

## 7. Limitações
1. Identidade `afrika@1/@2` continua **provisória**; ativos oficiais ausentes.
2. Tipografia renderizada da referência não é comparável (PowerPoint local sem as fontes); a declarada é.
3. Âncora/recuos de texto do PPTX não expostos no modo strict: Δcentro de caixas de texto mede caixa, não glifo.
4. Equivalência de conteúdo: listas da referência são tabelas (comprimento estimado); números não igualados.
5. "Muito baixa" agrupada em Baixa e rótulos com a nomenclatura Veracode ("Muito alta") — confirmar com o PO.
6. Rosca mostra as 7 severidades (agrupar por nível somaria valores — derivação não autorizada).
7. Linha da matriz limitada a 400 caracteres (a referência tem células maiores).
8. Referências Linux do `afrika-v2` criadas por bootstrap temporário no CI (procedimento das fases anteriores).

## 8. Pendências para o PO
- Confirmar: "Muito baixa" → Baixa; rótulo "Muito alta" × "Crítica"; direções declaradas (só backlog aberto).
- Autorizar/entregar ativos de marca (arquivos locais) e homologar `afrika@2` (identidade).
- Decidir os candidatos a ajuste (coluna de texto da capa, gráfico 10–11, lista 8) com o conteúdo oficial.
- Decidir se a matriz ganha estrutura própria (células > 400 caracteres por linha).

**Prompt sugerido para a próxima fase (não executado):** "F07 — Exportação editável PPTX/PDF a partir do plano de
exportação (`/export-plan`) da revisão aprovada: gerar PPTX com textos, formas (`custGeom`), tabelas e gráficos nativos
(lacuna = célula vazia), imagens só para ativos autorizados; reabrir o PPTX e conferir elemento a elemento contra o
plano; renderizar PPTX→PNG localmente e comparar com o HTML pelo motor visual (tolerância medida por slides de
controle); PDF com fontes incorporadas; sem IA (F08) e sem coleta real."

---

## Versão compacta para o PO
F06C concluída (`42a64e4`, `80c6f17`; CI estrito verde run `38923537613`). Semântica de cores do PO aplicada por tokens em `afrika@2` (severidade por
nível; variação colorida só quando comprovada e com direção declarada — hoje só backlog aberto), templates antigos
intactos (hashes fixados; 54 slides visuais idênticos), `afrika-modelo@2` com seleção flexível de slides (só capa e
encerramento obrigatórios). Comparação integral nova (conteúdo equivalente, por categoria): tipografia 24/24, gráficos
16/16, estrutura ≤0,8%, overflow 0; 2 defeitos corrigidos; demais diferenças classificadas (ativos ausentes,
inconsistências da referência, candidatos a ajuste). Ativos locais com fallback neutro (nenhum oficial ainda). Plano de
exportação + matriz de editabilidade prontos para a F07 (0 dado como imagem). pytest 525, visual 62/62.
