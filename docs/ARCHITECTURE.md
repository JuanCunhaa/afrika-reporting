# ADR-0001 — Local-first para reduzir dependências iniciais

**Provisório**: Python 3.11+ / FastAPI (API e coleta), React + Vite + TypeScript (visual), SQLite (metadados e métricas agregadas). Chamadas REST assinadas à Veracode no backend; navegador **nunca** recebe chaves Veracode. Exportação PPTX pode usar python-pptx + renderização visual/controle de qualidade; escolher engine final por spike de fidelidade. PDF produzido por renderer controlado, não prometer pixel perfect antes do teste.

## Módulos-alvo
1. Identity/Clients/Connections: gestão de clientes, subclientes e configuração.
2. Scope Engine: regras tipadas por domínio, resolução e explicação (`why included`).
3. Veracode Adapters: limites de taxa, paginação, retries 429/5xx, registro de extração completa.
4. Metric Registry: contrato versionado, fonte oficial, filtro, data de corte, método de dedup, proveniência.
5. Snapshot Store: agregados por período, versão, origem `api`/`manual`, auditoria de revisões.
6. Presentation Engine: catálogo de blocos com schema, preview fiel, exportadores HTML/PPTX/PDF.
7. Validation: unit + API contract mocked + E2E + visual regression + homologação em tenant autorizado.

## Riscos
- SQLite não deve ser usado como banco persistente compartilhado em Vercel serverless. Para cloud: avaliar Postgres e jobs assíncronos conforme demanda.
- Reporting/Analytics pode não oferecer fotografia exata de fechamento de meses antigos: testar contrato antes de prometer.
- Ser parte de BU/Team não equivale automaticamente a ter visibilidade de usuário ou a atribuição de findings: cada domínio tem sua query.
- Script referência third-party sem licença declarada: somente inspiração de arquitetura/algoritmos; não copiar.

## Limites de dados
Retenção: preferir snapshots de métricas e agregados, sem persistir todos os findings. F02: descoberta processada em memória (cache TTL, sem disco); concorrência, rate limit, orçamento e prazo por coleta em `backend/app/veracode/` — ver `docs/VERACODE_INTEGRATION.md`. Checkpoints de coletas longas (findings) ficam para F04.
