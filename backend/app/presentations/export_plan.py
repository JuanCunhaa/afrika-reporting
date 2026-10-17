"""Plano de exportação (F06C — preparação da F07). NÃO gera PPTX nem PDF.

Descreve, a partir da MESMA visualização usada pelo HTML (`view.build`: IR de dados aprovados + tema), como cada
elemento de cada slide deverá ser exportado e com que limitações. Tipos de saída (`export_as`):
- `text` — caixa de texto editável (parágrafos, tópicos, texto vertical);
- `shape` — forma vetorial editável (predefinida ou `custGeom` a partir do contorno do tema, com opacidade);
- `table` — tabela editável;
- `native_chart` — gráfico nativo do PowerPoint com dados incorporados (barras, linhas, combinado, rosca);
- `image` — SÓ ativos de marca (logo/foto/ilustração/ícones) e imagens do tema: inevitável, nunca dado.

Garantias (testadas em `test_export_plan.py`): nenhum dado vira imagem; lacuna/ausente nunca vira 0 (valor `None` —
célula vazia, `dispBlanksAs="gap"` — mais o texto de estado); cores são TOKENS do tema resolvidos na paleta efetiva;
a ordem/quantidade de slides é a do documento da revisão.
"""
from __future__ import annotations

from typing import Any

PLAN_VERSION = 1
EMU_PER_PX = 9525  # 1 px CSS (96 dpi) = 9525 EMU
EXPORT_KINDS = ('text', 'shape', 'table', 'native_chart', 'image')

# Matriz de editabilidade por componente (também documentada em docs/F07_EXPORT_READINESS.md).
MATRIX: dict[str, dict[str, Any]] = {
    'background': {'export_as': 'shape', 'editable': True, 'pptx': 'fundo do slide (bg/solidFill)'},
    'theme_shape': {'export_as': 'shape', 'editable': True,
                    'pptx': 'prstGeom rect/roundRect ou custGeom (contorno M/L/C/Q/A/Z do tema) com alpha'},
    'brand_asset': {'export_as': 'image', 'editable': False,
                    'pptx': 'pic (PNG/JPEG; SVG via svgBlip com PNG de reserva)',
                    'limitations': ['imagem é inevitável (ativo de marca); só se o arquivo autorizado existir na '
                                    'pasta local — senão o encaixe fica vazio (fallback neutro)']},
    'theme_image': {'export_as': 'image', 'editable': False, 'pptx': 'pic (ativo local do tema por SHA-256)'},
    'title': {'export_as': 'text', 'editable': True, 'pptx': 'sp/txBody (placeholder de título)'},
    'subtitle': {'export_as': 'text', 'editable': True, 'pptx': 'sp/txBody'},
    'body': {'export_as': 'text', 'editable': True, 'pptx': 'sp/txBody (parágrafos)'},
    'bullets': {'export_as': 'text', 'editable': True, 'pptx': 'sp/txBody com marcadores'},
    'caption': {'export_as': 'text', 'editable': True, 'pptx': 'sp/txBody'},
    'underline': {'export_as': 'shape', 'editable': True, 'pptx': 'roundRect'},
    'badge': {'export_as': 'shape', 'editable': True, 'pptx': 'roundRect com contorno + txBody (mês/ano)'},
    'footer_text': {'export_as': 'text', 'editable': True, 'pptx': 'sp/txBody (nº de página: campo slidenum)'},
    'cover_text': {'export_as': 'text', 'editable': True, 'pptx': 'sp/txBody'},
    'presenters': {'export_as': 'text', 'editable': True, 'pptx': 'sp/txBody'},
    'section_title': {'export_as': 'text', 'editable': True, 'pptx': 'sp/txBody com bodyPr vert="vert270"'},
    'closing_group': {'export_as': 'text', 'editable': True, 'pptx': 'sp/txBody (título | texto)'},
    'zone_frame': {'export_as': 'shape', 'editable': True, 'pptx': 'roundRect (moldura da zona, cor do tema)'},
    'zone_title': {'export_as': 'text', 'editable': True, 'pptx': 'sp/txBody'},
    'kpi': {'export_as': 'text', 'editable': True,
            'pptx': 'sp/txBody (valor, nome e unidade em parágrafos; estado "ausente"/"lacuna" como texto)'},
    'kpi_card': {'export_as': 'shape', 'editable': True, 'pptx': 'roundRect + txBody'},
    'variation_pill': {'export_as': 'shape', 'editable': True,
                       'pptx': 'roundRect com preenchimento da cor da tendência (alpha) + txBody com o rótulo'},
    'comparison_table': {'export_as': 'table', 'editable': True, 'pptx': 'graphicFrame/tbl'},
    'comparison_columns': {'export_as': 'text', 'editable': True,
                           'pptx': 'txBody por coluna + seta (forma rightArrow/linha com ponta)'},
    'severity_cards': {'export_as': 'shape', 'editable': True, 'pptx': 'rect da barra de cor + txBody por severidade'},
    'bar_chart': {'export_as': 'native_chart', 'editable': True, 'pptx': 'c:barChart (barDir=col, clustered)'},
    'line_chart': {'export_as': 'native_chart', 'editable': True, 'pptx': 'c:lineChart (marcadores)'},
    'combo_chart': {'export_as': 'native_chart', 'editable': True,
                    'pptx': 'c:barChart + c:lineChart no MESMO eixo (sem eixo duplo)'},
    'severity_chart': {'export_as': 'native_chart', 'editable': True,
                       'pptx': 'c:barChart com c:dPt (cor por severidade)'},
    'donut': {'export_as': 'native_chart', 'editable': True,
              'pptx': 'c:doughnutChart com c:dPt; filete = contorno da série na cor da superfície'},
    'ranking_table': {'export_as': 'table', 'editable': True, 'pptx': 'graphicFrame/tbl (ordem da fonte)'},
    # F07: o layout ranking-bars do HTML é uma TABELA com barras embutidas; exportá-lo como gráfico perderia colunas
    # (posição, extras). Tabela nativa completa + barras como formas vetoriais decorativas (o número é texto na célula).
    'ranking_bars': {'export_as': 'table', 'editable': True,
                     'pptx': 'graphicFrame/tbl (ordem da fonte) + barras como formas (decorativas; valor na célula)'},
    'metric_table': {'export_as': 'table', 'editable': True, 'pptx': 'graphicFrame/tbl'},
    'matrix': {'export_as': 'table', 'editable': True, 'pptx': 'graphicFrame/tbl (1ª linha = cabeçalho)'},
    'unavailable': {'export_as': 'text', 'editable': True,
                    'pptx': 'sp/txBody com o motivo ("Dado indisponível" — nunca um número presumido)'},
}

