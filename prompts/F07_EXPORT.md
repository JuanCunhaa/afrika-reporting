# ORDEM DO PO — F07: Exportação PPTX/PDF e Fidelidade Visual

**Projeto:** Afrika Reporting
**Fase:** F07
**Status:** F06C aprovada
**Próxima fase:** F08 — não autorizada

## Objetivo

Implementar a exportação de apresentações em PPTX editável e PDF, utilizando os contratos, templates, temas, layouts e snapshots aprovados das fases anteriores.

Não recriar o motor visual existente. O HTML, o PowerPoint e o PDF devem compartilhar uma representação intermediária consistente.

Não iniciar F08, geração de textos por IA ou novas integrações Veracode.

## 1. Preparação

Leia:
- CLAUDE.md.
- Skills relevantes.
- docs/AGENT_HANDOFF.md.
- docs/PRESENTATION_CONTRACTS.md.
- docs/F07_EXPORT_READINESS.md.
- docs/VISUAL_FIDELITY.md.

Inspecione os módulos necessários da F06A, F06B e F06C.

Reutilize o modelo afrika-modelo@2 e o tema afrika@2.

Preserve todos os templates e hashes anteriores.

Trabalhe incrementalmente, priorizando testes, segurança e economia de tokens.

## 2. Exportação PowerPoint

Implementar geração de arquivos .pptx válidos e editáveis.

Priorizar elementos nativos do PowerPoint:

- Caixas de texto editáveis.
- Formas e linhas vetoriais.
- Tabelas editáveis.
- Gráficos nativos com dados incorporados.
- Títulos e legendas editáveis.
- KPIs e indicadores como textos.
- Fundos e elementos decorativos em formas quando viável.

Imagens devem ser usadas somente para ativos visuais que realmente necessitem de rasterização ou não sejam representáveis de maneira editável.

Não transformar slides inteiros em screenshots.

Utilizar python-pptx ou outra solução adequada, documentando limitações reais da biblioteca.

Não declarar como editável um elemento que seja apenas uma imagem.

## 3. Contratos e representação intermediária

A exportação deverá consumir a mesma representação intermediária da F06.

Preservar:
- Template e versão.
- Tema e versão.
- Ordem e tipo dos slides.
- Dimensões 16:9.
- Textos editoriais.
- Indicadores aprovados.
- Proveniência.
- Unidades e formatos numéricos.
- Gráficos, tabelas e hierarquia visual.

Não recalcular métricas durante a exportação.

Não consultar novamente a Veracode.

A exportação deverá ser determinística para uma mesma revisão aprovada e versão de template, exceto metadados técnicos inevitavelmente variáveis.

## 4. Gráficos editáveis

Implementar gráficos nativos quando suportados:

- Barras.
- Linhas.
- Distribuições.
- Rankings.
- Séries históricas.

Preservar:
- Valores numéricos exatos.
- Rótulos.
- Unidades.
- Ordem de categorias.
- Cores do tema.
- Escala e limites dos eixos.
- Legendas.
- Dados ausentes.

Uma lacuna histórica deve permanecer ausente, jamais virar zero.

Não substituir o gráfico por imagem apenas para melhorar a comparação visual sem registrar a perda de editabilidade.

Caso determinado gráfico não seja suportado nativamente, documentar a limitação e utilizar uma alternativa explícita.

## 5. Matrizes, tabelas e textos extensos

Remover limitações artificiais de tamanho das células quando possível.

Implementar:
- Células multilinhas.
- Quebra de texto.
- Ajuste de fonte com limites mínimos.
- Controle de margens.
- Detecção de overflow.
- Layout alternativo ou divisão de conteúdo quando necessário.

Nunca truncar silenciosamente conteúdo.

Se não houver espaço suficiente, bloquear a exportação daquele slide com diagnóstico ou utilizar uma estratégia documentada que preserve todo o conteúdo.

Criar testes com textos maiores que 400 caracteres.

## 6. Regras visuais aprovadas

Utilizar os tokens do tema afrika@2.

Semântica:
- Crítica: vermelho.
- Alta: laranja.
- Média: amarelo.
- Baixa e Muito baixa: azul, mantendo categorias originais nos dados.
- Informativa: cinza.

Na apresentação executiva, permitir rótulo "Crítica" para a severidade original "Muito alta", preservando a origem.

Variações mensais:
- Verde somente para melhoria comprovada.
- Vermelho somente para piora comprovada.
- Neutro quando a direção desejável for desconhecida.

Não calcular sinalização visual apenas pelo sinal matemático da variação.

## 7. PDF

Implementar exportação PDF a partir de uma representação visual consistente com a apresentação.

Avaliar a melhor abordagem disponível no projeto:
- Conversão controlada de PPTX para PDF.
- Renderização HTML para impressão/PDF.
- Outra solução tecnicamente justificável.

Priorizar fidelidade, estabilidade e disponibilidade no Windows.

Se utilizar LibreOffice, detectar sua presença e tratar sua ausência sem falhas silenciosas.

Não declarar sucesso se o arquivo não for gerado ou estiver corrompido.

