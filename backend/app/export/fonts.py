"""Fontes na exportação PPTX (F07): nome da face no PowerPoint e incorporação das fontes LIVRES (SIL OFL 1.1) do tema.

- O HTML usa família + peso CSS (ex.: Montserrat 900). O PowerPoint identifica faces pelo nome de família "legado"
  (name ID 1): pesos fora de normal/negrito viram famílias próprias ("Montserrat Black", "Poppins SemiBold"). As fontes
  empacotadas no frontend (@fontsource, subconjunto latino) já trazem exatamente esses nomes.
- Incorporação: os WOFF do build (`dist/assets/<familia>-latin-<peso>-normal-*.woff`) são convertidos para TrueType
  (só biblioteca padrão: zlib por tabela) e embalados como EOT ("Embedded OpenType", sem compressão nem XOR) — o
  formato que o PowerPoint usa em `ppt/fonts/*.fntdata`. Só faces efetivamente usadas no deck; só fontes com
  incorporação permitida (`fsType` instalável/editável). A OFL permite incorporar em documentos.
- Família sem arquivo local (fonte de sistema do tema) => só o nome é gravado (o PowerPoint usa a fonte instalada).
"""
from __future__ import annotations

import re
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

WEIGHT_NAMES = {100: 'Thin', 200: 'ExtraLight', 300: 'Light', 500: 'Medium', 600: 'SemiBold', 800: 'ExtraBold',
                900: 'Black'}


