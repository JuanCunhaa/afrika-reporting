"""Ativos visuais AUTORIZADOS em pasta local fora do Git (F06C): logotipos, fotos, ilustrações e ícones da marca.

- Pasta: `AFRIKA_BRAND_ASSET_DIR` ou `data/brand-assets/` na raiz do repositório (`data/` é ignorado pelo Git).
  Estrutura: `<pasta>/<tema>/<encaixe>.<png|jpg|jpeg|svg>` — o tema declara os encaixes (`asset_slots`: nome, caixa,
  slides) e a pasta fornece (ou não) os arquivos. Nada é copiado para o repositório nem para o banco.
- Mesmas regras dos ativos de tema (`assets.py`): tipo pela ASSINATURA dos bytes, SVG sanitizado (sem script,
  entidades, eventos ou referências externas), limite de 5 MB. Arquivo inválido é ignorado (aviso) e nunca servido.
- Ausente => fallback NEUTRO: o encaixe fica vazio e aparece o que está por baixo (formas do tema). Nunca bloqueia
  dados nem a apresentação.
- Nada sai da máquina: o servidor local lê do disco e serve ao navegador local com CSP restritiva. Não enviar estes
  arquivos a serviços externos (inclusive de IA).
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from app.db import REPO_ROOT
from app.errors import ApiError
from app.presentations import assets

BRAND_DIR_ENV = 'AFRIKA_BRAND_ASSET_DIR'
EXTENSIONS = ('png', 'jpg', 'jpeg', 'svg')
IMAGE_MEDIA = ('image/png', 'image/jpeg', 'image/svg+xml')
_SLUG = re.compile(r'^[a-z0-9][a-z0-9-]{0,59}$')
_CACHE: dict[tuple[str, int, int], dict] = {}  # (caminho, mtime_ns, tamanho) -> resultado (evita re-hash a cada vista)


def brand_dir() -> Path:
    return Path(os.getenv(BRAND_DIR_ENV) or REPO_ROOT / 'data' / 'brand-assets')


def _file(theme_id: str, slot: str) -> Path | None:
    if not (_SLUG.match(theme_id) and _SLUG.match(slot)):  # nomes validados: sem separadores nem '..'
        return None
    base = brand_dir().resolve()
    for ext in EXTENSIONS:
        p = base / theme_id / f'{slot}.{ext}'
        if p.is_file():
            real = p.resolve()
            return real if real.is_relative_to(base) else None  # link para fora da pasta: ignorado
    return None


def _inspect(path: Path) -> dict:
    st = path.stat()
    key = (str(path), st.st_mtime_ns, st.st_size)
    if key in _CACHE:
        return _CACHE[key]
    if st.st_size == 0 or st.st_size > assets.MAX_ASSET_BYTES:
        out = {'status': 'invalid', 'message': 'arquivo vazio ou maior que 5 MB'}
    else:
        data = path.read_bytes()
        try:
            media = assets.detect(data)
        except ApiError as exc:
            media, out = None, {'status': 'invalid', 'message': exc.message}
        if media is not None:
            out = ({'status': 'available', 'media_type': media, 'sha256': hashlib.sha256(data).hexdigest(),
                    'size_bytes': len(data)} if media in IMAGE_MEDIA
                   else {'status': 'invalid', 'message': 'encaixe aceita só imagem (PNG, JPEG ou SVG)'})
    _CACHE[key] = out
    return out


def resolve(theme_id: str, slot: str) -> dict:
    """Situação de um encaixe: `available` (com tipo e SHA-256), `missing` (fallback neutro) ou `invalid` (ignorado)."""
    path = _file(theme_id, slot)
    info = {'status': 'missing'} if path is None else _inspect(path)
    out = {'slot': slot, **info}
    if info['status'] == 'available':
        out['url'] = f'/api/brand-assets/{theme_id}/{slot}?v={info["sha256"][:16]}'
    return out


def status(theme_id: str, slots: list[str]) -> dict[str, dict]:
    return {s: resolve(theme_id, s) for s in slots}


def read(theme_id: str, slot: str) -> tuple[bytes, str, str]:
    """(bytes, tipo, sha256) de um encaixe disponível; revalida o conteúdo lido (arquivo trocado entre chamadas)."""
    path = _file(theme_id, slot)
    if path is None:
        raise ApiError(404, 'brand_asset_not_found', 'Ativo local não encontrado (encaixe vazio: fallback neutro)')
    data = path.read_bytes()
    if not data or len(data) > assets.MAX_ASSET_BYTES:
        raise ApiError(404, 'brand_asset_not_found', 'Ativo local inválido')
    try:
        media = assets.detect(data)
    except ApiError:
        raise ApiError(404, 'brand_asset_not_found', 'Ativo local inválido') from None
    if media not in IMAGE_MEDIA:
        raise ApiError(404, 'brand_asset_not_found', 'Ativo local inválido')
    return data, media, hashlib.sha256(data).hexdigest()
