"""Inspeção LOCAL de PPTX de referência (F06B.1) — relatório técnico para reproduzir o template oficial.

Somente biblioteca padrão (zipfile + ElementTree): nada é enviado a serviços externos, nada é executado (macros,
OLE, vínculos externos são apenas DETECTADOS) e o arquivo não é extraído para o disco.

Privacidade (o PPTX pode conter dados de clientes):
- NENHUM texto de slide, nota, comentário, rótulo/valor de gráfico ou célula de tabela é copiado: só contagens,
  tamanhos e indícios estruturais (ex.: proporção de dígitos, para achar campos de dados).
- Modo `strict` (padrão): também omite nomes (arquivo, tema, masters, layouts, formas, seções) e destinos de vínculos
  externos — identificados por índice e hash curto. Modo `structural`: inclui nomes de masters/layouts/formas/tema
  (necessários para mapear placeholders), nunca conteúdo.
- O relatório é gravado fora do Git (`output/`, `private/` ou `data/`, ignorados) — ver `cli.py`.

Unidades: EMU (1 in = 914400 EMU); px = EMU / 9525 (96 dpi, a mesma escala do canvas HTML: 12192000 EMU = 1280 px).
"""
from __future__ import annotations

import hashlib
import math
import posixpath
import re
import struct
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Literal

TOOL_VERSION = 1
EMU_PER_PX = 9525
EMU_PER_PT = 12700
MAX_ENTRIES = 10_000
MAX_XML_BYTES = 50 * 1024 * 1024
MAX_MEDIA_BYTES = 300 * 1024 * 1024
MAX_RATIO = 200  # compressão suspeita (zip bomb) acima disto, para partes grandes

NS = {
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart',
    'rel': 'http://schemas.openxmlformats.org/package/2006/relationships',
    'ct': 'http://schemas.openxmlformats.org/package/2006/content-types',
    'mc': 'http://schemas.openxmlformats.org/markup-compatibility/2006',
    'p14': 'http://schemas.microsoft.com/office/powerpoint/2010/main',
}
GD_TABLE = 'http://schemas.openxmlformats.org/drawingml/2006/table'
GD_CHART = 'http://schemas.openxmlformats.org/drawingml/2006/chart'
GD_DIAGRAM = 'http://schemas.openxmlformats.org/drawingml/2006/diagram'
GD_OLE = 'http://schemas.openxmlformats.org/presentationml/2006/ole'
GD_CHARTEX = 'http://schemas.microsoft.com/office/drawing/2014/chartex'
REL_EXTERNAL_IMAGE = 'image'
SCHEME_SLOTS = ('dk1', 'lt1', 'dk2', 'lt2', 'accent1', 'accent2', 'accent3', 'accent4', 'accent5', 'accent6',
                'hlink', 'folHlink')
SAFE_FONTS = {'arial', 'calibri', 'calibri light', 'cambria', 'candara', 'consolas', 'corbel', 'courier new',
              'georgia', 'segoe ui', 'segoe ui light', 'segoe ui semibold', 'tahoma', 'times new roman',
              'trebuchet ms', 'verdana', 'aptos', 'aptos display'}
CHART_KINDS = ('barChart', 'bar3DChart', 'lineChart', 'line3DChart', 'pieChart', 'pie3DChart', 'doughnutChart',
               'areaChart', 'area3DChart', 'scatterChart', 'radarChart', 'bubbleChart', 'stockChart', 'surfaceChart',
               'surface3DChart', 'ofPieChart')
Privacy = Literal['strict', 'structural']


class PptxError(ValueError):
    """Arquivo recusado (não é PPTX válido ou viola limites de segurança)."""


def q(tag: str) -> str:
    prefix, _, local = tag.partition(':')
    return f'{{{NS[prefix]}}}{local}'


def local(tag: Any) -> str:
    return tag.rsplit('}', 1)[-1] if isinstance(tag, str) else ''


def first(*elements: ET.Element | None) -> ET.Element | None:
    """Primeiro elemento não nulo (verdade de Element depende de filhos: nunca usar `a or b`)."""
    return next((e for e in elements if e is not None), None)


def emu_px(v: int | float | None) -> float | None:
    return None if v is None else round(v / EMU_PER_PX, 2)


def short_hash(s: str) -> str:
    return hashlib.sha256(s.encode('utf-8')).hexdigest()[:8]


# ---------------------------------------------------------------- pacote

class Package:
    def __init__(self, path: Path):
        self.path = path
        try:
            self.zip = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError) as exc:
            raise PptxError(f'não é um pacote OOXML (zip) válido: {exc.__class__.__name__}') from None
        infos = self.zip.infolist()
        if len(infos) > MAX_ENTRIES:
            raise PptxError(f'pacote com entradas demais ({len(infos)})')
        self.infos = {i.filename: i for i in infos}
        self.problems: list[str] = []
        if '[Content_Types].xml' not in self.infos or 'ppt/presentation.xml' not in self.infos:
            raise PptxError('pacote sem [Content_Types].xml ou ppt/presentation.xml (não é PPTX)')

    def has(self, name: str) -> bool:
        return name in self.infos

    def xml(self, name: str) -> ET.Element | None:
        info = self.infos.get(name)
        if info is None:
            return None
        if info.file_size > MAX_XML_BYTES or (info.file_size > 10 * 1024 * 1024 and
                                              info.file_size > MAX_RATIO * max(1, info.compress_size)):
            self.problems.append(f'parte XML ignorada por limite de segurança: {self._anon(name)}')
            return None
        data = self.zip.read(info)
        if b'<!DOCTYPE' in data[:2048].upper() or b'<!ENTITY' in data.upper():
            self.problems.append(f'parte XML com DOCTYPE/entidades recusada: {self._anon(name)}')
            return None
        try:
            return ET.fromstring(data)
        except ET.ParseError:
            self.problems.append(f'parte XML malformada: {self._anon(name)}')
            return None

    def _anon(self, name: str) -> str:
        return re.sub(r'[^/]+$', lambda m: m.group(0) if re.match(r'^[a-zA-Z]+\d*\.\w+$', m.group(0)) else '…', name)

    def rels(self, part: str) -> dict[str, dict]:
        base, name = posixpath.split(part)
        root = self.xml(posixpath.join(base, '_rels', f'{name}.rels'))
        out = {}
        if root is None:
            return out
        for r in root.findall(q('rel:Relationship')):
            target, mode = r.get('Target', ''), r.get('TargetMode', 'Internal')
            resolved = target if mode == 'External' else posixpath.normpath(posixpath.join(base, target))
            out[r.get('Id', '')] = {'type': r.get('Type', '').rsplit('/', 1)[-1], 'target': resolved,
                                    'external': mode == 'External'}
        return out

    def media_info(self, name: str) -> dict:
        info = self.infos[name]
        h = hashlib.sha256()
        head = b''
        if info.file_size > MAX_MEDIA_BYTES:
            return {'size_bytes': info.file_size, 'sha256': None, 'note': 'grande demais para hash'}
        with self.zip.open(info) as fh:
            while chunk := fh.read(65536):
                if len(head) < 64 * 1024:
                    head += chunk[:64 * 1024 - len(head)]
                h.update(chunk)
        ext = posixpath.splitext(name)[1].lower().lstrip('.')
        return {'size_bytes': info.file_size, 'sha256': h.hexdigest(), 'format': ext,
                'pixels': image_size(head, ext)}


def image_size(head: bytes, ext: str) -> list[int] | None:
    """Dimensões em pixels pelo cabeçalho (PNG, JPEG, GIF); vetoriais/EMF/WMF => None."""
    try:
        if head.startswith(b'\x89PNG') and len(head) >= 24:
            return list(struct.unpack('>II', head[16:24]))
        if head[:6] in (b'GIF87a', b'GIF89a'):
            return list(struct.unpack('<HH', head[6:10]))
        if head.startswith(b'\xff\xd8'):
            i = 2
            while i + 9 < len(head):
                if head[i] != 0xFF:
                    i += 1
                    continue
                marker = head[i + 1]
                seg = struct.unpack('>H', head[i + 2:i + 4])[0]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack('>HH', head[i + 5:i + 9])
                    return [w, h]
                i += 2 + seg
    except struct.error:
        return None
    return None


# ---------------------------------------------------------------- formas

def _xfrm(el: ET.Element) -> dict | None:
    x = first(el.find(f"{q('p:spPr')}/{q('a:xfrm')}"), el.find(f"{q('p:grpSpPr')}/{q('a:xfrm')}"),
              el.find(q('p:xfrm')))
    if x is None:
        return None
    off, ext = x.find(q('a:off')), x.find(q('a:ext'))
    if off is None or ext is None:
        return None
    out = {'x': int(off.get('x', 0)), 'y': int(off.get('y', 0)), 'cx': int(ext.get('cx', 0)),
           'cy': int(ext.get('cy', 0)), 'rot': int(x.get('rot', 0)) / 60000,
           'flip': bool(x.get('flipH') == '1' or x.get('flipV') == '1')}
    ch_off, ch_ext = x.find(q('a:chOff')), x.find(q('a:chExt'))
    if ch_off is not None and ch_ext is not None:
        out['ch'] = (int(ch_off.get('x', 0)), int(ch_off.get('y', 0)), int(ch_ext.get('cx', 1)) or 1,
                     int(ch_ext.get('cy', 1)) or 1)
    return out


