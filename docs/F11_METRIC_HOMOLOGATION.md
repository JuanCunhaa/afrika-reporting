# F11 — Homologação de métricas com a plataforma Veracode (2026-10-19)

Base: `docs/F10_METRIC_RECONCILIATION.md` (matriz dos 35 indicadores), motor de conferência da F10
(`backend/app/reconciliation/`) — **reutilizado e estendido, sem segundo motor**. Execução real nesta fase: tenant de
testes, **somente GET (26)**, 0 POST. Valores reais só em `private/f11/` (ignorado pelo Git).

## 1. Resultado
**Indicadores homologados contra o dashboard: 0 de 21 aplicáveis (0 de 35).** O agente não tem acesso autorizado à
interface da Veracode (nenhuma ferramenta de navegador conectada nem autorização para usar a sessão do operador); não
foram usados endpoints internos, cookies ou automação de interface. Nenhum valor oficial foi observado, logo **nenhuma
divergência real** pôde ser medida e nenhum número foi alterado. Toda a preparação automatizável foi feita (§3); resta
ao operador **somente** ler o número na tela e digitá-lo.

## 2. Matriz de conciliação dos 21 aplicáveis
Valor calculado: lido pelo servidor do snapshot da revisão (nunca digitado). Valor observado, Δ absoluto/percentual,
status, evidência e data: registrados na página *Conferir com a Veracode* (F10) — append-only, com hash. Telas:
**indicativas** até o operador confirmá-las (o local real vai na evidência). Definições: documentação pública da
Veracode consultada em 2026-10-19 (`backend/app/reconciliation/official.py`, com links). Coluna "Doc." = a
documentação define o número (sim) ou não (não ⇒ conferir com cuidado; nada presumido).

| Pri. | Indicador | Tela (Platform) · alternativa Analytics | Filtros/contexto | Doc. | Observado / Δ / status |
|---|---|---|---|---|---|
| 1 | apps.total | Applications (lista) · Analytics → Applications | escopo do dono; mesma visibilidade de Teams | sim (perfil) | — / — / NOT_VERIFIED |
| 2 | apps.by_business_unit | Applications, filtro BU · dimensão Business Unit | escopo; BU por GUID | sim | — / — / NOT_VERIFIED |
| 2 | apps.by_team | Applications, filtro Team · dimensão Teams List | escopo; multi-Team conta em cada | sim | — / — / NOT_VERIFIED |
| 3 | apps.by_policy_compliance | Applications, Policy Compliance · Policy Compliance Status | só Policy | sim | — / — / NOT_VERIFIED |
| 4 | sast.policy.open.by_severity | Perfil → Policy scan → Findings (Static) · Findings, Policy, Open | Policy; aberto = OPEN sem mitigação aprovada; severidade 0–5 | sim | — / — / NOT_VERIFIED |
| 5 | sast.sandbox.open.by_severity | Perfil → Sandboxes → Findings · Findings, Sandbox, Open | cada sandbox; soma de ocorrências | sim | — / — / NOT_VERIFIED |
| 6 | sca.policy.open.by_severity | Perfil → SCA (Policy) | Policy; findings SCA (vulnerab. × componente) | sim | — / — / NOT_VERIFIED |
| 7 | sca.sandbox.open.by_severity | Perfil → Sandboxes → SCA | cada sandbox; soma | sim | — / — / NOT_VERIFIED |
| 8 | apps.loc.total | Perfil → último scan estático da Policy → Summary | Policy; build mais recente | **não** | — / — / NOT_VERIFIED |
| 9 | *Aplicações com scans* | — | — | — | **sem indicador aplicável** (§5) |
| — | apps.without_team | Applications sem Team · Teams List vazia | escopo; ausente ≠ vazio | não | — / — / NOT_VERIFIED |
| — | apps.multiple_teams | Applications com ≥ 2 Teams | escopo | não | — / — / NOT_VERIFIED |
| — | sast.policy.open.by_cwe | Findings por CWE · dimensão CWE ID | Policy; aberto | sim | — / — / NOT_VERIFIED |
| — | sast.policy.open.top_applications | Findings por aplicação | Policy; aberto | não | — / — / NOT_VERIFIED |
| — | sast.policy.new_in_period.by_severity | Findings, First Found Date na competência | Policy; qualquer status; fuso do cliente | sim | — / — / NOT_VERIFIED |
| — | sast.policy.open.by_first_found_month | Findings abertos por mês de First Found | Policy; fuso do cliente | sim | — / — / NOT_VERIFIED |
| — | sast.policy.summary.by_severity | Summary Report da Policy | build mais recente | não | — / — / NOT_VERIFIED |
| — | sca.policy.open.top_components | SCA → bibliotecas · dimensão Component Name | Policy; aberto | sim | — / — / NOT_VERIFIED |
| — | sca.policy.open.top_vulnerabilities | SCA → vulnerabilidades (CVE) | Policy; nº de aplicações | não | — / — / NOT_VERIFIED |
| — | sca.policy.open.by_dependency_mode | SCA, direta/transitiva | Policy; aberto | não | — / — / NOT_VERIFIED |
| — | sca.policy.summary.components | Summary Report → SCA | build mais recente | não | — / — / NOT_VERIFIED |
| — | sca.agent.linked_projects | Perfil → projetos do SCA Agent | escopo | não | — / — / NOT_VERIFIED |

