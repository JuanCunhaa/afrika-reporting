"""F07 — exportação PPTX (editável) e PDF a partir da MESMA representação da pré-visualização.

Fluxo (nada é recalculado; nenhuma chamada à Veracode):
1. `view.build` (revisão PERSISTIDA da apresentação + revisões APROVADAS fixadas + tema) e `export_plan.plan` (F06C).
2. `render.capture`: Chromium headless (CDP) abre a rota `#/render` do build do frontend (`dist`), com a visualização
   injetada por interceptação de requisições (sem rede); extrai o layout renderizado de cada slide, o detector de
   overflow e as fontes efetivas; o PDF é a impressão dessa mesma página.
3. `pptx_builder.build`: objetos NATIVOS do PowerPoint (texto, formas, tabelas, gráficos com planilha incorporada;
   imagem só para ativo de marca autorizado) a partir do layout + IR aprovada + tokens do tema.
4. `validate`: inspeção estrutural do PPTX e do PDF antes de declarar sucesso.
"""
