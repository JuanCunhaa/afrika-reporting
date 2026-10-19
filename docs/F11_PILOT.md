# F11 — Piloto assistido: sintético integral e condições do piloto real (2026-10-19)

Classificação: **PASS** · **FAIL** · **BLOCKED_EXTERNAL** · **NOT_VERIFIED** · **NOT_RUN**.

## 1. Piloto sintético integral — PASS
`backend/tests/test_f10_pilot.py` (12 etapas, dados 100% sintéticos), agora com o **backup automático antes de cada
aprovação** verificado em todas as aprovações do ciclo:

| Etapa (ordem do PO §7) | Resultado | Onde |
|---|---|---|
| Escopo (cliente + subcliente + escopos) | PASS | etapa 1 |
| Coleta → snapshots | PASS | etapas 2–3 |
| Conferência (oráculo independente; MATCH) + prioridades/definição/diagnóstico | PASS | etapa 4 + `test_f11_homologation.py` |
| **Backup automático verificado** → aprovação | PASS | etapas 2, 5, 6b (cópia do estado anterior à aprovação; SHA-256 conferido) |
| Snapshot aprovado e histórico | PASS | etapa 5 |
| Interpretação local revisada | PASS | etapa 7 |
| Apresentação `afrika-modelo@2` (cliente e subcliente) | PASS | etapas 6/6b |
| PPTX e PDF | PASS | etapa 8 (exportação obrigatória) |
| Backup manual e restauração | PASS | etapas 9–10 |
| Segredos fora de logs/SQLite | PASS | etapa 11 |

## 2. Backup automático antes da aprovação (novo)
- `POST /api/competences/{cid}/revisions/{n}/approve`: depois das validações e **antes** de gravar a aprovação, faz
  `backup.before_approval` — cópia consistente pela API de backup do SQLite + `PRAGMA integrity_check` + revisão
  Alembic + SHA-256 + manifesto `.json`.
- **Falha ⇒ aprovação bloqueada** (HTTP 409 `approval_backup_failed`, mensagem com o motivo e o lembrete do backup
  manual); a revisão continua `READY_FOR_REVIEW`; evento de auditoria `approval.blocked` com `backup_failed`. Cobre
  destino versionável/recusado, erro de E/S e falha do SQLite.
- Sucesso ⇒ resposta traz `approval_backup` (nome do arquivo, SHA-256, revisão, integridade) e o evento
  `revision.approved` registra nome + SHA-256 (sem caminho local).
- Destino: `AFRIKA_BACKUP_DIR` ou `backups/` ao lado do banco (banco padrão ⇒ `data/backups/`, ignorado). Dentro do
  repositório só `data/` e `private/` são aceitos. E2E: diretório temporário do sistema.
- **Backup manual mantido:** `python -m app.cli backup-db [--out DIR]`; restauração só com `--confirm` e backend parado.

## 3. Piloto real assistido — NOT_RUN (condições não atendidas)
Pré-condições da ordem: indicadores relevantes **conferidos** e **autorização do cliente** disponível.
- Conferidos: **0/21** (o operador ainda não registrou nenhuma leitura do dashboard).
- Autorização do cliente: **não informada** nesta fase.
⇒ Nenhuma coleta de cliente real foi feita. Só o tenant de testes foi consultado (26 GET de diagnóstico SCA).

Quando as condições forem atendidas, roteiro (uma estação, `127.0.0.1`):
1. Escopo do cliente autorizado → coleta (GET) → rascunho da competência.
2. *Conferir com a Veracode* no **mesmo dia**: prioridades 1 → 8; registrar evidência fora do repositório.
3. Só indicadores **MATCH** podem ser apresentados como conferidos; MISMATCH ⇒ diagnóstico, sem alterar números.
4. Enviar para revisão → aprovar (o backup automático roda; se falhar, corrigir o destino e repetir).
5. Interpretação local revisada → apresentação → PPTX/PDF em `data/exports` → backup manual ao fim do ciclo.
6. Devolver ao PO só status/Δ; valores, nomes e capturas ficam em `private/`/`data/`.

## 4. Segurança (ordem do PO §8)
| Requisito | Resultado | Evidência |
|---|---|---|
| Backend em 127.0.0.1 | PASS | `LocalOnlyMiddleware`; uvicorn/Vite em `127.0.0.1` (inalterado) |
| Nenhuma credencial em logs | PASS | piloto etapa 11; diagnóstico real imprime só booleanos/códigos |
| Nenhum dado real no Git | PASS | saída real só em `private/f11/` (`git check-ignore`); gitleaks; `check_repo` |
| Nenhuma escrita operacional na Veracode | PASS | 26 GET, 0 POST/PUT/DELETE; trava read-only intacta |
| Reporting POST nunca enquanto bloqueado | PASS | não repetido (403 desde a F05) |
| IA externa desabilitada | PASS | piloto etapa 7 (`deterministic-demo`) |
| Backups e relatórios reais em diretórios ignorados | PASS | `data/backups`, `data/exports`, `private/`; destino versionável recusado (teste) |
| Sem acesso público não autenticado | PASS (uso local) | só loopback; **sem autenticação ⇒ não expor** (impede produção) |
