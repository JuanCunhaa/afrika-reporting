"""F02 — cliente HTTP: paginação, 429/Retry-After, 401/403/404/5xx, timeouts, retries, orçamento, prazo,
concorrência, cancelamento, somente leitura. Transporte simulado; nenhuma chamada real."""
import asyncio
import json
import logging
import random

import httpx
import pytest

from app.veracode import adapters
from app.veracode.credentials import Credentials
from app.veracode.errors import VeracodeError
from app.veracode.fixtures import synthetic_credentials
from app.veracode.http import CollectionRun, ReadOnlyViolation, VeracodeHttpPool, parse_retry_after
from app.veracode.settings import VeracodeSettings

CREDS = Credentials(*synthetic_credentials('http-test'))


def page(key, items, number, total_pages, total_elements, size=2):
    body = {'page': {'number': number, 'size': size, 'total_pages': total_pages, 'total_elements': total_elements}}
    if items:
        body['_embedded'] = {key: items}
    return httpx.Response(200, json=body)


def apps(*ids):
    return [{'guid': i, 'id': n, 'profile': {'name': f'App {i}'}} for n, i in enumerate(ids)]


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def run(handler, coro_fn, *, clock=None, **overrides):
    """Executa `coro_fn(run)` com um pool sobre MockTransport(handler). Devolve (resultado, sleeps)."""
    settings = VeracodeSettings(**{'page_size': 2, 'max_retries': 2, **overrides})
    sleeps = []
    clock = clock or Clock()

    async def fake_sleep(s):
        sleeps.append(s)
        clock.now += s

    async def main():
        pool = VeracodeHttpPool(settings, httpx.MockTransport(handler))
        try:
            r = CollectionRun(pool, CREDS, 'commercial', sleep=fake_sleep, rng=random.Random(1), clock=clock)
            return await coro_fn(r)
        finally:
            await pool.aclose()
    return asyncio.run(main()), sleeps


# ---------------------------------------------------------------- paginação

def test_pagination_collects_all_pages_with_explicit_page_params():
    seen = []

    def handler(req):
        seen.append(dict(req.url.params))
        assert req.headers['Authorization'].startswith('VERACODE-HMAC-SHA-256 id=')
        n = int(req.url.params['page'])
        data = [apps('a', 'b'), apps('c', 'd'), apps('e')][n]
        return page('applications', data, n, 3, 5)

    col, _ = run(handler, adapters.fetch_applications)
    assert col.complete and col.error is None
    assert [a['guid'] for a in col.items] == ['a', 'b', 'c', 'd', 'e']
    assert (col.pages_fetched, col.total_pages, col.total_elements, col.requests) == (3, 3, 5, 3)
    assert seen == [{'page': '0', 'size': '2'}, {'page': '1', 'size': '2'}, {'page': '2', 'size': '2'}]


def test_identity_camelcase_page_metadata_and_empty_result_without_embedded():
    def handler(req):
        if req.url.path.endswith('/users'):
            return httpx.Response(200, json={'page': {'number': 0, 'size': 2, 'totalPages': 0, 'totalElements': 0}})
        n = int(req.url.params['page'])
        items = [[{'team_id': 't1'}, {'team_id': 't2'}], [{'team_id': 't3'}]][n]
        return httpx.Response(200, json={'_embedded': {'teams': items},
                                         'page': {'number': n, 'size': 2, 'totalPages': 2, 'totalElements': 3}})

    users, _ = run(handler, adapters.fetch_users)
    assert users.complete and users.items == []  # zero confirmado pela própria API (total=0)
    teams, _ = run(handler, adapters.fetch_teams)
    assert teams.complete and [t['team_id'] for t in teams.items] == ['t1', 't2', 't3']


def test_pages_without_metadata_stop_on_short_page():
    def handler(req):
        n = int(req.url.params['page'])
        return httpx.Response(200, json={'_embedded': {'business_units': [[{'bu_id': 'x'}, {'bu_id': 'y'}],
                                                                          [{'bu_id': 'z'}]][n]}})
    col, _ = run(handler, adapters.fetch_business_units)
    assert col.complete and [b['bu_id'] for b in col.items] == ['x', 'y', 'z'] and col.requests == 2


