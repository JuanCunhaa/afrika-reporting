# ORDEM DO PO — F10: Conciliação Veracode e Piloto Operacional

**Projeto:** Afrika Reporting
**Fase anterior:** F09 aprovada como homologação funcional
**Fase atual:** F10
**Produção:** NÃO AUTORIZADA

## Objetivo
Preparar o Afrika Reporting para seu primeiro piloto operacional assistido, priorizando a exatidão dos indicadores da
Veracode, a segurança dos dados e a qualidade do template reutilizável. Não iniciar deploy público, novas
funcionalidades de IA ou refatorações amplas.

## 1. Preparação
Ler CLAUDE.md, as skills pertinentes e `docs/AGENT_HANDOFF.md`, `docs/F09_ACCEPTANCE_MATRIX.md`,
`docs/F09_METRIC_RECONCILIATION.md`, `docs/F09_SECURITY_REVIEW.md`, `docs/F09_RELEASE_READINESS.md`,
`docs/API_SOURCE_MATRIX.md`. Inspecionar somente os módulos necessários. Preservar F00–F09.

## 2. Conciliação de indicadores
Para cada indicador aplicável da matriz de 35: definição exata, fonte Veracode, endpoint e filtros, Policy × Sandbox,
escopo e competência, mitigação/severidade/deduplicação, comparação do agregado com o valor oficial equivalente
(quando acessível), evidências e divergências. Não comparar períodos/filtros diferentes; não confundir estado atual com
fechamento histórico; não declarar homologação sem correspondência comprovada. NOT_APPLICABLE separado de bloqueados
e de não verificados.

## 3. Conferência no dashboard
Investigar o que pode ser conferido automaticamente por APIs oficiais. Sem acesso ao dashboard: fluxo simples de
conferência humana (indicador, valor calculado, caminho na Veracode, filtros, campo do valor oficial, diferença
automática, status, evidência local e data). O operador confere todos os aplicáveis sem editar código ou banco. Sem
endpoints internos, cookies ou automações que contornem permissões.

## 4. SCA e Reporting API
SCA: investigar falhas de transporte e completude, reaproveitar adaptadores, comparar alternativas oficiais, não
inventar valores. Reporting: preservar o adaptador, não repetir POST real sem mudança de autorização comprovada,
registrar quais indicadores se beneficiariam. Sem integrações especulativas.

## 5. Template reutilizável
Revisar `afrika@2` e `afrika-modelo@2` sem alterar versões imutáveis; nova versão só se necessária. Remover nomes de
clientes, dados históricos, valores fixos, recomendações de outros clientes e informação confidencial; preservar
layouts. Não modificar o PPTX em `references/`. Template deve funcionar com cliente genérico e indicadores aprovados.

## 6. Piloto sintético integral
Ciclo mensal completo com dados sintéticos (cliente/subcliente, escopos, coleta, competência, snapshots, aprovação,
histórico, apresentação, interpretação, PPTX e PDF), com consistência dos valores do início ao fim. Sintético nunca
apresentado como real.

## 7. Segurança do piloto
Exclusivamente local: backend em localhost, isolamento de clientes, sem credenciais em logs, `private/` fora do Git,
backups do SQLite com restauração testada, segurança dos exportados, nada confidencial no repositório, IA externa
desativada. Sem hospedagem pública.

## 8. Critérios de aceite
Classificar separadamente: funcionalidade, integração Veracode, correspondência dos indicadores, completude SCA,
qualidade visual, segurança do piloto, prontidão operacional, prontidão para produção — com PASS, FAIL,
BLOCKED_EXTERNAL, NOT_VERIFIED e NOT_APPLICABLE. Não mascarar divergências entre dashboard e API.

## 9. Testes e GitHub
Backend, exportação, E2E, regressão visual, npm audit, pip check, gitleaks, check_repo, migrations. Corrigir só
defeitos comprovados. Commit/push só de arquivos seguros. Acompanhar o CI estrito.

## 10. Entregáveis
`docs/F10_METRIC_RECONCILIATION.md`, `docs/F10_PILOT_VALIDATION.md`, `docs/F10_OPEN_ISSUES.md`, `docs/STATUS.md`,
`docs/AGENT_HANDOFF.md`. Não declarar prontidão para produção. Não iniciar F11. Aguardar aprovação do PO.
