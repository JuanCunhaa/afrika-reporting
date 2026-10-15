# Snapshots, revisões, aprovação, histórico e auditoria (F05)

Código: `backend/app/snapshots/` (`values.py`, `service.py`, `history.py`, `audit.py`), API `backend/app/api_snapshots.py`,
migration `0004_snapshots`. Telas: **Competências** (`#/snapshots`), **Histórico** (`#/history`) e botão
"Criar rascunho da competência" no painel de Indicadores.

## Entidades (migration `0004_snapshots`)
| Tabela | Papel | Proteção no banco |
|---|---|---|
| `competences` | competência `YYYY-MM` de um dono (cliente **ou** subcliente; `owner_key` `client:<id>`/`subclient:<id>`), fuso do cliente vigente na criação | identidade (dono, rótulo, fuso) imutável; sem DELETE; `UNIQUE(owner_key, label)` |
| `competence_revisions` | revisão numerada; `DRAFT` → `READY_FOR_REVIEW` → `APPROVED`; `lock_version`; conjunto explícito de obrigatórios (`required_metrics_json` + `required_set_version`) | nasce DRAFT; transições válidas só por gatilho; APPROVED imutável; sem DELETE; 1 revisão aberta por competência (índice parcial) |
| `metric_snapshots` | valor de UM indicador numa revisão (efetivo + fonte preservada + proveniência) | INSERT/UPDATE só com revisão DRAFT; sem DELETE; CHECKs de origem/estado |
| `manual_changes` | cada alteração manual: anterior, novo, origens, justificativa, operador, UTC | append-only; INSERT só em DRAFT |
| `approvals` | aprovação de uma revisão: aprovador declarado, `content_hash`, `previous_chain_hash`, `chain_hash` | append-only; só para revisão APPROVED da mesma competência; `UNIQUE(competence_id, sequence)` |
| `audit_events` | trilha de eventos encadeada por hash | append-only; `prev_hash` único (cadeia linear, sem bifurcação concorrente) |
| `collection_runs` | execução F04 importada: só metadados/resumos (engine, `input_hash`, escopos, conexão por id/nome/região, população, coleta, contagem de status) | append-only |
| view `v_official_revisions` | referência da série histórica: aprovação de maior sequência por competência | derivada (sem tabela redundante) |

Downgrade da 0004 é **recusado** se houver aprovações, salvo `AFRIKA_ALLOW_DESTRUCTIVE_DOWNGRADE=1` (procedimento
administrativo com backup). Não há exclusão física de histórico na aplicação.

## Contrato do snapshot (`metric_snapshots`)
- Dono e competência: pela revisão → competência (`owner_key`, `client_id`, `subclient_id`, `label`, `timezone`).
- Indicador: `metric_id`, `contract_version`, `value_type` (`count`, `decimal`, `percentage`, `by_severity`,
  `breakdown`, `ranking`), `shape`, `unit`.
- **Valor efetivo** `value_json` (NULL = ausente; `0` = zero legítimo) e `origin` `VERACODE` | `MANUAL`.
- **Fonte preservada** (nunca sobrescrita por valor manual): `source_status` (status técnico F04: VALIDATED,
  INCOMPLETE, UNAVAILABLE, UNSUPPORTED, FAILED), `source_value_json` (só com VALIDATED), `source_partial_json` (só com
  INCOMPLETE), `source_reasons_json` (motivo da incompletude), `source_name`, `endpoint`, `context` (POLICY/SANDBOX/…),
  `collected_at`, `temporal_json` (competência, intervalo local e UTC efetivamente usado, `as_of`).
- **Homologação com dashboard** `dashboard_homologation` (do contrato; ex.: `NOT_VERIFIED`) — separada do status
  técnico; nunca promovida automaticamente.
- Escopos: `scope_refs_json` (dono, domínio, versão, `rule_hash`, modo de conexão). Proveniência: `provenance_json`
  (`run_id`, engine, `input_hash`, conexão **sem** referência de credencial, cobertura, filtros), `collection_run_id`.
- Manual: `manual_justification`, `manual_operator`, `manual_at`. Integridade: `row_hash` (SHA-256 do conteúdo canônico).
- Nada de findings individuais, respostas HTTP, credenciais ou `credential_ref` (testado). Rankings/distribuições guardam
  dimensões necessárias aos slides (nome/GUID de aplicação, BU, Team, CWE, componente), apenas no banco local.

## Estado do valor (derivado, exibido)
| Estado | Condição |
|---|---|
| `VALIDATED` | valor da Veracode com coleta tecnicamente válida (zero incluso) — **não** significa homologado |
| `MANUAL` | valor efetivo manual (fonte preservada à parte) |
| `INCOMPLETE` | coleta incompleta: só agregado parcial + motivos |
| `SOURCE_UNAVAILABLE` | fonte indisponível/falhou (UNAVAILABLE, FAILED) |
| `UNSUPPORTED` | nenhuma fonte suporta o indicador |
| `MISSING` | nenhum dado |

