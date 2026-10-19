# Regras mínimas de segurança

- Git público somente com código autoral e fixtures sintéticas.
- Nunca versionar PPTX real de cliente, export CSV/JSONL de findings, .env, credentials, banco SQLite, relatórios gerados ou dados de pessoas.
- Credenciais HMAC exclusivamente no backend (variáveis ambiente / store seguro). Não armazenar segredos em SQLite plaintext.
- Mascarar tokens, headers Authorization, IDs/chaves em logs, trace e handoff.
- Backend Veracode read-only; TLS validado, sem `verify=False`.
- Restringir CORS em produção; demo local aceita localhost somente.
- Fluxos com acesso real só após autorização expressa e teste de permissões.
- Revisar dependências, proteção de branches, scanner de secrets, licenças de terceiros antes de tornar repo público.

## Controles implementados na F01

- **API sem autenticação**: uso exclusivamente local (`127.0.0.1`). **Não expor publicamente** nem em rede compartilhada até existir autenticação/autorização (fase futura, não decidida).
- **Conexões**: o banco guarda só metadados e `credential_ref` no formato `env:NOME` (nome de variável de ambiente do backend). Valores com aparência de chave (sequência hexadecimal ≥ 24) são recusados. Não há campo para API ID/Key; campos desconhecidos geram 422 (`extra='forbid'`).
- **Erros**: formato único `{"error": {code, message, details}}`; o `input` do Pydantic é descartado, então valores enviados não são ecoados. Erro 500 retorna mensagem genérica e loga só o tipo da exceção.
- **Logs**: a aplicação loga apenas IDs (UUID), nunca nomes ou payloads. Engine com `hide_parameters=True` (parâmetros SQL ocultos em logs e exceções).
- **Logs SQL em DEBUG (F01.1)**: em DEBUG o SQLAlchemy logaria **linhas de resultado** (nomes de clientes). `app.db.DropSqlResultRows` é instalado no logger `sqlalchemy.engine.Engine` a cada `make_engine` e descarta todo registro DEBUG desse logger; o filtro fica no logger (não no handler) e sobrevive a `dictConfig`/`uvicorn --log-config`. SQL em INFO continua visível, com parâmetros ocultos. Testado in-process e com servidor real + `--log-config` acidental, com controle negativo (sem o filtro os testes falham).
- **Banco**: `data/*.sqlite3` e `frontend/.e2e-data/` estão no `.gitignore`. Testes e E2E usam bancos temporários com dados sintéticos.
- **`.env.example`**: `scripts/check_env_example.py` classifica cada variável (vazio/placeholder/valor padrão não secreto/REVISAR) **sem imprimir valores** e recusa ler `.env` real. Roda no CI quando o arquivo está versionado.
- **Dependências Python**: versões exatas em `backend/constraints.txt` (aplicado por `requirements.txt`); CI roda `pip check`.
- **Publicação pública do código (2026-10-14)**: autorizada pelo titular após licença integral (PolyForm Noncommercial 1.0.0 + `NOTICE`), declaração de titularidade e auditoria (gitleaks histórico + árvore, sem dados reais). Isso **não** autoriza expor a aplicação: a API continua sem autenticação e só para uso local.

## Controles implementados na F02 (integração Veracode somente leitura)

- **Loopback obrigatório** (`app/local_only.py`): requisições com IP de origem não-loopback ou `Host` fora de
  localhost/127.0.0.1/::1 recebem 403 (protege contra `--host 0.0.0.0` acidental e DNS rebinding). Não substitui autenticação.
- **Credenciais**: só do ambiente do backend (`env:NOME` → `NOME_API_ID`/`NOME_API_KEY`), lidas por requisição, nunca persistidas,
  nunca devolvidas (nem valores, nem nomes derivados), `repr` mascarado. A UI recebe apenas o estado (`configured`/`missing`/…).
- **Somente leitura**: hook do cliente HTTP bloqueia qualquer método ≠ GET antes do envio; hosts fixos por região; redirects e `_links` não seguidos (sem SSRF); TLS sempre validado; cookies desativados (cliente compartilhado entre tenants sem estado).
- **Logs**: só recurso, status, tentativa, espera e IDs internos (UUID). `httpx`/`httpcore` filtrados para WARNING+ (não logam URL com query). Testes com controle negativo.
- **Minimização**: e-mail/telefone/IP de usuários descartados na normalização; nada coletado vai para disco; cache só em memória com chave sem credenciais.
- **Fixtures**: tenant sintético gerado em código (`app/veracode/fixtures.py`); credenciais sintéticas derivadas de rótulos fixos — não são chaves reais.
- **Integração real**: somente opt-in (`backend/tests_live`, `AFRIKA_VERACODE_LIVE=1`) com autorização do operador; nunca no CI.

