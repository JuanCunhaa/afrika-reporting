# ORDEM DO PO — F05: Snapshots, Histórico, Aprovações e Reporting API

**Projeto:** Afrika Reporting · **Fase:** F05 · **Modelo principal:** Claude Sonnet 5.5 · **Esforço:** High
**Status anterior:** F04.1 aprovada · **Próxima fase:** F06 — não autorizada

Executar exclusivamente a F05, incluindo a integração controlada com a Reporting API. Não iniciar a F06, não
implementar o motor de apresentações, não fazer alterações fora do escopo sem necessidade comprovada.

## 1. Contexto
Plataforma web de automação de apresentações DevSecOps (~30 clientes); clientes com subclientes opcionais (um nível);
escopos independentes (aplicações, usuários, scans, SCA); conexões herdadas ou sobrescritas; filtros versionados e
auditáveis; dados oficiais da Veracode; relatórios por competência mensal; histórico preservado; preenchimento manual
rastreável; geração futura de HTML/PPTX/PDF; aprovação com revisões posteriores. **A Veracode é a fonte de verdade**:
valor manual identificado como manual, preservando o resultado original. Local no Windows 11; hospedagem indefinida.

## 2. Preparação
Ler CLAUDE.md, skills, roadmap e AGENT_HANDOFF; inspecionar F03/F04/F04.1; consultar API_SOURCE_MATRIX e
VERACODE_INTEGRATION; evitar duplicação; planejar alterações incrementais e migrations. Sem subagentes desnecessários.

## 3. Persistência de snapshots (SQLite, SQLAlchemy, Alembic)
Entidades: competência mensal, execução de coleta, snapshot de métricas, revisão, aprovação, alterações manuais,
eventos de auditoria, referências de séries históricas (sem tabelas redundantes). Cada snapshot preserva: cliente e
subcliente; competência YYYY-MM; id e versão do contrato; valor, tipo e unidade; status técnico; homologação com
dashboard (separada); fonte Veracode/Manual; endpoint/fonte; data/hora da coleta; intervalo temporal usado; contexto
Policy/Sandbox; versões e hashes dos escopos; proveniência e id da execução; justificativa quando aplicável. Não
armazenar todos os findings; persistir agregados e dimensões para slides; sem credenciais ou respostas HTTP brutas.

## 4. Ciclo de vida
DRAFT → READY_FOR_REVIEW → APPROVED. Rascunhos editáveis; aprovação cria versão imutável; revisões posteriores criam
novas versões; aprovada nunca sobrescrita; só aprovadas alimentam o histórico; a mais recente é a referência; antigas
consultáveis; aprovação exige responsável declarado (não é identidade autenticada — documentar; backend só localhost);
mudanças concorrentes resultam em conflito.

## 5. Entrada e correção manual
Registrar indicador, valor anterior e novo, origem MANUAL, justificativa, operador declarado, timestamp UTC, revisão.
Preservar o valor da Veracode. Validar números, percentuais, contagens e séries. Distinguir zero legítimo, ausente,
coleta incompleta, fonte indisponível, valor manual e validado tecnicamente mas não homologado. Nunca converter
VALIDATED em homologação visual.

## 6. Aprovação e integridade
Bloquear: obrigatórios faltando; valores inválidos; violação de integridade; sem aprovador; conflito de revisão. Só
exigir indicadores do conjunto selecionado (seleção explícita e versionada, sem inventar requisitos de slides). Permitir
manuais válidos e justificados. Registro append-only de aprovações com hashes. Sem exclusão física de histórico.

## 7. Séries históricas
Mês atual × anterior; 6 meses; 12 meses; intervalos personalizados; só snapshots aprovados. Lacuna: mostrar, permitir
preenchimento manual auditado, não inventar, não interpolar, não substituir por zero. Aprovado em setembro mantém os
valores consultado em outubro. Fuso padrão America/Sao_Paulo, respeitando o do cliente.

## 8. Integração com a F04
Rascunhos a partir das execuções do motor preservando fonte, estado técnico, proveniência, escopo e versão, contrato,
data e contexto, valor observado. Coleta repetida não altera aprovada. Coleta incompleta conserva o motivo; operador pode
preencher manualmente. Rascunhos sobrevivem à reinicialização. Sem findings individuais.

