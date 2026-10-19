# Contratos de templates, documentos e gráficos (F06A + F06B.1 + F06B + F06C + F07)

Fonte de verdade do código: `backend/app/presentations/document.py` (esquemas Pydantic, `extra='forbid'`),
`catalog.py` (tipos de slide) e `charts.py` (IR). Catálogo em tempo de execução: `GET /api/presentation-catalog`.

## Template (versão imutável)
```jsonc
{
  "name": "Executivo mensal (demonstrativo)",
  "description": "…",
  "theme": {"id": "neutral-demo", "version": 1},
  "metric_contracts": {"apps.total": [1], "sast.policy.open.by_severity": [1]},  // versões de contrato aceitas
  "slides": [
    {"slot_id": "capa", "type": "cover", "layout": null, "required": true, "required_metrics": false,
     "fields": {"title": "…", "subtitle": "…"}, "metrics": [], "options": {"show_presenters": true}},
    {"slot_id": "kpis", "type": "kpis", "required_metrics": true, "fields": {"title": "Indicadores principais"},
     "metrics": ["apps.total", "sast.policy.open.by_severity"]}
  ]
}
```
- Identificação: `template_key` (`^[a-z0-9][a-z0-9-]*$`) + `version` (inteiro ≥ 1) + `definition_hash` (SHA-256 do JSON
  canônico). Origem `BUILTIN` (demonstrativo, sem novas versões via API) ou `CUSTOM`.
- **Sem números**: não existe campo de valor; qualquer chave extra (`value`, `number`…) ⇒ 422.
- Obrigatoriedade: `required` (slot não pode ser removido do documento nem mudar de tipo); `required_metrics` (os
  indicadores do slot não podem ser removidos e, sem valor aprovado, viram `blocker`). Campos obrigatórios por tipo
  (ex.: `title`) não podem ficar vazios no documento.
- Compatibilidade: todo indicador usado precisa estar em `metric_contracts`; snapshot com `contract_version` fora da
  lista ⇒ `INCOMPATIBLE` (valor não exibido). Indicador incluído pelo editor fora do template aceita a versão vigente
  do catálogo.
- Validação: tema existente, `slot_id` único, layout do tipo, campos editáveis do tipo, opções aplicáveis,
  quantidade de indicadores, indicador existente e compatível com o tipo de slide.

## Tema (F06B.1)
`theme: {id, version}` aponta para um tema embutido (`neutral-demo@1`, provisório) ou próprio (tabela
`presentation_themes`, append-only). O tema existe quando o template é criado (senão 422 `unknown_theme`). Formato completo
e validações: `docs/THEMES.md`. A visualização (`GET …/view`) traz `theme` completo (+ `canvas.aspect_ratio` derivado)
e o aviso `theme_asset_missing` se um ativo local faltar. `GET /api/presentation-catalog` lista **resumos** de temas
(`id, version, name, provisional, origin, versions, definition_hash`) — mudança da F06B.1 (antes: definição do tema
embutido).

### Semântica de cores e encaixes de ativos (F06C)
- `theme.semantics.severity` (opcional): `levels {critical, high, medium, low, informational} → token`, `mapping
  {VERY_HIGH…INFORMATIONAL} → nível`, `unknown → token`. Com ela, os tokens `severity.<CHAVE>` usados pela IR são
  **derivados** (não podem ser declarados em `colors` — fonte única). `theme.semantics.variation` (opcional):
  `improvement`, `worsening`, `neutral` (tokens) e `tint_opacity`. Sem semântica, o visual F06B é mantido.
- Saída pública do tema: `colors` = **paleta efetiva** (definição + derivados, incluindo `variation.*`, que sem
  semântica valem `text.secondary`); `declared_colors` = o que a definição declara. O hash é o da definição.
