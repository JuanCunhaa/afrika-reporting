# Interpretação dos indicadores (F08)

Texto editorial **assistido** (executivo ou técnico) para os slides, gerado a partir **somente** dos valores aprovados
fixados na revisão da apresentação, verificado por regras determinísticas no backend e liberado para o slide **apenas**
por aprovação humana explícita. A IA (ou o provedor de regras) **não** calcula, altera, substitui nem aprova
indicadores; o core determinístico, as apresentações e a exportação funcionam com a interpretação desligada.

Código: `backend/app/interpretation/` (`contracts.py`, `context.py`, `providers.py`, `validate.py`, `service.py`,
`settings.py`), `backend/app/api_interpretations.py`, migration `0007_interpretations`, painel
`frontend/src/pages/InterpretationPanel.tsx`. Testes: `backend/tests/test_interpretation.py`,
`backend/tests/test_interpretation_export.py`, `frontend/e2e/interpretation.spec.ts`.

## 1. Fluxo
```
revisão PERSISTIDA da apresentação (fontes aprovadas fixadas, F06A)
  └─ context.build: seleção de indicadores por slide/tipo + fatos determinísticos (M1…, P1, E1…)
       └─ provedor (padrão: deterministic-demo, local) → afirmações [{text, fact_ids}]
            └─ validate.validate (backend, determinístico) → bloqueios/avisos
                 └─ versão GENERATED (append-only) → IN_REVIEW → APPROVED | REJECTED (pessoa declarada)
                      └─ "Aplicar ao slide" → NOVA revisão da apresentação (texto no campo editorial)
                           └─ HTML / PPTX / PDF exibem o texto persistido (exportação nunca chama provedor)
```

## 2. Dados permitidos (e só estes)
- Valores **aprovados** da competência e do histórico (as aprovações fixadas na revisão da apresentação — mesmo
  resolvedor da visualização, `view.resolve`). Nenhuma consulta à Veracode.
- Variações calculadas pelo backend: `delta` pela mesma regra da IR (`charts.comparison`: só entre aprovados numéricos
  de mesmo tipo e versão de contrato), `delta_pct` = Δ/anterior×100 com 1 casa, meio-par (anterior = 0 ⇒ sem
  percentual, motivo `previous_zero`), por severidade, participação nas distribuições, soma dos 3 primeiros do
  ranking, mínimo/máximo/meses com valor do histórico.
- Estado e qualidade: `state` (VALUE, MISSING, GAP, INCOMPATIBLE, NOT_NUMERIC), `value_state` (VALIDATED, MANUAL,
  INCOMPLETE, SOURCE_UNAVAILABLE, UNSUPPORTED, MISSING), `origin`, `definitive`, tendência comprovada (`trend`, só com
  direção declarada no indicador) e proveniência (competência, revisão, sequência e hash da aprovação, contrato).
- Metadados: competência, anterior, janela do histórico (6 meses; 12 se o slide pedir) e competências aprovadas (P1).
- Notas editoriais **declaradas pelo operador** (até 5 × 500 caracteres; e-mail, URL, UUID, hex longo e cadeias
  com cara de segredo são recusados — `editorial_note_sensitive`).

Fora do contexto: findings brutos, credenciais, nome do cliente/subcliente, e **rótulos** de distribuições/rankings
identificáveis (aplicações, BUs, Teams, componentes, vulnerabilidades) — esses entram só como posição e valor
(`labels_redacted: true`). Rótulos não identificáveis são mantidos: status de conformidade, mês de identificação, tipo
de dependência, CWE, cobertura (`context.LABEL_SAFE`).

