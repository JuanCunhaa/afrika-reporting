# Estado do projeto

- F00: DONE_LOCAL
- F01 — clientes/subclientes: DONE_LOCAL — aprovada localmente pelo PO
- F01.1 — hardening e CI: DONE_LOCAL — aprovada localmente pelo PO (`.env.example` versionado em `d71f39e`)
- **F02 — conector Veracode read-only + descoberta: DONE_LOCAL — aguardando PO** (commit `5fce8bf`; validado só com tenant sintético; integração real NOT_VERIFIED; CI GitHub **verde** em `7fcfc92`)
- **F02.1-prep — `.env` local + trava read-only + homologação opt-in: DONE_LOCAL — aguardando PO** (commit `d3fa15f`)
- **F02.1 — homologação real Veracode: DONE — aguardando PO** (commit `7c52d57` + docs; 11/11 domínios VERIFIED_REAL — paginação Identity multipágina e 403/429 só em mock; 1 incompatibilidade corrigida)
- **F03 — motor de escopos e filtros: DONE — aguardando PO** (commits `2d9192f` + `17743cc` + docs; CI verde run `38670035298`)
- **F04 — motor de indicadores: DONE — aguardando PO** (commit `ddf3b01` + docs; CI verde run `38677349116`; homologação real parcial: STATIC ok, SCA bloqueado por HTTP 500 da Veracode)
- **F04.1 — fontes alternativas e confiabilidade: DONE — aguardando PO** (commit `0568326` + docs; CI verde run `38681179717`)
- **F05 — snapshots, histórico, aprovações e Reporting API: DONE_LOCAL — aprovada pelo PO** (commit `ad4b91f` + docs; CI verde run `38746312757`; Reporting API real: HTTP 403 — BLOCKED_EXTERNAL)
- **F06A — motor de templates e pré-visualização: DONE_LOCAL — aguardando PO** (commit `c160494` + docs; CI verde run `38776201083`; tema demonstrativo neutro PROVISÓRIO)
- **F06B.1 — preparação do motor visual oficial: DONE — aguardando PO** (commits `4cc9c61`, `e21ebce`, `8169e82` + docs; CI estrito verde run `38814645692`)
- **F06B — template de referência Afrika: DONE — aguardando PO** (commits `30446df`, `edcce8b`, `aaa54e9`, `54d1ba4` + docs; CI estrito verde run `38831748989`; tema `afrika@1` PROVISÓRIO)
- **F06C — homologação visual e preparação para exportação: DONE — aguardando PO** (commits `42a64e4`, `80c6f17` + docs; CI estrito verde run `38923537613`; tema `afrika@2` PROVISÓRIO)
- **F07 — exportação PPTX/PDF (+ F07.1 retomada e finalização): DONE — aprovada pelo PO (ordem F08)** (commits `23151ae`, `5d73c67` + docs; CI estrito verde run `38996755783`)
- **F08 — interpretação dos indicadores (assistida, com revisão humana): DONE — aprovada pelo PO (ordem F09)** (commit `c1766a5` + docs; CI verde run `39263203988`)
- **F09 — homologação ponta a ponta: DONE — aguardando aceite do PO** (commit `9173f1e` + docs; ver checkpoint F09; produção NÃO pronta)

## Checkpoint F09 (2026-10-19)
- Homologação funcional sintética: `backend/tests/test_f09_acceptance.py` — 22/22 etapas da ordem do PO + isolamento
  + segurança (25 testes), reinício real da aplicação no mesmo SQLite, exportação real PPTX/PDF e download.
- Homologação real (tenant de testes, **somente GET**, ≈176 pedidos; 0 POST): `backend/tests_live/test_f09_live_flow.py`
  (pilha completa, 58/58 GET registrados) + suítes live anteriores 18 passed / 1 skipped (Reporting POST não repetido
  — 403 sem mudança de permissão). Inventário/BUs/Teams/usuários/paginação/Summary/SAST PASS; SCA BLOCKED_EXTERNAL
  (falhas de transporte); HTTP 500 real não ocorreu (mock PASS). Valores reais só em `private/f09/` (ignorado).
