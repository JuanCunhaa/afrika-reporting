"""PDF da exportação (F07): impressão do MESMO HTML da pré-visualização pelo Chromium, normalizada e validada.

- Normalização: as datas técnicas (/CreationDate, /ModDate) viram o momento de criação da revisão exportada, com o
  MESMO comprimento (offsets da tabela xref intactos) — o arquivo fica determinístico para a mesma revisão e motor.
- Validação estrutural (sem dependências novas): cabeçalho, %%EOF, startxref -> tabela xref, objetos, nº de páginas =
  nº de slides, MediaBox = canvas do tema (px × 0,75 pt), todas as fontes INCORPORADAS (FontFile2/3), famílias
  esperadas (sem fonte de reserva quando o tema usa fontes empacotadas) e ausência de JavaScript/ações/arquivos anexos.
"""
from __future__ import annotations

import re
from datetime import datetime

from app.export.errors import ExportError

_DATE = re.compile(rb'(/(?:CreationDate|ModDate)\s*\()([^)]*)(\))')


_NODE_ID = re.compile(rb'\(node(\d{8})\)')


def normalize(data: bytes, ts: datetime) -> bytes:
    """Datas técnicas = criação da revisão; identificadores da árvore de acessibilidade (PDF marcado: nº de nó do DOM,
    variável a cada execução) renumerados na ordem de aparição — mesmo comprimento, mapeamento consistente."""
    stamp = ts.strftime("D:%Y%m%d%H%M%S+00'00'").encode()

    def repl(m: re.Match) -> bytes:
        value = m.group(2)
        return m.group(1) + (stamp if len(stamp) == len(value) else value) + m.group(3)

    ids: dict[bytes, bytes] = {}

    def node(m: re.Match) -> bytes:
        new = ids.setdefault(m.group(1), f'{len(ids) + 1:08d}'.encode())
        return b'(node' + new + b')'

    return _NODE_ID.sub(node, _DATE.sub(repl, data))


def _objects(data: bytes) -> dict[int, bytes]:
    """Objetos indiretos via tabela xref clássica (o Skia/Chromium não usa object streams)."""
    m = re.search(rb'startxref\s+(\d+)\s+%%EOF\s*$', data[-2048:])
    if not m:
        raise ExportError('pdf_invalid', 'PDF sem startxref/%%EOF', status=500)
    pos = int(m.group(1))
    if data[pos:pos + 4] != b'xref':
        raise ExportError('pdf_invalid', 'startxref não aponta para a tabela xref', status=500)
    lines = data[pos:].split(b'\n')
    offsets: dict[int, int] = {}
    i = 1
    while i < len(lines):
        head = lines[i].strip().split()
        if len(head) != 2 or not all(h.isdigit() for h in head):
            break
        start, count = int(head[0]), int(head[1])
        for k in range(count):
            entry = lines[i + 1 + k].strip().split()
            if len(entry) >= 3 and entry[2] == b'n':
                offsets[start + k] = int(entry[0])
        i += 1 + count
    out = {}
    for num, off in offsets.items():
        end = data.find(b'endobj', off)
        if not data[off:off + 30].lstrip().startswith(f'{num} '.encode()) or end < 0:
            raise ExportError('pdf_invalid', f'xref aponta para objeto inexistente ({num})', status=500)
        out[num] = data[off:end]
    return out


def _font_families(name: bytes) -> str:
    base = name.split(b'+', 1)[-1].decode('latin-1')
    return re.sub(r'[-,].*$', '', base)


def validate(data: bytes, *, slides: int, canvas: dict, expected_families: set[str] | None) -> dict:
    if not data.startswith(b'%PDF-1.'):
        raise ExportError('pdf_invalid', 'Arquivo não começa com cabeçalho PDF', status=500)
    objs = _objects(data)
    pages = [o for o in objs.values() if re.search(rb'/Type\s*/Page(?![s\w])', o)]
    w, h = canvas['width'] * 0.75, canvas['height'] * 0.75
    boxes = []
    for o in pages:
        m = re.search(rb'/MediaBox\s*\[\s*([-\d.\s]+)\]', o)
        boxes.append([float(x) for x in m.group(1).split()] if m else None)
    problems = []
    if len(pages) != slides:
        problems.append(f'{len(pages)} páginas para {slides} slides')
    bad_box = [i + 1 for i, b in enumerate(boxes) if not b or abs(b[2] - b[0] - w) > 0.5 or abs(b[3] - b[1] - h) > 0.5]
    if bad_box:
        problems.append(f'páginas com tamanho diferente do canvas ({w:g}×{h:g} pt): {bad_box[:10]}')
    fonts, not_embedded = set(), []
    for num, o in objs.items():
        if re.search(rb'/Type\s*/Font\b', o) and not re.search(rb'/Subtype\s*/Type0', o):
            fd = re.search(rb'/FontDescriptor\s+(\d+)\s+0\s+R', o)
            desc = objs.get(int(fd.group(1)), b'') if fd else b''
            m = re.search(rb'/BaseFont\s*/([^\s/>\[]+)', o) or re.search(rb'/FontName\s*/([^\s/>\[]+)', desc)
            name = m.group(1) if m else b'?'
            # Type3: glifos desenhados como vetores DENTRO do PDF (ex.: texto com contorno "halo") — autocontido
            if not re.search(rb'/Subtype\s*/Type3', o) and not re.search(rb'/FontFile[23]?\s+\d+\s+0\s+R', desc):
                not_embedded.append(name.decode('latin-1'))
            fonts.add(_font_families(name))
    if not_embedded:
        problems.append(f'fontes NÃO incorporadas: {sorted(set(not_embedded))[:10]}')
    unexpected = sorted(f for f in fonts if expected_families is not None
                        and not any(f.replace(' ', '').lower().startswith(e.replace(' ', '').lower())
                                    for e in expected_families))
    if expected_families is not None and unexpected:
        problems.append(f'fontes fora do tema (reserva): {unexpected[:10]}')
    # F08: só a estrutura (dicionários) conta — bytes de fluxos comprimidos (fontes, imagens, conteúdo) podem formar
    # "/AA" por acaso e geravam falso positivo dependente do texto do slide.
    structure = re.sub(rb'stream\r?\n.*?endstream', b'', data, flags=re.S)
    active = [k.decode() for k in (b'/JavaScript', b'/JS', b'/Launch', b'/EmbeddedFile', b'/OpenAction', b'/AA')
              if re.search(re.escape(k) + rb'(?![A-Za-z])', structure)]
    if active:
        problems.append(f'conteúdo ativo não permitido: {active}')
    if problems:
        raise ExportError('pdf_invalid', 'PDF gerado não passou na validação estrutural', status=500,
                          details=[{'field': 'pdf', 'message': p, 'type': 'pdf_invalid'} for p in problems])
    return {'pages': len(pages), 'page_size_pt': [round(w, 2), round(h, 2)], 'objects': len(objs),
            'fonts': sorted(fonts), 'fonts_embedded': True, 'active_content': False}
