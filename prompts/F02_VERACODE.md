# ORDEM DO PO — F02: Conector Veracode e descoberta de recursos

> Cópia resumida da ordem recebida em 2026-10-14 (rastreabilidade). Fonte: PO.

Executar exclusivamente a F02 após confirmar o fechamento das pendências da F01.1. Sonnet 5.5 como implementador
principal; revisão arquitetural só para decisão complexa não coberta pelos contratos.

**Objetivo:** integração read-only, segura, testável e reutilizável com a Veracode para ~30 clientes e subclientes
opcionais. Não implementar motor de indicadores, relatórios ou slides.

1. **Autenticação e conexões:** HMAC oficial; resolvedor integrado às referências da F01 (herança/sobrescrita);
   `env:NOME` → `NOME_API_ID`/`NOME_API_KEY` com validação explícita; nada de credenciais no SQLite, frontend,
   logs ou endpoints de diagnóstico; testar credenciais ausentes, inválidas e sem permissão.
2. **Conectores:** aplicações, BUs, Teams, usuários, relações app↔Team/BU e usuário↔Team, sandboxes, metadados
   para filtros futuros. APIs oficiais; documentar limitações em vez de inventar associações.
3. **Paginação/desempenho:** cliente HTTP compartilhado com paginação completa, timeouts, retry com backoff e
   jitter, 429/Retry-After, concorrência configurável, reuso de conexões, cancelamento seguro, indicação de coleta
   completa/incompleta; limites configuráveis; coleta incompleta nunca vira resultado confiável.
4. **Interface:** área Veracode por cliente/subcliente: referência sem segredos, teste sob demanda, listas de
   aplicações/BUs/Teams/usuários, relacionamentos, erros de permissão/conectividade, estados carregando/vazio/erro,
   paginação e busca.
5. **Cache:** temporário, isolado por conexão e escopo, TTL configurável, invalidação manual, sem credenciais,
   sem mistura de tenants. Não substitui snapshots.
6. **Segurança:** backend sem autenticação ⇒ só loopback; sem escrita na Veracode; sem dados reais em IA,
   fixtures ou Git; testes reais só com credenciais autorizadas e configuração explícita (nunca no CI).
7. **Testes:** auth/resolução; herança/sobrescrita; paginação multi-página; 429; 401/403/404/5xx; timeouts/retries;
   coletas incompletas; usuário em vários Teams; aplicação em várias BUs/Teams; isolamento de cache; ausência de
   credenciais em logs/respostas; interface; regressão F00/F01/F01.1. Fixtures sintéticas, E2E, integração real
   opt-in separada.
8. **Documentação:** endpoints usados, links oficiais, autenticação, campos e limitações, cache, retry/rate limit,
   relações/filtros suportados, o que fica para F03/F04.
9. **Entrega:** validações locais; `docs/AGENT_HANDOFF.md` completo; não implementar filtros da F03; não iniciar a
   F03 sem aprovação; devolutiva compacta para o PO.
