"""Trava SOMENTE LEITURA da integração Veracode (F02.1).

Toda requisição precisa passar por `check_request` antes de sair do processo:
- método exatamente GET (POST/PUT/PATCH/DELETE/HEAD/OPTIONS/... bloqueados);
- HTTPS, porta padrão e host oficial de uma região conhecida;
- caminho na allowlist explícita de endpoints de leitura usados pelos adaptadores.

Aplicada em duas camadas no cliente httpx (event hook de requisição + transporte envolvente), de modo que
mesmo uma requisição montada diretamente por código ou biblioteca (`client.send`, `client.request`, fluxo
de autenticação) é barrada antes da rede. A violação é um erro de programação: não é tentada de novo.
"""
from __future__ import annotations

import re

import httpx

ALLOWED_HOSTS = frozenset({'api.veracode.com', 'api.veracode.eu', 'api.veracode.us'})
# Um segmento variável = um único segmento já codificado (sem '/', '?', '#'); `..` não passa.
_SEG = r'(?!\.\.?(?:/|$))[^/?#]+'
ALLOWED_GET_PATHS = (
    re.compile(r'/appsec/v1/applications'),
    re.compile(rf'/appsec/v1/applications/{_SEG}/sandboxes'),
    re.compile(r'/api/authn/v2/business_units'),
    re.compile(r'/api/authn/v2/teams'),
    re.compile(rf'/api/authn/v2/teams/{_SEG}'),
    re.compile(r'/api/authn/v2/users'),
    # F04: Findings API (lista por aplicação; `context`=sandbox e `scan_type` vão na query). Somente leitura.
    re.compile(rf'/appsec/v2/applications/{_SEG}/findings'),
)


class ReadOnlyViolation(RuntimeError):
    """Requisição fora da política somente leitura: bloqueada antes do envio."""


def check_request(request: httpx.Request) -> None:
    if request.method != 'GET':
        raise ReadOnlyViolation('somente GET é permitido na integração Veracode')
    url = request.url
    if url.scheme != 'https' or url.host not in ALLOWED_HOSTS or url.port not in (None, 443):
        raise ReadOnlyViolation('host não autorizado para a integração Veracode')
    path = url.raw_path.split(b'?', 1)[0].decode('ascii')
    if not any(p.fullmatch(path) for p in ALLOWED_GET_PATHS):
        raise ReadOnlyViolation('endpoint Veracode não autorizado')


async def enforce_read_only_hook(request: httpx.Request) -> None:
    check_request(request)


class ReadOnlyTransport(httpx.AsyncBaseTransport):
    """Envolve o transporte real (ou simulado): a última barreira antes da rede."""

    def __init__(self, inner: httpx.AsyncBaseTransport):
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        check_request(request)
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()
