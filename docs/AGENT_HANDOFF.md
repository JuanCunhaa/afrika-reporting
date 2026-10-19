# Devolutiva Claude → ChatGPT PO — F09: Homologação ponta a ponta (2026-10-19)

- **Fase / commits:** F09 / `main` / **`9173f1e`** (testes + docs + CI) → commit de checkpoint (STATUS/handoff).
  Push feito. **Nenhuma fase nova iniciada.**
- **CI:** run `39290372716` (SHA `9173f1e`) — **success** (§10).
- Modelo: Opus 5.5 (ambiente). Nenhum subagente. **Nenhum código de produto alterado; nenhuma dependência nova.**
- Veracode real: tenant de testes, **somente GET (≈176)**, 0 POST/PUT/DELETE; POST da Reporting API **não repetido**.
  Nenhuma chamada a provedor externo de IA.

## 1. Resultado do fluxo completo (sintético)
**22/22 etapas PASS** + isolamento + segurança — `backend/tests/test_f09_acceptance.py` (25 testes, um por etapa,
mesmo arquivo SQLite, **reinício real** da aplicação na etapa 22, exportação real PPTX/PDF e download). Repetido 3×
com `AFRIKA_EXPORT_TESTS=required`: 25/25 em cada. Detalhe por etapa: `docs/F09_ACCEPTANCE_MATRIX.md` §1.

## 2. Critérios aprovados
**87 de 93 PASS · 0 FAIL · 2 BLOCKED_EXTERNAL · 3 NOT_VERIFIED · 1 NOT_APPLICABLE** (resumo no topo da matriz; os
35 indicadores são contados à parte, §4).

## 3. Critérios bloqueados / não verificados
- BLOCKED_EXTERNAL: **Findings SCA** (6/28 pedidos de findings com falha de transporte; SCA INCOMPLETE sem valor —
  correto); **Reporting API** (403 da F05; sem mudança de permissão ⇒ POST não executado).
- NOT_VERIFIED: tratamento de **HTTP 500 em real** (nenhum 500 ocorreu; mock PASS); abertura do PPTX/fontes em
  **outros computadores**; intermitência do `f06c.spec.ts` (não reproduzida em 3 rodadas + 10× isolado; causa não
  provada).

## 4. Indicadores
- **Homologados contra o dashboard: 0 de 35.** O dashboard não é acessível ao agente; nenhum número inventado.
- NOT_VERIFIED 16 (VALIDATED pelo Afrika, aguardando conferência humana) · BLOCKED_EXTERNAL 8 (SCA ×6, Reporting ×2)
  · NOT_APPLICABLE 11 (conceito próprio, estado histórico, identidade não comprovada, sem fonte).
- Coerência entre fontes oficiais (não substitui o dashboard): SAST Policy Findings × Summary Report 3/3 coincidentes.
- Valores reais e amostra (nomes/GUIDs) **somente** em `private/f09/live_flow.json` e
  `private/f09/CONFERENCIA_HUMANA.md` (ignorados). Roteiro objetivo (~20 min): `docs/F09_METRIC_RECONCILIATION.md` §5.

## 5. Evidências de exportação
- F09 etapas 19–21: PPTX com nº de slides = visualização, gráficos nativos = planilhas `.xlsx` incorporadas, 0 imagem,
  texto editado e interpretação aprovada presentes; PDF válido com páginas = slides e texto extraído; download com
  SHA-256 (cabeçalho = job = conteúdo), `nosniff`, `no-store`; modelo neutro também exporta PPTX e PDF.
- Etapa 22b: após reinício, a mesma revisão reexporta **o mesmo SHA-256** do PPTX; PDF exportado com os provedores de
  IA proibidos (qualquer chamada derrubaria o teste).
- Fidelidade local com PowerPoint (`export-fidelity.spec.ts`, 1 passed): Afrika HTML×PDF ≤ 0,25 %, HTML×PPTX
  0,04–0,84 %; neutro ≤ 0,39 % / 0,75–2,45 %; texto HTML×PDF ≤ 1 px; 0 quebra divergente — **idêntico à F07**.
- Exportação obrigatória: 82 passed (57 + 25).

## 6. Resultado de segurança (`docs/F09_SECURITY_REVIEW.md`)
17/17 PASS no uso local: nenhuma credencial em respostas, logs (fluxo inteiro em DEBUG), banco, arquivos exportados
ou Git (gitleaks 51 commits 0; `.env` em 0 commits); 0 identificador real em 508 arquivos; 58/58 pedidos reais = GET;
isolamento cliente/subcliente; escopos com versão otimista; snapshots íntegros e imutáveis (API 409 + gatilho SQL);
revisões auditadas; exportação sem macros/links externos/usuário do SO/caminhos; `Host` forjado ⇒ 403; CSRF mitigado
(corpos não-JSON ⇒ 422, CORS restrito); IA externa desligada por padrão.
**O backend NÃO possui autenticação real de usuários (aprovador declarado) e não deve ser exposto.**
Observação O-1 (higiene): o PPTX mantém `printerSettings1.bin` e a miniatura genérica herdadas do template do
python-pptx (inertes; a etapa 23 fixa que a única `.bin` é a da biblioteca). Sem correção — decisão do PO.

## 7. Limitações operacionais (`docs/F09_RELEASE_READINESS.md`)
Uma estação/um operador; coletas e jobs de exportação em memória (reinício ⇒ nova coleta/exportação, com mensagem
explícita); estado atual ≠ fechamento (histórico só por snapshot aprovado); lacunas preenchidas manualmente com
justificativa; SQLite local sem criptografia e backup manual; tema `afrika@2` provisório e sem ativos oficiais.