## Controles implementados na F03 (escopos)
- **Sem novos endpoints Veracode**: a resolução reutiliza a descoberta F02 (só GET, allowlist inalterada); scans/SCA não consultam nada.
- **Banco**: só regras (IDs/valores de filtro), opções e metadados de versão — nenhum recurso Veracode, nome de aplicação/usuário ou credencial (teste lê o dump do SQLite). Versões imutáveis por gatilhos; exclusão de dono com escopos bloqueada (RESTRICT).
- **Anti-abuso**: AST validado antes de avaliar (profundidade, nós, valores, tamanho, chaves e tipos); erros nunca ecoam o corpo além do caminho do campo.
- **Tenants**: subcliente em outra conexão exige confirmação explícita e nunca entra em interseção/não classificadas do cliente; mudança de conexão invalida a versão para resolução.
- **Respostas**: pré-visualização devolve no máximo 200 itens de amostra (id + nome) da descoberta em memória; sem credenciais (testado na API e no E2E).

## Controles implementados na F04 (indicadores)
- **Allowlist**: só `GET /appsec/v2/applications/{guid}/findings` foi acrescentado (justificativa: Findings API oficial;
  testes de bloqueio para v1, detalhe, CWE e SCA Agent). Trava somente leitura e loopback inalterados.
- **Minimização de findings**: descrição, caminho/arquivo/linha, módulo, procedimento e anotações são descartados na
  normalização; nada de findings vai para disco ou banco; resultados das execuções guardam só agregados (contagens,
  rankings com nome/GUID de aplicação, CWE, componente e identificador de vulnerabilidade) e vivem em memória.
- **Sem credenciais nas respostas**: nem valores, nem nomes de variáveis, nem `credential_ref` (testado na API e no E2E).
- **Abuso/custo**: execuções só por ação explícita; no máximo 3 simultâneas (429), orçamento/prazo por execução e teto
  de aplicações; cancelamento explícito. Homologação real só opt-in (`tests_live/test_metrics_live.py`), amostra
  pequena, imprimindo só contagens, chaves e enums.

## Controles implementados na F04.1 (fontes alternativas)
- **Allowlist**: + `GET /appsec/v2/applications/{guid}/summary_report` e `GET /srcclr/v3/applications/{guid}/projects`
  (ambos GET na especificação oficial; testes de bloqueio para Reporting API, issues/workspaces do agente e caminhos
  derivados). Política GET-only inalterada; nenhum POST, cookie, sessão de navegador ou endpoint interno de UI.
- **Minimização**: Summary Report descarta `submitter`, `business_owner`, nome da aplicação, Teams, BU, tags, campos
  personalizados e dados de componentes; SCA Agent guarda só IDs de projeto/workspace e data do último scan.
- **Fuso do cliente**: nome IANA validado contra a lista oficial instalada antes de abrir a zona (sem caminho de arquivo).
- **Custo/abuso**: 500 sem retry imediato, passada adiada única e circuit breaker limitam requisições repetindo a mesma
  falha. Repositório de referência sem licença: estudado, nenhum trecho copiado.

## Controles implementados na F05 (snapshots e Reporting API)
- **Imutabilidade no banco**: gatilhos impedem alterar revisão APPROVED, snapshots fora de DRAFT, excluir competências,
  revisões e snapshots, e qualquer UPDATE/DELETE em aprovações, alterações manuais, execuções importadas e auditoria.
  Downgrade da migration recusado com aprovações registradas (exige `AFRIKA_ALLOW_DESTRUCTIVE_DOWNGRADE=1`).
- **Integridade**: SHA-256 por snapshot, por conteúdo aprovado e encadeado (aprovações e auditoria); verificação
  recalcula tudo e bloqueia aprovação com hash divergente.
- **Concorrência**: `expected_lock_version` + UPDATE condicional ⇒ conflito 409, nunca sobrescrita.
- **Identidade declarada**: operador/aprovador são texto livre sem autenticação (`DECLARED_UNAUTHENTICATED`); API segue
  só em loopback. Entradas validadas (sem caracteres de controle; justificativa obrigatória; valores tipados;
  NaN/Infinity recusados); erros não ecoam valores.
- **Sem segredos nos snapshots**: conexão só por id/nome/região; nenhum `credential_ref`, chave, header ou resposta HTTP
  (teste varre todas as tabelas F05). Banco local fica em `data/` (ignorado pelo Git).
- **Reporting API (única escrita)**: deny-by-default — POST só com `AFRIKA_VERACODE_REPORTING_ENABLED=true`, só
  `POST /appsec/v1/analytics/report`, corpo JSON revalidado no transporte (FINDINGS/SCANS, campos/enums da spec, janela
  limitada); todo outro POST/PUT/PATCH/DELETE bloqueado antes da rede (testado com o pool habilitado). POST sem retry em
  5xx (sem duplicatas); cota 6/h, 1 simultâneo, polling/páginas/prazo limitados. Itens minimizados na leitura, nada
  persistido; logs só com id da execução, status e contagens (teste de vazamento com DEBUG).