## 3. Tipos e níveis
| `kind` | Indicadores selecionados |
|---|---|
| `EXECUTIVE_SUMMARY` | do slide + do documento com número principal (até 10) |
| `IMPROVEMENTS` / `ATTENTION_POINTS` | com direção declarada primeiro + demais do documento; melhora/piora só se comprovada; severidades Muito alta/Alta |
| `SAST_TRENDS` / `SCA_TRENDS` | `sast.*` / `sca.*` com número principal (histórico aprovado, lacunas explícitas) |
| `PERIOD_COMPARISON` | do slide (ou do documento) — atual × anterior |
| `COMPLIANCE_EVOLUTION` | `apps.by_policy_compliance` (participações) + `apps.total` |
| `SCAN_COVERAGE_EVOLUTION` | `scans.covered_apps` + `scans.count` + `apps.total` |
| `CHART_EXPLANATION` / `RANKING_HIGHLIGHTS` | os do próprio slide (ranking sem nomes) |
| `TECHNICAL_RECOMMENDATIONS` | direção declarada + cobertura/conformidade; recomendações só a partir de fatos (triagem por severidade, investigar aumento, agenda de varredura, concluir coleta) |

Níveis: `EXECUTIVE` (objetivo, consultivo) e `TECHNICAL` (cita `metric_id`, estado técnico, origem manual, ausência de
direção, práticas DevSecOps). Causa nunca é inferida: quando há piora, o texto propõe investigação neutra.

Aplicabilidade por tipo de slide (`contracts.KINDS_BY_SLIDE`; o 1º é o padrão) e campo de destino: sumário → `body`;
recomendações → `items` (matriz: não suportado); painel → campo da zona de texto do layout (sem zona de texto: não
suportado); gráficos/ranking → `caption` (ou `body` em `chart-with-text`); KPIs/tabela/comparação → `caption`;
`notes` pode ser pedido explicitamente. Capa, seção e encerramento não recebem interpretação.

## 4. Contrato de saída (versão de interpretação)
`{id, presentation_id, owner{kind, id, client_id, subclient_id}, competence{id, competence}, presentation_revision,
slide_id, target_field, kind, kind_name, level, version, parent_id, origin (GENERATED|EDITED), text, statements[{text,
fact_ids}], indicators[{fact_id, metric_id, name, state, value_state, origin, definitive, current, previous, delta,
delta_label, delta_pct, delta_unavailable_reason, trend, provenance, labels_redacted}], provider, model,
prompt_version, prompt_hash, context_hash, sources_hash, content_hash, validation{valid, blockers, warnings, issues[],
checked}, valid, justification, created_by, created_at, status, is_latest, stale[], notices[], applied[], events[],
history[]}`. `context` (fatos completos) e `editorial_notes` vêm no detalhe.

Hashes: `context_hash` = SHA-256 do contexto canônico (fatos + tipo + nível + destino + notas + versão do prompt);
`sources_hash` = hash das fontes fixadas na revisão da apresentação usada; `content_hash` cobre texto, afirmações,
contexto, validação, autoria e data. Persistência append-only (gatilhos): `interpretation_versions`,
`interpretation_events`, `interpretation_slide_settings`. Auditoria (`audit_events`) só com ids/hashes — nunca texto.

## 5. Validação determinística (`validate.py`, versão `f08-val-1`)
Por afirmação, contra os fatos que ela cita (edição humana = texto inteiro contra todos os fatos da versão de origem):
| Regra | Código (bloqueio, salvo indicação) |
|---|---|
| número inexistente nos fatos citados (arredondamento só no rótulo, meio-par, para menos casas) | `unverified_number` |
| `%`/pontos percentuais × contagem | `unit_mismatch` |
| número sem fato citado; afirmação gerada sem fato | `uncited_number`, `statement_without_evidence` |
| fato citado inexistente | `unknown_fact` |
| competência fora do contexto (`AAAA-MM`, `MM/AAAA`, "setembro de 2026") | `period_not_in_context` |
| fato sem valor aprovado sem declarar a ausência; número atribuído a ele | `missing_value_not_declared`, `number_for_missing_value` |
| "aumento/redução" contrário ao delta; "favorável/desfavorável" sem tendência comprovada | `direction_mismatch`, `trend_not_proven` |
| causa, remediação/correção, remoção, maturidade, risco de negócio, absolutos | `unsupported_<categoria>_claim` — vira **aviso** se a afirmação cita nota editorial (`claim_from_operator_note`) ou se a edição traz justificativa declarada (`claim_justified_by_editor`) |
| tamanho do campo do slide | `too_long`, `too_many_items` |
| e-mail, URL, UUID, hex longo, segredo | `sensitive_data` |
| valor manual citado sem declarar origem manual | `manual_not_disclosed` (aviso) |