## 9. Política de operações Veracode
**Autorizado o uso da Reporting API para gerar e consultar relatórios**: GET em endpoints oficiais autorizados; POST
exclusivamente na solicitação de geração de relatórios; GET para status e resultados. Proibido: criar/editar/excluir
aplicações; alterar findings, mitigações ou políticas; modificar BUs, Teams ou usuários; criar/alterar configurações de
scan; disparar SAST/SCA/DAST; exclusões/modificações operacionais; POST/PUT/PATCH/DELETE fora da operação autorizada;
contornar permissões. Deny-by-default.

## 10. Reporting API — implementação
Consultar a documentação oficial. Endpoint candidato `POST /appsec/v1/analytics/report`. Adaptador com HMAC; allowlist
por host, método e caminho; validação do tipo de relatório; limites de consultas; timeouts; retry com backoff; 429/5xx;
polling limitado com timeout global; cancelamento seguro; status de execução e erro; respostas tipadas; logs
sanitizados. Investigar FINDINGS, SCANS, DELETEDSCANS, AUDIT (priorizar FINDINGS e SCANS); validar fluxo, campos
obrigatórios, status, limites de período e recuperação. Não assumir formatos. Não integrar novos indicadores ao
catálogo sem contratos e testes.

## 11. Homologação da Reporting API
Primeiro testes sintéticos completos. Depois, só com permissões confirmadas e autorização do tenant de testes, UMA
geração real mínima (FINDINGS ou SCANS, intervalo pequeno, escopo limitado), habilitada explicitamente. Sem relatórios
de todos os clientes nem extrações massivas. API não habilitada ⇒ registrar e continuar. Sem findings reais em fixtures
ou arquivos versionados; sem envio a IA. Distinguir: adaptador implementado; testado com mocks; geração real
confirmada; métrica homologada contra dashboard.

## 12. Interface
Telas para: competências por cliente/subcliente; criação de rascunhos; importação de execução; edição manual;
histórico de revisões; comparação de versões; aprovação; snapshots aprovados; gráficos históricos e lacunas; estado das
execuções de reporting. Simples e funcional; sem editor de PowerPoint, templates ou exportação.

## 13. Testes obrigatórios
1 persistência após reinicialização; 2 rascunho derivado de coleta; 3 cliente e subcliente; 4 competência e timezone;
5 zero × ausência; 6 entrada manual tipada; 7 justificativa obrigatória; 8 integridade; 9 imutabilidade; 10 revisões
posteriores; 11 auditoria; 12 histórico 6 e 12 meses; 13 lacunas; 14 reutilização exata do mês anterior; 15 conflitos
concorrentes; 16 migrations em banco existente; 17 integridade referencial; 18 sem credenciais nos snapshots; 19 E2E;
20 regressão; 21 bloqueio de operações Veracode não autorizadas; 22 allowlist exclusiva do POST de reporting; 23 polling
e timeout; 24 HTTP 429, 403 e 5xx; 25 cancelamento; 26 sem vazamentos em logs; 27 teste real opt-in desabilitado por
padrão. O POST de geração não pode abrir permissão genérica a outros POST. Unitários e E2E sem chamadas reais.

## 14. Validação final e GitHub
pytest; build; Playwright Chromium; npm audit; pip check; Gitleaks; check_repo; migrations; reais opt-in quando
autorizados. Sem commits com testes falhando; atualizar locks se necessário; commit e push só de arquivos seguros;
acompanhar o GitHub Actions até o fim e corrigir falhas. Nunca publicar `.env`, bancos, logs, CSVs ou findings reais.

## 15. Entregáveis
Atualizar AGENT_HANDOFF, STATUS, docs de snapshots, histórico e auditoria, API_SOURCE_MATRIX e VERACODE_INTEGRATION se
necessário. Handoff: funcionalidades; entidades e migrations; endpoints internos; contratos de snapshot; aprovação e
revisão; histórico e manual; status da Reporting API; endpoints e métodos permitidos; resultados exatos dos testes;
evidências de segurança; CI; commits e push; limitações e pendências para F06. Versão compacta para o PO.

**Critério de encerramento:** snapshots persistentes, aprovação auditável, histórico funcional, regressões passando e
adaptador Reporting API implementado e testado, com homologação real quando autorizada e disponível. Indisponibilidade
externa da Reporting API não impede concluir a F05 se documentada. Não iniciar F06.
