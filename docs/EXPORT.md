# Exportação PPTX (editável) e PDF (F07 + F07.1)

Código: `backend/app/export/` · API: `backend/app/api_exports.py` · CLI: `python -m app.cli export` · UI: painel
**Exportar** no editor (`frontend/src/pages/ExportPanel.tsx`) · extração de layout: `frontend/src/presentation/exportLayout.ts`.
Fidelidade medida: `docs/EXPORT_FIDELITY.md`. Contrato de entrada: `docs/PRESENTATION_CONTRACTS.md` (plano de exportação).

## 1. Formatos e estratégia
| Formato | Como é gerado | Editável |
|---|---|---|
| **PPTX** | objetos NATIVOS do PowerPoint montados com `python-pptx` 1.0.2 (+ XML OOXML direto onde a biblioteca não cobre: `custGeom`, `pattFill`, `manualLayout`, fontes incorporadas, propriedades personalizadas) a partir do **layout renderizado** da pré-visualização + IR aprovada + tokens do tema | sim (texto, formas, linhas, tabelas, gráficos com planilha) |
| **PDF** | impressão (`Page.printToPDF`, CDP) da **mesma página** `#/render` usada na pré-visualização; fontes incorporadas | não (documento final) |

Uma única representação intermediária para as três modalidades: `view.build` (revisão PERSISTIDA da apresentação +
revisões APROVADAS fixadas + tema) → página `#/render` do build do frontend → (a) layout por elemento (`exportLayout.ts`)
→ PPTX; (b) impressão → PDF. Nada é recalculado; nenhuma chamada à Veracode; nenhum serviço online de conversão;
LibreOffice/PowerPoint **não** são usados na geração (só, opcionalmente, na medição local de fidelidade).

### Por que HTML→PDF e não PPTX→PDF
O PDF sai do mesmo renderizador da pré-visualização (Chromium do Playwright, já usado na regressão visual), disponível
no Windows e no CI Linux sem software proprietário. Medido: HTML×PDF ≤ 0,39% de pixels diferentes por slide e texto
deslocado no máximo 1 px (`docs/EXPORT_FIDELITY.md`). PPTX→PDF exigiria PowerPoint (Windows, licença) ou LibreOffice
(não instalado; fidelidade de fontes/gráficos inferior).

## 2. Fluxo
1. **Pré-checagem** (`service.precheck`, síncrona, 409 com diagnóstico): cadeia de revisões e template íntegros
   (`presentations.verify`), política de fontes `APPROVED_ONLY_PINNED` com fonte primária, todas as fontes fixadas
   existentes e aprovadas com hash conferido, nenhum bloqueio na visualização (ex.: indicador obrigatório sem valor).
2. **Fila** (`jobs.py`): uma thread, um navegador por vez; `MAX_QUEUE = 4` aguardando (429 acima), `MAX_JOBS = 50`
   guardados, retenção `TTL_S = 30 min`; arquivos num diretório temporário próprio da instância (`AFRIKA_EXPORT_DIR`
   absoluto ou temp do sistema), um subdiretório por job, apagados na expiração e no desligamento.
3. **Renderização** (`render.capture`): Chromium headless via CDP, perfil descartável, `--host-resolver-rules=MAP *
   ~NOTFOUND`; toda requisição é interceptada — só `dist/` do build, a visualização injetada e ativos do tema; qualquer
   outra é bloqueada e **falha** o job (`render_request_blocked`). Prazo por job (padrão 120 s).
4. **Bloqueios de conteúdo** (por slide, nunca truncamento silencioso): corte real além do recuo interno, vazamento de
   texto, saída da zona/slide, reticências (CSS) e **rótulo de eixo abreviado** (F07.1) ⇒ `content_overflow`; fonte do
   tema substituída por fonte de sistema ⇒ `font_unavailable`. Conteúdo que só invade o recuo vira aviso.
5. **Montagem + validação** (`pptx_builder`, `opc`, `validate`, `pdf.validate`) — sucesso só se a inspeção passar.
6. **Download** `GET /api/exports/{id}/file` (nome gerado no servidor, `nosniff`, `no-store`, cabeçalho
   `X-Export-Sha256`) + auditoria `presentation.exported` (ids, formato, SHA-256, tamanho; nenhum dado).

| Endpoint | Uso |
|---|---|
| `GET /api/export-engine` | disponibilidade (build do renderizador atualizado? navegador?) sem abrir navegador |
| `POST /api/presentations/{pid}/exports` `{format, revision, operator}` | cria exportação da revisão PERSISTIDA informada (202) |
| `GET /api/presentations/{pid}/exports` | exportações recentes (status, erros, avisos, relatório) |
| `GET /api/exports/{id}` · `GET /api/exports/{id}/file` | status · download (só concluída) |

