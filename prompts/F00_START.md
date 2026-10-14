# F00 — PRIMEIRA ORDEM AO CLAUDE CODE

Você é implementador sob coordenação do PO (ChatGPT). Leia `CLAUDE.md`, `docs/STATUS.md`, `docs/PRODUCT.md`, `docs/ARCHITECTURE.md` e a skill `.claude/skills/phase-delivery/SKILL.md`. **Não inicie F01**.

Objetivos apenas F00:
1. Audite o scaffold atual e rode backend unit tests e frontend build/typecheck em Windows local.
2. Corrija problemas concretos de instalação, sintaxe, CORS ou funcionamento da demo, sem introduzir coleta Veracode nem manipular PPTX real.
3. Crie um smoke test E2E mínimo de UI (Playwright, se viável no ambiente) para: abrir, ver clientes sintéticos, selecionar cliente e observar detalhes; capture evidências SEM dados reais. Se navegador/tool indisponível, marque NOT_RUN e explique.
4. Adicione CI GitHub Actions mínimo para testes Python e build frontend, preferindo pin de actions por SHA após validação.
5. Revise `.gitignore`, `LICENSE`, documentação e esquema dos contratos; destaque decisões abertas sem perguntar por não-bloqueantes.
6. Execute checklist de segurança de repositório público; nunca inclua dados reais.
7. Atualize `docs/STATUS.md`, preencha `docs/AGENT_HANDOFF.md` e pare.

Aceite: smoke API e testes passando; build TS sem erros; app abre localmente; nenhum endpoint Veracode real; documente resultado E2E real vs não testado. Não chame uma mera UI demo de produto completo.

Economia de tokens: não explore arquivos irrelevantes, `node_modules`, `.venv` ou os PPTXs; use Sonnet para execução, Opus só se bloqueio arquitetural real. Entregue devolutiva compacta pronta para colar no ChatGPT.