LIMITATIONS = [
    {'code': 'adaptive_type', 'message': 'Zonas usam tamanho de fonte adaptativo (container queries: limite por '
     'largura e nº de caracteres). O exportador precisa calcular o MESMO tamanho (sem autofit do PowerPoint).'},
    {'code': 'fonts', 'message': 'O PPTX referencia `export_family` de cada papel de fonte (Montserrat/Poppins/Be '
     'Vietnam Pro no tema Afrika, OFL). Sem a fonte instalada ou incorporada, o PowerPoint substitui; no PDF as '
     'fontes são incorporadas.'},
    {'code': 'number_format_locale', 'message': 'Rótulos de dados em pt-BR: o código de formato do gráfico segue o '
     'locale de quem abre. Para garantir milhar "." e decimal ",", usar o rótulo já formatado da IR como texto do '
     'rótulo (editável) — decisão da F07.'},
    {'code': 'chart_geometry', 'message': 'Eixos, escala e grade do gráfico nativo são calculados pelo PowerPoint: '
     'valores idênticos aos aprovados, geometria pode diferir do SVG.'},
    {'code': 'unknown_texture', 'message': 'Textura da severidade "Desconhecida" vira preenchimento de padrão '
     '(pattFill dkUpDiag) — aproximação editável.'},
    {'code': 'svg_assets', 'message': 'Ativo de marca em SVG precisa de PNG de reserva no PPTX (svgBlip).'},
]

_FRAMED = {'severity_cards', 'comparison', 'ranking', 'table'}


def _el(component: str, binding: str, **extra) -> dict:
    m = MATRIX[component]
    return {'component': component, 'export_as': m['export_as'], 'editable': m['editable'], 'binding': binding,
            **extra}


def _slide_kind(t: str) -> str:
    return t if t in ('cover', 'closing', 'section') else 'content'