def _apply_group(box: dict, groups: list[dict]) -> dict:
    """Coordenadas de filhos de grupo -> coordenadas do slide (escala/deslocamento de cada grupo)."""
    x, y, cx, cy = box['x'], box['y'], box['cx'], box['cy']
    for g in reversed(groups):
        if 'ch' not in g:
            continue
        cox, coy, cex, cey = g['ch']
        sx, sy = g['cx'] / cex, g['cy'] / cey
        x, y, cx, cy = g['x'] + (x - cox) * sx, g['y'] + (y - coy) * sy, cx * sx, cy * sy
    return {**box, 'x': round(x), 'y': round(y), 'cx': round(cx), 'cy': round(cy)}


def _box_px(b: dict | None) -> dict | None:
    if b is None:
        return None
    return {'x': emu_px(b['x']), 'y': emu_px(b['y']), 'w': emu_px(b['cx']), 'h': emu_px(b['cy'])}


MAX_PATH_CHARS = 4000


def _cust_path(cust: ET.Element | None, box_px: dict | None) -> str | None:
    """Contorno de uma geometria personalizada (<a:custGeom>) como path SVG em px RELATIVOS à caixa da forma.
    Geometria pura (sem texto/imagem). None se usar fórmulas (guias), arcos degenerados ou ficar grande demais."""
    if cust is None or not box_px or box_px['w'] <= 0 or box_px['h'] <= 0:
        return None
    out: list[str] = []
    for path in cust.iter(q('a:path')):
        pw, ph = int(path.get('w', '0') or 0), int(path.get('h', '0') or 0)
        if pw <= 0 or ph <= 0:
            return None
        sx, sy = box_px['w'] / pw, box_px['h'] / ph
        cur = (0.0, 0.0)

        def pt(p: ET.Element) -> tuple[float, float]:
            return int(p.get('x')) * sx, int(p.get('y')) * sy

        try:
            for cmd in path:
                name = local(cmd.tag)
                pts = [pt(p) for p in cmd.iter(q('a:pt'))]
                if name in ('moveTo', 'lnTo') and len(pts) == 1:
                    cur = pts[0]
                    out.append(('M' if name == 'moveTo' else 'L') + f'{cur[0]:.1f} {cur[1]:.1f}')
                elif name == 'cubicBezTo' and len(pts) == 3:
                    cur = pts[2]
                    out.append('C' + ' '.join(f'{x:.1f} {y:.1f}' for x, y in pts))
                elif name == 'quadBezTo' and len(pts) == 2:
                    cur = pts[1]
                    out.append('Q' + ' '.join(f'{x:.1f} {y:.1f}' for x, y in pts))
                elif name == 'arcTo':
                    wr, hr = int(cmd.get('wR')) * sx, int(cmd.get('hR')) * sy
                    st, sw = math.radians(int(cmd.get('stAng')) / 60000), math.radians(int(cmd.get('swAng')) / 60000)
                    cx, cy = cur[0] - wr * math.cos(st), cur[1] - hr * math.sin(st)
                    cur = (cx + wr * math.cos(st + sw), cy + hr * math.sin(st + sw))
                    out.append(f'A{wr:.1f} {hr:.1f} 0 {int(abs(sw) > math.pi)} {int(sw > 0)} {cur[0]:.1f} {cur[1]:.1f}')
                elif name == 'close':
                    out.append('Z')
                else:
                    return None
        except (TypeError, ValueError):  # coordenadas por guia/fórmula: não reproduzido
            return None
    d = ''.join(out)
    return d if d and len(d) <= MAX_PATH_CHARS else None


def _fill(sppr: ET.Element | None) -> str | None:
    if sppr is None:
        return None
    for tag, name in (('a:solidFill', 'solid'), ('a:gradFill', 'gradient'), ('a:blipFill', 'image'),
                      ('a:pattFill', 'pattern'), ('a:noFill', 'none'), ('a:grpFill', 'group')):
        if sppr.find(q(tag)) is not None:
            return name
    return None


def _hex_to_rgb(h: str) -> tuple[float, float, float]:
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))  # type: ignore[return-value]


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return '#' + ''.join(f'{max(0, min(255, round(c * 255))):02X}' for c in rgb)


def _rgb_to_hsl(r: float, g: float, b: float) -> tuple[float, float, float]:
    mx, mn = max(r, g, b), min(r, g, b)
    lum = (mx + mn) / 2
    if mx == mn:
        return 0.0, 0.0, lum
    d = mx - mn
    sat = d / (2 - mx - mn) if lum > 0.5 else d / (mx + mn)
    if mx == r:
        hue = ((g - b) / d + (6 if g < b else 0)) / 6
    elif mx == g:
        hue = ((b - r) / d + 2) / 6
    else:
        hue = ((r - g) / d + 4) / 6
    return hue, sat, lum


def _hsl_to_rgb(hue: float, sat: float, lum: float) -> tuple[float, float, float]:
    if sat == 0:
        return lum, lum, lum
    def channel(p: float, q_: float, t: float) -> float:
        t %= 1
        if t < 1 / 6:
            return p + (q_ - p) * 6 * t
        if t < 1 / 2:
            return q_
        if t < 2 / 3:
            return p + (q_ - p) * (2 / 3 - t) * 6
        return p
    q_ = lum * (1 + sat) if lum < 0.5 else lum + sat - lum * sat
    p_ = 2 * lum - q_
    return channel(p_, q_, hue + 1 / 3), channel(p_, q_, hue), channel(p_, q_, hue - 1 / 3)


class ColorResolver:
    """Cor efetiva de um elemento de cor DrawingML (srgb/esquema/sistema) com os modificadores mais comuns
    (lumMod, lumOff, tint, shade). Esquema resolvido pelo tema + clrMap do master (bg1→lt1, tx1→dk1…)."""
    PRESET = {'black': '#000000', 'white': '#FFFFFF', 'red': '#FF0000', 'green': '#008000', 'blue': '#0000FF',
              'yellow': '#FFFF00', 'gray': '#808080'}

    def __init__(self, scheme: dict[str, str], clr_map: dict[str, str]):
        self.scheme, self.clr_map = scheme, clr_map

    def resolve(self, el: ET.Element | None) -> str | None:
        if el is None:
            return None
        tag, base = local(el.tag), None
        if tag == 'srgbClr':
            base = '#' + el.get('val', '').upper()
        elif tag == 'schemeClr':
            slot = el.get('val', '')
            base = self.scheme.get(self.clr_map.get(slot, slot))
        elif tag == 'sysClr':
            base = '#' + el.get('lastClr', '000000').upper()
        elif tag == 'prstClr':
            base = self.PRESET.get(el.get('val', ''))
        if not base or not re.fullmatch(r'#[0-9A-F]{6}', base):
            return None
        r, g, b = _hex_to_rgb(base)
        for m in el:
            name, val = local(m.tag), int(m.get('val', '100000')) / 100000
            if name == 'tint':
                r, g, b = (c + (1 - c) * (1 - val) for c in (r, g, b))
            elif name == 'shade':
                r, g, b = (c * val for c in (r, g, b))
            elif name in ('lumMod', 'lumOff'):
                hue, sat, lum = _rgb_to_hsl(r, g, b)
                lum = lum * val if name == 'lumMod' else lum + val
                r, g, b = _hsl_to_rgb(hue, sat, max(0.0, min(1.0, lum)))
        return _rgb_to_hex((r, g, b))

    @staticmethod
    def alpha(container: ET.Element | None) -> float | None:
        """Opacidade (0–100) de um <a:solidFill>, só quando diferente de 100%."""
        if container is None:
            return None
        if local(container.tag) != 'solidFill':
            container = container.find(q('a:solidFill'))
        if container is None or not len(container):
            return None
        a = container[0].find(q('a:alpha'))
        if a is None:
            return None
        val = round(int(a.get('val', '100000')) / 1000, 1)
        return None if val >= 100 else val

    def of_fill(self, container: ET.Element | None) -> str | None:
        """Cor de um <a:solidFill> (ou de um elemento que contém um)."""
        if container is None:
            return None
        if local(container.tag) != 'solidFill':
            container = container.find(q('a:solidFill'))
            if container is None:
                return None
        return self.resolve(container[0]) if len(container) else None

    def gradient(self, grad: ET.Element | None) -> dict | None:
        if grad is None:
            return None
        stops = []
        for gs in grad.iter(q('a:gs')):
            if len(gs):
                stops.append({'pos': int(gs.get('pos', 0)) / 1000, 'color': self.resolve(gs[0])})
        lin = grad.find(q('a:lin'))
        return {'stops': stops, 'angle': None if lin is None else int(lin.get('ang', 0)) / 60000}


class Collector:
    """Acumula cores, fontes, tamanhos e efeitos vistos em qualquer parte."""

    def __init__(self, theme_fonts: dict[str, str], colors: ColorResolver | None = None):
        self.theme_fonts = theme_fonts
        self.colors = colors or ColorResolver({}, {})
        self.srgb: Counter = Counter()
        self.scheme: Counter = Counter()
        self.fonts: Counter = Counter()
        self.sizes: Counter = Counter()

    def colors_in(self, el: ET.Element) -> None:
        for c in el.iter(q('a:srgbClr')):
            if re.fullmatch(r'[0-9A-Fa-f]{6}', c.get('val', '')):
                self.srgb['#' + c.get('val').upper()] += 1
        for c in el.iter(q('a:schemeClr')):
            self.scheme[c.get('val', '?')] += 1

    def font(self, typeface: str | None) -> str | None:
        if not typeface:
            return None
        resolved = self.theme_fonts.get(typeface, typeface)  # +mj-lt / +mn-lt => fonte do tema
        self.fonts[resolved] += 1
        return resolved


