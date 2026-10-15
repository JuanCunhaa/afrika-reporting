"""Coleta dos findings da população (F04): SOMENTE GET, um contexto por requisição paginada.

Por aplicação: sandboxes (lista) -> Policy STATIC, Policy SCA e, para cada sandbox, STATIC e SCA.
- Uma única `CollectionRun` por execução: orçamento e prazo globais (`metrics_max_requests`/`metrics_timeout`).
- Cache transitório (memória, TTL) isolado por escopo + conexão + credencial + aplicação + contexto + tipo; só
  coletas completas entram. Nada é persistido; findings são minimizados na normalização.
- Contexto com erro => estado explícito (incomplete/failed/unsupported); nunca vira lista vazia.
- Cancelamento (asyncio.CancelledError) propaga e interrompe a coleta.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from app.veracode import adapters
from app.veracode.discovery import DiscoveryService, ScopeContext
from app.veracode.http import Collection

LIMIT_ERRORS = {'request_budget_exhausted', 'deadline_exceeded'}


class CollectState(StrEnum):
    COMPLETE = 'complete'
    INCOMPLETE = 'incomplete'    # parte das páginas coletada (ou limite atingido no meio)
    FAILED = 'failed'            # nada coletado
    UNSUPPORTED = 'unsupported'  # a Veracode recusou o contexto (HTTP 400)


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
    findings: list[dict] = field(default_factory=list)
    cached: bool = False


@dataclass
class SandboxListing:
    app_guid: str
    state: CollectState
    sandboxes: list[dict] = field(default_factory=list)
    error: str | None = None


@dataclass
class CollectionOutcome:
    contexts: list[ContextData] = field(default_factory=list)
    listings: dict[str, SandboxListing] = field(default_factory=dict)
    requests: int = 0
    retries: int = 0
    limit_reached: str | None = None
    skipped_reason: str | None = None

    def summary(self) -> dict:
        by_state = {s.value: 0 for s in CollectState}
        for c in self.contexts:
            by_state[c.state.value] += 1
        return {'contexts': len(self.contexts), 'by_state': by_state,
                'sandbox_listings_failed': sum(lst.state != CollectState.COMPLETE for lst in self.listings.values()),
                'cache_hits': sum(c.cached for c in self.contexts), 'requests': self.requests,
                'retries': self.retries, 'limit_reached': self.limit_reached, 'skipped_reason': self.skipped_reason}


def _state(col: Collection) -> tuple[CollectState, str | None]:
    if col.complete:
        return CollectState.COMPLETE, None
    code = col.error.code if col.error else 'unknown'
    if code == 'bad_request' and col.pages_fetched == 0:
        return CollectState.UNSUPPORTED, code
    return (CollectState.INCOMPLETE if col.pages_fetched else CollectState.FAILED), code


async def collect(service: DiscoveryService, ctx: ScopeContext, applications: list[dict], *,
                  progress: Callable[[int, int], None] | None = None) -> CollectionOutcome:
    out = CollectionOutcome()
    if not applications:
        return out
    creds = service.credentials_for(ctx)
    run = service.metrics_run(ctx, creds)
    gate = asyncio.Semaphore(max(1, service.settings.max_concurrency))
    done = 0

    async def fetch(resource: str, params: tuple, collector) -> tuple[Collection, bool]:
        return await service.collect_cached(ctx, creds, resource, params, collector)

    async def one_context(app: dict, context: str, sandbox: dict | None, scan_type: str) -> ContextData:
        guid = app['guid']
        sb_guid = sandbox['guid'] if sandbox else None
        col, cached = await fetch('findings', (guid.lower(), sb_guid, scan_type),
                                  lambda: adapters.fetch_findings(run, guid, scan_type, sb_guid))
        state, error = _state(col)
        return ContextData(guid.lower(), app.get('name'), context, sb_guid, sandbox.get('name') if sandbox else None,
                           scan_type, state, error, list(col.items) if state != CollectState.FAILED else [], cached)

    async def one_app(app: dict) -> None:
        nonlocal done
        guid = app['guid']
        async with gate:
            col, _ = await fetch('sandboxes', (guid,), lambda: adapters.fetch_sandboxes(run, guid))
            state, error = _state(col)
            out.listings[guid.lower()] = SandboxListing(guid.lower(), state, list(col.items), error)
            jobs = [one_context(app, 'POLICY', None, t) for t in adapters.FINDING_SCAN_TYPES]
            if state != CollectState.FAILED:
                jobs += [one_context(app, 'SANDBOX', sb, t) for sb in col.items if sb.get('guid')
                         for t in adapters.FINDING_SCAN_TYPES]
            out.contexts.extend(await asyncio.gather(*jobs))
        done += 1
        if progress:
            progress(done, len(applications))

    try:
        await asyncio.gather(*(one_app(a) for a in applications))
    finally:
        out.requests, out.retries = run.requests, run.retries
    errors = {c.error for c in out.contexts} | {lst.error for lst in out.listings.values()}
    out.limit_reached = next((e for e in sorted(errors - {None}) if e in LIMIT_ERRORS), None)
    out.contexts.sort(key=lambda c: (c.app_guid, c.context, c.sandbox_guid or '', c.scan_type))
    return out
