"""F06B.1 — inspeção LOCAL de PPTX de referência, testada só com PPTX SINTÉTICO gerado aqui (nenhum arquivo real).
Garante estrutura do relatório, privacidade (nenhum texto/valor/nome confidencial copiado), limites de segurança do
pacote, rascunho de tema não aprovado e CLI com saída fora do Git.
"""
from __future__ import annotations

import json
import zipfile

import pytest

from app import cli, db
from app.presentations import pptx_inspect, synthetic_pptx, themes
from app.presentations.pptx_inspect import PptxError


@pytest.fixture
def pptx(tmp_path):
    return synthetic_pptx.build(tmp_path / 'referencia-sintetica.pptx')


@pytest.fixture
def report(pptx):
    return pptx_inspect.inspect(pptx)


def test_presentation_dimensions_order_masters_and_layouts(report):
    p = report['presentation']
    assert (p['slides'], p['hidden_slides'], p['masters'], p['layouts']) == (3, 1, 1, 2)
    assert p['size'] == {'emu': [12192000, 6858000], 'inches': [13.333, 7.5], 'px_96dpi': [1280.0, 720.0],
                         'aspect_ratio': '16:9', 'type': None}
    assert (p['embedded_fonts'], p['sections'], p['notes_slides'], p['comment_parts']) == (1, 1, 1, 1)
    assert [s['order'] for s in report['slides']] == [1, 2, 3]
    assert [s['slide_id'] for s in report['slides']] == [256, 257, 258]
    assert [s['layout'] for s in report['slides']] == ['layout-1.1', 'layout-1.2', 'layout-1.2']
    assert [s['hidden'] for s in report['slides']] == [False, False, True]
    m = report['masters'][0]
    assert [ph['type'] for ph in m['placeholders']] == ['title', 'body', 'dt', 'ftr', 'sldNum']
    assert m['text_styles']['titleStyle'] == {'size_pt': 40.0, 'bold': True, 'font': 'Fonte Titulo Sintetica'}
    assert {(lay['type'], tuple(lay['used_by_slides'])) for lay in report['layouts']} == {('title', (1,)), ('obj', (2, 3))}


def test_theme_colors_fonts_shapes_charts_tables_and_images(report):
    assert report['theme']['colors']['dk1'] == '#000000'  # sysClr => lastClr
    assert report['theme']['colors']['accent1'] == '#125E68'
    assert report['theme']['fonts'] == {'major': 'Fonte Titulo Sintetica', 'minor': 'Fonte Corpo Sintetica'}
    assert {'color': '#125E68', 'count': 6} in report['colors']['srgb_used'] or \
        any(c['color'] == '#125E68' for c in report['colors']['srgb_used'])
    used = {f['font']: f for f in report['fonts']['used']}
    assert used['Fonte Titulo Sintetica']['web_safe'] is False  # +mj-lt resolvida pelo esquema do tema
    s2 = report['slides'][1]
    chart = s2['charts'][0]
    assert chart['kinds'] == [{'type': 'barChart', 'bar_direction': 'col', 'grouping': 'clustered', 'series': 2,
                               'points_per_series': [4, 4], 'number_formats': ['#,##0'], 'data_labels': True,
                               'gap_width': '150', 'series_colors': ['#125E68', '#86449F'], 'point_colors': None,
                               'hole_size': None, 'markers': None, 'show_percent': False}]
    assert chart['legend_position'] == 'b' and chart['embedded_workbook'] is True and chart['is_3d'] is False
    assert s2['tables'][0]['rows'] == 3 and s2['tables'][0]['columns'] == 3 and s2['tables'][0]['merged_cells'] == 2
    assert s2['tables'][0]['column_widths_px'] == [192.0, 144.0, 144.0]
    assert s2['images'] == [{'external': False, 'target': 'ppt/media/image2.jpeg', 'cropped': True,
                                                    'vector': False}]
    title = s2['shapes'][0]
    assert title['placeholder']['type'] == 'title' and title['box_inherited'] is True  # posição herdada do master
    assert title['box_px'] == {'x': 48.0, 'y': 38.4, 'w': 1183.68, 'h': 96.0}
    group_children = [s for s in s2['shapes'] if s.get('depth') == 1]
    assert [c['box_px'] for c in group_children] == [{'x': 96.0, 'y': 576.0, 'w': 96.0, 'h': 48.0},
                                                     {'x': 192.0, 'y': 576.0, 'w': 96.0, 'h': 48.0}]
    body = s2['shapes'][1]['text']
    assert body['paragraphs'] == 3 and body['bullets'] == 2 and body['fields'] == ['slidenum'] and body['hyperlinks'] == 1
    media = {m['format']: m for m in report['media']}
    assert media['png']['pixels'] == [120, 40] and media['jpeg']['pixels'] == [64, 32] and media['emf']['pixels'] is None