**Interface:** botões *Exportar PowerPoint* / *Exportar PDF* exportam sempre a **revisão salva** exibida no painel; com
alterações não salvas os botões ficam desabilitados com o aviso "alterações não salvas" até salvar (sem ambiguidade
entre rascunho e persistido). Apresentação com bloqueios mostra o motivo e não exporta; a API recusa mesmo se chamada
diretamente. Status por job (Na fila / Gerando… / Concluída / Falhou), tamanho, SHA-256, tempo e erros com diagnóstico.

**Build do renderizador:** `npm run build` grava `dist/afrika-render.json` com o hash do código-fonte da
pré-visualização (`render-stamp.mjs`); o backend recalcula e **recusa** um `dist` desatualizado (`renderer_stale`).

## 3. Matriz de editabilidade (verificada programaticamente no PPTX gerado)
| Elemento | Objeto PPTX | Editável | Observação |
|---|---|---|---|
| títulos, subtítulos, parágrafos, tópicos, rodapé, selo | `p:sp` com `txBody` (fonte, tamanho, cor, entrelinha exata, marcadores) | sim | título de seção vertical = `vert270` |
| KPIs e indicadores | texto (`p:sp`) sobre moldura (forma) | sim | valor = rótulo pt-BR já formatado da IR |
| fundos, cartões, pílulas, filetes, painéis curvos | `prstGeom`/`custGeom` (contorno M/L/C/Q/A/Z do tema), preenchimento com alpha, `pattFill dkUpDiag` p/ "Desconhecida" | sim | |
| linhas e setas | conector com `tailEnd` | sim | |
| tabelas, rankings, matriz | `graphicFrame`/`a:tbl` | sim | espaço entre células = borda na cor do fundo; cantos arredondados do HTML não existem em célula |
| barras (colunas), linhas, combinado barras+linha, severidade (barras horizontais), rosca | `c:chart` nativo + planilha `.xlsx` incorporada | sim | cor por ponto = token do tema |
| ativo de marca autorizado (logo, foto) | `p:pic` (SVG com PNG de reserva) | não (inevitável) | só se o arquivo existir na pasta local; ausência ⇒ encaixe vazio (fallback neutro) |
| dado indisponível | texto com o motivo | sim | nunca número presumido |

**Contagem nos decks sintéticos medidos (F07.1):**
| Caso | Slides | Texto | Formas | Linhas | Tabelas | Gráficos nativos | Imagens | **Editáveis** |
|---|---|---|---|---|---|---|---|---|
| `afrika-modelo@2` (16 slides) | 16 | 301 | 146 | 10 | 6 | 6 (2 rosca, 1 barras+linha, 3 colunas) | 0 | **469** |
| `neutral-demo@1` (19 slides) | 19 | 179 | 44 | 40 | 4 | 6 (2 colunas, 2 linhas, 2 barras horizontais) | 0 | **273** |

Gráficos: 6 planilhas incorporadas por deck; o validador confere que o cache do gráfico **e** a planilha têm exatamente
os valores aprovados da IR e que o nº de gráficos/tabelas é o previsto no plano de exportação. Nenhum slide é imagem;
nenhum dado vira imagem (o validador recusa qualquer `p:pic` que não seja ativo autorizado e qualquer mídia extra).

## 4. Dados, lacunas e semântica
- Valores exatos da IR; rótulos de dados com o texto pt-BR da IR (milhar ".", decimal ","), independentes do idioma do
  PowerPoint de quem abre. Escala: eixo Y de 0 ao mesmo máximo "redondo" do HTML; mesma rarefação de meses.
- Lacuna/ausente/incompatível ⇒ **célula vazia** na planilha e `dispBlanksAs="gap"` (linha quebrada, sem barra) —
  nunca 0, nunca interpolação.
- Severidade (`afrika@2`): Crítica vermelho · Alta laranja · Média amarelo · Baixa e Muito baixa azul (categorias
  originais preservadas) · Informativa cinza. Rótulo executivo "Crítica" opcional por documento
  (`severity_labels: executive`), com a categoria original em `source_label`/`key` e na propriedade
  `afrika.severity_labels`.
- Variação: verde só para melhora comprovada, vermelho só para piora comprovada, neutro sem direção declarada — vem da IR
  (`trend`), nunca do sinal matemático.
- Matriz: células de até 1000 caracteres; linhas com altura proporcional e fonte reduzida em degraus até 60%; sem caber
  no mínimo ⇒ bloqueio com diagnóstico por slide.
- Rótulo de categoria longo (F07.1): quebra em até 3 linhas no HTML/PDF (área de plotagem reservada; o PPTX usa a mesma
  área e recebe a categoria completa); acima disso ⇒ bloqueio (`ellipsis`, "rótulo do eixo … abreviado").