@pytest.mark.parametrize('scenario', ['total_changes', 'duplicate', 'count_mismatch', 'empty_middle_page'])
def test_inconsistent_pagination_is_incomplete(scenario):
    def handler(req):
        n = int(req.url.params['page'])
        if scenario == 'total_changes':
            return page('applications', apps(f'a{n}', f'b{n}'), n, 2 + n, 4 + n)
        if scenario == 'duplicate':  # registro "escorregou" entre páginas
            return page('applications', [apps('a', 'b'), apps('b', 'c')][n], n, 2, 4)
        if scenario == 'count_mismatch':
            return page('applications', [apps('a', 'b'), apps('c')][n], n, 2, 4)
        return page('applications', [apps('a', 'b'), [], apps('e')][n], n, 3, 5)

    col, _ = run(handler, adapters.fetch_applications)
    assert not col.complete
    assert col.error.code == 'inconsistent_pagination'
    assert col.status()['status'] == 'incomplete'


@pytest.mark.parametrize('body', [[1, 2], {'_embedded': {'outra_chave': []}, 'page': {'total_pages': 1,
                                                                                     'total_elements': 1}},
                                  {'_embedded': {'applications': [{'sem_guid': 1}]}},
                                  {'_embedded': {'applications': 'x'}}, {'page': {'total_pages': 'x'}}])
def test_unexpected_shapes_are_invalid_response_not_empty(body):
    col, _ = run(lambda req: httpx.Response(200, json=body), adapters.fetch_applications)
    assert not col.complete and col.error.code == 'invalid_response' and col.items == []


def test_non_json_body_is_invalid_response():
    col, _ = run(lambda req: httpx.Response(200, content=b'<html>'), adapters.fetch_applications)
    assert col.error.code == 'invalid_response'


# ---------------------------------------------------------------- 429 / Retry-After

def test_429_honors_retry_after_then_succeeds():
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={'Retry-After': '7'})
        return page('applications', apps('a'), 0, 1, 1)

    col, sleeps = run(handler, adapters.fetch_applications)
    assert col.complete and col.retries == 1 and col.requests == 2
    assert len(sleeps) == 1 and 7 <= sleeps[0] <= 7 + 0.5  # Retry-After + jitter <= backoff_base


def test_429_without_retry_after_uses_exponential_backoff_with_jitter():
    def handler(req):
        return httpx.Response(429)

    col, sleeps = run(handler, adapters.fetch_applications, max_retries=3, backoff_base=1, backoff_max=3)
    assert not col.complete and col.error.code == 'rate_limited' and col.error.upstream_status == 429
    assert col.requests == 4 and len(sleeps) == 3
    for attempt, s in enumerate(sleeps):
        assert 0 <= s <= min(3, 1 * 2 ** attempt)


def test_retry_after_above_limit_gives_up_without_waiting():
    col, sleeps = run(lambda req: httpx.Response(429, headers={'Retry-After': '3600'}), adapters.fetch_applications,
                      max_retry_after=30)
    assert col.error.code == 'rate_limited' and sleeps == [] and col.requests == 1


def test_parse_retry_after_formats():
    assert parse_retry_after('12') == 12
    assert parse_retry_after(None) is None and parse_retry_after('abc') is None
    assert parse_retry_after('Wed, 21 Oct 2015 07:28:10 GMT', now=1445412480) == 10


# ---------------------------------------------------------------- 4xx / 5xx

@pytest.mark.parametrize('status,code', [(401, 'auth_failed'), (403, 'forbidden'), (404, 'not_found'),
                                         (400, 'bad_request'), (501, 'upstream_error')])
def test_non_retryable_errors_fail_immediately(status, code):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(status, json={'_embedded': {'errors': [{'detail': 'x'}]}})

    col, sleeps = run(handler, adapters.fetch_applications)
    assert not col.complete and col.error.code == code and col.error.upstream_status == status
    assert len(calls) == 1 and sleeps == []


@pytest.mark.parametrize('status', [500, 502, 503, 504])
def test_5xx_is_retried_then_succeeds(status):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(status) if len(calls) < 3 else page('applications', apps('a'), 0, 1, 1)

    col, sleeps = run(handler, adapters.fetch_applications, max_retries=2)
    assert col.complete and col.retries == 2 and len(sleeps) == 2