def _slug(family: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', family.lower()).strip('-')


def _weight(w: float) -> int:
    return max(100, min(900, int(round(w / 100.0)) * 100))


@dataclass(frozen=True)
class Face:
    typeface: str  # nome no PowerPoint (latin typeface)
    bold: bool
    file_weight: int  # peso do arquivo que contém a face
    family: str  # família CSS


class FontBook:
    """Faces disponíveis nos arquivos do build (`dist/assets`) e conversão de família/peso CSS -> face do PowerPoint."""

    def __init__(self, dist: Path | None):
        self.files: dict[tuple[str, int], Path] = {}
        if dist is not None and (dist / 'assets').is_dir():
            for f in sorted((dist / 'assets').glob('*-latin-*-normal-*.woff')):
                m = re.match(r'^(?P<fam>[a-z0-9-]+?)-latin-(?P<w>\d{3})-normal-', f.name)
                if m and '-latin-ext-' not in f.name:
                    self.files.setdefault((m.group('fam'), int(m.group('w'))), f)

    def bundled(self, family: str) -> bool:
        return any(k[0] == _slug(family) for k in self.files)

    def face(self, family: str, weight: float) -> Face:
        w = _weight(weight)
        if not self.bundled(family):  # fonte de sistema: nome + negrito (o PowerPoint usa a instalada)
            return Face(family, w >= 600, w, family)
        if w == 400 or w == 700:
            return Face(family, w == 700, w, family)
        return Face(f'{family} {WEIGHT_NAMES[w]}', False, w, family)

    def file_for(self, face: Face) -> Path | None:
        return self.files.get((_slug(face.family), face.file_weight))

    def file_for_typeface(self, typeface: str, bold: bool) -> Path | None:
        """Arquivo da face do PowerPoint ("Montserrat Black" => Montserrat 900; "Poppins" negrito => 700)."""
        for w, name in WEIGHT_NAMES.items():
            if typeface.endswith(f' {name}') and self.bundled(typeface[:-len(name) - 1]):
                return None if bold else self.files.get((_slug(typeface[:-len(name) - 1]), w))
        if not self.bundled(typeface):
            return None
        return self.files.get((_slug(typeface), 700 if bold else 400))


# ---------------------------------------------------------------- WOFF -> TrueType -> EOT

def woff_to_sfnt(data: bytes) -> bytes:
    sig, flavor, _length, num, _res, _total, _maj, _min, *_rest = struct.unpack('>4sIIHHIHHIIIII', data[:44])
    if sig != b'wOFF':
        raise ValueError('não é WOFF 1.0')
    tables = []
    for i in range(num):
        tag, off, comp, orig, checksum = struct.unpack('>4sIIII', data[44 + i * 20:64 + i * 20])
        raw = data[off:off + comp]
        body = zlib.decompress(raw) if comp != orig else raw
        if len(body) != orig:
            raise ValueError('tabela WOFF corrompida')
        tables.append((tag, checksum, body))
    tables.sort(key=lambda t: t[0])
    entry = max(i for i in range(16) if 2 ** i <= num)
    search = 2 ** entry * 16
    header = struct.pack('>IHHHH', flavor, num, search, entry, num * 16 - search)
    offset = 12 + 16 * num
    directory, blobs, head_at = b'', b'', None
    for tag, checksum, body in tables:
        if tag == b'head':  # checkSumAdjustment recalculado abaixo (offsets mudaram)
            body = body[:8] + b'\0\0\0\0' + body[12:]
            head_at = offset
        directory += struct.pack('>4sIII', tag, checksum, offset, len(body))
        pad = body + b'\0' * (-len(body) % 4)
        blobs += pad
        offset += len(pad)
    font = bytearray(header + directory + blobs)
    if head_at is not None:
        total = sum(struct.unpack(f'>{len(font) // 4}I', bytes(font))) & 0xFFFFFFFF
        font[head_at + 8:head_at + 12] = struct.pack('>I', (0xB1B0AFBA - total) & 0xFFFFFFFF)
    return bytes(font)


def _tables(sfnt: bytes) -> dict[bytes, bytes]:
    num = struct.unpack('>H', sfnt[4:6])[0]
    out = {}
    for i in range(num):
        tag, _cs, off, length = struct.unpack('>4sIII', sfnt[12 + i * 16:28 + i * 16])
        out[tag] = sfnt[off:off + length]
    return out


def _names(name: bytes) -> dict[int, str]:
    _fmt, count, start = struct.unpack('>HHH', name[:6])
    out: dict[int, str] = {}
    for i in range(count):
        pid, eid, lid, nid, length, off = struct.unpack('>HHHHHH', name[6 + i * 12:18 + i * 12])
        if pid == 3 and eid in (0, 1) and lid == 0x409:
            out[nid] = name[start + off:start + off + length].decode('utf-16-be', errors='replace')
    return out


def info(sfnt: bytes) -> dict:
    t = _tables(sfnt)
    os2, head = t[b'OS/2'], t[b'head']
    n = _names(t[b'name'])
    return {'family': n.get(1, ''), 'style': n.get(2, ''), 'full': n.get(4, ''), 'version': n.get(5, ''),
            'weight': struct.unpack('>H', os2[4:6])[0], 'fs_type': struct.unpack('>H', os2[8:10])[0],
            'italic': bool(struct.unpack('>H', os2[62:64])[0] & 1)}


def embeddable(fs_type: int) -> bool:
    """fsType: 0 instalável; bit 1 (0x2) restrito => não incorpora; bits 2/3 (visualização/edição) permitem."""
    return not (fs_type & 0x0002) or bool(fs_type & 0x000C)


def to_eot(sfnt: bytes) -> bytes:
    """EOT versão 2.2 SEM compressão (MTX) nem XOR, no mesmo leiaute que o PowerPoint grava ao incorporar fontes
    (conferido num `.fntdata` gerado pelo próprio PowerPoint): família e estilo terminados em NUL, charset 0,
    itálico 0/0xFF, RootString vazia (checksum 0x50475342), EUDCCodePage 1252, sem assinatura nem EUDC."""
    t = _tables(sfnt)
    os2, head = t[b'OS/2'], t[b'head']
    n = _names(t[b'name'])

    def s(v: str) -> bytes:
        b = v.encode('utf-16-le')
        return struct.pack('<H', len(b)) + b

    panose = os2[32:42]
    u1, u2, u3, u4 = struct.unpack('>IIII', os2[42:58])
    cp1, cp2 = struct.unpack('>II', os2[78:86]) if len(os2) >= 86 else (1, 0)
    italic = 0xFF if struct.unpack('>H', os2[62:64])[0] & 1 else 0
    fixed = struct.pack('<10sBBIHH', panose, 0, italic, struct.unpack('>H', os2[4:6])[0],
                        struct.unpack('>H', os2[8:10])[0], 0x504C)
    fixed += struct.pack('<IIIIII', u1, u2, u3, u4, cp1, cp2)
    fixed += struct.pack('<I', struct.unpack('>I', head[8:12])[0]) + b'\0' * 16
    names = (b'\0\0' + s(n.get(1, '') + '\0') + b'\0\0' + s(n.get(2, '') + '\0') + b'\0\0' + s(n.get(5, ''))
             + b'\0\0' + s(n.get(4, '')))
    v21 = b'\0\0' + struct.pack('<H', 0)  # Padding5 + RootStringSize (sem RootString)
    v22 = struct.pack('<IIHH', 0x50475342, 1252, 0, 0) + struct.pack('<II', 0, 0)  # checksum, EUDC, sem assinatura
    body = struct.pack('<III', len(sfnt), 0x00020002, 0) + fixed + names + v21 + v22
    total = 4 + len(body) + len(sfnt)
    return struct.pack('<I', total) + body + sfnt
