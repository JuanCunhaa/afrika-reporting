"""Coleta da população (F04/F04.1): SOMENTE GET, um contexto por requisição paginada.

Por aplicação: sandboxes (lista), Summary Report da Policy, projetos do SCA Agent vinculados e Findings
(Policy STATIC/SCA e, para cada sandbox, STATIC/SCA).
- Uma única `CollectionRun` por execução: orçamento e prazo globais (`metrics_max_requests`/`metrics_timeout`).
- Cache transitório (memória, TTL) isolado por escopo + conexão + credencial + recurso + parâmetros; só coletas
  completas entram. Nada é persistido; respostas são minimizadas na normalização.
- Estado explícito por contexto (complete/incomplete/failed/unsupported/circuit_open/no_sca_components); nunca
  vira lista vazia.
- Confiabilidade (evidência real F04.1): 500 da Findings API não é repetido de imediato; os contextos que deram 500
  recebem UMA nova tentativa numa passada adiada (`findings_retry_pass_delay`). Falhas 5xx consecutivas por
  (recurso, tipo, contexto) abrem um circuito (`circuit_breaker_threshold`): o restante não é requisitado.
- Pré-checagem SCA (`sca_precheck`): Summary Report da Policy com `third_party_components == 0` (no tenant real a
  Findings SCA devolveu 500 em todas as observações — mas o 500 também ocorre, intermitente, com componentes).
  `verify`: chama; 200 => dado normal; 500 => nova tentativa adiada e, persistindo, ausência INFERIDA
  (`no_sca_components`, fora do circuit breaker). `skip`: nem chama. `off`: desliga.
- Cancelamento (asyncio.CancelledError) propaga e interrompe a coleta.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum

from app.veracode import adapters
from app.veracode.discovery import DiscoveryService, ScopeContext
from app.veracode.http import Collection

LIMIT_ERRORS = {'request_budget_exhausted', 'deadline_exceeded'}
SERVER_ERRORS = {'upstream_error', 'timeout', 'network_error', 'invalid_response'}


class CollectState(StrEnum):
    COMPLETE = 'complete'
    INCOMPLETE = 'incomplete'                # parte das páginas coletada (ou limite atingido no meio)
    FAILED = 'failed'                        # nada coletado
    UNSUPPORTED = 'unsupported'              # a Veracode recusou o contexto (HTTP 400)
    CIRCUIT_OPEN = 'circuit_open'            # não requisitado: circuito aberto por falhas 5xx consecutivas
    NO_SCA_COMPONENTS = 'no_sca_components'  # não requisitado: Summary Report sem componentes de terceiros


NOT_COLLECTED = (CollectState.FAILED, CollectState.CIRCUIT_OPEN)


@dataclass
class ContextData:
    app_guid: str
    app_name: str | None
    context: str                 # POLICY | SANDBOX
    sandbox_guid: str | None
    sandbox_name: str | None
    scan_type: str               # STATIC | SCA
    state: CollectState
    error: str | None = None
    upstream_status: int | None = None
    findings: list[dict] = field(default_factory=list)
    cached: bool = False
    retried: bool = False


@dataclass
class Fetched:
    """Resultado de um recurso por aplicação (lista de sandboxes, Summary Report, projetos do SCA Agent)."""
    state: CollectState
    data: list[dict] = field(default_factory=list)
    error: str | None = None


@dataclass
class CollectionOutcome:
    contexts: list[ContextData] = field(default_factory=list)
    listings: dict[str, Fetched] = field(default_factory=dict)
    summaries: dict[str, Fetched] = field(default_factory=dict)
    sca_projects: dict[str, Fetched] = field(default_factory=dict)
    requests: int = 0
    retries: int = 0
    limit_reached: str | None = None
    skipped_reason: str | None = None
    circuits_opened: list[str] = field(default_factory=list)
    retry_pass: dict = field(default_factory=lambda: {'attempted': 0, 'recovered': 0})

    def summary(self) -> dict:
        by_state = {s.value: 0 for s in CollectState}
        for c in self.contexts:
            by_state[c.state.value] += 1
        return {'contexts': len(self.contexts), 'by_state': by_state,
                'sandbox_listings_failed': sum(x.state != CollectState.COMPLETE for x in self.listings.values()),
                'summary_reports_failed': sum(x.state != CollectState.COMPLETE for x in self.summaries.values()),
                'sca_project_lookups_failed': sum(x.state != CollectState.COMPLETE for x in self.sca_projects.values()),
                'cache_hits': sum(c.cached for c in self.contexts), 'requests': self.requests,
                'retries': self.retries, 'limit_reached': self.limit_reached, 'skipped_reason': self.skipped_reason,
                'circuits_opened': list(self.circuits_opened), 'retry_pass': dict(self.retry_pass)}


class CircuitBreaker:
    """Abre por chave após N falhas de servidor consecutivas (sucesso zera). Aberto = não requisitar mais."""

    def __init__(self, threshold: int):
        self.threshold = threshold
        self._failures: dict[str, int] = {}
        self.opened: list[str] = []

    def is_open(self, key: str) -> bool:
        return key in self.opened

    def record(self, key: str, state: CollectState, error: str | None) -> None:
        if state == CollectState.COMPLETE:
            self._failures[key] = 0
        elif error in SERVER_ERRORS:
            self._failures[key] = self._failures.get(key, 0) + 1
            if self._failures[key] >= self.threshold and key not in self.opened:
                self.opened.append(key)


def _state(col: Collection) -> tuple[CollectState, str | None, int | None]:
    if col.complete:
        return CollectState.COMPLETE, None, None
    code = col.error.code if col.error else 'unknown'
    status = col.error.upstream_status if col.error else None
    if code == 'bad_request' and col.pages_fetched == 0:
        return CollectState.UNSUPPORTED, code, status
    return (CollectState.INCOMPLETE if col.pages_fetched else CollectState.FAILED), code, status


def no_sca_components(summary: Fetched | None) -> bool:
    if summary is None or summary.state != CollectState.COMPLETE or not summary.data:
        return False
    sca = summary.data[0].get('sca') or {}
    return sca.get('third_party_components') == 0


async def collect(service: DiscoveryService, ctx: ScopeContext, applications: list[dict], *,
                  progress: Callable[[int, int], None] | None = None,
                  sleep: Callable[[float], Awaitable[None]] | None = None,
                  clock: Callable[[], float] = time.monotonic) -> CollectionOutcome:
    out = CollectionOutcome()
    if not applications:
        return out
    settings = service.settings
    sleep = sleep or service.sleep
    creds = service.credentials_for(ctx)
    run = service.metrics_run(ctx, creds)
    gate = asyncio.Semaphore(max(1, settings.max_concurrency))
    breaker = CircuitBreaker(settings.circuit_breaker_threshold)
    first_500: list[float] = []
    done = 0

    async def fetch(resource: str, params: tuple, collector) -> tuple[Collection, bool]:
        return await service.collect_cached(ctx, creds, resource, params, collector)

    async def guarded(key: str, resource: str, params: tuple, collector) -> tuple[Collection | None, bool]:
        if breaker.is_open(key):
            return None, False
        col, cached = await fetch(resource, params, collector)
        state, error, _ = _state(col)
        breaker.record(key, state, error)
        return col, cached

    async def single(resource: str, guid: str, collector) -> Fetched:
        col, _ = await guarded(resource, resource, (guid,), collector)
        if col is None:
            return Fetched(CollectState.CIRCUIT_OPEN)
        state, error, _ = _state(col)
        return Fetched(state, list(col.items) if state != CollectState.FAILED else [], error)

    async def one_context(app: dict, context: str, sandbox: dict | None, scan_type: str, *,
                          absence_expected: bool = False) -> ContextData:
        guid = app['guid']
        sb_guid = sandbox['guid'] if sandbox else None
        base = ContextData(guid.lower(), app.get('name'), context, sb_guid, sandbox.get('name') if sandbox else None,
                           scan_type, CollectState.CIRCUIT_OPEN)
        params = (guid.lower(), sb_guid, scan_type)
        collector = lambda: adapters.fetch_findings(run, guid, scan_type, sb_guid)  # noqa: E731
        if absence_expected:  # falha explicada pela ausência de componentes: não alimenta o circuito
            col, cached = await fetch('findings', params, collector)
        else:
            col, cached = await guarded(f'findings:{scan_type}:{context}', 'findings', params, collector)
        if col is None:
            return base
        base.state, base.error, base.upstream_status = _state(col)
        base.findings = list(col.items) if base.state != CollectState.FAILED else []
        base.cached = cached
        if absence_expected and base.state == CollectState.FAILED and base.upstream_status == 500:
            base.state = CollectState.NO_SCA_COMPONENTS
        elif base.upstream_status == 500 and not first_500:
            first_500.append(clock())
        return base

    async def one_app(app: dict) -> None:
        nonlocal done
        guid = app['guid']
        key = guid.lower()
        async with gate:
            listing, summary, projects = await asyncio.gather(
                single('sandboxes', guid, lambda: adapters.fetch_sandboxes(run, guid)),
                single('summary_report', guid, lambda: adapters.fetch_summary_report(run, guid)),
                single('sca_app_projects', guid, lambda: adapters.fetch_sca_app_projects(run, guid)))
            out.listings[key], out.summaries[key], out.sca_projects[key] = listing, summary, projects
            jobs = [one_context(app, 'POLICY', None, 'STATIC')]
            absent = settings.sca_precheck != 'off' and no_sca_components(summary)
            if absent and settings.sca_precheck == 'skip':
                out.contexts.append(ContextData(key, app.get('name'), 'POLICY', None, None, 'SCA',
                                                CollectState.NO_SCA_COMPONENTS))
            else:
                jobs.append(one_context(app, 'POLICY', None, 'SCA', absence_expected=absent))
            if listing.state not in NOT_COLLECTED:
                jobs += [one_context(app, 'SANDBOX', sb, t) for sb in listing.data if sb.get('guid')
                         for t in adapters.FINDING_SCAN_TYPES]
            out.contexts.extend(await asyncio.gather(*jobs))
        done += 1
        if progress:
            progress(done, len(applications))

    try:
        await asyncio.gather(*(one_app(a) for a in applications))
        await _retry_pass(out, run, settings, breaker, first_500, sleep, clock)
    finally:
        out.requests, out.retries = run.requests, run.retries
        out.circuits_opened = list(breaker.opened)
    errors = {c.error for c in out.contexts} | {x.error for group in (out.listings, out.summaries, out.sca_projects)
                                                for x in group.values()}
    out.limit_reached = next((e for e in sorted(errors - {None}) if e in LIMIT_ERRORS), None)
    out.contexts.sort(key=lambda c: (c.app_guid, c.context, c.sandbox_guid or '', c.scan_type))
    return out


async def _retry_pass(out: CollectionOutcome, run, settings, breaker: CircuitBreaker, first_500: list[float],
                      sleep, clock) -> None:
    """Uma única nova tentativa, adiada, para contextos que falharam com HTTP 500 e cujo circuito está fechado."""
    # 500 "explicado" pela ausência de componentes também tem UMA nova tentativa (o 500 real é intermitente até em
    # aplicações com componentes — homologação F04.1); `skip` nunca chamou, então não tem upstream_status.
    targets = [c for c in out.contexts if c.upstream_status == 500
               and (c.state == CollectState.NO_SCA_COMPONENTS
                    or (c.state in NOT_COLLECTED and not breaker.is_open(f'findings:{c.scan_type}:{c.context}')))]
    if not targets:
        return
    wait = settings.findings_retry_pass_delay - (clock() - first_500[0]) if first_500 else 0
    if wait > 0:
        await sleep(wait)
    out.retry_pass['attempted'] = len(targets)

    async def again(c: ContextData) -> None:
        col = await adapters.fetch_findings(run, c.app_guid, c.scan_type, c.sandbox_guid)
        state, error, status = _state(col)
        c.retried = True
        if state == CollectState.COMPLETE or len(col.items) > len(c.findings):
            c.state, c.error, c.upstream_status, c.findings = state, error, status, list(col.items)
            out.retry_pass['recovered'] += state == CollectState.COMPLETE

    await asyncio.gather(*(again(c) for c in targets))
