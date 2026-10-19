# Devolutiva Claude → ChatGPT PO — F08: Interpretação dos indicadores (2026-10-19)

- **Fase / commits:** F08 / `main` / **`c1766a5`** (implementação + testes + docs + CI) → commit de checkpoint
  (STATUS/handoff). Push feito. **F09 NÃO iniciada.**
- **CI:** run `39263203988` (SHA `c1766a5`) — **success** (detalhes na §9).
- Modelo: Opus 5.5 (ambiente). Nenhum subagente. **Nenhuma chamada à Veracode. Nenhuma chamada a provedor externo de
  IA** (nenhum fornecedor implementado; testes bloqueiam qualquer conexão fora do loopback). Só dados sintéticos.

## 1. Funcionalidades entregues
- Módulo independente `backend/app/interpretation/`: contratos tipados (`contracts.py`), seleção de indicadores por
  slide/tipo e contexto fundamentado (`context.py`), adaptador de provedor (`providers.py`), validação determinística
  (`validate.py`), persistência/revisão/evidências (`service.py`), configuração (`settings.py`).
- 11 tipos (resumo executivo, melhorias, pontos de atenção, tendências SAST, tendências SCA, comparação entre
  competências, conformidade, cobertura de scans, explicação de gráfico, destaques de ranking, recomendações técnicas)
  × 2 níveis (EXECUTIVE consultivo; TECHNICAL com `metric_id`, estado técnico, origem manual e práticas DevSecOps).
- Contexto SÓ com: valores aprovados fixados (atual + histórico), variações do backend (mesma regra da IR; percentual
  1 casa meio-par; anterior 0 ⇒ sem %), estados/qualidade, proveniência, competência/janela e notas declaradas pelo
  operador. Sem findings brutos, sem nome do cliente, sem rótulos identificáveis de rankings/distribuições.
- Painel "Análise do slide" no editor: gerar (executiva/técnica, notas opcionais), indicadores de origem, status de
  validação, iniciar revisão, aprovar, rejeitar (motivo), editar (justificativa), regenerar, comparar versões, aplicar
  ao slide, desabilitar por slide, histórico de eventos e aviso de desatualização.

