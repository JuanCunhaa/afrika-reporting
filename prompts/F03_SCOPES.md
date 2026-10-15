# ORDEM DO PO — F03: Motor de Escopos e Filtros

> Cópia resumida da ordem recebida em 2026-10-14 (rastreabilidade). Fonte: PO. F02.1 aprovada.

Executar exclusivamente a F03 (não iniciar F04). Motor configurável de seleção de recursos Veracode para clientes
e subclientes, sem regras específicas de nenhum cliente.

1. **Modelo:** escopos independentes para aplicações, usuários, scans e SCA; dono = cliente ou subcliente; versão,
   status e critérios próprios; SQLite + SQLAlchemy + Alembic. Sem findings, scans históricos ou indicadores.
2. **Filtros:** AND/OR/NOT, agrupamento, igualdade/inclusão/exclusão, IDs de BU e Team, aplicações explícitas,
   nome/tags/criticidade/campos personalizados quando disponíveis, usuários por Teams, campos ausentes. Sem nomes
   como identificadores; sem relacionamentos inventados; AST validado com limites de profundidade/complexidade.
3. **Semântica:** cliente define o universo; subcliente com critérios próprios; aplicações em vários subclientes;
   domínios sem filtros compartilhados; scans/SCA só armazenados e validados (consultas na F04); Team de usuários
   não seleciona aplicações; interseção com o universo na mesma conexão; conexão diferente exige validação
   explícita da abrangência, sem misturar tenants.
4. **Não classificadas:** universo − união dos subclientes, por ID; universo restrito respeitado; avisar sem
   subclientes ou universo incompleto.
5. **Interface:** construtor simples (BU, Teams, aplicações, filtros comuns) e avançado (grupos, AND/OR/NOT,
   validação antes de salvar); pré-visualização (incluídas, excluídas, não classificadas, sobreposição, usuários
   únicos por Team); estados de carregamento, erro e coleta incompleta; nada "validado" com origem incompleta.
6. **Correções F02.1:** `?` → `Indisponível`; sem user_count com resultados incompletos; reconciliação
   usuário–Team com informação confiável (motivo quando não comprovável); usuários inativos à parte, regra padrão
   documentada e configurável.
7. **Persistência:** migration versionada; versões anteriores preservadas; nunca sobrescrever silenciosamente;
   sem cópias de recursos Veracode no banco; cache transitório isolado por conexão.
8. **Segurança:** só GET; nenhuma alteração na Veracode; credenciais fora de banco/logs; sem dados reais em
   fixtures/commits; sem envio a IA externa; aplicação local; allowlist inalterada salvo justificativa e testes.
9. **Testes:** 16 cenários (sem subclientes, três subclientes, sobreposição, não classificadas, AND/OR/NOT
   aninhados, BU/Teams, filtros independentes, usuários em vários Teams, inativos, campos ausentes, conexão herdada
   e sobrescrita, coletas incompletas, versionamento, migrations, E2E do construtor, regressão). Consultas reais
   opt-in, limitadas, somente leitura.
10. **Entrega:** AGENT_HANDOFF, STATUS, documentação do motor, contratos; commit/push só de arquivos seguros;
    devolutiva compacta ao PO e aguardar aprovação.
