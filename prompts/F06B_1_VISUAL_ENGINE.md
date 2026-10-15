# ORDEM DO PO — F06B.1: Preparação do Motor Visual Oficial

**Projeto:** Afrika Reporting · **Fase:** F06B.1 · **Status anterior:** F06A aprovada · **Não autorizadas:** F07, F08,
exportação definitiva PPTX/PDF, reprodução visual definitiva (aguarda PPTX de referência aprovado)

Executar somente a preparação técnica da F06B: reproduzir fielmente apresentações oficiais a partir de arquivos PPTX de
referência, preservando a arquitetura da F06A. Ainda não há template oficial escolhido: não inventar nem declarar
identidade visual definitiva.

## 1. Preparação
Ler `CLAUDE.md`, skills de apresentações, handoff, `docs/PRESENTATION_CONTRACTS.md` e módulos da F06A. Reutilizar o
modelo de templates e gráficos. Implementação incremental, testes e economia de tokens.

## 2. Sistema de temas versionados
Tokens visuais: paleta; fontes e pesos; tamanhos tipográficos; margens e espaçamentos; posicionamento de elementos;
cabeçalhos e rodapés; logotipos e imagens; fundos; formatos de gráficos; proporção e dimensões dos slides. Temas
diferentes por cliente, sem valores visuais codificados nos componentes. Compatibilidade com apresentações da F06A.

## 3. Referências PPTX
Ferramenta local que inspeciona um PPTX autorizado e produz relatório técnico: quantidade/ordem dos slides; dimensões;
layouts e masters; cores; fontes; formas, textos e imagens; gráficos e tabelas; elementos reutilizáveis; elementos não
reproduzíveis diretamente. Arquivo local, sem serviços externos. Não importar textos confidenciais nem dados de
clientes. Não versionar PPTX original nem recursos proprietários. Sem PPTX de referência: testar com arquivo sintético
criado localmente.

## 4. Motor de comparação visual
Regressão visual de slides renderizados: captura determinística dos slides HTML; comparação por imagem com referência;
relatório de diferenças; registro de dimensões e tolerâncias; diagnóstico de elementos desalinhados; separação entre
diferenças de fonte, layout e conteúdo quando viável. Tolerâncias medidas e documentadas (sem porcentagem arbitrária
como prova de fidelidade). Fixtures sintéticas. Comparação definitiva com o PPTX oficial fica pendente.

## 5. Componentes reutilizáveis
Revisar os 11 tipos de slide: temas diferentes; layouts configuráveis; campos editáveis; indicadores aprovados;
gráficos com unidades e formatação corretas; valores ausentes e lacunas; referências de proveniência. Não reescrever o
que já está adequado. Não transformar slides em imagens (preservar elementos editáveis no PPTX futuro).

## 6. Confiabilidade do editor
Testes: duas edições em sequência rápida; salvamento concorrente; resposta de salvamento atrasada; falha na releitura
após HTTP 200; persistência após reinicialização; resposta antiga chegando após edição mais recente. Não assumir SQLite
como causa sem evidência. Sem retries indiscriminados. Defeito reproduzível ⇒ correção + teste de regressão.

## 7. Segurança
Não acessar a Veracode desnecessariamente; não alterar credenciais; não publicar PPTXs reais, logos proprietários ou
dados confidenciais; recursos originais fora do Git; snapshots sintéticos nos testes.

## 8. Validação
Backend pytest; frontend build; E2E Chromium; regressão visual; migrations se necessárias; npm audit e pip check;
gitleaks e verificações do repositório; GitHub Actions. Testes obrigatórios passando antes de commit e push.

## 9. Entrega
Atualizar `docs/AGENT_HANDOFF.md`, `docs/STATUS.md`, documentação de temas, da inspeção PPTX e da comparação visual.
Entregar ao PO: funcionalidades; formato dos temas; capacidades de inspeção PPTX; estratégia de comparação visual;
resultados dos testes; status da intermitência do editor; limitações de elementos editáveis; commits e CI;
dependências para concluir a F06B. Não iniciar F07/F08. Aguardar o PPTX de referência aprovado.
