"""Validação do PPTX exportado (F07) — antes de declarar sucesso. Nada é "aprovado" só porque o arquivo abre.

Pacote: ZIP íntegro, partes obrigatórias, todo XML bem formado (parser sem rede/entidades), sem macros/ActiveX/OLE,
nenhuma relação externa, tipos de conteúdo coerentes.
Conteúdo (reabrindo com python-pptx): nº/ordem de slides = documento; tamanho = canvas do tema; para cada objeto do
manifesto do construtor, o objeto existe com o MESMO tipo (texto/forma/linha/tabela/gráfico/imagem); textos e células
iguais ao layout; imagens só de ativos autorizados; gráficos com os valores APROVADOS exatos (cache do gráfico E
planilha incorporada), lacunas vazias; contagem de gráficos/tabelas igual ao plano de exportação (F06C).
"""
from __future__ import annotations

import io
import re
import zipfile

from lxml import etree
from pptx import Presentation
from pptx.oxml.ns import qn
from pptx.util import Emu

from app.export import pptx_charts
from app.export.errors import ExportError
from app.export.pptx_builder import resolve_ir
from app.export.pptx_xml import EMU_PER_PX

_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
_FORBIDDEN_PARTS = re.compile(r'(vbaProject|activeX|oleObject|embeddings/.*\.(bin|docm|xlsm))', re.I)


def _fail(problems: list[str]) -> None:
    if problems:
        raise ExportError('pptx_invalid', 'PPTX gerado não passou na validação', status=500,
                          details=[{'field': 'pptx', 'message': p, 'type': 'pptx_invalid'} for p in problems[:100]])


def package(data: bytes) -> dict:
    problems: list[str] = []
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        _fail(['não é um ZIP/OPC válido'])
    bad = z.testzip()
    if bad:
        problems.append(f'entrada ZIP corrompida: {bad}')
    names = z.namelist()
    for required in ('[Content_Types].xml', '_rels/.rels', 'ppt/presentation.xml'):
        if required not in names:
            problems.append(f'parte obrigatória ausente: {required}')
    for n in names:
        if _FORBIDDEN_PARTS.search(n):
            problems.append(f'parte não permitida (macro/ActiveX/OLE): {n}')
        if n.endswith(('.xml', '.rels')):
            try:
                root = etree.fromstring(z.read(n), _PARSER)
            except etree.XMLSyntaxError as exc:
                problems.append(f'XML malformado em {n}: {str(exc)[:80]}')
                continue
            if n.endswith('.rels'):
                for rel in root:
                    if rel.get('TargetMode') == 'External':
                        problems.append(f'relação externa não permitida em {n}')
    ct = z.read('[Content_Types].xml').decode('utf-8', errors='replace') if '[Content_Types].xml' in names else ''
    if 'macroEnabled' in ct or 'vbaProject' in ct:
        problems.append('tipo de conteúdo com macros')
    _fail(problems)
    return {'parts': len(names), 'macros': False, 'external_relationships': False,
            'embedded_workbooks': sum(1 for n in names if n.startswith('ppt/embeddings/') and n.endswith('.xlsx')),
            'embedded_fonts': sum(1 for n in names if n.startswith('ppt/fonts/'))}


def _workbook_values(blob: bytes) -> list[list[float | None]]:
    """Valores numéricos por coluna (séries) da 1ª planilha de um XLSX incorporado (linha 1 = cabeçalho)."""
    z = zipfile.ZipFile(io.BytesIO(blob))
    sheet = etree.fromstring(z.read('xl/worksheets/sheet1.xml'), _PARSER)
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    cols: dict[int, dict[int, float | None]] = {}
    max_row = 1
    for c in sheet.iterfind('.//s:c', ns):
        ref = c.get('r')
        m = re.match(r'([A-Z]+)(\d+)', ref)
        col = sum((ord(ch) - 64) * 26 ** i for i, ch in enumerate(reversed(m.group(1))))
        row = int(m.group(2))
        max_row = max(max_row, row)
        v = c.find('s:v', ns)
        if row > 1 and col > 1 and c.get('t') not in ('s', 'str', 'inlineStr'):
            cols.setdefault(col, {})[row] = float(v.text) if v is not None and v.text is not None else None
    return [[vals.get(r) for r in range(2, max_row + 1)] for _, vals in sorted(cols.items())]


