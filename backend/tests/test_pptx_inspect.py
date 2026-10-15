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
                               'gap_width': '150'}]
    assert chart['legend_position'] == 'b' and chart['embedded_workbook'] is True and chart['is_3d'] is False
    assert s2['tables'][0]['rows'] == 3 and s2['tables'][0]['columns'] == 3 and s2['tables'][0]['merged_cells'] == 2
    assert s2['tables'][0]['column_widths_px'] == [192.0, 144.0, 144.0]
    assert s2['images'] == [{'external': False, 'target': 'ppt/media/image2.jpeg', 'cropped': True}]
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