## Ciclo de vida e aprovação
1. **Rascunho**: `POST /api/competences` (vazio) ou `POST /api/competences/from-run` (execução F04 concluída; cria a
   competência se preciso; se a última revisão já está aprovada, abre a revisão seguinte). Também
   `POST …/revisions/{n}/import-run`. Execução precisa ser do mesmo dono, competência e fuso; coleta repetida nunca toca
   revisão aprovada (gatilho + regra). Valor manual existente é mantido na reimportação; a fonte é atualizada.
2. **Edição** (só DRAFT): `PUT …/metrics/{metric_id}` (valor tipado + justificativa ≥ 10 caracteres + operador),
   `POST …/revert` (volta ao valor da fonte, também registrado), `PUT …/required` (conjunto explícito e versionado).
3. **Revisão**: `POST …/submit` (READY_FOR_REVIEW, não editável) / `POST …/return` (volta a DRAFT com motivo).
4. **Aprovação** `POST …/approve` — bloqueada (409 `approval_blocked`, evento `approval.blocked` auditado) quando:
   conjunto obrigatório vazio; obrigatório sem valor; valor inválido para o tipo; `row_hash` divergente; revisão fora de
   READY_FOR_REVIEW; `lock_version` divergente. Aprovador é obrigatório (422). Permite valores manuais justificados.
   Cria `approvals` com `content_hash` (competência, revisão, obrigatórios, hashes dos snapshots) e `chain_hash`.
5. **Revisão posterior**: `POST /api/competences/{cid}/revisions` copia exatamente a última aprovada (mesmos hashes);
   aprovada de novo, passa a ser a oficial; anteriores seguem consultáveis (`GET …/revisions/{n}`, `…/compare?a&b`).

Concorrência: toda alteração exige `expected_lock_version`; a atualização é condicional no banco
(`WHERE lock_version = esperado`) ⇒ escrita concorrente = 409 `revision_conflict`/`concurrent_modification`
(teste com 4 threads: 1 sucesso, 3 conflitos).

**Identidade**: operador/aprovador são **declarados** (texto, `identity_mode = DECLARED_UNAUTHENTICATED`), sem
autenticação — rastreabilidade, não prova de identidade. Backend restrito a loopback (`LocalOnlyMiddleware`).

## Indicadores obrigatórios
Sem template oficial, **não** há lista padrão: o operador seleciona explicitamente, por revisão, os `metric_id`
obrigatórios (versão incrementada a cada mudança; copiada para revisões posteriores). Só eles bloqueiam a aprovação.

## Histórico
- `GET /api/history/{kind}/{owner_id}/series?metric_id=…&months=6|12[&end=YYYY-MM]` ou `&start=…&end=…` (máx. 60
  meses). Fim padrão = último mês fechado no fuso do cliente (padrão `America/Sao_Paulo`).
- Só revisões aprovadas (referência = aprovação mais recente). Competência sem aprovação = `GAP` (valor `null`), sem
  interpolação nem zero. Aprovada sem o indicador = `MISSING`. Avisos se tipo de valor ou versão de contrato mudam.
- `GET /api/history/{kind}/{owner_id}/compare?competence=YYYY-MM[&metric_id=…]`: mês × anterior, com `delta` só quando
  ambos aprovados, numéricos e com mesmo tipo/versão de contrato.
- Valores saem do banco exatamente como aprovados: setembro consultado em outubro devolve o aprovado em setembro,
  mesmo que a Veracode tenha mudado (teste `test_previous_month_is_reused_exactly_even_after_veracode_changes`).
- Lacuna é preenchida só por competência criada para aquele mês, valor manual justificado e aprovação (auditado).

## Auditoria e integridade
Eventos: `competence.created`, `revision.created`, `run.imported`, `metric.manual_set`, `metric.manual_reverted`,
`required_set.updated`, `revision.submitted`, `revision.returned_to_draft`, `approval.blocked`, `revision.approved`.
`GET /api/competences/{cid}/audit` lista; `GET …/integrity` recalcula `row_hash`, `content_hash`, cadeia de aprovações
e a cadeia global de auditoria (adulteração direta no banco é detectada — testado).

## Limitações
- Identidade declarada (sem autenticação/assinatura); hashes detectam adulteração, não a impedem fora da aplicação
  (quem tem o arquivo SQLite pode remover gatilhos — por isso a verificação recalcula tudo).
- Execuções F04 vivem em memória: importar na mesma sessão do backend; o rascunho importado persiste.
- SQLite local (sem uso compartilhado/multiusuário); hospedagem futura exige reavaliação (Postgres, autenticação).
