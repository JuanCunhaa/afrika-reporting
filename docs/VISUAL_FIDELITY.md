# Fidelidade visual — template Afrika × PowerPoint de referência (F06B + F06C)

Status: **medida, não prometida.** Os números abaixo são MEDIÇÕES locais de dois métodos complementares; nenhum deles,
isolado ou somado, prova "fidelidade completa". A homologação final depende de ativos oficiais e de revisão humana com
o conteúdo real (fora do repositório).

## 1. Regras de privacidade (inalteradas desde a F06B)
- O PowerPoint de referência existe **só** em `references/` (ignorado, nunca rastreado; SHA-256 conferido). A inspeção é
  `strict` (geometria, cores, fontes declaradas, contagens de caracteres/parágrafos/linhas — **nenhum** texto, número,
  nome ou imagem). Render local em `private/reference-render/`; saídas em `output/reference-compare/` (ignorados).
- **Nenhuma** renderização da referência nem PNG de diferença foi aberto por assistente de IA ou enviado a serviço
  externo: a análise da F06C usou apenas os números agregados de `integral.json`/`report.json`.
- O repositório recebe só a metodologia e números agregados (este documento).

## 2. Métodos
| Método | Spec (local; pulada no CI) | O que compara | O que NÃO prova |
|---|---|---|---|
| A. Estrutural mascarado (F06B) | `frontend/e2e/reference.spec.ts` | `afrika-modelo@1` com dados sintéticos; texto/gráfico/tabela/imagem **mascarados dos dois lados** → fundos, faixas, cartões, formas, filetes | conteúdo, tipografia, gráficos, overflow |
| B. Integral por categoria (F06C) | `frontend/e2e/reference-integral.spec.ts` | `afrika-modelo@2` com **conteúdo sintético equivalente**, **sem máscara**; métricas separadas: geometria, tipografia, cores, gráficos, distribuição de conteúdo, overflow/cortes; diferença atribuída por classe de área | identidade de glifos (texto real × sintético), ativos oficiais (ausentes), tipografia renderizada (fontes não instaladas no PowerPoint local) |

**Conteúdo sintético equivalente** (método B): para cada slide *i* (slot *i* do template), os campos editoriais recebem
texto sintético com o **mesmo nº de caracteres** das formas mapeadas da referência (título, subtítulo, legenda, título de
seção, corpo do painel, grupos do encerramento, cabeçalhos/rótulos/células da matriz) e listas com o **mesmo nº de
tópicos** (parágrafos; quando os tópicos da referência são tabelas, nº de linhas com comprimento **estimado** de 60 —
registrado como estimativa). Só contagens estruturais do relatório `strict` são usadas. Números (KPIs, séries) seguem
sintéticos — distribuição de dígitos **não** foi igualada.

Classes de área (prioridade): **ativos de marca** (imagens da referência > 60 px, elementos do master nos slides de
conteúdo — logo, ícones, textos laterais/rodapé — e encaixes de ativo do tema) > **gráficos** (molduras de gráfico da
referência + desenhos de gráfico do HTML) > **texto** (formas com texto + elementos de texto do HTML) > **estrutura**
(resto). Limiar de cor YIQ Δ>0,08; antisserrilhado somado.

## 3. Resultados

### 3.1 Método A (estrutural mascarado) — reexecutado na F06C: números idênticos aos da F06B
Capa 0,1% · seções 0,3% · painéis 0,4–1,8% · matrizes 0,6% · encerramento 0,7% (Δ>0,08 sobre pixels não mascarados). A
estrutura de `afrika-modelo@1` não mudou (hash fixado) e o método A continua mostrando os mesmos valores.

### 3.2 Método B (integral, `afrika-modelo@2`, conteúdo equivalente) — 2026-10-16, Windows/Chromium 156
| Slide | Tipo | Dif. total | Ativos (área / dif. na área / % da dif. total) | Gráficos | Texto | Estrutura |
|---|---|---|---|---|---|---|
| 1 | capa | 5,6% | 49% / 2,6% / 22,5% | — | 17,5% / 23% / 72,6% | 33,5% / 0,8% / 4,9% |
| 2–4, 13 | seção | 2,6–4,6% | 45% / 0,1% / 1–1,9% | — | 11,9% / 20,5–36,8% / 92,8–96% | 43,1% / 0,3% / 3,1–5,3% |
| 5 | painel KPIs | 12,3% | 1,6% / 19,4% / 2,6% | — | 68,4% / 17,4% / 96,6% | 30% / 0,3% / 0,8% |
| 6 | painel gráficos | 12,6% | 2% / 20,6% / 3,2% | 22,8% / 29,9% / 54,2% | 34,4% / 14,9% / 40,8% | 40,9% / 0,5% / 1,8% |
| 7 | painel grupos | 12,3% | 1,6% / 19,5% / 2,6% | 15,5% / 31,9% / 40,4% | 48,4% / 14,4% / 56,7% | 34,5% / 0,1% / 0,3% |
| 8–9 | painéis severidades | 7,3–8,4% | 1,6% / 19,5% / 3,8–4,4% | — | 60% / 11,4–13% / 92,9–93,6% | 38,3% / 0,4–0,7% / 2–3,4% |
| 10–11 | ranking + gráfico | 12,8–13,5% | 1,6% / 19,4% / 2,4–2,5% | 12,7% / 24,8–28,7% / 24,6–27% | 64,6% / 14,5–14,8% / 70,6–72,9% | 21% / 0,1% / 0,1% |
| 12 | destaque + tabela | 9,2% | 1,6% / 19,4% / 3,5% | — | 59% / 14,9% / 96,4% | 39,3% / 0% / 0,1% |
| 14–15 | matriz | 5,5–7,9% | 2% / 26,3% / 6,7–9,6% | — | 70,1–70,7% / 7,1–10,4% / 90–93% | 27,3–27,9% / 0,1% / 0,2–0,3% |
| 16 | encerramento | 7% | 37,3% / 3,5% / 18,9% | — | 22,9% / 23,4% / 76,6% | 39,8% / 0,8% / 4,5% |

