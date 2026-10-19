# ORDEM DO PO — F11: Homologação de Métricas e Piloto Assistido

**Projeto:** Afrika Reporting
**Fase anterior:** F10 aprovada
**Objetivo:** reconciliar indicadores com a Veracode e preparar um piloto real controlado.
**Produção:** NÃO autorizada.

Não iniciar F12.

## 1. Preparação

Leia CLAUDE.md, as skills pertinentes, docs/AGENT_HANDOFF.md, docs/F10_OPEN_ISSUES.md e os contratos de métricas e conciliação.

Reutilize o que já existe. Não desenvolva um segundo motor de relatórios.

Priorize testes, segurança e economia de tokens.

## 2. Homologação dos indicadores

Trabalhe sobre os 21 indicadores aplicáveis identificados na F10.

Para cada indicador:

- Identifique a tela exata da Veracode.
- Identifique filtros, período, contexto e escopo.
- Registre a definição oficial do indicador.
- Prepare o valor calculado pelo Afrika Reporting.
- Permita registrar o valor observado no dashboard.
- Calcule diferença absoluta e percentual.
- Determine correspondência ou divergência.
- Preserve a evidência e a data da comparação.

Não declarar HOMOLOGATED sem comparação real com o dashboard.

Priorize:
1. Total de aplicações.
2. Aplicações por BU e Team.
3. Conformidade de política.
4. SAST por severidade em produção.
5. SAST por severidade em desenvolvimento.
6. SCA por severidade em produção.
7. SCA por severidade em desenvolvimento.
8. Linhas de código.
9. Aplicações com scans.

## 3. Automação da conferência

Automatize toda a preparação possível.

Produza uma interface ou arquivo local de conferência que apresente:

- Indicador.
- Valor do Afrika Reporting.
- Localização do indicador no dashboard.
- Filtros equivalentes.
- Campo para valor oficial.
- Diferença.
- Status.

Se não houver acesso autorizado à interface da Veracode, deixe somente essa leitura manual para o operador.

Não solicitar ao usuário tarefas que o Claude consegue executar.

Não usar endpoints internos não documentados para contornar permissões.

## 4. Diagnóstico de divergências

Para qualquer diferença:

- Confirmar o mesmo universo de aplicações.
- Conferir BU, Teams e subclientes.
- Conferir Policy/Sandbox.
- Conferir competência e timezone.
- Conferir critérios de aberto, mitigado e resolvido.
- Conferir severidade original.
- Conferir paginação e completude.
- Conferir identidade e deduplicação.

Corrigir somente defeitos comprovados.

Se a definição do dashboard diferir da nossa, documentar o contrato e propor a correção antes de alterar números históricos.

Não modificar snapshots aprovados.

## 5. SCA

Validar a correção da F10.

Manter a versão 1 do contrato somente se sua semântica permanecer idêntica.

Verificar completude pelas informações oficiais de paginação e totais.

Não exigir issue_id quando a API não o fornece.

Não utilizar nomes como identificadores estáveis de findings.

Não tratar resultados incompletos como zero.

## 6. Reporting API

Não repetir o POST real enquanto o acesso continuar bloqueado.

Preparar diagnóstico objetivo da configuração exigida, incluindo permissões documentadas, sem tentar modificá-las.

Não alterar a política de segurança nem conceder permissões.

Documentar o caminho para habilitação pelo suporte Veracode.

## 7. Piloto operacional

Executar um piloto controlado com dados sintéticos completos.

Depois, caso os indicadores relevantes estejam conferidos e a autorização do cliente esteja disponível, permitir um piloto real assistido.

Fluxo:
- Escopo.
- Coleta.
- Conferência.
- Snapshot.
- Aprovação.
- Interpretação.
- Apresentação.
- PPTX e PDF.
- Backup.

Antes de aprovar uma competência, automatizar uma cópia de segurança consistente do banco.

Caso o backup falhe, bloquear a aprovação e informar o erro.

Não eliminar a opção de backup manual.

## 8. Segurança

- Backend em 127.0.0.1.
- Nenhuma credencial em logs.
- Nenhum dado real no Git.
- Nenhuma escrita operacional na Veracode.
- Reporting POST somente conforme autorização específica já existente e nunca enquanto bloqueado.
- Provedores externos de IA desabilitados.
- Backups e relatórios reais em diretórios locais ignorados.
- Sem acesso público não autenticado.

## 9. Testes

Executar:
- pytest.
- Testes do exportador.
- E2E Chromium.
- Regressão visual.
- Migrations.
- Backup e restauração.
- npm audit.
- pip check.
- gitleaks.
- check_repo.
- GitHub Actions.

Executar processos pesados sequencialmente para não esgotar a memória.

Não ocultar testes interrompidos.

## 10. Entrega

Atualizar:
- docs/STATUS.md
- docs/AGENT_HANDOFF.md
- docs/F10_OPEN_ISSUES.md
- Matriz de conciliação.
- Documentação do piloto.

Informar:

1. Quantos dos 21 indicadores foram efetivamente homologados.
2. Divergências identificadas.
3. Correções comprovadas.
4. Indicadores ainda não homologados.
5. Estado da Reporting API.
6. Resultado do piloto.
7. Backup e restauração.
8. Segurança.
9. Testes.
10. Commits e CI.
11. Impedimentos para produção.

Faça commit e push somente de código e documentação seguros.

Não versionar valores reais ou evidências confidenciais.

Não iniciar F12.

Pare após entregar o handoff para o PO.