def test_reusable_and_not_directly_reproducible_elements(report):
    reuse = report['reusable']
    statics = reuse['master_static_elements']
    assert {(e['kind'], e['image']) for e in statics} == {('shape', False), ('picture', True)}
    assert any('master-1' in r['used_by'] for r in reuse['repeated_images'])
    assert reuse['placeholder_types'] == {'ctrTitle': 1, 'subTitle': 1, 'title': 1, 'body': 1}
    nr = {x['code']: x for x in report['not_directly_reproducible']}
    expected = {'smartart': [2], 'ole_object': [3], 'video_or_audio': [3], 'animation': [2], 'transition': [1],
                'image_emf': [3], 'wordart_warp': [3], 'custom_geometry': [2], 'effect': [2], 'gradient_fill': [3],
                'hidden_slide': [3], 'chart_embedded_workbook': [2]}
    for code, slides in expected.items():
        assert nr[code]['slides'] == slides, code
    assert nr['embedded_fonts']['occurrences'] == 1
    assert nr['smartart']['class'] == 'not_reproducible' and nr['effect']['class'] == 'approximate'
    assert report['not_directly_reproducible'][0]['class'] == 'not_reproducible'  # mais graves primeiro


@pytest.mark.parametrize('privacy', ['strict', 'structural'])
def test_no_confidential_text_values_comments_or_links_leave_the_file(pptx, privacy):
    r = pptx_inspect.inspect(pptx, privacy=privacy)
    blob = json.dumps(r, ensure_ascii=False) + pptx_inspect.render_markdown(r) + \
        json.dumps(pptx_inspect.theme_draft(r), ensure_ascii=False)
    for sentinel in synthetic_pptx.SENTINELS:
        assert sentinel not in blob, sentinel
    names_present = [n for n in synthetic_pptx.NAMES if n in blob]
    if privacy == 'strict':
        assert names_present == [] and r['source']['file_name'] is None
        assert all(m['part'].startswith('media-') for m in r['media'])
    else:
        assert 'Capa Confidencial XYZ' in names_present and r['source']['file_name'] == 'referencia-sintetica.pptx'


def test_package_safety_limits(tmp_path, monkeypatch):
    not_zip = tmp_path / 'falso.pptx'
    not_zip.write_bytes(b'nao sou zip')
    with pytest.raises(PptxError, match='não é um pacote OOXML'):
        pptx_inspect.inspect(not_zip)
    docx_like = tmp_path / 'outro.pptx'
    with zipfile.ZipFile(docx_like, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types/>')
        z.writestr('word/document.xml', '<doc/>')
    with pytest.raises(PptxError, match='não é PPTX'):
        pptx_inspect.inspect(docx_like)
    # parte com DOCTYPE/entidade é recusada sem derrubar a inspeção
    src = synthetic_pptx.build(tmp_path / 'base.pptx')
    evil = tmp_path / 'entidade.pptx'
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(evil, 'w') as zout:
        for item in zin.infolist():
            data = zin.read(item)
            if item.filename == 'ppt/slides/slide3.xml':
                data = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]>' + data.split(b'?>', 1)[1]
            zout.writestr(item, data)
    r = pptx_inspect.inspect(evil)
    assert any('DOCTYPE' in p for p in r['problems']) and r['presentation']['slides'] == 3
    monkeypatch.setattr(pptx_inspect, 'MAX_ENTRIES', 5)
    with pytest.raises(PptxError, match='entradas demais'):
        pptx_inspect.inspect(src)


