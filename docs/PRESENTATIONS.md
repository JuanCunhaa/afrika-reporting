# Motor de apresentações (F06A + F06B.1 + F06B)

Código: `backend/app/presentations/` (`catalog.py`, `themes.py`, `document.py`, `templates.py`, `charts.py`, `view.py`,
`service.py`), API `backend/app/api_presentations.py`, migration `0005_presentations`; frontend
`frontend/src/presentation/SlideView.tsx` (renderizador HTML), telas **Apresentações** (`#/presentations`) e editor
(`#/presentations/{id}`). Contratos detalhados: `docs/PRESENTATION_CONTRACTS.md`.

> **Temas PROVISÓRIOS.** Os três templates demonstrativos (`demo-executivo`, `demo-tecnico`, `demo-minimo`) usam o
> tema neutro. Desde a F06B há também o template `afrika-modelo@1` com o tema `afrika@1`, reproduzido
> estruturalmente do PowerPoint de referência local (sem logos, fotos ou conteúdo dele) e ainda **não homologado**
> pelo PO — ver `docs/AFRIKA_TEMPLATE.md`.

## Camadas (separadas)
| Camada | Onde | Responsabilidade |
|---|---|---|
| Dados e proveniência | F05 (`snapshots`) + `view.load_entries/resolve` | revisões **aprovadas** fixadas; valor, estado, origem, fonte técnica, hashes |
| Modelo de apresentação | `document.py` (template, documento) | slides ordenados, tipo, layout, campos editoriais, `metric_id`, opções — **sem números** |
| Tema | `themes.py` + `assets.py` (F06B.1) | tema versionado com tokens COMPLETOS (cores, fontes, tamanhos, espaçamentos, regiões, cabeçalho/rodapé, capa, fundos, imagens, gráficos, canvas) — ver `docs/THEMES.md` |
| Layout | `catalog.py` (layouts por tipo) + CSS do renderizador | posição dos blocos por layout |
| IR de gráficos | `charts.py` | barras, linhas, severidade, ranking, comparação, tabela, KPI — independente do renderizador |
| Renderização HTML | `SlideView.tsx` + `theme.ts` | desenha a IR (SVG/HTML nativos, texto selecionável); só lê tokens do tema; `#/render/{id}` = captura determinística em escala 1 |
| Regressão visual | `frontend/visual/` (F06B.1) | captura + manifesto + comparação por imagem com tolerância medida — ver `docs/VISUAL_REGRESSION.md` |
| Painel composto (F06B) | `catalog.DASHBOARD_LAYOUTS` + `view._zone_data` + `SlideView` (`Dashboard`) | zonas tipadas com indicadores e gráficos próprios, posicionadas por tokens do tema |
| Exportação PPTX/PDF | **F07 (não implementada)** | consumirá a mesma visualização (IR + tema), gerando objetos nativos editáveis |

## Fluxo
1. Templates: instalar os demonstrativos (`POST /api/presentation-templates/builtin`, idempotente; também em
   `python -m app.cli seed-demo`) ou criar template próprio (`POST /api/presentation-templates`). Mudança = nova
   versão (`POST …/{key}/versions`, com `expected_version`); versões são imutáveis (gatilho).
2. Escolha por dono: `PUT /api/template-selection/{client|subclient}/{id}` (histórico append-only). Subcliente sem
   escolha herda a do cliente; cliente sem subclientes funciona igual.
3. Criação: `POST /api/presentations {competence_id[, revision][, template_key, template_version][, title], operator}`.
   Exige revisão **APROVADA** (padrão: a oficial); rascunho/em revisão ⇒ 409. Fixa as fontes: revisão principal +
   aprovações vigentes dos 11 meses anteriores (para séries de até 12 meses), cada uma com `content_hash`.
4. Edição: o editor altera só o documento editorial (título, textos, tópicos, legendas, observações, notas,
   apresentadores, layout, opções, inclusão/remoção/reordenação de slides e escolha de indicadores compatíveis).
   Pré-visualização ao vivo: `POST …/preview` (valida e monta a IR, **nada é gravado**). Salvar:
   `PUT …/document {document, expected_revision, operator, summary}` ⇒ nova revisão append-only; conflito ⇒ 409.
