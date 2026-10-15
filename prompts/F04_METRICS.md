# ORDEM DO PO — F04: Motor de Indicadores Veracode

> Cópia resumida da ordem recebida em 2026-10-14/15 (rastreabilidade). Fonte: PO. F03 aprovada.

Executar exclusivamente a F04 (não iniciar F05; sem slides/exportação). Primeiro motor funcional de métricas sobre
os escopos da F03: cliente ou subcliente + competência ⇒ indicadores com origem, filtros, período e completude.
Prioridade: aplicações, SAST e SCA.

1. **Contratos:** registro tipado (enums) com id, nome/descrição, domínio, fonte/endpoint, escopo de aplicações,
   Policy/Sandbox, campo temporal, competência, critérios de status/severidade/tipo, dedup, unidade/fórmula/
   arredondamento, completude, proveniência. Estados VALIDATED, INCOMPLETE, UNAVAILABLE, UNSUPPORTED, FAILED.
   Ausência nunca vira zero.
2. **Indicadores:** apps (total, por BU, por Team, sem Team, distintas); SAST (abertos por severidade, Policy,
   Sandbox, distintos, CWE, Top 10 aplicações, datas de identificação/resolução quando disponíveis); SCA (abertos por
   severidade, Policy, Sandbox quando suportado, distintos, biblioteca/CVE, associação comprovada). Sem declarar
   scans, licenças ou SCA Agent sem evidência; documentar lacunas.
3. **Competências:** mês fechado `YYYY-MM`; distinguir coleta, período, campo de data, estado atual × histórico.
   Histórico não reconstruível ⇒ UNAVAILABLE/UNSUPPORTED com motivo; sem estimativas. Snapshots/entrada manual = F05.
4. **Policy = produção, Sandbox = desenvolvimento:** origem real registrada; sem somar sandboxes às cegas; dedup por
   identidade comprovada (senão sinalizar); SAST e SCA com identidades próprias.
5. **Coleta:** cliente HTTP da F02 (GET, HTTPS, hosts autorizados, paginação, limites, 429, timeouts), cache
   transitório isolado, sem credenciais nos dados, cancelamento e incompletude; sem banco permanente de findings;
   limite excedido ⇒ INCOMPLETE.
6. **Escopos F03:** cliente sem subclientes, herança/sobrescrita de conexão, aplicações compartilhadas, sobreposição,
   não classificadas, indeterminados; nunca tenant inteiro implícito; versão exata do escopo na proveniência.
7. **Interface:** painel inicial (seleção, competência, coleta explícita, status, domínios, severidades, fonte/data,
   filtros, motivos). Sem editor de apresentações nem polimento visual.
8. **Testes (20 itens)** com fixtures sintéticas; testes reais opt-in, read-only, conservadores.
9. **Homologação:** amostra pequena autorizada; diferenciar correspondência comprovada, divergência de definição,
   fonte não homologada e teste não executado.
10. **Entrega:** AGENT_HANDOFF, STATUS, catálogo, fontes/limitações, contratos; backend, frontend, E2E, auditorias,
    CI; commit/push só de arquivos seguros; devolutiva compacta e aguardar o PO.