- Indicadores: **0/35 homologados** contra o dashboard (inacessível ⇒ NOT_VERIFIED 16, BLOCKED_EXTERNAL 8,
  NOT_APPLICABLE 11); roteiro de conferência humana em `docs/F09_METRIC_RECONCILIATION.md` §5.
- Segurança: 17/17 PASS no uso local; **backend sem autenticação real — não expor**. Observação O-1 (resíduos
  inertes do template python-pptx no PPTX). Docs: `docs/F09_ACCEPTANCE_MATRIX.md`, `docs/F09_SECURITY_REVIEW.md`,
  `docs/F09_RELEASE_READINESS.md`.
- Nenhum defeito de produto comprovado; nenhum código de produto alterado; nenhuma dependência nova.
- Testes (local, sequenciais): pytest **679 passed**; exportação obrigatória **82 passed**; F09 isolado 25/25 ×3; E2E
  Chromium 3 rodadas **40 passed + 3 skipped**; `f06c.spec.ts` ×10 sem retry 40/40 (intermitência da F08 não
  reproduzida); fidelidade HTML×PPTX×PDF com PowerPoint 1 passed (idêntica à F07); build + motor visual 12/12;
  `npm audit` 0; `pip check` OK; gitleaks histórico/novos/staged 0; `check_repo`/`check_env_example` OK; migrations
  CLI OK (`0007`).
- CI run `39290372716` (`9173f1e`, estrito): **success** — Backend 3.11/3.14 652 passed + 27 skipped, Exportação 82
  passed, E2E 40 passed + 3 skipped (visual Linux), build + motor visual.

Próxima autorização esperada: aceite da F09 pelo PO (piloto local assistido ou não); nenhuma fase nova sem ordem
expressa.

## Checkpoint F08 (2026-10-19)
- `backend/app/interpretation/` (contratos, contexto fundamentado, provedor determinístico `deterministic-demo` + base
  `ExternalProvider` com travas — nenhum fornecedor acoplado —, validador determinístico, serviço) +
  `api_interpretations.py` + migration `0007_interpretations` (versões/eventos/desativação append-only) + painel
  "Análise do slide" no editor. Docs: `docs/INTERPRETATION.md`; contratos em `docs/PRESENTATION_CONTRACTS.md`;
  `docs/SECURITY.md` (F08).
- 11 tipos × 2 níveis; contexto só com aprovados fixados, variações do backend, estados e notas declaradas (sem nomes
  de aplicações/BUs/Teams/componentes/vulnerabilidades nem do cliente). Validação: números, percentuais/unidades,
  período, fatos, ausências, direção/tendência, causas/remediação/remoção/maturidade/risco/absolutos, tamanho, dados
  sensíveis. Fluxo GENERATED → IN_REVIEW → APPROVED | REJECTED; editar/regenerar = nova versão; comparar; desabilitar
  por slide; desatualização (fontes/fatos/slide) bloqueia aprovar/aplicar; aplicar = nova revisão da apresentação
  (sobrescrita só com confirmação).
- Limites de texto por layout MEDIDOS com o motor real de exportação (afrika@2 e neutral-demo).
- Correção F07: falso positivo de conteúdo ativo no PDF (`/AA` em bytes de fluxo comprimido) — só a estrutura é
  verificada agora.
- pytest **654 passed** (579 + 75); exportação obrigatória **57 passed** (54 + 3); E2E Chromium completo 3 rodadas
  (ver handoff; 1 falha intermitente em `f06c.spec.ts` na 1ª rodada, não reproduzida); visual win32 62/62; motor visual
  12/12; build OK; `npm audit` 0; `pip check` OK; `check_repo`/`check_env_example` OK; migrations CLI OK (`0007`).
- CI run `39263203988` (`c1766a5`): **success** — Backend 3.11/3.14 631 passed + 23 skipped, Exportação 57 passed,
  E2E 40 passed + 3 skipped (visual Linux incluído), build + motor visual.
- Nenhuma chamada à Veracode; nenhuma chamada a provedor externo de IA; nenhuma dependência nova.

Próxima autorização esperada: aceite da F08 pelo PO (decisões: fornecedor externo de IA ou manter só o local;
`.env.example` com `AFRIKA_AI_*`); F09 só com ordem expressa.

