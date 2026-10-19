"""F10 — regressão do formato REAL da Findings API para SCA (diagnóstico real só GET, 2026-10-19).

Observado no tenant de testes (só formato, nunca valores): itens SCA têm `context_guid`, `context_type`, `count`,
`description`, `finding_details`, `finding_status`, `scan_type`, `violates_policy` — **sem `issue_id`** — e a página
traz `page.total_elements`/`total_pages`. Até a F09 o paginador exigia `issue_id` em todo finding e rejeitava a
primeira página SCA (`invalid_response`, sem status HTTP): todo contexto SCA com componentes ficava INCOMPLETE. A
causa NÃO era transporte. Somente dados SINTÉTICOS; nenhuma chamada real.
"""
import asyncio

import httpx
import pytest

from app.metrics import collector
from app.veracode import adapters
from app.veracode.credentials import Credentials
from app.veracode.fixtures import FixtureVeracode, default_tenants, make_finding, synthetic_credentials
from app.veracode.http import CollectionRun, VeracodeHttpPool
from app.veracode.settings import VeracodeSettings

CREDS = Credentials(*synthetic_credentials('f10-sca'))
APP = '00000000-0000-4000-8000-0000000000a1'


def _sca_items(n: int) -> list[dict]:
    return [make_finding(i, 'SCA', severity=i % 6, component=f'comp-{i % 7}', vulnerability=f'SYNTH-{i}',
                         dep_mode='DIRECT') for i in range(n)]


def _handler(items: list[dict], *, total: int | None = None, meta: bool = True, scan_type: str = 'SCA'):
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == 'GET'
        assert request.url.params['scan_type'] == scan_type
        page, size = int(request.url.params['page']), int(request.url.params['size'])
        chunk = items[page * size:(page + 1) * size]
        body: dict = {'_links': {}}
        if meta:
            announced = len(items) if total is None else total
            body['page'] = {'size': size, 'number': page, 'total_elements': announced,
                            'total_pages': (announced + size - 1) // size}
        if chunk:
            body['_embedded'] = {'findings': chunk}
        return httpx.Response(200, json=body)
    return handle


def _fetch(handler, scan_type: str = 'SCA'):
    async def main():
        pool = VeracodeHttpPool(VeracodeSettings(max_retries=0), httpx.MockTransport(handler))
        try:
            return await adapters.fetch_findings(CollectionRun(pool, CREDS, 'commercial'), APP, scan_type)
        finally:
            await pool.aclose()
    return asyncio.run(main())


def test_real_sca_shape_has_no_issue_id():
    item = _sca_items(1)[0]
    assert 'issue_id' not in item
    assert {'context_guid', 'context_type', 'count', 'description', 'finding_details', 'finding_status',
            'scan_type', 'violates_policy'} <= set(item)
    assert adapters.normalize_finding(item)['issue_id'] is None


def test_sca_without_issue_id_is_collected_completely_across_pages():
    """Mesmo formato da amostra real: 92 findings em 2 páginas de 50."""
    col = _fetch(_handler(_sca_items(92)))
    assert col.complete, col.error
    assert (col.pages_fetched, col.total_elements, len(col.items)) == (2, 92, 92)


def test_sca_total_mismatch_is_still_inconsistent():
    col = _fetch(_handler(_sca_items(60), total=61))
    assert not col.complete and col.error.code == 'inconsistent_pagination'


def test_sca_without_page_metadata_is_not_presumed_complete():
    """Sem identificador por item E sem total anunciado não há como provar completude."""
    col = _fetch(_handler(_sca_items(3), meta=False))
    assert not col.complete and col.error.code == 'invalid_response'


def test_static_still_requires_issue_id():
    items = [make_finding(i, 'STATIC', severity=3) for i in range(3)]
    del items[1]['issue_id']
    col = _fetch(_handler(items, scan_type='STATIC'), 'STATIC')
    assert not col.complete and col.error.code == 'invalid_response'


@pytest.mark.parametrize('scan_type', ['STATIC'])
def test_static_duplicate_issue_id_still_detected(scan_type):
    items = [make_finding(1, scan_type, severity=3), make_finding(1, scan_type, severity=3)]
    col = _fetch(_handler(items, scan_type=scan_type), scan_type)
    assert not col.complete and col.error.code == 'inconsistent_pagination'


def test_fixture_sca_mirrors_real_shape_and_collection_completes():
    """O tenant sintético devolve SCA sem issue_id e a coleta inteira fica completa (antes: INCOMPLETE)."""
    tenants = default_tenants()
    assert all('issue_id' not in f for (_, _, t), fs in tenants['alpha'].findings.items() if t == 'SCA' for f in fs)

    async def main():
        from app.veracode.cache import DiscoveryCache
        from app.veracode.discovery import DiscoveryService, ScopeContext
        import uuid
        settings = VeracodeSettings(mode='fixture', cache_ttl=0)
        pool = VeracodeHttpPool(settings, transport=FixtureVeracode(tenants).transport())
        try:
            run = CollectionRun(pool, Credentials(*synthetic_credentials('alpha')), 'commercial')
            apps = await adapters.fetch_applications(run)
            with_sca = [a for a in apps.items if tenants['alpha'].findings.get((a['guid'], None, 'SCA'))][:2]
            assert with_sca
            service = DiscoveryService(settings, pool, DiscoveryCache(0, 1))
            ctx = ScopeContext('client', uuid.uuid4(), 'sintetico', uuid.uuid4(), uuid.uuid4(), 'fixture',
                               'commercial', 'env:SINTETICO', 'client')
            service.credentials_for = lambda _ctx: Credentials(*synthetic_credentials('alpha'))
            return await collector.collect(service, ctx, with_sca)
        finally:
            await pool.aclose()

    outcome = asyncio.run(main())
    sca = [c for c in outcome.contexts if c.scan_type == 'SCA']
    assert sca and all(c.state == collector.CollectState.COMPLETE for c in sca), [(c.state, c.error) for c in sca]
    assert any(c.findings for c in sca)
