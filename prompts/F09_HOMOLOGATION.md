# ORDEM DO PO — F09: Homologação Ponta a Ponta do Afrika Reporting

**Status:** F08 aprovada.
**Objetivo:** validar o produto completo antes de sua utilização operacional.
**Próximas fases:** não autorizadas.

Execute exclusivamente a F09. Não desenvolva novas funcionalidades desnecessárias.

## 1. Preparação
Leia CLAUDE.md, as skills pertinentes, docs/AGENT_HANDOFF.md, docs/STATUS.md e os contratos de integração, métricas,
snapshots, apresentações e exportação. Inspecione o código e os testes existentes antes de propor alterações. Utilize
o ambiente local, banco de testes e credenciais já configurados. Não recrie o projeto nem refatore componentes
estáveis sem defeito comprovado.

## 2. Fluxo completo sintético
Homologue, usando dados exclusivamente sintéticos: 1. Cadastro de cliente. 2. Cadastro de subclientes. 3. Conexão
herdada e independente. 4. Criação de escopos. 5. Seleção de aplicações e usuários. 6. Coleta simulada de indicadores.
7. Tratamento de indisponibilidade e incompletude. 8. Criação de competência. 9. Snapshot persistente. 10. Preenchimento
manual justificado. 11. Aprovação da competência. 12. Recuperação de histórico aprovado. 13. Seleção do template
Afrika. 14. Criação da apresentação. 15. Edição de slides. 16. Geração de interpretação local. 17. Validação e
aprovação humana da interpretação. 18. Aplicação do texto aos slides. 19. Exportação PPTX. 20. Exportação PDF.
21. Download dos dois formatos. 22. Reabertura do sistema sem perda dos dados persistidos.
Não presumir sucesso de uma etapa: produzir evidências automatizadas.

## 3. Homologação real Veracode
Utilize somente o tenant autorizado de testes. Permissões: GET nos endpoints oficiais permitidos; POST apenas na
operação de geração de relatórios da Reporting API, se houver autorização e habilitação efetivas. É proibido modificar
aplicações, políticas, findings, usuários, Teams, BUs, configurações ou executar scans. Não repetir o POST da Reporting
API enquanto persistir o bloqueio 403 sem alteração confirmada de permissão. Realizar consultas pequenas e
controladas. Validar: inventário de aplicações, Business Units, Teams, usuários, escopos, Summary Report, findings
SAST, findings SCA (se disponível), completude e paginação, tratamento dos HTTP 500, isolamento entre clientes. Não
persistir findings reais em fixtures ou commits.

## 4. Conferência de indicadores com a plataforma
Matriz por indicador: ID, nome, fonte, escopo, competência, filtros, contexto Policy/Sandbox, valor coletado, valor
oficial observado no dashboard, diferença absoluta e percentual, status de comparação, justificativa. Comparar só
valores com filtros, datas e definições equivalentes. Não presumir que métricas de estado atual representam
fechamento histórico. Não declarar homologado sem evidência do valor oficial. Dashboard inacessível ⇒ NOT_VERIFIED e
roteiro objetivo para conferência humana. Não inventar números.

## 5. Segurança e isolamento
Verificar: nenhuma credencial em respostas, logs ou Git; nenhum dado real versionado; nenhuma operação Veracode não
autorizada; isolamento entre clientes e subclientes; controle de escopos; integridade dos snapshots; imutabilidade de
versões aprovadas; revisões auditáveis; segurança da exportação; ausência de acesso público não autenticado;
provedores externos de IA desabilitados por padrão. Registrar que o backend ainda não possui autenticação real de
usuários e não deve ser exposto publicamente.

## 6. PowerPoint e PDF
Validar os modelos Afrika e neutro: slides em ordem, indicadores aprovados, textos editáveis, formas nativas, tabelas
nativas, gráficos com planilhas incorporadas, lacunas preservadas, HTML × PPTX × PDF, fontes, overflow, download,
integridade dos arquivos. NOT_VERIFIED para o que depender de testes indisponíveis em outros computadores.

## 7. Interpretação
Com dados sintéticos: texto executivo, texto técnico, validação numérica, ausência de causas inventadas, aprovação
humana, rejeição, regeneração, aplicação ao slide, bloqueio de interpretações desatualizadas, exportação sem chamadas
de IA. Não enviar dados reais a provedores externos.

## 8. Testes de estabilidade
pytest completo, E2E Chromium, exportação real, regressão visual, migrations, build frontend, npm audit, pip check,
Gitleaks, check_repo, verificação de dependências, testes de persistência e reinicialização. Investigar falhas
intermitentes anteriores. Não mascarar falhas com retries indiscriminados. Evitar processos pesados simultâneos no
Windows.

## 9. Correções permitidas
Corrigir defeitos comprovados: evidência do problema, ajuste mínimo, teste de regressão, testes afetados, resultado
documentado. Sem funcionalidades novas desnecessárias.

## 10. Critérios de classificação
PASS, FAIL, BLOCKED_EXTERNAL, NOT_VERIFIED, NOT_APPLICABLE. Não transformar bloqueios externos em sucesso. Não declarar
prontidão para produção com ausência de autenticação, indicadores importantes não homologados ou outras limitações
críticas. Distinguir: homologação funcional, de integração, dos indicadores, visual; prontidão operacional; prontidão
para produção.

## 11. Entregáveis
Criar `docs/F09_ACCEPTANCE_MATRIX.md`, `docs/F09_METRIC_RECONCILIATION.md`, `docs/F09_SECURITY_REVIEW.md`,
`docs/F09_RELEASE_READINESS.md`; atualizar `docs/STATUS.md` e `docs/AGENT_HANDOFF.md`. Entregar ao PO: resultado do
fluxo, critérios aprovados, bloqueados, indicadores homologados e não homologados, evidências de exportação,
segurança, limitações operacionais, testes, commits e CI, recomendação fundamentada de aceite. Commit e push só após
validação dos arquivos seguros e aprovação dos testes obrigatórios; acompanhar o CI estrito até concluir.
**Não iniciar novas fases. Aguardar o aceite do PO.**
