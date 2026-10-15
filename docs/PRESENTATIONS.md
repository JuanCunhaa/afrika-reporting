# Motor de apresentações (F06A)

Código: `backend/app/presentations/` (`catalog.py`, `themes.py`, `document.py`, `templates.py`, `charts.py`, `view.py`,
`service.py`), API `backend/app/api_presentations.py`, migration `0005_presentations`; frontend
`frontend/src/presentation/SlideView.tsx` (renderizador HTML), telas **Apresentações** (`#/presentations`) e editor
(`#/presentations/{id}`). Contratos detalhados: `docs/PRESENTATION_CONTRACTS.md`.

> **Tema demonstrativo neutro — PROVISÓRIO.** A identidade visual oficial da Afrika não foi escolhida; nenhum logo,
> marca ou template proprietário foi incorporado. Os três templates embutidos (`demo-executivo`, `demo-tecnico`,
> `demo-minimo`) são sintéticos e não são o template oficial.

## Camadas (separadas)
| Camada | Onde | Responsabilidade |
|---|---|---|
| Dados e proveniência | F05 (`snapshots`) + `view.load_entries/resolve` | revisões **aprovadas** fixadas; valor, estado, origem, fonte técnica, hashes |
| Modelo de apresentação | `document.py` (template, documento) | slides ordenados, tipo, layout, campos editoriais, `metric_id`, opções — **sem números** |
| Tema | `themes.py` | tokens de cor/fonte/tamanho, canvas 1280×720 (16:9), aviso de provisório |
| Layout | `catalog.py` (layouts por tipo) + CSS do renderizador | posição dos blocos por layout |
| IR de gráficos | `charts.py` | barras, linhas, severidade, ranking, comparação, tabela, KPI — independente do renderizador |
| Renderização HTML | `SlideView.tsx` | desenha a IR (SVG/HTML nativos, texto selecionável) |
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

## Preparação para PPTX/PDF (F07)
- A IR já traz tudo que um exportador precisa sem reler snapshots: categorias, séries, `y` bruto, rótulo formatado,
  tokens de cor, eixos, unidade, legenda, lacunas e referências de dados.
- Mapeamento previsto (a validar por spike na F07): KPI/tabela/ranking/comparação ⇒ tabelas e caixas de texto nativas;
  barras/linhas/severidade ⇒ gráficos nativos (`python-pptx` chart data a partir da IR; lacuna = ponto vazio, nunca
  zero); textos ⇒ placeholders editáveis; tema ⇒ cores/fontes do master. Sem converter slides em imagem.
- PDF: impressão do HTML em ambiente controlado ou derivado do PPTX — escolha e fidelidade **NOT_VERIFIED**.

## Limitações (F06A)
- Tema e templates demonstrativos; fidelidade a template oficial (diff visual por slide) depende do arquivo aprovado.
- Sem exportação (F07); sem autenticação (autor/operador declarados); SQLite local.
- Valores de estrutura livre (distribuições/rankings manuais) só viram gráfico com adaptador explícito por indicador;
  estrutura não reconhecida ⇒ "indisponível" (nada é presumido).
- Janela fixada de 12 meses: séries maiores exigirão nova fixação/contrato.