## 8. Testes executados (sequenciais, Windows local)
| Verificação | Resultado |
|---|---|
| pytest completo (Py 3.14.7) | **PASS — `679` passed** (654 anteriores + 25 F09) |
| Exportação obrigatória (`AFRIKA_EXPORT_TESTS=required`) | **PASS — 82 passed** |
| F09 isolado ×3 (exportação obrigatória) | **PASS — 25/25 ×3** |
| E2E Chromium completo ×3 | **PASS — 40 passed + 3 skipped** em cada rodada (`retries: 0`, `workers: 1`) |
| `f06c.spec.ts` ×10 sem retry | **PASS — 40/40** (intermitência da F08 não reproduzida) |
| Regressão visual | **PASS** win32 (3 rodadas); Linux no CI |
| Fidelidade HTML×PPTX×PDF (PowerPoint local) | **PASS — 1 passed** |
| Build frontend + motor visual | **PASS** (12/12) |
| `npm audit` / `pip check` | **PASS** (0 vulnerabilidades / OK) |
| Gitleaks | **PASS** — histórico 51 commits 0; arquivos novos 0; staged 0 (commit `9173f1e`) |
| `check_repo` / `check_env_example` | **PASS** (estrutura F09 / SEGURO) |
| Migrations (banco novo: migrate, db-status, seed-demo, migrate) | **PASS** (`0007`) |
| Real opt-in: `test_f09_live_flow.py` | **PASS** (1 passed; 58 GET) |
| Real opt-in: `test_veracode_live.py` + `test_scopes_live.py` + `test_reporting_live.py` | **PASS** 18 passed, 1 skipped (Reporting POST não autorizado) |
| Real opt-in: `test_metrics_live.py` | **PASS** (1 passed; 40 GET; Findings × Summary 3/3) |

## 9. Correções / alterações
Nenhum defeito de produto comprovado ⇒ nenhuma correção de produto. Alterações:
- `backend/tests/test_f09_acceptance.py` (novo, 25 testes), `backend/tests_live/test_f09_live_flow.py` (novo, opt-in).
- `.github/workflows/ci.yml`: F09 no job de exportação obrigatória. `scripts/check_repo.py`: entregáveis F09.
- Docs: `F09_ACCEPTANCE_MATRIX.md`, `F09_METRIC_RECONCILIATION.md`, `F09_SECURITY_REVIEW.md`,
  `F09_RELEASE_READINESS.md`, `STATUS.md`, este handoff; `prompts/F09_HOMOLOGATION.md`.
- Achados na construção dos testes (instrumento, não produto): cache de descoberta (TTL) mascarava a falha injetada
  — o teste invalida o cache como o operador faria; duas interpretações no mesmo slide formam uma cadeia (por
  desenho); edição humana nasce `IN_REVIEW` (por desenho).

## 10. Commits e CI
`9173f1e` (F09) e checkpoint docs — em `origin/main`. CI run `39290372716` (SHA `9173f1e`, estrito) — **success**: Backend 3.11 e 3.14 652 passed + 27 skipped cada (os 27 usam o motor real: 23 anteriores + 4 etapas de exportação da F09, que rodam no job próprio); **Exportação PPTX/PDF** obrigatória 82 passed (inclui as 25 da F09); Frontend typecheck + build + motor visual 12/12; E2E Chromium 40 passed + 3 skipped com regressão visual Linux (sem referência nova). Um run duplicado do mesmo push (`39290372470`) foi cancelado pelo grupo de concorrência.

## 11. Recomendação fundamentada de aceite
**Aceitar a F09** como: homologação **funcional** aprovada (sintética), homologação de **integração parcial**
(descoberta, escopos, SAST e Summary em real; SCA e Reporting bloqueados externamente) e homologação **visual**
aprovada localmente com ressalvas. **Indicadores NÃO homologados** (0/35 contra o dashboard). Prontidão operacional:
no máximo **piloto local assistido** (uma estação, números conferidos manualmente antes do uso, lacunas declaradas).
**Prontidão para produção: NÃO** — sem autenticação, indicadores não homologados, SCA/Reporting bloqueados.

## 12. Pendências para o PO
1. Aceite da F09 e decisão sobre o piloto local assistido. 2. Conferência humana dos indicadores no dashboard
(roteiro §5 da conciliação). 3. Pedido de papel/habilitação da Reporting API à Veracode; decisão sobre a fonte de SCA.
4. Decisões herdadas: provedor externo de IA, `AFRIKA_AI_*` no `.env.example`, Be Vietnam Pro no PPTX, ativos de
marca, template visual oficial. 5. Observação O-1 (remover partes herdadas do template python-pptx?).

## 13. Prompt sugerido para a próxima fase (NÃO executado)
> **F10 — Conferência dos indicadores e fundação de produção (somente com ordem do PO).** Ler `CLAUDE.md`,
> `docs/STATUS.md`, `docs/F09_RELEASE_READINESS.md`, `docs/F09_METRIC_RECONCILIATION.md`. (a) Registrar, a partir da
> conferência humana feita pelo PO/usuário, o status MATCH/MISMATCH de cada indicador (sem versionar valores reais) e
> investigar divergências na nossa consulta; (b) se aprovado, desenhar autenticação local com segregação de funções
> (operador × aprovador × revisor) sem quebrar o fluxo homologado; (c) reavaliar SCA/Reporting só após mudança de
> permissão confirmada. Sem deploy, sem novas integrações externas e sem provedor de IA externo sem decisão do PO.