- `theme.asset_slots[]` (opcional): `{name, box, slides, fit, alt}` — encaixes de ativos autorizados carregados da pasta
  local (`docs/THEMES.md`). A visualização traz `brand_assets {encaixe: {status: available|missing|invalid, media_type,
  sha256, url}}`; ausente = fallback neutro (aviso `info` `brand_asset_missing`), inválido = ignorado (`warning`
  `brand_asset_invalid`). Nunca bloqueia.
- Grupos/campos novos saem do JSON canônico quando no padrão: hashes de `neutral-demo@1`, `afrika@1` e de todos os
  templates anteriores **inalterados** (fixados em `test_f06c_homologation.py`).

## Tipos de slide (componentes disponíveis — nenhum é obrigatório por si)
| Tipo | Layouts | Indicadores | Tipos de valor | IR |
|---|---|---|---|---|
| `cover` Capa | cover | 0 | — | dono, competência, período (+ `period_label` `dd/mm/aaaa a dd/mm/aaaa`, F06B.1), apresentadores |
| `executive_summary` Sumário | text-with-highlights, text-only | 0–4 | count, decimal, percentage, by_severity | kpi |
| `kpis` KPIs | kpi-grid, kpi-band (F06B) | 1–6 | idem | kpi |
| `month_comparison` Mês × anterior | comparison-table, comparison-cards | 1–6 | idem | comparison |
| `bar_chart` Barras | chart-full, chart-with-text | 1 | `breakdown`: breakdown, ranking, by_severity; `history`: count, decimal, percentage, by_severity | bar |
| `line_chart` Linhas | chart-full, chart-with-text | 1–4 | count, decimal, percentage, by_severity | line |
| `severity_distribution` Severidade | chart-full, chart-with-text, severity-cards, donut (F06B) | 1 | by_severity | severity |
| `top10_ranking` Top 10 | ranking-table, ranking-bars | 1 | ranking | ranking |
| `metric_table` Tabela | table | 1–12 | todos | table |
| `recommendations` Recomendações | bullets, two-columns, matrix (F06B) | 0 | — | — (texto; em `matrix` cada item é uma linha `a \| b \| c \| d`, a 1ª é o cabeçalho) |
| `closing` Encerramento | closing | 0 | — | apresentadores; `items` (F06B) = grupos `título \| texto` |
| `section` Seção (F06B) | section | 0 | — | dono, competência (divisor; título + subtítulo/número) |
| `dashboard` Painel composto (F06B) | painel-kpis, painel-graficos, painel-grupos, painel-severidades, painel-tabela-grafico, painel-destaque-tabela | por zona | por zona | `{kind: dashboard, layout, zones{}}` |

Campos editoriais: `title`, `subtitle`, `body`, `items[]` (≤ 12), `chart_title`, `legend_title`, `caption`, `notes`
(notas do apresentador; fora do canvas). Opções: `months` (6|12), `data_mode` (breakdown|history), `show_values`,
`show_legend`, `show_presenters`, `top_n` (1–10).

### Painel composto e zonas (F06B)
Um `dashboard` é um layout com **zonas tipadas** (catálogo: `DASHBOARD_LAYOUTS`; API: `slide_types[].zones`). Cada zona
tem `kind` (`kpi_band`, `kpi_cards`, `severity_cards`, `donut`, `comparison`, `ranking`, `table`, `chart`, `text`),
mínimo/máximo de indicadores, tipos de valor aceitos, gráficos permitidos e fração padrão de posição. No slide:
`zones: {zona: {title?, metrics[≤6], chart? (bar|line|combo), data_mode?, months? (6|12), top_n? (1–10)}}`.
Validação (422 `invalid_document`/`invalid_template`, `details[].type`): `unknown_zone`, `metric_count`,
`duplicate_metric`, `unknown_metric`, `incompatible_metric`, `option_not_applicable`; `zones_not_applicable` fora do
painel. Zonas de texto usam os campos do slide (`body` ou `items`). A IR de cada zona usa os **mesmos** construtores
dos slides simples (nada é recalculado); `required_metrics` do slot cobre os indicadores de todas as zonas.
Gráfico `combo` (F06B): barras da 1ª série + linha da 2ª, mesmos meses e lacunas explícitas (IR `kind: combo`).
Retrocompatibilidade: `zones` vazio não é serializado — documentos e templates F06A mantêm os mesmos hashes (fixados
em `backend/tests/test_afrika_template.py`).

