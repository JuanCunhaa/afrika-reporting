---
name: phase-delivery
description: Executar uma única fase com gates de qualidade e relatório ao PO, reduzindo tokens.
---
1. Leia instruções da fase e procure só os módulos afetados.
2. Antes de codar, faça plano curto (máximo 8 linhas) e enumere critérios de aceite.
3. Implemente mínimo funcional, preferindo interfaces estáveis a abstrações prematuras.
4. Rode testes focados e regressões obrigatórias; sem falso PASS.
5. Atualize STATUS e AGENT_HANDOFF; pare ao terminar fase.
6. Não crie PR, publique, exponha secrets nem inicie próxima fase sem ordem do PO.