def test_theme_draft_is_valid_provisional_and_flags_review(report):
    d = pptx_inspect.theme_draft(report)
    assert d['validation_errors'] == []
    draft = themes.ThemeDefinition.model_validate(d['draft'])
    assert draft.provisional is True and 'NÃO aprovado' in draft.notice
    assert (draft.canvas.width, draft.canvas.height) == (1280, 720)
    assert draft.colors['accent'] == '#125E68' and draft.colors['text.primary'] == '#000000'
    assert draft.fonts.heading.stack[0] == 'Fonte Titulo Sintetica'
    assert draft.layout.mode == 'fixed' and draft.layout.header.y == 38.4  # placeholder de título do master
    assert 'severity.HIGH' in d['needs_review'] and d['mapped_colors']['series.2'] == 'accent2'


def test_cli_writes_reports_outside_versioned_area(pptx, tmp_path, capsys):
    out = tmp_path / 'relatorio'
    assert cli.main(['inspect-pptx', str(pptx), '--out', str(out), '--theme-draft']) == 0
    assert {p.name for p in out.iterdir()} == {'report.json', 'report.md', 'theme-draft.json'}
    printed = capsys.readouterr().out
    assert '3 slides' in printed and '16:9' in printed
    assert not any(s in printed for s in synthetic_pptx.SENTINELS + synthetic_pptx.NAMES)
    with pytest.raises(SystemExit, match='versionável'):
        cli.main(['inspect-pptx', str(pptx), '--out', str(db.REPO_ROOT / 'docs' / 'nao-aqui')])
    assert cli.safe_output_dir(str(db.REPO_ROOT / 'output' / 'x'), 'a' * 64) == db.REPO_ROOT / 'output' / 'x'
    bad = tmp_path / 'ruim.pptx'
    bad.write_bytes(b'x')
    assert cli.main(['inspect-pptx', str(bad), '--out', str(out)]) == 1
    gen = tmp_path / 'gerado.pptx'
    assert cli.main(['synthetic-pptx', str(gen)]) == 0 and zipfile.is_zipfile(gen)


def test_gitignore_keeps_reference_files_and_reports_out_of_git():
    ignored = (db.REPO_ROOT / '.gitignore').read_text(encoding='utf-8').splitlines()
    for pattern in ('*.pptx', '*.pdf', 'output/', 'private/', 'data/'):
        assert pattern in ignored, pattern


def test_design_attributes_colors_and_text_style_without_text(report):
    resolver = pptx_inspect.ColorResolver({'lt1': '#FFFFFF', 'accent1': '#5C2483'}, {'bg1': 'lt1'})
    import xml.etree.ElementTree as ET
    def el(xml):
        return ET.fromstring(f'<a:x xmlns:a="{pptx_inspect.NS["a"]}">{xml}</a:x>')[0]
    assert resolver.resolve(el('<a:schemeClr val="bg1"/>')) == '#FFFFFF'  # clrMap: bg1 -> lt1
    darker = resolver.resolve(el('<a:schemeClr val="accent1"><a:lumMod val="50000"/></a:schemeClr>'))
    assert darker != '#5C2483' and int(darker[1:3], 16) < 0x5C
    assert resolver.resolve(el('<a:srgbClr val="000000"><a:tint val="50000"/></a:srgbClr>')) == '#808080'
    s2 = report['slides'][1]
    body = s2['shapes'][1]['text']['style']
    assert body['colors'] == ['#1F2A44'] and body['bold_share'] > 0
    band = next(e for e in report['masters'][0]['static_shapes'] if e['kind'] == 'shape')
    assert band['fill_color'] == '#125E68'
    logo = next(e for e in report['masters'][0]['static_shapes'] if e['kind'] == 'picture')
    assert logo['media_ref'] == 'media-1'  # referência anônima, sem nome de arquivo
    grad = next(x for x in report['slides'][2]['shapes'] if x.get('fill') == 'gradient')
    assert [st['color'] for st in grad['fill_gradient']['stops']] == ['#125E68', '#86449F']
    table = s2['tables'][0]
    assert table['header_fill'] == '#E6F0F1' and table['text_style']['sizes_pt'] == []
    assert report['masters'][0]['background_detail'] == {'type': 'solid', 'color': '#FFFFFF'}



