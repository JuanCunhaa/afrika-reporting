---
name: metric-contracts
description: Implementar e testar regras determinísticas de indicadores e snapshots.
---
- `metric_id` estável, versão, filtros, população, janela, unidade, rounding, source e provenance.
- Differenciar 0, unknown, error, partial e manual; dados incompletos bloqueiam publicação.
- Deduplicar por identidade apropriada e preservar escopos sobrepostos.
- Histórico aprovado não se reconstrói silenciosamente a partir do estado corrente.
- Criar golden fixtures com boundary do mês e timezone, mudanças de status e duplicatas.
