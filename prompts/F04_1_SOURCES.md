# ORDEM DO PO — F04.1: Veracode API Discovery & Reliability

> Cópia resumida da ordem recebida em 2026-10-15 (rastreabilidade). Fonte: PO. F04 aprovada (indicadores ainda não
> homologados com dashboards).

Executar exclusivamente a F04.1 (não iniciar F05). Ampliar cobertura e confiabilidade das fontes Veracode, investigar
APIs alternativas e os HTTP 500. Veracode = fonte de verdade; nada de números alterados ou métricas inventadas.

1. **Inventário** (documentação oficial): Applications, Findings, Reporting, Summary Report, SCA REST/Agent, Identity,
   Policy e outros relevantes; estudar `ancient-cthulhu/Veracode-All-Findings-Extract` (SAST, SCA, paginação,
   autenticação, reconciliação, falhas) sem copiar código sem verificar licença.
2. **Matriz de cobertura** por indicador (fonte atual/alternativas, endpoint/método, autenticação, Policy/Sandbox,
   datas, histórico, paginação, limitações, reprodução do dashboard, homologação); separar oficial, UI e hipótese.
3. **Diagnóstico dos 500** (paginação, scan_type, contextos, status das apps, SCA, permissões, respostas); amostras
   pequenas; sem repetir o mesmo erro sem nova hipótese; 500 ≠ prova de licença/permissão; circuit breaker.
4. **APIs alternativas** só com GET verificado, autenticação permitida, benefício concreto e sem regressão. Reporting
   API estudada (POST + GET) e não executada. Sem allowlist especulativa, cookies, sessões ou endpoints internos.
5. **Definições oficiais**: aberto/fechado/mitigado, First Found, First Found in Application, Resolved, Last Updated,
   únicos, Policy/Sandbox, scans executados, aplicações com scans, SCA Upload/Agent. HTTP 200 ≠ VALIDATED.
6. **Fuso**: `America/Sao_Paulo` padrão configurável por cliente, regras históricas; distinguir competência,
   intervalo UTC, coleta e campo temporal; testar limites de mês e horário de verão.
7. **Testes**: backend, E2E Chromium, build, dependências, gitleaks, CI; novos adaptadores e falhas; reais opt-in,
   só GET, sem persistir respostas sensíveis.
8. **Entrega**: `docs/API_SOURCE_MATRIX.md`; atualizar VERACODE_INTEGRATION, catálogo, STATUS, AGENT_HANDOFF;
   commit/push seguros; devolutiva compacta e parar.
