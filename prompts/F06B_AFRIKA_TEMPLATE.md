# ORDEM DO PO — F06B: Template de referência Afrika

**Projeto:** Afrika Reporting · **Fase:** F06B · **Status anterior:** F06A aprovada (F06B.1 entregue) ·
**Não autorizadas:** F07, F08

Registro resumido da ordem (o texto original citava o cliente e a unidade de negócio da referência; aqui ficam
omitidos de propósito — o produto é genérico).

## Contexto
Há um PowerPoint real como referência visual, guardado **localmente** em `references/` (fora do Git). Objetivo: usar o
arquivo para reproduzir a identidade visual e os layouts no HTML, **sem** ficar limitado ao cliente nem à unidade de
negócio da referência.

## Instruções
1. Confirmar que o arquivo existe e está protegido pelo `.gitignore`, inclusive contra publicação acidental.
2. Analisar slides, layouts, cores, fontes, fundos, gráficos, tabelas, cabeçalhos, rodapés e elementos visuais.
3. Identificar tipos de slide reutilizáveis e relacioná-los aos componentes da F06A.
4. Criar um tema Afrika versionado mantendo a identidade.
5. Reproduzir os layouts no HTML preservando a edição de títulos, textos e gráficos.
6. Substituir dados reais, nomes, aplicações e indicadores da referência por dados sintéticos/placeholders em testes e
   exemplos.
7. Qualquer cliente/subcliente pode usar os layouts, com indicadores e quantidade de slides configuráveis.
8. Comparação visual por slide, documentando diferenças e limitações.
9. Arquitetura pronta para exportação PPTX/PDF na F07.

## Segurança
Não versionar o PowerPoint original. Não publicar imagens, textos, números ou informações confidenciais extraídas do
arquivo. Não enviar o PowerPoint a serviços externos de IA. Não incluir o conteúdo real em prompts, logs ou fixtures.
Não alterar o arquivo original.

## Validação e entrega
Testes de backend, frontend, E2E, regressão visual e verificações de segurança; atualizar `docs/STATUS.md` e
`docs/AGENT_HANDOFF.md`; commit e push **somente dos arquivos seguros**; relatório com layouts implementados,
fidelidade visual alcançada, limitações, testes, commits e resultado do CI. Não iniciar F07 ou F08; aguardar o PO.