def test_5xx_exhausted_reports_upstream_error():
    col, sleeps = run(lambda req: httpx.Response(503), adapters.fetch_applications, max_retries=2)
    assert col.error.code == 'upstream_error' and col.requests == 3 and len(sleeps) == 2


# ---------------------------------------------------------------- timeouts / rede

@pytest.mark.parametrize('exc,code', [(httpx.ReadTimeout('t'), 'timeout'), (httpx.ConnectTimeout('t'), 'timeout'),
                                      (httpx.ConnectError('c'), 'network_error')])
def test_timeouts_and_network_errors_are_retried(exc, code):
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            raise exc
        return page('applications', apps('a'), 0, 1, 1)

    col, sleeps = run(handler, adapters.fetch_applications)
    assert col.complete and col.retries == 1

    def always(req):
        raise exc
    col, sleeps = run(always, adapters.fetch_applications, max_retries=1)
    assert col.error.code == code and col.requests == 2


def test_timeouts_are_explicit_in_client():
    async def main():
        pool = VeracodeHttpPool(VeracodeSettings(connect_timeout=3, read_timeout=11))
        try:
            c = pool.client('european')
            assert (c.timeout.connect, c.timeout.read) == (3, 11)
            assert str(c.base_url).startswith('https://api.veracode.eu')
            assert c.follow_redirects is False
            assert pool.client('european') is c  # conexões reutilizadas por região
            with pytest.raises(ValueError):
                pool.client('http://evil.example')
        finally:
            await pool.aclose()
    asyncio.run(main())


# ---------------------------------------------------------------- coleta incompleta

def test_failure_mid_pagination_keeps_partial_items_flagged_incomplete():
    def handler(req):
        n = int(req.url.params['page'])
        return page('applications', apps(f'a{n}', f'b{n}'), n, 3, 6) if n < 2 else httpx.Response(403)

    col, _ = run(handler, adapters.fetch_applications)
    assert not col.complete and col.error.code == 'forbidden'
    assert len(col.items) == 4 and col.pages_fetched == 2 and col.total_pages == 3


def test_request_budget_exhausted_is_incomplete():
    def handler(req):
        n = int(req.url.params['page'])
        return page('applications', apps(f'a{n}', f'b{n}'), n, 10, 20)

    col, _ = run(handler, adapters.fetch_applications, max_requests_per_collection=3)
    assert not col.complete and col.error.code == 'request_budget_exhausted' and col.requests == 3


def test_collection_deadline_is_incomplete():
    clock = Clock()

    def handler(req):
        clock.now += 40  # cada página "demora" 40s
        n = int(req.url.params['page'])
        return page('applications', apps(f'a{n}', f'b{n}'), n, 10, 20)

    col, _ = run(handler, adapters.fetch_applications, clock=clock, collection_timeout=100)
    assert not col.complete and col.error.code == 'deadline_exceeded' and col.pages_fetched == 3


def test_backoff_that_would_cross_deadline_stops_early():
    col, sleeps = run(lambda req: httpx.Response(429, headers={'Retry-After': '20'}), adapters.fetch_applications,
                      collection_timeout=10)
    assert col.error.code == 'deadline_exceeded' and sleeps == []


def test_team_memberships_incomplete_when_any_team_fails_or_count_diverges():
    teams = [{'team_id': 't1', 'name': 'T1', 'user_count': 1}, {'team_id': 't2', 'name': 'T2', 'user_count': 2},
             {'team_id': 't3', 'name': 'T3', 'user_count': None}]

    def handler(req):
        tid = req.url.path.rsplit('/', 1)[1]
        if tid == 't1':
            return httpx.Response(200, json={'team_id': 't1', 'user_count': 1, 'users': [{'user_id': 'u1'}]})
        if tid == 't2':
            return httpx.Response(200, json={'team_id': 't2', 'user_count': 2, 'users': [{'user_id': 'u1'}]})
        return httpx.Response(403)

    col, _ = run(handler, lambda r: adapters.fetch_team_memberships(r, teams))
    assert not col.complete and col.error.code in ('membership_count_mismatch', 'forbidden')
    assert {(m['team_id'], m['user_id']) for m in col.items} == {('t1', 'u1'), ('t2', 'u1')}


# ---------------------------------------------------------------- concorrência e cancelamento

