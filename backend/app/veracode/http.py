"""Cliente HTTP compartilhado da Veracode: SOMENTE GET, retry com backoff+jitter, 429/Retry-After,
concorrência limitada, orçamento de requisições, prazo total, paginação completa e indicação de completude.

Garantias:
- Um `httpx.AsyncClient` por região (conexões reutilizadas), TLS sempre validado, sem redirects, sem cookies.
- Autenticação por requisição (HMAC) — o cliente é compartilhado entre tenants sem guardar estado deles.
- Hosts fixos por região; links `_links.next` da resposta NÃO são seguidos (página calculada localmente).
- Trava somente leitura (`readonly.py`): só GET, em host oficial e endpoint da allowlist (única exceção: POST de
  geração de relatório da Reporting API, se habilitado); aplicada no event hook e no transporte (duas camadas).
  `VERACODE_READ_ONLY` diferente de true impede a criação do pool.
- Logs: apenas recurso, status, tentativa e espera. Nunca URL com query, headers, corpo ou credenciais.
- Cancelamento (asyncio.CancelledError) propaga: semáforo e conexão são liberados e nada é cacheado.
"""
from __future__ import annotations

import asyncio
import email.utils
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.cookiejar import CookieJar, DefaultCookiePolicy

import httpx

from app.veracode.credentials import Credentials
from app.veracode.errors import VeracodeError
from app.veracode.hmac_auth import VeracodeHmacAuth
from app.veracode.readonly import ReadOnlyTransport, ReadOnlyViolation, make_policy_hook
from app.veracode.settings import VeracodeSettings

logger = logging.getLogger('afrika.veracode')

REGION_BASE_URLS = {
    'commercial': 'https://api.veracode.com',
    'european': 'https://api.veracode.eu',
    'federal': 'https://api.veracode.us',
}
USER_AGENT = 'afrika-reporting/0.2 (read-only discovery)'
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_STATUS_ERRORS = {401: 'auth_failed', 403: 'forbidden', 404: 'not_found'}


