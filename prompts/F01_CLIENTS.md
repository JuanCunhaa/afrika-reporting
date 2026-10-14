# ORDEM DO PO — F01: Cadastro de Clientes e Subclientes

> Cópia da ordem recebida em 2026-10-14 (rastreabilidade). Fonte: PO.

Você está autorizado a iniciar a F01 do Afrika Reporting.

**Antes de implementar:**
1. Leia `CLAUDE.md`, o roadmap, as skills pertinentes, `docs/AGENT_HANDOFF.md` e os contratos existentes.
2. Inspecione a implementação atual. Preserve a arquitetura e as funcionalidades da F00.
3. Utilize Sonnet 5.5 como implementador principal. Não invoque outros agentes desnecessariamente.
4. Não inicie F02 ou fases posteriores.

## Objetivo

Substituir o cadastro demonstrativo em memória por um módulo persistente, funcional e testado de clientes e subclientes.

O sistema deverá funcionar localmente no Windows 11 e não depender de serviços pagos ou infraestrutura externa.

## Requisitos funcionais

### Clientes
- Identificador UUID imutável.
- Nome, nome de exibição, descrição opcional e status ativo/inativo.
- Configuração de relatórios: consolidado, individual por subcliente ou ambos.
- Referência opcional à conexão Veracode.
- Data de criação e atualização.

### Subclientes
- Vínculo obrigatório a um único cliente.
- UUID imutável.
- Nome, nome de exibição e status.
- Referência opcional à conexão Veracode.
- Herança da conexão do cliente quando não houver sobrescrita.
- Proibição de subclientes dentro de subclientes.

Uma aplicação poderá futuramente pertencer a vários subclientes. Não implementar regras de exclusividade.

### Conexões
Criar somente o cadastro de metadados e referências de conexão, sem acessar a Veracode.
Nunca armazenar chaves HMAC ou secrets em texto puro, nem expô-los via API ou logs.
Permitir configurar e identificar qual referência de conexão será utilizada pelo cliente ou subcliente.

### Persistência
- SQLite local. SQLAlchemy para modelos e persistência. Alembic com migrations versionadas.
- Integridade referencial habilitada. Não apagar dados automaticamente na inicialização.
- Não usar `create_all()` como substituto de migrations.
- Definir comportamento seguro para exclusão de clientes com subclientes, priorizando desativação lógica e preservação de referências.

### Backend
Endpoints REST para clientes, subclientes e configuração de conexões. Schemas Pydantic tipados; validação de
entradas e UUIDs; tratamento de 400, 404, 409 e 422; paginação/limites; respostas previsíveis; nenhum segredo em
erros ou logs. Sem autenticação real nesta fase, documentando que a API local não está preparada para exposição pública.

### Frontend
Listagem, cadastro, edição e detalhes de clientes; cadastro e edição de subclientes; ativação/desativação; modo de
relatório; exibição da conexão herdada ou sobrescrita; estados de carregamento, vazio e erro; formulários com validação.
Dados sintéticos da F00 disponíveis por comando explícito de seed, sem recriação automática.

## Testes obrigatórios
1. CRUD completo de clientes. 2. CRUD completo de subclientes. 3. Persistência após reiniciar o backend.
4. Integridade dos relacionamentos. 5. Herança e sobrescrita da conexão. 6. Proibição de hierarquia > 2 níveis.
7. Exclusão/desativação. 8. Validações e respostas de erro. 9. Ausência de segredos em respostas e logs.
10. Interface funcional via Playwright. 11. Regressão da F00.
Executar migrations em banco novo e testar o caminho de atualização de esquema disponível.
Integrar E2E com Chromium no GitHub Actions. Se o CI não puder ser executado no GitHub, reportar `NOT_RUN`.

## Git e segurança
Inicializar Git localmente se necessário; verificar `.gitignore` antes do primeiro commit; não adicionar bancos,
secrets, arquivos de clientes ou artefatos sensíveis; não criar repositório público nem publicar; não declarar a
licença resolvida sem verificação; commits locais coerentes se as validações passarem.

## Restrições
Não consultar a Veracode; não implementar métricas nem apresentações; não adicionar dependências sem justificativa;
nada especulativo; sem deploy; compatibilidade Python 3.11 e 3.14 (ou bloqueio fundamentado); não iniciar a F02.

## Entrega obrigatória
`docs/AGENT_HANDOFF.md` com: resumo, arquivos, migrations, endpoints, comandos Windows, resultados com números,
status E2E/CI, evidências de segurança, limitações/riscos/pendências, commit hash, recomendação — e versão compacta
para o PO. **Parar ao concluir a F01.**
