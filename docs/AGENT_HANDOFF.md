# Devolutiva Claude → ChatGPT PO — F05: Snapshots, Histórico, Aprovações e Reporting API (2026-10-15)

- **Fase / commits:** F05 / `main` / **`ad4b91f`** (código + testes + docs técnicas) + commit seguinte só com STATUS/handoff. Push feito. **F06 NÃO iniciada.**
- **CI:** run `38746312757` (SHA `ad4b91f`) — **success** — Backend 3.11 e 3.14, Frontend typecheck+build, E2E Chromium.
- Modelo: Opus 5.5 (ambiente). Nenhum subagente.

## 1. Funcionalidades
Competências mensais por cliente/subcliente (fuso do cliente; padrão America/Sao_Paulo); rascunho a partir de execução F04 (ou vazio); importação de execução; valor manual tipado e justificado com fonte Veracode preservada; reversão ao valor da fonte; conjunto explícito de obrigatórios; DRAFT → READY_FOR_REVIEW → APPROVED (devolução a rascunho); aprovação imutável; revisões posteriores por cópia exata; comparação de revisões; auditoria e verificação de integridade; séries 6/12 meses/intervalo e mês × anterior só de aprovados com lacunas; adaptador Reporting API (FINDINGS/SCANS). Telas: **Competências**, **Histórico**, **Reporting** e botão "Criar rascunho da competência" em Indicadores. Doc: `docs/SNAPSHOTS.md`.

## 2. Entidades e migration
`0004_snapshots`: `competences`, `competence_revisions`, `metric_snapshots`, `manual_changes`, `approvals`, `audit_events`, `collection_runs` + view `v_official_revisions` (referência da série = aprovação mais recente; sem tabela redundante). Gatilhos: revisão nasce DRAFT, transições válidas, APPROVED imutável, snapshots só mudam em DRAFT, nada é excluído, tabelas de registro append-only. Downgrade recusado com aprovações (`AFRIKA_ALLOW_DESTRUCTIVE_DOWNGRADE=1`). Upgrade testado em banco F04.1 com dados.

## 3. Endpoints internos (loopback, sem autenticação)
`GET/POST /api/competences`, `POST /api/competences/from-run`, `GET /api/competences/{cid}`, `…/official`, `POST …/revisions`, `GET …/revisions/{n}`, `POST …/revisions/{n}/import-run`, `PUT …/metrics/{metric_id}`, `POST …/metrics/{metric_id}/revert`, `PUT …/required`, `POST …/submit|return|approve`, `GET …/compare?a&b`, `GET …/audit`, `GET …/integrity`, `GET /api/history/{kind}/{id}/series`, `GET /api/history/{kind}/{id}/compare`, `GET /api/reporting/status`, `POST/GET /api/reporting/jobs`, `GET /api/reporting/jobs/{id}`, `POST …/cancel`.

## 4. Contrato do snapshot
Dono/competência (via revisão); `metric_id`, `contract_version`, `value_type`, `shape`, `unit`; valor efetivo (`NULL` ≠ `0`) + `origin` VERACODE/MANUAL; fonte preservada (`source_status` técnico, valor, parcial, motivos, fonte, endpoint, contexto Policy/Sandbox, `collected_at`, intervalo local/UTC); `dashboard_homologation` separado (nunca promovido); escopos (versão + `rule_hash`); proveniência (`run_id`, engine, `input_hash`, conexão sem credencial); manual (justificativa, operador, UTC); `row_hash`. Estados exibidos: VALIDATED, MANUAL, INCOMPLETE, SOURCE_UNAVAILABLE, UNSUPPORTED, MISSING. Sem findings individuais nem respostas HTTP.

