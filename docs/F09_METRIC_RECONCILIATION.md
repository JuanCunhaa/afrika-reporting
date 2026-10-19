# F09 — Conciliação dos indicadores com a plataforma Veracode

Data da coleta real: 2026-10-19 (tenant **de testes** autorizado, região `commercial`, somente GET).
Competência pedida: `2026-09` (fuso `America/Sao_Paulo`). Coleta pela pilha completa da aplicação
(`backend/tests_live/test_f09_live_flow.py`): API local → escopos → execução de métricas → rascunho de competência.

> **Valores reais NÃO estão neste arquivo** (repositório público). O valor coletado pelo Afrika Reporting de cada
> indicador, a identificação da amostra (nomes/GUIDs) e a planilha de conferência estão **somente** em
> `private/f09/live_flow.json` e `private/f09/CONFERENCIA_HUMANA.md` (pasta ignorada pelo Git, máquina local).

## 1. Resultado em uma linha
**0 indicador homologado contra o dashboard.** O dashboard da Veracode não é acessível a este agente (sem sessão de
interface; a API não expõe "o número do dashboard"). Toda comparação com o valor oficial é **NOT_VERIFIED** e depende
da conferência humana do §5. Nenhum número foi inventado ou estimado.

O que **foi** verificado com o tenant real:
- Formato, paginação e completude das fontes (aplicações 667 em 7 páginas; BUs, Teams, usuários, vínculos de Team).
- Coerência **entre fontes oficiais**: SAST Policy Findings API × Summary Report — 3/3 aplicações coincidentes na
  amostra de `test_metrics_live` (não substitui o dashboard).
- Status corretos: valor só com VALIDATED; INCOMPLETE/UNAVAILABLE/UNSUPPORTED sem valor (zero ≠ ausente).

## 2. Amostra e filtros
| Item | Cliente A | Cliente B |
|---|---|---|
| Escopo de aplicações | `application.id in [2 GUIDs]` (2 primeiras aplicações com scan concluído, ordem de GUID) | `application.id in [1 GUID]` (3ª aplicação) |
| Subcliente | 1 por BU da 1ª aplicação de A | — |
| Interseção A × B (prévia de escopos) | 0 | 0 |
| Competência / fuso | 2026-09 / America/Sao_Paulo (UTC 2026-09-01T03:00Z → 2026-10-01T03:00Z) | idem |
| `as_of` (estado atual) | data da coleta (2026-10-19) | idem |

Contexto: **Policy = produção**, **Sandbox = desenvolvimento** (convenção autorizada). "Aberto" = `OPEN` e mitigação
não aprovada (`OPEN_EXCLUDING_APPROVED_MITIGATIONS`). Severidade 0–5.

## 3. Matriz por indicador
Colunas fixas para todas as linhas: **Escopo** = amostra do §2; **Competência** = 2026-09; **Valor coletado** = ver
`private/f09/live_flow.json` (status abaixo); **Valor oficial no dashboard** = não observado; **Δ abs / Δ %** = não
calculável sem valor oficial. Temporal: **ATUAL** = estado na data da coleta (não é fechamento histórico); **EVENTO** =
filtro de data na competência; **FECHAMENTO** = estado no fim do mês.

