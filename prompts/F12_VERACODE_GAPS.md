# ORDEM DO PO — F12: Fechamento de Lacunas Veracode

**Projeto:** Afrika Reporting
**Fase anterior:** F11 aprovada
**Objetivo:** resolver lacunas prioritárias de integração e preparar a homologação dos indicadores.
**Produção:** NÃO autorizada.

Execute somente a F12. Não desenvolva funcionalidades fora do escopo.

## 1. Preparação

Leia CLAUDE.md, skills pertinentes, docs/AGENT_HANDOFF.md, docs/F11_METRIC_HOMOLOGATION.md e os contratos existentes.

Priorize alterações pequenas, testáveis e sem retrabalho.

## 2. Diagnóstico das permissões Veracode

O PO autoriza consultas GET aos endpoints oficiais:

- `/api/authn/v2/users/self`
- `/api/authn/v2/principal`, caso necessário e comprovadamente adequado.

Consulte a documentação oficial e confirme os hosts corretos para a região da conta.

Implemente um diagnóstico seguro da própria conta autenticada:

- Papéis disponíveis.
- Permissões pertinentes à Reporting API, se retornadas.
- Limitações encontradas.
- Diferença entre permissão ausente e habilitação não confirmada.

Não expor credenciais, identificadores sensíveis ou dados pessoais desnecessários.

Não consultar contas de outros usuários para realizar esse diagnóstico.

Não modificar permissões.

Não repetir o POST da Reporting API enquanto o bloqueio anterior não tiver sido efetivamente resolvido.

## 3. Novo indicador apps.scanned

Implementar o indicador de aplicações com scans publicados na competência.

Definição:

Quantidade de aplicações distintas do escopo com pelo menos um scan publicado no período selecionado.

Requisitos:

- GUID como identificador da aplicação.
- Separação SAST/SCA.
- Separação Policy/Sandbox.
- Competência e timezone do cliente.
- Data efetiva de publicação.
- Deduplicação.
- Proveniência.
- Estado de completude.

Investigue as fontes oficiais necessárias, incluindo Summary Report e Reporting API.

Não inferir quantidade mensal utilizando apenas o último scan disponível.

Caso não exista fonte suficiente, manter o indicador como indisponível com motivo explícito.

Versionar o contrato e atualizar templates apenas quando a compatibilidade exigir.

## 4. Conferência com dashboards

Reutilizar o mecanismo da F11.

Preparar os 21 indicadores aplicáveis para revisão humana, além do novo apps.scanned quando houver fonte comprovada.

Para cada um, apresentar:

- Valor coletado.
- Definição.
- Escopo.
- Competência.
- Filtros.
- Origem.
- Link ou caminho para conferência oficial.
- Campo para valor do dashboard.
- Diferença calculada.
- Status.

Não registrar HOMOLOGATED sem comparação real.

Não inventar valores.

Não armazenar evidências reais no Git.

## 5. Reporting API

Se identificar ausência de papel ou habilitação, preparar um diagnóstico técnico objetivo para solicitação ao suporte.

Não assumir automaticamente que todo 403 é problema de licença.

Não contornar permissões.

Não modificar a conta Veracode.

## 6. Segurança e operação

Preservar:

- Backend localhost.
- Proteção contra operações Veracode não autorizadas.
- Isolamento entre clientes.
- Backups antes da aprovação.
- Integridade dos snapshots.
- Provedores externos de IA desabilitados por padrão.
- Dados reais fora do Git.

Verificar que falhas de backup continuam bloqueando a aprovação.

## 7. Testes

Executar:

- pytest completo.
- Testes de exportação.
- E2E Chromium.
- Regressão visual.
- Testes do novo indicador.
- Testes de allowlist GET.
- Migrations.
- npm audit.
- pip check.
- gitleaks.
- check_repo.
- GitHub Actions.

Evitar execuções simultâneas pesadas no Windows.

Corrigir regressões antes de publicar.

## 8. Entrega

Atualizar STATUS, AGENT_HANDOFF, catálogo de indicadores e documentação de integração.

Entregar:

1. Resultado do diagnóstico das permissões.
2. Estado de apps.scanned.
3. Fonte comprovada do indicador.
4. Indicadores efetivamente homologados.
5. Pendências da Reporting API.
6. Testes.
7. Commits.
8. CI.
9. Limitações restantes para produção.

Faça commit e push somente de arquivos seguros.

Não iniciar F13.

Aguarde aprovação do PO.