Leitura: a **estrutura** difere em ≤0,8% da própria área; a diferença integral concentra-se no **texto** (glifos reais ×
sintéticos — esperado por definição) e, onde há gráfico, nos **gráficos** (valores sintéticos; mesmo tipo de gráfico). Nos
slides de conteúdo, ~19–26% da área de ativos difere (logo, ícones e textos do master ausentes); na capa/seções/
encerramento a área de ativos é grande, mas a foto/ilustração da referência difere pouco do bloco de cor neutro.

### 3.3 Por categoria
| Categoria | Resultado | Observação |
|---|---|---|
| Geometria | 93 pares: **55 ok** (≤5 px), **11 aprox.** (≤15 px), **27 divergentes** | todos classificados na §4 |
| Tipografia (declarada no PPTX × computada no HTML) | **24/24 iguais** (família, tamanho Δ0 px, peso) | após 2 correções no `afrika@2` (§5); o render do PowerPoint usou fontes substitutas, por isso a tipografia é comparada pelo declarado |
| Cores | **33/39 iguais** (cor predominante das formas; cor declarada dos textos) | as 6 diferenças são o tom do título nos slides 7–12 (§4) |
| Gráficos | **16/16 com os mesmos tipos** (barras, linhas/combinado, rosca) | nº de pontos/séries difere por configuração (§4) |
| Distribuição de conteúdo | caracteres iguais por construção onde há contagem; "tinta" de listas: ref 7–13% × HTML 1–4% | listas da referência são tabelas com ícones (comprimento não exposto; ícones = ativos) |
| Overflow/cortes | **0** achados no HTML com conteúdo equivalente; referência tem `autofit` (encolher texto) em capa, seções, encerramento e no painel de gráficos | o HTML não encolhe texto: quebra linha dentro de zonas adaptativas |

## 4. Classificação das diferenças
| # | Slide(s) | Diferença medida | Classe | Tratamento |
|---|---|---|---|---|
| 1 | 1, 2–4, 13, 16 | área de foto/ilustração: Δcentro 17–138 px, Δtamanho 35–275 px | **ativo oficial ausente** + caixa da imagem da referência **excede o canvas** (recorte em 1920 px) | encaixes `foto-capa`, `foto-secao`, `ilustracao-encerramento` (§6); fallback neutro = forma do tema |
| 2 | 5–12, 14–15 | 19–26% da área de logo/ícones/textos do master difere | **ativo oficial ausente** | encaixes `logo-conteudo`, `icones-laterais`; textos do master não são reproduzidos (conteúdo proprietário) |
| 3 | 1 | sobretítulo/título/competência: Δcentro 45–214 px | **layout — candidato a ajuste** | coluna de texto da capa = 734 px (padding direito 1080) × caixas da referência 960–1162 px com `autofit`; títulos longos quebram antes no HTML. Decidir com o conteúdo oficial (não alterado sem ver o real) |
| 4 | 5–7 | título: Δx ≈ 40 px (slide 5 também Δy 40) | **inconsistência da referência** | na referência a caixa do título desses 3 slides está deslocada, mas o filete continua centralizado; o tema mantém título e filete centralizados em todos |
| 5 | 7–12 | cor do título `#2B0B43`/`#280F44` × `#4A1D6E` | **inconsistência da referência** | a referência usa 3 tons; slides 5–6 usam `#4A1D6E`, adotado pelo tema |
| 6 | 6 | roscas Δ43–103 px; gráfico/cartão Δ13–26 px | layout conhecido (F06B §6.4) | molduras da referência se sobrepõem; ajuste fino possível |
| 7 | 7 | gráfico Δtamanho 17 px | layout — ajuste fino | — |
| 8 | 8 | lista Δcentro 65 px | layout — candidato a ajuste fino | na referência a lista é tabela com ícones; zona sem moldura no HTML |
| 9 | 9 | comparação Δ131–173 px | layout conhecido (F06B §6.5) | a referência desloca o cartão só neste slide; o template reutiliza o layout do slide 8 |
| 10 | 10–11 | gráfico Δaltura 75 px; legenda Δ33 px (segue o gráfico) | layout — candidato a ajuste fino | caixa da zona do gráfico |
| 11 | 14 | rótulo/célula da matriz Δ48/100 px | layout conhecido (F06B §6.6) | linhas de altura igual no HTML; variáveis na referência |
| 12 | 16 | título/grupos Δ62–78 px | caixa de texto × caixa do conteúdo | a âncora do texto não é exposta pelo relatório `strict`; conferir na homologação visual |
| 13 | 6, 7, 11 | gráficos: 7 pontos × 6; 2 séries × 1; rosca 4 categorias × 7; CWE 5 × 7 | **configuração/contrato** | janela de meses do contrato é 6 ou 12; rosca mostra as 7 severidades Veracode (agrupar por nível = soma derivada, não permitida sem decisão do PO); séries/top N editáveis por zona |
| 14 | 15 | célula da matriz equivalente não cabe | **limite de contrato** | cada linha da matriz é um item ≤ 400 caracteres ("a \| b \| c \| d"); a referência tem célula com 167 caracteres (3 parágrafos) — limitada a 129 na medição. Decisão do PO/F07 |
| 15 | todos | texto (glifos) | **conteúdo esperado** | real × sintético |