## Controles implementados na F06B.1 (temas, ativos, inspeção PPTX, regressão visual)
- **Recursos proprietários fora do Git**: temas próprios só no banco local; logos/fontes no armazenamento local de
  ativos (`AFRIKA_ASSET_DIR`, padrão `data/theme-assets/`, ignorado); o tema guarda só `{sha256, media_type}`. PPTX,
  PDF e relatórios de inspeção (`output/`, `private/`) ignorados pelo Git; a CLI recusa gravar relatório em área
  versionável. Fixtures de teste (PPTX, PNG, temas) são sintéticas e geradas em tempo de execução.
- **Ativos**: tipo pela assinatura dos bytes (PNG, JPEG, SVG, WOFF2, WOFF, TTF, OTF), ≤ 5 MB, endereçamento por SHA-256
  (sem nome original). SVG só sem DOCTYPE/entidades, `script`, `foreignObject`, eventos `on*`, referências/`url()`
  externas ou `@import`; servido com `nosniff`, CSP `default-src 'none'; sandbox` e conferência do hash antes de servir
  (adulterado ⇒ 409). Renderização só por `<img>`/`@font-face` com URL local.
- **Tema**: esquema estrito (`extra='forbid'`); cores só `#RRGGBB`; nomes de família sem aspas/vírgulas/ponto e vírgula
  (impede injeção de CSS); textos sem `<`/`>`/controle; versões append-only (gatilho) com auditoria.
- **Inspeção PPTX**: 100% local (biblioteca padrão), sem rede, sem execução de macros/OLE, sem leitura de planilhas
  incorporadas, sem extração para disco; limites contra zip bomb, XML com DOCTYPE/entidades recusado. Nenhum texto,
  valor, nota ou comentário copiado; modo `strict` (padrão) também omite nomes e destinos de vínculos.
- **Regressão visual**: só dados sintéticos; manifesto grava hash do texto (não o texto); artefato do CI contém apenas
  capturas da fixture sintética.
- Nenhuma chamada à Veracode nesta fase.

## Controles implementados na F06B (template de referência Afrika)
- PowerPoint de referência só local em `references/` (ignorado, junto com `*.pptx *.potx *.pptm *.ppt *.ppsx *.pdf
  *.key`); `scripts/check_repo.py` falha se algum for rastreado e se o nome do cliente/unidade da referência aparecer em
  arquivo versionado (comparação por SHA-256 de palavras/bigramas; o nome não fica no repositório).
- Original nunca alterado: SHA-256 conferido antes/depois da inspeção e da renderização; `scripts/render_reference.ps1`
  abre somente leitura, sem janela, nunca salva, não encerra um PowerPoint já aberto e recusa saída versionável (só
  `private/`, `output/`, `data/` ou fora do repositório).
- Nada foi enviado a serviços externos/IA. Análise só pela inspeção `strict` (sem texto/números/nomes/imagens). PNGs da
  renderização e diffs (que contêm a referência) ficam em `private/`/`output/` e não são publicados; a documentação
  traz só números agregados.
- Template, tema, fixtures e testes usam apenas dados sintéticos e placeholders genéricos (teste dedicado verifica a
  ausência dos termos da referência no template e no tema).
- Fontes de terceiros: `@fontsource/montserrat|poppins|be-vietnam-pro@5.3.0` (OFL-1.1), versões exatas, sem scripts de
  instalação, servidas localmente (nenhuma requisição a CDN; E2E falha em requisição externa).

## Controles implementados na F06C (homologação visual e preparação para exportação)
- Ativos de marca autorizados só em pasta local (`AFRIKA_BRAND_ASSET_DIR`, padrão `data/brand-assets/`, ignorada; o
  `.gitignore` também ignora qualquer `brand-assets/`). `scripts/check_repo.py` falha se algo sob `brand-assets/` ou
  `data/` for rastreado. Nenhum ativo oficial foi recebido; testes usam imagens sintéticas geradas em pasta descartável.
- Leitura do ativo: nome de tema/encaixe restrito a `[a-z0-9-]` (sem separadores nem `..`), caminho resolvido precisa
  ficar dentro da pasta (links para fora são ignorados), assinatura de bytes, SVG sanitizado (mesmas regras dos ativos
  de tema), ≤ 5 MB, revalidação a cada leitura; resposta com `nosniff`, CSP `default-src 'none'; sandbox`, `no-cache`.
  Arquivo inválido nunca é servido.