Texto com bloqueio fica visível, mas **não pode ser aprovado** (409 `interpretation_not_valid`).

### Limites por slide (medidos com o motor real de exportação)
Medição F08 (texto sintético, Chromium do exportador, temas `afrika@2` nos painéis e `neutral-demo` nos demais) — o
que cabe sem corte → limite adotado (`contracts.budget_for`): `painel-graficos` 3 tópicos × 150 → **3 × 130**;
`painel-grupos`/`painel-severidades` 5 × 150 → **4 × 150**; `painel-tabela-grafico` 6 × 150 → **5 × 150**; corpo do
`painel-kpis` ~520 → **420**; tópicos de recomendações 8 × 220 → **8 × 220**; duas colunas 8 × 160 (10 × 160 estoura)
→ **8 × 160**; texto lateral de gráfico ~600 (800 estoura) → **500**; legenda 520 → **240**; sumário 1400+ →
**700** (`text-with-highlights`) / **1400** (`text-only`); notas 3000. O provedor só **escolhe quantas afirmações
cabem** (nunca corta frases; em tópicos curtos usa frases compactas e, no técnico, identifica o indicador pelo
`metric_id`). A verificação final continua sendo a da exportação (F07), que bloqueia corte em vez de truncar.

## 6. Revisão humana e integração com a apresentação
- `GENERATED → IN_REVIEW → APPROVED | REJECTED` (rejeição exige motivo). Só a versão mais recente da linha
  (apresentação, slide, tipo) avança (`interpretation_superseded`).
- Editar = nova versão `EDITED` (autor declarado, justificativa opcional, entra em `IN_REVIEW`), revalidada contra os
  mesmos fatos. Regenerar = nova versão `GENERATED` com `parent_id` (pode trocar nível/notas). Comparar = diff por
  palavra (mesma linha).
- **Desatualização**: `sources_changed` (fontes fixadas trocadas — nova aprovação + "Atualizar fontes aprovadas"),
  `facts_changed` (fatos recalculados diferentes: snapshot/histórico/slide), `slide_missing`. Bloqueiam aprovar e
  aplicar (`interpretation_stale`); informativos: `newer_approval_available` (há aprovação mais nova ainda não
  fixada — a apresentação e a interpretação seguem coerentes com a fixada) e `applied_text_edited` (texto aplicado e
  depois editado à mão).
- **Aplicar** (`APPROVED` + atual + não desatualizada + `expected_revision`): grava o texto no campo do slide como
  NOVA revisão da apresentação (mesma transação do evento `APPLIED`; resumo "Interpretação aprovada aplicada…").
  Campo com texto diferente ⇒ 409 `interpretation_overwrite_requires_confirmation` com o texto atual; só substitui com
  `overwrite_confirmed: true`. Indicadores, proveniência, template e tema não mudam; edição manual posterior é
  preservada.
- Desabilitar por slide (append-only): geração e edição recusadas (`interpretation_disabled`).
- HTML, PPTX e PDF leem o **documento persistido**: o mesmo texto aparece nos três (teste com motor real). Nenhum texto
  entra numa revisão sem "Aplicar" explícito; nenhuma chamada a provedor durante a exportação (teste que derruba
  qualquer chamada).