class _HttpLibLogGuard(logging.Filter):
    """httpx/httpcore logam URL completa (INFO) e detalhes de conexão (DEBUG). Só WARNING+ passa."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.WARNING


def install_http_log_guard() -> None:
    for name in ('httpx', 'httpcore'):
        lg = logging.getLogger(name)
        if not any(isinstance(f, _HttpLibLogGuard) for f in lg.filters):
            lg.addFilter(_HttpLibLogGuard())


def _no_cookies() -> CookieJar:
    return CookieJar(policy=DefaultCookiePolicy(allowed_domains=[]))


def parse_retry_after(value: str | None, now: float | None = None) -> float | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, when.timestamp() - (time.time() if now is None else now))


class VeracodeHttpPool:
    """Recursos compartilhados pelo processo: clientes por região + semáforo de concorrência."""

    def __init__(self, settings: VeracodeSettings, transport: httpx.AsyncBaseTransport | None = None):
        if settings.read_only is not True:  # redundante com VeracodeSettings; nunca relaxar
            raise ReadOnlyViolation('a integração Veracode só opera em modo somente leitura')
        install_http_log_guard()
        self.settings = settings
        self._transport = transport
        self._clients: dict[str, httpx.AsyncClient] = {}
        self.semaphore = asyncio.Semaphore(settings.max_concurrency)
        self.in_flight = 0

    def client(self, region: str) -> httpx.AsyncClient:
        if region not in REGION_BASE_URLS:
            raise ValueError('região desconhecida')
        if region not in self._clients:
            s = self.settings
            limits = httpx.Limits(max_connections=s.max_concurrency, max_keepalive_connections=s.max_concurrency)
            inner = self._transport or httpx.AsyncHTTPTransport(limits=limits)  # TLS validado (padrão)
            self._clients[region] = httpx.AsyncClient(
                base_url=REGION_BASE_URLS[region],
                timeout=httpx.Timeout(s.read_timeout, connect=s.connect_timeout),
                limits=limits,
                follow_redirects=False,
                cookies=_no_cookies(),
                headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'},
                # Geração de relatório (único POST) só quando habilitada nas configurações (padrão: desligada).
                event_hooks={'request': [make_policy_hook(allow_report_generation=s.reporting_enabled)]},
                transport=ReadOnlyTransport(inner, allow_report_generation=s.reporting_enabled),
            )
        return self._clients[region]

    async def aclose(self) -> None:
        clients, self._clients = list(self._clients.values()), {}
        for c in clients:
            await c.aclose()


@dataclass
class Collection:
    """Resultado de uma coleta. `complete=False` NUNCA deve ser tratado como dado confiável."""
    resource: str
    items: list[dict] = field(default_factory=list)
    complete: bool = True
    error: VeracodeError | None = None
    pages_fetched: int = 0
    total_pages: int | None = None
    total_elements: int | None = None
    requests: int = 0
    retries: int = 0
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    meta: dict = field(default_factory=dict)  # dados auxiliares da coleta (ex.: Teams cujo detalhe foi obtido)

    def status(self) -> dict:
        return {
            'resource': self.resource,
            'complete': self.complete,
            'status': 'complete' if self.complete else 'incomplete',
            'reason': self.error.as_dict() if self.error else None,
            'pages_fetched': self.pages_fetched,
            'total_pages_reported': self.total_pages,
            'total_elements_reported': self.total_elements,
            'items_collected': len(self.items),
            'requests': self.requests,
            'retries': self.retries,
            'fetched_at': self.fetched_at.isoformat(),
        }


def _page_meta(data: dict) -> tuple[int | None, int | None]:
    page = data.get('page')
    if not isinstance(page, dict):
        return None, None
    # Applications API usa snake_case; a especificação da Identity API declara camelCase. Aceita os dois.
    tp = page.get('total_pages', page.get('totalPages'))
    te = page.get('total_elements', page.get('totalElements'))
    if not isinstance(tp, int) or not isinstance(te, int) or tp < 0 or te < 0:
        raise VeracodeError('invalid_response')
    return tp, te


def _embedded(data: dict, key: str, total_elements: int | None) -> list[dict]:
    emb = data.get('_embedded')
    if emb is None:
        # Veracode omite `_embedded` quando a página não tem itens; a coerência com o total anunciado é
        # verificada pela paginação (página vazia com itens pendentes => inconsistent_pagination).
        return []
    if not isinstance(emb, dict) or not isinstance(emb.get(key, []), list):
        raise VeracodeError('invalid_response')
    items = emb.get(key)
    if items is None:
        if emb or total_elements not in (None, 0):
            raise VeracodeError('invalid_response')  # chave inesperada: não presumir lista vazia
        return []
    if not all(isinstance(i, dict) for i in items):
        raise VeracodeError('invalid_response')
    return items


class CollectionRun:
    """Uma coleta (com orçamento e prazo próprios) para uma credencial e região."""

    def __init__(self, pool: VeracodeHttpPool, creds: Credentials, region: str, *,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 rng: random.Random | None = None, clock: Callable[[], float] = time.monotonic,
                 max_requests: int | None = None, timeout: float | None = None):
        # max_requests/timeout: limites próprios de coletas maiores (métricas, F04); padrão = descoberta.
        self.pool = pool
        self.settings = pool.settings
        self._client = pool.client(region)
        self._auth = VeracodeHmacAuth(creds)
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._clock = clock
        self.max_requests = max_requests or self.settings.max_requests_per_collection
        self.deadline = clock() + (timeout or self.settings.collection_timeout)
        self.requests = 0
        self.retries = 0

    def _backoff(self, attempt: int) -> float:
        s = self.settings
        return self._rng.uniform(0, min(s.backoff_max, s.backoff_base * (2 ** attempt)))  # full jitter

    async def get_json(self, path: str, params: dict | None = None, *, label: str,
                       no_retry_status: frozenset[int] = frozenset()) -> dict:
        """`no_retry_status`: status que NÃO são repetidos de imediato (F04.1: 500 da Findings API só passa após
        dezenas de segundos — repetir em segundos só gasta orçamento; o coletor faz uma passada adiada)."""
        s = self.settings
        for attempt in range(s.max_retries + 1):
            if self.requests >= self.max_requests:
                raise VeracodeError('request_budget_exhausted')
            remaining = self.deadline - self._clock()
            if remaining <= 0:
                raise VeracodeError('deadline_exceeded')
            self.requests += 1
            retry_after = None
            try:
                async with self.pool.semaphore:
                    self.pool.in_flight += 1
                    try:
                        async with asyncio.timeout(remaining):
                            resp = await self._client.get(path, params=params, auth=self._auth)
                    finally:
                        self.pool.in_flight -= 1
            except TimeoutError:
                raise VeracodeError('deadline_exceeded') from None
            except httpx.TimeoutException:
                error = VeracodeError('timeout')
            except httpx.TransportError:
                error = VeracodeError('network_error')
            else:
                status = resp.status_code
                if 200 <= status < 300:
                    try:
                        data = resp.json()
                    except ValueError:
                        raise VeracodeError('invalid_response', upstream_status=status) from None
                    if not isinstance(data, dict):
                        raise VeracodeError('invalid_response', upstream_status=status)
                    return data
                if status not in RETRYABLE_STATUS or status in no_retry_status:
                    # 3xx: redirects não são seguidos (host fixo por região) => resposta inesperada.
                    code = _STATUS_ERRORS.get(status) or ('rate_limited' if status == 429 else 'bad_request'
                                                          if 400 <= status < 500 else 'invalid_response'
                                                          if status < 400 else 'upstream_error')
                    logger.warning('veracode recurso=%s status=%s erro=%s', label, status, code)
                    raise VeracodeError(code, upstream_status=status)
                error = VeracodeError('rate_limited' if status == 429 else 'upstream_error', upstream_status=status)
                if status == 429:
                    retry_after = parse_retry_after(resp.headers.get('Retry-After'))

            if attempt >= s.max_retries:
                logger.warning('veracode recurso=%s erro=%s tentativas esgotadas (%s)', label, error.code,
                               attempt + 1)
                raise error
            if retry_after is not None and retry_after > s.max_retry_after:
                logger.warning('veracode recurso=%s Retry-After=%.0fs acima do limite configurado', label,
                               retry_after)
                raise error
            delay = (retry_after + self._rng.uniform(0, s.backoff_base)) if retry_after is not None \
                else self._backoff(attempt)
            if self._clock() + delay >= self.deadline:
                raise VeracodeError('deadline_exceeded')
            self.retries += 1
            logger.info('veracode recurso=%s erro=%s tentativa=%s nova tentativa em %.2fs', label, error.code,
                        attempt + 1, delay)
            await self._sleep(delay)
        raise AssertionError('inalcançável')

    async def post_json(self, path: str, body: dict, *, label: str) -> dict:
        """F05: SOMENTE para a geração de relatório da Reporting API (a trava do transporte recusa qualquer outro
        POST). Repete apenas o que comprovadamente não foi processado: HTTP 429 e falha ao CONECTAR. 5xx, timeout
        de leitura e erro de rede após o envio NÃO são repetidos — poderiam gerar relatórios duplicados."""
        s = self.settings
        for attempt in range(s.max_retries + 1):
            if self.requests >= self.max_requests:
                raise VeracodeError('request_budget_exhausted')
            remaining = self.deadline - self._clock()
            if remaining <= 0:
                raise VeracodeError('deadline_exceeded')
            self.requests += 1
            retry_after = None
            try:
                async with self.pool.semaphore:
                    self.pool.in_flight += 1
                    try:
                        async with asyncio.timeout(remaining):
                            resp = await self._client.post(path, json=body, auth=self._auth)
                    finally:
                        self.pool.in_flight -= 1
            except TimeoutError:
                raise VeracodeError('deadline_exceeded') from None
            except (httpx.ConnectError, httpx.ConnectTimeout):
                error = VeracodeError('network_error')  # não chegou ao servidor: repetir é seguro
            except httpx.TimeoutException:
                raise VeracodeError('timeout') from None
            except httpx.TransportError:
                raise VeracodeError('network_error') from None
            else:
                status = resp.status_code
                if 200 <= status < 300:
                    try:
                        data = resp.json()
                    except ValueError:
                        raise VeracodeError('invalid_response', upstream_status=status) from None
                    if not isinstance(data, dict):
                        raise VeracodeError('invalid_response', upstream_status=status)
                    return data
                if status != 429:
                    code = _STATUS_ERRORS.get(status) or ('bad_request' if 400 <= status < 500 else
                                                          'invalid_response' if status < 400 else 'upstream_error')
                    logger.warning('veracode recurso=%s status=%s erro=%s (sem nova tentativa)', label, status, code)
                    raise VeracodeError(code, upstream_status=status)
                error = VeracodeError('rate_limited', upstream_status=status)
                retry_after = parse_retry_after(resp.headers.get('Retry-After'))
            if attempt >= s.max_retries:
                logger.warning('veracode recurso=%s erro=%s tentativas esgotadas (%s)', label, error.code, attempt + 1)
                raise error
            if retry_after is not None and retry_after > s.max_retry_after:
                raise error
            delay = (retry_after + self._rng.uniform(0, s.backoff_base)) if retry_after is not None \
                else self._backoff(attempt)
            if self._clock() + delay >= self.deadline:
                raise VeracodeError('deadline_exceeded')
            self.retries += 1
            logger.info('veracode recurso=%s erro=%s tentativa=%s nova tentativa em %.2fs', label, error.code,
                        attempt + 1, delay)
            await self._sleep(delay)
        raise AssertionError('inalcançável')

    def remaining(self) -> float:
        return self.deadline - self._clock()

    async def paginate(self, path: str, embedded_key: str, *, label: str, id_field: str | None,
                       params: dict | None = None, page_size: int | None = None,
                       no_retry_status: frozenset[int] = frozenset()) -> Collection:
        """`id_field`: identificador por item usado para detectar repetição entre páginas. `None` = o recurso não tem
        identificador por item (F10: findings SCA reais não trazem `issue_id`); a completude fica provada só pelos
        metadados de paginação (`total_elements` anunciado = itens recebidos), sem supor identidade."""
        size = page_size or self.settings.page_size
        col = Collection(resource=label)
        start_requests, start_retries = self.requests, self.retries
        seen: set = set()
        duplicates = 0
        page = 0
        try:
            while True:
                data = await self.get_json(path, {**(params or {}), 'page': page, 'size': size}, label=label,
                                           no_retry_status=no_retry_status)
                total_pages, total_elements = _page_meta(data)
                if id_field is None and total_pages is None:
                    raise VeracodeError('invalid_response')  # sem identificador E sem total: completude improvável
                batch = _embedded(data, embedded_key, total_elements)
                col.pages_fetched += 1
                if total_pages is not None:
                    if col.total_pages is None:
                        col.total_pages, col.total_elements = total_pages, total_elements
                    elif (total_pages, total_elements) != (col.total_pages, col.total_elements):
                        raise VeracodeError('inconsistent_pagination')
                for item in batch:
                    if id_field is None:
                        col.items.append(item)
                        continue
                    key = item.get(id_field)
                    if key is None:
                        raise VeracodeError('invalid_response')
                    if key in seen:
                        duplicates += 1
                        continue
                    seen.add(key)
                    col.items.append(item)
                if total_pages is not None:
                    if page + 1 >= total_pages:
                        break
                    if not batch:
                        raise VeracodeError('inconsistent_pagination')  # páginas restantes anunciadas e vazias
                elif len(batch) < size:
                    break
                page += 1
            if duplicates or (col.total_elements is not None and len(col.items) != col.total_elements):
                raise VeracodeError('inconsistent_pagination')
        except VeracodeError as exc:
            col.complete, col.error = False, exc
        finally:
            col.requests = self.requests - start_requests
            col.retries = self.retries - start_retries
        logger.info('veracode coleta recurso=%s status=%s páginas=%s itens=%s requisições=%s retries=%s', label,
                    'complete' if col.complete else f'incomplete:{col.error.code}', col.pages_fetched,
                    len(col.items), col.requests, col.retries)
        return col

    async def get_one(self, path: str, *, label: str, params: dict | None = None) -> Collection:
        col = Collection(resource=label)
        start_requests, start_retries = self.requests, self.retries
        try:
            col.items = [await self.get_json(path, params, label=label)]
            col.pages_fetched = 1
        except VeracodeError as exc:
            col.complete, col.error = False, exc
        finally:
            col.requests = self.requests - start_requests
            col.retries = self.retries - start_retries
        return col