- Comparação integral com a referência: só contagens estruturais do relatório `strict` (caracteres/parágrafos/linhas)
  alimentam o conteúdo sintético equivalente; nenhuma renderização da referência nem PNG de diferença foi aberto por
  assistente de IA ou enviado a serviço externo — a análise usou só os números agregados. Saídas em `output/`.
- Plano de exportação (`/export-plan`) é somente leitura e não grava arquivo; segue as mesmas regras de dados (só
  revisões aprovadas fixadas; lacuna nunca vira zero).
- Nenhuma chamada à Veracode; nenhuma dependência nova (backend/frontend).

## Controles implementados na F07 (exportação PPTX/PDF) — detalhes em `docs/EXPORT.md` §7
- Só revisão PERSISTIDA com fonte aprovada e referências íntegras; snapshots/aprovações apenas lidos; nenhuma Veracode.
- Nomes de arquivo e caminhos gerados no servidor; download pelo id aleatório do job; diretório temporário próprio por
  job com limpeza na expiração (30 min) e no desligamento; limites de fila (4), prazo (120 s), tamanho (100 MiB).
- Chromium headless com argumentos fixos (sem shell), perfil descartável, sem rede (`MAP * ~NOTFOUND` + interceptação:
  só `dist/`, a visualização e ativos do tema; qualquer outra requisição falha o job).
- Validação antes do sucesso: PPTX sem macros/ActiveX/OLE/relações externas, XML sem entidades; PDF sem
  JavaScript/Launch/arquivos incorporados/ações automáticas e com fontes incorporadas.
- Repositório: `check_repo` recusa PPTX/PDF e arquivos de fonte rastreados; medições locais só em `output/`.

## Controles implementados na F08 (interpretação dos indicadores) — detalhes em `docs/INTERPRETATION.md` §8
- Padrão local: provedor determinístico `deterministic-demo`, sem rede; envio externo DESLIGADO e nenhum fornecedor
  acoplado (`EXTERNAL_PROVIDERS` vazio). Teste: nenhuma conexão fora do loopback (conftest) e configuração padrão.
- Base para provedor externo futuro com travas: habilitação no ambiente, credencial só em `.env` (`AFRIKA_AI_API_KEY`,
  nunca exposta pela API — `credential_configured` booleano), consentimento explícito por execução, limite diário e de
  tamanho, payload minimizado e recusado com padrão sensível, pré-visualização exata do que seria transmitido, falhas
  com mensagem fixa (sem eco de conteúdo) e nada persistido.
- Contexto só com valores aprovados fixados, variações do backend, estados e notas declaradas; sem findings brutos, sem
  nome do cliente/subcliente e sem rótulos identificáveis de rankings/distribuições (aplicações, BUs, Teams,
  componentes, vulnerabilidades). Notas com e-mail/URL/UUID/segredo recusadas.
- Logs e auditoria só com ids/hashes/tipo/nível/provedor — nunca texto, valores ou notas (teste com `caplog` e
  `audit_events`). Tabelas append-only por gatilho; aprovação humana declarada; texto só entra no slide por nova revisão.
- Exportação nunca chama provedor (teste com motor real que derruba qualquer chamada).
- F07 corrigido na F08: a checagem de conteúdo ativo do PDF procurava `/AA`, `/JS`… também DENTRO de fluxos binários
  comprimidos — falso positivo dependente do texto do slide (reproduzido numa legenda de 240 caracteres). Agora só a
  estrutura (fora de `stream…endstream`) é verificada; dicionário com `/AA` continua recusado (teste unitário).

## Controles implementados na F10 (conferência e piloto local) — detalhes em `docs/F10_PILOT_VALIDATION.md`
- Conferência humana: o servidor lê o valor calculado do snapshot (o cliente nunca o envia; campo extra ⇒ 422);
  registros append-only por gatilho (`metric_conferences_append_only`); auditoria só com indicador/sequência/status
  (sem valores); conferente DECLARADO (sem autenticação). CSV de evidência com `no-store`, `nosniff`, `attachment` e
  neutralização de fórmulas (`=`, `+`, `-`, `@` em textos). Nenhum dado real versionado: valores e capturas ficam em
  `private/`.
- Backup/restauração do SQLite (`python -m app.cli backup-db | restore-db`): cópia consistente pela API de backup do
  SQLite, `integrity_check`, revisão Alembic e SHA-256; destino só fora do repositório ou sob `data/`/`private/`
  (ignorados); restauração exige `--confirm`, backend parado, arquivo íntegro e mesma revisão de esquema, e salva antes o
  banco atual. **Backups não são criptografados**: mesmo conteúdo do banco (nunca credenciais nem findings).
- SCA: o paginador aceita recurso sem identificador por item SOMENTE com metadados de paginação (total anunciado =
  itens recebidos); sem metadados ⇒ resposta recusada (nunca completude presumida).