## 7. API
| Método | Rota | Uso |
|---|---|---|
| GET | `/api/interpretation/config` | provedores, tipos, níveis, aplicabilidade, limites (sem segredo) |
| GET | `/api/presentations/{pid}/interpretations` | versões + estado + desatualização + slides desabilitados |
| POST | `…/interpretations/context` | contexto e o que SERIA transmitido (nada é gravado/enviado) |
| POST | `…/interpretations` | `{slide_id, kind?, level, notes[], provider?, target_field?, external_consent, operator}` |
| GET | `…/interpretations/{iid}` | detalhe (fatos, validação, histórico) |
| POST | `…/{iid}/review` · `/approve` · `/reject` | `{operator, reason?}` (rejeição exige motivo) |
| POST | `…/{iid}/edit` | `{text, operator, justification?}` → nova versão |
| POST | `…/{iid}/regenerate` | `{operator, level?, notes?, provider?, external_consent}` → nova versão |
| POST | `…/{iid}/apply` | `{operator, expected_revision, overwrite_confirmed}` → revisão nova da apresentação |
| GET | `…/{iid}/compare/{other}` | diff por palavra |
| PUT | `/api/presentations/{pid}/interpretation-settings/{slide_id}` | `{disabled, operator, reason?}` |
Isolamento: toda versão é lida pela apresentação dona (`404` por outra apresentação/cliente).

## 8. Provedores e segurança
- **`deterministic-demo`** (padrão, único implementado): regras locais, sem rede, mesma entrada ⇒ mesma saída;
  `model = regras-f08@1`; `prompt_version = f08-interp-1` (o texto de instruções é versionado e tem hash mesmo sem uso).
- **`ExternalProvider`** (base, nenhum fornecedor acoplado; `EXTERNAL_PROVIDERS` vazio): subclasses implementam só
  `_send(payload) -> {statements}`. Travas na base, nesta ordem: `AFRIKA_AI_EXTERNAL_ENABLED=true`; credencial
  `AFRIKA_AI_API_KEY` no ambiente do servidor (nunca exposta pela API nem logada); **consentimento por execução**
  (`external_consent: true` — sem ele nada é enviado); limite diário (`AFRIKA_AI_MAX_REQUESTS_PER_DAY`, padrão 20);
  tamanho máximo (`AFRIKA_AI_MAX_INPUT_CHARS`, padrão 30000); conteúdo minimizado (sem hashes/ids de aprovação/nome
  de fonte) e recusado com padrão sensível; prazo (`AFRIKA_AI_TIMEOUT_S`); falha/timeout/saída fora do contrato ⇒
  502 com mensagem fixa, nada persistido. A saída externa passa pela MESMA validação. `POST …/context` mostra
  exatamente o payload que seria transmitido.
- Outras variáveis: `AFRIKA_AI_PROVIDER` (padrão `deterministic-demo`), `AFRIKA_AI_MODEL`. Nenhuma é obrigatória.
- Logs: só ids, tipo, nível, provedor, código de erro e tamanho — nunca texto, valores, nomes ou notas.
- Nenhum PPTX de referência ou dado de cliente é usado/enviado; testes só com dados sintéticos; o conftest bloqueia
  qualquer conexão fora do loopback.

## 9. Limitações conhecidas
- Painel sem zona de texto (`painel-destaque-tabela`) e recomendações em `matrix` não recebem interpretação (422
  explícito) — a matriz exige linhas "a | b | c | d" editoriais.
- O validador é conservador e lexical (pt-BR): pode bloquear frase correta com palavra da lista (ex.: "sempre") —
  edição com justificativa transforma em aviso; não entende paráfrases numéricas por extenso ("dois").
- Limites medidos com texto sintético nos temas atuais; tema/fonte nova exige nova medição (a exportação bloqueia corte
  de qualquer forma).
- Nenhum provedor externo real implementado (decisão de fornecedor, custos e termos de uso: pendência do PO).
