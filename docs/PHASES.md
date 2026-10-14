# Planejamento autorizado por fases

| Fase | Entrega | Gate obrigatório |
|---|---|---|
| F00 | baseline executável, documentação, testes/CI e contratos mínimos | CI verde, demo sintética, segurança e handoff |
| F01 | CRUD clientes/subclientes e conexões sem secretos em claro | testes CRUD, sem vazamento, migrações |
| F02 | conexões reais Veracode somente leitura, paginação/retries | fixture replay + smoke autorizado + contagens reconciliadas |
| F03 | engine de escopos por domínio com visual builder | property tests AND/OR/NOT + overlaps + unclassified |
| F04 | catálogo e motor de métricas determinístico | golden fixtures + comparações dashboard + dias de corte |
| F05 | histórico, snapshots, inputs manuais, auditoria | imutabilidade histórica + revisão auditada |
| F06 | catalogação do template oficial e engine de slides | diff de imagem por slide + fontes/layout |
| F07 | fluxo relatório e exportações HTML/PPTX/PDF | E2E + integridade de artefatos + revisão visual |
| F08 | análises opcionais por IA com fontes | sem números inventados + revisão humana |
| F09 | homologação múltiplos clientes | happy path + falhas reais + isolamento |

## Done por fase
- Código e testes reproduzíveis, sem bypass de erros; CI verde.
- Documentação e `docs/STATUS.md` atualizados.
- Testes executados, PASS/FAIL/NOT_RUN e evidências descritas.
- Riscos e decisões ainda abertas declarados.
- O PO autoriza **expressamente** a próxima fase.
