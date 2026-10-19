# Devolutiva Claude → ChatGPT PO — F11: Homologação de Métricas e Piloto Assistido (2026-10-19)

- **Fase / commit:** F11 / `main` / **`18f8bb7`** + commit de checkpoint (STATUS/handoff). **F12 não iniciada. Produção
  NÃO autorizada.** Modelo: Opus 5.5; nenhum subagente; nenhuma dependência nova.
- Veracode real: tenant de testes, **somente GET (26)**, 0 POST. IA externa: nenhuma chamada.

1. **Homologados: 0 de 21.** O agente não tem acesso autorizado à interface da Veracode; nenhum HOMOLOGATED declarado.
2. **Divergências identificadas:** nenhuma medida (sem valor oficial observado). Diferenças de DEFINIÇÃO conhecidas
   documentadas (conformidade "Pass"/"Calculating...", Teams List com security lead teams, Count of Flaws × Total,
   First Found Date × First Found in Application Date, Custom Severity, SCA findings × bibliotecas).
3. **Correções comprovadas:** nenhum defeito de cálculo comprovado; nada alterado em números ou snapshots aprovados.
   Funcionalidades da ordem: definições oficiais/prioridades/diagnóstico automático na conferência
   (`backend/app/reconciliation/official.py`, `diagnostics.py`, página e CSV) e backup automático antes de aprovar.
4. **Não homologados:** os 21 aplicáveis (NOT_VERIFIED), ordenados por prioridade; 12 NOT_APPLICABLE e 2
   BLOCKED_EXTERNAL inalterados. Prioridade 9 ("aplicações com scans") sem indicador aplicável — proposta `apps.scanned`.
5. **Reporting API:** BLOCKED_EXTERNAL (403 desde a F05; POST não repetido). Requisitos documentados: papel Reporting
   API (conta de API) ou Executive/Security Lead/Security Insights + habilitação por e-mail ao suporte Veracode.
   Caminho em `docs/F11_METRIC_HOMOLOGATION.md` §7.
6. **Piloto:** sintético integral 12/12 PASS; real assistido NOT_RUN (0 conferidos, autorização do cliente ausente).
7. **Backup/restauração:** automático e verificado antes de cada aprovação (falha bloqueia, auditado); manual e
   restauração via CLI PASS; destinos versionáveis recusados.
8. **Segurança:** 127.0.0.1; sem credenciais em logs; dados reais só em `private/f11/`; 0 escrita na Veracode; IA externa
   desligada; backups em diretórios ignorados. **Sem autenticação ⇒ não expor.**
9. **Testes (local, sequencial):** pytest 736 passed; exportação obrigatória 130 passed; E2E Chromium completo + visual
   win32 41 passed + 3 skipped (opt-in); E2E conferência PASS; live SCA 1 passed; migrations CLI OK (`0008`);
   backup/restore CLI OK; `npm audit` 0; `pip check` OK; gitleaks 0; `check_repo` OK. Fidelidade com PowerPoint:
   NOT_RUN (motor de exportação inalterado).
10. **Commits e CI:** `18f8bb7` (F11) e `399bf32` (checkpoint) em `origin/main`. CI run `39316124239` (SHA `399bf32`,
    contém `18f8bb7`) — **success**: Backend 3.11 e 3.14 **707 passed + 29 skipped** cada, Exportação PPTX/PDF **94
    passed**, E2E Chromium **41 passed + 3 skipped** com regressão visual Linux, typecheck + build. O run `39315992801`
    (`18f8bb7`) foi cancelado pelo push seguinte (só o frontend tinha concluído, com sucesso).
11. **Impedimentos para produção:** sem autenticação/segregação de funções; 0 indicador homologado; Reporting API
    bloqueada; SQLite e backups sem criptografia; tema provisório.

Pendências: `docs/F10_OPEN_ISSUES.md` (itens 13–16 novos; 5 resolvido; 6 parcial).

**Prompt sugerido (NÃO executado):** F12 — com as conferências do operador registradas (status/Δ, sem valores no
repo), investigar cada MISMATCH pelo diagnóstico; decidir `apps.scanned` e a inclusão de `/api/authn/v2/users/self` na
allowlist GET; desenhar autenticação local com segregação operador × aprovador × conferente; Reporting só após
habilitação confirmada.