## Checkpoint F07 / F07.1 (2026-10-17)
- `backend/app/export/` + `api_exports.py` + CLI `export` + painel Exportar: PPTX com objetos NATIVOS (texto, formas
  `custGeom`, tabelas, gráficos com planilha incorporada; lacuna = célula vazia; 0 imagem de dado) e PDF impresso do
  MESMO HTML da pré-visualização (Chromium headless via CDP, sem rede, build carimbado). Só revisão persistida com fonte
  aprovada e referências íntegras; overflow/fonte de reserva bloqueiam com diagnóstico por slide; pacote determinístico.
  Docs: `docs/EXPORT.md` (matriz de editabilidade, fontes, segurança), `docs/EXPORT_FIDELITY.md`.
- Editáveis medidos: `afrika-modelo@2` 469 objetos (301 texto, 146 formas, 10 linhas, 6 tabelas, 6 gráficos nativos),
  `neutral-demo` 273; imagens 0.
- Fidelidade (local, Windows + PowerPoint): HTML×PDF ≤ 0,25% (afrika) / ≤ 0,39% (neutro), texto ≤ 1 px; HTML×PPTX
  0,04–0,82% (afrika) / 0,75–2,45% (neutro, fonte de sistema × Arial); 0 quebra de linha divergente.
- F07.1: desvio da matriz corrigido (linha do cabeçalho crescia 5 px no PowerPoint; Δy 4→0, p95 7→2 px); slide 11
  corrigido (HTML abreviava "Outros (fo…" — agora quebra em linhas; 1,77%→0,66%); abreviação residual bloqueia.
- Fontes: declaradas e incorporadas (EOT); PowerPoint local APLICA Montserrat/Poppins incorporadas sem instalação e NÃO
  aplica Be Vietnam Pro (reproduzido com a incorporação do próprio PowerPoint); outro computador NOT_VERIFIED; PDF com
  todas as fontes incorporadas.
- Dependências: python-pptx 1.0.2, lxml 6.1.3, pillow 12.3.0, xlsxwriter 3.2.9 (lock; venv novo `pip check` OK).
- pytest **579 passed**; export obrigatório **54 passed**; E2E Chromium **38 passed + 3 skipped**; fidelidade local 1
  passed (2 execuções idênticas); visual win32 **62/62** e Linux (CI) **62/62**; motor visual 12/12; build OK; `npm
  audit` 0; `pip check` OK; gitleaks staged 0 (2 commits); `check_repo`/`check_env_example` OK; migrations OK (0006,
  nenhuma nova).
- CI: run `38996490059` (`23151ae`, bootstrap temporário de 1 referência Linux) success; run `38996755783` (`5d73c67`,
  estrito) **success** — Backend 3.11/3.14 558 passed + 21 skipped (motor real fica no job próprio), Exportação 54
  passed, E2E 38 passed + 3 skipped, Frontend build + motor visual.
- Nenhuma chamada à Veracode; nenhum PPTX/PDF/fonte/dado real versionado.

Próxima autorização esperada: aceite da F07 pelo PO (decisão sobre Be Vietnam Pro no PPTX); F08 só com ordem expressa.