def _values(points: list[dict]) -> list:
    """Valor aprovado exato ou None (lacuna/ausente/incompatível): NUNCA 0 presumido."""
    return [p['y'] if p.get('state') == 'VALUE' and p.get('y') is not None else None for p in points]


def _chart(component: str, chart_type: str, ir: dict | None, binding: str) -> list[dict]:
    if not ir or ir.get('available') is False:
        return [_el('unavailable', binding, reason=(ir or {}).get('reason', 'no_data'))]
    if ir.get('empty') or not ir.get('series'):  # distribuição aprovada sem itens: o HTML mostra "indisponível"
        return [_el('unavailable', binding, reason='empty')]
    series = []
    for i, s in enumerate(ir.get('series', [])):
        colors = [p.get('color') for p in s['points']]
        series.append({'name': s['label'], 'metric_id': s['metric_id'], 'color': s['color'],
                       'render': 'bar' if chart_type == 'combo' and i == 0 else 'line' if chart_type == 'combo'
                       else chart_type, 'values': _values(s['points']), 'states': [p['state'] for p in s['points']],
                       'point_colors': colors if any(colors) else None})
    return [_el(component, binding, chart={
        'type': chart_type, 'categories': list(ir.get('categories', [])), 'series': series, 'blanks_as': 'gap',
        'gaps': list(ir.get('gaps', [])), 'data_labels': ir.get('show_values', True) is not False,
        'legend': bool((ir.get('legend') or {}).get('show')), 'number_format': ir.get('number_format'),
        'y_axis': ir.get('y_axis'), 'total': ir.get('total'), 'empty': bool(ir.get('empty'))})]


def _ranking(ir: dict | None, binding: str, bars: bool) -> list[dict]:
    if not ir or ir.get('available') is False:
        return [_el('unavailable', binding, reason=(ir or {}).get('reason', 'no_data'))]
    rows = ir.get('rows', [])
    if ir.get('empty'):
        return [_el('unavailable', binding, reason='empty')]
    return [_el('ranking_bars' if bars else 'ranking_table', binding,
                table={'columns': list(ir.get('columns', [])), 'rows': len(rows) + len(ir.get('aggregate_rows', []))})]


def _kpis(ir: dict | None, binding: str, component: str = 'kpi') -> list[dict]:
    if not ir or ir.get('available') is False:
        return [_el('unavailable', binding, reason=(ir or {}).get('reason', 'no_data'))]
    return [_el(component, f'{binding}.items[{i}]', metric_id=k['metric_id'], state=k['state'],
                value=k['y'] if k['state'] == 'VALUE' else None, label=k['label'])
            for i, k in enumerate(ir.get('items', []))]


def _comparison(ir: dict | None, binding: str, variant: str) -> list[dict]:
    if not ir or ir.get('available') is False:
        return [_el('unavailable', binding, reason=(ir or {}).get('reason', 'no_data'))]
    rows = ir.get('rows', [])
    out = []
    if variant == 'table':
        out.append(_el('comparison_table', binding, table={'columns': 4, 'rows': len(rows) + 1}))
    else:
        for i, r in enumerate(rows):
            out.append(_el('comparison_columns' if variant == 'columns' else 'kpi_card', f'{binding}.rows[{i}]',
                           metric_id=r['metric_id'], state=r['current']['state']))
    for i, r in enumerate(rows):  # variação: forma + texto, cor = token da tendência COMPROVADA (ou neutra)
        if variant != 'table':
            out.append(_el('variation_pill', f'{binding}.rows[{i}]', metric_id=r['metric_id'], delta=r['delta'],
                           trend=r.get('trend'), color=r.get('trend_color')))
    return out


def _severity(ir: dict | None, binding: str, layout: str) -> list[dict]:
    if layout == 'severity-cards':
        if not ir or ir.get('available') is False:
            return [_el('unavailable', binding, reason=(ir or {}).get('reason', 'no_data'))]
        return [_el('severity_cards', binding, cards=len(ir['series'][0]['points']),
                    colors=[p.get('color') for p in ir['series'][0]['points']])]
    if layout == 'donut':
        return _chart('donut', 'doughnut', ir, binding)
    return _chart('severity_chart', 'bar', ir, binding)