def content(data: bytes, view: dict, manifest: list[list[dict]], plan: dict) -> dict:
    problems: list[str] = []
    prs = Presentation(io.BytesIO(data))
    canvas = view['theme']['canvas']
    if (prs.slide_width, prs.slide_height) != (Emu(canvas['width'] * EMU_PER_PX), Emu(canvas['height'] * EMU_PER_PX)):
        problems.append('tamanho do slide diferente do canvas do tema')
    slides = list(prs.slides)
    if len(slides) != len(view['slides']):
        _fail([f'{len(slides)} slides no PPTX para {len(view["slides"])} no documento'])
    z = zipfile.ZipFile(io.BytesIO(data))
    counts = {'text': 0, 'shape': 0, 'line': 0, 'table': 0, 'chart': 0, 'picture': 0}
    chart_points = gaps_empty = 0
    for i, (slide, items, vs) in enumerate(zip(slides, manifest, view['slides']), start=1):
        by_name: dict[str, object] = {}
        for sh in slide.shapes:
            by_name.setdefault(sh.name, sh)
        pictures = [sh for sh in slide.shapes if sh.shape_type == 13]
        allowed = {it['key'] for it in items if it['kind'] == 'picture'}
        for pic in pictures:
            if pic.name not in allowed or not pic.name.startswith(('brand:', 'image:')):
                problems.append(f'slide {i}: imagem não autorizada ({pic.name}) — dado nunca vira imagem')
        for it in items:
            sh = by_name.get(it['key'])
            if sh is None:
                problems.append(f'slide {i}: objeto ausente {it["key"]}')
                continue
            kind = it['kind']
            counts[kind] += 1
            if kind == 'text':
                if not sh.has_text_frame:
                    problems.append(f'slide {i}: {it["key"]} não é caixa de texto editável')
                elif sh.text_frame.text.replace('\v', '\n').replace('\n', '') != it['text'].replace('\n', ''):
                    problems.append(f'slide {i}: texto divergente em {it["key"]}')
            elif kind == 'table':
                if not sh.has_table:
                    problems.append(f'slide {i}: {it["key"]} não é tabela nativa')
                    continue
                tbl = sh.table
                got = [[tbl.cell(r, c).text_frame.text.replace('\n', '') for c in range(len(row))]
                       for r, row in enumerate(it['cells'])]
                if got != [[c.replace('\n', '') for c in row] for row in it['cells']]:
                    problems.append(f'slide {i}: células divergentes em {it["key"]}')
            elif kind == 'chart':
                if not getattr(sh, 'has_chart', False):
                    problems.append(f'slide {i}: {it["key"]} não é gráfico nativo')
                    continue
                ir = resolve_ir(vs, it['ir'])
                expected = [pptx_charts.values_of(s) for s in ir['series']]
                cached = pptx_charts.chart_values(sh)
                if cached != expected:
                    problems.append(f'slide {i}: valores do gráfico {it["key"]} diferentes dos aprovados')
                wb = sh.chart.part.chart_workbook.xlsx_part
                if wb is None:
                    problems.append(f'slide {i}: gráfico {it["key"]} sem planilha incorporada')
                elif _workbook_values(wb.blob) != expected:
                    problems.append(f'slide {i}: planilha incorporada de {it["key"]} diferente dos valores aprovados')
                chart_points += sum(len(s) for s in expected)
                gaps_empty += sum(1 for s in expected for v in s if v is None)
            elif kind == 'picture' and sh.shape_type != 13:
                problems.append(f'slide {i}: {it["key"]} deveria ser imagem de ativo autorizado')
    planned = {'native_chart': 0, 'table': 0}
    for s in plan['slides']:
        for e in s['elements']:
            if e['export_as'] in planned:
                planned[e['export_as']] += 1
    if counts['chart'] != planned['native_chart']:
        problems.append(f'{counts["chart"]} gráficos nativos no PPTX; o plano de exportação prevê '
                        f'{planned["native_chart"]}')
    if counts['table'] != planned['table']:
        problems.append(f'{counts["table"]} tabelas no PPTX; o plano de exportação prevê {planned["table"]}')
    for name in z.namelist():  # textos nunca como imagem: nenhuma mídia além dos ativos autorizados
        if name.startswith('ppt/media/') and not any(it['kind'] == 'picture' for items in manifest for it in items):
            problems.append(f'mídia inesperada no pacote: {name}')
    _fail(problems)
    editable = sum(v for k, v in counts.items() if k != 'picture')
    return {'slides': len(slides), 'objects': counts, 'editable_objects': editable, 'images': counts['picture'],
            'chart_points': chart_points, 'chart_gaps_empty': gaps_empty, 'plan_match': True}


def pptx(data: bytes, view: dict, manifest: list[list[dict]], plan: dict) -> dict:
    return {'package': package(data), 'content': content(data, view, manifest, plan)}


__all__ = ['pptx', 'package', 'content', 'qn']