| ID | Nome (resumo) | Fonte | Filtros / temporal | P/S | Status Afrika (A · B) | Comparação | Justificativa |
|---|---|---|---|---|---|---|---|
| apps.total | Aplicações no escopo | Applications 1.0 | ATUAL | — | VALIDATED · VALIDATED | NOT_VERIFIED | igual ao tamanho do escopo (2 · 1) — prova do escopo, não do dashboard |
| apps.by_business_unit | Aplicações por BU | Applications | ATUAL | — | VALIDATED · VALIDATED | NOT_VERIFIED | conferir filtro de BU no portfólio |
| apps.by_team | Aplicações por Team | Applications | ATUAL | — | VALIDATED · VALIDATED | NOT_VERIFIED | soma por Team ≥ total (multi-Team) |
| apps.without_team | Aplicações sem Team | Applications | ATUAL | — | VALIDATED · VALIDATED | NOT_VERIFIED | |
| apps.multiple_teams | Aplicações em >1 Team | Applications | ATUAL | — | VALIDATED · VALIDATED | NOT_VERIFIED | |
| apps.unclassified | Não classificadas em subcliente | Applications + escopos | ATUAL | — | VALIDATED · VALIDATED | NOT_APPLICABLE | conceito do Afrika (não existe no dashboard) |
| apps.by_policy_compliance | Conformidade de política | Applications `policies[]` | ATUAL | P | VALIDATED · VALIDATED | NOT_VERIFIED | conferir "Policy Compliance" por aplicação |
| apps.loc.total | Linhas de código | Summary Report | ATUAL (último build) | P | VALIDATED · VALIDATED | NOT_VERIFIED | |
| apps.total.at_period_end | Aplicações no fechamento | — | FECHAMENTO | — | UNAVAILABLE · UNAVAILABLE | NOT_APPLICABLE | estado histórico não reconstruível (snapshot aprovado/manual) |
| sast.policy.open.by_severity | SAST aberto por severidade | Findings 2.1 `scan_type=STATIC` | ATUAL | P | VALIDATED · VALIDATED | NOT_VERIFIED | Findings × Summary coincidiram (3/3); dashboard não observado |
| sast.sandbox.open.by_severity | SAST aberto (ocorrências por sandbox) | Findings `context` | ATUAL | S | VALIDATED · VALIDATED | NOT_VERIFIED | ocorrências, não distintos |
| sast.sandbox.open.distinct | SAST distintos em sandboxes | Findings | ATUAL | S | INCOMPLETE · INCOMPLETE | NOT_APPLICABLE | identidade de dedup entre contextos NOT_PROVEN (por contrato) |
| sast.open.distinct | SAST distintos P+S | Findings | ATUAL | P+S | INCOMPLETE · INCOMPLETE | NOT_APPLICABLE | idem |
| sast.policy.open.by_cwe | SAST por CWE (top 10) | Findings | ATUAL | P | VALIDATED · VALIDATED | NOT_VERIFIED | desempate não oficial |
| sast.policy.open.top_applications | Top aplicações SAST | Findings | ATUAL | P | VALIDATED · VALIDATED | NOT_VERIFIED | desempate não oficial |
| sast.policy.new_in_period.by_severity | SAST novos na competência | Findings `first_found_date` | EVENTO | P | VALIDATED · VALIDATED | NOT_VERIFIED | só findings ainda visíveis hoje |
| sast.policy.open.by_first_found_month | Envelhecimento por mês | Findings | ATUAL | P | VALIDATED · VALIDATED | NOT_VERIFIED | |
| sast.policy.summary.by_severity | SAST por severidade (Summary) | Summary Report v2 | ATUAL (último build) | P | VALIDATED · VALIDATED | NOT_VERIFIED | fonte alternativa |
| sast.policy.reconciliation | Findings × Summary | ambas | ATUAL | P | VALIDATED · VALIDATED | NOT_APPLICABLE | qualidade de dados (sem divergência na amostra) |
| sast.policy.open.at_period_end | SAST no fechamento | — | FECHAMENTO | P | UNAVAILABLE · UNAVAILABLE | NOT_APPLICABLE | estado histórico não reconstruível |
| sast.policy.resolved_in_period | SAST resolvidos | Reporting API (POST) | EVENTO | P | UNSUPPORTED · UNSUPPORTED | BLOCKED_EXTERNAL | Reporting API HTTP 403 (F05); POST não repetido |
| sca.policy.open.by_severity | SCA aberto por severidade | Findings `scan_type=SCA` | ATUAL | P | INCOMPLETE · INCOMPLETE | BLOCKED_EXTERNAL | falhas de transporte (timeout) na Findings SCA; sem valor |
| sca.sandbox.open.by_severity | SCA aberto em sandbox | Findings | ATUAL | S | INCOMPLETE · INCOMPLETE | BLOCKED_EXTERNAL | idem; suporte SUPPORT_NOT_VERIFIED |
| sca.open.distinct | SCA distintos | Findings | ATUAL | P+S | INCOMPLETE · INCOMPLETE | BLOCKED_EXTERNAL | coleta incompleta + identidade NOT_PROVEN |
| sca.policy.open.top_components | Top componentes | Findings | ATUAL | P | INCOMPLETE · INCOMPLETE | BLOCKED_EXTERNAL | coleta SCA incompleta |
| sca.policy.open.top_vulnerabilities | Top vulnerabilidades | Findings | ATUAL | P | INCOMPLETE · INCOMPLETE | BLOCKED_EXTERNAL | idem |
| sca.policy.open.by_dependency_mode | Direta × transitiva | Findings | ATUAL | P | INCOMPLETE · INCOMPLETE | BLOCKED_EXTERNAL | idem |
| sca.policy.summary.components | Componentes (Summary) | Summary Report | ATUAL (último build) | P | VALIDATED · VALIDATED | NOT_VERIFIED | |
| sca.agent.linked_projects | Projetos do agente vinculados | SCA Agent 3.0 | ATUAL | — | VALIDATED · VALIDATED | NOT_VERIFIED | |
| sca.policy.open.at_period_end | SCA no fechamento | — | FECHAMENTO | P | UNAVAILABLE · UNAVAILABLE | NOT_APPLICABLE | estado histórico não reconstruível |
| sca.policy.new_in_period | SCA novos | — | EVENTO | P | UNSUPPORTED · UNSUPPORTED | NOT_APPLICABLE | data ambígua na fonte (spec) |
| sca.agent.issues | Issues do agente | — | ATUAL | — | UNSUPPORTED · UNSUPPORTED | NOT_APPLICABLE | fora da allowlist |
| scans.count | Scans executados | Reporting API (POST) | EVENTO | P/S | UNSUPPORTED · UNSUPPORTED | BLOCKED_EXTERNAL | Reporting API HTTP 403 |
| scans.covered_apps | Aplicações com scan na competência | Applications `scans[]` | EVENTO | — | INCOMPLETE · INCOMPLETE | NOT_APPLICABLE | scan posterior ao período oculta o anterior (`later_scan_hides_period`) |
| licenses.usage | Uso de licenças | — | ATUAL | — | UNSUPPORTED · UNSUPPORTED | NOT_APPLICABLE | sem API; entrada manual justificada (F05) |