## 5. Aprovação e revisão
Bloqueia: obrigatórios vazio/sem valor, valor inválido, hash divergente, fora de READY_FOR_REVIEW, `lock_version` divergente, sem aprovador. Aceita manuais justificados. Aprovação grava `content_hash` + `chain_hash` (encadeado à anterior). Toda alteração exige `expected_lock_version` + UPDATE condicional ⇒ 409 (4 threads: 1 sucesso, 3 conflitos). **Aprovador/operador são declarados (`DECLARED_UNAUTHENTICATED`), não identidade autenticada.** Obrigatórios: sem template oficial não há lista padrão — seleção explícita por revisão, versionada.

## 6. Histórico e preenchimento manual
Só aprovados; lacuna = `GAP` (sem zero, sem interpolação); fim padrão = último mês fechado no fuso do cliente; avisos de mudança de tipo/versão de contrato; delta só entre aprovados comparáveis. Setembro aprovado continua igual após a Veracode mudar (testado). Lacuna é preenchida criando a competência, valor manual justificado e aprovação (auditado).

## 7. Reporting API — status
| Estado | F05 |
|---|---|
| Adaptador implementado | **sim** (`backend/app/veracode/reporting.py`, `reporting_policy.py`) |
| Testado com mocks | **sim** (22 testes + E2E fixture) |
| Geração real confirmada | **não** — 1 POST real (FINDINGS, 1 aplicação, 7 dias): **HTTP 403** (HMAC aceito; papel *Reporting API*/habilitação ausentes) ⇒ **BLOCKED_EXTERNAL**; sem retry; nenhuma outra chamada à Reporting API |
| Métrica homologada contra dashboard | **não** (NOT_RUN); agregados são exploratórios e fora do catálogo |
Fluxo conferido na spec oficial 1.12.0: POST ⇒ `_embedded.id`/`status`; GET `…/report/{id}?page=N` ⇒ status QUEUED/SUBMITTED/PROCESSING/COMPLETED/FAILED, `findings[]`/`scans[]`, `page_metadata`; obrigatórios `report_type` + `last_updated_start_date`; máx. 6 meses; itens em EDT. DELETEDSCANS e AUDIT estudados, não habilitados (AUDIT contém dados pessoais).

## 8. Endpoints e métodos Veracode permitidos
Todos os GET anteriores + `GET /appsec/v1/analytics/report/{uuid}`; **único POST**: `POST /appsec/v1/analytics/report`, só com `AFRIKA_VERACODE_REPORTING_ENABLED=true` (padrão false), caminho exato, sem query, JSON revalidado no transporte (FINDINGS/SCANS, campos/enums da spec, janela ≤ 31 dias configurável, teto 6 meses). Todo outro POST/PUT/PATCH/DELETE bloqueado antes da rede (testado com geração habilitada). Teste real exige ainda `VERACODE_REPORTING_LIVE_ENABLED=true`.

## 9. Testes
| Verificação | Resultado |
|---|---|
| `python -m pytest -q` | **PASS 411** (329 + 82: snapshots 19, histórico 6, valores 33, reporting 22, migrations +2) |
| E2E Chromium (`npm run test:e2e`) | **PASS 22/22** (19 + 3 F05) em 3 de 4 rodadas completas; 1 rodada com falha intermitente em `scopes.spec.ts` (F03, sem alteração; passou isolado e nas demais) |
| build; `npm audit` (prod e dev); `pip check` | OK; 0 vulnerabilidades; OK |
| gitleaks staged; `dir` | 0; 3 achados só em arquivos ignorados (`.env` local e 2 falsos positivos no `.venv`) |
| `check_repo`; `check_env_example` | OK (F05); SEGURO |
| migrations CLI (migrate, db-status, seed, migrate) em banco novo | OK (`0004_snapshots`) |
| `tests_live` sem opt-in | 20 SKIPPED |
| Real opt-in `test_reporting_live.py` | SKIPPED com `BLOCKED_EXTERNAL` (403) — 1 POST; 1ª tentativa falhou antes do POST (campo `legacy_id`), corrigida |
| venv novo pelo lock | NOT_RUN (nenhuma dependência nova) |
Cobertura dos 27 itens da ordem: 1 restart, 2 rascunho, 3 subcliente, 4 competência/fuso, 5 zero×ausência, 6 manual tipado, 7 justificativa, 8 integridade/adulteração, 9 imutabilidade (gatilhos), 10 revisões, 11 auditoria/cadeia, 12–13 6/12 meses e lacunas, 14 reutilização exata, 15 concorrência, 16 banco existente, 17 FKs, 18 sem credenciais, 19 E2E API + Playwright, 20 regressão, 21–22 bloqueios/allowlist, 23 polling/limite/prazo, 24 429/403/5xx, 25 cancelamento, 26 logs, 27 opt-in.

