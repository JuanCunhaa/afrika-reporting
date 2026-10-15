# ORDEM DO PO — F06A: Motor de Templates e Pré-visualização

**Projeto:** Afrika Reporting · **Fase:** F06A · **Status anterior:** F05 aprovada · **Próximas:** F06B, F07, F08 — não autorizadas

Executar exclusivamente a F06A. Criar um motor reutilizável de apresentações HTML, alimentado por snapshots aprovados
da F05, preparado para exportação futura em PPTX e PDF. Identidade visual oficial ainda não escolhida: usar tema
demonstrativo neutro, claramente identificado como provisório.

## 1. Preparação
Ler CLAUDE.md, skills pertinentes, handoff F05, contratos de métricas e snapshots e roadmap. Reutilizar componentes;
não refatorar módulos estáveis desnecessariamente.

## 2. Sistema de templates
Definições tipadas e versionadas: identificador e versão; nome e descrição; tema; slides ordenados; layout por slide;
indicadores vinculados; campos editáveis; regras de obrigatoriedade; compatibilidade com versões dos contratos de
métricas. Cada cliente/subcliente escolhe um template (sem conjunto universal). Adicionar, remover e reordenar slides.
Não armazenar números no template.

## 3. Tipos de slides (componentes disponíveis, não obrigatórios)
Capa; sumário executivo; KPIs; mês atual × anterior; barras; linhas/séries históricas; distribuição por severidade;
ranking Top 10; tabela de indicadores; recomendações e observações; encerramento.

## 4. Vinculação com snapshots
Toda apresentação usa revisão aprovada da F05. Preservar cliente/subcliente, competência, ID da revisão aprovada,
template e versão, indicadores, origem e qualidade dos dados, hash de integridade. Não consultar a Veracode para
reconstruir históricos aprovados. Nunca inventar valores; exibir lacunas e indisponibilidades.

## 5. Edição
Pré-visualização HTML navegável; edição de título e textos livres; seleção de métricas compatíveis; inclusão/exclusão;
reordenação; títulos de gráficos; legendas e observações; apresentadores; visualização dos dados de origem. Edições
editoriais não alteram valores aprovados; correção de indicador = nova revisão na F05.

## 6. Gráficos
Representação intermediária independente do renderizador: barras, linhas, severidade, rankings, comparação, tabelas.
Contratos de cores, eixos, rótulos, unidade e arredondamento. Só dados aprovados; sem métricas por inferência.

## 7. Arquitetura visual
Separar dados/proveniência, modelo de apresentação, tema, layout, renderização HTML e futura exportação PPTX/PDF.
Artefatos editáveis (não transformar slides em imagens). Tema neutro, responsivo para edição, canvas 16:9. Não
reproduzir a marca Afrika sem referência aprovada.

## 8. Persistência
Apresentações, seleção de template, ordem dos slides e conteúdo editorial; migrations versionadas; histórico/revisões;
editor não altera snapshots aprovados.

## 9. Testes
Slides opcionais; templates por cliente; snapshots aprovados; rejeição de rascunhos; séries de 6 e 12 meses; dados
ausentes; manuais identificados; gráficos sem números inventados; edição sem alterar métricas; reordenação e remoção;
persistência após reinicialização; versionamento de templates; integridade das referências; E2E completo da
pré-visualização; regressão. Investigar a intermitência de `scopes.spec.ts` sem retries indiscriminados.

## 10. Segurança
Não modificar credenciais/políticas Veracode; não iniciar scans; sem coletas reais desnecessárias; fixtures e
snapshots sintéticos; nada de dados reais no GitHub; sem logos/templates proprietários.

## 11. Validação
Testes backend; build frontend; Playwright Chromium; dependências; gitleaks; migrations; GitHub Actions.

## 12. Entrega
Atualizar AGENT_HANDOFF, STATUS, documentação do motor e contratos de templates/gráficos. Entregar funcionalidades,
tipos de slides, modelo de templates, persistência/migrations, endpoints/interface, testes, CI, limitações,
pendências para F06B, commits e push (somente arquivos seguros). Aguardar aprovação do PO.