## 5. Determinismo e proveniência
- Mesma revisão + mesmo template/tema + mesmo build ⇒ **mesmo SHA-256** (testado): datas técnicas = criação da revisão
  exportada; ZIP com data fixa e ordem estável; planilhas internas normalizadas; IDs de nó do PDF normalizados.
- Propriedades personalizadas no PPTX (`docProps/custom.xml`): apresentação, revisão e hashes (revisão, documento,
  fontes), template@versão + hash, tema@versão + hash, dono, competência, fonte primária (competência/revisão/aprovação/
  hash), política de dados, rótulos de severidade, versões do plano/layout, hash do código do renderizador, motor.
- Descrição (`descr`) de cada objeto com dado: indicador | competência | estado | origem.

## 6. Fontes (F07.1 — registrado separadamente)
| Fonte (papel no `afrika@2`) | Declarada no arquivo | Incorporada estruturalmente | Aplicada pelo PowerPoint sem a fonte instalada (Windows 11, Microsoft 365 16.0.20430) | Outro computador |
|---|---|---|---|---|
| Montserrat / Montserrat Black (títulos) | sim (`a:latin`) | sim — EOT em `ppt/fonts/*.fntdata` + `embeddedFontLst` | **sim** (render sem fontes na sessão = render com fontes; capa 0 px de diferença) | NOT_VERIFIED |
| Poppins (corpo) | sim | sim | **sim** (corpo da matriz idêntico) | NOT_VERIFIED |
| Be Vietnam Pro / SemiBold (números: KPIs, cabeçalhos de tabela, rótulos da matriz, rótulos de dados — 78 objetos + 4 gráficos) | sim | sim | **não** — substituída por fonte de reserva | NOT_VERIFIED (esperado: substituída sem a fonte instalada) |
| Arial (tema neutro) | sim | não (fonte de sistema; só o nome) | sim (instalada) | depende da fonte instalada |

Evidência (local, dados sintéticos, nada versionado): (1) deck exportado aberto **sem** registrar fontes ⇒ Montserrat e
Poppins aplicadas, Be Vietnam Pro não; (2) controle: o **próprio PowerPoint** criou um deck com as 5 faces e o salvou
incorporando fontes — reaberto sem as fontes, o resultado foi o mesmo (Be Vietnam Pro não aplicada) ⇒ não é defeito do
nosso EOT; (3) `fsType = 0` (incorporação livre) e checksums de tabela corretos nas 11 faces. A propriedade
`Font.Embedded` do COM retorna `False` até para fontes aplicadas — não serve de prova. **PDF:** todas as fontes
incorporadas (validado em cada exportação). Recomendação: instalar Be Vietnam Pro (OFL) onde o PPTX for editado, ou o PO
decidir outra fonte numérica. Arquivos de fonte nunca são versionados (`check_repo` bloqueia).

## 7. Segurança
Caminhos e nomes só gerados no servidor (slug ASCII; download pelo id aleatório do job; o cliente não envia caminho);
CLI só grava em `output/`, `private/`, `data/` (ignorados) ou fora do repositório; diretórios temporários próprios, limpeza controlada;
limites de fila, prazo, tamanho (100 MiB) e retenção; navegador com argumentos fixos (sem shell, sem interpolação de
entrada), perfil descartável e sem rede; validador recusa macros, ActiveX/OLE, relações externas e XML malformado (parser
sem entidades/rede); PDF recusado com JavaScript/Launch/arquivo incorporado/ações automáticas; isolamento por dono
(cliente × subcliente testado); endpoints só em loopback, sem autenticação real (inalterado).

## 8. Desempenho (medição local, Windows)
`afrika-modelo@2` 16 slides: PPTX 256 KB em 1,7 s · PDF 371 KB em 1,0 s. `neutral-demo` 19 slides: PPTX 114 KB em
1,3 s · PDF 312 KB em 1,1 s (navegador já aquecido; um job por vez).

## 9. Limitações conhecidas
- Be Vietnam Pro incorporada não é aplicada pelo PowerPoint testado (seção 6); outro computador NOT_VERIFIED.
- Cantos arredondados de células e rótulos de dados posicionados pelo próprio PowerPoint (ver `EXPORT_FIDELITY.md`).
- Rótulos de dados são texto personalizado: ao editar os dados do gráfico no PowerPoint, atualizar/remover o rótulo.
- Lista de severidade do tema neutro vira gráfico de barras horizontais nativo (rótulos alinhados ao eixo, sem trilho).
- Fontes de sistema (tema neutro) dependem do computador que abre o PPTX.
- Fila em memória: reiniciar o backend descarta jobs e arquivos (por desenho).
