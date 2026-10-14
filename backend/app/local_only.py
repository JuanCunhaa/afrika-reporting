"""Restrição ao loopback (F02). A API não tem autenticação e, a partir da F02, dispara consultas à Veracode com
credenciais do backend; por isso recusa:
- conexões cujo IP de origem não é loopback (ex.: servidor iniciado por engano com --host 0.0.0.0);
- `Host` diferente de localhost/127.0.0.1/::1 (defesa contra DNS rebinding a partir de páginas maliciosas).
Não substitui autenticação: é só uma barreira para uso estritamente local.
"""
from __future__ import annotations

import ipaddress
import json

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

ALLOWED_HOST_NAMES = {'localhost', '127.0.0.1', '::1', 'testserver'}  # testserver: Starlette TestClient
TEST_CLIENT_HOST = 'testclient'  # nome fixo do TestClient; nunca é um IP de socket real


def _is_loopback(host: str | None) -> bool:
    if host == TEST_CLIENT_HOST:
        return True
    try:
        return ipaddress.ip_address(host or '').is_loopback
    except ValueError:
        return False


def _host_name(raw: str | None) -> str:
    raw = (raw or '').strip().lower()
    if raw.startswith('['):  # IPv6 com porta: [::1]:8000
        return raw[1:raw.find(']')] if ']' in raw else ''
    return raw.rsplit(':', 1)[0] if raw.count(':') == 1 else raw


class LocalOnlyMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] not in ('http', 'websocket'):
            await self.app(scope, receive, send)
            return
        client = scope.get('client')
        host = _host_name(Headers(scope=scope).get('host'))
        if not _is_loopback(client[0] if client else None) or host not in ALLOWED_HOST_NAMES:
            body = json.dumps({'error': {'code': 'local_only', 'message': 'API restrita ao acesso local (loopback)',
                                         'details': []}}).encode()
            await send({'type': 'http.response.start', 'status': 403,
                        'headers': [(b'content-type', b'application/json'),
                                    (b'content-length', str(len(body)).encode())]})
            await send({'type': 'http.response.body', 'body': body})
            return
        await self.app(scope, receive, send)
