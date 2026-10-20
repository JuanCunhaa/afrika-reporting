# F10/F11/F12 — Pendências abertas (atualizado na F12, 2026-10-19)

Ordenadas por impacto no piloto. "Dono" = quem pode destravar.

| # | Pendência | Impacto | Dono | Estado |
|---|---|---|---|---|
| 1 | **Conferência humana dos 21 indicadores aplicáveis** no portal do tenant, no mesmo dia de uma coleta, pela página *Conferir com a Veracode* (F11: ordenada pelas prioridades 1–8, com definição oficial e diagnóstico automático) | sem ela nenhum indicador é homologado (0/35) | operador | NOT_VERIFIED |
| 2 | **Reporting API HTTP 403** (papel/habilitação na conta) | scans.count, sast.policy.resolved_in_period e **apps.scanned** sem fonte; fechamento histórico só por snapshot/manual | PO → cliente → suporte Veracode | BLOCKED_EXTERNAL — **F12:** papéis de UI compatíveis presentes ⇒ habilitação da organização não confirmada; texto ao suporte em `docs/F12_VERACODE_GAPS.md` §2 |
| 3 | **Backend sem autenticação** (operador/aprovador/conferente declarados) | proíbe qualquer uso fora de uma estação local | PO (fase futura) | aceito para piloto local |
| 4 | Identidade de deduplicação entre contextos (SAST `issue_id`; SCA componente+CVE) não comprovada | 3 "distintos" ficam sem valor (NOT_APPLICABLE) | PO (definição) + evidência real | aberto |
| 5 | Metadado de dedup SCA corrigido sem novo `version` de contrato | rastreabilidade do contrato | — | **RESOLVIDO (F11)**: semântica idêntica provada por teste ⇒ v1 mantida |
| 6 | Semântica de `count` nos findings SCA reais e de `third_party_components` do Summary Report | possíveis diferenças com o portal | — | **PARCIAL (F11, real)**: `count` = 1 em todos os findings da amostra; componentes ≥ componentes vulneráveis (não comparáveis). Semântica oficial de `count` não documentada |
| 7 | SQLite local sem criptografia; backups (`data/backups/`) com o mesmo conteúdo do banco | proteger a pasta como o banco; sem cópia fora da estação | operador | aceito para piloto local |
| 8 | Tema `afrika@2` PROVISÓRIO, ativos de marca ausentes, Be Vietnam Pro não aplicada pelo PowerPoint local, abertura em outros computadores NOT_VERIFIED | qualidade visual com ressalvas | PO (ativos/decisões) | herdado |
| 9 | Observação O-1 (partes inertes do template python-pptx no PPTX) | higiene, não segurança | PO | herdado |
| 10 | Coletas e jobs de exportação em memória (reinício ⇒ nova coleta/exportação, com mensagem) | operacional | — | aceito (por desenho) |
| 11 | Caminhos da plataforma no guia são INDICATIVOS (agente sem acesso ao portal); F11 acrescentou definição oficial e local no Analytics com links da documentação | operador registra o local real na evidência | operador | NOT_VERIFIED |
| 12 | Tratamento de HTTP 500 real na Findings API não reobservado (F10: SCA sem componentes respondeu 200) | mock PASS; real NOT_VERIFIED nesta fase | — | NOT_VERIFIED |
| 13 | **Prioridade 9 "Aplicações com scans"** sem indicador aplicável (`scans.covered_apps` é NOT_APPLICABLE) | grupo da ordem sem conferência | — | **F12:** `apps.scanned` v1 implementado (fonte: relatório SCANS) — UNAVAILABLE/BLOCKED_EXTERNAL até a Reporting API |
| 14 | Diagnóstico objetivo dos papéis da conta (Reporting 403) exigiria GET documentado `/api/authn/v2/users/self` fora da allowlist | — | **RESOLVIDO (F12)**: allowlist exata + diagnóstico real (2 GET) |
| 15 | **Piloto real assistido** não executado: 0/21 conferidos e autorização do cliente não informada | sem validação com dados de cliente | operador + PO + cliente | NOT_RUN |
| 16 | Backup automático antes de aprovar exige destino permitido (`AFRIKA_BACKUP_DIR` fora do repo ou `data/`/`private/`) | aprovação bloqueada se o destino falhar (por desenho) | operador | aceito |
| 17 | **Credencial de testes com papéis de escrita/administração** (Administrator, Delete Scans, Policy Administrator…) | regra "credenciais mínimas" não atendida; o Afrika só lê (trava GET-only) | cliente/administrador Veracode | aberto (F12) |
| 18 | `/users/self` real sem `account_type`/`api_user` | tipo da conta (UI × API) não confirmável por campo | — | aceito (F12: avaliados os dois critérios documentados) |
| 19 | `apps.scanned` sem rota/tela de coleta (só `collect_evidence`); janela padrão de 31 dias insuficiente | ligar após habilitação e autorização de POST | PO | aberto (F12) |

Decisões herdadas ainda abertas: fornecedor externo de IA (desligado) e `AFRIKA_AI_*` no `.env.example`; template
visual oficial.