NOT_APPLICABLE (12) e BLOCKED_EXTERNAL (2): inalterados em relação à F10 (motivos na própria planilha).

### Diferenças de definição já conhecidas (primeiros pontos a verificar em divergência)
- **Conformidade:** Analytics usa "Pass" e tem "Calculating..."; o filtro `policy_compliance` da API REST aceita só
  PASSED/DID_NOT_PASS/NOT_ASSESSED; sandbox também recebe Conditional Pass (o indicador é só Policy).
- **Teams:** "Teams List" do Analytics inclui *security lead teams*; o Afrika usa os Teams do perfil.
- **SAST:** Analytics recomenda "Count of Flaws Application" (findings únicos casados à política no contexto Policy);
  "Total Number of Flaws - Application" conta diferente. Custom Severity × severidade da Findings API. Mitigação
  proposta/rejeitada segue aberta no Afrika.
- **Novos no período:** o Afrika usa `first_found_date` por contexto; o Analytics recomenda "First Found in
  Application Date".
- **SCA:** o Afrika conta findings da Findings API (vulnerabilidade × componente, sem deduplicação); telas que contam
  bibliotecas ou CVEs distintos não são comparáveis. Componentes do Summary Report ≠ vulnerabilidades.
- **Visibilidade:** credencial de API e usuário do portal precisam enxergar os mesmos Teams.

## 3. Automação da conferência (o que o produto faz sozinho)
Na página *Conferir com a Veracode* (`#/conference/{competência}/{revisão}`), API e CSV:
- **Prioridades da ordem do PO** (tabela 1–9 com homologados por grupo; cartões e CSV ordenados por prioridade).
- **Definição oficial** com links da documentação, local alternativo no Analytics e diferenças conhecidas.
- Valor calculado do snapshot, local e filtros equivalentes, campo do valor oficial, Δ e Δ% em tempo real (prévia) e
  status do servidor (MATCH/MISMATCH/NOT_COMPARABLE), evidência, data e conferente (F10).
- **Diagnóstico automático** por indicador (ordem do PO §4), calculado só do que o snapshot guarda: universo de
  aplicações (escopo, versões, visíveis à credencial), BU/Teams/subclientes (indeterminados, campos ausentes),
  Policy/Sandbox (contexto, sandboxes, falha de listagem), competência/data/fuso (coleta × conferência), critério de
  aberto/mitigado (mitigações aprovadas excluídas), severidade (ausente), paginação e completude (contextos completos
  e novas tentativas), identidade/dedup (prova da identidade) e origem (manual não homologa). Em MISMATCH ou
  NOT_COMPARABLE o diagnóstico abre automaticamente com os pontos a investigar.
- CSV com as colunas novas `prioridade`, `definicao_oficial`, `local_analytics`, `diferencas_conhecidas`,
  `diagnostico_atencao` (sem fórmulas; guardar só em `private/`).

**Única tarefa do operador:** abrir cada tela no mesmo dia da coleta, aplicar os filtros indicados, digitar o número,
marcar "filtros conferidos", indicar onde salvou a captura e registrar. Ordem: prioridades 1 → 8.

## 4. Diagnóstico de divergências
Sem valor oficial observado, **não há divergência real a diagnosticar** nesta fase. Correções comprovadas na F11:
**nenhuma no cálculo** (nenhum defeito comprovado; nenhum número histórico alterado; nenhum snapshot aprovado tocado).
Procedimento para quando o operador registrar MISMATCH: seguir os itens ATTENTION do diagnóstico, depois as
diferenças conhecidas; só corrigir defeito comprovado na nossa consulta; se a definição do dashboard diferir da nossa,
documentar e propor contrato novo ao PO **antes** de alterar qualquer número.