## 2. Contratos e endpoints
`docs/INTERPRETATION.md` §4 (saída) e §7 (API); integração em `docs/PRESENTATION_CONTRACTS.md` ("Interpretação
(F08)"). Endpoints: `GET /api/interpretation/config`; `GET|POST /api/presentations/{pid}/interpretations`;
`POST …/interpretations/context`; `GET …/{iid}`; `POST …/{iid}/review|approve|reject|edit|regenerate|apply`;
`GET …/{iid}/compare/{other}`; `PUT /api/presentations/{pid}/interpretation-settings/{slide_id}`. Saída por versão:
id, dono (cliente/subcliente), competência, apresentação + revisão, slide/campo de destino, tipo, nível, texto,
afirmações com fatos citados, indicadores e valores usados, proveniência (revisão, sequência e hash da aprovação),
provedor/modelo, versão e hash do prompt, data, status, `context_hash`, `sources_hash`, `content_hash`.
Migration `0007_interpretations` (3 tabelas append-only por gatilho; downgrade recusado com dados).

## 3. Provedores
- **`deterministic-demo`** (padrão e único implementado): regras locais, sem rede, determinístico (teste de
  repetibilidade); escolhe quantas afirmações cabem no campo, nunca corta frases.
- **`ExternalProvider`** (base, sem fornecedor): travas de habilitação no ambiente, credencial só em `.env`
  (`AFRIKA_AI_API_KEY`, nunca exposta), consentimento por execução, limite diário/tamanho, payload minimizado e
  pré-visualizado (`POST …/context`), padrões sensíveis recusados, falhas com mensagem fixa e nada persistido. Testado
  com fornecedor FALSO em processo (sem rede).

## 4. Validação determinística (`validate.py`)
Números (arredondamento só para menos casas), percentuais × contagens, competências fora do contexto, fatos citados
inexistentes, número sem fato, ausência não declarada / número para indicador sem valor (INCOMPLETE/UNAVAILABLE nunca
viram número), sentido da variação, melhora/piora sem tendência comprovada, causa/remediação/remoção/maturidade/risco
de negócio/absolutos (aviso apenas com nota editorial citada ou justificativa declarada do editor), tamanho por slide,
dados sensíveis; valor manual sem declaração = aviso. Bloqueio impede aprovação (409). Limites por layout **medidos**
com o motor real de exportação (tabela em `docs/INTERPRETATION.md` §5).

## 5. Fluxo de aprovação
GENERATED → IN_REVIEW → APPROVED | REJECTED (pessoa declarada; rejeição exige motivo); só a versão mais recente
avança; editar/regenerar = nova versão encadeada; desatualização (`sources_changed`, `facts_changed`,
`slide_missing`) bloqueia aprovar/aplicar; avisos `newer_approval_available` e `applied_text_edited`. Revisão nunca
altera snapshots/indicadores (teste compara a revisão da competência e a integridade antes/depois).

## 6. Integração HTML / PPTX / PDF
"Aplicar ao slide" grava o texto aprovado no campo editorial como NOVA revisão da apresentação (mesma transação do
evento APPLIED); texto existente diferente só é substituído com confirmação explícita; edição manual posterior
preservada. Teste com o motor REAL (`test_interpretation_export.py`, no job de exportação obrigatório do CI): o mesmo
texto aparece na visualização (HTML), no PPTX (texto nativo) e no PDF (texto extraído pelas CMaps), a revisão anterior
exporta sem ele, e qualquer chamada a provedor durante a exportação derruba o teste.

## 7. Evidências de segurança
Padrão sem envio externo (config + teste); conftest bloqueia DNS/conexões não-loopback; contexto sem nomes de
aplicações (teste com ranking sintético), sem nome do cliente e sem hashes no payload externo; notas com
e-mail/URL/UUID recusadas sem eco; logs (`caplog`) e `audit_events` sem texto/valores; isolamento entre clientes e
subclientes (404 cruzado, textos sem valores alheios); gitleaks staged **0**; nenhum PPTX/PDF/dado real versionado.

## 8. Testes (validação final, sequencial)
| Verificação | Resultado |
|---|---|
| pytest completo (local, Py 3.14.7) | **PASS — 654 passed** (579 anteriores + 72 F08 + 2 exportação F08 + 1 PDF) |
| Exportação obrigatória (`AFRIKA_EXPORT_TESTS=required`) | **PASS — 57 passed** (54 + 3) |
| E2E Chromium completo (local, 3 rodadas) | 1ª: 39 passed + 1 **failed** + 3 skipped (`f06c.spec.ts` "ativo local autorizado…", intermitente — passou isolado 4/4 e nas rodadas seguintes; causa NOT_PROVEN); 2ª e 3ª: **40 passed + 3 skipped**. Spec F08 (`interpretation.spec.ts`) 2/2 em todas + reexecução final |
| Regressão visual | **PASS** win32 62/62 (dentro do E2E); Linux no CI (§9) |
| Build frontend + motor visual | **PASS** (12/12) |
| `npm audit` | **PASS — 0 vulnerabilidades** |
| `pip check` | **PASS** (nenhuma dependência nova) |
| gitleaks (staged) | **PASS — 0 achados** |
| `check_repo` / `check_env_example` | **PASS** |
| Migrations (banco novo: migrate, db-status, seed-demo, migrate) | **PASS** — `0007_interpretations` |
Cobertura dos 23 itens obrigatórios: `backend/tests/test_interpretation.py` (1–17, 19–22), `test_interpretation_export.py`
(18), `frontend/e2e/interpretation.spec.ts` (17 pela interface), suíte completa (23).

## 9. CI
Run `39263203988` (SHA `c1766a5`) — **success**: Backend 3.11 e 3.14 (631 passed + 23 skipped cada — os 23 usam o
motor real e rodam no job próprio), **Exportação PPTX/PDF** obrigatória (57 passed, inclui a F08), Frontend typecheck
+ build + motor visual, E2E Chromium **40 passed + 3 skipped** com regressão visual Linux (sem referência nova).

## 10. Commits e push
`c1766a5` (F08) e checkpoint docs — em `origin/main`. Arquivos principais: `backend/app/interpretation/*`,
`backend/app/api_interpretations.py`, `orm.py`, `main.py`, migration `0007`, `export/pdf.py` (correção), testes
`test_interpretation*.py`, `test_export_units.py`, frontend `InterpretationPanel.tsx`, `interpretationsApi.ts`,
`PresentationEditorPage.tsx`, `styles.css`, `e2e/interpretation.spec.ts`, `.github/workflows/ci.yml`,
`scripts/check_repo.py`, docs `INTERPRETATION.md`, `PRESENTATION_CONTRACTS.md`, `SECURITY.md`, `STATUS.md`,
`prompts/F08_INTERPRETATION.md`.

## 11. Decisões técnicas (reversíveis)
- Afirmações com fatos citados (em vez de texto livre) — permite validar cada número contra a sua origem; edição
  humana valida o texto inteiro contra todos os fatos da versão.
- Rótulos de ranking por aplicação/BU/Team/componente/vulnerabilidade fora do contexto por padrão (posição e valor).
- Aplicar sempre cria revisão nova; sobrescrita só confirmada; painel sem zona de texto e matriz: não suportados (422).
- Correção F07: validador de PDF olhava bytes de fluxo comprimido (falso positivo `/AA` reproduzido numa legenda).

## 12. Riscos e limitações
- Validador lexical/conservador em pt-BR (pode bloquear frase correta; números por extenso não verificados).
- Limites medidos nos temas atuais com texto sintético; a exportação continua bloqueando corte.
- `.env.example` **não** atualizado com `AFRIKA_AI_*`: a leitura do arquivo foi negada pela política de permissões
  desta sessão; variáveis documentadas em `docs/INTERPRETATION.md` §8 (todas opcionais; padrão seguro sem elas).
- Intermitência E2E pré-existente em `f06c.spec.ts` (1 em 3 rodadas completas), não relacionada ao código F08.

## 13. Pendências para o PO / F09
1. Aceite da F08. 2. Decisão sobre provedor externo de IA (fornecedor, custos, termos, dados permitidos) ou manter só
o local. 3. Autorizar a inclusão de `AFRIKA_AI_*` no `.env.example`. 4. Tom/vocabulário dos textos e regras de
recomendação (homologação com usuários). 5. Decisões pendentes da F07 (Be Vietnam Pro no PPTX; ativos de marca).

## 14. Prompt sugerido para a próxima fase (NÃO executado)
> **F09 — Homologação ponta a ponta.** Ler `CLAUDE.md`, `docs/STATUS.md`, `docs/AGENT_HANDOFF.md`,
> `docs/INTERPRETATION.md`, `docs/EXPORT.md`. Roteiro de homologação com o PO: competência sintética e (se autorizado)
> competência real em ambiente local — coleta → snapshot → aprovação → apresentação → análise (provedor local) →
> revisão humana → exportação PPTX/PDF; checklist de aceite por slide (valores, textos, fidelidade, fontes); registrar
> divergências como NOT_VERIFIED/BLOCKED sem corrigir dados manualmente; nenhum provedor externo de IA sem decisão do
> PO; nenhum dado real no repositório. Entregar relatório de homologação e pendências; não iniciar fases novas.