## 10. Evidências de segurança
Gatilhos de imutabilidade testados com SQL direto; adulteração de snapshot e de auditoria detectada; nenhuma credencial/`credential_ref` nas tabelas F05 nem nas respostas E2E; logs em DEBUG sem chaves, corpo, datas do pedido, id do relatório ou conteúdo de itens; itens da Reporting minimizados (descartados descrição, arquivos, usuários, comentários, solicitante); nada de findings persistido nem enviado a IA; E2E sem requisições externas.

## 11. CI
Run `38746312757` (SHA `ad4b91f`): **success** — Backend (Python 3.11) success, Backend (Python 3.14) success, Frontend (typecheck + build) success, E2E (Playwright Chromium) success.

## 12. Commits e push
`ad4b91f` (implementação) + commit de checkpoint (STATUS/handoff). Push em `origin/main`.

## 13. Limitações e pendências para F06
1. Identidade declarada (sem autenticação/assinatura); hashes detectam, não impedem adulteração por quem tem o arquivo SQLite.
2. Reporting API: pedir à Veracode habilitação + papel *Reporting API* na conta de testes e repetir UMA geração mínima; só depois criar contratos (ex.: resolvidos no mês, scans no período) com testes e homologação.
3. Execuções F04 vivem em memória: importar na mesma sessão do backend.
4. Sem template oficial: obrigatórios são escolhidos manualmente por revisão; F06 deve definir o conjunto por template/slide.
5. Snapshots guardam dimensões com nomes de aplicações/BUs/Teams (necessárias aos slides) no banco local.
6. Teste E2E `scopes.spec.ts` intermitente (1/4) — investigar se persistir.
7. Comparação contra dashboard segue NOT_RUN para todos os indicadores.

**Prompt sugerido para F06 (não executado):** "F06 — Catalogar o template oficial de slides aprovado pelo PO (sem commitar PPTX real), mapear cada bloco a `metric_id` + versão de contrato, definir o conjunto obrigatório por template a partir disso, consumir SOMENTE revisões aprovadas (`/api/competences/{cid}/official` e `/api/history`), exibir lacunas e valores manuais como tais, e montar a engine de slides com diff de imagem por slide; sem exportação final (F07)."

---

## Versão compacta para o PO
F05 concluída localmente (`ad4b91f`, CI verde run `38746312757`). Snapshots persistentes por competência (migration 0004, gatilhos de imutabilidade), ciclo DRAFT→REVIEW→APPROVED com lock otimista, aprovador declarado (não autenticado), obrigatórios explícitos, valores manuais tipados/justificados com fonte Veracode preservada, aprovações e auditoria append-only com hash encadeado, histórico 6/12 meses/intervalo só de aprovados com lacunas explícitas. Reporting API: adaptador FINDINGS/SCANS deny-by-default (único POST autorizado, desligado por padrão) testado em mock; **geração real: 1 POST ⇒ HTTP 403 (papel/habilitação ausentes) — BLOCKED_EXTERNAL**. Testes: pytest 411 PASS, E2E 22 PASS (1 intermitência em F03), build/audit/pip/gitleaks OK. Pendência principal: habilitar Reporting API na Veracode; F06 aguardando ordem.
