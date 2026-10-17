"""Renderizador HTML usado pela exportação: o build do frontend (`frontend/dist`), conferido contra o código-fonte.

- O PPTX e o PDF saem da rota `#/render` do MESMO renderizador da pré-visualização. Para não exportar com um build
  antigo, o build grava `dist/afrika-render.json` (hash do código-fonte, `frontend/render-stamp.mjs`) e aqui o mesmo
  hash é recalculado sobre `frontend/` — divergência => exportação recusada (`renderer_stale`), com a instrução de
  rodar `npm run build`.
- Sem `frontend/src` (ex.: instalação só com o build), a conferência é registrada como não aplicável.
- `AFRIKA_RENDERER_DIST` permite apontar outro build (caminho absoluto; nunca vem do frontend/requisição).
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from app.db import REPO_ROOT
from app.export.errors import ExportError

DIST_ENV = 'AFRIKA_RENDERER_DIST'
STAMP_FILE = 'afrika-render.json'
STAMP_INPUTS = ('src', 'index.html', 'package-lock.json', 'vite.config.ts', 'tsconfig.json')  # = render-stamp.mjs


@dataclass(frozen=True)
class Renderer:
    dist: Path
    source_hash: str
    stamp_check: str  # 'match' | 'not_applicable'


def source_hash(frontend: Path) -> tuple[str, int]:
    """Mesmo algoritmo de `frontend/render-stamp.mjs`."""
    files: list[str] = []
    for name in STAMP_INPUTS:
        p = frontend / name
        if p.is_dir():
            files += [f.relative_to(frontend).as_posix() for f in p.rglob('*') if f.is_file()]
        elif p.is_file():
            files.append(name)
    files.sort()
    h = hashlib.sha256()
    for f in files:
        h.update(f'{f}\0{hashlib.sha256((frontend / f).read_bytes()).hexdigest()}\n'.encode())
    return h.hexdigest(), len(files)


def locate(environ: dict | None = None) -> Renderer:
    env = os.environ if environ is None else environ
    configured = env.get(DIST_ENV)
    dist = Path(configured) if configured else REPO_ROOT / 'frontend' / 'dist'
    if configured and not dist.is_absolute():
        raise ExportError('renderer_missing', f'{DIST_ENV} precisa ser um caminho absoluto', status=503)
    stamp_path = dist / STAMP_FILE
    if not (dist / 'index.html').is_file() or not stamp_path.is_file():
        raise ExportError('renderer_missing', 'Build do renderizador ausente: execute "npm run build" em frontend/ '
                                              '(a exportação usa o mesmo renderizador da pré-visualização).', status=503)
    try:
        stamp = json.loads(stamp_path.read_text(encoding='utf-8'))
        built = str(stamp['source_hash'])
    except (ValueError, KeyError, TypeError):
        raise ExportError('renderer_missing', 'Carimbo do build do renderizador ilegível: refaça o build.',
                          status=503) from None
    frontend = dist.parent
    if not configured and (frontend / 'src').is_dir():
        current, _ = source_hash(frontend)
        if current != built:
            raise ExportError('renderer_stale', 'O build do renderizador está desatualizado em relação ao código da '
                                                'pré-visualização: execute "npm run build" em frontend/ e tente de novo.',
                              status=503)
        return Renderer(dist.resolve(), built, 'match')
    return Renderer(dist.resolve(), built, 'not_applicable')
