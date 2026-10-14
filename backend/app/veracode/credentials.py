"""Resolução de credenciais HMAC a partir da referência da conexão (F01).

Convenção suportada: `env:NOME` -> variáveis de ambiente do backend `NOME_API_ID` e `NOME_API_KEY`.
- Nada é persistido: os valores são lidos do ambiente a cada resolução e vivem só em memória.
- `repr`/`str` mascarados; nomes das variáveis derivadas e valores NUNCA são devolvidos pela API.
- Validação explícita: formato da referência, presença dos dois valores e formato hexadecimal.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.veracode.errors import VeracodeError

REF_RE = re.compile(r'^env:([A-Z][A-Z0-9_]{1,62})$')
_HEX = re.compile(r'^[0-9a-fA-F]+$')
ID_SUFFIX, KEY_SUFFIX = '_API_ID', '_API_KEY'
# Sal aleatório por processo: a impressão digital só serve para isolar o cache dentro deste processo
# e não permite recuperar nem comparar credenciais fora dele.
_FINGERPRINT_SALT = secrets.token_bytes(32)


@dataclass(frozen=True)
class Credentials:
    api_id: str = field(repr=False)
    api_key: str = field(repr=False)

    def __repr__(self) -> str:
        return 'Credentials(api_id=***, api_key=***)'

    __str__ = __repr__

    @property
    def fingerprint(self) -> str:
        """Identificador irreversível (HMAC com sal do processo) do API ID. Usado só em chaves de cache."""
        return hmac.new(_FINGERPRINT_SALT, self.api_id.encode(), hashlib.sha256).hexdigest()[:16]

    @property
    def key_bytes(self) -> bytes:
        return bytes.fromhex(self.api_key)


def env_name(credential_ref: str) -> str:
    match = REF_RE.fullmatch(credential_ref or '')
    if not match:
        raise VeracodeError('unsupported_credential_ref')
    return match.group(1)


def credential_status(credential_ref: str, environ: Mapping[str, str] | None = None) -> str:
    """'configured' | 'missing' | 'invalid_format' | 'unsupported_ref' — sem chamar a Veracode."""
    try:
        resolve(credential_ref, environ)
    except VeracodeError as exc:
        return {'credentials_missing': 'missing', 'credentials_invalid_format': 'invalid_format'}.get(
            exc.code, 'unsupported_ref')
    return 'configured'


def resolve(credential_ref: str, environ: Mapping[str, str] | None = None) -> Credentials:
    env = os.environ if environ is None else environ
    name = env_name(credential_ref)
    api_id = (env.get(name + ID_SUFFIX) or '').strip()
    api_key = (env.get(name + KEY_SUFFIX) or '').strip()
    if not api_id or not api_key:
        raise VeracodeError('credentials_missing')
    # Veracode emite API ID e API Key hexadecimais; a chave é decodificada de hex na assinatura HMAC.
    if not _HEX.fullmatch(api_id) or not _HEX.fullmatch(api_key) or len(api_key) % 2:
        raise VeracodeError('credentials_invalid_format')
    return Credentials(api_id=api_id, api_key=api_key)