def _text_stats(tx: ET.Element | None, col: Collector) -> dict | None:
    if tx is None:
        return None
    paras = tx.findall(q('a:p'))
    runs = [r for p in paras for r in p.findall(q('a:r'))]
    text = ''.join(t.text or '' for t in tx.iter(q('a:t')))
    for rpr in [*tx.iter(q('a:rPr')), *tx.iter(q('a:defRPr')), *tx.iter(q('a:endParaRPr'))]:
        if rpr.get('sz'):
            col.sizes[int(rpr.get('sz')) / 100] += 1
        latin = rpr.find(q('a:latin'))
        if latin is not None:
            col.font(latin.get('typeface'))
    body = tx.find(q('a:bodyPr'))  # cores do texto já entram na varredura do slide inteiro (SlidePart)
    digits = sum(ch.isdigit() for ch in text)
    # Estilo efetivo por run (ponderado pelo nº de caracteres; o texto em si nunca sai daqui)
    weight: Counter = Counter()
    sizes, colors, fonts = Counter(), Counter(), Counter()
    bold_chars = 0
    for r in runs:
        rpr = r.find(q('a:rPr'))
        n = len(''.join(t.text or '' for t in r.iter(q('a:t')))) or 1
        weight['chars'] += n
        if rpr is None:
            continue
        if rpr.get('sz'):
            sizes[int(rpr.get('sz')) / 100] += n
        if rpr.get('b') == '1':
            bold_chars += n
        c = col.colors.of_fill(rpr)
        if c:
            colors[c] += n
        latin = rpr.find(q('a:latin'))
        if latin is not None and latin.get('typeface'):
            fonts[col.theme_fonts.get(latin.get('typeface'), latin.get('typeface'))] += n
    for rpr in tx.iter(q('a:endParaRPr')):
        if rpr.get('sz') and not sizes:
            sizes[int(rpr.get('sz')) / 100] += 1
    style = {'sizes_pt': [s_ for s_, _ in sizes.most_common(4)], 'colors': [c for c, _ in colors.most_common(4)],
             'fonts': [f for f, _ in fonts.most_common(3)],
             'bold_share': round(bold_chars / weight['chars'], 2) if weight['chars'] else 0.0}
    return {
        'style': style,
        'paragraphs': len(paras), 'runs': len(runs), 'characters': len(text), 'words': len(text.split()),
        'digit_ratio': round(digits / len(text), 2) if text else 0.0,
        'bold_runs': sum(1 for r in runs if (r.find(q('a:rPr')) is not None and r.find(q('a:rPr')).get('b') == '1')),
        'fields': sorted({f.get('type', 'outro') for f in tx.iter(q('a:fld'))}),
        'bullets': sum(1 for p in paras if p.find(f"{q('a:pPr')}/{q('a:buChar')}") is not None
                       or p.find(f"{q('a:pPr')}/{q('a:buAutoNum')}") is not None),
        'alignments': sorted({p.find(q('a:pPr')).get('algn') for p in paras
                              if p.find(q('a:pPr')) is not None and p.find(q('a:pPr')).get('algn')}),
        'autofit': None if body is None else ('normal' if body.find(q('a:normAutofit')) is not None else
                                              'shape' if body.find(q('a:spAutoFit')) is not None else None),
        'vertical': None if body is None else body.get('vert'),
        'warp': None if body is None or body.find(q('a:prstTxWarp')) is None
        else body.find(q('a:prstTxWarp')).get('prst'),
        'hyperlinks': sum(1 for _ in tx.iter(q('a:hlinkClick'))),
    }


def _merge_styles(stats: list[dict | None]) -> dict:
    sizes, colors, fonts = Counter(), Counter(), Counter()
    for st in stats:
        if not st:
            continue
        for x in st['style']['sizes_pt']:
            sizes[x] += 1
        for x in st['style']['colors']:
            colors[x] += 1
        for x in st['style']['fonts']:
            fonts[x] += 1
    return {'sizes_pt': [x for x, _ in sizes.most_common(4)], 'colors': [x for x, _ in colors.most_common(4)],
            'fonts': [x for x, _ in fonts.most_common(3)]}


def _effects(sppr: ET.Element | None) -> list[str]:
    if sppr is None:
        return []
    out = []
    eff = sppr.find(q('a:effectLst'))
    if eff is not None:
        out += sorted({local(e.tag) for e in eff})
    if sppr.find(q('a:scene3d')) is not None or sppr.find(q('a:sp3d')) is not None:
        out.append('3d')
    return out


class SlidePart:
    """Formas de um slide/layout/master (recursivo em grupos e AlternateContent)."""

    def __init__(self, pkg: Package, part: str, col: Collector, privacy: Privacy):
        self.pkg, self.part, self.col, self.privacy = pkg, part, col, privacy
        self.root = pkg.xml(part)
        self.rels = pkg.rels(part)
        self.shapes: list[dict] = []
        self.flags: Counter = Counter()
        if self.root is not None:
            tree = self.root.find(f"{q('p:cSld')}/{q('p:spTree')}")
            if tree is not None:
                self._walk(tree, [], depth=0)
            self.col.colors_in(self.root.find(q('p:cSld')) if self.root.find(q('p:cSld')) is not None
                               else self.root)

    def name_of(self, nv: ET.Element | None, kind: str, n: int) -> str:
        raw = '' if nv is None else (nv.get('name') or '')
        if self.privacy == 'structural' and raw:
            return raw
        return f'{kind}-{n}' + (f'#{short_hash(raw)}' if raw else '')

    def _walk(self, tree: ET.Element, groups: list[dict], depth: int) -> None:
        for el in tree:
            tag = local(el.tag)
            if tag == 'AlternateContent':
                choice = el.find(q('mc:Choice'))
                branch = choice if choice is not None else el.find(q('mc:Fallback'))
                if branch is not None:
                    self._walk(branch, groups, depth)
                continue
            if tag not in ('sp', 'pic', 'graphicFrame', 'grpSp', 'cxnSp', 'contentPart'):
                continue
            n = len(self.shapes) + 1
            nvroot = el[0] if len(el) else None  # nvSpPr / nvPicPr / nvGraphicFramePr / nvGrpSpPr / nvCxnSpPr
            nv = None if nvroot is None else nvroot.find(q('p:cNvPr'))
            ph = None if nvroot is None else nvroot.find(f"{q('p:nvPr')}/{q('p:ph')}")
            box = _xfrm(el)
            if box is not None:
                box = _apply_group(box, groups)
            sppr = el.find(q('p:spPr'))
            shape: dict[str, Any] = {
                'n': n, 'kind': {'sp': 'shape', 'pic': 'picture', 'graphicFrame': 'frame', 'grpSp': 'group',
                                 'cxnSp': 'connector', 'contentPart': 'ink'}[tag],
                'name': self.name_of(nv, tag, n), 'depth': depth, 'box_emu': box, 'box_px': _box_px(box),
                'placeholder': None if ph is None else {'type': ph.get('type', 'body'), 'idx': ph.get('idx')},
                'hidden': nv is not None and nv.get('hidden') == '1',
                'has_alt_text': nv is not None and bool(nv.get('descr')),
            }
            if box and box['rot']:
                shape['rotation'] = box['rot']
                self.flags['rotation'] += 1
            if box and box['flip']:
                self.flags['flip'] += 1
            if sppr is not None:
                geom = sppr.find(q('a:prstGeom'))
                shape['geometry'] = 'custom' if sppr.find(q('a:custGeom')) is not None else \
                    (geom.get('prst') if geom is not None else None)
                if shape['geometry'] == 'custom':
                    self.flags['custom_geometry'] += 1
                    shape['custom_path'] = _cust_path(sppr.find(q('a:custGeom')), shape['box_px'])
                shape['fill'] = _fill(sppr)
                if shape['fill'] in ('gradient', 'pattern', 'image') and tag == 'sp':
                    self.flags[f'{shape["fill"]}_fill'] += 1
                if shape['fill'] == 'solid':
                    shape['fill_color'] = self.col.colors.of_fill(sppr)
                    shape['fill_alpha'] = ColorResolver.alpha(sppr)
                elif shape['fill'] == 'gradient':
                    shape['fill_gradient'] = self.col.colors.gradient(sppr.find(q('a:gradFill')))
                elif shape['fill'] is None:
                    ref = el.find(f"{q('p:style')}/{q('a:fillRef')}")
                    if ref is not None and len(ref) and ref.get('idx', '0') != '0':
                        shape['fill'] = 'style'
                        shape['fill_color'] = self.col.colors.resolve(ref[0])
                ln = sppr.find(q('a:ln'))
                if ln is not None and ln.get('w'):
                    shape['line_pt'] = round(int(ln.get('w')) / EMU_PER_PT, 2)
                if ln is not None:
                    lc = self.col.colors.of_fill(ln)
                    if lc:
                        shape['line_color'] = lc
                    if ln.find(q('a:noFill')) is not None:
                        shape['line'] = 'none'
                elif el.find(f"{q('p:style')}/{q('a:lnRef')}") is not None:
                    lref = el.find(f"{q('p:style')}/{q('a:lnRef')}")
                    if len(lref) and lref.get('idx', '0') != '0':
                        shape['line_color'] = self.col.colors.resolve(lref[0])
                eff = _effects(sppr)
                if eff:
                    shape['effects'] = eff
                    for e in eff:
                        self.flags['effect_3d' if e == '3d' else 'effect'] += 1
            if tag in ('sp', 'cxnSp'):
                shape['text'] = _text_stats(el.find(q('p:txBody')), self.col)
                if shape['text'] and shape['text']['warp']:
                    self.flags['wordart_warp'] += 1
                if shape['text'] and shape['text']['vertical'] not in (None, 'horz'):
                    self.flags['vertical_text'] += 1
                cnv = None if nvroot is None else nvroot.find(q('p:cNvSpPr'))
                if cnv is not None and cnv.get('txBox') == '1':
                    shape['text_box'] = True
            elif tag == 'pic':
                self._picture(el, shape, nvroot)
            elif tag == 'graphicFrame':
                self._frame(el, shape)
            elif tag == 'grpSp':
                g = _xfrm(el)
                self.shapes.append(shape)
                self._walk(el, [*groups, g] if g else groups, depth + 1)
                continue
            elif tag == 'contentPart':
                self.flags['ink'] += 1
            self.shapes.append(shape)

    def _picture(self, el: ET.Element, shape: dict, nvroot: ET.Element | None) -> None:
        blip = el.find(f'.//{q("a:blip")}')
        rid = None if blip is None else (blip.get(q('r:embed')) or blip.get(q('r:link')))
        # imagem vetorial (extensão Office 2016): <asvg:svgBlip r:embed>; vale sozinha quando não há bitmap reserva
        svg = None if blip is None else next((e for e in blip.iter() if local(e.tag) == 'svgBlip'), None)
        svg_rid = None if svg is None else (svg.get(q('r:embed')) or svg.get(q('r:link')))
        rel = self.rels.get(rid or svg_rid or '', {})
        shape['image'] = {'external': rel.get('external', False),
                          'target': (None if rel.get('external') else rel.get('target')),
                          'cropped': el.find(f'.//{q("a:srcRect")}') is not None, 'vector': svg_rid is not None}
        if rel.get('external'):
            self.flags['external_image'] += 1
        nvpr = None if nvroot is None else nvroot.find(q('p:nvPr'))
        if nvpr is not None:
            if nvpr.find(q('a:videoFile')) is not None or any(local(m.tag) == 'media' for m in nvpr.iter()):
                self.flags['video_or_audio'] += 1
                shape['media'] = True
            if nvpr.find(q('a:audioFile')) is not None:
                self.flags['video_or_audio'] += 1
                shape['media'] = True

    def _frame(self, el: ET.Element, shape: dict) -> None:
        gd = el.find(f'{q("a:graphic")}/{q("a:graphicData")}')
        uri = '' if gd is None else gd.get('uri', '')
        if uri == GD_TABLE:
            tbl = gd.find(q('a:tbl'))
            rows = tbl.findall(q('a:tr')) if tbl is not None else []
            cells = [c for r in rows for c in r.findall(q('a:tc'))]
            tblpr = None if tbl is None else tbl.find(q('a:tblPr'))
            style = None if tblpr is None else tblpr.find(q('a:tableStyleId'))
            shape['table'] = {
                'rows': len(rows), 'columns': len(tbl.findall(f"{q('a:tblGrid')}/{q('a:gridCol')}")) if tbl is not None
                else 0,
                'column_widths_px': [emu_px(int(g.get('w', 0))) for g in tbl.findall(f"{q('a:tblGrid')}/{q('a:gridCol')}")]
                if tbl is not None else [],
                'merged_cells': sum(1 for c in cells if any(c.get(k) for k in ('gridSpan', 'rowSpan', 'hMerge', 'vMerge'))),
                'style_id': None if style is None else style.text,
                'flags': sorted(k for k in ('firstRow', 'lastRow', 'bandRow', 'firstCol', 'bandCol')
                                if tblpr is not None and tblpr.get(k) == '1'),
                'numeric_cells': sum(1 for c in cells if re.search(r'\d', ''.join(t.text or '' for t in c.iter(q('a:t'))))),
                'header_fill': None if not rows else Counter(
                    self.col.colors.of_fill(c.find(q('a:tcPr'))) for c in rows[0].findall(q('a:tc'))).most_common(1)[0][0],
                'body_fills': [c for c, _ in Counter(self.col.colors.of_fill(c.find(q('a:tcPr')))
                                                     for r in rows[1:] for c in r.findall(q('a:tc'))).most_common(3)],
                'row_heights_px': sorted({emu_px(int(r.get('h', 0))) for r in rows})[:4],
                'text_style': _merge_styles([_text_stats(c.find(q('a:txBody')), self.col) for c in cells]),
            }
        elif uri == GD_CHART:
            ref = gd.find(q('c:chart'))
            rel = self.rels.get('' if ref is None else ref.get(q('r:id'), ''), {})
            shape['chart'] = chart_info(self.pkg, rel.get('target'), self.col) if rel.get('target') else \
                {'error': 'gráfico sem parte'}
        elif uri == GD_DIAGRAM:
            shape['smartart'] = True
            self.flags['smartart'] += 1
        elif uri == GD_OLE:
            shape['ole'] = True
            self.flags['ole_object'] += 1
        elif uri == GD_CHARTEX or 'chartex' in uri:
            shape['chartex'] = True
            self.flags['chartex'] += 1
        else:
            shape['graphic_uri'] = uri.rsplit('/', 1)[-1] or None
            self.flags['other_graphic'] += 1


