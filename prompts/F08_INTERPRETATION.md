# ORDEM DO PO — F08: Interpretação Inteligente dos Indicadores

**Projeto:** Afrika Reporting
**Fase:** F08
**Status:** F07 aprovada
**Próxima fase:** F09 — não autorizada

## Objetivo

Implementar um motor de interpretação de indicadores com IA, capaz de produzir textos executivos e técnicos para apresentações mensais, sempre com base em snapshots aprovados da F05.

A IA NÃO deve calcular, modificar, substituir ou aprovar indicadores.

Não iniciar F09.

## 1. Preparação

Leia CLAUDE.md, as skills pertinentes, docs/AGENT_HANDOFF.md, os contratos das métricas, snapshots, apresentações e exportação.

Inspecione o código existente e reaproveite os serviços já implementados.

Priorize implementação incremental, testes automatizados e economia de tokens.

## 2. Arquitetura de interpretação

Criar módulo independente com:

- Contratos tipados de entrada e saída.
- Seleção dos indicadores relevantes por slide.
- Construção de contexto fundamentado.
- Adaptador de provedor de IA.
- Validação da resposta.
- Registro de evidências.
- Persistência das interpretações.
- Fluxo de revisão humana.

Criar inicialmente um provedor determinístico de demonstração, sem chamadas externas.

Deixar a arquitetura preparada para provedores reais configuráveis posteriormente, sem acoplar o sistema a um único fornecedor.

## 3. Dados permitidos

A interpretação deve utilizar exclusivamente:

- Valores aprovados.
- Histórico aprovado.
- Metadados de competência e contexto.
- Variações calculadas deterministicamente pelo backend.
- Status e qualidade dos indicadores.
- Informações editoriais explicitamente fornecidas pelo operador.

Não utilizar findings brutos, credenciais, nomes de aplicações, usuários ou outros dados sensíveis sem autorização específica.

Não consultar novamente a Veracode para produzir textos.

## 4. Tipos de interpretação

Implementar geração de textos para:

- Resumo executivo do mês.
- Principais melhorias.
- Principais pontos de atenção.
- Tendências de SAST.
- Tendências de SCA.
- Comparações entre competências.
- Evolução de conformidade.
- Evolução de cobertura de scans.
- Explicações para gráficos.
- Destaques de rankings.
- Recomendações técnicas fundamentadas.

Distinguir níveis de linguagem:

EXECUTIVE: objetivo, consultivo e orientado à gestão.

TECHNICAL: detalhado, preciso e relacionado a métricas e práticas DevSecOps.

Evitar afirmações genéricas sem evidências.

## 5. Regras contra interpretações incorretas

Não inventar:

- Causas de aumento ou redução de vulnerabilidades.
- Remediações não comprovadas.
- Aplicações corrigidas ou removidas.
- Melhorias de maturidade não demonstradas.
- Riscos de negócio específicos não fundamentados.
- Valores históricos ausentes.

Exemplo:

Permitido: "O número de findings altos aumentou 12% em relação à competência anterior."

Não permitido sem evidência: "O aumento ocorreu porque os desenvolvedores deixaram de corrigir vulnerabilidades."

Quando a causa não puder ser comprovada, utilizar linguagem neutra e propor investigação.

Não interpretar métricas INCOMPLETE ou UNAVAILABLE como números definitivos.

## 6. Contratos de saída

Cada interpretação deve conter:

- ID.
- Cliente/subcliente.
- Competência.
- ID da apresentação e revisão.
- Slide de destino.
- Tipo de interpretação.
- Texto.
- Indicadores e valores utilizados.
- Referências de proveniência.
- Modelo/provedor, quando aplicável.
- Versão do prompt.
- Data de geração.
- Status de revisão.
- Hash das fontes.

Estados sugeridos:

GENERATED → IN_REVIEW → APPROVED ou REJECTED.

Permitir regeneração com histórico.

## 7. Validação automática

Antes de apresentar o texto como válido:

- Conferir os números citados.
- Verificar percentuais e unidades.
- Validar período.
- Validar os indicadores referenciados.
- Detectar citações de dados ausentes.
- Identificar afirmações categóricas sem evidência.
- Respeitar limites de tamanho de cada slide.

