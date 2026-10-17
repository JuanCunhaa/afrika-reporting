"""Utilitários DrawingML para a exportação PPTX (F07): cores com alfa, preenchimentos, contornos, texto e geometria.

Tudo que o python-pptx não expõe (alfa, recuos de 0, entrelinha exata, marcadores, bordas de célula, `custGeom` com
curvas) é escrito aqui em XML, na ordem exigida pelo esquema OOXML (ECMA-376).
"""
from __future__ import annotations

import math
import re

from lxml import etree
from pptx.oxml.ns import qn

EMU_PER_PX = 9525


def emu(px: float) -> int:
    return int(round(px * EMU_PER_PX))


def hundredths_pt(px: float) -> int:
    """px CSS (96 dpi) -> centésimos de ponto (1 px = 0,75 pt)."""
    return int(round(px * 75))


def sub(parent, tag: str, **attrs):
    el = etree.SubElement(parent, qn(tag))
    for k, v in attrs.items():
        el.set(k, str(v))
    return el


def color_el(parent, color: dict, tag: str = 'a:srgbClr'):
    """<a:srgbClr val="RRGGBB"><a:alpha val="…"/></a:srgbClr> (alfa só quando < 1)."""
    c = sub(parent, tag, val=color['rgb'])
    if color.get('a', 1) < 0.999:
        sub(c, 'a:alpha', val=int(round(color['a'] * 100000)))
    return c


def solid_fill(parent, color: dict):
    f = sub(parent, 'a:solidFill')
    color_el(f, color)
    return f


