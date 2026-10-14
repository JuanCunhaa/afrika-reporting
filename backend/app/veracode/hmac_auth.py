"""Assinatura VERACODE-HMAC-SHA-256 (implementação própria a partir da documentação oficial).

Fonte: https://docs.veracode.com/r/c_enabling_hmac e exemplo oficial
https://docs.veracode.com/r/Example_SRM_script_for_HMAC_signing
  data      = "id={api_id}&host={host}&url={path+query}&method={METHOD}"
  k_nonce   = HMAC_SHA256(key=hex_decode(api_key), msg=nonce)
  k_date    = HMAC_SHA256(key=k_nonce, msg=timestamp_ms)
  k_sig     = HMAC_SHA256(key=k_date, msg="vcode_request_version_1")
  signature = hex(HMAC_SHA256(key=k_sig, msg=data))
  header    = "VERACODE-HMAC-SHA-256 id={api_id},ts={timestamp_ms},nonce={hex(nonce)},sig={signature}"
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from collections.abc import Callable, Generator

import httpx

from app.veracode.credentials import Credentials

SCHEME = 'VERACODE-HMAC-SHA-256'
REQUEST_VERSION = b'vcode_request_version_1'
NONCE_SIZE = 16


def _hmac(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


def signature(api_key_hex: str, nonce: bytes, timestamp_ms: str, data: str) -> str:
    k_nonce = _hmac(bytes.fromhex(api_key_hex), nonce)
    k_date = _hmac(k_nonce, timestamp_ms.encode())
    k_sig = _hmac(k_date, REQUEST_VERSION)
    return hmac.new(k_sig, data.encode(), hashlib.sha256).hexdigest()


def signing_data(api_id: str, host: str, path_and_query: str, method: str) -> str:
    return f'id={api_id}&host={host}&url={path_and_query}&method={method.upper()}'


def authorization_header(creds: Credentials, host: str, path_and_query: str, method: str, *,
                         nonce: bytes | None = None, timestamp_ms: str | None = None) -> str:
    nonce = nonce if nonce is not None else os.urandom(NONCE_SIZE)
    ts = timestamp_ms if timestamp_ms is not None else str(int(time.time() * 1000))
    sig = signature(creds.api_key, nonce, ts, signing_data(creds.api_id, host, path_and_query, method))
    return f'{SCHEME} id={creds.api_id},ts={ts},nonce={nonce.hex()},sig={sig}'


class VeracodeHmacAuth(httpx.Auth):
    """httpx.Auth: assina cada envio (inclusive retries) com nonce e timestamp novos."""

    def __init__(self, creds: Credentials, *, clock: Callable[[], float] = time.time):
        self._creds = creds
        self._clock = clock

    def __repr__(self) -> str:
        return 'VeracodeHmacAuth(***)'

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        path_and_query = request.url.raw_path.decode('ascii')
        request.headers['Authorization'] = authorization_header(
            self._creds, request.url.host, path_and_query, request.method,
            timestamp_ms=str(int(self._clock() * 1000)))
        yield request