5. Fontes: aprovação nova da competência (ou de meses do histórico) gera aviso; a troca é explícita
   (`POST …/rebind`) e vira nova revisão. Revisões anteriores continuam consultáveis (`GET …/view?revision=n`).
6. Integridade: `GET …/integrity` recalcula hash do documento, das fontes, cadeia de revisões, hash do template e,
   para cada fonte fixada, `content_hash` da aprovação e `row_hash` dos snapshots.

## Regras de dados (inegociáveis)
- Fonte única: revisões aprovadas fixadas. Nenhuma consulta à Veracode; nada é recalculado, somado, interpolado.
- Zero ≠ ausente: competência sem aprovação = **lacuna**; indicador ausente = **ausente**; contrato fora das
  versões aceitas = **incompatível** (valor não exibido). Valor manual é identificado ("Manual").
- O editor não tem caminho de escrita para `metric_snapshots`, `approvals` ou execuções (testado: `row_hash`,
  aprovação e integridade F05 iguais antes/depois). Correção de indicador = nova revisão em **Competências** (F05),
  aprovação e "Atualizar fontes aprovadas".
- Pendências por slide: `blocker` quando indicador de slot com `required_metrics` não tem valor aprovado
  (`ready=false` para a exportação futura); `warning`/`info` para ausências, incompatibilidade, lacunas e manuais.

## Persistência (migration `0005_presentations`)
| Tabela | Papel | Proteção |
|---|---|---|
| `presentation_templates` | versão de template (chave, versão, tema, definição JSON canônica, `definition_hash`, origem BUILTIN/CUSTOM) | append-only (sem UPDATE/DELETE) |
| `owner_template_selections` | escolha de template por cliente/subcliente | append-only |
| `presentations` | identidade (dono, competência, template) + título e ponteiro `current_revision` | identidade imutável; sem DELETE |
| `presentation_revisions` | documento + fontes fixadas + hashes encadeados + resumo/autor declarado | append-only; INSERT só com revisão de competência APROVADA e aprovação dessa revisão |

Downgrade da 0005 é recusado se houver apresentações, salvo `AFRIKA_ALLOW_DESTRUCTIVE_DOWNGRADE=1`. Eventos de
auditoria (cadeia F05): `template.version_created`, `template.selected`, `presentation.created`, `presentation.saved`,
`presentation.sources_rebound`.

## Endpoints (loopback, sem autenticação; operador declarado)
`GET /api/presentation-catalog` · `GET/POST /api/presentation-templates` · `POST /api/presentation-templates/builtin` ·
`GET /api/presentation-templates/{key}/versions/{v}` · `POST /api/presentation-templates/{key}/versions` ·
`GET/PUT /api/template-selection/{kind}/{owner_id}` · `GET/POST /api/presentations` · `GET /api/presentations/{pid}` ·
`GET …/revisions/{n}` · `PUT …/document` · `POST …/preview` · `POST …/rebind` · `GET …/view[?revision=n]` ·
`GET …/integrity`.

## Interface
- **Apresentações**: aviso de tema provisório; dono (cliente/subcliente); escolha do template; criação só a partir de
  competências aprovadas (as sem aprovação são listadas como indisponíveis); lista de apresentações.
- **Editor**: lista de slides (↑ ↓ ✕, obrigatórios não removíveis, adicionar por tipo); canvas 16:9 escalável com
  navegação (botões, setas, contador) e modo apresentação (tela cheia, Esc); painel de propriedades por tipo (campos
  editáveis, layout, opções, indicadores compatíveis); documento (título, apresentadores, operador, resumo); pendências;
  dados de origem (valor aprovado, estado, fonte técnica, homologação, justificativa manual, revisões fixadas);
  histórico de revisões (visualização somente leitura); verificação de integridade.

## Editor — confiabilidade (F06B.1)
- O estado salvo vem da resposta do `PUT` (fonte da verdade). A releitura seguinte só atualiza metadados e visualização:
  **edições feitas durante o salvamento não são sobrescritas** (defeito reproduzido e corrigido) e uma falha na
  releitura após HTTP 200 é informada como "a revisão N foi gravada, mas a releitura falhou" (sem nova tentativa
  automática, sem "alterações não salvas" falso).