## Checkpoint F06C (2026-10-16)
- Semântica de cores do PO por tokens: tema `afrika@2` (severidade por nível — Crítica vermelho, Alta laranja, Média amarelo, Baixa azul, Informativa cinza; variação comprovada — melhora verde, piora vermelho, neutra) + `afrika-modelo@2` (mesmos 16 slots, cópia programática). Direção desejável por indicador (`Direction`, padrão neutro; só backlog aberto declara `LOWER_IS_BETTER`); IR de comparação com `trend`. Docs: `docs/THEMES.md`, `docs/PRESENTATION_CONTRACTS.md`, `docs/METRIC_CATALOG.md`.
- Hashes de `neutral-demo@1`, `afrika@1` e de todos os templates anteriores inalterados (fixados em teste); 54 slides visuais antigos idênticos.
- Seleção flexível de slides na criação (`slots` + disponibilidade por slot na revisão aprovada; só capa/encerramento obrigatórios).
- Ativos de marca por encaixes do tema + pasta local ignorada (`AFRIKA_BRAND_ASSET_DIR`), fallback neutro; nenhum ativo oficial recebido.
- Fidelidade: comparação mascarada (F06B) mantida com os mesmos números + comparação INTEGRAL por categoria com conteúdo sintético equivalente (tipografia declarada 24/24, gráficos 16/16, estrutura ≤0,8%, overflow 0); 2 defeitos corrigidos no `afrika@2`; demais diferenças classificadas. Doc: `docs/VISUAL_FIDELITY.md`.
- F07 preparada (não implementada): plano de exportação por elemento + matriz de editabilidade (0 dado como imagem; lacuna = célula vazia). Doc: `docs/F07_EXPORT_READINESS.md`.
- Overflow/fontes: detector no DOM (Windows e Linux) e bloqueio de fontes de reserva nos casos Afrika — 0 achados.
- pytest **525 passed**; E2E Chromium **35 passed + 2 skipped** em 3 rodadas completas (repetições extras ×5 interrompidas por falta de memória na máquina — NOT_RUN); visual win32 **62/62** e Linux (CI) **62/62**; motor visual 12/12; build OK; `npm audit` 0; `pip check` OK; gitleaks staged 0; `check_repo`/`check_env_example` OK; migrations CLI OK (sem migration nova).
- CI: run `38923537613` (SHA `80c6f17`, estrito): **success** (Backend 3.11/3.14 525 passed; build + motor visual 12/12; E2E 35 passed + 2 skipped; visual Linux 62/62). Referência Linux do `afrika-v2` criada por bootstrap temporário (run `38922993662`), revisada e o bootstrap removido.
- Nenhuma chamada à Veracode nesta fase.

Próxima autorização esperada: aceite da F06C pelo PO (confirmações: "Muito baixa"→Baixa, rótulo "Crítica", direções; ativos de marca); F07 só com ordem expressa.

## Checkpoint F06B (2026-10-15)
- PowerPoint de referência só local (`references/`, ignorado, nunca rastreado; SHA-256 inalterado); análise só estrutural (inspeção `strict`), render local em `private/`; nada enviado a serviços externos; `check_repo` barra arquivos de referência rastreados e o nome do cliente da referência (via SHA-256).
- Template `afrika-modelo@1` (16 slots) + tema `afrika@1` (provisório): tipos novos `section` e `dashboard` (6 layouts com zonas tipadas e editáveis), layouts `kpi-band`, `severity-cards`, `donut`, `matrix`, gráfico `combo`, comparação em colunas, formas com contorno/opacidade, selo de competência; fontes OFL locais. Doc: `docs/AFRIKA_TEMPLATE.md`.
- Genérico: placeholders sintéticos, qualquer cliente/subcliente, indicadores por `metric_id` validados por zona, nº de slides configurável (só capa/encerramento obrigatórios). Hashes de `neutral-demo@1` e dos templates F06A inalterados.
- Fidelidade estrutural medida por slide (conteúdo mascarado): capa 0,1%, seções 0,3%, painéis 0,4–1,8%, matrizes 0,6%, encerramento 0,7% (Δ>0,08); 41/67 pares geométricos em ≤2 px. Limitações: imagens de marca ausentes, cor de variação neutra, severidade × cor a confirmar.
- pytest **498 passed**; E2E **31 passed + 1 skipped** (comparação local) em 3 rodadas; visual win32 **54/54**; motor visual 12/12; build OK; `npm audit` 0; `pip check` OK; gitleaks staged 0 achados (em cada commit); `check_repo`/`check_env_example` OK; migrations CLI OK.
- CI: GitHub run `38831748989` (SHA `54d1ba4`, estrito): **success** (Backend 3.11/3.14 498 passed; build + motor visual 12/12; E2E 31 passed + 1 skipped; visual Linux 54/54). Referência Linux do caso `afrika` criada por bootstrap temporário (runs `38829304285`, `38830508073`, `38831429248`), revisada e o bootstrap removido; a 1ª captura Linux revelou estouro no painel de grupos e fonte de reserva na seta — ambos corrigidos antes de versionar.
- Nenhuma chamada à Veracode nesta fase.

Próxima autorização (na época): aceite da F06B — concedido; seguiu-se a F06C.

