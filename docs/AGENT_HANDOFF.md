# Devolutiva Claude → ChatGPT PO — F06A: Motor de Templates e Pré-visualização (2026-10-15)

- **Fase / commits:** F06A / `main` / **`c160494`** (código + testes + docs técnicas) + commit seguinte só com STATUS/handoff. Push feito. **F06B, F07 e F08 NÃO iniciadas.**
- **CI:** run `38776201083` (SHA `c160494`) — **success** — Backend 3.11 e 3.14 (438 passed cada), Frontend typecheck+build, E2E Chromium (24 passed).
- Modelo: Opus 5.5 (ambiente). Nenhum subagente. Nenhuma chamada à Veracode nesta fase.

## 1. Funcionalidades implementadas
Templates tipados e versionados (imutáveis, append-only) com tema, slides ordenados, layout, indicadores, campos editáveis, obrigatoriedade e compatibilidade de versões de contrato; escolha de template por cliente/subcliente (subcliente herda do cliente; cliente sem subcliente funciona); criação de apresentação **só** a partir de revisão aprovada (rascunho/em revisão ⇒ 409); fontes fixadas com hash (revisão principal + aprovações dos 11 meses anteriores) e troca explícita (`rebind`); editor HTML com canvas 16:9, navegação (botões, setas, contador, modo apresentação), edição de título/textos/tópicos/títulos de gráfico/legendas/observações/notas/apresentadores, layout e opções, seleção de indicadores compatíveis, inclusão/remoção/reordenação, pré-visualização ao vivo **sem gravação**, dados de origem, revisões (consulta somente leitura) e verificação de integridade. Tema demonstrativo neutro **PROVISÓRIO** (aviso na tela e no rodapé de cada slide). Docs: `docs/PRESENTATIONS.md`, `docs/PRESENTATION_CONTRACTS.md`.

## 2. Tipos de slides disponíveis (nenhum obrigatório por si)
Capa · Sumário executivo · KPIs principais · Mês atual × anterior · Gráfico de barras (categorias da competência ou série mensal) · Linhas/série histórica (até 4 séries, 6/12 meses) · Distribuição por severidade · Ranking Top 10 · Tabela de indicadores · Recomendações e observações · Encerramento. Cada tipo declara layouts, campos editáveis/obrigatórios, nº e tipos de valor aceitos e opções.

## 3. Modelo de templates
`template_key` + `version` + `definition_hash`; `theme {id, version}`; `metric_contracts {metric_id: [versões aceitas]}`; `slides[{slot_id, type, layout, required, required_metrics, fields, metrics, options}]`. Sem campo de valor (`extra=forbid` ⇒ 422 para `value`). `required` = slot não removível nem trocável de tipo; `required_metrics` = indicadores não removíveis e, sem valor aprovado, viram **bloqueio** (`ready=false` para F07). Contrato fora das versões aceitas ⇒ `INCOMPATIBLE` (valor não exibido). Embutidos sintéticos: `demo-executivo`, `demo-tecnico`, `demo-minimo` (instalação idempotente; também no `seed-demo`).

## 4. Persistência e migrations
`0005_presentations`: `presentation_templates` (append-only), `owner_template_selections` (append-only), `presentations` (identidade imutável, sem DELETE, ponteiro `current_revision` com concorrência otimista), `presentation_revisions` (append-only; documento + fontes + `document_hash`/`sources_hash`/`revision_hash` encadeado; gatilho exige revisão de competência APROVADA e a aprovação dela). Downgrade recusado com apresentações salvas (`AFRIKA_ALLOW_DESTRUCTIVE_DOWNGRADE=1`). Upgrade testado em banco F05 com histórico aprovado. Auditoria na cadeia F05: `template.version_created`, `template.selected`, `presentation.created|saved|sources_rebound`. O editor não tem caminho de escrita para snapshots/aprovações (testado: `row_hash`, aprovação e integridade F05 iguais antes/depois).

## 5. Endpoints e interface
`GET /api/presentation-catalog`; `GET/POST /api/presentation-templates`; `POST /api/presentation-templates/builtin`; `GET /api/presentation-templates/{key}/versions/{v}`; `POST /api/presentation-templates/{key}/versions`; `GET/PUT /api/template-selection/{kind}/{id}`; `GET/POST /api/presentations`; `GET /api/presentations/{pid}`; `GET …/revisions/{n}`; `PUT …/document`; `POST …/preview`; `POST …/rebind`; `GET …/view[?revision=n]`; `GET …/integrity`. Telas: **Apresentações** (`#/presentations`) e editor (`#/presentations/{id}`).

IR de gráficos (`charts.py`, `ir_version` 1): `y` = exatamente o número aprovado; ausência ⇒ `y=null` com estado `GAP`/`MISSING`/`NOT_NUMERIC`/`INCOMPATIBLE`; cores por token (`series.1..4` fixas por vinculação, rampa ordinal de severidade de um tom + cinza com textura para desconhecida — paletas validadas com validador de CVD/contraste); eixo Y a partir de 0; unidade do contrato; pt-BR; contagens sem arredondamento, decimal 2 casas e percentual 1 casa (meio-par só no rótulo); linhas quebram em lacunas (sem interpolação); distribuições/rankings só com adaptador explícito por indicador.

