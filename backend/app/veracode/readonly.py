"""Trava SOMENTE LEITURA da integração Veracode (F02.1), com UMA exceção autorizada pelo PO na F05.

Toda requisição precisa passar por `check_request` antes de sair do processo:
- HTTPS, porta padrão e host oficial de uma região conhecida;
- GET: caminho na allowlist explícita de endpoints de leitura usados pelos adaptadores;
- POST: SOMENTE `POST /appsec/v1/analytics/report` (geração de relatório da Reporting API), SOMENTE quando a
  geração foi habilitada explicitamente (`AFRIKA_VERACODE_REPORTING_ENABLED=true`), sem query string, com
  `Content-Type: application/json` e corpo revalidado pela política (`reporting_policy`). Qualquer outro POST,
  e PUT/PATCH/DELETE/HEAD/OPTIONS/..., é bloqueado sempre (deny-by-default).

Aplicada em duas camadas no cliente httpx (event hook de requisição + transporte envolvente), de modo que
mesmo uma requisição montada diretamente por código ou biblioteca (`client.send`, `client.request`, fluxo
de autenticação) é barrada antes da rede. A violação é um erro de programação: não é tentada de novo.
"""
from __future__ import annotations

import re

import httpx

from app.veracode.reporting_policy import GENERATION_PATH, ReportPolicyError, check_generation_body

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
    # F12: papéis/permissões da PRÓPRIA conta autenticada (Identity API; acessível sem papel de administrador).
    # Caminho exato: nenhum outro usuário (`/users/{id}`) nem `/principal`. Somente leitura.
    re.compile(r'/api/authn/v2/users/self'),
    # F04: Findings API (lista por aplicação; `context`=sandbox e `scan_type` vão na query). Somente leitura.
    re.compile(rf'/appsec/v2/applications/{_SEG}/findings'),
    # F04.1: Summary Report API (agregado por build; `context`=sandbox na query) e SCA Agent — projetos vinculados
    # a UMA aplicação por GUID. Ambos GET documentados (SwaggerHub Veracode). Somente leitura.
    re.compile(rf'/appsec/v2/applications/{_SEG}/summary_report'),
    re.compile(rf'/srcclr/v3/applications/{_SEG}/projects'),
    # F05: Reporting API — consulta de status/páginas de UM relatório gerado (id = UUID). Somente leitura.
    re.compile(r'/appsec/v1/analytics/report/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
               r'[0-9a-fA-F]{12}'),
)


class ReadOnlyViolation(RuntimeError):
    """Requisição fora da política somente leitura: bloqueada antes do envio."""


def _check_report_generation(request: httpx.Request, path: str, query: bytes) -> None:
    if path != GENERATION_PATH or query:
        raise ReadOnlyViolation('POST só é permitido na geração de relatório da Reporting API')
    if request.headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'application/json':
        raise ReadOnlyViolation('geração de relatório exige corpo JSON')
    try:
        content = request.content
    except httpx.RequestNotRead:
        raise ReadOnlyViolation('corpo da geração de relatório precisa estar em memória') from None
    try:
        check_generation_body(content)
    except ReportPolicyError:
        raise ReadOnlyViolation('corpo da geração de relatório fora da política autorizada') from None


def check_request(request: httpx.Request, *, allow_report_generation: bool = False) -> None:
    if request.method not in ('GET', 'POST') or (request.method == 'POST' and not allow_report_generation):
        raise ReadOnlyViolation('somente GET é permitido na integração Veracode (exceção: geração de relatório '
                                'da Reporting API, quando habilitada)')
    url = request.url
    if url.scheme != 'https' or url.host not in ALLOWED_HOSTS or url.port not in (None, 443):
        raise ReadOnlyViolation('host não autorizado para a integração Veracode')
    raw_path, _, query = url.raw_path.partition(b'?')
    path = raw_path.decode('ascii')
    if request.method == 'POST':
        _check_report_generation(request, path, query)
        return
    if not any(p.fullmatch(path) for p in ALLOWED_GET_PATHS):
        raise ReadOnlyViolation('endpoint Veracode não autorizado')


async def enforce_read_only_hook(request: httpx.Request) -> None:
    check_request(request)


def make_policy_hook(*, allow_report_generation: bool):
    async def hook(request: httpx.Request) -> None:
        check_request(request, allow_report_generation=allow_report_generation)
    return hook


class ReadOnlyTransport(httpx.AsyncBaseTransport):
    """Envolve o transporte real (ou simulado): a última barreira antes da rede."""

    def __init__(self, inner: httpx.AsyncBaseTransport, *, allow_report_generation: bool = False):
        self._inner = inner
        self._allow_report_generation = allow_report_generation

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        check_request(request, allow_report_generation=self._allow_report_generation)
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()