## Checkpoint F06B.1 (2026-10-15)
- Temas versionados com tokens completos (`themes.py`, migration `0006_themes` append-only, ativos locais por SHA-256 fora do Git, API/CLI); renderizador e CSS só leem tokens; tema por cliente via template. Docs: `docs/THEMES.md`.
- Compatibilidade F06A: conversão do tema neutro 19/19 idêntica (pixel + manifesto); 3 correções deliberadas com diff (legenda × rodapé, período ISO, gráfico encolhido) + rótulos de mês rarefeitos; hash de `neutral-demo@1` fixado em teste.
- Inspeção PPTX local (`inspect-pptx`, stdlib, sem conteúdo; `strict`/`structural`; rascunho de tema não aprovado) testada só com PPTX sintético. Doc: `docs/PPTX_INSPECTION.md`.
- Motor visual próprio (`frontend/visual/`): captura `#/render`, manifesto (geometria, hash de texto, fontes de plataforma via CDP), diff YIQ + antisserrilhado separado, categorias conteúdo/fonte/layout/estilo/rasterização; referências win32 (38 slides, 2 temas) com ruído medido 0. Doc: `docs/VISUAL_REGRESSION.md`.
- Editor: D1 (edição durante salvamento perdida) e D2 (pré-visualização tardia após Descartar) reproduzidos e corrigidos; releitura falha após 200 informada; duplo clique = 1 PUT. Intermitência F06A: NOT_REPRODUCED (60 s de carga real, 4.335 req., 0 erros, máx. 744 ms; 50/50 repetições E2E).
- Referências visuais Linux criadas pelo CI (bootstrap temporário, já removido) e revisadas: a 1ª captura revelou rótulos de mês sobrepostos (largura estimada só servia para Segoe UI) — corrigido com medição real (`e21ebce`); ruído Linux 0 e 37/38 idênticos entre duas execuções de CI.
- pytest **479 passed** (438 + 41); E2E Chromium **30 passed** (24 + 6) em 3 rodadas completas; motor visual 11/11; build OK; `npm audit` 0; `pip check` OK; gitleaks staged 0; `check_repo`/`check_env_example` OK; migrations CLI OK (`0006_themes`).
- CI GitHub run `38814645692` (SHA `8169e82`, estrito): **success** (Backend 3.11/3.14 479 passed; build + motor visual 11/11; E2E 30 passed; visual Linux 38/38).
- Nenhuma chamada à Veracode nesta fase.

Próxima autorização esperada: aceite da F06B.1 pelo PO + PPTX de referência aprovado (fora do repo) para a reprodução definitiva.

## Checkpoint F06A (2026-10-15)
- `backend/app/presentations/` + migration `0005_presentations` (templates versionados append-only, escolha por dono, apresentações, revisões append-only com hash encadeado; gatilho: só revisão de competência APROVADA). Docs: `docs/PRESENTATIONS.md`, `docs/PRESENTATION_CONTRACTS.md`.
- 11 tipos de slide; 3 templates demonstrativos sintéticos; IR de gráficos (bar/line/severity/ranking/comparison/table/kpi); fontes fixadas (principal + 11 meses) e `rebind` explícito; editor HTML 16:9 com pré-visualização ao vivo sem gravação, dados de origem, revisões e integridade.
- pytest **438 passed** (411 + 27); E2E Chromium **24 passed** (22 + 2) em 3 rodadas completas locais + CI; build OK; `npm audit` 0; `pip check` OK; gitleaks staged 0; `check_repo`/`check_env_example` OK; migrations CLI OK (`0005_presentations`).
- `scopes.spec.ts`: não reproduzido (6 repetições isoladas + 6 suítes completas + sonda com CPU 20× lenta); sem retry adicionado. Editor: 1 falha intermitente em ~51 execuções (GET após salvar sem resposta) — causa NOT_PROVEN; UI passou a derivar o estado salvo da resposta do PUT.
- Nenhuma chamada à Veracode nesta fase.

Próxima autorização esperada: aceite da F06A pelo PO; F06B só com ordem expressa.