## Seleção flexível de slides e disponibilidade (F06C)
- `POST /api/presentations {…, slots?: [slot_id]}`: mantém só os slots escolhidos, na ordem do template; slots
  `required` (no Afrika: capa e encerramento) entram **sempre**; slot inexistente ⇒ 422 `unknown_slot`. Auditoria
  `presentation.created` registra `selected_slots` e `required_added`. Sem `slots` = todos (compatível). Depois da
  criação, o editor continua removendo/reordenando/adicionando slides.
- `GET /api/presentation-templates/{key}/versions/{v}/availability?competence_id=…[&revision=n]` (somente leitura):
  por slot, `status` ∈ `complete` (todos os indicadores com valor aprovado), `partial`, `none`, `editorial` (sem
  indicadores), estados por indicador e `suggested` (obrigatório, completo, parcial ou editorial). É sugestão: nada é
  removido automaticamente; histórico (6/12 meses) não entra — meses sem aprovação seguem como LACUNA.

## Documento da apresentação (por revisão)
`{schema_version: 1, title, presenters[{name, role}], slides[{slide_id, template_slot|null, type, layout, fields,
metrics[], options, zones?}]}` — sempre revalidado contra a versão do template. Fontes fixadas por revisão:
`{policy: "APPROVED_ONLY_PINNED", primary: ref, history_window: {start, end}, history: {YYYY-MM: ref}}`, com
`ref = {competence_id, competence, revision_id, revision, approval_id, approval_sequence, content_hash, chain_hash}`.
Hashes: `document_hash`, `sources_hash`, `revision_hash = SHA-256(presentation, number, previous_hash, document_hash,
sources_hash, template, primary_revision, primary_approval, autor, data, resumo)`.

## IR de gráficos (`ir_version` 1)
Comum: `{ir_version, kind, available, title, data_refs[{metric_id, competence, revision, approval_sequence,
content_hash}], warnings[]}`. Indisponível: `{available: false, reason, message}` com `reason` ∈ `gap`, `missing`,
`incompatible`, `unrecognized_structure`.

Ponto: `{x, y, state, label, value_state, origin, competence, metric_id[, color, extra, aggregate]}`.
- `state`: `VALUE` (há número aprovado), `GAP` (competência sem aprovação fixada), `MISSING` (sem snapshot/valor),
  `NOT_NUMERIC` (estrutura sem número principal), `INCOMPATIBLE` (versão de contrato).
- `y` só existe com `VALUE` e é **exatamente** o número aprovado (headline F05: contagem, total por severidade,
  decimal ou percentual). Ausência nunca vira 0.

| kind | Campos específicos |
|---|---|
| `kpi` | `items[]` (ponto + `name`, `unit`, `unit_label`, `value_type`) |
| `comparison` | `rows[{current, previous, delta, delta_label, delta_unavailable_reason, direction, trend, trend_reason, trend_color}]`; `delta` só entre aprovados numéricos de mesmo tipo e versão de contrato; motivos `gap`, `no_numeric_value`, `value_type_changed`, `contract_version_changed`. F06C: `trend` ∈ `improvement`/`worsening` (só com `delta` e direção declarada no indicador), `unchanged` (delta 0 com direção), `unknown` (sem direção — `trend_reason: direction_not_declared` — ou sem delta — motivo do delta); `trend_color` = `variation.improvement|worsening|neutral` |
| `bar` / `line` | `x_axis {type: month|category, label}`, `y_axis {label, min: 0, integer}`, `number_format`, `categories[]`, `series[{key, label, metric_id, color, points[]}]`, `legend {show, title}`, `gaps[]`, `show_values` |
| `severity` | como `bar`, categorias fixas Muito alta → Desconhecida, `color = severity.<CHAVE>`, `total` |
| `ranking` | `columns[]`, `rows[{rank, label, y, value, extra}]` (ordem da fonte, até `top_n`), `aggregate_rows` ("Outros"), `max_y` |
| `table` | `rows[{metric_id, name, state, value, y, unit_label, value_state, origin, source}]` |