def chart_info(pkg: Package, part: str, col: Collector) -> dict:
    root = pkg.xml(part)
    if root is None:
        return {'error': 'parte do gráfico ilegível'}
    chart = root.find(q('c:chart'))
    plot = None if chart is None else chart.find(q('c:plotArea'))
    kinds = []
    if plot is not None:
        for k in plot:
            if local(k.tag) in CHART_KINDS:
                sers = k.findall(q('c:ser'))
                points = []
                for s in sers:
                    pc = first(s.find(f".//{q('c:val')}//{q('c:ptCount')}"),
                               s.find(f".//{q('c:yVal')}//{q('c:ptCount')}"))
                    points.append(int(pc.get('val')) if pc is not None else None)
                fmt = {f.text for f in k.iter(q('c:formatCode')) if f.text}
                series_colors, point_colors = [], []
                for s in sers:
                    sp = s.find(q('c:spPr'))
                    series_colors.append(None if sp is None else (col.colors.of_fill(sp) or
                                                                  col.colors.of_fill(sp.find(q('a:ln')))))
                    point_colors.append([col.colors.of_fill(d.find(q('c:spPr'))) for d in s.findall(q('c:dPt'))])
                hole = k.find(q('c:holeSize'))
                kinds.append({
                    'series_colors': series_colors,
                    'point_colors': point_colors if any(point_colors) else None,
                    'hole_size': None if hole is None else int(hole.get('val', 0)),
                    'markers': None if k.find(q('c:marker')) is None else k.find(q('c:marker')).get('val'),
                    'show_percent': any(e.get('val') == '1' for e in k.iter(q('c:showPercent'))),
                    'type': local(k.tag),
                    'bar_direction': (k.find(q('c:barDir')).get('val') if k.find(q('c:barDir')) is not None else None),
                    'grouping': (k.find(q('c:grouping')).get('val') if k.find(q('c:grouping')) is not None else None),
                    'series': len(sers), 'points_per_series': points, 'number_formats': sorted(fmt)[:5],
                    'data_labels': k.find(f".//{q('c:dLbls')}/{q('c:showVal')}") is not None and
                    k.find(f".//{q('c:dLbls')}/{q('c:showVal')}").get('val') == '1',
                    'gap_width': (k.find(q('c:gapWidth')).get('val') if k.find(q('c:gapWidth')) is not None else None),
                })
    col.colors_in(root)
    legend = None if chart is None else chart.find(q('c:legend'))
    ext = root.find(q('c:externalData'))
    rels = pkg.rels(part)
    linked = any(r['external'] for r in rels.values())
    return {
        'kinds': kinds,
        'has_title': chart is not None and chart.find(q('c:title')) is not None,
        'legend_position': None if legend is None or legend.find(q('c:legendPos')) is None
        else legend.find(q('c:legendPos')).get('val'),
        'axes': sorted({local(a.tag) for a in (plot if plot is not None else []) if local(a.tag).endswith('Ax')}),
        'embedded_workbook': ext is not None and not linked,
        'linked_external_data': linked,
        'is_3d': any(k['type'].endswith('3DChart') or k['type'].startswith('surface') for k in kinds),
        'gridlines': sorted({local(g.tag) for g in root.iter() if local(g.tag) in ('majorGridlines', 'minorGridlines')}),
        'text_sizes_pt': sorted({int(e.get('sz')) / 100 for e in root.iter(q('a:defRPr')) if e.get('sz')}
                                | {int(e.get('sz')) / 100 for e in root.iter(q('a:rPr')) if e.get('sz')})[:6],
    }


# ---------------------------------------------------------------- tema

def theme_info(pkg: Package, part: str | None, privacy: Privacy) -> dict:
    root = None if part is None else pkg.xml(part)
    if root is None:
        return {'colors': {}, 'fonts': {}, 'name': None}
    out: dict[str, Any] = {'name': root.get('name') if privacy == 'structural' else
                           (f'tema#{short_hash(root.get("name", ""))}' if root.get('name') else None)}
    scheme = root.find(f"{q('a:themeElements')}/{q('a:clrScheme')}")
    colors = {}
    if scheme is not None:
        for slot in SCHEME_SLOTS:
            el = scheme.find(q(f'a:{slot}'))
            if el is None or not len(el):
                continue
            c = el[0]
            val = c.get('val') if local(c.tag) == 'srgbClr' else c.get('lastClr')
            if val and re.fullmatch(r'[0-9A-Fa-f]{6}', val):
                colors[slot] = '#' + val.upper()
    out['colors'] = colors
    fonts = {}
    fs = root.find(f"{q('a:themeElements')}/{q('a:fontScheme')}")
    if fs is not None:
        for role, tag in (('major', 'a:majorFont'), ('minor', 'a:minorFont')):
            el = fs.find(q(tag))
            latin = None if el is None else el.find(q('a:latin'))
            if latin is not None:
                fonts[role] = latin.get('typeface')
    out['fonts'] = fonts
    return out


