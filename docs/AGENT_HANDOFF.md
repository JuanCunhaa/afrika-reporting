# Devolutiva Claude → ChatGPT PO — F06B: Template de referência Afrika (2026-10-15)

- **Fase / commits:** F06B / `main` / __COMMITS__. Push feito. **F07 e F08 NÃO iniciadas.**
- **CI:** __CI__
- Modelo: Opus 5.5 (ambiente). Nenhum subagente. **Nenhuma chamada à Veracode**; nenhuma credencial alterada.
- **PowerPoint de referência:** só local em `references/` (ignorado, nunca rastreado); original **intacto** (SHA-256
  conferido antes/depois de cada leitura e da renderização); nada enviado a serviços externos; nenhum texto, número,
  nome ou imagem dele entrou no repositório, em prompts, logs ou fixtures.

## 1. Layouts implementados (template `afrika-modelo@1` + tema `afrika@1`, provisório)
Sequência de 16 slots espelhando a referência, todos com conteúdo sintético/placeholder e indicadores só por `metric_id`:
| # | Slot | Tipo/layout | Componentes |
|---|---|---|---|
| 1 | `capa` | `cover` | painel branco 95% com borda direita curva (contorno extraído), área de foto, sobretítulo, título, competência, apresentadores |
| 2–4, 13 | `secao-*` | **`section` (novo)** | fundo roxo, título vertical, subtítulo/número, área de foto |
| 5 | `painel-kpis` | **`dashboard`/painel-kpis** | faixa de KPIs, cartões com pílula de variação, tabela, comentário |
| 6 | `painel-graficos` | dashboard/painel-graficos | destaques, tópicos, 2 roscas, comparação, **gráfico combo** |
| 7 | `painel-grupos` | dashboard/painel-grupos | 2 grupos de KPIs, tópicos, comparação, gráfico |
| 8–9 | `painel-severidades(-dev)` | dashboard/painel-severidades | 2 blocos de cartões de severidade, comparação em colunas, tópicos |
| 10–11 | `ranking-*` | dashboard/painel-tabela-grafico | ranking top N, observações, gráfico, legenda |
| 12 | `destaque-vulnerabilidades` | dashboard/painel-destaque-tabela | faixa de destaque, ranking |
| 14–15 | `matriz-*` | `recommendations`/**`matrix` (novo)** | cabeçalho roxo, rótulos de linha, células editáveis |
| 16 | `encerramento` | `closing` (+`items`) | painel com borda inferior curva, título, grupos “título \| texto” |
Cabeçalho comum: título Montserrat Black centralizado, filete 113×5 e **selo de competência** (mês/ano). Mapeamento
completo e tokens: `docs/AFRIKA_TEMPLATE.md`.

## 2. Arquivos alterados
- Backend: `presentations/catalog.py` (tipos `section`/`dashboard`, `DASHBOARD_LAYOUTS` com zonas tipadas, layouts
  `kpi-band`, `severity-cards`, `donut`, `matrix`), `document.py` (modelo `Zone` + validação; `zones` vazio não é
  serializado), `view.py` (IR por zona, seção), `charts.py` (`combo`; rótulo de ranking do adaptador),
  `themes.py` (grupo `components`; tema `afrika@1`), `templates.py` (`afrika-modelo@1`), `pptx_inspect.py` (cores
  efetivas, opacidade, contorno de geometria personalizada, estilo de texto sem texto, `svgBlip`, wireframes), `cli.py`
  (`--wireframes`).
- Frontend: `SlideView.tsx` (seção, painel/zonas, faixa e cartões de KPI, cartões de severidade, rosca, combo, matriz,
  comparação em colunas, formas com contorno/opacidade, selo, filete), `theme.ts`, `presentationsApi.ts`, `styles.css`,
  `PresentationEditorPage.tsx` (editor de zonas), `main.tsx` + `package.json/lock` (fontes OFL `@fontsource/*@5.3.0`).
- Visual: `visual/diff.ts` (máscaras), `engine.test.ts`, `reference-map.json`, `e2e/visual-fixture.ts` e
  `visual.spec.ts` (caso `afrika`, viewport 1920×1080), `e2e/reference.spec.ts` (comparação local), referências
  `baselines/{win32,linux}/afrika/`.
- Testes: `test_afrika_template.py` (novo, 17), `test_pptx_inspect.py` (+1), `test_presentations.py`/`test_api.py`
  (4 templates embutidos), `e2e/afrika.spec.ts` (novo).
- Segurança/scripts: `.gitignore` (`references/`, `*.potx *.pptm *.ppt *.ppsx *.key`), `scripts/check_repo.py` (falha
  com arquivo de referência rastreado ou nome do cliente da referência em arquivo versionado — via SHA-256),
  `scripts/render_reference.ps1` (render local somente leitura).
- Docs: `AFRIKA_TEMPLATE.md` (novo), `THEMES.md`, `PRESENTATIONS.md`, `PRESENTATION_CONTRACTS.md`,
  `VISUAL_REGRESSION.md`, `PPTX_INSPECTION.md`, `SECURITY.md`, `STATUS.md`; `prompts/F06B_AFRIKA_TEMPLATE.md`.

## 3. Decisões
1. **Análise só estrutural** (inspeção `strict`): nunca li texto/números/imagens do PPTX; renderizações reais ficam em
   `private/` e só números agregados de comparação foram usados.
2. **Painel composto com zonas** em vez de 8 tipos fixos: cada zona reaproveita os construtores de IR da F06A (nada é
   recalculado) e tem indicadores/gráfico editáveis, validados pelo catálogo.
3. **Retrocompatibilidade provada:** hashes de `neutral-demo@1` e dos templates F06A inalterados (fixados em teste);
   regressão visual neutro/alternativo idêntica.
4. **Contornos e opacidade** extraídos da geometria da referência (não desenhados à mão): capa 8,9% → 0,1% de diferença.
5. **Sem semântica inventada:** pílula de variação neutra (contrato não diz se subir é bom); rosca sem percentuais
   derivados; ausente ≠ zero (estado e motivo explícitos; `required_metrics` vira bloqueio).
6. Severidade × cor **inferida** da paleta de status — precisa de confirmação do PO.

## 4. Fidelidade visual alcançada (comparação local por slide, conteúdo mascarado dos dois lados)
| Slides | Dif. Δ>0,08 (pixels não mascarados) |
|---|---|
| capa | 0,1% |
| seções (4) | 0,3% |
| painéis (8) | 0,4% – 1,8% |
| matrizes (2) | 0,6% |
| encerramento | 0,7% |
Geometria: 41/67 pares não textuais coincidem em ≤2 px, 44 em ≤5 px, 51 em ≤15 px (o restante é área de foto que
excede o canvas, posição das roscas, alturas variáveis de linhas/gráficos — ver `docs/AFRIKA_TEMPLATE.md` §5–6).
**Isto mede a estrutura sob máscara, não o conteúdo nem a tipografia.**

## 5. Testes
| Verificação | Resultado |
|---|---|
| `python -m pytest -q` (local) | **PASS 498** (479 + 19: Afrika 17, inspeção PPTX 2) |
| E2E Chromium `npm run test:e2e` | **PASS 31 + 1 SKIPPED** (afrika +1; `reference.spec.ts` pulado sem o arquivo — esperado) em **3 rodadas completas** |
| Regressão visual (win32) | **54/54 PASS** (neutro 19 + alternativo 19 idênticos às referências anteriores + afrika 16) |
| Comparação com a referência (local) | executada; números na seção 4 (`output/reference-compare/`, não versionado) |
| Motor visual `npm run test:visual-unit` | **PASS 12/12** (+ máscara) |
| build; `npm audit`; `pip check` | OK; 0 vulnerabilidades; OK |
| gitleaks (staged) | __GITLEAKS__ |
| `check_repo`; `check_env_example` | __CHECKREPO__; SEGURO |
| migrations CLI em banco novo | OK (`0006_themes`; seed cria 4 templates) |
| SHA-256 do PPTX de referência após tudo | **inalterado** |
| CI GitHub | __CI_TABLE__ |
| `tests_live` | NOT_RUN (fase sem chamadas reais) |

## 6. Riscos e limitações
1. Imagens de marca (fotos, ilustração, logos, ícones e texto do master) **não reproduzidas** — viram áreas
   reservadas; exigem ativos aprovados.
2. Tema `afrika@1` é **provisório** até homologação; severidade × cor e cor de variação dependem do PO.
3. Fontes da referência não estavam instaladas na máquina que renderizou o PowerPoint; a comparação mascara texto, então
   tipografia não está medida.
4. Referências Linux do caso `afrika` foram criadas pelo CI (bootstrap temporário, removido) e revisadas visualmente
   (dados sintéticos); mudança da imagem do runner pode exigir nova referência.
5. `licenses.usage` (unidade `findings`) segue pendente (herdado; não usado no template Afrika).

## 7. Pendências para o PO
- Homologar `afrika@1` (identidade, severidade × cor), aprovar ativos de marca, decidir cor de variação por direção.
- Confirmar se a sequência de 16 slots e os indicadores sugeridos nas zonas atendem ao relatório padrão.

**Prompt sugerido para a próxima fase (não executado):** "F07 — Exportação PPTX/PDF a partir da visualização
aprovada (IR + tema): spike de editabilidade com `python-pptx` (textos e tabelas editáveis, gráficos nativos a partir da
IR com lacuna = ponto vazio, formas com contorno via `custGeom`, zonas como grupos), export do template
`afrika-modelo@1` e dos demonstrativos, comparação visual PPTX exportado × HTML com o motor existente e PDF com
fidelidade medida; sem IA (F08) e sem coleta real."

---

## Versão compacta para o PO
F06B concluída (__COMMITS_SHORT__; __CI_SHORT__). Template `afrika-modelo@1` (16 slots: capa, 4 seções, 8 painéis
compostos com zonas editáveis, 2 matrizes, encerramento) + tema `afrika@1` provisório, derivados só da estrutura do
PowerPoint local (sem conteúdo dele no repo). Genérico para qualquer cliente/subcliente, indicadores e nº de slides
configuráveis, dados só de revisões aprovadas. Fidelidade estrutural medida por slide: 0,1%–1,8% de diferença (Δ>0,08,
conteúdo mascarado). Testes: pytest 498, E2E 31 (×3), visual 54/54, unit 12, build/audit/pip/gitleaks OK. Pendências:
ativos de marca, homologação da identidade e da cor por severidade.