## Checkpoint F05 (2026-10-15)
- Migration `0004_snapshots`: competences, competence_revisions, metric_snapshots, manual_changes, approvals, audit_events, collection_runs + view `v_official_revisions`; gatilhos de imutabilidade/append-only; downgrade recusado com aprovações. Doc: `docs/SNAPSHOTS.md`.
- Ciclo DRAFT → READY_FOR_REVIEW → APPROVED com `expected_lock_version` (conflito 409); aprovador **declarado** (sem autenticação); obrigatórios explícitos e versionados; hashes por snapshot, conteúdo aprovado e cadeias (aprovações e auditoria).
- Histórico só de aprovados (6/12 meses, intervalo, mês × anterior), lacunas explícitas, sem interpolação.
- Reporting API: adaptador FINDINGS/SCANS (POST de geração único, deny-by-default, desligado por padrão); mocks PASS; geração real: 1 POST ⇒ **HTTP 403** (BLOCKED_EXTERNAL: papel/habilitação ausentes na conta de testes).
- pytest **411 passed** (329 + 82); E2E Chromium **22 passed** (19 + 3; 1 falha intermitente em `scopes.spec.ts` numa de 4 rodadas completas); build OK; `npm audit` 0; `pip check` OK; `check_repo`/`check_env_example` OK; migrations CLI OK; `tests_live` sem opt-in 20 SKIPPED.
- CI GitHub run `38746312757` (SHA `ad4b91f`): **success** (Backend 3.11/3.14, build, E2E).

Próxima autorização esperada: aceite da F05 pelo PO; F06 só com ordem expressa.

## Checkpoint F04.1 (2026-10-15)
- Inventário oficial (SwaggerHub) + matriz por indicador: `docs/API_SOURCE_MATRIX.md`. Allowlist: + Summary Report e SCA Agent (projetos por aplicação), ambos GET. Reporting API: BLOCKED_POST.
- Diagnóstico 500: intermitente do lado da Veracode (padrão ~3 s); `size=100` refutado (corrige F04); permissão refutada; SCA sem componentes = indício. Mecanismos: sem retry imediato do 500, passada adiada, circuit breaker, pré-checagem SCA.
- 7 indicadores novos de fontes alternativas; fuso IANA por cliente (padrão America/Sao_Paulo, migration 0003, tzdata 2026.5).
- pytest **329 passed**; venv do lock 329; E2E **19 passed**; build OK; `npm audit` 0; `pip check` OK; gitleaks 0; checks OK; real opt-in PASS (≈150 GETs na fase).
- CI GitHub run `38681179717` (SHA `0568326`): **success**.

Próxima autorização esperada: aceite da F04.1 pelo PO; depois prompt F05.

## Checkpoint F04 (2026-10-15)
- `backend/app/metrics/` (contratos tipados, registro de 29 indicadores — 20 calculados + 9 lacunas UNAVAILABLE/UNSUPPORTED, competência fechada, população F03, coletor, motor, execuções em memória), `api_metrics.py`, painel `#/metrics`. Catálogo: `docs/METRIC_CATALOG.md`.
- Allowlist: + `GET /appsec/v2/applications/{guid}/findings` (só). `findings_page_size=50` (real: `size=100` ⇒ 500).
- pytest **303 passed** (259 + 44 novos); E2E Chromium **19 passed** (17 + 2); build OK; `npm audit` 0; `pip check` OK; gitleaks (staged) 0; `check_repo`/`check_env_example` OK; `tests_live` sem opt-in 19 SKIPPED.
- Homologação real opt-in (`tests_live/test_metrics_live.py`, amostra de 3 apps, só GET, ≈300 GETs na fase com diagnóstico): STATIC VERIFIED_REAL (formato/paginação); SCA BLOCKED_EXTERNAL (500); identidade entre contextos NOT_PROVEN; comparação com dashboard **NOT_RUN**.
- CI GitHub run `38677349116` (SHA `ddf3b01`): **success** (Backend 3.11/3.14 303 passed; build; E2E 19 passed).


