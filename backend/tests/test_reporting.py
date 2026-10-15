"""F05 — Reporting API: política deny-by-default, POST exclusivo de geração, polling limitado, erros e minimização.

Somente tenant SINTÉTICO (`FixtureVeracode`) e transporte simulado; nenhuma chamada real.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import date

import httpx
import pytest

from app.veracode import adapters
from app.veracode.errors import VeracodeError
from app.veracode.http import VeracodeHttpPool
from app.veracode.readonly import ReadOnlyViolation, check_request
from app.veracode.reporting import ReportingClient, aggregate, minimize, parse_report
from app.veracode.reporting_policy import GENERATION_PATH, ReportPolicyError, build, check_generation_body
from app.veracode.settings import SettingsError, VeracodeSettings
from conftest import error_code
from test_metrics import gamma_tenant, metrics_env

TODAY = date(2026, 10, 15)
RID = '0b9b5c1e-1111-4222-8333-444455556666'
OK_BODY = {'report_type': 'FINDINGS', 'last_updated_start_date': '2026-09-01', 'last_updated_end_date': '2026-10-01'}
BASE = 'https://api.veracode.com'


def post(path=GENERATION_PATH, body=None, *, content_type='application/json', raw=None):
    content = raw if raw is not None else json.dumps(body if body is not None else OK_BODY).encode()
    return httpx.Request('POST', BASE + path, content=content, headers={'Content-Type': content_type})


# ---------------------------------------------------------------- política (unidade)

def test_policy_accepts_only_documented_fields_types_and_bounded_window():
    r = build({**OK_BODY, 'app_id': 5001, 'policy_sandbox': 'Policy', 'scan_type': ['Static Analysis'],
               'status': 'Open', 'severity': ['4', '5']}, max_days=31, today=TODAY)
    assert r.body() == {**OK_BODY, 'app_id': 5001, 'policy_sandbox': 'Policy', 'scan_type': ['Static Analysis'],
                        'status': 'Open', 'severity': ['4', '5']}
    scans = build({'report_type': 'SCANS', 'last_updated_start_date': '2026-09-01',
                   'last_updated_end_date': '2026-09-08', 'most_recent_scan': True}, today=TODAY)
    assert scans.body()['most_recent_scan'] is True
    cases = [
        ({**OK_BODY, 'report_type': 'AUDIT'}, 'report_type_not_enabled'),
        ({**OK_BODY, 'report_type': 'DELETEDSCANS'}, 'report_type_not_enabled'),
        ({**OK_BODY, 'report_type': 'findings'}, 'invalid_report_type'),
        ({**OK_BODY, 'extra': 1}, 'unknown_field'),
        ({**OK_BODY, 'most_recent_scan': True}, 'unknown_field'),          # campo de SCANS em FINDINGS
        ({k: v for k, v in OK_BODY.items() if k != 'last_updated_end_date'}, 'invalid_date'),
        ({**OK_BODY, 'last_updated_start_date': '2026-9-1'}, 'invalid_date'),
        ({**OK_BODY, 'last_updated_end_date': '2026-02-30'}, 'invalid_date'),
        ({**OK_BODY, 'last_updated_end_date': '2026-09-01'}, 'invalid_range'),
        ({**OK_BODY, 'last_updated_end_date': '2026-12-01'}, 'invalid_range'),  # futuro
        ({**OK_BODY, 'last_updated_start_date': '2026-01-01'}, 'range_too_large'),
        ({**OK_BODY, 'app_id': True}, 'invalid_value'),
        ({**OK_BODY, 'app_id': -3}, 'invalid_value'),
        ({**OK_BODY, 'policy_sandbox': 'policy'}, 'invalid_value'),
        ({**OK_BODY, 'scan_type': ['Static Analysis', 'Static Analysis']}, 'invalid_value'),
        ({**OK_BODY, 'scan_type': ['DAST']}, 'invalid_value'),
        ({**OK_BODY, 'status': 'OPEN'}, 'invalid_value'),
        ({**OK_BODY, 'severity': [5]}, 'invalid_value'),
        (['não', 'objeto'], 'invalid_body'),
    ]
    for body, code in cases:
        with pytest.raises(ReportPolicyError) as info:
            build(body, max_days=31, today=TODAY)
        assert info.value.code == code, body
    # teto documentado (6 meses) vale mesmo com configuração maior
    with pytest.raises(ReportPolicyError, match='Janela'):
        build({**OK_BODY, 'last_updated_start_date': '2026-03-01'}, max_days=400, today=TODAY)
    with pytest.raises(SettingsError):
        VeracodeSettings(reporting_max_window_days=200)


def test_reporting_is_disabled_by_default():
    assert VeracodeSettings().reporting_enabled is False
    assert VeracodeSettings.from_env({}).reporting_enabled is False
    assert VeracodeSettings.from_env({'AFRIKA_VERACODE_REPORTING_ENABLED': 'true'}).reporting_enabled is True
    with pytest.raises(SettingsError):
        VeracodeSettings.from_env({'AFRIKA_VERACODE_REPORTING_ENABLED': 'sim'})


# ---------------------------------------------------------------- trava no transporte (allowlist)

def test_generation_post_passes_only_when_enabled_and_exact():
    check_request(post(), allow_report_generation=True)
    check_request(httpx.Request('GET', f'{BASE}{GENERATION_PATH}/{RID}', params={'page': 2}))
    with pytest.raises(ReadOnlyViolation):
        check_request(post())  # desabilitado (padrão)
    blocked = [
        post(adapters.APPLICATIONS),                             # POST genérico continua proibido
        post('/appsec/v2/applications/abc/findings'),
        post(f'{GENERATION_PATH}/{RID}'),
        post(GENERATION_PATH + '/'),
        post(GENERATION_PATH + '?x=1'),
        post('/appsec/v1/analytics/report/../applications'),
        post(body={**OK_BODY, 'report_type': 'AUDIT'}),
        post(body={**OK_BODY, 'report_type': 'DELETEDSCANS'}),
        post(body={**OK_BODY, 'app_id': 1, 'unknown': 1}),
        post(body={**OK_BODY, 'last_updated_start_date': '2025-01-01'}),
        post(raw=b'report_type=FINDINGS'),
        post(raw=json.dumps(OK_BODY).encode(), content_type='text/plain'),
        post(raw=b''),
        post(raw=b'{"report_type": "FINDINGS", "report_type": "AUDIT", "last_updated_start_date": "2026-09-01",'
                 b' "last_updated_end_date": "2026-10-01"}'),
        httpx.Request('POST', 'https://evil.example' + GENERATION_PATH, json=OK_BODY),
        httpx.Request('POST', 'http://api.veracode.com' + GENERATION_PATH, json=OK_BODY),
    ]
    for req in blocked:
        with pytest.raises(ReadOnlyViolation):
            check_request(req, allow_report_generation=True)
    for method in ('PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'):
        with pytest.raises(ReadOnlyViolation):
            check_request(httpx.Request(method, BASE + GENERATION_PATH, json=OK_BODY), allow_report_generation=True)
    for path in (GENERATION_PATH, f'{GENERATION_PATH}/abc', f'{GENERATION_PATH}/{RID}/x'):
        with pytest.raises(ReadOnlyViolation):
            check_request(httpx.Request('GET', BASE + path))


def test_enabled_pool_still_blocks_every_other_write_before_the_network():
    sent = []

    async def main():
        pool = VeracodeHttpPool(VeracodeSettings(reporting_enabled=True), httpx.MockTransport(
            lambda req: sent.append((req.method, req.url.path)) or httpx.Response(200, json={})))
        client = pool.client('commercial')
        try:
            for method, path in (('POST', adapters.APPLICATIONS), ('PUT', GENERATION_PATH),
                                 ('DELETE', f'{GENERATION_PATH}/{RID}'), ('PATCH', adapters.USERS),
                                 ('POST', '/srcclr/v3/applications/abc/projects')):
                with pytest.raises(ReadOnlyViolation):
                    await client.request(method, path, json=OK_BODY)
            with pytest.raises(ReadOnlyViolation):
                await client.post(GENERATION_PATH, json={**OK_BODY, 'report_type': 'AUDIT'})
            await client.post(GENERATION_PATH, json=OK_BODY)  # o único POST que sai
        finally:
            await pool.aclose()
    asyncio.run(main())
    assert sent == [('POST', GENERATION_PATH)]


def test_transport_revalidates_body_even_without_client_hooks():
    from app.veracode.readonly import ReadOnlyTransport
    sent = []
    transport = ReadOnlyTransport(httpx.MockTransport(lambda r: sent.append(r) or httpx.Response(200)),
                                  allow_report_generation=True)

    async def main():
        async with httpx.AsyncClient(transport=transport) as raw:
            with pytest.raises(ReadOnlyViolation):
                await raw.post(BASE + GENERATION_PATH, json={**OK_BODY, 'report_type': 'AUDIT'})
            with pytest.raises(ReadOnlyViolation):
                await raw.post(BASE + adapters.APPLICATIONS, json=OK_BODY)
    asyncio.run(main())
    assert sent == []


# ---------------------------------------------------------------- respostas tipadas e minimização

def test_parse_report_follows_spec_and_minimizes_items():
    data = {'_embedded': {'id': RID.upper(), 'status': 'COMPLETED', 'report_type': 'FINDINGS',
                          'requested_by_user': 'pessoa', 'report_expiration_date': '2026-10-22T00:00:00Z',
                          'findings': [{'app_id': '5001', 'status': 'Open', 'severity': '5', 'description': 'segredo',
                                        'filename': 'a/b.java', 'mitigation_last_accepted_comment': 'c',
                                        'scan_type': 'Static Analysis', 'policy_sandbox': 'Policy'}],
                          'page_metadata': {'number': 0, 'size': 1, 'total_elements': 1, 'total_pages': 1}}}
    st = parse_report(data, 'FINDINGS')
    assert st.id == RID and st.status == 'COMPLETED' and st.envelope == 'embedded'
    assert st.items == [{'app_id': '5001', 'scan_type': 'Static Analysis', 'policy_sandbox': 'Policy',
                         'status': 'Open', 'severity': '5'}]
    assert st.dates['report_expiration_date'] == '2026-10-22T00:00:00Z' and 'requested_by_user' not in st.dates
    assert parse_report({'id': RID, 'status': 'SUBMITTED'}, 'SCANS').envelope == 'top_level'
    for bad in ({'_embedded': {'id': 'x', 'status': 'COMPLETED'}}, {'_embedded': {'id': RID, 'status': 'DONE'}},
                {'_embedded': {'id': RID, 'status': 'COMPLETED', 'report_type': 'SCANS'}}, {},
                {'_embedded': {'id': RID, 'status': 'COMPLETED', 'findings': 'x'}},
                {'_embedded': {'id': RID, 'status': 'COMPLETED', 'page_metadata': {'total_pages': -1}}}):
        with pytest.raises(VeracodeError):
            parse_report(bad, 'FINDINGS')
    assert minimize('SCANS', {'submitter_name': 'p', 'scan_state': 'Results Ready', 'published': '2026-09-01',
                              'most_recent_scan': True}) == {'scan_state': 'Results Ready',
                                                             'published': '2026-09-01', 'most_recent_scan': True}
    agg = aggregate('FINDINGS', [{'app_id': '1', 'status': 'Open', 'severity': '5'},
                                 {'app_id': '1', 'status': 'Closed', 'severity': '3', 'resolved_date': '2026-09-02'}])
    assert agg['items'] == 2 and agg['distinct_applications'] == 1 and agg['with_resolved_date'] == 1
    assert agg['by_status'] == {'Closed': 1, 'Open': 1}


# ---------------------------------------------------------------- execuções pela API (tenant sintético)

def settings(**kw):
    base = dict(page_size=50, max_retries=2, reporting_enabled=True, reporting_poll_interval=1.0,
                reporting_poll_max_interval=4.0)
    base.update(kw)
    return VeracodeSettings(**base)


class R:
    def __init__(self, env, client):
        self.env, self.api, self.client = env, env.api, client

    def start(self, **request):
        body = {'owner_kind': 'client', 'owner_id': self.client['id'], 'request': {**OK_BODY, **request}}
        return self.api.post('/api/reporting/jobs', json=body)

    def wait(self, job_id, timeout=10.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            body = self.api.get(f'/api/reporting/jobs/{job_id}').json()
            if body['status'] in ('done', 'failed', 'cancelled'):
                return body
            time.sleep(0.01)
        raise AssertionError('relatório não terminou')

    def run(self, **request):
        r = self.start(**request)
        assert r.status_code == 202, r.text
        return self.wait(r.json()['job_id'])

    def calls(self, method=None):
        return [(m, p) for t, m, p in self.env.fake.requests if t == 'gamma' and '/analytics/' in p
                and (method is None or m == method)]


@pytest.fixture
def rep(db_url):
    with metrics_env(db_url, settings=settings()) as env:
        yield R(env, env.client())


def make(db_url, tenant=None, **kw):
    return metrics_env(db_url, tenant=tenant, settings=settings(**kw))


def real_sleep(env):
    """Espera real (curta) para testes que precisam de um relatório EM ANDAMENTO."""
    env.api.app.state.reporting._sleep = asyncio.sleep


def test_findings_report_full_flow_with_polling_pagination_and_minimization(rep):
    tenant = rep.env.tenant
    total = sum(len(v) for v in tenant.findings.values())
    job = rep.run()
    assert job['status'] == 'done'
    assert job['veracode']['report_id'] and job['veracode']['veracode_status'] == 'COMPLETED'
    assert job['veracode']['report_expiration_date'] == '2026-10-22T12:01:00Z'
    res = job['result']
    assert res['complete'] and res['items_processed'] == total == res['total_elements_reported']
    assert res['pages_fetched'] == res['total_pages'] == -(-total // 3)
    assert res['aggregates']['items'] == total and res['aggregates_status'] == 'EXPLORATORY_NOT_HOMOLOGATED'
    assert sum(res['aggregates']['by_status'].values()) == total
    assert job['progress']['polls'] == 2  # 1 consulta em PROCESSING + 1 COMPLETED
    assert rep.calls('POST') == [('POST', GENERATION_PATH)]  # exatamente uma geração
    blob = json.dumps(job)
    for leaked in ('usuario.sintetico', 'Descrição sintética', 'Arquivo.java', 'aprovador.sintetico',
                   'comentário sintético', 'Gama App', 'requested_by'):
        assert leaked not in blob
    assert rep.env.sleep.calls[:2] == [1.0, 1.5]  # intervalo crescente


def test_scans_report_and_app_filter(rep):
    app = rep.env.tenant.applications[0]
    job = rep.run(report_type='SCANS', app_id=app['id'], most_recent_scan=True)
    assert job['status'] == 'done' and job['result']['items_processed'] == 1
    assert job['result']['aggregates']['published'] == 1 and 'submitter' not in json.dumps(job)
    assert rep.env.tenant.reports[job['veracode']['report_id']]['body'] == {
        'report_type': 'SCANS', 'last_updated_start_date': '2026-09-01', 'last_updated_end_date': '2026-10-01',
        'app_id': app['id'], 'most_recent_scan': True}


def test_disabled_by_default_returns_409_and_sends_nothing(db_url):
    with metrics_env(db_url) as env:
        c = env.client()
        status = env.api.get('/api/reporting/status').json()
        assert status['enabled'] is False and status['enabled_types'] == ['FINDINGS', 'SCANS']
        assert set(status['not_enabled_types']) == {'DELETEDSCANS', 'AUDIT'}
        r = env.api.post('/api/reporting/jobs', json={'owner_kind': 'client', 'owner_id': c['id'], 'request': OK_BODY})
        assert r.status_code == 409 and error_code(r) == 'reporting_disabled'
        assert not [x for x in env.fake.requests if '/analytics/' in x[2]]


def test_policy_errors_are_422_and_limits_429(rep):
    r = rep.start(report_type='AUDIT')
    assert r.status_code == 422 and error_code(r) == 'report_type_not_enabled'
    r = rep.start(last_updated_start_date='2026-07-01')
    assert r.status_code == 422 and error_code(r) == 'range_too_large'  # janela padrão: 31 dias
    r = rep.api.post('/api/reporting/jobs', json={'owner_kind': 'client', 'owner_id': str(uuid.uuid4()),
                                                  'request': OK_BODY})
    assert r.status_code == 404
    assert not rep.calls()


def test_active_limit_and_hourly_quota(db_url):
    t = gamma_tenant(reporting_processing_polls=-1)
    with make(db_url, t, reporting_max_per_hour=2, reporting_max_polls=10_000, reporting_poll_interval=0.01,
              reporting_poll_max_interval=0.01) as env:
        real_sleep(env)
        r = R(env, env.client())
        first = r.start()
        assert first.status_code == 202
        busy = r.start()
        assert busy.status_code == 429 and error_code(busy) == 'too_many_reports'
        r.api.post(f'/api/reporting/jobs/{first.json()["job_id"]}/cancel')
        r.wait(first.json()['job_id'])
        second = r.start()
        assert second.status_code == 202
        r.api.post(f'/api/reporting/jobs/{second.json()["job_id"]}/cancel')
        r.wait(second.json()['job_id'])
        third = r.start()
        assert third.status_code == 429 and error_code(third) == 'report_quota_exceeded'
        assert r.api.get('/api/reporting/status').json()['quota_left_this_hour'] == 0


def test_poll_limit_and_global_timeout(db_url):
    t = gamma_tenant(reporting_processing_polls=-1)
    with make(db_url, t, reporting_max_polls=3) as env:
        job = R(env, env.client()).run()
        assert job['status'] == 'failed' and job['error']['code'] == 'report_poll_limit'
        assert job['progress']['polls'] == 3
    t = gamma_tenant(reporting_processing_polls=-1)
    with make(db_url, t, reporting_timeout=2.5, reporting_poll_interval=1.0, reporting_poll_max_interval=1.0) as env:
        # espera simulada + relógio que avança com ela: o prazo global é checado antes de cada espera
        r = R(env, env.client(name='Cliente prazo'))
        env.api.app.state.reporting._clock = _FakeClock(env.sleep)
        job = r.run()
        assert job['status'] == 'failed' and job['error']['code'] == 'deadline_exceeded'


class _FakeClock:
    """Relógio que avança com as esperas registradas (SleepRecorder)."""

    def __init__(self, sleep):
        self.sleep = sleep

    def __call__(self) -> float:
        return sum(self.sleep.calls)


def test_429_on_generation_is_retried_with_retry_after(db_url):
    with make(db_url, gamma_tenant(reporting_post_errors=[429, 429])) as env:
        r = R(env, env.client())
        job = r.run()
        assert job['status'] == 'done' and job['usage']['retries'] >= 2
        assert len(r.calls('POST')) == 3  # 2 recusadas (não processadas) + 1 aceita
        assert all(1.0 <= s < 1.5 for s in env.sleep.calls[:2])  # Retry-After: 1 (+ jitter)


@pytest.mark.parametrize('status', [500, 502, 503])
def test_5xx_on_generation_is_never_retried(db_url, status):
    with make(db_url, gamma_tenant(reporting_post_errors=[status])) as env:
        r = R(env, env.client())
        job = r.run()
        assert job['status'] == 'failed' and job['error']['code'] == 'upstream_error'
        assert job['error']['upstream_status'] == status
        assert len(r.calls('POST')) == 1 and not r.calls('GET')  # sem risco de relatório duplicado


def test_5xx_and_429_on_status_polling_are_retried(db_url):
    with make(db_url, gamma_tenant(reporting_status_errors=[503, 429])) as env:
        r = R(env, env.client())
        job = r.run()
        assert job['status'] == 'done' and job['result']['complete']
        assert len(r.calls('POST')) == 1 and job['usage']['retries'] == 2
    with make(db_url, gamma_tenant(reporting_status_errors=[503, 500, 502])) as env:
        job = R(env, env.client(name='Cliente 5xx')).run()  # tentativas esgotadas => falha explícita
        assert job['status'] == 'failed' and job['error']['code'] == 'upstream_error'


def test_403_reports_permission_hint(db_url):
    with make(db_url, gamma_tenant(reporting_forbidden=True)) as env:
        r = R(env, env.client())
        job = r.run()
        assert job['status'] == 'failed' and job['error']['code'] == 'forbidden'
        assert job['error']['upstream_status'] == 403 and 'Reporting API' in job['error']['hint']
        assert len(r.calls('POST')) == 1


def test_failed_report_and_truncated_report(db_url):
    with make(db_url, gamma_tenant(reporting_fail=True)) as env:
        job = R(env, env.client()).run()
        assert job['status'] == 'failed' and job['error']['code'] == 'report_failed'
    with make(db_url, gamma_tenant(reporting_page_size=1), reporting_max_pages=2) as env:
        job = R(env, env.client(name='Cliente truncado')).run()
        res = job['result']
        assert job['status'] == 'done' and not res['complete'] and res['truncated']
        assert res['pages_fetched'] == 2 and res['items_processed'] == 2
        assert res['aggregates_status'] == 'INCOMPLETE' and res['reasons'][0]['code'] == 'report_too_large'


def test_cancel_stops_polling_and_notes_remote_report(db_url):
    t = gamma_tenant(reporting_processing_polls=-1)
    with make(db_url, t, reporting_max_polls=10_000, reporting_poll_interval=0.01,
              reporting_poll_max_interval=0.01) as env:
        real_sleep(env)
        r = R(env, env.client())
        job_id = r.start().json()['job_id']
        deadline = time.monotonic() + 5
        while not r.api.get(f'/api/reporting/jobs/{job_id}').json()['veracode'].get('report_id'):
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert r.api.post(f'/api/reporting/jobs/{job_id}/cancel').status_code == 202
        job = r.wait(job_id)
        assert job['status'] == 'cancelled' and 'não oferece cancelamento' in job['remote_note']
        seen = len(r.calls())
        time.sleep(0.1)
        assert len(r.calls()) == seen  # nada mais é consultado após o cancelamento
        assert r.api.post(f'/api/reporting/jobs/{job_id}/cancel').status_code == 200
        assert not [c for c in r.calls() if c[0] not in ('GET', 'POST')]


def test_logs_never_leak_credentials_or_report_content(db_url, caplog):
    from app.veracode.fixtures import synthetic_credentials
    caplog.set_level(logging.DEBUG)
    with make(db_url, gamma_tenant(reporting_post_errors=[429], reporting_status_errors=[500])) as env:
        job = R(env, env.client()).run()
        assert job['status'] == 'done'
        report_id = job['veracode']['report_id']
    text_logs = '\n'.join(r.getMessage() for r in caplog.records)
    api_id, api_key = synthetic_credentials('gamma')
    assert 'reporting job=' in text_logs
    for leaked in (api_id, api_key, 'VERACODE-HMAC', 'Authorization', 'usuario.sintetico', 'Descrição sintética',
                   'Arquivo.java', 'last_updated_start_date', '2026-09-01', report_id, 'Gama App'):
        assert leaked not in text_logs


def test_reporting_client_direct_budget_is_bounded():
    s = VeracodeSettings(reporting_enabled=True, reporting_max_polls=4, reporting_max_pages=3, max_retries=1)

    async def main():
        pool = VeracodeHttpPool(s, httpx.MockTransport(lambda r: httpx.Response(200, json={})))
        from app.veracode.credentials import Credentials
        from app.veracode.fixtures import synthetic_credentials
        api_id, api_key = synthetic_credentials('gamma')
        try:
            client = ReportingClient(pool, Credentials(api_id, api_key), 'commercial')
            return client.run.max_requests
        finally:
            await pool.aclose()
    assert asyncio.run(main()) == 4 + 3 + 4