### Direção desejável (F06C)
`MetricContract.desired_direction` ∈ `LOWER_IS_BETTER`, `HIGHER_IS_BETTER`, `NEUTRAL` (padrão) + `direction_rationale`;
declarada num único lugar (`registry.DESIRED_DIRECTIONS`) e exposta no catálogo (`metrics[].desired_direction`).
Metadado de apresentação: **não** muda `version` do contrato nem valores. Hoje só o backlog de findings ABERTOS (7
indicadores SAST/SCA, Policy/Sandbox/distintos) declara `LOWER_IS_BETTER`; todo o resto é neutro (pendente de
confirmação do PO).

### Plano de exportação (F06C — contrato da F07)
`GET /api/presentations/{id}/export-plan` — ver `docs/F07_EXPORT_READINESS.md` (nenhum arquivo é gerado). Na F07 o
layout `ranking-bars` passou a `export_as: table` (tabela nativa completa + barras como formas decorativas; o número é
texto na célula) e distribuição aprovada sem itens a `unavailable` (como o HTML).

### Exportação (F07 + F07.1) — `docs/EXPORT.md`
- Entrada: `POST /api/presentations/{id}/exports {format: pptx|pdf, revision: N ≥ 1, operator}` (`extra='forbid'`); só
  a revisão PERSISTIDA informada, com fonte aprovada (`APPROVED_ONLY_PINNED`), referências íntegras e sem bloqueios;
  senão 409 `export_blocked` com `details[{field, message, type}]`.
- Job: `{id, presentation_id, revision, format, operator, status: queued|running|done|failed, created_at, started_at,
  finished_at, template, theme, filename, media_type, size, sha256, download_url, report, warnings[], timings,
  error{code, message, details}}` (caminho local nunca exposto). Erros: `content_overflow` (por slide;
  tipos `clipped-x|clipped-y|spill-x|ellipsis|outside-zone|outside-slide`), `font_unavailable`,
  `render_request_blocked`, `renderer_missing|renderer_stale`, `export_engine_unavailable`, `pptx_invalid|pdf_invalid`,
  `export_too_large`.
- Documento: `severity_labels: veracode|executive` (padrão `veracode`, omitido do JSON canônico — hashes antigos
  preservados). `executive` troca só o RÓTULO de "Muito alta" por "Crítica"; a categoria original segue em `key` e
  `source_label` do ponto da IR.
- Matriz: célula de até 1000 caracteres (`MATRIX_CELL_MAX`); fonte reduzida em degraus até 60%; sem caber ⇒ bloqueio.
- Rótulo de categoria (F07.1): quebra em até 3 linhas (`<tspan>`); acima disso o `<text>` recebe `data-abbrev` e a
  exportação é bloqueada (`ellipsis`, elemento `axis-label:<rótulo>`).
- Saída PPTX: `docProps/custom.xml` com `afrika.*` (revisão e hashes, template@versão+hash, tema@versão+hash, dono,
  competência, fonte primária, política, rótulos, versões de plano/layout, hash do renderizador); mesmo SHA-256 para a
  mesma revisão + template/tema + build.