def _master_text_styles(root: ET.Element | None, col: Collector) -> dict:
    out = {}
    if root is None:
        return out
    styles = root.find(q('p:txStyles'))
    if styles is None:
        return out
    for name in ('titleStyle', 'bodyStyle', 'otherStyle'):
        st = styles.find(q(f'p:{name}'))
        lvl = None if st is None else st.find(q('a:lvl1pPr'))
        rpr = None if lvl is None else lvl.find(q('a:defRPr'))
        if rpr is None:
            continue
        latin = rpr.find(q('a:latin'))
        out[name] = {'size_pt': int(rpr.get('sz')) / 100 if rpr.get('sz') else None,
                     'bold': rpr.get('b') == '1', 'font': col.font(None if latin is None else latin.get('typeface'))}
    return out


def _background_detail(root: ET.Element | None, colors: ColorResolver) -> dict | None:
    if root is None:
        return None
    bg = root.find(f"{q('p:cSld')}/{q('p:bg')}")
    if bg is None:
        return None
    pr, ref = bg.find(q('p:bgPr')), bg.find(q('p:bgRef'))
    if ref is not None:
        return {'type': 'theme_style', 'idx': ref.get('idx'), 'color': colors.resolve(ref[0]) if len(ref) else None}
    if pr is None:
        return {'type': 'other'}
    kind = _fill(pr)
    out: dict[str, Any] = {'type': kind}
    if kind == 'solid':
        out['color'] = colors.of_fill(pr)
    elif kind == 'gradient':
        out['gradient'] = colors.gradient(pr.find(q('a:gradFill')))
    elif kind == 'image':
        out['image'] = True
    return out


def _background(root: ET.Element | None) -> str | None:
    if root is None:
        return None
    bg = root.find(f"{q('p:cSld')}/{q('p:bg')}")
    if bg is None:
        return None
    if bg.find(q('p:bgRef')) is not None:
        return 'theme_style'
    pr = bg.find(q('p:bgPr'))
    return _fill(pr) if pr is not None else 'other'


# ---------------------------------------------------------------- relatório

def inspect(path: str | Path, privacy: Privacy = 'strict') -> dict:
    path = Path(path)
    pkg = Package(path)
    pres = pkg.xml('ppt/presentation.xml')
    if pres is None:
        raise PptxError('ppt/presentation.xml ilegível')
    prels = pkg.rels('ppt/presentation.xml')
    sld_sz = pres.find(q('p:sldSz'))
    cx, cy = (int(sld_sz.get('cx')), int(sld_sz.get('cy'))) if sld_sz is not None else (None, None)
    theme_part = next((r['target'] for r in prels.values() if r['type'] == 'theme'), None)
    master_ids = pres.findall(f"{q('p:sldMasterIdLst')}/{q('p:sldMasterId')}")
    masters_parts = [prels[m.get(q('r:id'))]['target'] for m in master_ids if m.get(q('r:id')) in prels]
    # O tema efetivo vem do master (rels do master), não da apresentação
    if masters_parts:
        mrels = pkg.rels(masters_parts[0])
        theme_part = next((r['target'] for r in mrels.values() if r['type'] == 'theme'), theme_part)
    theme = theme_info(pkg, theme_part, privacy)
    tf = theme.get('fonts', {})
    mroot = pkg.xml(masters_parts[0]) if masters_parts else None
    cmap_el = None if mroot is None else mroot.find(q('p:clrMap'))
    clr_map = {} if cmap_el is None else dict(cmap_el.attrib)
    resolver = ColorResolver(theme.get('colors', {}), clr_map)
    col = Collector({'+mj-lt': tf.get('major'), '+mn-lt': tf.get('minor')} if tf else {}, resolver)

    layouts_by_part: dict[str, dict] = {}
    masters = []
    for mi, mpart in enumerate(masters_parts, start=1):
        m = SlidePart(pkg, mpart, col, privacy)
        mname = (m.root.find(q('p:cSld')).get('name') if m.root is not None and m.root.find(q('p:cSld')) is not None
                 else None)
        lay_list = []
        for li, (rid, rel) in enumerate(sorted(((k, v) for k, v in m.rels.items() if v['type'] == 'slideLayout'),
                                               key=lambda kv: kv[1]['target']), start=1):
            lp = SlidePart(pkg, rel['target'], col, privacy)
            csld = None if lp.root is None else lp.root.find(q('p:cSld'))
            raw = '' if csld is None else (csld.get('name') or '')
            entry = {'id': f'layout-{mi}.{li}', 'name': raw if privacy == 'structural' else
                     (f'layout#{short_hash(raw)}' if raw else None),
                     'type': None if lp.root is None else lp.root.get('type', 'cust'), 'part': rel['target'],
                     'background': _background(lp.root),
                     'background_detail': _background_detail(lp.root, resolver),
                     'placeholders': [{'type': s['placeholder']['type'], 'idx': s['placeholder']['idx'],
                                       'box_px': s['box_px']} for s in lp.shapes if s['placeholder']],
                     'static_shapes': [_static(s) for s in lp.shapes if not s['placeholder'] and s['depth'] == 0],
                     'used_by_slides': [], '_part': lp}
            layouts_by_part[rel['target']] = entry
            lay_list.append(entry)
        masters.append({'id': f'master-{mi}', 'name': mname if privacy == 'structural' else
                        (f'master#{short_hash(mname)}' if mname else None), 'part': mpart,
                        'background': _background(m.root), 'background_detail': _background_detail(m.root, resolver),
                        'text_styles': _master_text_styles(m.root, col),
                        'placeholders': [{'type': s['placeholder']['type'], 'idx': s['placeholder']['idx'],
                                          'box_px': s['box_px']} for s in m.shapes if s['placeholder']],
                        'static_shapes': [_static(s) for s in m.shapes if not s['placeholder'] and s['depth'] == 0],
                        'layouts': [x['id'] for x in lay_list], '_part': m})

    slides = []
    flags: Counter = Counter()
    image_use: dict[str, list[str]] = {}
    geometry_use: dict[tuple, list[int]] = {}
    sld_ids = pres.findall(f"{q('p:sldIdLst')}/{q('p:sldId')}")
    for order, sid in enumerate(sld_ids, start=1):
        rel = prels.get(sid.get(q('r:id'), ''))
        if rel is None:
            pkg.problems.append(f'slide {order}: relação ausente')
            continue
        sp = SlidePart(pkg, rel['target'], col, privacy)
        layout_rel = next((r for r in sp.rels.values() if r['type'] == 'slideLayout'), None)
        layout = layouts_by_part.get(layout_rel['target']) if layout_rel else None
        if layout:
            layout['used_by_slides'].append(order)
            _inherit_boxes(sp.shapes, layout, masters)
        hidden = sp.root is not None and sp.root.get('show') == '0'
        timing = sp.root is not None and sp.root.find(q('p:timing')) is not None and \
            any(True for _ in sp.root.find(q('p:timing')).iter(q('p:par')))
        transition = sp.root is not None and sp.root.find(q('p:transition')) is not None
        for k, v in sp.flags.items():
            flags[k] += v
        flags['hidden_slide'] += int(hidden)
        flags['animation'] += int(timing)
        flags['transition'] += int(transition)
        for s in sp.shapes:
            target = (s.get('image') or {}).get('target')
            if target:
                image_use.setdefault(target, []).append(f'slide {order}')
            if s['box_emu'] and s['depth'] == 0 and not s['placeholder']:
                geometry_use.setdefault((s['kind'], s.get('geometry'), s['box_emu']['x'], s['box_emu']['y'],
                                         s['box_emu']['cx'], s['box_emu']['cy']), []).append(order)
        kinds = Counter(s['kind'] for s in sp.shapes)
        texts = [s['text'] for s in sp.shapes if s.get('text')]
        notes = any(r['type'] == 'notesSlide' for r in sp.rels.values())
        comments = sum(1 for r in sp.rels.values() if 'comment' in r['type'].lower())
        slides.append({
            'order': order, 'slide_id': int(sid.get('id', 0)), 'part': rel['target'], 'hidden': hidden,
            'layout': None if layout is None else layout['id'], 'background': _background(sp.root),
            'background_detail': _background_detail(sp.root, resolver),
            'shape_counts': dict(sorted(kinds.items())),
            'placeholders': sorted({f"{s['placeholder']['type']}" for s in sp.shapes if s['placeholder']}),
            'text': {'characters': sum(t['characters'] for t in texts), 'paragraphs': sum(t['paragraphs'] for t in texts),
                     'numeric_like_shapes': sum(1 for t in texts if t['digit_ratio'] >= 0.3),
                     'fields': sorted({f for t in texts for f in t['fields']})},
            'charts': [s['chart'] for s in sp.shapes if s.get('chart')],
            'tables': [s['table'] for s in sp.shapes if s.get('table')],
            'images': [s['image'] for s in sp.shapes if s.get('image')],
            'shapes': sp.shapes,
            'animation': timing, 'transition': transition, 'has_notes': notes, 'comments': comments,
            'flags': dict(sorted(sp.flags.items())),
        })
    for m in masters:
        for s in m['_part'].shapes:
            if (s.get('image') or {}).get('target'):
                image_use.setdefault(s['image']['target'], []).append(m['id'])
        for k, v in m['_part'].flags.items():
            flags[k] += v
    for lay in layouts_by_part.values():
        for s in lay['_part'].shapes:
            if (s.get('image') or {}).get('target'):
                image_use.setdefault(s['image']['target'], []).append(lay['id'])

    media = {}
    for name in sorted(n for n in pkg.infos if n.startswith('ppt/media/')):
        media[name] = {**pkg.media_info(name), 'used_by': image_use.get(name, [])}
    media_ref = {name: (name if privacy == 'structural' else f'media-{i}') for i, name in enumerate(media, start=1)}
    for container in [*(s['shapes'] for s in slides), *(m['_part'].shapes for m in masters),
                      *(lay['_part'].shapes for lay in layouts_by_part.values())]:
        for shp in container:
            target = (shp.get('image') or {}).get('target')
            if target:
                shp['media_ref'] = media_ref.get(target)
    for lay in layouts_by_part.values():
        lay['static_shapes'] = [_static(x) for x in lay['_part'].shapes if not x['placeholder'] and x['depth'] == 0]
    for m in masters:
        m['static_shapes'] = [_static(x) for x in m['_part'].shapes if not x['placeholder'] and x['depth'] == 0]
    embedded_fonts = len(pres.findall(f"{q('p:embeddedFontLst')}/{q('p:embeddedFont')}"))
    flags['embedded_fonts'] += embedded_fonts
    flags['macros'] += int(any(n.lower().endswith('vbaproject.bin') for n in pkg.infos))
    media_where: dict[str, list[int]] = {}
    for name, info in media.items():
        if info.get('format') in ('emf', 'wmf', 'tif', 'tiff'):
            code = f'image_{info["format"]}'
            flags[code] += 1
            media_where.setdefault(code, []).extend(int(u.split()[1]) for u in info['used_by'] if u.startswith('slide '))

    ext_links = sum(1 for part in [*(s['part'] for s in slides)]
                    for r in pkg.rels(part).values() if r['external'])
    width_px, height_px = emu_px(cx), emu_px(cy)
    for s in slides:
        s['shapes'] = [_shape_out(x) for x in s['shapes']]
    report = {
        'tool': 'afrika-pptx-inspect', 'tool_version': TOOL_VERSION, 'privacy': privacy,
        'source': {'sha256': _file_sha256(path), 'size_bytes': path.stat().st_size,
                   'file_name': path.name if privacy == 'structural' else None,
                   'format': {'.pptx': 'pptx', '.potx': 'potx', '.pptm': 'pptm'}.get(path.suffix.lower(), path.suffix)},
        'presentation': {
            'slides': len(slides), 'hidden_slides': sum(1 for s in slides if s['hidden']),
            'size': {'emu': [cx, cy], 'inches': [round(cx / 914400, 3), round(cy / 914400, 3)] if cx else None,
                     'px_96dpi': [width_px, height_px], 'aspect_ratio': _ratio(cx, cy),
                     'type': None if sld_sz is None else sld_sz.get('type')},
            'masters': len(masters), 'layouts': len(layouts_by_part), 'embedded_fonts': embedded_fonts,
            'sections': len(list(pres.iter(q('p14:section')))),
            'notes_slides': sum(1 for n in pkg.infos if n.startswith('ppt/notesSlides/') and n.endswith('.xml')),
            'comment_parts': sum(1 for n in pkg.infos if n.startswith('ppt/comments/') and n.endswith('.xml')),
            'external_links': ext_links,
        },
        'theme': theme,
        'masters': [{k: v for k, v in m.items() if k != '_part'} for m in masters],
        'layouts': [{k: v for k, v in lay.items() if k != '_part'} for lay in layouts_by_part.values()],
        'slides': slides,
        'colors': {'theme_scheme': theme.get('colors', {}),
                   'srgb_used': [{'color': c, 'count': n} for c, n in col.srgb.most_common(40)],
                   'scheme_refs': dict(col.scheme.most_common())},
        'fonts': {'theme': tf, 'used': [{'font': f, 'count': n, 'web_safe': (f or '').lower() in SAFE_FONTS}
                                        for f, n in col.fonts.most_common(30) if f],
                  'sizes_pt': [{'size': s, 'count': n} for s, n in sorted(col.sizes.items())]},
        'media': [{'part': k if privacy == 'structural' else f'media-{i}', **v}
                  for i, (k, v) in enumerate(media.items(), start=1)],
        'reusable': _reusable(masters, layouts_by_part, media, geometry_use, len(slides), privacy),
        'not_directly_reproducible': _not_reproducible(flags, slides, media_where),
        'problems': pkg.problems,
    }
    return report