**Defeitos de layout encontrados e corrigidos na F06C** (só no `afrika@2`; `afrika@1` intacto):
1. subtítulo dos painéis 10–12: declarado na referência como Montserrat Black em roxo de marca; o HTML usava Poppins
   regular cinza → tokens `components.subtitle_font/weight/color` (tipografia 24/24 e cor do subtítulo iguais);
2. rótulo de linha da matriz: 22 pt na referência × 14 pt no HTML (Δ10,6 px) → `components.matrix_label_size`;
3. efeito colateral da correção 1 (Montserrat tem entrelinha menor): descendentes do subtítulo encostavam no filete →
   `components.subtitle_line_height = 1,5` (mesma caixa da v1; ~9 px de respiro, como na referência).

## 5. Overflow e fontes entre plataformas
- `frontend/visual/overflow.ts` mede no DOM real: corte (`clipped-x/y`), texto mais longo que a própria caixa na direção
  inline (`spill-x`), reticências, fora da zona, fora do slide. A regressão visual falha com qualquer achado (exceto
  reticências, registradas) — roda no Windows (local) e no Linux (CI). Resultado: **0** achados nos 62 slides (4 casos)
  e **0** com o conteúdo equivalente ao real. O E2E `f06c.spec.ts` prova que o detector encontra estouros injetados.
- Casos com fontes empacotadas (`afrika`, `afrika-v2`): a regressão falha se o Chromium usar qualquer fonte de
  plataforma além de Montserrat/Poppins/Be Vietnam Pro (OFL) — hoje 0 fontes de reserva, Windows e Linux.

## 6. Ativos de marca (estado)
Nenhum ativo oficial foi fornecido/autorizado: os encaixes do `afrika@2` (`logo-capa`, `foto-capa`, `foto-secao`,
`ilustracao-encerramento`, `logo-conteudo`, `icones-laterais`) ficam vazios com fallback neutro. Mecanismo:
`docs/THEMES.md` → "Encaixes de ativos locais". O E2E e a regressão visual usam imagens **sintéticas** geradas em tempo
de teste numa pasta descartável.

## 7. Limitações
1. A renderização da referência foi feita com fontes substitutas (Montserrat/Poppins/Be Vietnam Pro não instaladas na
   máquina do PowerPoint): tipografia de pixel não é comparável; a de contrato (declarada) é.
2. Âncora vertical do texto e recuos internos das caixas do PPTX não são expostos no modo `strict`: Δcentro de caixas de
   texto mede caixa, não necessariamente o texto visível.
3. Listas/tabelas da referência: contagem de caracteres não exposta; equivalência estimada.
4. Números sintéticos não igualados (dígitos), portanto "tinta" de KPIs/gráficos não é comparável.
5. Cor predominante por área quantizada (16 níveis) — tolera antisserrilhado, não mede gradientes.
6. Todo resultado é por plataforma (Windows local); o método B não roda no CI (arquivo não existe lá).

## 8. Reproduzir (local)
```
cd frontend
AFRIKA_REFERENCE_RENDER=<repo>/private/reference-render AFRIKA_REFERENCE_REPORT=<repo>/output/pptx-inspection/referencia/report.json \
  npx playwright test e2e/reference.spec.ts e2e/reference-integral.spec.ts
```
Saída: `output/reference-compare/report.{md,json}` (A) e `integral.{md,json}` (B) — só números; `diffs/`,
`integral-diffs/`, `html/`, `integral-html/` são PNGs locais (os de diferença contêm a referência: não publicar).
