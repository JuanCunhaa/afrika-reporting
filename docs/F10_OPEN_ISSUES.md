# F10 — Pendências abertas (2026-10-19)

Ordenadas por impacto no piloto. "Dono" = quem pode destravar.

| # | Pendência | Impacto | Dono | Estado |
|---|---|---|---|---|
| 1 | **Conferência humana dos 21 indicadores aplicáveis** no portal do tenant, no mesmo dia de uma coleta, pela página *Conferir com a Veracode* | sem ela nenhum indicador é homologado (0/35) | operador | NOT_VERIFIED |
| 2 | **Reporting API HTTP 403** (papel/habilitação na conta) | scans.count e sast.policy.resolved_in_period sem fonte; fechamento histórico só por snapshot/manual | PO → Veracode | BLOCKED_EXTERNAL |
| 3 | **Backend sem autenticação** (operador/aprovador/conferente declarados) | proíbe qualquer uso fora de uma estação local | PO (fase futura) | aceito para piloto local |
| 4 | Identidade de deduplicação entre contextos (SAST `issue_id`; SCA componente+CVE) não comprovada | 3 "distintos" ficam sem valor (NOT_APPLICABLE) | PO (definição) + evidência real | aberto |
| 5 | Metadado de dedup SCA corrigido sem novo `version` de contrato (fórmula/valor inalterados) | rastreabilidade do contrato | PO (confirmar ou pedir v2 + novos templates) | decisão pendente |
| 6 | Semântica de `count` nos findings SCA reais (campo presente, não usado) e de `third_party_components` do Summary Report | possíveis diferenças com o portal ao conferir SCA | operador (na conferência) | NOT_VERIFIED |
| 7 | SQLite local sem criptografia; backups (`data/backups/`) com o mesmo conteúdo do banco | proteger a pasta como o banco; sem cópia fora da estação | operador | aceito para piloto local |
| 8 | Tema `afrika@2` PROVISÓRIO, ativos de marca ausentes, Be Vietnam Pro não aplicada pelo PowerPoint local, abertura em outros computadores NOT_VERIFIED | qualidade visual com ressalvas | PO (ativos/decisões) | herdado |
| 9 | Observação O-1 (partes inertes do template python-pptx no PPTX) | higiene, não segurança | PO | herdado |
| 10 | Coletas e jobs de exportação em memória (reinício ⇒ nova coleta/exportação, com mensagem) | operacional | — | aceito (por desenho) |
| 11 | Caminhos da plataforma no guia de conferência são INDICATIVOS (agente sem acesso ao portal) | operador pode precisar ajustar a navegação | operador | NOT_VERIFIED |
| 12 | Tratamento de HTTP 500 real na Findings API não reobservado (F10: SCA sem componentes respondeu 200) | mock PASS; real NOT_VERIFIED nesta fase | — | NOT_VERIFIED |

Decisões herdadas ainda abertas: fornecedor externo de IA (desligado) e `AFRIKA_AI_*` no `.env.example`; template
visual oficial.
