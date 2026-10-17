"""F07 — grava as fontes LIVRES (SIL OFL 1.1) empacotadas no build do frontend como TrueType, para a medição LOCAL de
fidelidade (o PowerPoint desta máquina não aplica fontes incorporadas; `render_pptx.ps1 -FontsDir` as registra só
durante a renderização e remove em seguida). Saída fora do Git (output/, private/ ou fora do repositório).

Uso (a partir da raiz):  python scripts/export_fonts.py output/export-fidelity/fonts
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from app.cli import safe_output_dir  # noqa: E402
from app.export import fonts, renderer  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    out = safe_output_dir(argv[0], '')
    out.mkdir(parents=True, exist_ok=True)
    book = fonts.FontBook(renderer.locate().dist)
    for (family, weight), path in sorted(book.files.items()):
        target, data = out / f'{family}-{weight}.ttf', fonts.woff_to_sfnt(path.read_bytes())
        # idêntico ao existente: não regrava (o Windows bloqueia a escrita de fonte ainda carregada por um processo)
        if not (target.is_file() and target.read_bytes() == data):
            target.write_bytes(data)
    print(f'{len(book.files)} fontes OFL em {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
