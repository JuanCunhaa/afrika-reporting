# ADR-0001 — Local-first para reduzir dependências iniciais

**Provisório**: Python 3.11+ / FastAPI (API e coleta), React + Vite + TypeScript (visual), SQLite (metadados e métricas agregadas). Chamadas REST assinadas à Veracode no backend; navegador **nunca** recebe chaves Veracode. Exportação PPTX pode usar python-pptx + renderização visual/controle de qualidade; escolher engine final por spike de fidelidade. PDF produzido por renderer controlado, não prometer pixel perfect antes do teste.

## Módulos-alvo
1. Identity/Clients/Connections: gestão de clientes, subclientes e configuração.
2. Scope Engine (F03, `backend/app/scopes/`): regras tipadas por domínio (AST validado, lógica de 3 valores), versões append-only, resolução sobre a descoberta (universo, interseção, sobreposição, não classificadas) — `docs/SCOPES.md`.
3. Veracode Adapters: limites de taxa, paginação, retries 429/5xx, registro de extração completa.
4. Metric Registry (F04, `backend/app/metrics/`): contratos tipados (enums), registro versionado, competência fechada, população pelos escopos F03, coleta Findings API com orçamento/cache, motor determinístico com status VALIDATED/INCOMPLETE/UNAVAILABLE/UNSUPPORTED/FAILED e proveniência — `docs/METRIC_CATALOG.md`.
5. Snapshot Store (F05, `backend/app/snapshots/`): competências por dono, revisões DRAFT/READY_FOR_REVIEW/APPROVED com lock otimista, snapshots com fonte preservada e origem VERACODE/MANUAL, aprovações e auditoria append-only com hash encadeado, séries só de aprovados — `docs/SNAPSHOTS.md`.
6. Presentation Engine: catálogo de blocos com schema, preview fiel, exportadores HTML/PPTX/PDF.
7. Validation: unit + API contract mocked + E2E + visual regression + homologação em tenant autorizado.

## Riscos
- SQLite não deve ser usado como banco persistente compartilhado em Vercel serverless. Para cloud: avaliar Postgres e jobs assíncronos conforme demanda.
- Reporting/Analytics pode não oferecer fotografia exata de fechamento de meses antigos: testar contrato antes de prometer.
- Ser parte de BU/Team não equivale automaticamente a ter visibilidade de usuário ou a atribuição de findings: cada domínio tem sua query.
- Script referência third-party sem licença declarada: somente inspiração de arquitetura/algoritmos; não copiar.

## Limites de dados
Retenção: preferir snapshots de métricas e agregados, sem persistir todos os findings. F02: descoberta processada em memória (cache TTL, sem disco); concorrência, rate limit, orçamento e prazo por coleta em `backend/app/veracode/` — ver `docs/VERACODE_INTEGRATION.md`. F04: findings processados em memória (minimizados), só agregados retidos por execução (memória); sem banco de findings.
