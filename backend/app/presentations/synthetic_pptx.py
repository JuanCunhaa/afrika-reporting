"""PPTX SINTÉTICO para testar a inspeção local (F06B.1) sem nenhum arquivo real de cliente.

Gera, só com a biblioteca padrão, um pacote OOXML com: 1 master (placeholders, logotipo e faixa estáticos, estilos de
texto), 2 layouts, tema (esquema de cores com sysClr/srgbClr e esquema de fontes), 3 slides (um oculto), gráfico de
barras com planilha incorporada, tabela com célula mesclada, imagem recortada, grupo com escala, SmartArt, OLE, vídeo
vinculado, imagem EMF, WordArt, gradiente, efeitos, geometria livre, animação, transição, nota, comentário, vínculo
externo e fonte incorporada. Textos, rótulos e valores contêm SENTINELAS (`SENTINELS`) que a inspeção NUNCA pode
copiar para o relatório. Nada aqui representa marca ou dado real.
"""
from __future__ import annotations

import struct
import zipfile
import zlib
from pathlib import Path

SENTINELS = ('SEGREDO-TITULO-XYZ', 'Receita 1234567', 'CelulaSecreta', 'CategoriaSecreta', '98765.4321',
             'NotaSecreta', 'ComentarioSecreto', 'confidencial.invalid', 'TextoCorpoSecreto')
NAMES = ('Capa Confidencial XYZ', 'Tema Cliente Confidencial', 'Seção Sintética Confidencial', 'Logo Cliente XYZ')

A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
C = 'http://schemas.openxmlformats.org/drawingml/2006/chart'
NSDECL = f'xmlns:a="{A}" xmlns:p="{P}" xmlns:r="{R}"'
RT = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
CT_P = 'application/vnd.openxmlformats-officedocument.presentationml'


def _png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)
    raw = b''.join(b'\x00' + bytes((18, 94, 104)) * width for _ in range(height))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def _jpeg_header(width: int, height: int) -> bytes:
    # cabeçalho mínimo (SOI + SOF0 + EOI): suficiente para a leitura de dimensões; não é uma foto real
    sof = b'\xff\xc0' + struct.pack('>HBHHB', 11, 8, height, width, 1) + b'\x01\x11\x00'
    return b'\xff\xd8' + sof + b'\xff\xd9'


def _rels(items: list[tuple[str, str, str, bool]]) -> str:
    rows = ''.join(f'<Relationship Id="{i}" Type="{RT}/{t}" Target="{tg}"'
                   + (' TargetMode="External"' if ext else '') + '/>' for i, t, tg, ext in items)
    return f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rows}</Relationships>'


def _xfrm(x: int, y: int, cx: int, cy: int, tag: str = 'a:xfrm', extra: str = '') -> str:
    return f'<{tag}{extra}><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></{tag}>'


def _sp(n: int, name: str, *, ph: str = '', xfrm: str = '', geom: str = '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>',
        fill: str = '', text: str = '', extra_sppr: str = '', body_pr: str = '<a:bodyPr/>', txbox: bool = False) -> str:
    tx = f'<p:txBody>{body_pr}<a:lstStyle/>{text}</p:txBody>' if text else ''
    txb = ' txBox="1"' if txbox else ''
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{n}" name="{name}"/><p:cNvSpPr{txb}/>'
            f'<p:nvPr>{ph}</p:nvPr></p:nvSpPr><p:spPr>{xfrm}{geom}{fill}{extra_sppr}</p:spPr>{tx}</p:sp>')


def _p(text: str, *, sz: int | None = None, bold: bool = False, font: str | None = None, bullet: bool = False,
       algn: str | None = None, color: str | None = None, link: str | None = None) -> str:
    rpr = ''.join([f' sz="{sz}"' if sz else '', ' b="1"' if bold else ''])
    inner = ''.join([f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill>' if color else '',
                     f'<a:latin typeface="{font}"/>' if font else '',
                     f'<a:hlinkClick r:id="{link}"/>' if link else ''])
    ppr = ''.join([f' algn="{algn}"' if algn else ''])
    bu = '<a:buChar char="•"/>' if bullet else ''
    return f'<a:p><a:pPr{ppr}>{bu}</a:pPr><a:r><a:rPr lang="pt-BR"{rpr}>{inner}</a:rPr><a:t>{text}</a:t></a:r></a:p>'


