# ORDEM DO PO — F06C: Homologação Visual e Preparação para Exportação

**Projeto:** Afrika Reporting · **Fase:** F06C · **Status anterior:** F06B aprovada · **Não autorizadas:** F07, F08

Registro resumido da ordem (o texto original citava o cliente da referência; aqui fica omitido de propósito — o produto
é genérico).

## Objetivo
Consolidar o tema Afrika, completar contratos visuais, validar os layouts com dados sintéticos e garantir que a
representação intermediária esteja preparada para exportação editável em PPTX e PDF — aproveitando integralmente a
F06B (sem reimplementar `afrika-modelo@1` nem os 16 layouts) e preservando templates existentes e seus hashes.

## Decisões visuais do PO (semântica configurável, por tokens do tema)
- Severidade: Crítica vermelho · Alta laranja · Média amarelo · Baixa azul · Informativa cinza.
- Variação mensal: melhora comprovada verde · piora comprovada vermelho · direção desconhecida neutra.
- Não assumir que toda redução é boa nem que todo aumento é ruim: cada indicador declara a direção desejável ou fica
  neutro.

## Templates
16 layouts como modelo-base; seleção flexível de slides por cliente/subcliente/indicadores disponíveis; só capa e
encerramento obrigatórios; nenhuma apresentação precisa ter 16 slides; nenhum número do cliente da referência em
templates ou exemplos.

## Fidelidade visual
Manter a comparação geométrica e acrescentar comparação integral com conteúdo sintético equivalente, separando
geometria, tipografia, cores, gráficos, distribuição de conteúdo e overflow/cortes; registrar o que decorre da ausência
de ativos oficiais e o que é defeito do layout; não prometer fidelidade completa com base só em imagens mascaradas.

## Ativos locais
Mecanismo configurável para carregar ativos visuais autorizados de pasta local ignorada pelo Git, com fallbacks
neutros; nada proprietário no repositório público; não enviar o PPTX original ou seus recursos a serviços externos de IA.

## Preparação para F07
Revisar a IR e registrar, por tipo de slide, a exportação futura como texto editável, forma vetorial, tabela editável,
gráfico nativo ou imagem (só quando inevitável); contratos e testes, sem implementar a exportação definitiva; lacunas
históricas continuam lacunas na exportação.

## Confiabilidade e validação
Salvamentos rápidos, concorrência de revisões, respostas atrasadas, overflow Windows × Linux, renderização sem fontes
proprietárias, regressões visuais, integridade dos snapshots; sem retries indiscriminados. pytest, E2E Chromium,
regressão visual, build, auditorias, gitleaks, check_repo e migrations; dados sintéticos; sem chamadas à Veracode.

## Entrega
Atualizar STATUS, AGENT_HANDOFF, PRESENTATION_CONTRACTS e a documentação do tema e da fidelidade; commit e push só de
arquivos seguros; não iniciar F07/F08; aguardar o PO.
