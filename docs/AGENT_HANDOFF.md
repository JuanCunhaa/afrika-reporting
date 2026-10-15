# Devolutiva Claude → ChatGPT PO — F04.1: Veracode API Discovery & Reliability (2026-10-15)

- **Fase / commits:** F04.1 / `main` / **`0568326`** (código + testes + docs técnicas) + commit seguinte só com STATUS/handoff. Push feito. **F05 NÃO iniciada.**
- **CI:** run `38681179717` (SHA `0568326`) **success** — Backend 3.11 e 3.14, Frontend typecheck+build, E2E Chromium.
- Modelo: Opus 5.5. Nenhum subagente. Matriz completa: `docs/API_SOURCE_MATRIX.md`.

## 1. APIs investigadas
Especificações oficiais da Veracode no SwaggerHub: Applications 1.0, Findings 2.1, Summary Report v2, Reporting 1.12.0, SCA Agent 3.0, Policy 1.0, Development Sandbox 2.0, Identity 1.5, Healthcheck 1.0 (+ páginas docs.veracode.com de Findings, Reporting e Summary Report). Repositório `ancient-cthulhu/Veracode-All-Findings-Extract`: **sem licença** ⇒ só estudado (paginação por `total_pages` + `_links.next`, `size=500`, retry de 500, reconciliação `total_elements` × coletado, SCA por chamada separada, mapeamento de agente por GUID **ou nome** — não adotado, IaC por endpoint interno de UI — proibido). Nada copiado.

## 2. Endpoints realmente testados (tenant de testes, só GET)
`/appsec/v1/applications` (+ `scans[]`), `/appsec/v2/applications/{guid}/findings` (STATIC/SCA, Policy/Sandbox, `size` 1/10/50/100), **`/appsec/v2/applications/{guid}/summary_report`** (novo), **`/srcclr/v3/applications/{guid}/projects`** (novo), `/appsec/v1/applications/{guid}/sandboxes`. Não testados: Reporting (POST), Policy, workspaces/issues do SCA Agent (fora da allowlist).

## 3. Indicadores com fontes alternativas (novos)
`sast.policy.summary.by_severity` (Summary Report), `sast.policy.reconciliation` (Findings × Summary Report), `apps.loc.total` (Summary Report), `apps.by_policy_compliance` (perfil), `sca.policy.summary.components` (Summary Report), `sca.agent.linked_projects` (SCA Agent), `scans.covered_apps` (perfil `scans[]`; antes UNSUPPORTED). Na amostra real: Summary Report, LOC, conformidade, componentes SCA, SCA Agent e cobertura de scans saíram VALIDATED; reconciliação coincidiu onde as duas fontes responderam.

## 4. Diagnóstico dos HTTP 500
H1 (sem scan do tipo) refutada — `scans[]` real não lista SCA; H2 (`size=100`) **refutada — corrige a conclusão da F04**; H4 (permissão) refutada; H3 (Summary Report responde) confirmada; H5 ("aquecimento": 500 em ~3,3 s, sucesso após ~20 s) confirmada para STATIC; H6 (SCA sem componentes ⇒ 500) **inconclusiva** (também houve 500 com componentes). Conclusão: falha intermitente do lado da Veracode com padrão de tempo-limite interno; não comprova licença/permissão. Implementado: 500 sem retry imediato + passada adiada única (20 s); circuit breaker por (recurso, tipo, contexto), limiar 5; pré-checagem SCA `verify|skip|off` (ausência só **inferida** ⇒ INCOMPLETE). Pipeline real: de 73 GETs/48 retries/~300 s (F04) para 31 GETs/0 retries imediatos/47 s na mesma amostra; passada adiada recuperou 1 de 3.

## 5. Bloqueadas por POST
Reporting API (FINDINGS, SCANS, DELETEDSCANS, AUDIT: `POST /appsec/v1/analytics/report` + `GET …/{id}`) — teria `resolved_date`, `fixed_date`, `reopened_date`, `found_date`, `last_updated_date`, scans por período (máx. 6 meses). Também POST/PUT/DELETE: vínculo de projetos/agentes do SCA Agent, SBOM scan, promoção de sandbox.

## 6. Métricas que podem reproduzir dashboards
Nenhuma **comprovada** (comparação com dashboard NOT_RUN). Candidatas mais fortes (definição por GUID/contagem direta): `apps.total`/`by_business_unit`/`by_team`, `apps.by_policy_compliance`, `sast.policy.summary.by_severity` e `sast.policy.open.by_severity` (quando coincidem), `apps.loc.total`.

## 7. Ainda não homologadas
Todas contra dashboard; formato SCA (Findings) por instabilidade; identidade entre contextos (`issue_id`); definição de "aberto" × mitigados; findings fechados por padrão; semântica de `third_party_components`; contexto de `scans[]`; issues do SCA Agent; licenças; densidades; tendências.

## 8. Testes
| Verificação | Resultado |
|---|---|
| `python -m pytest -q` | **PASS 329** (303 + 26: 14 em `test_metrics_sources.py`, 7 de fuso/DST, allowlist +6, migração) |
| venv novo só pelo lock (`tzdata==2026.5` incluído) | PASS 329 |
| E2E Chromium | **PASS 19/19** (painel com fuso, Summary Report, reconciliação, SCA Agent, cobertura de scans) |
| build; `npm audit --omit=dev`; `pip check` | OK; 0 vulnerabilidades; OK |
| gitleaks (staged); `check_repo`; `check_env_example` | 0; OK; SEGURO |
| `tests_live` sem opt-in | 19 SKIPPED |
| Real opt-in `test_metrics_live.py` | PASS 1/1 (2 execuções) + diagnósticos ≈ 150 GETs na fase |
| CI `38681179717` | **success** |
Fuso: `America/Sao_Paulo` padrão por cliente (migration `0003_client_timezone`; subclientes herdam; sobrescrita por execução); testes de limites de mês, horário de verão 2017/2018 e 2018/2019, abolição em 2019, meia-noite inexistente (Havana 2012), mês fechado no fuso do cliente, nome IANA validado (sem caminho de arquivo).

## 9. Riscos
1. Findings API instável no tenant ⇒ indicadores Findings tendem a INCOMPLETE em coleta real; o Summary Report cobre severidade SAST por build, não "aberto" por status.
2. Summary Report reflete o build mais recente; tratamento de mitigados não documentado ⇒ pode divergir da Findings (a reconciliação sinaliza).
3. Pré-checagem SCA baseada em correlação (H6 inconclusiva).
4. Custo: +2 GETs por aplicação (Summary Report, SCA Agent); orçamento padrão 2000.
5. `tzdata` adicionado como dependência (Apache-2.0) — necessário no Windows.

## 10. Pendências para F05
Snapshots aprovados por competência (só agregados, `input_hash`, versões de contrato/escopo, fuso e intervalo UTC); entrada manual tipada para lacunas (resolvidos no mês, scans, licenças, histórico); decisão do PO sobre pedir à Veracode a habilitação da Reporting API **e** uma exceção à política GET-only (POST de geração de relatório), ou mantê-la fora; conferência humana contra dashboard das candidatas do item 6; decidir `sca_precheck` padrão (`verify` × `skip`) e o tratamento de mitigados.

---