## Checkpoint F03 (2026-10-14)
- Escopos por dono (cliente/subcliente) × domínio (applications/users/scans/SCA); versões append-only (migration `0002_scopes`, gatilhos); AST com AND/OR/NOT, limites e lógica de 3 valores; universo, interseção, outro tenant com confirmação, sobreposição, não classificadas; reconciliação `team_count`; inativos fora por padrão (configurável); UI simples/avançada com pré-visualização. Doc: `docs/SCOPES.md`.
- pytest **256 passed** (213 + 43); E2E Chromium **17 passed** (14 + 3); build OK; `npm audit` 0; `pip check` OK; gitleaks (staged) 0; `check_repo`/`check_env_example` OK.
- Validação real opt-in (`tests_live/test_scopes_live.py`, só GET, ~22 requisições): **2 passed**; `team_count` presente nos membros de Team reais; reconciliação 100% `verified`. Contagens só no relatório ao PO.
- CI GitHub run `38670035298` (SHA `17743cc`): **success** (Backend 3.11/3.14 256 passed; build; E2E 17 passed).


## Checkpoint F02.1 (2026-10-14)
- Tenant REAL de testes (região `commercial`), somente GET; flag live só no ambiente do processo (`.env` intacto, `VERACODE_LIVE_TESTS_ENABLED=false` nele).
- 1ª credencial rejeitada pela Veracode (401 "API ID … is invalid for user") — causa externa; HMAC idêntico à implementação oficial (200/200). Usuário substituiu a credencial → 200.
- `tests_live` **16 passed** (real); pytest **213 passed** (201 + 12 regressões); E2E Chromium **14 passed**; build OK; `npm audit` 0; gitleaks (staged + histórico) 0.
- Correção: `relationship` do membro de Team é objeto na API real; fixture sintético alinhado ao formato real; `account_type` não é mais anunciado como filtro.
- Matriz por domínio: `docs/VERACODE_INTEGRATION.md` → "Homologação real (F02.1) — resultado". Contagens do tenant não versionadas (repo público).


## Checkpoint F02.1-prep (2026-10-14)
- `.env` criado na raiz (ignorado pelo Git; nunca versionado — 0 commits no histórico); campos a preencher: `AFRIKA_VC_TEST_API_ID`, `AFRIKA_VC_TEST_API_KEY`.
- pytest **201 passed** (144 anteriores + 57 novos); `tests_live` 6 SKIPPED por padrão; E2E Chromium **14 passed**; build OK; `pip check` OK; gitleaks (staged) 0 achados.
- Testes reais: **NOT_RUN** (proibido nesta tarefa). Integração real: NOT_VERIFIED.

## Publicação pública (2026-10-14) — não é fase de produto
- Repo **público** https://github.com/JuanCunhaa/afrika-reporting (`origin`, branch `main`). Sem deploy.
- Licença: PolyForm Noncommercial 1.0.0 integral (blob `5ecc88c` = upstream tag `1.0.0`) + `NOTICE` (titular JuanCunhaa, declarado pelo usuário).
- Auditoria: gitleaks no histórico (8 commits) e na árvore HEAD — 0 achados; só dados sintéticos.
- CI GitHub run `38646957227` (SHA anterior à reescrita): **success**; histórico reescrito em 2026-10-14 só para remover trailers `Co-Authored-By` (árvores idênticas, SHAs novos) e CI reexecutado (Backend 3.11/3.14 144 passed cada; build OK; E2E 14 passed).

## Checkpoint F02 (2026-10-14)
- pytest **144 passed** (Py 3.14.7; `.venv` e venv novo só pelo lock) + 5 testes live opt-in SKIPPED; E2E Chromium **14 passed** (5 novos F02); build OK; `npm audit` 0 vulnerabilidades; `pip check` OK.
- Integração real com a Veracode: **NOT_VERIFIED** (sem credenciais autorizadas; nenhuma chamada real executada).
- Sem remote Git; CI GitHub NOT_RUN. Detalhes: `docs/AGENT_HANDOFF.md`, `docs/VERACODE_INTEGRATION.md`.


## Checkpoint F01.1 (2026-10-14)
- pytest **59 passed** (Py 3.14.7) no `.venv` e num venv novo instalado só pelo lock; E2E Chromium **9 passed** (inclui 4 de API indisponível); build OK; `pip check` OK.
- Lock `backend/constraints.txt` resolve com wheels para CPython 3.11 e 3.14 (Linux/Windows). Execução em 3.11: NOT_VERIFIED localmente.
- Sem remote Git. Publicação pública BLOQUEADA (licença, titularidade, autenticação).
- `.env.example` ainda NÃO versionado na época — resolvido em `d71f39e` (verificador: SEGURO).