Não utilizar serviços online de conversão.

Preservar proporção, fontes, páginas e legibilidade.

## 8. Fluxo na interface

Adicionar ações de exportação na apresentação:

- Exportar PowerPoint.
- Exportar PDF.
- Consultar status e erros.

Permitir exportação somente de apresentações com fonte aprovada e referências íntegras.

As edições editoriais devem estar salvas antes da exportação.

Se existirem alterações não salvas, informar e exigir salvamento ou utilizar explicitamente a versão persistida, sem ambiguidade.

Não alterar os snapshots ao exportar.

## 9. Fidelidade visual

Comparar as saídas exportadas com a pré-visualização HTML.

Validar:
- Dimensões.
- Posicionamento.
- Tipografia.
- Cores.
- Formas.
- Tabelas.
- Gráficos.
- Cortes e overflow.
- Elementos ausentes.

Renderizar localmente os arquivos para comparação.

Utilizar conteúdo sintético equivalente em todas as modalidades.

Medir diferenças e produzir diagnósticos por slide.

Distinguir diferenças aceitáveis do mecanismo de renderização e defeitos reais.

Não considerar aprovado apenas porque o arquivo abre.

Não exigir fidelidade 100% em pixels quando os renderizadores usam mecanismos de fontes diferentes; registrar limites objetivos e evidências.

## 10. Ativos e confidencialidade

O PowerPoint original permanece em references/, fora do Git.

Ativos autorizados permanecem em data/brand-assets/afrika/, também fora do Git.

Se um ativo estiver ausente, utilizar fallback neutro.

Não versionar:
- Apresentações reais.
- PDFs reais.
- Dados de clientes.
- Credenciais.
- Screenshots confidenciais.
- Recursos proprietários não autorizados.

Testes e exemplos públicos devem utilizar exclusivamente dados sintéticos.

Não enviar arquivos para conversores ou serviços externos.

## 11. Segurança da exportação

- Validar nomes e caminhos dos arquivos.
- Impedir path traversal.
- Não aceitar caminhos arbitrários enviados pelo frontend.
- Gerar arquivos em diretório temporário seguro.
- Limpar artefatos temporários de maneira controlada.
- Impor limites de tamanho e duração.
- Não permitir injeção em comandos de conversão.
- Não executar macros.
- Preservar isolamento entre clientes.

O backend continua local, sem autenticação real de usuários.

Não expor endpoints publicamente.

## 12. Testes obrigatórios

Implementar testes para:

1. PPTX válido.
2. PDF válido.
3. Contagem e ordem dos slides.
4. Textos editáveis.
5. Tabelas editáveis.
6. Gráficos nativos editáveis.
7. Dados incorporados aos gráficos.
8. Valores numéricos exatos.
9. Lacunas sem zero.
10. Severidades.
11. Direções de variação.
12. Matrizes com textos longos.
13. Detecção de overflow.
14. Template afrika-modelo@2.
15. Templates antigos.
16. Cliente e subcliente.
17. Revisões aprovadas.
18. Recusa de fonte não aprovada.
19. Integridade das referências.
20. Alterações não salvas.
21. Download pela interface.
22. Erros de conversão.
23. Fontes ausentes.
24. Ativos locais ausentes.
25. Segurança dos caminhos.
26. Regressão visual.
27. Regressão das fases anteriores.

Inspecionar programaticamente o PPTX para comprovar editabilidade, não apenas sua aparência.

## 13. Execução e desempenho

Evitar rodar testes completos, múltiplos browsers e conversores simultaneamente no Windows.

Executar etapas pesadas de forma sequencial quando necessário.

Se uma execução for interrompida por falta de memória, registrar NOT_RUN e o motivo.

Não ocultar testes falhos ou incompletos.

## 14. Validação final

Executar:
- pytest.
- Build frontend.
- E2E Chromium.
- Regressão visual.
- Validação estrutural de PPTX.
- Validação estrutural de PDF.
- npm audit.
- pip check.
- Gitleaks.
- check_repo.
- GitHub Actions.

Não realizar chamadas Veracode.

Corrigir falhas antes dos commits.

## 15. Entregáveis

Atualizar:
- docs/STATUS.md.
- docs/AGENT_HANDOFF.md.
- docs/PRESENTATION_CONTRACTS.md.
- Documentação de exportação.
- Matriz de editabilidade.
- Relatório de fidelidade HTML × PPTX × PDF.

Entregar ao PO:

1. Formatos implementados.
2. Estratégia de exportação.
3. Tipos de elementos efetivamente editáveis.
4. Limitações.
5. Fidelidade visual medida.
6. Resultados dos testes.
7. Evidência de arquivos PPTX/PDF válidos.
8. Fluxo de download.
9. Segurança.
10. Desempenho.
11. Commits.
12. Resultado do CI.
13. Pendências para F08.

Gerar arquivos demonstrativos sintéticos, sem incluí-los no repositório público caso contenham ativos não autorizados.

Faça commit e push somente de arquivos seguros, com testes obrigatórios passando.

**Não iniciar F08. Aguarde aprovação do PO.**
