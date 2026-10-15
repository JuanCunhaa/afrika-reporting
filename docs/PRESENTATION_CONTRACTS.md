# Contratos de templates, documentos e gráficos (F06A)

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

## Tipos de slide (componentes disponíveis — nenhum é obrigatório por si)
| Tipo | Layouts | Indicadores | Tipos de valor | IR |
|---|---|---|---|---|
| `cover` Capa | cover | 0 | — | dono, competência, período, apresentadores |
| `executive_summary` Sumário | text-with-highlights, text-only | 0–4 | count, decimal, percentage, by_severity | kpi |
| `kpis` KPIs | kpi-grid | 1–6 | idem | kpi |
| `month_comparison` Mês × anterior | comparison-table, comparison-cards | 1–6 | idem | comparison |
| `bar_chart` Barras | chart-full, chart-with-text | 1 | `breakdown`: breakdown, ranking, by_severity; `history`: count, decimal, percentage, by_severity | bar |
| `line_chart` Linhas | chart-full, chart-with-text | 1–4 | count, decimal, percentage, by_severity | line |
| `severity_distribution` Severidade | chart-full, chart-with-text | 1 | by_severity | severity |
| `top10_ranking` Top 10 | ranking-table, ranking-bars | 1 | ranking | ranking |
| `metric_table` Tabela | table | 1–12 | todos | table |
| `recommendations` Recomendações | bullets, two-columns | 0 | — | — (texto) |
| `closing` Encerramento | closing | 0 | — | apresentadores |

Campos editoriais: `title`, `subtitle`, `body`, `items[]` (≤ 12), `chart_title`, `legend_title`, `caption`, `notes`
(notas do apresentador; fora do canvas). Opções: `months` (6|12), `data_mode` (breakdown|history), `show_values`,
`show_legend`, `show_presenters`, `top_n` (1–10).

## Documento da apresentação (por revisão)
`{schema_version: 1, title, presenters[{name, role}], slides[{slide_id, template_slot|null, type, layout, fields,
metrics[], options}]}` — sempre revalidado contra a versão do template. Fontes fixadas por revisão:
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
| `comparison` | `rows[{current, previous, delta, delta_label, delta_unavailable_reason}]`; `delta` só entre aprovados numéricos de mesmo tipo e versão de contrato; motivos `gap`, `no_numeric_value`, `value_type_changed`, `contract_version_changed` |
| `bar` / `line` | `x_axis {type: month|category, label}`, `y_axis {label, min: 0, integer}`, `number_format`, `categories[]`, `series[{key, label, metric_id, color, points[]}]`, `legend {show, title}`, `gaps[]`, `show_values` |
| `severity` | como `bar`, categorias fixas Muito alta → Desconhecida, `color = severity.<CHAVE>`, `total` |
| `ranking` | `columns[]`, `rows[{rank, label, y, value, extra}]` (ordem da fonte, até `top_n`), `aggregate_rows` ("Outros"), `max_y` |
| `table` | `rows[{metric_id, name, state, value, y, unit_label, value_state, origin, source}]` |

### Cores
Tokens do tema; o renderizador resolve. Séries: `series.1…4` na ordem de vinculação (fixa, nunca por posição de
ranking; máx. 4 séries por gráfico de linhas). Severidade: rampa ordinal de um tom (`severity.VERY_HIGH` mais escura
→ `severity.INFORMATIONAL` mais clara) + `severity.UNKNOWN` cinza com textura. Lacuna: `gap` (contorno tracejado).
Paleta validada com o validador de paleta (categórica 4 slots: PASS, aviso de contraste ⇒ rótulos visíveis; rampa de
severidade: PASS no modo claro do canvas). Identidade nunca só por cor: rótulos/legenda sempre presentes.

### Eixos, rótulos, unidade e arredondamento
- Eixo Y começa em 0, linear; `integer=true` para contagens. Escala/grade são geometria do renderizador, não dados.
- Unidade do contrato (`applications` ⇒ "aplicações", `findings`, `lines_of_code` ⇒ "linhas de código",
  `components`, `projects`).
- Formato pt-BR (milhar `.`, decimal `,`). Contagens: inteiras, sem arredondamento. `decimal`: 2 casas; `percentage`:
  1 casa + `%`; arredondamento **meio-par** só no rótulo — `y` preserva o valor bruto.
- Linhas: segmentos só entre meses consecutivos com valor; lacuna quebra a linha (sem interpolação).

### Adaptadores de estrutura (distribuições e rankings)
Explícitos por indicador (`charts._CATEGORY_ADAPTERS`, `_FIXED_KEYS`): `apps.by_business_unit`, `apps.by_team`,
`apps.by_policy_compliance`, `sast.policy.open.by_first_found_month`, `sca.policy.open.by_dependency_mode`,
`sast.policy.open.by_cwe` (+ "Outros"), `sast.policy.open.top_applications`, `sca.policy.open.top_components`,
`sca.policy.open.top_vulnerabilities`, `scans.covered_apps`. Indicador sem adaptador ou valor sem a forma esperada ⇒
`unrecognized_structure`.