- Gerações de resposta: toda edição, recarga ou salvamento invalida pré-visualizações em voo; resposta antiga nunca
  substitui a tela (inclusive após "Descartar" — defeito reproduzido e corrigido — ou ao voltar manualmente ao texto
  salvo). Duplo clique em "Salvar" gera um único `PUT` (guarda síncrona).
- Concorrência entre abas: `expected_revision` ⇒ 409 na segunda, edição preservada para o operador decidir.
- Testes: `frontend/e2e/editor-reliability.spec.ts` (rede interceptada: atraso/falha determinísticos) e
  `backend/tests/test_editor_reliability.py` (leitura após escrita sob leitores concorrentes, revisão vencida,
  reinício).

## Preparação para PPTX/PDF (F07)
- A IR já traz tudo que um exportador precisa sem reler snapshots: categorias, séries, `y` bruto, rótulo formatado,
  tokens de cor, eixos, unidade, legenda, lacunas e referências de dados.
- Mapeamento previsto (a validar por spike na F07): KPI/tabela/ranking/comparação ⇒ tabelas e caixas de texto nativas;
  barras/linhas/severidade ⇒ gráficos nativos (`python-pptx` chart data a partir da IR; lacuna = ponto vazio, nunca
  zero); textos ⇒ placeholders editáveis; tema ⇒ cores/fontes do master. Sem converter slides em imagem.
- PDF: impressão do HTML em ambiente controlado ou derivado do PPTX — escolha e fidelidade **NOT_VERIFIED**.

### Editabilidade prevista por elemento (F06B.1; a validar no spike da F07)
| Elemento | No PPTX futuro | Observação |
|---|---|---|
| Títulos, subtítulos, textos, tópicos, legendas, notas | caixa de texto/placeholder **editável** | fonte/tamanho/cor do tema; `export_family` quando a fonte do tema não existir no PowerPoint |
| KPIs, comparação, tabela de indicadores, ranking | tabela/caixas de texto **editáveis** | valores = rótulos já formatados da IR; proveniência no texto alternativo (`data-provenance`) |
| Barras, linhas, série histórica | gráfico **nativo** editável (dados da IR; lacuna = ponto vazio) | sem planilha externa; rótulos de mês rarefeitos são só HTML |
| Severidade | gráfico de barras horizontais nativo ou tabela | textura da "desconhecida" depende de padrão de preenchimento |
| Logos, imagens de fundo | imagem (ativo local) | não editável como vetor; SVG precisa de PNG de reserva |
| Faixas, barra de destaque, separadores | formas nativas | |
| Formas com contorno (`components.shapes[].path`, F06B) | forma livre nativa (`custGeom`) | painéis curvos da capa/encerramento Afrika |
| Zonas de painel (F06B) | grupo de formas por zona (caixa absoluta do tema) | cada zona reaproveita o mapeamento do seu componente |
| Lacuna (tracejado), aviso "indisponível" | forma com contorno tracejado + texto | nunca zero |
| Rótulos de eixo calculados (escala) | gerados pelo gráfico nativo | escala pode diferir do HTML (geometria, não dado) |
Não reproduzíveis como objeto editável: efeitos CSS sem equivalente (ex.: textura repetida exata), `object-fit: cover`
de imagens (vira recorte), rarefação de rótulos (o PowerPoint decide).

## Limitações (F06A; atualizadas na F06B)
- F06B: template Afrika reproduzido e comparado por slide com a referência local (estrutura sob máscara; ver
  `docs/AFRIKA_TEMPLATE.md`); identidade, ativos de marca e mapeamento de severidade dependem de homologação do PO.
- Sem exportação (F07); sem autenticação (autor/operador declarados); SQLite local.
- Valores de estrutura livre (distribuições/rankings manuais) só viram gráfico com adaptador explícito por indicador;
  estrutura não reconhecida ⇒ "indisponível" (nada é presumido).
- Janela fixada de 12 meses: séries maiores exigirão nova fixação/contrato.
