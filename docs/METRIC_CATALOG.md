# Catálogo de indicadores — hipóteses a homologar

| ID | Domínio | Dado desejado | Fonte candidata | Observação |
|---|---|---|---|---|
| apps.total | apps | total de aplicações do escopo | Applications API | regras BU/Team; excluídas/arquivadas a definir |
| users.unique | users | usuários únicos por Team | Identity API | dedup por ID |
| scans.count | scans | scans na competência | Reporting/scan metadata | contar eventos, policy/sandbox |
| scans.covered_apps | scans | apps com ao menos um scan | scan metadata | distinct GUID |
| sast.open.by_severity | SAST | abertas no corte do mês | Findings/Analytics | validar snapshot retrospectivo |
| sast.fixed.month | SAST | corrigidas no mês | Reporting/Analytics | métrica de fechamento correta |
| sast.fixed.cumulative | SAST | corrigidas acumuladas | Analytics | aplicações excluídas: seguir dashboard |
| sca.open.by_severity | SCA | abertas por severidade | SCA/Findings | SCA agent vs upload |
| sca.direct_transitive | SCA | questões em dependências | SCA | categorização dashboard |
| sca.vulnerable_methods | SCA | métodos vulneráveis | SCA | confirmar superfície API |
| compliance.by_status | policy | pass/fail/conditional/not assessed | Policy/Analytics | população e janela |
| loc.total | metrics | LOC de aplicações | Applications/Analytics | origem exata pendente |
| density.kloc | metrics | findings por KLOC | Analytics | respeitar regra oficial |
| density.mb | metrics | findings por MB | Analytics | não assumir denominador |
| density.per_app | metrics | findings por aplicação | Analytics | convenções de população |
| top_apps.sast | SAST | ranking de aplicações | Findings/Analytics | desempates oficiais |
| top_weaknesses | SAST | categorias CWE | Findings/Analytics | agrupamentos oficiais |
| licenses.usage | license | licenças em uso | API/entrada manual | pode exigir preenchimento manual |
| trend.monthly | history | séries de 6/12 meses | snapshots aprovados | manual quando faltar histórico |

**Status:** todas fontes são candidatas até prova real da equivalência com dashboards. F04 exige para cada métrica: query real, parâmetros, timestamp, filtro, contagem e prova reconciliada. Fases anteriores não devem inventar.