def _static(s: dict) -> dict:
    return {'kind': s['kind'], 'name': s['name'], 'box_px': s['box_px'], 'geometry': s.get('geometry'),
            'fill': s.get('fill'), 'fill_color': s.get('fill_color'), 'fill_alpha': s.get('fill_alpha'),
            'fill_gradient': s.get('fill_gradient'), 'custom_path': s.get('custom_path'), 'line_color': s.get('line_color'), 'image': bool(s.get('image')), 'media_ref': s.get('media_ref'),
            'rotation': s.get('rotation'),
            'has_text': bool(s.get('text') and s['text']['characters']),
            'text_style': (s.get('text') or {}).get('style')}


def _shape_out(s: dict) -> dict:
    keep = ('n', 'kind', 'name', 'depth', 'box_px', 'placeholder', 'geometry', 'custom_path', 'fill', 'fill_color',
            'fill_alpha', 'fill_gradient',
            'line', 'line_color', 'line_pt', 'effects', 'rotation', 'text', 'text_box', 'table', 'smartart', 'ole',
            'chartex', 'media', 'media_ref', 'hidden', 'has_alt_text', 'box_inherited')
    out = {k: s[k] for k in keep if k in s and s[k] not in (None, False, [])}
    if s.get('image'):
        out['image'] = {'external': s['image']['external'], 'cropped': s['image']['cropped'],
                        'vector': s['image'].get('vector', False)}
    if s.get('chart'):
        out['chart'] = {'kinds': [k['type'] for k in s['chart'].get('kinds', [])],
                        'series_colors': [c for k in s['chart'].get('kinds', []) for c in k.get('series_colors', [])],
                        'point_colors': [k.get('point_colors') for k in s['chart'].get('kinds', []) if k.get('point_colors')],
                        'legend_position': s['chart'].get('legend_position')}
    return out


def _inherit_boxes(shapes: list[dict], layout: dict, masters: list[dict]) -> None:
    """Placeholder sem xfrm herda a posição do layout (mesmo idx ou tipo) e, na falta, do master."""
    sources = [layout['placeholders'], *(m['placeholders'] for m in masters if layout['id'] in m['layouts'])]
    for s in shapes:
        if s['placeholder'] is None or s['box_px'] is not None:
            continue
        for src in sources:
            hit = next((p for p in src if p['box_px'] and p['idx'] is not None and p['idx'] == s['placeholder']['idx']),
                       None) or next((p for p in src if p['box_px'] and p['type'] == s['placeholder']['type']), None)
            if hit:
                s['box_px'] = hit['box_px']
                s['box_inherited'] = True
                break


def _reusable(masters: list[dict], layouts: dict, media: dict, geometry_use: dict, n_slides: int,
              privacy: Privacy) -> dict:
    repeated_images = [{'media': k if privacy == 'structural' else f'sha256:{v["sha256"][:12]}' if v['sha256'] else k,
                        'used_by': v['used_by'], 'pixels': v.get('pixels'), 'format': v.get('format')}
                       for k, v in media.items() if len(set(v['used_by'])) >= 2 or
                       any(u.startswith(('master', 'layout')) for u in v['used_by'])]
    repeated_shapes = [{'kind': k[0], 'geometry': k[1], 'box_px': _box_px({'x': k[2], 'y': k[3], 'cx': k[4], 'cy': k[5]}),
                        'slides': v} for k, v in geometry_use.items() if len(v) >= 2]
    placeholders = Counter(p['type'] for lay in layouts.values() for p in lay['placeholders'])
    return {
        'master_static_elements': [{'master': m['id'], **s} for m in masters for s in m['static_shapes']],
        'layout_static_elements': [{'layout': lay['id'], **s} for lay in layouts.values() for s in lay['static_shapes']],
        'repeated_images': repeated_images,
        'repeated_shapes_same_geometry': sorted(repeated_shapes, key=lambda r: -len(r['slides']))[:30],
        'placeholder_types': dict(placeholders.most_common()),
        'note': 'Elementos estáticos de master/layout e imagens repetidas são candidatos a tokens do tema (logos, '
                'faixas, fundos); placeholders title/body/ftr/sldNum/dt mapeiam para as regiões do tema.',
    }