def _zone(zone: dict, binding: str, slide: dict, theme: dict) -> list[dict]:
    kind, ir = zone['kind'], zone.get('data')
    frames = (theme.get('components', {}).get('zone_frames', {}).get(slide['layout']) or {})
    frame = frames.get(zone['zone']) or ('band' if kind == 'kpi_band' else 'card' if kind in _FRAMED or (
        kind == 'text' and zone.get('text_field') == 'body') else 'plain')
    out = [] if frame == 'plain' else [_el('zone_frame', binding, frame=frame)]
    if zone.get('title'):
        out.append(_el('zone_title', f'{binding}.title'))
    if kind == 'text':
        field = zone.get('text_field') or 'body'
        if (field == 'items' and slide['fields'].get('items')) or (field == 'body' and slide['fields'].get('body')):
            out.append(_el('bullets' if field == 'items' else 'body', f'fields.{field}'))
        return out
    b = f'{binding}.data'
    if kind == 'kpi_band':
        out += _kpis(ir, b)
    elif kind == 'kpi_cards':
        out += _comparison(ir, b, 'cards')
    elif kind == 'severity_cards':
        out += _severity(ir, b, 'severity-cards')
    elif kind == 'donut':
        out += _severity(ir, b, 'donut')
    elif kind == 'comparison':
        variant = 'columns' if theme.get('components', {}).get('zone_comparison') == 'columns' else 'table'
        out += _comparison(ir, b, variant)
    elif kind == 'ranking':
        out += _ranking(ir, b, bars=False)
    elif kind == 'table':
        out += [_el('metric_table', b, table={'rows': len((ir or {}).get('rows', [])) + 1, 'columns': 5})] \
            if ir and ir.get('available') is not False else [_el('unavailable', b)]
    elif kind == 'chart':
        k = (ir or {}).get('kind')
        out += _chart({'combo': 'combo_chart', 'line': 'line_chart'}.get(k, 'bar_chart'),
                      {'combo': 'combo', 'line': 'line'}.get(k, 'bar'), ir, b)
    return out


def _content(slide: dict, theme: dict) -> list[dict]:
    t, lay, d, f = slide['type'], slide['layout'], slide.get('data'), slide['fields']
    out: list[dict] = []
    if t == 'cover':
        out += [_el('cover_text', 'data.owner'), _el('title', 'fields.title')]
        out += [_el('subtitle', 'fields.subtitle')] if f.get('subtitle') else []
        out += [_el('cover_text', 'data.period_label')]
        out += [_el('presenters', 'data.presenters')] if (d or {}).get('presenters') else []
        return out
    if t == 'closing':
        out += [_el('title', 'fields.title')]
        out += [_el('subtitle', 'fields.subtitle')] if f.get('subtitle') else []
        out += [_el('body', 'fields.body')] if f.get('body') else []
        out += [_el('presenters', 'data.presenters')] if (d or {}).get('presenters') else []
        out += [_el('closing_group', f'fields.items[{i}]') for i in range(len(f.get('items') or []))]
        return out
    if t == 'section':
        vertical = theme.get('components', {}).get('section', {}).get('orientation') == 'vertical'
        out += [_el('section_title', 'fields.title', vertical=vertical)]
        return out + ([_el('subtitle', 'fields.subtitle')] if f.get('subtitle') else [])
    out.append(_el('title', 'fields.title'))
    out += [_el('subtitle', 'fields.subtitle')] if f.get('subtitle') else []
    if t == 'dashboard':
        for zid, z in ((d or {}).get('zones') or {}).items():
            out += _zone(z, f'data.zones.{zid}', slide, theme)
    elif t == 'recommendations':
        out += [_el('body', 'fields.body')] if f.get('body') else []
        out += [_el('matrix', 'fields.items', table={'rows': len(f.get('items') or [])})] if lay == 'matrix' else \
            [_el('bullets', 'fields.items')] if f.get('items') else []
    elif t == 'executive_summary':
        out += [_el('body', 'fields.body')] if f.get('body') else []
        out += [_el('bullets', 'fields.items')] if f.get('items') else []
        out += _kpis(d, 'data') if d and lay != 'text-only' else []
    elif t == 'kpis':
        out += _kpis(d, 'data', 'kpi' if lay == 'kpi-band' else 'kpi_card')
    elif t == 'month_comparison':
        out += _comparison(d, 'data', 'cards' if lay == 'comparison-cards' else 'table')
    elif t == 'severity_distribution':
        out += _severity(d, 'data', lay)
    elif t == 'top10_ranking':
        out += _ranking(d, 'data', bars=lay == 'ranking-bars')
    elif t == 'metric_table':
        out += [_el('metric_table', 'data', table={'rows': len((d or {}).get('rows', [])) + 1, 'columns': 5})] \
            if d and d.get('available') is not False else [_el('unavailable', 'data')]
    elif t in ('bar_chart', 'line_chart'):
        kind = (d or {}).get('kind')
        out += _chart('line_chart' if kind == 'line' else 'bar_chart', 'line' if kind == 'line' else 'bar', d, 'data')
    if t not in ('dashboard', 'recommendations') and lay == 'chart-with-text' and f.get('body'):
        out.append(_el('body', 'fields.body'))
    out += [_el('caption', 'fields.caption')] if f.get('caption') else []
    return out


