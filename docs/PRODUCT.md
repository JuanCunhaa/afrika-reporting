# PRD condensado — decisões fornecidas pelo usuário

**Missão:** gerar relatórios mensais Veracode em HTML navegável/editável, PPTX e PDF, com layout corporativo fiel a template oficial a definir. ~30 clientes, cadastro manual. Multi-tenant lógico (cliente; 0..N subclientes com apenas um nível).

## Escopos
- Um cliente pode permitir relatório consolidado e/ou relatórios por subcliente (configurável).
- Compartilhamento de aplicações entre subclientes é permitido; relatórios individuais respeitam cada filtro. Consolidado requer resolução por conjunto, não soma cega.
- Conexão Veracode padrão no cliente; subcliente pode sobrescrever credencial/conexão.
- Filtros independentes: aplicações (BU, Teams, custom fields, etc.), usuários (Teams Veracode), scans e SCA; UI simples e avançada (AND/OR/NOT). Membros não classificados => bucket `unclassified`.
- Sandbox = desenvolvimento; Policy Scan = produção por padrão. Usuários únicos por ID; findings de múltiplos sandboxes deduplicados por ID/critério homologado.

## Relatório
- Competência: mês civil fechado (dia 1 ao último). Abertas: estado no final daquele mês, não dados de hoje rotulados retroativamente. Corrigidas: período e acumulado.
- Histórico dos comparativos: snapshots de relatórios anteriores aprovados; gráficos de 6/12 meses podem ter preenchimento manual com origem registrada. Não recalcular aprovado em silêncio.
- Coleta automática da competência atual quando autorizado, com possibilidade de campos manuais obrigatórios para falhas ou dados históricos ausentes. Dados incompletos impedem publicação até resolução.
- Visão de dashboard e de slides; edição de campos no HTML; IA somente em slides interpretativos. Nome de capa automático editável; apresentadores padrão editáveis. Slides por cliente configuráveis.
- Relatório aprovado pode receber edições com audit trail e revisões, nunca destruição da revisão original.
- Geração acionada manualmente. Exportações: HTML, PPTX, PDF.

## Princípios de valores
Veracode é fonte de verdade, inclusive quando o número exibido parecer errado. Conferir nossa equivalência de filtros, contexto, timestamp e medida com dashboard; não inventar correções locais. Definições temporais como `first_found_date`, `created_date`, `resolved_date` **variam por métrica**.

## Não decidido (não bloquear F00)
- Template final: ambos anexos apenas referência, não publicar arquivos reais.
- Regra formal da referência entre múltiplas revisões aprovadas.
- Forma de consolidar escopos sobrepostos por indicador.
- Fórmula/endpoint validado para cada métrica.
- Hospedagem final; decisão Vercel vs local; autenticação multiusuário.
- Requisitos jurídicos da titularidade sobre marca, slides e código.