def test_concurrency_limit_is_respected():
    state = {'now': 0, 'peak': 0}
    teams = [{'team_id': f't{i}', 'name': f'T{i}', 'user_count': 0} for i in range(10)]

    async def handler(req):
        state['now'] += 1
        state['peak'] = max(state['peak'], state['now'])
        await asyncio.sleep(0.01)
        state['now'] -= 1
        return httpx.Response(200, json={'users': []})

    col, _ = run(handler, lambda r: adapters.fetch_team_memberships(r, teams), max_concurrency=3)
    assert col.complete and col.requests == 10
    assert 1 < state['peak'] <= 3


def test_cancellation_releases_resources_and_propagates():
    started = asyncio.Event

    async def main():
        gate = started()
        settings = VeracodeSettings(max_concurrency=2)

        async def handler(req):
            gate.set()
            await asyncio.sleep(3600)  # nunca responde
            return httpx.Response(200)

        pool = VeracodeHttpPool(settings, httpx.MockTransport(handler))
        r = CollectionRun(pool, CREDS, 'commercial')
        task = asyncio.create_task(adapters.fetch_applications(r))
        await gate.wait()
        assert pool.in_flight == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert pool.in_flight == 0
        # semáforo liberado: as 2 vagas continuam disponíveis
        await asyncio.wait_for(pool.semaphore.acquire(), 1)
        await asyncio.wait_for(pool.semaphore.acquire(), 1)
        await pool.aclose()
    asyncio.run(main())


# ---------------------------------------------------------------- somente leitura, cookies, logs

def test_non_get_methods_are_blocked_before_sending():
    sent = []

    async def main():
        pool = VeracodeHttpPool(VeracodeSettings(), httpx.MockTransport(lambda req: sent.append(req) or
                                                                        httpx.Response(200, json={})))
        try:
            client = pool.client('commercial')
            for method in ('POST', 'PUT', 'PATCH', 'DELETE'):
                with pytest.raises(ReadOnlyViolation):
                    await client.request(method, '/appsec/v1/applications')
        finally:
            await pool.aclose()
    asyncio.run(main())
    assert sent == []


def test_cookies_from_one_response_are_never_sent_back():
    cookies_seen = []

    def handler(req):
        cookies_seen.append(req.headers.get('cookie'))
        n = int(req.url.params['page'])
        resp = page('applications', apps(f'a{n}', f'b{n}'), n, 2, 4)
        resp.headers['Set-Cookie'] = 'SESSION=tenant-a; Path=/'
        return resp

    col, _ = run(handler, adapters.fetch_applications)
    assert col.complete and cookies_seen == [None, None]


def test_redirects_are_not_followed():
    def handler(req):
        return httpx.Response(302, headers={'Location': 'https://evil.example/steal'})
    col, _ = run(handler, adapters.fetch_applications)
    assert col.error.code == 'invalid_response' and col.requests == 1


def test_http_logs_never_contain_credentials_signature_or_query(caplog):
    caplog.set_level(logging.DEBUG)
    headers_seen = []

    def handler(req):
        headers_seen.append(req.headers['Authorization'])
        return httpx.Response(429) if len(headers_seen) == 1 else page('applications', apps('a'), 0, 1, 1)

    col, _ = run(handler, adapters.fetch_applications)
    assert col.complete
    text = caplog.text + json.dumps(col.status())
    sig = headers_seen[0].rsplit('sig=', 1)[1]
    for secret in (CREDS.api_id, CREDS.api_key, sig, 'VERACODE-HMAC', 'page=0', 'size='):
        assert secret not in text
    assert 'recurso=applications' in caplog.text  # log operacional continua útil


def test_veracode_error_rejects_unknown_codes():
    with pytest.raises(ValueError):
        VeracodeError('qualquer')


def test_duplicates_without_page_metadata_are_inconsistent():
    """Sem `page` não há total para conferir: só a detecção de duplicatas revela registros deslocados."""
    def handler(req):
        n = int(req.url.params['page'])
        return httpx.Response(200, json={'_embedded': {'applications': [apps('a', 'b'), apps('b')][n]}})
    col, _ = run(handler, adapters.fetch_applications)
    assert not col.complete and col.error.code == 'inconsistent_pagination'
    assert [a['guid'] for a in col.items] == ['a', 'b']
