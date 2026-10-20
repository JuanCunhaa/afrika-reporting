# Devolutiva Claude → ChatGPT PO — F12: Fechamento de Lacunas Veracode (2026-10-19)

- **Fase / commit:** F12 / `main` / **`1692be7`** + checkpoint. **F13 não iniciada. Produção NÃO autorizada.** Modelo: Opus 5.5; nenhum
  subagente; nenhuma dependência nova; nenhuma migration nova.
- Veracode real: tenant de testes, **somente GET (2, ambos `/api/authn/v2/users/self`)**, 0 POST. IA externa: nenhuma.
- Detalhes: `docs/F12_VERACODE_GAPS.md`.

1. **Diagnóstico das permissões:** hosts confirmados na documentação oficial (`api.veracode.com|eu|us`). `/users/self`
   (allowlist com caminho exato); `/principal` não usado (fora da exceção documentada, mais dados pessoais, nada a
   acrescentar). Real: resposta **sem `account_type`/`api_user`**; papéis de interface **Executive, Security Lead e
   Security Insights** ativos; permissões por papel não retornadas; sem restrição de Team efetiva; credencial válida.
   Classificação **`ROLE_PRESENT_ENABLEMENT_NOT_CONFIRMED`** — o papel exigido existe ⇒ o 403 não é permissão ausente;
   a habilitação da organização não é observável por API (não confirmada); licença não presumida. **Risco novo:** a
   credencial de testes tem papéis de escrita/administração (Administrator, Delete Scans…) — o Afrika só lê, mas não é
   privilégio mínimo. Saída minimizada (sem ids, e-mail, nomes, IPs, Teams) só em `private/f12/`.
2. **Estado de `apps.scanned`:** contrato **v1** implementado (36º indicador): distintas por GUID, `scanned_policy` /
   `scanned_sandbox`, `not_scanned`, `indeterminate`, **SCA = null (UNAVAILABLE)**, competência no fuso do cliente,
   `published` "EDT" tratado como intervalo, dedup por `scan_id`/GUID, cobertura e completude (janela, sem
   `most_recent_scan`, sem filtros, visibilidade × perfil). **Hoje UNAVAILABLE** (`scans_report_not_collected`);
   conferência BLOCKED_EXTERNAL. Não usa o último scan do perfil para o mês. Templates não alterados (não exigido).
3. **Fonte comprovada:** só **documental** — relatório SCANS da Reporting API (spec 1.12.0: um item por scan). Real:
   NOT_VERIFIED (403). Summary Report e `scans[]` investigados: só o último build/scan ⇒ insuficientes. XML
   `getbuildlist`/`getbuildinfo`: candidata NOT_VERIFIED (host/XML fora da allowlist; exige autorização).
4. **Homologados: 0 de 21.** Sem comparação real (agente sem acesso ao portal). Conferência agora traz o bloco
   `review` com os 10 itens da ordem (21/21 completos quando há valor). Nenhum valor real coletado para conferência: os
   de estado atual exigem coleta no mesmo dia em que o operador abrir o portal.
5. **Pendências da Reporting API:** cliente/administrador envia ao suporte o texto de `docs/F12_VERACODE_GAPS.md` §2
   (habilitação da organização; UI user × conta de API; `role_name` do papel); depois o PO autoriza **um** POST SCANS.
   Para `apps.scanned`: ligar `collect_evidence` a uma rota/execução e ajustar
   `AFRIKA_VERACODE_REPORTING_MAX_WINDOW_DAYS` (padrão 31 não cobre competência fechada + geração).
6. **Testes (local, sequencial):** pytest completo **772 passed** (736 + 36 novos em `test_f12_gaps.py`); exportação
   obrigatória (`AFRIKA_EXPORT_TESTS=required`, + F11/F12) **155 passed** em 3 de 4 execuções — a 1ª, logo após o pytest
   completo, teve **1 falha não identificada** (nome perdido no corte da saída; não reproduzida em 3 repetições);
   E2E Chromium completo + visual win32 **41 passed + 3 skipped** (opt-in) após ajustar `conference.spec.ts`
   (BLOCKED_EXTERNAL 2→3; a 1ª rodada falhou só nisso); motor visual 12/12; build OK; migrations CLI OK (`0008`);
   allowlist GET (testes novos) PASS; live `users/self` 1 passed (×2); `npm audit` 0; `pip check` OK; gitleaks staged 0;
   `check_repo` OK; `check_env_example` SEGURO. Fidelidade com PowerPoint: NOT_RUN (motor de exportação inalterado).
7. **Commits e CI:** `1692be7` (F12) + commit de checkpoint (STATUS/handoff) em `origin/main`. CI run `39352590718`
   (SHA `1692be7`) — **success**: Backend 3.11 e 3.14 **743 passed + 29 skipped** cada, Exportação PPTX/PDF **94
   passed**, E2E Chromium **41 passed + 3 skipped** com regressão visual Linux, typecheck + build.
8. **Limitações para produção:** sem autenticação/segregação de funções; 0 indicador homologado; Reporting API
   bloqueada (habilitação); credencial de testes sem privilégio mínimo; SQLite/backups sem criptografia; tema provisório;
   `apps.scanned` sem fonte coletada.

Arquivos: `backend/app/veracode/{self_diagnostic.py (novo), readonly.py, discovery.py, reporting.py, fixtures.py}`,
`backend/app/api_veracode.py`, `backend/app/metrics/{scans_published.py (novo), registry.py, contracts.py, engine.py,
collector.py}`, `backend/app/reconciliation/{service.py, guide.py, official.py}`, testes
(`test_f12_gaps.py`, `tests_live/test_f12_self_diagnostic_live.py`, ajustes de contagem em F10/F11 e
`frontend/e2e/conference.spec.ts`), docs (`F12_VERACODE_GAPS.md`, catálogo, matriz, integração, pendências, STATUS),
`prompts/F12_VERACODE_GAPS.md`.

**Prompt sugerido (NÃO executado):** F13 — após a resposta do suporte Veracode confirmando a habilitação, autorizar um
único POST SCANS de teste; ligar `apps.scanned` a uma execução explícita (rota + UI) com janela configurada e
homologar contra o Analytics; registrar as conferências do operador dos 21 aplicáveis (status/Δ, sem valores no
repo) e investigar MISMATCH pelo diagnóstico; substituir a credencial de testes por conta de API de leitura;
desenhar autenticação local com segregação operador × aprovador × conferente.