### Cores
Tokens do tema; o renderizador resolve (tokens obrigatórios em `docs/THEMES.md`). Séries: `series.1…4` na ordem de vinculação (fixa, nunca por posição de
ranking; máx. 4 séries por gráfico de linhas). Severidade: rampa ordinal de um tom (`severity.VERY_HIGH` mais escura
→ `severity.INFORMATIONAL` mais clara) + `severity.UNKNOWN` cinza com textura (temas F06A/F06B); no `afrika@2` (F06C),
por nível semântico do PO — Muito alta=Crítica vermelho, Alta laranja, Média amarelo, Baixa e Muito baixa azul,
Informativa cinza, Desconhecida cinza claro com textura. Lacuna: `gap` (contorno tracejado).
Paleta validada com o validador de paleta (categórica 4 slots: PASS, aviso de contraste ⇒ rótulos visíveis; rampa de
severidade: PASS no modo claro do canvas). Identidade nunca só por cor: rótulos/legenda sempre presentes.

### Eixos, rótulos, unidade e arredondamento
- Eixo Y começa em 0, linear; `integer=true` para contagens. Escala/grade são geometria do renderizador, não dados.
- Unidade do contrato (`applications` ⇒ "aplicações", `findings`, `lines_of_code` ⇒ "linhas de código",
  `components`, `projects`).
- Formato pt-BR (milhar `.`, decimal `,`). Contagens: inteiras, sem arredondamento. `decimal`: 2 casas; `percentage`:
  1 casa + `%`; arredondamento **meio-par** só no rótulo — `y` preserva o valor bruto.
- Linhas: segmentos só entre meses consecutivos com valor; lacuna quebra a linha (sem interpolação).
- F06B.1 (renderização): eixo de meses sem espaço mostra um rótulo a cada N meses (sempre o último) em vez de truncar;
  categorias longas continuam truncadas no eixo, com o nome completo no título do elemento. Geometria do gráfico
  (viewBox, recuos, barras, linhas, rótulos) vem de `theme.charts`.

### Adaptadores de estrutura (distribuições e rankings)
Explícitos por indicador (`charts._CATEGORY_ADAPTERS`, `_FIXED_KEYS`): `apps.by_business_unit`, `apps.by_team`,
`apps.by_policy_compliance`, `sast.policy.open.by_first_found_month`, `sca.policy.open.by_dependency_mode`,
`sast.policy.open.by_cwe` (+ "Outros"), `sast.policy.open.top_applications`, `sca.policy.open.top_components`,
`sca.policy.open.top_vulnerabilities`, `scans.covered_apps`. Indicador sem adaptador ou valor sem a forma esperada ⇒
`unrecognized_structure`.

## Interpretação (F08) — integração com o documento (`docs/INTERPRETATION.md`)
- Fonte: a revisão **persistida** da apresentação e as aprovações fixadas nela (nunca rascunho do editor, nunca
  Veracode). O contexto usa `view.resolve` e a regra de variação de `charts.comparison` — os mesmos números da IR.
- Destino: um campo editorial do slide (`body`, `items`, `caption` ou `notes`) conforme tipo/layout
  (`contracts.default_target`). Nenhum campo novo no documento nem no template: hashes antigos inalterados.
- Entrada no slide só por `POST /api/presentations/{pid}/interpretations/{iid}/apply` (versão `APPROVED`, mais recente,
  não desatualizada) ⇒ nova revisão da apresentação (`change_summary` "Interpretação aprovada aplicada: …"), auditoria
  `presentation.saved` com `interpretation_id`. Texto diferente no campo exige `overwrite_confirmed: true` (409
  `interpretation_overwrite_requires_confirmation` com o texto atual). `expected_revision` = concorrência otimista
  (409 `presentation_conflict`). `items` recebe uma afirmação por tópico.
- Desatualização sinalizada quando `sources_hash` da revisão atual ≠ o da geração (`sources_changed`) ou o contexto
  recalculado diverge (`facts_changed`); edição manual posterior do texto aplicado é preservada (`applied_text_edited`).
- Exportação (F07) e visualização (F06A) não conhecem o módulo de interpretação: exibem o texto persistido.