def mix(color: dict, other: str, amount: float) -> dict:
    a = [int(color['rgb'][i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(other[i:i + 2], 16) for i in (0, 2, 4)]
    return {'rgb': ''.join(f'{round(x + (y - x) * amount):02X}' for x, y in zip(a, b)), 'a': color.get('a', 1)}


def replace_fill(sppr, fill: dict | None, texture: bool = False) -> None:
    """Preenchimento do spPr na posição do esquema (após a geometria, antes de ln)."""
    for tag in ('a:noFill', 'a:solidFill', 'a:gradFill', 'a:blipFill', 'a:pattFill', 'a:grpFill'):
        for el in sppr.findall(qn(tag)):
            sppr.remove(el)
    geom = sppr.find(qn('a:prstGeom'))
    if geom is None:
        geom = sppr.find(qn('a:custGeom'))
    if fill is None:
        el = etree.Element(qn('a:noFill'))
    elif texture:
        # textura da severidade "Desconhecida": padrão diagonal editável (aproximação da hachura do HTML)
        el = etree.Element(qn('a:pattFill'), prst='dkUpDiag')
        color_el(sub(el, 'a:fgClr'), mix(fill, 'FFFFFF', 0.45))
        color_el(sub(el, 'a:bgClr'), fill)
    else:
        el = etree.Element(qn('a:solidFill'))
        color_el(el, fill)
    geom.addnext(el)


DASH = {'solid': 'solid', 'dashed': 'dash', 'dotted': 'sysDot'}


def replace_line(sppr, line: dict | None, *, tail_arrow: bool = False) -> None:
    for el in sppr.findall(qn('a:ln')):
        sppr.remove(el)
    ln = etree.Element(qn('a:ln'))
    if line is None:
        sub(ln, 'a:noFill')
    else:
        ln.set('w', str(emu(line['w'])))
        ln.set('cap', 'rnd' if tail_arrow else 'flat')
        solid_fill(ln, line['color'])
        sub(ln, 'a:prstDash', val=DASH.get(line.get('style', 'solid'), 'solid'))
        sub(ln, 'a:round')
        if tail_arrow:
            sub(ln, 'a:tailEnd', type='arrow', w='med', len='med')
    # ln vem depois do preenchimento e antes de effectLst/scene3d/sp3d
    anchor = None
    for tag in ('a:noFill', 'a:solidFill', 'a:gradFill', 'a:blipFill', 'a:pattFill', 'a:grpFill', 'a:custGeom',
                'a:prstGeom', 'a:xfrm'):
        found = sppr.find(qn(tag))
        if found is not None:
            anchor = found
            break
    if anchor is None:
        sppr.insert(0, ln)
    else:
        anchor.addnext(ln)


def drop_style(el) -> None:
    """Remove `p:style` (referência ao tema do PowerPoint: sombra/linha implícitas) — formatação 100% explícita."""
    st = el.find(qn('p:style'))
    if st is not None:
        el.remove(st)


def set_descr(shape, name: str, descr: str | None) -> None:
    nv = shape._element.find('.//' + qn('p:cNvPr'))
    nv.set('name', name[:250])
    if descr:
        nv.set('descr', descr[:2000])


# ---------------------------------------------------------------- texto

def body_pr(txbody, *, wrap: bool, vertical: bool = False, anchor: str = 't', insets=(0, 0, 0, 0)):
    old = txbody.find(qn('a:bodyPr'))
    bp = etree.Element(qn('a:bodyPr'))
    if vertical:
        bp.set('vert', 'vert270')
    bp.set('wrap', 'square' if wrap else 'none')
    for k, v in zip(('lIns', 'tIns', 'rIns', 'bIns'), insets):
        bp.set(k, str(emu(v)))
    bp.set('rtlCol', '0')
    bp.set('anchor', anchor)
    sub(bp, 'a:noAutofit')
    if old is not None:
        old.addprevious(bp)
        txbody.remove(old)
    else:
        txbody.insert(0, bp)
    return bp


def write_paragraphs(txbody, paras: list[dict], face_of, *, lang: str = 'pt-BR', scale: float = 1.0) -> None:
    """Parágrafos/runs com fonte, tamanho, cor, espaçamento e entrelinha exatos do layout renderizado.
    `face_of(family, weight) -> (typeface, bold)`; `scale` reduz o tamanho (ajuste com limite mínimo)."""
    for p in txbody.findall(qn('a:p')):
        txbody.remove(p)
    if not paras:
        p = sub(txbody, 'a:p')
        sub(p, 'a:endParaRPr', lang=lang)
        return
    for para in paras:
        p = sub(txbody, 'a:p')
        ppr = sub(p, 'a:pPr', algn=para['align'], marL=emu(para.get('marL', 0)), indent=emu(para.get('indent', 0)))
        sub(sub(ppr, 'a:lnSpc'), 'a:spcPts', val=max(0, min(158400, hundredths_pt(para['lh'] * scale))))
        sub(sub(ppr, 'a:spcBef'), 'a:spcPts', val=0)
        sub(sub(ppr, 'a:spcAft'), 'a:spcPts', val=max(0, min(158400, hundredths_pt(para.get('after', 0) * scale))))
        bullet = para.get('bullet')
        if bullet:
            color_el(sub(ppr, 'a:buClr'), bullet['color'])
            sub(ppr, 'a:buSzPct', val=max(25000, min(400000, int(round(bullet.get('scale', 1) * 100000)))))
            # mesmo glifo do HTML: o marcador usa a fonte do próprio item (incorporada), não uma fonte de sistema
            sub(ppr, 'a:buFont', typeface=face_of(bullet.get('font') or 'Arial', bullet.get('weight', 400))[0])
            sub(ppr, 'a:buChar', char=bullet['char'])
        else:
            sub(ppr, 'a:buNone')
        last = None
        for run in para['runs']:
            for i, piece in enumerate(run['t'].split('\n')):
                if i > 0:
                    br = sub(p, 'a:br')
                    _rpr(br, run, face_of, lang, scale)
                if piece:
                    r = sub(p, 'a:r')
                    _rpr(r, run, face_of, lang, scale)
                    sub(r, 'a:t').text = piece
            last = run
        end = sub(p, 'a:endParaRPr', lang=lang)
        if last is not None:
            end.set('sz', str(max(100, hundredths_pt(last['size'] * scale))))


def _rpr(parent, run: dict, face_of, lang: str, scale: float):
    typeface, bold = face_of(run['font'], run['weight'])
    rpr = sub(parent, 'a:rPr', lang=lang, sz=max(100, min(400000, hundredths_pt(run['size'] * scale))),
              b=int(bold), i=int(bool(run.get('italic'))), kern=100, dirty='0')
    if run.get('spacing'):
        rpr.set('spc', str(hundredths_pt(run['spacing'] * scale)))
    if run.get('underline'):
        rpr.set('u', 'sng')
    solid_fill(rpr, run['color'])
    for tag in ('a:latin', 'a:ea', 'a:cs'):
        sub(rpr, tag, typeface=typeface)
    return rpr


# ---------------------------------------------------------------- geometria personalizada

_TOKEN = re.compile(r'[MmLlHhVvCcSsQqTtAaZz]|-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?')


def _arc_to_cubics(x1, y1, rx, ry, phi, large, sweep, x2, y2):
    """Arco elíptico SVG (parametrização por extremos) -> curvas de Bézier cúbicas (SVG 1.1, apêndice F.6)."""
    if rx == 0 or ry == 0:
        return [((x2, y2), None)]
    phi = math.radians(phi)
    cos, sin = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p, y1p = cos * dx + sin * dy, -sin * dx + cos * dy
    rx, ry = abs(rx), abs(ry)
    lam = (x1p ** 2) / (rx ** 2) + (y1p ** 2) / (ry ** 2)
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx ** 2 * ry ** 2 - rx ** 2 * y1p ** 2 - ry ** 2 * x1p ** 2
    den = rx ** 2 * y1p ** 2 + ry ** 2 * x1p ** 2
    coef = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        coef = -coef
    cxp, cyp = coef * rx * y1p / ry, -coef * ry * x1p / rx
    cx, cy = cos * cxp - sin * cyp + (x1 + x2) / 2, sin * cxp + cos * cyp + (y1 + y2) / 2

    def ang(ux, uy, vx, vy):
        return math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)

    t1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dt = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    n = max(1, math.ceil(abs(dt) / (math.pi / 2)))
    step = dt / n
    out = []
    k = 4 / 3 * math.tan(step / 4)
    for i in range(n):
        a1, a2 = t1 + i * step, t1 + (i + 1) * step
        p1 = (math.cos(a1) - k * math.sin(a1), math.sin(a1) + k * math.cos(a1))
        p2 = (math.cos(a2) + k * math.sin(a2), math.sin(a2) - k * math.cos(a2))
        p3 = (math.cos(a2), math.sin(a2))
        conv = []
        for px, py in (p1, p2, p3):
            ex, ey = rx * px, ry * py
            conv.append((cos * ex - sin * ey + cx, sin * ex + cos * ey + cy))
        out.append((conv[2], (conv[0], conv[1])))
    return out


def svg_path_segments(d: str) -> list[tuple]:
    """Caminho SVG -> segmentos absolutos: ('M', x, y) | ('L', x, y) | ('C', x1, y1, x2, y2, x, y) | ('Q', …) | ('Z',)."""
    tokens = _TOKEN.findall(d)
    out: list[tuple] = []
    i, cmd = 0, None
    x = y = sx = sy = 0.0
    prev_c = None

    def num():
        nonlocal i
        v = float(tokens[i])
        i += 1
        return v

    while i < len(tokens):
        if re.fullmatch(r'[A-Za-z]', tokens[i]):
            cmd = tokens[i]
            i += 1
            if cmd in 'Zz':
                out.append(('Z',))
                x, y = sx, sy
                continue
        if cmd is None:
            raise ValueError('caminho SVG sem comando inicial')
        rel = cmd.islower()
        c = cmd.upper()
        if c == 'M':
            nx, ny = num(), num()
            x, y = (x + nx, y + ny) if rel else (nx, ny)
            sx, sy = x, y
            out.append(('M', x, y))
            cmd = 'l' if rel else 'L'
        elif c == 'L':
            nx, ny = num(), num()
            x, y = (x + nx, y + ny) if rel else (nx, ny)
            out.append(('L', x, y))
        elif c == 'H':
            nx = num()
            x = x + nx if rel else nx
            out.append(('L', x, y))
        elif c == 'V':
            ny = num()
            y = y + ny if rel else ny
            out.append(('L', x, y))
        elif c == 'C':
            v = [num() for _ in range(6)]
            if rel:
                v = [v[0] + x, v[1] + y, v[2] + x, v[3] + y, v[4] + x, v[5] + y]
            out.append(('C', *v))
            prev_c = (v[2], v[3])
            x, y = v[4], v[5]
            continue
        elif c == 'S':
            v = [num() for _ in range(4)]
            if rel:
                v = [v[0] + x, v[1] + y, v[2] + x, v[3] + y]
            c1 = (2 * x - prev_c[0], 2 * y - prev_c[1]) if prev_c else (x, y)
            out.append(('C', c1[0], c1[1], *v))
            prev_c = (v[0], v[1])
            x, y = v[2], v[3]
            continue
        elif c == 'Q':
            v = [num() for _ in range(4)]
            if rel:
                v = [v[0] + x, v[1] + y, v[2] + x, v[3] + y]
            out.append(('Q', *v))
            x, y = v[2], v[3]
        elif c == 'A':
            rx, ry, phi, large, sweep, nx, ny = (num() for _ in range(7))
            if rel:
                nx, ny = nx + x, ny + y
            for end, ctrl in _arc_to_cubics(x, y, rx, ry, phi, int(large), int(sweep), nx, ny):
                out.append(('C', *ctrl[0], *ctrl[1], *end) if ctrl else ('L', *end))
            x, y = nx, ny
        else:
            raise ValueError(f'comando SVG não suportado: {cmd}')
        prev_c = None
    return out


def cust_geom(sppr, segments: list[tuple], vw: float, vh: float, scale: int = 100) -> None:
    """Substitui a geometria do spPr por `a:custGeom` (caminho em unidades do viewBox × `scale`, esticado na caixa)."""
    for tag in ('a:prstGeom', 'a:custGeom'):
        old = sppr.find(qn(tag))
        if old is not None:
            sppr.remove(old)
    geom = etree.Element(qn('a:custGeom'))
    for tag in ('a:avLst', 'a:gdLst', 'a:ahLst', 'a:cxnLst'):
        sub(geom, tag)
    sub(geom, 'a:rect', l='0', t='0', r='r', b='b')
    path = sub(sub(geom, 'a:pathLst'), 'a:path', w=int(round(vw * scale)), h=int(round(vh * scale)))

    def pt(parent, px_, py_):
        sub(parent, 'a:pt', x=int(round(px_ * scale)), y=int(round(py_ * scale)))

    for seg in segments:
        kind = seg[0]
        if kind == 'M':
            pt(sub(path, 'a:moveTo'), seg[1], seg[2])
        elif kind == 'L':
            pt(sub(path, 'a:lnTo'), seg[1], seg[2])
        elif kind == 'C':
            el = sub(path, 'a:cubicBezTo')
            for j in (1, 3, 5):
                pt(el, seg[j], seg[j + 1])
        elif kind == 'Q':
            el = sub(path, 'a:quadBezTo')
            for j in (1, 3):
                pt(el, seg[j], seg[j + 1])
        elif kind == 'Z':
            sub(path, 'a:close')
    xfrm = sppr.find(qn('a:xfrm'))
    if xfrm is not None:
        xfrm.addnext(geom)
    else:
        sppr.insert(0, geom)


def rounded_rect_segments(w: float, h: float, r: list[float]) -> list[tuple]:
    """Retângulo com raio por canto (sup-esq, sup-dir, inf-dir, inf-esq) em cúbicas (k = 0,5523)."""
    k = 0.5523
    tl, tr, br, bl = (max(0.0, min(v, w / 2, h / 2)) for v in r)
    segs: list[tuple] = [('M', tl, 0), ('L', w - tr, 0)]
    if tr:
        segs.append(('C', w - tr + tr * k, 0, w, tr - tr * k, w, tr))
    segs.append(('L', w, h - br))
    if br:
        segs.append(('C', w, h - br + br * k, w - br + br * k, h, w - br, h))
    segs.append(('L', bl, h))
    if bl:
        segs.append(('C', bl - bl * k, h, 0, h - bl + bl * k, 0, h - bl))
    segs.append(('L', 0, tl))
    if tl:
        segs.append(('C', 0, tl - tl * k, tl - tl * k, 0, tl, 0))
    segs.append(('Z',))
    return segs
