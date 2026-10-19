# Devolutiva Claude → ChatGPT PO — F10: Conciliação Veracode e Piloto Operacional (2026-10-19)

- **Fase / commits:** F10 / `main` / **`5f52ff8`** (código + testes + docs) → commit de checkpoint (STATUS/handoff).
  **Nenhuma fase nova iniciada. Produção NÃO autorizada nem declarada.**
- **CI:** run `39301551936` (SHA `5f52ff8`, estrito) — **success** (§8).
- Modelo: Opus 5.5 (ambiente). Nenhum subagente. Nenhuma dependência nova.
- Veracode real: tenant de testes, **somente GET (68)**: diagnóstico SCA 31 + recoleta de métricas 37. **0 POST**
  (Reporting API não repetida: sem mudança de permissão). Nenhuma chamada a provedor externo de IA.

## 1. Indicadores efetivamente homologados
**0 de 35** contra o dashboard (o agente não acessa o portal; nenhum número inventado). A F10 entrega o fluxo para o
operador homologar: 21 aplicáveis **NOT_VERIFIED** (com valor), 12 **NOT_APPLICABLE**, 2 **BLOCKED_EXTERNAL**.
Coerência entre fontes oficiais (não é dashboard): SAST Policy Findings × Summary Report 3/3.
Detalhe por indicador (definição, fonte, endpoint/filtros, P/S, temporal, dedup): `docs/F10_METRIC_RECONCILIATION.md`.

## 2. Indicadores bloqueados e motivos
- **BLOCKED_EXTERNAL (2):** `sast.policy.resolved_in_period`, `scans.count` — Reporting API HTTP 403 (papel/habilitação
  na conta de testes).
- **NOT_APPLICABLE (12, separados dos bloqueados):** distintos ×3 (identidade de dedup não comprovada), fechamento ×3
  (estado histórico não reconstruível — só snapshot aprovado/manual), `apps.unclassified` e `sast.policy.reconciliation`
  (conceitos próprios), `sca.policy.new_in_period` (data ambígua), `sca.agent.issues` (fora da allowlist),
  `scans.covered_apps` (só o último scan é visível), `licenses.usage` (sem API).
- **Saíram do bloqueio:** SCA ×5 (eram BLOCKED_EXTERNAL na F09) — ver §3.

## 3. Correções implementadas (defeitos comprovados)
1. **SCA incompleto era defeito NOSSO, não transporte.** Diagnóstico real (só GET): findings SCA reais **não têm
   `issue_id`**; o paginador exigia o campo e rejeitava a página 200 (`invalid_response`, sem status HTTP). As 6 falhas
   `-1` da F09 tinham sido recuperadas por retry. Correção: SCA pagina sem identificador por item, com completude
   provada por `total_elements` (sem metadados ⇒ recusa); STATIC inalterado. Fixture passa a reproduzir o formato real;
   metadado de dedup dos 5 contratos SCA de contexto único corrigido para `NONE` (fórmula/valor inalterados ⇒ `version`
   mantida — **decisão para o PO**, pendência 5). Real pós-correção: 18/18 contextos completos; SCA VALIDATED.
2. **Teste instável** `test_interpretation.py::test_confidentiality…`: procurava `'30'` em logs com UUIDs aleatórios
   (falso positivo ≈11%); UUIDs agora são mascarados antes da busca (instrumento, não produto).

Funcionalidades pedidas pela ordem (não são correções): **conferência humana** (migration `0008_metric_conferences`,
`backend/app/reconciliation/`, `api_reconciliation.py`, página `ConferencePage.tsx`, CSV) e **backup/restauração do
SQLite** (`backend/app/backup.py`, `python -m app.cli backup-db | restore-db`).

## 4. Estado do template reutilizável
`afrika-modelo@2` + `afrika@2` revisados: só estrutura, títulos genéricos, placeholders editoriais e `metric_id`; **sem
nome de cliente, dado histórico, valor fixo, recomendação de outro cliente ou informação confidencial** ⇒ **nenhuma nova
versão criada** (versões imutáveis intactas). Novo teste `test_f10_template_reusable.py` fixa isso. Funciona com cliente
genérico e com subcliente herdando o modelo (piloto 6/6b). PPTX de `references/` **não tocado** (SHA-256 igual antes e
depois). Ressalvas herdadas: tema PROVISÓRIO, ativos de marca ausentes, fontes em outro computador NOT_VERIFIED.

## 5. Resultado do piloto
Ciclo mensal sintético integral **12/12 PASS** (`backend/tests/test_f10_pilot.py`): cliente+subcliente → escopos →
coleta → snapshots (35 = coleta) → conferência contra **oráculo independente** (5 MATCH) → aprovação → histórico (mês
anterior aprovado) → apresentação `afrika-modelo@2` (todos os pontos = snapshot aprovado; subcliente só com os próprios
números) → interpretação local revisada → PPTX/PDF (números nos gráficos nativos, texto no PDF) → backup/restauração
(hashes de integridade idênticos; reexportação com o mesmo SHA-256). Detalhe: `docs/F10_PILOT_VALIDATION.md` §2.