def test_custom_geometry_outline_and_fill_opacity_are_structural():
    """F06B: contorno de geometria personalizada (path SVG relativo à caixa) e opacidade do preenchimento."""
    import xml.etree.ElementTree as ET
    a = pptx_inspect.NS['a']
    cust = ET.fromstring(
        f'<a:custGeom xmlns:a="{a}"><a:pathLst><a:path w="1000" h="500">'
        '<a:moveTo><a:pt x="0" y="0"/></a:moveTo><a:lnTo><a:pt x="1000" y="0"/></a:lnTo>'
        '<a:cubicBezTo><a:pt x="1000" y="250"/><a:pt x="800" y="500"/><a:pt x="500" y="500"/></a:cubicBezTo>'
        '<a:quadBezTo><a:pt x="250" y="500"/><a:pt x="0" y="250"/></a:quadBezTo><a:close/>'
        '</a:path></a:pathLst></a:custGeom>')
    d = pptx_inspect._cust_path(cust, {'x': 10, 'y': 20, 'w': 200, 'h': 100})
    assert d == 'M0.0 0.0L200.0 0.0C200.0 50.0 160.0 100.0 100.0 100.0Q50.0 100.0 0.0 50.0Z'
    # coordenadas por guia (fórmula) não são reproduzidas: None em vez de um contorno errado
    guided = ET.fromstring(f'<a:custGeom xmlns:a="{a}"><a:pathLst><a:path w="10" h="10">'
                           '<a:moveTo><a:pt x="g1" y="0"/></a:moveTo></a:path></a:pathLst></a:custGeom>')
    assert pptx_inspect._cust_path(guided, {'x': 0, 'y': 0, 'w': 10, 'h': 10}) is None
    arc = ET.fromstring(f'<a:custGeom xmlns:a="{a}"><a:pathLst><a:path w="100" h="100">'
                        '<a:moveTo><a:pt x="100" y="50"/></a:moveTo>'
                        '<a:arcTo wR="50" hR="50" stAng="0" swAng="10800000"/></a:path></a:pathLst></a:custGeom>')
    assert pptx_inspect._cust_path(arc, {'x': 0, 'y': 0, 'w': 100, 'h': 100}) == 'M100.0 50.0A50.0 50.0 0 0 1 0.0 50.0'
    fill = ET.fromstring(f'<a:solidFill xmlns:a="{a}"><a:srgbClr val="FFFFFF"><a:alpha val="95000"/></a:srgbClr>'
                         '</a:solidFill>')
    assert pptx_inspect.ColorResolver.alpha(fill) == 95.0
    opaque = ET.fromstring(f'<a:solidFill xmlns:a="{a}"><a:srgbClr val="FFFFFF"/></a:solidFill>')
    assert pptx_inspect.ColorResolver.alpha(opaque) is None
    assert 'opacity:0.95;' in pptx_inspect._css_fill({'fill_color': '#FFFFFF', 'fill_alpha': 95.0})