Totais (35 indicadores): VALIDATED 18 · INCOMPLETE 9 · UNAVAILABLE 3 · UNSUPPORTED 5 (iguais em A e B).
Comparação: **homologados 0** · NOT_VERIFIED 16 · BLOCKED_EXTERNAL 8 · NOT_APPLICABLE 11.

## 4. Divergências e observações
- **SCA (Findings API)**: na F04/F04.1 o bloqueio era HTTP 500; na F09 os pedidos SCA falharam por **transporte**
  (6 de 28 pedidos de findings sem resposta; `upstream_status` ausente; o cliente HTTP já fez as tentativas
  configuradas). Resultado: SCA INCOMPLETE sem valor — comportamento correto. A passada adiada só cobre HTTP 500 (por
  desenho), não timeouts. Nenhum HTTP 500 observado na F09: o tratamento de 500 segue verificado em mock
  (`test_metrics_sources.py`, F09 etapa 7) e em real na F04.1.
- **Estado atual × fechamento**: os indicadores ATUAL refletem 2026-10-19, não 30/09. Não comparar com relatórios
  históricos do dashboard; o fechamento oficial é o snapshot APROVADO da competência (ou entrada manual justificada).

## 5. Roteiro de conferência humana (objetivo, ≈20 min)
Pré-requisito: acesso de leitura ao portal do tenant de testes **no mesmo dia** de uma nova coleta (estado atual muda).
1. Rodar a coleta (opt-in, só GET): `VERACODE_LIVE_TESTS_ENABLED=true python -m pytest
   backend/tests_live/test_f09_live_flow.py -q -s -rs --run-veracode-live` (a partir de `backend/`). Gera
   `private/f09/live_flow.json` e a planilha `private/f09/CONFERENCIA_HUMANA.md`.
2. Para cada aplicação da amostra (lista privada), no portal: **Application Profile → Policy scan → Findings**,
   filtro *Open* (excluir mitigações aprovadas), agrupar por severidade. Anotar Very High…Informational.
3. Somar por cliente (A = 2 aplicações; B = 1) e comparar com `sast.policy.open.by_severity`.
4. Mesma aplicação, **Summary/Overview**: LOC (`apps.loc.total`), *Policy Compliance* (`apps.by_policy_compliance`).
5. Sandboxes: para cada sandbox, findings abertos por severidade → `sast.sandbox.open.by_severity` (soma de
   ocorrências).
6. Findings com *First Found* em 09/2026 (fuso de São Paulo) ainda visíveis → `sast.policy.new_in_period.by_severity`.
7. SCA: só se a coleta SCA ficar VALIDATED (hoje INCOMPLETE).
8. Registrar na planilha privada: valor oficial, Δ absoluto, Δ %, status (MATCH / MISMATCH / NOT_COMPARABLE) e
   justificativa. **Divergência = investigação da nossa consulta**, nunca "correção" do dashboard.
9. Devolver ao PO só os status e as diferenças; valores e nomes ficam fora do repositório.

Critério para "homologado": mesmo filtro, mesma data e Δ = 0 (ou diferença explicada pela definição documentada).