def _ph(kind: str, idx: str | None = None) -> str:
    return f'<p:ph type="{kind}"' + (f' idx="{idx}"' if idx else '') + '/>'


def _slide(tree: str, *, extra: str = '', show: bool = True, bg: str = '') -> str:
    hidden = '' if show else ' show="0"'
    return (f'<?xml version="1.0" encoding="UTF-8"?><p:sld {NSDECL}'
            f' xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
            f' xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main"{hidden}>'
            f'<p:cSld>{bg}<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            f'<p:grpSpPr/>{tree}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>{extra}</p:sld>')


def build(path: str | Path) -> Path:
    path = Path(path)
    E = 914400  # 1 polegada em EMU
    parts: dict[str, bytes | str] = {}
    overrides = {
        '/ppt/presentation.xml': f'{CT_P}.presentation.main+xml',
        '/ppt/slideMasters/slideMaster1.xml': f'{CT_P}.slideMaster+xml',
        '/ppt/slideLayouts/slideLayout1.xml': f'{CT_P}.slideLayout+xml',
        '/ppt/slideLayouts/slideLayout2.xml': f'{CT_P}.slideLayout+xml',
        '/ppt/theme/theme1.xml': 'application/vnd.openxmlformats-officedocument.theme+xml',
        '/ppt/charts/chart1.xml': 'application/vnd.openxmlformats-officedocument.drawingml.chart+xml',
        '/ppt/notesSlides/notesSlide1.xml': f'{CT_P}.notesSlide+xml',
        '/ppt/comments/comment1.xml': f'{CT_P}.comments+xml',
        **{f'/ppt/slides/slide{i}.xml': f'{CT_P}.slide+xml' for i in (1, 2, 3)},
    }
    defaults = {'rels': 'application/vnd.openxmlformats-package.relationships+xml', 'xml': 'application/xml',
                'png': 'image/png', 'jpeg': 'image/jpeg', 'emf': 'image/x-emf', 'xlsx':
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'fntdata': 'application/x-fontdata'}
    parts['[Content_Types].xml'] = (
        '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        + ''.join(f'<Default Extension="{e}" ContentType="{t}"/>' for e, t in defaults.items())
        + ''.join(f'<Override PartName="{n}" ContentType="{t}"/>' for n, t in overrides.items()) + '</Types>')
    parts['_rels/.rels'] = _rels([('rId1', 'officeDocument', 'ppt/presentation.xml', False)])
    parts['ppt/presentation.xml'] = (
        f'<?xml version="1.0" encoding="UTF-8"?><p:presentation {NSDECL}'
        ' xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main">'
        '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
        '<p:sldIdLst><p:sldId id="256" r:id="rId2"/><p:sldId id="257" r:id="rId3"/><p:sldId id="258" r:id="rId4"/></p:sldIdLst>'
        '<p:sldSz cx="12192000" cy="6858000"/><p:notesSz cx="6858000" cy="9144000"/>'
        '<p:embeddedFontLst><p:embeddedFont><p:font typeface="Fonte Corpo Sintetica"/><p:regular r:id="rId6"/></p:embeddedFont></p:embeddedFontLst>'
        f'<p:extLst><p:ext uri="{{521415D9-36F7-43E2-AB2F-B90AF26B5E84}}"><p14:sectionLst><p14:section name="{NAMES[2]}" id="{{00000000-0000-0000-0000-000000000001}}">'
        '<p14:sldIdLst><p14:sldId id="256"/></p14:sldIdLst></p14:section></p14:sectionLst></p:ext></p:extLst></p:presentation>')
    parts['ppt/_rels/presentation.xml.rels'] = _rels([
        ('rId1', 'slideMaster', 'slideMasters/slideMaster1.xml', False), ('rId2', 'slide', 'slides/slide1.xml', False),
        ('rId3', 'slide', 'slides/slide2.xml', False), ('rId4', 'slide', 'slides/slide3.xml', False),
        ('rId5', 'theme', 'theme/theme1.xml', False), ('rId6', 'font', 'fonts/font1.fntdata', False)])
    scheme = {'dk2': '1F2A44', 'lt2': 'E7E6E6', 'accent1': '125E68', 'accent2': '86449F', 'accent3': 'C27C0E',
              'accent4': '3F7D3A', 'accent5': '5B9BD5', 'accent6': '70AD47', 'hlink': '0563C1', 'folHlink': '954F72'}
    parts['ppt/theme/theme1.xml'] = (
        f'<?xml version="1.0" encoding="UTF-8"?><a:theme xmlns:a="{A}" name="{NAMES[1]}"><a:themeElements>'
        '<a:clrScheme name="Sintetico"><a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>'
        '<a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>'
        + ''.join(f'<a:{k}><a:srgbClr val="{v}"/></a:{k}>' for k, v in scheme.items()) + '</a:clrScheme>'
        '<a:fontScheme name="Sintetico"><a:majorFont><a:latin typeface="Fonte Titulo Sintetica"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>'
        '<a:minorFont><a:latin typeface="Fonte Corpo Sintetica"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme>'
        '<a:fmtScheme name="Sintetico"><a:fillStyleLst/><a:lnStyleLst/><a:effectStyleLst/><a:bgFillStyleLst/></a:fmtScheme>'
        '</a:themeElements></a:theme>')
    # master: placeholders + logotipo e faixa estáticos + estilos de texto
    master_tree = (
        _sp(2, 'Title Placeholder 1', ph=_ph('title'), xfrm=_xfrm(int(0.5 * E), int(0.4 * E), int(12.33 * E), int(1.0 * E)))
        + _sp(3, 'Text Placeholder 2', ph=_ph('body', '1'), xfrm=_xfrm(int(0.5 * E), int(1.6 * E), int(12.33 * E), int(4.6 * E)))
        + _sp(4, 'Date Placeholder 3', ph=_ph('dt', '10'), xfrm=_xfrm(int(0.5 * E), int(6.95 * E), int(3 * E), int(0.4 * E)))
        + _sp(5, 'Footer Placeholder 4', ph=_ph('ftr', '11'), xfrm=_xfrm(int(4.2 * E), int(6.95 * E), int(5 * E), int(0.4 * E)))
        + _sp(6, 'Slide Number Placeholder 5', ph=_ph('sldNum', '12'), xfrm=_xfrm(int(10.3 * E), int(6.95 * E), int(2.5 * E), int(0.4 * E)))
        + _sp(7, 'Faixa', xfrm=_xfrm(0, 0, 12192000, int(0.15 * E)), fill='<a:solidFill><a:srgbClr val="125E68"/></a:solidFill>')
        + f'<p:pic><p:nvPicPr><p:cNvPr id="8" name="{NAMES[3]}" descr="logotipo"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>'
        f'<p:blipFill><a:blip r:embed="rId4"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
        f'<p:spPr>{_xfrm(int(11.6 * E), int(0.25 * E), int(1.2 * E), int(0.4 * E))}<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>')
    parts['ppt/slideMasters/slideMaster1.xml'] = (
        f'<?xml version="1.0" encoding="UTF-8"?><p:sldMaster {NSDECL}><p:cSld name="Master Sintetico">'
        '<p:bg><p:bgPr><a:solidFill><a:schemeClr val="bg1"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>'
        f'<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>{master_tree}</p:spTree></p:cSld>'
        '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" '
        'accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
        '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/><p:sldLayoutId id="2147483650" r:id="rId2"/></p:sldLayoutIdLst>'
        '<p:txStyles><p:titleStyle><a:lvl1pPr><a:defRPr sz="4000" b="1"><a:latin typeface="+mj-lt"/></a:defRPr></a:lvl1pPr></p:titleStyle>'
        '<p:bodyStyle><a:lvl1pPr><a:defRPr sz="2000"><a:latin typeface="+mn-lt"/></a:defRPr></a:lvl1pPr></p:bodyStyle>'
        '<p:otherStyle><a:lvl1pPr><a:defRPr sz="1800"/></a:lvl1pPr></p:otherStyle></p:txStyles></p:sldMaster>')
    parts['ppt/slideMasters/_rels/slideMaster1.xml.rels'] = _rels([
        ('rId1', 'slideLayout', '../slideLayouts/slideLayout1.xml', False),
        ('rId2', 'slideLayout', '../slideLayouts/slideLayout2.xml', False),
        ('rId3', 'theme', '../theme/theme1.xml', False), ('rId4', 'image', '../media/image1.png', False)])
    lay1 = (_sp(2, 'Title 1', ph=_ph('ctrTitle'), xfrm=_xfrm(int(1.5 * E), int(2.2 * E), int(10.3 * E), int(1.5 * E)))
            + _sp(3, 'Subtitle 2', ph=_ph('subTitle', '1'), xfrm=_xfrm(int(1.5 * E), int(3.8 * E), int(10.3 * E), int(1 * E))))
    lay2 = (_sp(2, 'Title 1', ph=_ph('title'))
            + _sp(3, 'Content Placeholder 2', ph=_ph('body', '1'), xfrm=_xfrm(int(0.5 * E), int(1.6 * E), int(12.33 * E), int(4.6 * E))))
    for i, (name, kind, tree) in enumerate(((NAMES[0], 'title', lay1), ('Conteudo', 'obj', lay2)), start=1):
        parts[f'ppt/slideLayouts/slideLayout{i}.xml'] = (
            f'<?xml version="1.0" encoding="UTF-8"?><p:sldLayout {NSDECL} type="{kind}" preserve="1"><p:cSld name="{name}">'
            f'<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>{tree}</p:spTree>'
            '</p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>')
        parts[f'ppt/slideLayouts/_rels/slideLayout{i}.xml.rels'] = _rels(
            [('rId1', 'slideMaster', '../slideMasters/slideMaster1.xml', False)])
    # slide 1: capa (texto sentinela; transição)
    parts['ppt/slides/slide1.xml'] = _slide(
        _sp(2, 'Title 1', ph=_ph('ctrTitle'), text=_p(f'{SENTINELS[0]} Relatório', sz=4400))
        + _sp(3, 'Subtitle 2', ph=_ph('subTitle', '1'), text=_p(SENTINELS[1], font='+mn-lt')),
        extra='<p:transition spd="med"><p:fade/></p:transition>')
    parts['ppt/slides/_rels/slide1.xml.rels'] = _rels([('rId1', 'slideLayout', '../slideLayouts/slideLayout1.xml', False)])
    # slide 2: conteúdo rico
    merge = {(0, 0): ' gridSpan="2"', (0, 1): ' hMerge="1"'}
    table_rows = ''.join(
        '<a:tr h="370840">' + ''.join(
            f'<a:tc{merge.get((r, c), "")}>'
            f'<a:txBody><a:bodyPr/><a:lstStyle/>{_p(f"{SENTINELS[2]} {r}{c} 4242")}</a:txBody>'
            '<a:tcPr><a:solidFill><a:srgbClr val="E6F0F1"/></a:solidFill></a:tcPr></a:tc>' for c in range(3)) + '</a:tr>'
        for r in range(3))
    group = ('<p:grpSp><p:nvGrpSpPr><p:cNvPr id="20" name="Grupo"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
             '<p:grpSpPr><a:xfrm><a:off x="914400" y="5486400"/><a:ext cx="1828800" cy="457200"/>'
             '<a:chOff x="0" y="0"/><a:chExt cx="914400" cy="228600"/></a:xfrm></p:grpSpPr>'
             + _sp(21, 'Livre', xfrm=_xfrm(0, 0, 457200, 228600),
                   geom='<a:custGeom><a:pathLst><a:path w="10" h="10"><a:moveTo><a:pt x="0" y="0"/></a:moveTo>'
                        '<a:lnTo><a:pt x="10" y="10"/></a:lnTo></a:path></a:pathLst></a:custGeom>')
             + _sp(22, 'Sombra', xfrm=_xfrm(457200, 0, 457200, 228600),
                   extra_sppr='<a:effectLst><a:outerShdw blurRad="40000"/></a:effectLst>') + '</p:grpSp>')
    parts['ppt/slides/slide2.xml'] = _slide(
        _sp(2, 'Title 1', ph=_ph('title'), text=_p('Indicadores do mês'))
        + _sp(3, 'Content Placeholder 2', ph=_ph('body', '1'), xfrm=_xfrm(int(0.5 * E), int(1.6 * E), int(5 * E), int(3 * E)),
              text=_p(SENTINELS[8], bullet=True, bold=True, color='1F2A44')
              + _p('Segundo tópico', bullet=True, link='rId9')
              + '<a:p><a:fld id="{00000000-0000-0000-0000-000000000002}" type="slidenum"><a:t>2</a:t></a:fld></a:p>')
        + (f'<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="4" name="Grafico"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr>'
           f'{_xfrm(int(6 * E), int(1.6 * E), int(6.5 * E), int(3 * E), "p:xfrm")}<a:graphic><a:graphicData uri="{C}">'
           f'<c:chart xmlns:c="{C}" r:id="rId2"/></a:graphicData></a:graphic></p:graphicFrame>')
        + ('<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="5" name="Tabela"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr>'
           f'{_xfrm(int(0.5 * E), int(4.8 * E), int(5 * E), int(1.1 * E), "p:xfrm")}<a:graphic>'
           '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table"><a:tbl>'
           '<a:tblPr firstRow="1" bandRow="1"><a:tableStyleId>{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}</a:tableStyleId></a:tblPr>'
           '<a:tblGrid><a:gridCol w="1828800"/><a:gridCol w="1371600"/><a:gridCol w="1371600"/></a:tblGrid>'
           f'{table_rows}</a:tbl></a:graphicData></a:graphic></p:graphicFrame>')
        + ('<p:pic><p:nvPicPr><p:cNvPr id="6" name="Foto"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>'
           '<p:blipFill><a:blip r:embed="rId3"/><a:srcRect l="10000"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
           f'<p:spPr>{_xfrm(int(11 * E), int(5 * E), int(1.5 * E), int(1 * E))}<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>')
        + group
        + ('<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="30" name="SmartArt"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr>'
           f'{_xfrm(int(6 * E), int(5 * E), int(4 * E), int(1 * E), "p:xfrm")}<a:graphic>'
           '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/diagram">'
           '<dgm:relIds xmlns:dgm="http://schemas.openxmlformats.org/drawingml/2006/diagram" r:dm="rId5" r:lo="rId6" r:qs="rId7" r:cs="rId8"/>'
           '</a:graphicData></a:graphic></p:graphicFrame>')
        + _sp(31, 'Rodape repetido', xfrm=_xfrm(int(0.5 * E), int(7 * E), int(2 * E), int(0.3 * E)), text=_p('Rodapé')),
        extra='<p:timing><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"/></p:par></p:tnLst></p:timing>')
    parts['ppt/slides/_rels/slide2.xml.rels'] = _rels([
        ('rId1', 'slideLayout', '../slideLayouts/slideLayout2.xml', False), ('rId2', 'chart', '../charts/chart1.xml', False),
        ('rId3', 'image', '../media/image2.jpeg', False), ('rId4', 'notesSlide', '../notesSlides/notesSlide1.xml', False),
        ('rId10', 'comments', '../comments/comment1.xml', False),
        ('rId9', 'hyperlink', f'https://{SENTINELS[7]}/relatorio', True)])
    # slide 3 (oculto): OLE, vídeo vinculado, EMF, WordArt, gradiente, AlternateContent
    parts['ppt/slides/slide3.xml'] = _slide(
        _sp(2, 'Title 1', ph=_ph('title'), text=_p('Anexo'))
        + ('<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="3" name="Objeto"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr>'
           f'{_xfrm(int(0.5 * E), int(1.6 * E), int(3 * E), int(2 * E), "p:xfrm")}<a:graphic>'
           '<a:graphicData uri="http://schemas.openxmlformats.org/presentationml/2006/ole"><p:oleObj r:id="rId2" progId="Excel.Sheet.12"/>'
           '</a:graphicData></a:graphic></p:graphicFrame>')
        + ('<p:pic><p:nvPicPr><p:cNvPr id="4" name="Video"/><p:cNvPicPr/><p:nvPr><a:videoFile r:link="rId3"/></p:nvPr></p:nvPicPr>'
           f'<p:blipFill><a:blip r:embed="rId4"/></p:blipFill><p:spPr>{_xfrm(int(4 * E), int(1.6 * E), int(3 * E), int(2 * E))}</p:spPr></p:pic>')
        + _sp(5, 'WordArt', xfrm=_xfrm(int(8 * E), int(1.6 * E), int(4 * E), int(1 * E)),
              body_pr='<a:bodyPr><a:prstTxWarp prst="textArchUp"><a:avLst/></a:prstTxWarp></a:bodyPr>', text=_p('Arco'))
        + _sp(6, 'Gradiente', xfrm=_xfrm(int(8 * E), int(3 * E), int(4 * E), int(1 * E)),
              fill='<a:gradFill><a:gsLst><a:gs pos="0"><a:srgbClr val="125E68"/></a:gs><a:gs pos="100000"><a:srgbClr val="86449F"/></a:gs></a:gsLst></a:gradFill>')
        + ('<mc:AlternateContent><mc:Choice Requires="p14">'
           + _sp(7, 'Alternativo', xfrm=_xfrm(int(0.5 * E), int(4 * E), int(2 * E), int(0.5 * E)), text=_p('Alt'), txbox=True)
           + '</mc:Choice><mc:Fallback/></mc:AlternateContent>'),
        show=False)
    parts['ppt/slides/_rels/slide3.xml.rels'] = _rels([
        ('rId1', 'slideLayout', '../slideLayouts/slideLayout2.xml', False),
        ('rId2', 'oleObject', '../embeddings/oleObject1.bin', False), ('rId3', 'video', 'file:///videos/sintetico.mp4', True),
        ('rId4', 'image', '../media/image3.emf', False)])
    parts['ppt/charts/chart1.xml'] = (
        f'<?xml version="1.0" encoding="UTF-8"?><c:chartSpace xmlns:c="{C}" xmlns:a="{A}" xmlns:r="{R}"><c:chart>'
        '<c:title><c:tx><c:rich><a:bodyPr/><a:p><a:r><a:t>Titulo do grafico</a:t></a:r></a:p></c:rich></c:tx></c:title>'
        '<c:plotArea><c:barChart><c:barDir val="col"/><c:grouping val="clustered"/>'
        + ''.join(
            f'<c:ser><c:idx val="{s}"/><c:order val="{s}"/><c:spPr><a:solidFill><a:srgbClr val="{["125E68", "86449F"][s]}"/></a:solidFill></c:spPr>'
            '<c:cat><c:strRef><c:f>Plan1!$A$2:$A$5</c:f><c:strCache><c:ptCount val="4"/>'
            + ''.join(f'<c:pt idx="{i}"><c:v>{SENTINELS[3]} {i}</c:v></c:pt>' for i in range(4))
            + '</c:strCache></c:strRef></c:cat><c:val><c:numRef><c:f>Plan1!$B$2:$B$5</c:f><c:numCache><c:formatCode>#,##0</c:formatCode>'
            '<c:ptCount val="4"/>' + ''.join(f'<c:pt idx="{i}"><c:v>{SENTINELS[4]}</c:v></c:pt>' for i in range(4))
            + '</c:numCache></c:numRef></c:val></c:ser>' for s in range(2))
        + '<c:dLbls><c:showVal val="1"/></c:dLbls><c:gapWidth val="150"/><c:axId val="1"/><c:axId val="2"/></c:barChart>'
        '<c:catAx><c:axId val="1"/></c:catAx><c:valAx><c:axId val="2"/></c:valAx></c:plotArea>'
        '<c:legend><c:legendPos val="b"/></c:legend></c:chart><c:externalData r:id="rId1"><c:autoUpdate val="0"/></c:externalData></c:chartSpace>')
    parts['ppt/charts/_rels/chart1.xml.rels'] = _rels([('rId1', 'package', '../embeddings/Planilha1.xlsx', False)])
    parts['ppt/embeddings/Planilha1.xlsx'] = b'PK\x05\x06' + b'\x00' * 18  # zip vazio: planilha nunca é lida
    parts['ppt/embeddings/oleObject1.bin'] = b'\x00' * 16
    parts['ppt/notesSlides/notesSlide1.xml'] = (
        f'<?xml version="1.0" encoding="UTF-8"?><p:notes {NSDECL}><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/>'
        f'<p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>{_sp(2, "Notas", ph=_ph("body", "1"), text=_p(SENTINELS[5]))}'
        '</p:spTree></p:cSld></p:notes>')
    parts['ppt/comments/comment1.xml'] = (
        f'<?xml version="1.0" encoding="UTF-8"?><p:cmLst {NSDECL}><p:cm authorId="0"><p:text>{SENTINELS[6]}</p:text></p:cm></p:cmLst>')
    parts['ppt/media/image1.png'] = _png(120, 40)
    parts['ppt/media/image2.jpeg'] = _jpeg_header(64, 32)
    parts['ppt/media/image3.emf'] = b'\x01\x00\x00\x00' + b'\x00' * 36 + b' EMF'
    parts['ppt/fonts/font1.fntdata'] = b'\x00' * 32
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)
    return path
