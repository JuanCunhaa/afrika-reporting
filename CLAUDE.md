# Claude Code — contrato operativo (leia ANTES de modificar)

Você é o **implementador**, não o PO. O PO é ChatGPT e o usuário aprova escolhas de negócio. Execute somente a fase explicitamente autorizada em `docs/STATUS.md` e no prompt entregue.

## Hierarquia de contexto para economizar tokens
1. Este arquivo (<100 linhas); 2. `docs/STATUS.md`; 3. prompt da fase em `prompts/`; 4. somente a skill relevante em `.claude/skills/`; 5. somente as partes necessárias de `docs/`.
Não reler tudo a cada tarefa. Buscar símbolos/arquivos antes de abrir arquivos grandes. Sem varrer `node_modules`, `.venv`, `dist`, banco ou artefatos.

## Regras inegociáveis
- Não iniciar a próxima fase, refatorações fora de escopo nem integração externa por conta própria.
- Não inventar dados, APIs, valores, endpoints ou sucesso de testes. Se não verificável: `NOT_VERIFIED`.
- Veracode é fonte de verdade **para os valores da plataforma sob os filtros e data certos**; nossa extração/filtro/dedup continuam sujeitos a testes.
- Indicador tem `metric_id`, contrato, source, filters, timeframe, dedup, coverage, status e provenance. Zero != missing.
- Vulnerabilidades: Policy Scan => produção; Sandbox => desenvolvimento (convenção inicial autorizada); deduplicar findings no consolidado conforme contrato de métrica; não supor identidade por nome.
- Filtros separados por domínio: applications, users, scans, sca. Aplicação pode aparecer em subclientes distintos. Clientes sem subclientes devem funcionar.
- Snapshots aprovados: preservar valores por competência; futuras revisões auditadas, sem sobrescrita silenciosa. Dados anteriores de slides vêm de snapshot aprovado; falta de histórico = entrada manual, não preenchimento especulativo.
- Segredos/dados pessoais e findings reais NUNCA no repo, output de CLI compartilhado, fixtures, screenshots de CI ou logs. Use dados sintéticos.
- APIs em produção: somente leitura, credenciais mínimas, sem executar coleta real sem fase/autorização explícita.
- Design não está congelado: nenhum PPTX anexo é template oficial. Não commitar PPTX real.
- Não instalar dependências arbitrárias sem necessidade; preferir pequenas alterações bem testadas. Integração IA pode ser opcional; nunca bloquear core determinístico.
- `LICENSE` somente código original autorizado; não incorporar código de repositório externo sem verificar licença.

## Modelo e economia
- Sonnet 5.5: implementação padrão + testes; Opus 5.5: arquitetura, tradeoffs difíceis, revisões; Haiku 5.5: tarefas mecânicas/documentação delimitada. Não assumir disponibilidade exata de IDs; usar os modelos habilitados no ambiente.
- Trabalhe incrementalmente. Rode testes relevantes + regressão; reporte comandos, resultados e limitações. Não usar subagentes paralelos sem motivo mensurável.
- Nunca responder "está pronto" sem evidência. Checkpoint em `docs/STATUS.md`.

## Relatório para PO obrigatório
Ao terminar, responder com `docs/AGENT_HANDOFF.md`: fase/commit, arquivos alterados, decisões, testes rodados PASS/FAIL/NOT_RUN, evidência, riscos, pendências e prompt sugerido para fase seguinte (**sem executá-la**).