def plan(view: dict) -> dict:
    theme = view['theme']
    comp = theme.get('components', {})
    canvas = theme['canvas']
    brand = view.get('brand_assets') or {}
    slots = {s['name']: s for s in theme.get('asset_slots', [])}
    slides, totals = [], {k: 0 for k in EXPORT_KINDS}
    for s in view['slides']:
        kind = _slide_kind(s['type'])
        els: list[dict] = [_el('background', 'theme.backgrounds')]
        els += [_el('theme_shape', f'theme.components.shapes[{sh["name"]}]', custom_geometry=bool(sh.get('path')),
                    opacity=sh.get('opacity', 1), color=sh['fill'])
                for sh in comp.get('shapes', []) if 'all' in sh['slides'] or kind in sh['slides']]
        fallbacks = []
        for name, slot in slots.items():
            if 'all' not in slot['slides'] and kind not in slot['slides']:
                continue
            if (brand.get(name) or {}).get('status') == 'available':
                els.append(_el('brand_asset', f'brand_assets.{name}', media_type=brand[name]['media_type'],
                               sha256=brand[name]['sha256'], box=slot['box']))
            else:
                fallbacks.append(name)
        els += [_el('theme_image', f'theme.images[{img["name"]}]') for img in theme.get('images', [])
                if 'all' in img['slides'] or kind in img['slides']]
        els += _content(s, theme)
        if kind == 'content':
            els += [_el('underline', 'theme.components.title_underline')] if comp.get('title_underline') else []
            els += [_el('badge', 'view.competence')] if comp.get('badge') else []
        if theme.get('footer', {}).get('show'):
            els += [_el('footer_text', f'theme.footer.{item}') for item in theme['footer'].get('items', [])
                    if item != 'provisional' or theme.get('provisional')]
        counts = {k: sum(1 for e in els if e['export_as'] == k) for k in EXPORT_KINDS}
        for k, n in counts.items():
            totals[k] += n
        slides.append({'index': s['index'], 'slide_id': s['slide_id'], 'type': s['type'], 'layout': s['layout'],
                       'elements': els, 'counts': counts, 'brand_fallbacks': fallbacks,
                       'data_as_image': [e['binding'] for e in els if e['export_as'] == 'image'
                                         and e['component'] not in ('brand_asset', 'theme_image')]})
    fonts = {r: {'html': theme['fonts'][r]['stack'][0], 'export_family': theme['fonts'][r]['export_family']}
             for r in ('heading', 'body', 'numeric')}
    return {'export_plan_version': PLAN_VERSION, 'status': 'IMPLEMENTED',
            'note': 'Contrato do exportador F07 (POST /api/presentations/{id}/exports): cada elemento é exportado '
                    'conforme `export_as`; este endpoint não gera arquivo.',
            'presentation': view['presentation'], 'revision': view['revision'],
            'theme': {'id': theme['id'], 'version': theme['version'], 'definition_hash': theme['definition_hash']},
            'canvas': {'width_px': canvas['width'], 'height_px': canvas['height'],
                       'width_emu': canvas['width'] * EMU_PER_PX, 'height_emu': canvas['height'] * EMU_PER_PX,
                       'emu_per_px': EMU_PER_PX},
            'palette': theme['colors'], 'fonts': fonts, 'slides': slides, 'totals': totals,
            'gap_policy': 'Lacuna/ausente/incompatível => valor None no gráfico nativo (célula vazia, sem '
                          'interpolação) + texto de estado; nunca 0.',
            'limitations': LIMITATIONS, 'matrix': MATRIX}