_NR = {
    # código: (classe, descrição, tratamento sugerido)
    'smartart': ('not_reproducible', 'SmartArt', 'converter em formas/gráfico nativo ou imagem aprovada'),
    'ole_object': ('not_reproducible', 'Objeto OLE incorporado', 'substituir por tabela/gráfico nativo'),
    'video_or_audio': ('not_reproducible', 'Vídeo/áudio', 'fora do escopo do relatório estático'),
    'animation': ('not_reproducible', 'Animações', 'HTML/PPTX gerados são estáticos'),
    'transition': ('approximate', 'Transições de slide', 'podem ser reaplicadas no PPTX (F07); HTML sem transição'),
    'chartex': ('not_reproducible', 'Gráfico moderno (cascata/treemap/funil…)', 'sem equivalente na IR; definir alternativa'),
    'macros': ('not_reproducible', 'Macros VBA', 'nunca executadas nem copiadas'),
    'ink': ('not_reproducible', 'Tinta digital', 'remover ou converter em imagem aprovada'),
    'external_image': ('not_reproducible', 'Imagem vinculada externamente', 'não é baixada; incorporar o arquivo aprovado'),
    'embedded_fonts': ('approximate', 'Fontes incorporadas', 'verificar licença; instalar/servir como ativo local ou usar substituta'),
    'wordart_warp': ('approximate', 'WordArt (texto deformado)', 'sem equivalente CSS fiel; usar texto simples'),
    'effect_3d': ('approximate', 'Efeitos 3D', 'aproximar com 2D'),
    'effect': ('approximate', 'Sombra/brilho/reflexo/desfoque', 'CSS aproxima; PPTX nativo preserva'),
    'custom_geometry': ('approximate', 'Geometria personalizada', 'reproduzível como SVG/forma livre; conferir visualmente'),
    'gradient_fill': ('approximate', 'Preenchimento em gradiente', 'CSS/PPTX suportam; conferir paradas de cor'),
    'pattern_fill': ('approximate', 'Preenchimento com padrão', 'aproximação por textura CSS'),
    'image_fill': ('approximate', 'Forma preenchida com imagem', 'reproduzível como imagem recortada'),
    'image_emf': ('not_reproducible', 'Imagem EMF', 'converter para PNG/SVG aprovado (navegador não exibe EMF)'),
    'image_wmf': ('not_reproducible', 'Imagem WMF', 'converter para PNG/SVG aprovado'),
    'image_tif': ('not_reproducible', 'Imagem TIFF', 'converter para PNG'),
    'image_tiff': ('not_reproducible', 'Imagem TIFF', 'converter para PNG'),
    'vertical_text': ('approximate', 'Texto vertical', 'CSS writing-mode aproxima'),
    'rotation': ('approximate', 'Forma rotacionada', 'CSS transform; conferir alinhamento'),
    'hidden_slide': ('approximate', 'Slide oculto', 'decidir se entra no template'),
    'other_graphic': ('not_reproducible', 'Gráfico/objeto não reconhecido', 'avaliar manualmente'),
}


def _not_reproducible(flags: Counter, slides: list[dict], media_where: dict[str, list[int]]) -> list[dict]:
    out = []
    for code, n in sorted(flags.items()):
        if not n or code not in _NR:
            continue
        cls, label, how = _NR[code]
        where = [s['order'] for s in slides if s['flags'].get(code) or (code == 'animation' and s['animation'])
                 or (code == 'transition' and s['transition']) or (code == 'hidden_slide' and s['hidden'])]
        where = sorted(set(where) | set(media_where.get(code, [])))
        out.append({'code': code, 'class': cls, 'element': label, 'occurrences': n, 'slides': where,
                    'suggested_handling': how})
    out += [{'code': f'chart_{k}', 'class': cls, 'element': label, 'occurrences': n, 'slides': w,
             'suggested_handling': how} for k, cls, label, how, n, w in _chart_flags(slides) if n]
    return sorted(out, key=lambda x: (x['class'] != 'not_reproducible', x['code']))


def _chart_flags(slides: list[dict]):
    is3d = [s['order'] for s in slides for c in s['charts'] if c.get('is_3d')]
    linked = [s['order'] for s in slides for c in s['charts'] if c.get('linked_external_data')]
    embedded = [s['order'] for s in slides for c in s['charts'] if c.get('embedded_workbook')]
    return [
        ('3d', 'approximate', 'Gráfico 3D', 'reproduzir como 2D equivalente', len(is3d), is3d),
        ('linked_data', 'approximate', 'Gráfico com dados vinculados externos',
         'estrutura reproduzível; dados vêm SEMPRE dos snapshots aprovados', len(linked), linked),
        ('embedded_workbook', 'approximate', 'Gráfico com planilha incorporada',
         'planilha não é lida nem reaproveitada; dados vêm dos snapshots aprovados', len(embedded), embedded),
    ]


def _ratio(cx: int | None, cy: int | None) -> str | None:
    if not cx or not cy:
        return None
    for name, r in (('16:9', 16 / 9), ('16:10', 16 / 10), ('4:3', 4 / 3), ('A4', 297 / 210)):
        if abs(cx / cy - r) < 0.005:
            return name
    return f'{round(cx / cy, 4)}:1'


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fh:
        while chunk := fh.read(1 << 16):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- rascunho de tema e relatório legível

_DRAFT_COLORS = {'text.primary': 'dk1', 'surface': 'lt1', 'page': 'lt1', 'band': 'lt2', 'text.secondary': 'dk2',
                 'accent': 'accent1', 'series.1': 'accent1', 'series.2': 'accent2', 'series.3': 'accent3',
                 'series.4': 'accent4'}
_FAMILY = re.compile(r'^-?[A-Za-z0-9][A-Za-z0-9 _-]*$')


def theme_draft(report: dict) -> dict:
    """RASCUNHO de tema no esquema do motor a partir do relatório (cores/fontes do tema PPTX, tamanho do slide e
    placeholders do master). Não é aprovado nem instalado: serve de ponto de partida para revisão humana.
    Tokens sem equivalente no PPTX (severidade, grade, lacuna…) ficam com os valores neutros e vão para
    `needs_review`."""
    import copy

    from app.presentations import themes

    base = copy.deepcopy(themes.NEUTRAL_DEMO_V1)
    scheme = report['theme'].get('colors', {})
    colors, mapped = dict(base['colors']), {}
    for token, slot in _DRAFT_COLORS.items():
        if slot in scheme:
            colors[token] = scheme[slot]
            mapped[token] = slot
    fonts, font_notes = copy.deepcopy(base['fonts']), []
    for role, src in (('heading', 'major'), ('body', 'minor'), ('numeric', 'minor')):
        name = report['theme'].get('fonts', {}).get(src)
        if name and _FAMILY.match(name):
            fonts[role] = {'stack': [name, 'Arial', 'sans-serif'], 'export_family': name}
        elif name:
            font_notes.append(f'fonts.{role}: nome "{src}" com caracteres fora do permitido — revisar manualmente')
    size = report['presentation']['size']['px_96dpi']
    canvas = {'width': int(round(size[0])), 'height': int(round(size[1]))} if size and size[0] else base['canvas']
    layout = _draft_layout(report, canvas) or _scaled_flow(base['layout'], canvas)
    draft = {**base, 'name': f'Rascunho de tema (referência {report["source"]["sha256"][:8]})',
             'description': 'Gerado pela inspeção local de um PPTX de referência. NÃO aprovado.',
             'provisional': True, 'notice': 'Rascunho derivado de PPTX de referência — NÃO aprovado; revisar antes de usar.',
             'canvas': canvas, 'colors': colors, 'fonts': fonts, 'layout': layout}
    errors = []
    try:
        themes.ThemeDefinition.model_validate(draft)
    except Exception as exc:  # noqa: BLE001 — erros de validação viram lista para revisão
        errors = [str(e.get('msg')) for e in getattr(exc, 'errors', lambda: [{'msg': str(exc)}])()]
    return {'draft': draft, 'mapped_colors': mapped,
            'needs_review': sorted(set(themes.REQUIRED_COLORS) - set(mapped)) + font_notes
            + ['images/logos: enviar o arquivo aprovado como ativo local (POST /api/theme-assets) e referenciar'],
            'validation_errors': errors}


def _draft_layout(report: dict, canvas: dict) -> dict | None:
    if not report['masters']:
        return None
    phs = report['masters'][0]['placeholders']
    def box(kind: str):
        return next((p['box_px'] for p in phs if p['type'] == kind and p['box_px']), None)
    title, body = box('title'), box('body')
    foot = [p['box_px'] for p in phs if p['type'] in ('ftr', 'sldNum', 'dt') and p['box_px']]
    if not title or not body or not foot:
        return None
    clamp = lambda b: {'x': max(0.0, b['x']), 'y': max(0.0, b['y']),  # noqa: E731
                       'w': min(b['w'], canvas['width'] - max(0.0, b['x'])),
                       'h': min(b['h'], canvas['height'] - max(0.0, b['y']))}
    title, body = clamp(title), clamp(body)
    fx = min(b['x'] for b in foot)
    fw = max(b['x'] + b['w'] for b in foot) - fx
    ftop = min(b['y'] for b in foot)
    fbottom = max(b['y'] + b['h'] for b in foot)
    union = {'x': min(title['x'], body['x']), 'y': title['y'],
             'w': round(max(title['x'] + title['w'], body['x'] + body['w']) - min(title['x'], body['x']), 2),
             'h': round(body['y'] + body['h'] - title['y'], 2)}
    return {'mode': 'fixed', 'body': union, 'header': title, 'content': body,
            'footer': {'x': fx, 'w': round(fw, 2), 'bottom': round(max(0.0, canvas['height'] - fbottom), 2),
                       'reserve': round(fbottom - ftop, 2)}}


def _scaled_flow(layout: dict, canvas: dict) -> dict:
    sx, sy = canvas['width'] / 1280, canvas['height'] / 720
    b, f = layout['body'], layout['footer']
    return {**layout, 'body': {'x': b['x'] * sx, 'y': b['y'] * sy, 'w': b['w'] * sx, 'h': b['h'] * sy},
            'footer': {'x': f['x'] * sx, 'w': f['w'] * sx, 'bottom': f['bottom'] * sy, 'reserve': f['reserve'] * sy}}