## 6. Testes
| Verificação | Resultado |
|---|---|
| `python -m pytest -q` (local e CI 3.11/3.14) | **PASS 438** (411 + 27 F06A) |
| E2E Chromium `npm run test:e2e` | **PASS 24/24** (22 + 2 F06A) em 3 rodadas completas locais + CI |
| `presentations.spec.ts` repetido | 2 + 16 + 24 + 6 (partida a frio) PASS; **1 FAIL** isolado antes (ver riscos) |
| build; `npm audit` (total e prod); `pip check` | OK; 0 vulnerabilidades; OK |
| gitleaks (staged) | 0 achados |
| `check_repo`; `check_env_example` | OK (F06A); SEGURO |
| migrations CLI (migrate, db-status, seed ×2, migrate) em banco novo | OK (`0005_presentations`; seed idempotente, 3 templates) |
| `tests_live` | NOT_RUN (fase sem chamadas reais) |
Cobertura da ordem: slides opcionais (remoção/obrigatórios), templates por cliente/subcliente, só aprovados (rascunho, em revisão e revisão-rascunho recusados; gatilho no banco), séries 6 e 12 meses com lacunas, dados ausentes/incompatíveis/estrutura não reconhecida, manuais identificados, gráficos sem números inventados (todo número da IR ⊆ valores aprovados ∪ deltas), edição sem alterar métricas, reordenação/remoção/inclusão, persistência após reinício (visualização idêntica), versionamento de templates, integridade (adulteração de documento e de snapshot detectadas), concorrência (4 threads: 1 sucesso, 3 conflitos), downgrade, upgrade F05→F06A, pré-visualização sem gravação, E2E completo, regressão.

## 7. `scopes.spec.ts` (investigação)
Não reproduzido: 6 repetições isoladas (18/18), 3+1+3 suítes completas (22/22 e 24/24), sonda temporária com CPU 20× mais lenta clicando logo após trocar de dono (0/24 cliques perdidos). Duração do teste 5,1 s (timeout 30 s). Hipótese examinada (formulário sincronizado por `useEffect` passivo sobrescrevendo clique) não confirmada — Playwright espera estabilidade antes do clique. **Nenhum retry adicionado e nenhum código F03 alterado.** Causa: NOT_PROVEN; trace é retido em falha (`trace: retain-on-failure`) para a próxima ocorrência.

## 8. Riscos e limitações
1. **Intermitência nova no editor (1 em ~51 execuções):** PUT de salvamento respondeu 200, mas o GET seguinte ficou sem resposta > 5 s (≈ timeout padrão de lock do SQLite; compatível com bloqueio transitório do arquivo no Windows, **não provado**). Mitigação de correção (não retry): a UI passou a derivar o estado salvo da resposta do PUT; não se repetiu nas 48 execuções seguintes.
2. Tema e templates demonstrativos; nenhuma fidelidade a template oficial (diff visual por slide depende do arquivo aprovado — F06B).
3. Sem exportação PPTX/PDF (F07); mapeamento previsto documentado (objetos nativos a partir da IR, sem imagens).
4. Identidade declarada (sem autenticação); SQLite local.
5. Janela fixada de 12 meses; distribuições/rankings sem adaptador ⇒ indisponíveis.
6. Pendências herdadas: Reporting API BLOCKED_EXTERNAL (403); comparação com dashboard NOT_RUN.

## 9. Pendências para F06B
Catalogar o template oficial aprovado (sem commitar PPTX real): tema oficial (cores/fontes/master) como novo tema versionado; layouts reais por slide; mapear cada bloco a `metric_id` + versões de contrato e `required_metrics`; regressão visual por slide (screenshots com tolerância medida, ambiente de fontes registrado); decidir conjunto obrigatório por template; eventualmente adaptadores para novos indicadores.

## 10. Commits e push
`c160494` (implementação) + commit de checkpoint (STATUS/handoff). Push em `origin/main`. Só arquivos de código, testes e docs (sem banco, PPTX, evidências ou `.env`).

**Prompt sugerido para F06B (não executado):** "F06B — A partir do template oficial aprovado pelo PO (arquivo fora do repo), criar o tema oficial versionado (cores, fontes com fallback, master) e as versões de template correspondentes, mapeando cada bloco a `metric_id` + versões de contrato e `required_metrics`; implementar regressão visual por slide com dados sintéticos (tolerância medida, ambiente registrado) e verificação semântica (nº de slides, textos, valores); manter o tema demonstrativo; sem exportação PPTX/PDF (F07)."

---

## Versão compacta para o PO
F06A concluída localmente (`c160494`, CI verde run `38776201083`). Templates tipados e versionados (imutáveis), escolha por cliente/subcliente, 11 tipos de slide, apresentações criadas somente de revisões aprovadas com fontes fixadas por hash e troca explícita, IR de gráficos independente do renderizador (sem números inventados; lacunas/ausências/manuais explícitos), editor HTML 16:9 navegável com pré-visualização ao vivo, dados de origem, revisões e integridade; tema neutro **provisório**. Migration `0005_presentations` com gatilhos. Testes: pytest 438 PASS, E2E 24 PASS, build/audit/pip/gitleaks OK. `scopes.spec.ts` não reproduzido (sem retry). Risco: 1 intermitência rara no editor (causa não provada, mitigada sem retry). F06B aguardando ordem.
