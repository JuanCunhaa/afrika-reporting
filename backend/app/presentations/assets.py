"""Ativos de tema (F06B.1): logotipos, imagens de fundo e arquivos de fonte, guardados LOCALMENTE e fora do Git.

- Diretório: `AFRIKA_ASSET_DIR` ou `data/theme-assets/` na raiz do repositório (`data/` é ignorado pelo Git).
  Recursos proprietários (logos/fontes do template oficial) nunca entram no repositório: o tema guarda só a referência
  `{asset_id: sha256, media_type}`.
- Endereçamento por conteúdo (SHA-256): o mesmo arquivo gera o mesmo id; nada é sobrescrito.
- Tipo detectado pela ASSINATURA dos bytes (não pela extensão nem pelo cabeçalho enviado). SVG só se for XML bem
  formado, sem DOCTYPE/entidades, scripts, `foreignObject`, manipuladores `on*` ou referências externas.
- Sem metadados pessoais: o nome original do arquivo não é guardado.
"""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from app.db import REPO_ROOT
from app.errors import ApiError

ASSET_DIR_ENV = 'AFRIKA_ASSET_DIR'
MAX_ASSET_BYTES = 5 * 1024 * 1024
EXT = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/svg+xml': 'svg', 'font/woff2': 'woff2', 'font/woff': 'woff',
       'font/ttf': 'ttf', 'font/otf': 'otf'}
_ID = re.compile(r'^[0-9a-f]{64}$')
_SVG_FORBIDDEN = {'script', 'foreignobject', 'iframe', 'embed', 'object', 'audio', 'video', 'animate', 'set',
                  'handler', 'listener'}


def asset_dir() -> Path:
    return Path(os.getenv(ASSET_DIR_ENV) or REPO_ROOT / 'data' / 'theme-assets')


def _invalid(message: str) -> ApiError:
    return ApiError(422, 'invalid_asset', message, [{'field': 'asset', 'message': message, 'type': 'invalid_asset'}])


def _check_svg(data: bytes) -> None:
    head = data[:4096].lower()
    if b'<!doctype' in head or b'<!entity' in data.lower():
        raise _invalid('SVG com DOCTYPE/entidades não é aceito')
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise _invalid('SVG malformado') from None
    if root.tag.rsplit('}', 1)[-1].lower() != 'svg':
        raise _invalid('Raiz do SVG deve ser <svg>')
    for el in root.iter():
        tag = el.tag.rsplit('}', 1)[-1].lower() if isinstance(el.tag, str) else ''
        if tag in _SVG_FORBIDDEN:
            raise _invalid(f'Elemento <{tag}> não é aceito em SVG de tema')
        for name, value in el.attrib.items():
            local = name.rsplit('}', 1)[-1].lower()
            if local.startswith('on'):
                raise _invalid('Atributos de evento (on*) não são aceitos em SVG de tema')
            v = value.strip().lower()
            if local == 'href' and not (v.startswith('#') or v.startswith('data:image/png') or
                                        v.startswith('data:image/jpeg')):
                raise _invalid('Referências externas não são aceitas em SVG de tema')
            external_url = any(not m.group(1).strip().strip('\'"').startswith('#')
                               for m in re.finditer(r'url\(([^)]*)\)', v))
            if 'javascript:' in v or external_url or '@import' in v:
                raise _invalid('Referências externas não são aceitas em SVG de tema')
        if tag == 'style' and el.text and ('@import' in el.text.lower() or re.search(r'url\(\s*[^#\s)]', el.text)):
            raise _invalid('CSS com importação/URL externa não é aceito em SVG de tema')


def detect(data: bytes) -> str:
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith(b'wOF2'):
        return 'font/woff2'
    if data.startswith(b'wOFF'):
        return 'font/woff'
    if data[:4] in (b'\x00\x01\x00\x00', b'true'):
        return 'font/ttf'
    if data.startswith(b'OTTO'):
        return 'font/otf'
    text = data.lstrip()[:512].lower()
    if text.startswith(b'<?xml') or text.startswith(b'<svg'):
        _check_svg(data)
        return 'image/svg+xml'
    raise _invalid('Tipo de arquivo não aceito (PNG, JPEG, SVG, WOFF2, WOFF, TTF ou OTF)')


def _path(asset_id: str, media_type: str) -> Path:
    return asset_dir() / f'{asset_id}.{EXT[media_type]}'


def add(data: bytes) -> dict:
    if not data:
        raise _invalid('Arquivo vazio')
    if len(data) > MAX_ASSET_BYTES:
        raise _invalid(f'Arquivo maior que {MAX_ASSET_BYTES // (1024 * 1024)} MB')
    media_type = detect(data)
    asset_id = hashlib.sha256(data).hexdigest()
    target = _path(asset_id, media_type)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix='.upload-')
        try:
            with os.fdopen(fd, 'wb') as fh:
                fh.write(data)
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    return {'asset_id': asset_id, 'media_type': media_type, 'size_bytes': len(data)}


def find(asset_id: str) -> tuple[Path, str] | None:
    if not _ID.match(asset_id):
        return None
    for media_type in EXT:
        p = _path(asset_id, media_type)
        if p.is_file():
            return p, media_type
    return None


def exists(asset_id: str, media_type: str | None = None) -> bool:
    hit = find(asset_id)
    return hit is not None and (media_type is None or hit[1] == media_type)


def read(asset_id: str) -> tuple[bytes, str]:
    hit = find(asset_id)
    if hit is None:
        raise ApiError(404, 'asset_not_found', 'Ativo de tema não encontrado no armazenamento local')
    path, media_type = hit
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != asset_id:  # arquivo adulterado no disco: não servir
        raise ApiError(409, 'asset_integrity', 'Ativo de tema não confere com o hash registrado')
    return data, media_type