def render_markdown(r: dict) -> str:
    pres, size = r['presentation'], r['presentation']['size']
    lines = [
        '# Inspeção técnica de PPTX de referência (local)', '',
        f'Ferramenta `{r["tool"]}` v{r["tool_version"]} · privacidade `{r["privacy"]}` · arquivo sha256 '
        f'`{r["source"]["sha256"][:16]}…` ({r["source"]["size_bytes"]} bytes, {r["source"]["format"]}).',
        '', '> Nenhum texto, valor de gráfico, célula, nota ou comentário do arquivo é copiado para este relatório.',
        '', '## Apresentação',
        f'- Slides: **{pres["slides"]}** (ocultos: {pres["hidden_slides"]}); masters: {pres["masters"]}; layouts: '
        f'{pres["layouts"]}; seções: {pres["sections"]}; notas: {pres["notes_slides"]}; comentários: {pres["comment_parts"]}',
        f'- Dimensões: {size["emu"][0]}×{size["emu"][1]} EMU = {size["inches"][0]}×{size["inches"][1]} pol = '
        f'{size["px_96dpi"][0]:g}×{size["px_96dpi"][1]:g} px (96 dpi) · proporção {size["aspect_ratio"]}',
        f'- Fontes incorporadas: {pres["embedded_fonts"]} · vínculos externos: {pres["external_links"]}',
        '', '## Tema (esquema do PPTX)',
        '| Slot | Cor |', '|---|---|', *[f'| {k} | `{v}` |' for k, v in r['theme'].get('colors', {}).items()],
        '', f'Fontes do tema: títulos `{r["theme"].get("fonts", {}).get("major")}`, corpo `{r["theme"].get("fonts", {}).get("minor")}`.',
        '', '## Masters e layouts',
    ]
    for m in r['masters']:
        lines.append(f'- **{m["id"]}** ({m["name"] or "sem nome"}): fundo {m["background"]}; estilos '
                     + ', '.join(f'{k} {v["size_pt"]}pt{" negrito" if v["bold"] else ""} {v["font"] or ""}'
                                 for k, v in m['text_styles'].items())
                     + f'; placeholders: {", ".join(p["type"] for p in m["placeholders"])}; elementos estáticos: '
                     f'{len(m["static_shapes"])}')
    for lay in r['layouts']:
        lines.append(f'  - {lay["id"]} ({lay["type"]}, {lay["name"] or "sem nome"}): placeholders '
                     f'{", ".join(p["type"] for p in lay["placeholders"]) or "—"}; usado nos slides '
                     f'{", ".join(map(str, lay["used_by_slides"])) or "—"}')
    lines += ['', '## Slides (ordem)', '| # | Layout | Oculto | Formas | Gráficos | Tabelas | Imagens | Texto (car.) | '
              'Campos numéricos | Animação |', '|---|---|---|---|---|---|---|---|---|---|']
    for s in r['slides']:
        shapes = ', '.join(f'{k}:{v}' for k, v in s['shape_counts'].items())
        charts = '; '.join('+'.join(k['type'] for k in c.get('kinds', [])) for c in s['charts']) or '—'
        tables = '; '.join(f"{t['rows']}×{t['columns']}" for t in s['tables']) or '—'
        lines.append(f'| {s["order"]} | {s["layout"]} | {"sim" if s["hidden"] else "não"} | {shapes} | {charts} | '
                     f'{tables} | {len(s["images"])} | {s["text"]["characters"]} | {s["text"]["numeric_like_shapes"]} | '
                     f'{"sim" if s["animation"] else "não"} |')
    lines += ['', '## Cores mais usadas', ', '.join(f'`{c["color"]}`×{c["count"]}' for c in r['colors']['srgb_used'][:15]) or '—',
              '', '## Fontes usadas', ', '.join(f'{f["font"]}×{f["count"]}{"" if f["web_safe"] else " (instalar/licenciar)"}'
                                               for f in r['fonts']['used']) or '—',
              'Tamanhos (pt): ' + (', '.join(f'{x["size"]:g}×{x["count"]}' for x in r['fonts']['sizes_pt']) or '—'),
              '', '## Mídia', *[f'- {m["part"]}: {m.get("format")} {m.get("pixels") or ""} {m["size_bytes"]} bytes, usado em '
                               f'{", ".join(m["used_by"]) or "—"}' for m in r['media']],
              '', '## Elementos reutilizáveis',
              f'- Estáticos de master: {len(r["reusable"]["master_static_elements"])}; de layout: '
              f'{len(r["reusable"]["layout_static_elements"])}; imagens repetidas/de master: {len(r["reusable"]["repeated_images"])}; '
              f'formas repetidas (mesma geometria): {len(r["reusable"]["repeated_shapes_same_geometry"])}',
              f'- Placeholders: {r["reusable"]["placeholder_types"]}', f'- {r["reusable"]["note"]}',
              '', '## Não reproduzíveis diretamente', '| Classe | Elemento | Ocorr. | Slides | Tratamento sugerido |',
              '|---|---|---|---|---|',
              *[f'| {x["class"]} | {x["element"]} | {x["occurrences"]} | {", ".join(map(str, x["slides"])) or "—"} | '
                f'{x["suggested_handling"]} |' for x in r['not_directly_reproducible']]]
    if r['problems']:
        lines += ['', '## Problemas na leitura', *[f'- {p}' for p in r['problems']]]
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------- wireframe (sem conteúdo)

def _css_fill(shape: dict) -> str:
    if shape.get('fill_color'):
        alpha = shape.get('fill_alpha')
        return f"background:{shape['fill_color']};" + (f'opacity:{alpha / 100:g};' if alpha is not None else '')
    grad = shape.get('fill_gradient') or {}
    stops = [s for s in grad.get('stops', []) if s.get('color')]
    if stops:
        angle = (grad.get('angle') or 0) + 90
        return 'background:linear-gradient({}deg,{});'.format(
            angle, ','.join(f"{s['color']} {s['pos']:g}%" for s in stops))
    return ''


def _wf_label(s: dict) -> str:
    parts = [f"#{s.get('n', '')} {s['kind']}"]
    if s.get('placeholder'):
        parts.append(f"ph:{s['placeholder']['type']}")
    if s.get('geometry') and s['geometry'] != 'rect':
        parts.append(s['geometry'])
    style = (s.get('text') or {}).get('style') or s.get('text_style')
    chars = (s.get('text') or {}).get('characters')
    if style and (chars or s.get('has_text')):
        parts.append('texto {}pt {} {}{}'.format('/'.join(f'{x:g}' for x in style['sizes_pt']) or '?',
                                                 '/'.join(style['fonts']) or '', ' '.join(style['colors']),
                                                 ' negrito' if style.get('bold_share', 0) > 0.5 else ''))
    if chars:
        parts.append(f'{chars} car.')
    if s.get('kind') == 'picture' or s.get('image'):
        parts.append(f"imagem {s.get('media_ref') or ''}")
    if s.get('chart'):
        parts.append('gráfico ' + '+'.join(s['chart'].get('kinds', [])) + ' ' +
                     ' '.join(c for c in s['chart'].get('series_colors', []) if c))
    if s.get('table'):
        t = s['table']
        parts.append(f"tabela {t['rows']}×{t['columns']} cab {t.get('header_fill')}")
    return ' · '.join(p for p in parts if p)


def wireframes_html(report: dict) -> str:
    """Página HTML com um wireframe por slide: caixas nas posições reais, cores de preenchimento/gradiente/linha e
    rótulos GENÉRICOS (tipo, placeholder, estilo de texto, nº de caracteres, referência anônima de imagem). Nenhum
    texto, imagem ou valor do arquivo é reproduzido."""
    import html
    w, h = report['presentation']['size']['px_96dpi']
    layouts = {lay['id']: lay for lay in report['layouts']}
    masters = report['masters']
    out = ['<!doctype html><meta charset="utf-8"><title>Wireframes (sem conteúdo)</title><style>',
           'body{margin:0;background:#888;font:12px/1.2 monospace}',
           f'.wf-slide{{position:relative;width:{w}px;height:{h}px;overflow:hidden;background:#fff;margin:0 0 24px}}',
           '.wf-box{position:absolute;box-sizing:border-box;border:1px dashed rgba(0,0,0,.45)}',
           '.wf-static{border-style:dotted;opacity:.85}',
           '.wf-pic{background:repeating-linear-gradient(45deg,#ddd 0 8px,#bbb 8px 16px)!important}',
           '.wf-lbl{position:absolute;left:2px;top:2px;max-width:calc(100% - 4px);background:rgba(255,255,255,.85);'
           'color:#000;padding:1px 3px;font-size:13px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}',
           '.wf-title{position:absolute;right:8px;bottom:8px;background:#000;color:#fff;padding:4px 8px;font-size:18px}',
           '</style>']

    def box(s: dict, static: bool) -> str:
        b = s.get('box_px')
        if not b:
            return ''
        cls = 'wf-box' + (' wf-static' if static else '') + (' wf-pic' if s.get('kind') == 'picture' else '')
        style = f"left:{b['x']}px;top:{b['y']}px;width:{b['w']}px;height:{b['h']}px;" + _css_fill(s)
        if s.get('line_color'):
            style += f"border:2px solid {s['line_color']};"
        if s.get('rotation'):
            style += f"transform:rotate({s['rotation']}deg);"
        return f'<div class="{cls}" style="{style}"><span class="wf-lbl">{html.escape(_wf_label(s))}</span></div>'

    def bg_css(detail: dict | None) -> str:
        if not detail:
            return ''
        if detail.get('color'):
            return f"background:{detail['color']};"
        return _css_fill({'fill_gradient': detail.get('gradient')}) if detail.get('gradient') else ''

    for s in report['slides']:
        lay = layouts.get(s['layout'] or '')
        master = next((m for m in masters if lay and lay['id'] in m['layouts']), masters[0] if masters else None)
        bg = (bg_css(s.get('background_detail')) or bg_css((lay or {}).get('background_detail'))
              or bg_css((master or {}).get('background_detail')))
        out.append(f'<div class="wf-slide" data-slide="{s["order"]}" style="{bg}">')
        for st in (master or {}).get('static_shapes', []):
            out.append(box(st, True))
        for st in (lay or {}).get('static_shapes', []):
            out.append(box(st, True))
        for sh in s['shapes']:
            out.append(box(sh, False))
        out.append(f'<span class="wf-title">slide {s["order"]} · {s["layout"]}{" · oculto" if s["hidden"] else ""}</span></div>')
    return '\n'.join(out) + '\n'