## 6. Evidências de segurança
`docs/F10_PILOT_VALIDATION.md` §3 — todos PASS no uso local: localhost-only, isolamento, sem credenciais em logs/SQLite,
`private/` e `data/` ignorados, backup com restauração testada (recusa pasta versionável, sem `--confirm` e arquivo
corrompido; salva o banco atual antes), exportados com `nosniff`/`no-store`/SHA-256, 0 identificador real em 403
arquivos, IA externa desligada. **Backend sem autenticação: não expor.** Backups não criptografados.

## 7. Testes executados
| Verificação | Resultado |
|---|---|
| pytest completo (Py 3.14.7, local) | **PASS — 711 passed** (679 anteriores + 32 novos: SCA 7, conferência 11, piloto 12, template 2) |
| Exportação obrigatória (`AFRIKA_EXPORT_TESTS=required`, local) | **PASS — 105 passed** (82 + piloto 12 + conferência 11) |
| Piloto F10 isolado (exportação obrigatória) | **PASS — 12/12** |
| E2E da conferência (`conference.spec.ts`, local) | **PASS — 1 passed** |
| E2E Chromium completo + regressão visual (local) | **NOT_RUN** — a execução foi **interrompida pelo sistema por falta de memória** na máquina (não é falha do teste); não reiniciada sem ordem. No CI: **41 passed + 3 skipped**, regressão visual Linux sem diferença |
| Build frontend + typecheck | **PASS** (local e CI) |
| Real opt-in: `test_f10_sca_diagnostics.py` | **PASS** (31 GET, 0 retry; saída só em `private/f10/`) |
| Real opt-in: `test_metrics_live.py` pós-correção | **PASS** (37 GET; 18/18 contextos completos; Findings × Summary 3/3) |
| `npm audit` / `pip check` | **PASS** (0 vulnerabilidades / OK) |
| Gitleaks | **PASS** — 15 arquivos novos 0; staged do commit 0 |
| Identificadores reais no repo | **PASS** — 8 da amostra × 403 arquivos rastreados/novos = 0 |
| `check_repo` / `check_env_example` | **PASS** (Estrutura F10 / SEGURO) |
| Migrations CLI (banco novo: migrate, db-status, seed-demo, migrate, seed-demo) | **PASS** (`0008`, idempotente) |
| Backup/restauração CLI (smoke em banco temporário) | **PASS** (integrity ok; sem `--confirm` recusado; destino `docs/` recusado) |
| PPTX de `references/` | **PASS** — SHA-256 igual antes/depois, não rastreado |
| Fidelidade HTML×PPTX×PDF com PowerPoint (`export-fidelity.spec.ts`) | **NOT_RUN** nesta fase (motor de exportação inalterado; parte do E2E local interrompido) |

## 8. Commits e CI
`5f52ff8` (F10) e commit de checkpoint (STATUS/handoff) — em `origin/main`. CI run `39301551936` (SHA `5f52ff8`,
estrito) — **success**: Backend 3.11 e 3.14 **682 passed + 29 skipped** cada (motor real fica no job próprio);
**Exportação PPTX/PDF** obrigatória **94 passed** (82 + piloto 12); Frontend typecheck + build + motor visual; **E2E
Chromium 41 passed + 3 skipped** com regressão visual Linux (sem referência nova).

## 9. Ações que dependem exclusivamente do operador
1. Conferir os 21 indicadores aplicáveis no portal (página *Conferir com a Veracode*, no mesmo dia da coleta) e devolver
   ao PO só status/Δ. 2. Guardar capturas e CSV de conferência em `private/`. 3. `backup-db` antes de aprovar e ao fim do
   ciclo. 4. Preencher lacunas manualmente com justificativa. 5. Ajustar, se preciso, os caminhos indicativos do guia.

## 10. Recomendação de prontidão operacional
**Piloto local assistido: apto**, condicionado a (a) conferência humana registrada antes de usar números fora da
equipe — só MATCH sobre valor Veracode conta como conferido; (b) uma estação, `127.0.0.1`; (c) backups locais.
**Prontidão para produção: NÃO** (sem autenticação/segregação, 0 indicador homologado, Reporting bloqueada, SQLite sem
criptografia).

## 11. Pendências para o PO
`docs/F10_OPEN_ISSUES.md` (12 itens). Decisões: versão do contrato SCA (pendência 5); pedido de papel da Reporting API;
autenticação local numa fase futura; ativos de marca/template oficial; IA externa.

## 12. Prompt sugerido para a próxima fase (NÃO executado)
> **F11 — Homologação assistida dos indicadores e autenticação local (somente com ordem do PO).** Ler `CLAUDE.md`,
> `docs/STATUS.md`, `docs/F10_METRIC_RECONCILIATION.md`, `docs/F10_OPEN_ISSUES.md`. (a) A partir das conferências
> registradas pelo operador (status/Δ, sem valores reais no repo), investigar cada MISMATCH na nossa consulta e
> corrigir só defeitos comprovados; (b) se o PO decidir, criar `version` 2 dos contratos SCA e novas versões de
> template que a aceitem; (c) desenhar autenticação local com segregação operador × aprovador × conferente sem quebrar
> o fluxo; (d) Reporting API só após mudança de permissão confirmada. Sem deploy público e sem IA externa.
