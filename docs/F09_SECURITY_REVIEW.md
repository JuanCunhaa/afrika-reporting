# F09 — Revisão de segurança e isolamento (2026-10-19)

Escopo: produto completo como está em `main` + alterações da F09 (só testes e documentação; nenhum código de produto
alterado). Método: testes automatizados (sintéticos), execução real somente leitura no tenant de testes, varreduras
(gitleaks, identificadores reais, dependências) e sondas locais. Não é teste de intrusão nem auditoria de conformidade.

> **ATENÇÃO — limitação crítica:** o backend **não possui autenticação real de usuários**. Operador, aprovador e
> revisor são **nomes declarados** (`identity_mode = DECLARED_UNAUTHENTICATED`). Qualquer processo com acesso à porta
> local pode ler e alterar dados, aprovar competências e exportar. O sistema **não deve ser exposto** em rede,
> servidor compartilhado ou internet. Uso suportado: uma estação, um operador, API em `127.0.0.1`.

## 1. Resultado por requisito
| # | Requisito | Resultado | Evidência |
|---|---|---|---|
| S1 | Nenhuma credencial em respostas | PASS | F09 etapa 3: credenciais sintéticas ausentes das respostas de escopo/teste de conexão; API só devolve `env:NOME` |
| S2 | Nenhuma credencial em logs | PASS | F09 etapa 23: TODOS os logs do fluxo (nível DEBUG, raiz) sem API ID/Key, sem texto de interpretação nem justificativa manual |
| S3 | Nenhuma credencial no banco | PASS | F09 etapa 23: arquivo SQLite sem os valores; contém só `env:VC_GAMMA` |
| S4 | Nenhuma credencial no Git | PASS | gitleaks `git` 51 commits — 0 achados; `gitleaks dir` nos 4 arquivos novos — 0; `.env` em 0 commits; `.env` e `private/` ignorados |
| S5 | Nenhum dado real versionado | PASS | 8 identificadores reais da amostra (nomes/GUIDs/BU, só em `private/`) procurados em 508 arquivos rastreados/novos: 0 ocorrências; 0 PPTX/PDF rastreados; valores reais só em `private/f09/` |
| S6 | Nenhuma operação Veracode não autorizada | PASS | transporte de registro na execução real: **58 GET, 0 outro método**; demais testes reais ≈118 GET; POST da Reporting API **não executado** (403 anterior sem mudança de permissão confirmada; `VERACODE_REPORTING_LIVE_ENABLED` não definido); trava `ReadOnlyTransport` + allowlist de rotas |
| S7 | Isolamento entre clientes | PASS | F09 etapas 12, 13, 18b: competências, histórico, template, apresentações e interpretações de um cliente invisíveis ao outro (404 cruzado); real: escopos disjuntos (interseção 0) |
| S8 | Isolamento cliente × subcliente | PASS | F09 etapas 2–5: conexão herdada × independente resolvidas por dono; subcliente sem escopo ⇒ UNAVAILABLE (nunca dados do cliente); `test_subclients.py`, `test_scopes_api.py` |
| S9 | Controle de escopos | PASS | F09 etapa 4: regra de aplicações recusada no domínio de usuários (422); versão esperada desatualizada ⇒ 409 (sem sobrescrita) |
| S10 | Integridade dos snapshots | PASS | `GET …/integrity` ok antes e depois do reinício (hash por snapshot, conteúdo aprovado, cadeia de aprovações e de auditoria) |
| S11 | Imutabilidade de versões aprovadas | PASS | F09 etapa 11: API ⇒ 409; SQL direto (`UPDATE`/`DELETE` em `metric_snapshots`) ⇒ abortado pelo gatilho `snapshot_revision_not_draft` |
| S12 | Revisões auditáveis | PASS | F09 etapa 18: revisão 2 aprovada com justificativa; revisão 1 preservada e consultável; 2 eventos `revision.approved`; cadeia de auditoria ok |
| S13 | Segurança da exportação | PASS | F09 etapas 21/23: `nosniff`, `no-store`, SHA-256 no cabeçalho = conteúdo; download por id aleatório; 404 sem caminho do servidor; PPTX sem macros/ActiveX/OLE/links externos; PPTX e PDF sem nome do usuário do SO, caminhos locais nem referência de credencial |
| S14 | Ausência de acesso público não autenticado | PASS (local) / **limitação** | `LocalOnlyMiddleware`: `Host` forjado ⇒ 403 (F09 etapa 23), IP não-loopback ⇒ 403 (`test_veracode_discovery.py::test_local_only_rejects_non_loopback_clients_and_hosts`); uvicorn e Vite em `127.0.0.1`; CORS só `localhost:5173`. Sem autenticação: ver aviso acima |
| S15 | CSRF a partir do navegador do operador | PASS (mitigado) | sonda local: corpos `text/plain`, `form-urlencoded`, `multipart` e sem `Content-Type` ⇒ 422 (nada gravado); JSON exige *preflight*, negado pelo CORS a outras origens. Residual baixo: POST sem corpo (ex.: teste de conexão) exige UUID aleatório do dono |
| S16 | Provedores externos de IA desabilitados por padrão | PASS | F09 etapa 16: `external_enabled=false`, provedor `deterministic-demo`, sem credencial; etapa 22b: exportação com provedores proibidos (qualquer chamada derruba o teste); suíte bloqueia DNS/conexão não-loopback |
| S17 | Dependências | PASS | `pip check` OK; `npm audit` 0 vulnerabilidades (ver `docs/F09_ACCEPTANCE_MATRIX.md` §8) |

## 2. Achados
Nenhuma vulnerabilidade nova explorável no modo de uso suportado (local, um operador). Riscos residuais aceitos
explicitamente pelo desenho e que **impedem uso em produção compartilhada**:
1. **Sem autenticação/autorização de usuários** (aprovador declarado). Qualquer exposição da porta = controle total.
2. **Sem segregação de funções**: o mesmo operador pode preencher, aprovar e exportar.
3. **Banco SQLite local sem criptografia em repouso** (contém nomes de clientes, escopos e valores agregados; não
   contém credenciais nem findings). Depende da proteção do perfil do sistema operacional.
4. **Credenciais Veracode no `.env` local** (fora do Git) — protegidas apenas pelo sistema de arquivos.
5. **Jobs de exportação e execuções de coleta em memória**: reinício descarta (por desenho; F09 etapa 22 prova a
   mensagem explícita e a reexportação idêntica da revisão persistida).

Observação de higiene (não é vulnerabilidade; sem correção nesta fase — decisão do PO):
- **O-1** O PPTX exportado parte do template padrão do python-pptx e mantém duas partes herdadas:
  `ppt/printerSettings/printerSettings1.bin` (configurações de impressão, 9.395 bytes, idênticas às da biblioteca) e
  `docProps/thumbnail.jpeg` (miniatura genérica do pacote, não do conteúdo). Os metadados (`core.xml`) SÃO
  sobrescritos ("Afrika Reporting"). A etapa 23 fixa que a única `.bin` é exatamente a da biblioteca. Remover as duas
  partes mudaria o pacote (hashes/fidelidade aprovados na F07) e fica como sugestão.

## 3. Verificações não feitas
- Teste de intrusão, fuzzing amplo da API, revisão de cadeia de suprimentos além de `npm audit`/`pip check`.
- Comportamento em outros computadores/sistemas operacionais além de Windows 11 (local) e Ubuntu (CI): NOT_VERIFIED.