Não confiar apenas na própria IA para validar suas afirmações.

Utilizar verificações determinísticas no backend sempre que possível.

Se uma interpretação não puder ser validada, bloqueá-la para aprovação e apresentar o motivo.

## 8. Revisão humana

Na interface permitir:

- Gerar interpretação.
- Visualizar indicadores de origem.
- Editar texto.
- Aprovar.
- Rejeitar.
- Regenerar.
- Comparar versões.
- Desabilitar interpretação por slide.

Nenhum texto gerado deve entrar automaticamente numa apresentação aprovada para entrega sem revisão humana explícita.

Edições devem preservar autoria declarada, justificativa quando apropriada e histórico.

A revisão não altera os snapshots ou indicadores.

## 9. Segurança e privacidade

Por padrão, o sistema NÃO deve enviar dados para provedores externos de IA.

Qualquer integração externa deve exigir:

- Configuração explícita do provedor.
- Credenciais em .env, nunca no frontend.
- Consentimento explícito para envio dos dados da execução.
- Minimização e sanitização dos dados.
- Identificação clara do que será transmitido.
- Limites e controle de custos.
- Logs sem conteúdo sensível.

Não implementar envio silencioso de dados reais.

Não incluir dados de clientes no GitHub público.

Não enviar arquivos PPTX de referência para modelos externos.

## 10. Integração com apresentações

A interpretação aprovada poderá preencher campos editoriais dos slides.

Preservar:

- Indicadores originais.
- Proveniência.
- Template e tema.
- Edição manual posterior.
- Histórico das interpretações.

Uma nova interpretação não deve sobrescrever silenciosamente texto já revisado.

Quando o snapshot aprovado ou a revisão da apresentação mudar, sinalizar interpretações potencialmente desatualizadas.

HTML, PPTX e PDF deverão exibir o mesmo texto persistido.

Não executar chamadas de IA durante a exportação.

## 11. Experiência de usuário

Adicionar ao editor:

- Botão "Gerar análise".
- Escolha entre análise executiva e técnica.
- Painel de revisão.
- Indicadores utilizados.
- Status de validação.
- Aprovar/rejeitar.
- Histórico.
- Aviso de interpretação desatualizada.

Priorize funcionamento e clareza, sem refazer o design existente.

## 12. Testes obrigatórios

Cobrir:

1. Geração determinística.
2. Resumo executivo.
3. Resumo técnico.
4. Indicadores ausentes.
5. Valores manuais.
6. Percentuais.
7. Comparação de períodos.
8. Citações numéricas corretas.
9. Rejeição de valores inventados.
10. Afirmações causais sem evidência.
11. Limites de caracteres e overflow.
12. Aprovação humana.
13. Rejeição e regeneração.
14. Edição manual de texto.
15. Versionamento.
16. Snapshot alterado.
17. Integração com editor.
18. Exportação PPTX/PDF com texto aprovado.
19. Nenhuma chamada externa por padrão.
20. Isolamento entre clientes.
21. Falhas do provedor.
22. Segurança e confidencialidade.
23. Regressão das fases anteriores.

Usar somente dados sintéticos.

## 13. Validação final

Executar sequencialmente:

- pytest completo.
- E2E Chromium.
- Build frontend.
- Testes de exportação.
- Regressão visual.
- npm audit.
- pip check.
- gitleaks.
- check_repo.
- Migrations.
- GitHub Actions.

Não fazer chamadas Veracode.

Não realizar chamadas a provedores externos de IA com dados reais.

Corrigir regressões antes de publicar.

## 14. Entrega

Atualizar:

- docs/STATUS.md
- docs/AGENT_HANDOFF.md
- Documentação da interpretação por IA.
- Contratos de integração.

Informar ao PO:

1. Funcionalidades entregues.
2. Contratos e endpoints.
3. Provedores implementados.
4. Validação determinística.
5. Fluxo de aprovação.
6. Integração com HTML/PPTX/PDF.
7. Evidências de segurança.
8. Testes.
9. CI.
10. Commits e push.
11. Pendências para F09.

Não iniciar F09.

Ao concluir, entregar uma devolutiva compacta e aguardar aprovação do PO.