## 5. Prioridade 9 — "Aplicações com scans" (proposta, NÃO implementada)
> **Superado na F12:** a ordem do PO definiu `apps.scanned` como scan publicado NA competência (não estado atual) e
> proibiu inferir pelo último scan; implementado sobre o relatório SCANS — ver `docs/F12_VERACODE_GAPS.md` §3.

`scans.covered_apps` continua NOT_APPLICABLE (scan publicado *dentro* da competência; o perfil só mostra o último).
O dashboard tem "Application Scanned (Yes/No): Determines if the application was scanned" (Applications explore), que
é estado ATUAL. Proposta de contrato novo para decisão do PO: `apps.scanned` v1 — aplicações do escopo com ao menos um
scan publicado (`last_completed_scan_date` presente na Applications API), estado ATUAL, dedup por GUID, sem
contexto; opcionalmente por tipo (STATIC/SCA) via `scans[]`. Criar exige decisão do PO (novo indicador no catálogo,
nos obrigatórios e nos templates).

## 6. SCA — validação da correção da F10 (real, só GET)
`backend/tests_live/test_f11_sca_completeness.py` (26 GET, 0 retry; 2 aplicações com componentes entre 8 candidatas;
Policy + 2 sandboxes cada = 6 contextos):
- **6/6 contextos completos**: itens recebidos = `total_elements`, páginas lidas = `total_pages` — inclusive **coleta
  multipágina** em Policy e sandboxes (antes só provada em mock).
- **Campo `count`** (pendência F10 nº 6): **= 1 em todos os findings observados** ⇒ Σ`count` = nº de findings; não
  explica diferença na amostra. Semântica oficial continua não documentada (monitorar se aparecer `count` > 1).
- Aplicação com componentes no Summary Report e **zero** findings SCA: zero **provado** pela paginação
  (`total_elements = 0`), não presumido.
- Componentes do Summary Report ≥ componentes vulneráveis distintos na Findings SCA (confirma: componentes ≠
  vulnerabilidades).

**Versão do contrato SCA:** mantida em **1** — semântica idêntica comprovada por teste
(`test_f11_homologation.py::test_sca_v1_semantics_identical_with_and_without_issue_id`): com findings únicos, a regra
antiga (identificador por item) e a nova (total anunciado) aceitam a coleta e produzem o mesmo valor por severidade;
só mudou a prova de completude, nunca a fórmula. Incompleto nunca vira zero (teste). Nomes nunca são identidade.

## 7. Reporting API — diagnóstico (POST NÃO repetido)
Evidência existente (F05): 1 POST real (FINDINGS, 1 aplicação, 7 dias) ⇒ **HTTP 403** com assinatura HMAC aceita (as
mesmas credenciais obtêm 200 nas APIs GET) ⇒ falta papel ou habilitação, não autenticação.
Requisitos documentados (docs.veracode.com, consultado em 2026-10-19):
1. **Habilitação da conta:** "To enable the Reporting API for your account" — pedido por e-mail ao suporte Veracode
   ([Reporting REST API](https://docs.veracode.com/r/Reporting_REST_API)).
2. **Papel:** conta de API (*API service account*) com o papel **Reporting API**, ou usuário de interface com
   **Executive, Security Lead ou Security Insights**; o papel "Reporting API User" "Must be combined with the Security
   Lead, Executive, or Security Insights UI user roles" ([API roles](https://docs.veracode.com/r/c_API_roles_details)).
3. **Limites:** Security Insights só vê dados dos próprios Teams; conta de API restrita a Teams vê só essas aplicações;
   no máximo 6 meses de dados por relatório.

Caminho de habilitação (feito pelo cliente/administrador — o agente não altera nada): (a) administrador da conta
Veracode confere, em *Admin → Users*, o tipo da conta usada pela credencial e seus papéis; (b) se faltar, concede o
papel Reporting API (conta de API) — decisão do cliente, mínimo privilégio; (c) pede ao suporte Veracode a habilitação
da Reporting API para a organização; (d) confirma ao PO por escrito; (e) só então o PO autoriza **um** POST de teste.
Diagnóstico adicional possível (proposta, não executado): ler os papéis da própria conta pelo GET documentado da
Identity API (`/api/authn/v2/users/self`) — exige incluir esse caminho na allowlist GET (decisão do PO).
