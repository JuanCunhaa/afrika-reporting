"""Pacote OPC do PPTX (F07): fontes incorporadas, propriedades personalizadas de proveniência e bytes determinísticos.

Determinismo: para a mesma revisão aprovada, mesmo template/tema e mesmo motor de renderização, o arquivo sai
idêntico byte a byte — datas internas = criação da revisão exportada, entradas ZIP com data fixa (1980-01-01) e
atributos fixos, planilhas incorporadas normalizadas do mesmo modo. Nenhum carimbo de "agora" é gravado.
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape, quoteattr

from lxml import etree
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.opc.package import Part
from pptx.opc.packuri import PackURI
from pptx.oxml.ns import qn

from app.export import fonts as F

FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_CUSTOM_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/custom-properties'
_VT_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes'


def add_custom_properties(prs, props: dict[str, str]) -> None:
    items = ''.join(
        f'<property fmtid="{{D5CDD505-2E9C-101B-9397-08002B2CF9AE}}" pid="{i}" name={quoteattr(k)}>'
        f'<vt:lpwstr>{escape(str(v))}</vt:lpwstr></property>' for i, (k, v) in enumerate(props.items(), start=2))
    blob = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Properties xmlns="{_CUSTOM_NS}" '
            f'xmlns:vt="{_VT_NS}">{items}</Properties>').encode('utf-8')
    pkg = prs.part.package
    part = Part(PackURI('/docProps/custom.xml'), 'application/vnd.openxmlformats-officedocument.custom-properties+xml',
                pkg, blob)
    pkg.relate_to(part, RT.CUSTOM_PROPERTIES)


def embed_fonts(prs, faces: dict[str, set[bool]], book: F.FontBook) -> dict:
    """Incorpora as faces usadas que existem como arquivo OFL local; devolve relatório (incorporadas/não)."""
    report: dict = {'embedded': [], 'not_embedded': []}
    entries: list[tuple[str, dict[str, str]]] = []
    n = 0
    for typeface in sorted(faces):
        rids: dict[str, str] = {}
        # o PowerPoint só reconhece a família incorporada com a variante regular: incluída sempre que existir
        variants = set(faces[typeface]) | ({False} if book.file_for_typeface(typeface, False) else set())
        for bold in sorted(variants):
            path = book.file_for_typeface(typeface, bold)
            variant = 'bold' if bold else 'regular'
            if path is None:
                report['not_embedded'].append({'typeface': typeface, 'variant': variant,
                                               'reason': 'sem arquivo local (fonte do sistema ou ausente)'})
                continue
            try:
                sfnt = F.woff_to_sfnt(path.read_bytes())
                meta = F.info(sfnt)
            except (OSError, ValueError, KeyError) as exc:
                report['not_embedded'].append({'typeface': typeface, 'variant': variant,
                                               'reason': f'arquivo de fonte inválido ({type(exc).__name__})'})
                continue
            if meta['family'] != typeface or not F.embeddable(meta['fs_type']):
                report['not_embedded'].append({'typeface': typeface, 'variant': variant,
                                               'reason': 'nome interno divergente ou incorporação não permitida'})
                continue
            n += 1
            part = Part(PackURI(f'/ppt/fonts/font{n}.fntdata'), 'application/x-fontdata', prs.part.package,
                        F.to_eot(sfnt))
            rids[variant] = prs.part.relate_to(part, RT.FONT)
            report['embedded'].append({'typeface': typeface, 'variant': variant, 'file': path.name,
                                       'style': meta['style'], 'license': 'SIL OFL 1.1 (fonte livre empacotada)'})
        if rids:
            entries.append((typeface, rids))
    if entries:
        pres = prs.part._element
        pres.set('embedTrueTypeFonts', '1')
        lst = etree.Element(qn('p:embeddedFontLst'))
        for typeface, rids in entries:
            ef = etree.SubElement(lst, qn('p:embeddedFont'))
            etree.SubElement(ef, qn('p:font'), typeface=typeface, pitchFamily='2', charset='0')
            for variant in ('regular', 'bold'):
                if variant in rids:
                    el = etree.SubElement(ef, qn(f'p:{variant}'))
                    el.set(qn('r:id'), rids[variant])
        anchor = pres.find(qn('p:smartTags'))
        if anchor is None:
            anchor = pres.find(qn('p:notesSz'))
        anchor.addnext(lst)
    return report


def _zip(entries: list[tuple[str, bytes]]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, blob in entries:
            zi = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.create_system = 0
            zi.external_attr = 0
            z.writestr(zi, blob, compresslevel=6)
    return out.getvalue()


_DCTERMS = re.compile(rb'(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:(?:created|modified)>)')


def _normalize_xlsx(blob: bytes, stamp: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        entries = []
        for info in z.infolist():
            data = z.read(info.filename)
            if info.filename == 'docProps/core.xml':
                data = _DCTERMS.sub(lambda m: m.group(1) + stamp + m.group(2), data)
            entries.append((info.filename, data))
    return _zip(entries)


def normalize(data: bytes, ts: datetime) -> bytes:
    """Reescreve o ZIP com datas/atributos fixos; planilhas incorporadas idem (datas = criação da revisão)."""
    stamp = ts.strftime('%Y-%m-%dT%H:%M:%SZ').encode()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        entries = []
        for info in z.infolist():
            blob = z.read(info.filename)
            if info.filename.startswith('ppt/embeddings/') and info.filename.endswith('.xlsx'):
                blob = _normalize_xlsx(blob, stamp)
            entries.append((info.filename, blob))
    return _zip(entries)
