# F09 — Prontidão para liberação (2026-10-19)

Base: `docs/F09_ACCEPTANCE_MATRIX.md`, `docs/F09_METRIC_RECONCILIATION.md`, `docs/F09_SECURITY_REVIEW.md`.

## 1. Veredito por dimensão
| Dimensão | Veredito | Fundamento |
|---|---|---|
| Homologação funcional | **APROVADA (dados sintéticos)** | fluxo 22/22 etapas PASS com evidência automatizada, incluindo reinício sem perda e exportação real |
| Homologação de integração (Veracode) | **PARCIAL** | inventário, BUs, Teams, usuários, escopos, paginação, Summary Report e SAST: PASS em real (somente GET). SCA: BLOCKED_EXTERNAL (falhas da fonte). Reporting API: BLOCKED_EXTERNAL (403). HTTP 500 real: NOT_VERIFIED nesta fase (mock PASS) |
| Homologação dos indicadores | **NÃO HOMOLOGADA** | 0 de 35 indicadores comparados com o valor oficial do dashboard (inacessível ao agente); roteiro de conferência humana pronto |
| Homologação visual | **APROVADA localmente, com ressalvas** | PPTX nativo/PDF íntegros nos modelos Afrika e neutro; regressão visual (Windows e CI Linux); tema `afrika@2` PROVISÓRIO; ativos oficiais de marca ausentes; fontes em outro computador NOT_VERIFIED; PowerPoint local não aplica Be Vietnam Pro incorporada |
| Prontidão operacional | **CONDICIONADA — piloto local assistido** | possível usar em UMA estação, por um operador, com: valores críticos conferidos manualmente no dashboard antes da aprovação; lacunas (SCA, fechamento, scans, licenças) preenchidas manualmente com justificativa; revisão humana de todo texto |
| Prontidão para produção | **NÃO PRONTO** | sem autenticação/autorização de usuários; indicadores não homologados; SCA e Reporting bloqueados; SQLite local sem criptografia; sem backup/operação definidos |

## 2. Limitações críticas (impedem produção)
1. Backend sem autenticação real: aprovador/revisor são nomes declarados; não expor fora de `127.0.0.1`.
2. Nenhum indicador homologado contra o dashboard.
3. SCA (Findings API) instável na conta de testes (500 na F04/F04.1; falhas de transporte na F09).
4. Reporting API sem permissão (403): sem resolvidos no período, sem contagem de scans, sem fechamento histórico pela
   fonte — dependem de snapshot aprovado ou entrada manual.

## 3. Limitações operacionais (aceitáveis num piloto local)
- Execuções de coleta e jobs de exportação vivem em memória: reiniciar o backend exige nova coleta (mensagem
  explícita) e nova exportação (mesma revisão ⇒ mesmo PPTX).
- Estado atual ≠ fechamento: competências passadas só por snapshot aprovado; meses sem aprovação são lacunas.
- Uso local de uma pessoa; SQLite sem acesso concorrente entre máquinas; backup do arquivo `data/` é manual.
- Exportação depende do Chromium headless do Playwright e do build do frontend na mesma máquina.
- PPTX carrega resíduo inerte do template do python-pptx (`printerSettings1.bin`; miniatura genérica do pacote).

## 4. Recomendação ao PO
**Aceitar a F09 como homologação funcional e de integração parcial**, e autorizar no máximo um **piloto local
assistido** com o tenant de testes, condicionado a:
1. Conferência humana no dashboard (roteiro em `docs/F09_METRIC_RECONCILIATION.md` §5) antes de qualquer uso dos
   números fora da equipe; registrar MATCH/MISMATCH por indicador.
2. Decisão sobre a Reporting API (pedido de papel/habilitação à Veracode) e sobre a fonte de SCA.
3. Não expor o backend em rede; uma estação, um operador.

**Não declarar prontidão para produção.** Pré-requisitos mínimos para uma futura fase de produção (não iniciada):
autenticação e autorização com segregação de funções, homologação dos indicadores com o dashboard, banco/servidor
adequados a uso compartilhado com backup e criptografia, e decisão sobre o template visual oficial e ativos de marca.
