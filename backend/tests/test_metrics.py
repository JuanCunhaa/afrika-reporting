"""F04 — motor de indicadores sobre os escopos da F03 (tenant SINTÉTICO `gamma`; nenhuma Veracode real).

Valores-ouro calculados à mão a partir de `gamma_tenant()`:
- 4 aplicações (App 001..004). BU0: 001, 003; BU1: 002, 004. Teams: 001 = T0+T3; 002 = T1; 003 = T2; 004 = [].
- Sandboxes: 001 tem 3 (sb0..sb2); 004 tem 2 (sb0, sb1); 002/003 nenhum.
- SAST Policy abertos (OPEN e mitigação não aprovada): 001 {1:VH, 2:H, 5:INFO}; 002 {1:M}; 004 {7:H} => 5.
- SAST Sandbox abertos: 001/sb0 {1:VH, 10:M}; 001/sb1 {10:M, 11:L}; 001/sb2 {12 CLOSED}; 004/sb0 {10:H} =>
  5 ocorrências; distintos (app, issue_id) = 4; Policy ∪ Sandboxes distintos = 8.
- SCA Policy: 001 {C1/V1 H DIRECT, C2/V2 L TRANSITIVE}; 002 {C1/V1 H DIRECT}. SCA Sandbox: 001/sb0 {C1/V1 H};
  004/sb0 {C2/V2 M, sem dep_mode}. SCA distintos por (app, componente, vulnerabilidade) = 4 (issue_ids diferem).
"""
from __future__ import annotations

import asyncio
import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.metrics import competence as comp
from app.metrics.contracts import MetricResult, MetricStatus
from app.metrics.registry import CONTRACTS, REGISTRY
from app.veracode.fixtures import FixtureVeracode, build_tenant, make_finding, synthetic_credentials
from app.veracode.settings import VeracodeSettings

from conftest import SleepRecorder, veracode_environ

C1, C2, V1, V2 = 'c1c1c1c1-0000-4000-8000-000000000001', 'c2c2c2c2-0000-4000-8000-000000000002', 'SYNTH-V1', \
    'SYNTH-V2'


def gamma_tenant(**flags):
    t = build_tenant('gamma', apps=4, bus=2, teams=4, users=2, label='Gama')
    apps = t.applications
    apps[3]['profile']['teams'] = []                      # App 004 sem Team
    g = [a['guid'] for a in apps]
    sb = {i: [s['guid'] for s in t.sandboxes[g[i]]] for i in range(4)}
    assert len(sb[0]) == 3 and len(sb[3]) == 2 and not sb[1] and not sb[2]
    F = make_finding
    t.findings = {k: [] for k in t.findings}
    t.findings[(g[0], None, 'STATIC')] = [
        F(1, 'STATIC', severity=5, cwe=(79, 'XSS'), first_found='2026-09-01T00:00:00.000Z'),
        F(2, 'STATIC', severity=4, cwe=(89, 'SQLi'), first_found='2026-08-31T23:30:00.000Z'),
        F(3, 'STATIC', severity=3, cwe=(79, 'XSS'), status='CLOSED', resolution='FIXED',
          first_found='2026-09-30T23:59:59.999Z'),
        F(4, 'STATIC', severity=2, resolution='MITIGATED', resolution_status='APPROVED',
          first_found='2026-09-10T10:00:00.000Z'),
        # atualizado (last_seen) dentro da competência, identificado fora dela
        F(5, 'STATIC', severity=0, cwe=(117, 'Log'), first_found='2026-10-01T00:00:00.000Z',
          last_seen='2026-09-15T00:00:00.000Z'),
    ]
    t.findings[(g[1], None, 'STATIC')] = [F(1, 'STATIC', severity=3, cwe=(79, 'XSS'),
                                            first_found='2026-07-10T08:00:00.000Z')]
    t.findings[(g[3], None, 'STATIC')] = [F(7, 'STATIC', severity=4, cwe=(89, 'SQLi'),
                                            first_found='2026-09-05T08:00:00.000Z')]
    t.findings[(g[0], sb[0][0], 'STATIC')] = [F(1, 'STATIC', severity=5, sandbox_guid=sb[0][0]),
                                              F(10, 'STATIC', severity=3, sandbox_guid=sb[0][0])]
    t.findings[(g[0], sb[0][1], 'STATIC')] = [F(10, 'STATIC', severity=3, sandbox_guid=sb[0][1]),
                                              F(11, 'STATIC', severity=2, sandbox_guid=sb[0][1])]
    t.findings[(g[0], sb[0][2], 'STATIC')] = [F(12, 'STATIC', severity=1, status='CLOSED', sandbox_guid=sb[0][2])]
    t.findings[(g[3], sb[3][0], 'STATIC')] = [F(10, 'STATIC', severity=4, sandbox_guid=sb[3][0])]
    t.findings[(g[0], None, 'SCA')] = [
        F(100, 'SCA', severity=4, component=C1, filename='lib-um.jar', version='1.0', vulnerability=V1,
          dep_mode='DIRECT'),
        F(101, 'SCA', severity=2, component=C2, filename='lib-dois.jar', version='2.0', vulnerability=V2,
          dep_mode='TRANSITIVE')]
    t.findings[(g[1], None, 'SCA')] = [F(100, 'SCA', severity=4, component=C1, filename='lib-um.jar',
                                         version='1.0', vulnerability=V1, dep_mode='DIRECT')]
    t.findings[(g[0], sb[0][0], 'SCA')] = [F(200, 'SCA', severity=4, component=C1, filename='lib-um.jar',
                                             version='1.0', vulnerability=V1, dep_mode='DIRECT',
                                             sandbox_guid=sb[0][0])]
    t.findings[(g[3], sb[3][0], 'SCA')] = [F(201, 'SCA', severity=3, component=C2, filename='lib-dois.jar',
                                             version='2.0', vulnerability=V2, sandbox_guid=sb[3][0])]
    for k, v in flags.items():
        setattr(t, k, v)
    return t


def ids(tenant):
    apps = tenant.applications
    return {'apps': [a['guid'] for a in apps],
            'bu': [apps[0]['profile']['business_unit']['guid'], apps[1]['profile']['business_unit']['guid']],
            'teams': [tm['team_id'] for tm in tenant.teams]}


class Env:
    def __init__(self, api, fake, tenant, sleep):
        self.api, self.fake, self.tenant, self.sleep = api, fake, tenant, sleep
        self.ids = ids(tenant)

    def client(self, name='Cliente Métricas', ref='env:VC_GAMMA', **kw):
        # Valores-ouro do tenant gamma são em UTC; o padrão real (America/Sao_Paulo) tem teste próprio.
        conn = self.connection(ref)
        kw.setdefault('timezone', 'UTC')
        r = self.api.post('/api/clients', json={'name': name, 'connection_id': conn['id'], **kw})
        assert r.status_code == 201, r.text
        return r.json()

    def connection(self, ref):
        existing = [c for c in self.api.get('/api/connections?limit=200').json()['items'] if c['credential_ref'] == ref]
        if existing:
            return existing[0]
        r = self.api.post('/api/connections', json={'name': f'Conexão {ref}', 'region': 'commercial',
                                                     'credential_ref': ref})
        assert r.status_code == 201, r.text
        return r.json()

    def subclient(self, client_id, name, connection_id=None):
        r = self.api.post(f'/api/clients/{client_id}/subclients', json={'name': name, 'connection_id': connection_id})
        assert r.status_code == 201, r.text
        return r.json()

    def scope(self, kind, owner_id, domain, rule, coverage_ack=False):
        r = self.api.put(f'/api/scopes/{kind}/{owner_id}/{domain}',
                         json={'rule': rule, 'expected_version': 0, 'coverage_ack': coverage_ack})
        assert r.status_code == 201, r.text

    def universe(self, client_id):
        self.scope('clients', client_id, 'applications',
                   {'field': 'business_unit.id', 'cmp': 'in', 'values': self.ids['bu']})

    def run(self, kind, owner_id, competence='2026-09', tz=None, timeout=20.0):
        body = {'owner_kind': kind, 'owner_id': owner_id, 'competence': competence}
        if tz is not None:
            body['timezone'] = tz
        r = self.api.post('/api/metrics/runs', json=body)
        assert r.status_code == 202, r.text
        return self.wait(r.json()['run_id'], timeout)

    def wait(self, run_id, timeout=20.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            body = self.api.get(f'/api/metrics/runs/{run_id}').json()
            if body['status'] in ('done', 'cancelled', 'failed'):
                return body
            time.sleep(0.02)
        raise AssertionError('execução não terminou')

    def findings_requests(self, tenant='gamma'):
        return [r for r in self.fake.requests if r[0] == tenant and r[2].endswith('/findings')]


@contextmanager
def metrics_env(db_url, *, tenant=None, settings=None, wrap=None, extra_tenants=None):
    tenant = tenant or gamma_tenant()
    tenants = {'gamma': tenant, 'beta': build_tenant('beta', apps=3, bus=1, teams=1, users=1, label='Beta'),
               **(extra_tenants or {})}
    fake = FixtureVeracode(tenants)
    handler = fake.handle if wrap is None else wrap(fake.handle)
    sleep = SleepRecorder()
    app = create_app(db_url, veracode_settings=settings or VeracodeSettings(page_size=50, max_retries=2),
                     veracode_transport=httpx.MockTransport(handler),
                     environ=veracode_environ(VC_GAMMA='gamma', VC_BETA='beta'), sleep=sleep)
    with TestClient(app) as api:
        yield Env(api, fake, tenant, sleep)


def M(run, metric_id):
    return next(m for m in run['result']['metrics'] if m['metric_id'] == metric_id)


def sev(**kw):
    out = {'VERY_HIGH': 0, 'HIGH': 0, 'MEDIUM': 0, 'LOW': 0, 'VERY_LOW': 0, 'INFORMATIONAL': 0, 'UNKNOWN': 0}
    out.update(kw)
    out['total'] = sum(v for k, v in out.items() if k != 'total')
    return out


@pytest.fixture
def env(db_url):
    with metrics_env(db_url) as e:
        yield e


@pytest.fixture
def client_run(env):
    c = env.client()
    env.universe(c['id'])
    return env, c, env.run('client', c['id'])


# ---------------------------------------------------------------- contratos e catálogo

def test_catalog_contracts_are_typed_unique_and_complete(api):
    body = api.get('/api/metrics/catalog').json()
    assert body['statuses'] == ['VALIDATED', 'INCOMPLETE', 'UNAVAILABLE', 'UNSUPPORTED', 'FAILED']
    metrics = body['metrics']
    assert len({m['metric_id'] for m in metrics}) == len(metrics) == len(CONTRACTS)
    required = {'metric_id', 'version', 'name', 'description', 'domain', 'source', 'endpoint', 'application_scope',
                'context', 'scan_type', 'temporal_mode', 'date_field', 'status_criterion', 'severity_criterion',
                'dedup', 'identity_proof', 'unit', 'formula', 'rounding', 'completeness_rules', 'support',
                'homologation', 'limitations'}
    for m in metrics:
        assert required <= set(m), m['metric_id']
        if m['support'] == 'UNSUPPORTED' or m['temporal_mode'] == 'STATE_AT_PERIOD_END':
            assert m['unsupported_reason']
    # Lacunas declaradas, nunca implementadas por suposição
    for gap in ('scans.count', 'licenses.usage', 'sca.agent.issues', 'sast.policy.resolved_in_period'):
        assert REGISTRY[gap].support.value == 'UNSUPPORTED'
    assert all(c.homologation.value != 'MATCHES_DASHBOARD' for c in CONTRACTS)  # sem comparação real


def test_metric_result_never_carries_value_unless_validated():
    with pytest.raises(ValueError):
        MetricResult('x', 1, MetricStatus.INCOMPLETE, value=3)
    with pytest.raises(ValueError):
        MetricResult('x', 1, MetricStatus.VALIDATED, value=3, partial=2)
    assert MetricResult('x', 1, MetricStatus.VALIDATED, value=0).as_dict()['publishable'] is True


# ---------------------------------------------------------------- 10. competências

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize('label', ['2026-9', '26-09', '2026-13', '2026-00', '2026/09', '', '1999-12', '2026-09x'])
def test_competence_format_is_strict(label):
    with pytest.raises(comp.CompetenceError):
        comp.parse(label, now=NOW)


def test_competence_must_be_closed_month_and_has_exact_bounds():
    with pytest.raises(comp.CompetenceError) as exc:
        comp.parse('2026-10', 'UTC', now=NOW)
    assert exc.value.code == 'competence_not_closed'
    c = comp.parse('2026-09', 'UTC', now=NOW)
    assert (c.start.isoformat(), c.end.isoformat()) == ('2026-09-01T00:00:00+00:00', '2026-10-01T00:00:00+00:00')
    assert c.contains(comp.parse_timestamp('2026-09-30T23:59:59.999Z'))
    assert not c.contains(comp.parse_timestamp('2026-10-01T00:00:00.000Z'))
    assert comp.parse_timestamp('2026-09-30T23:59:59') is None  # sem fuso => desconhecido, não presumido UTC
    assert comp.parse_timestamp('2026-08-11 17:53:42 UTC').isoformat() == '2026-08-11T17:53:42+00:00'  # Summary
    for bad in ('-03:00', 'BRT', 'America/Nowhere', '../etc/passwd', 'America/Sao_Paulo/..', 'x' * 70, ''):
        with pytest.raises(comp.CompetenceError) as exc:
            comp.parse('2026-09', bad, now=NOW)
        assert exc.value.code == 'invalid_timezone'


def test_default_timezone_is_sao_paulo_with_utc_interval():
    c = comp.parse('2026-09', now=NOW)
    assert c.timezone == comp.DEFAULT_TIMEZONE == 'America/Sao_Paulo'
    d = c.as_dict()
    assert d['period_start'] == '2026-09-01T00:00:00-03:00' and d['period_end_exclusive'] == '2026-10-01T00:00:00-03:00'
    assert (d['utc_start'], d['utc_end_exclusive']) == ('2026-09-01T03:00:00+00:00', '2026-10-01T03:00:00+00:00')
    assert c.contains(comp.parse_timestamp('2026-10-01T02:59:59.999Z'))      # 30/09 23:59:59 em São Paulo
    assert not c.contains(comp.parse_timestamp('2026-09-01T02:59:59Z'))      # 31/08 23:59:59 em São Paulo
    # mês "aberto" é avaliado no fuso do cliente: 2026-09 em Kiritimati (UTC+14) fecha antes de em São Paulo
    almost = datetime(2026, 10, 1, 2, 0, tzinfo=timezone.utc)
    with pytest.raises(comp.CompetenceError):
        comp.parse('2026-09', now=almost)
    assert comp.parse('2026-09', 'Pacific/Kiritimati', now=almost).label == '2026-09'


@pytest.mark.parametrize('label, start, end, hours', [
    # horário de verão de 2017/2018: 15/10/2017 a 18/02/2018 (-02:00)
    ('2018-02', '2018-02-01T00:00:00-02:00', '2018-03-01T00:00:00-03:00', 28 * 24 + 1),
    ('2017-10', '2017-10-01T00:00:00-03:00', '2017-11-01T00:00:00-02:00', 31 * 24 - 1),
    # 2018/2019: início em 04/11/2018, fim em 17/02/2019
    ('2018-11', '2018-11-01T00:00:00-03:00', '2018-12-01T00:00:00-02:00', 30 * 24 - 1),
    ('2019-02', '2019-02-01T00:00:00-02:00', '2019-03-01T00:00:00-03:00', 28 * 24 + 1),
    # horário de verão abolido a partir de 2019 (Decreto 9.772/2019): dezembro sem mudança
    ('2019-12', '2019-12-01T00:00:00-03:00', '2020-01-01T00:00:00-03:00', 31 * 24),
])
def test_sao_paulo_historical_dst_rules(label, start, end, hours):
    c = comp.parse(label, 'America/Sao_Paulo', now=NOW)
    assert (c.start.isoformat(), c.end.isoformat()) == (start, end)
    assert (c.utc_end - c.utc_start).total_seconds() == hours * 3600


def test_nonexistent_local_midnight_moves_to_first_valid_instant():
    # Asia/Tehran não tem mudança à meia-noite; America/Havana iniciava o horário de verão às 00:00 (ex.: 2012-04-01).
    c = comp.parse('2012-04', 'America/Havana', now=NOW)
    assert c.start.isoformat() == '2012-04-01T01:00:00-04:00'
    assert c.utc_start.isoformat() == '2012-04-01T05:00:00+00:00'


def test_api_rejects_open_or_malformed_competence(env):
    c = env.client()
    env.universe(c['id'])
    current = datetime.now(timezone.utc).strftime('%Y-%m')
    for label, code in ((current, 'competence_not_closed'), ('2026-13', 'invalid_competence')):
        r = env.api.post('/api/metrics/runs', json={'owner_kind': 'client', 'owner_id': c['id'], 'competence': label})
        assert r.status_code == 422 and r.json()['error']['code'] == code
    r = env.api.post('/api/metrics/runs', json={'owner_kind': 'client', 'owner_id': c['id'], 'competence': '2026-09',
                                               'timezone': 'BRT-03'})
    assert r.status_code == 422 and r.json()['error']['code'] == 'invalid_timezone'
    assert env.fake.requests == []  # nada coletado com entrada inválida


# ---------------------------------------------------------------- 1. aplicações

def test_application_metrics_distinct_by_bu_and_team(client_run):
    env, _, run = client_run
    assert run['status'] == 'done'
    a = env.ids['apps']
    assert M(run, 'apps.total')['value'] == 4 and M(run, 'apps.total')['status'] == 'VALIDATED'
    by_bu = M(run, 'apps.by_business_unit')['value']
    assert [i['applications'] for i in by_bu['items']] == [2, 2] and by_bu['unknown'] == 0
    by_team = M(run, 'apps.by_team')['value']
    assert by_team['distinct_applications'] == 4            # total distinto, não a soma por Team
    assert by_team['team_assignments'] == 4                  # 001 conta em T0 e T3
    assert by_team['distinct_applications_with_team'] == 3
    assert {i['team_id']: i['applications'] for i in by_team['items']} == {t: 1 for t in env.ids['teams']}
    assert M(run, 'apps.without_team')['value'] == 1
    assert M(run, 'apps.multiple_teams')['value'] == 1
    assert M(run, 'apps.unclassified')['value'] == {'count': 4, 'no_subclients': True}
    assert run['result']['population']['applications'] == len(a)


def test_unknown_teams_make_team_metrics_incomplete_never_zero(db_url):
    t = gamma_tenant()
    del t.applications[3]['profile']['teams']                # lista de Teams ausente (desconhecida)
    with metrics_env(db_url, tenant=t) as env:
        c = env.client()
        env.universe(c['id'])
        run = env.run('client', c['id'])
    m = M(run, 'apps.without_team')
    assert m['status'] == 'INCOMPLETE' and m['value'] is None and m['partial'] == 0
    assert any(r['code'] == 'teams_unknown' for r in m['reasons'])
    assert M(run, 'apps.total')['status'] == 'VALIDATED'


# ---------------------------------------------------------------- 2. cliente sem escopo

def test_client_without_scope_never_uses_whole_tenant(env):
    c = env.client()
    run = env.run('client', c['id'])
    assert run['status'] == 'done'
    for m in run['result']['metrics']:
        assert m['value'] is None
        if REGISTRY[m['metric_id']].support.value != 'UNSUPPORTED' and m['temporal']['mode'] != 'STATE_AT_PERIOD_END':
            assert m['status'] == 'UNAVAILABLE'
            assert m['reasons'][0]['code'] == 'universe_not_defined'
    assert env.fake.requests == []  # nem aplicações nem findings foram consultados


def test_client_without_connection_is_unavailable(env):
    r = env.api.post('/api/clients', json={'name': 'Sem conexão'})
    c = r.json()
    env.scope('clients', c['id'], 'applications', {'op': 'all'})
    run = env.run('client', c['id'])
    assert M(run, 'apps.total')['status'] == 'UNAVAILABLE'
    assert M(run, 'apps.total')['reasons'][0]['code'] == 'connection_not_configured'


# ---------------------------------------------------------------- 3/4. subclientes

def test_inherited_subclient_is_intersection_with_universe(env):
    c = env.client()
    env.universe(c['id'])
    sub_a = env.subclient(c['id'], 'Sub A')
    sub_b = env.subclient(c['id'], 'Sub B')
    env.scope('subclients', sub_a['id'], 'applications', {'field': 'team.id', 'cmp': 'eq', 'value': env.ids['teams'][0]})
    env.scope('subclients', sub_b['id'], 'applications',
              {'field': 'business_unit.id', 'cmp': 'eq', 'value': env.ids['bu'][1]})
    run_a = env.run('subclient', sub_a['id'])
    assert M(run_a, 'apps.total')['value'] == 1
    assert M(run_a, 'sast.policy.open.by_severity')['value'] == sev(VERY_HIGH=1, HIGH=1, INFORMATIONAL=1)
    assert M(run_a, 'apps.unclassified')['status'] == 'UNAVAILABLE'
    refs = run_a['result']['provenance']['scope_refs']
    assert {(r['owner_key'].split(':')[0], r['domain'], r['version']) for r in refs if r['status'] == 'active'} == {
        ('client', 'applications', 1), ('subclient', 'applications', 1)}
    assert all(len(r['rule_hash']) == 64 for r in refs if r['status'] == 'active')
    assert run_a['result']['connection']['connection_source'] == 'client'
    run_c = env.run('client', c['id'])
    assert M(run_c, 'apps.unclassified')['value'] == {'count': 1, 'no_subclients': False}  # só App 003


def test_subclient_on_other_connection_uses_only_its_tenant(env):
    c = env.client()
    env.universe(c['id'])
    beta = env.connection('env:VC_BETA')
    sub = env.subclient(c['id'], 'Outro tenant', beta['id'])
    env.scope('subclients', sub['id'], 'applications', {'op': 'all'}, coverage_ack=True)
    before = len(env.fake.requests)
    run = env.run('subclient', sub['id'])
    new = env.fake.requests[before:]
    assert {t for t, _, _ in new} == {'beta'}                # gamma nunca consultado por este subcliente
    assert M(run, 'apps.total')['value'] == 3
    assert run['result']['connection']['connection_source'] == 'subclient'
    assert run['result']['connection']['id'] == beta['id']


def test_subclient_without_scope_or_unconfirmed_coverage_is_unavailable(env):
    c = env.client()
    env.universe(c['id'])
    sub = env.subclient(c['id'], 'Sem escopo')
    run = env.run('subclient', sub['id'])
    assert M(run, 'apps.total')['status'] == 'UNAVAILABLE'
    assert M(run, 'apps.total')['reasons'][0]['code'] == 'subclient_not_defined'


def test_shared_application_counts_in_each_subclient(env):
    c = env.client()
    env.universe(c['id'])
    a = env.ids['apps'][0]
    s1, s2 = env.subclient(c['id'], 'S1'), env.subclient(c['id'], 'S2')
    for s in (s1, s2):
        env.scope('subclients', s['id'], 'applications', {'field': 'application.id', 'cmp': 'eq', 'value': a})
    assert M(env.run('subclient', s1['id']), 'apps.total')['value'] == 1
    assert M(env.run('subclient', s2['id']), 'apps.total')['value'] == 1
    assert M(env.run('client', c['id']), 'apps.total')['value'] == 4   # sobreposição não duplica no cliente


# ---------------------------------------------------------------- 5/6/7/8. Policy, Sandbox, dedup, SAST/SCA

def test_policy_versus_sandbox_are_separate_contexts(client_run):
    _, _, run = client_run
    policy = M(run, 'sast.policy.open.by_severity')
    assert policy['status'] == 'VALIDATED'
    assert policy['value'] == sev(VERY_HIGH=1, HIGH=2, MEDIUM=1, INFORMATIONAL=1)
    assert policy['coverage']['excluded_approved_mitigations'] == 1
    assert policy['filters']['context'] == 'POLICY' and policy['filters']['scan_type'] == 'STATIC'
    sandbox = M(run, 'sast.sandbox.open.by_severity')
    assert sandbox['status'] == 'VALIDATED'
    assert sandbox['value'] == sev(VERY_HIGH=1, HIGH=1, MEDIUM=2, LOW=1)   # ocorrências
    assert sandbox['coverage']['sandboxes'] == 5


def test_dedup_between_sandboxes_requires_proven_identity(client_run):
    _, _, run = client_run
    distinct = M(run, 'sast.sandbox.open.distinct')
    assert distinct['status'] == 'INCOMPLETE' and distinct['value'] is None
    assert distinct['partial'] == sev(VERY_HIGH=1, HIGH=1, MEDIUM=1, LOW=1)   # 5 ocorrências -> 4 candidatos
    assert distinct['coverage']['duplicates_removed'] == 1
    assert [r['code'] for r in distinct['reasons']] == ['dedup_identity_not_proven']
    assert distinct['filters']['identity_proof'] == 'NOT_PROVEN'
    total = M(run, 'sast.open.distinct')
    assert total['status'] == 'INCOMPLETE' and total['partial']['total'] == 8


def test_sast_and_sca_use_distinct_identities(client_run):
    _, _, run = client_run
    sca = M(run, 'sca.policy.open.by_severity')
    assert sca['value'] == sev(HIGH=2, LOW=1)
    assert M(run, 'sca.sandbox.open.by_severity')['value'] == sev(HIGH=1, MEDIUM=1)
    distinct = M(run, 'sca.open.distinct')
    assert distinct['filters']['dedup'] == 'APP_COMPONENT_VULNERABILITY_ACROSS_CONTEXTS'
    # 5 ocorrências SCA com issue_ids todos diferentes; identidade componente+vulnerabilidade => 4
    assert distinct['partial'] == sev(HIGH=2, MEDIUM=1, LOW=1) and distinct['coverage']['duplicates_removed'] == 1
    # nada de SCA entra nos números SAST (e vice-versa)
    assert M(run, 'sast.policy.open.by_severity')['value']['total'] == 5
    assert M(run, 'sca.policy.open.top_components')['value']['top'][0] == {
        'component_id': C1, 'filename': 'lib-um.jar', 'version': '1.0', 'findings': 2, 'applications': 2}
    vulns = M(run, 'sca.policy.open.top_vulnerabilities')['value']['top']
    assert vulns[0] == {'vulnerability_id': V1, 'applications': 2, 'findings': 2, 'max_severity': 'HIGH'}
    assert M(run, 'sca.policy.open.by_dependency_mode')['value']['items'] == [
        {'mode': 'DIRECT', 'findings': 2}, {'mode': 'TRANSITIVE', 'findings': 1}]


def test_missing_severity_is_incomplete_not_dropped(db_url):
    t = gamma_tenant()
    t.findings[(t.applications[1]['guid'], None, 'STATIC')].append(make_finding(9, 'STATIC', severity=None))
    with metrics_env(db_url, tenant=t) as env:
        c = env.client()
        env.universe(c['id'])
        m = M(env.run('client', c['id']), 'sast.policy.open.by_severity')
    assert m['status'] == 'INCOMPLETE' and m['partial']['UNKNOWN'] == 1
    assert any(r['code'] == 'severity_missing' for r in m['reasons'])


def test_unknown_finding_status_is_not_assumed_open(db_url):
    t = gamma_tenant()
    t.findings[(t.applications[1]['guid'], None, 'STATIC')].append(make_finding(9, 'STATIC', severity=3, status=None))
    with metrics_env(db_url, tenant=t) as env:
        c = env.client()
        env.universe(c['id'])
        m = M(env.run('client', c['id']), 'sast.policy.open.by_severity')
    assert m['status'] == 'INCOMPLETE' and m['partial']['total'] == 5
    assert any(r['code'] == 'finding_status_unknown' for r in m['reasons'])


# ---------------------------------------------------------------- 9. categorias e Top 10

def test_cwe_categories_and_top_applications(client_run):
    env, _, run = client_run
    cwe = M(run, 'sast.policy.open.by_cwe')['value']
    assert [(r['cwe_id'], r['findings']) for r in cwe['top']] == [(79, 2), (89, 2), (117, 1)]
    top = M(run, 'sast.policy.open.top_applications')['value']
    assert [(r['name'], r['findings']) for r in top['top']] == [('Gama App 001', 3), ('Gama App 002', 1),
                                                                 ('Gama App 004', 1)]   # empate: nome
    assert top['applications_with_findings'] == 3


def test_top_ten_is_truncated_with_others(db_url):
    with metrics_env(db_url, tenant=build_tenant('gamma', apps=40, bus=2, teams=4, users=2, label='Gama'),
                     settings=VeracodeSettings(page_size=500, max_retries=0)) as env:
        c = env.client()
        env.scope('clients', c['id'], 'applications', {'op': 'all'})
        run = env.run('client', c['id'])
    top = M(run, 'sast.policy.open.top_applications')
    assert top['status'] == 'VALIDATED' and len(top['value']['top']) == 10
    counts = [r['findings'] for r in top['value']['top']]
    assert counts == sorted(counts, reverse=True)
    assert top['value']['applications_with_findings'] > 10
    assert M(run, 'sast.policy.open.by_cwe')['value']['distinct_cwes'] <= 10


# ---------------------------------------------------------------- 11/12. datas e histórico

def test_first_found_date_defines_period_not_update_date(client_run):
    _, _, run = client_run
    m = M(run, 'sast.policy.new_in_period.by_severity')
    assert m['status'] == 'VALIDATED'
    # 001: #1 (09-01 00:00, fronteira), #3 (09-30 23:59:59.999, fechado), #4 (mitigado); 004: #7.
    # Fora: 001 #2 (08-31), 001 #5 (identificado 10-01, last_seen dentro do mês) e 002 #1 (07-10).
    assert m['value'] == sev(VERY_HIGH=1, HIGH=1, MEDIUM=1, LOW=1)
    assert m['temporal']['date_field'] == 'finding_status.first_found_date'
    assert m['coverage']['outside_period'] == 3


def test_period_boundaries_follow_client_timezone(env):
    c = env.client(timezone='America/Sao_Paulo')
    assert c['timezone'] == 'America/Sao_Paulo'
    env.universe(c['id'])
    run = env.run('client', c['id'])                       # sem override: fuso do cliente
    m = M(run, 'sast.policy.new_in_period.by_severity')
    # período = [09-01T03:00Z, 10-01T03:00Z): #1 sai; #5 (10-01T00:00Z = 09-30 21:00 local) entra
    assert m['value'] == sev(HIGH=1, MEDIUM=1, LOW=1, INFORMATIONAL=1)
    assert m['temporal']['period']['period_start'] == '2026-09-01T00:00:00-03:00'
    months = M(run, 'sast.policy.open.by_first_found_month')['value']['items']
    assert months == [{'month': '2026-07', 'findings': 1}, {'month': '2026-08', 'findings': 2},
                      {'month': '2026-09', 'findings': 2}]


def test_historical_state_is_unavailable_and_current_state_is_labeled(client_run):
    _, _, run = client_run
    for mid in ('apps.total.at_period_end', 'sast.policy.open.at_period_end', 'sca.policy.open.at_period_end'):
        m = M(run, mid)
        assert m['status'] == 'UNAVAILABLE' and m['value'] is None
        assert m['reasons'][0]['code'] == 'historical_state_unavailable'
    current = M(run, 'sast.policy.open.by_severity')['temporal']
    assert current['mode'] == 'CURRENT_STATE' and current['historical_state'] is False
    assert current['as_of'] == run['result']['collected_at'] and current['competence'] == '2026-09'
    assert M(run, 'sast.policy.resolved_in_period')['status'] == 'UNSUPPORTED'
    assert M(run, 'sca.policy.new_in_period')['status'] == 'UNSUPPORTED'


# ---------------------------------------------------------------- 13. zero legítimo × ausência

def test_legitimate_zero_versus_missing_data(db_url):
    t = gamma_tenant()
    target = t.applications[2]['guid']

    def wrap(handle):
        def h(req):
            if req.url.path.endswith(f'{t.applications[1]["guid"]}/findings'):
                return httpx.Response(500, json={})
            return handle(req)
        return h
    with metrics_env(db_url, tenant=t, wrap=wrap, settings=VeracodeSettings(page_size=50, max_retries=0)) as env:
        c = env.client()
        env.universe(c['id'])
        zero = env.subclient(c['id'], 'Zero')
        broken = env.subclient(c['id'], 'Quebrado')
        env.scope('subclients', zero['id'], 'applications', {'field': 'application.id', 'cmp': 'eq', 'value': target})
        env.scope('subclients', broken['id'], 'applications',
                  {'field': 'application.id', 'cmp': 'eq', 'value': t.applications[1]['guid']})
        run_zero = env.run('subclient', zero['id'])
        run_broken = env.run('subclient', broken['id'])
    m = M(run_zero, 'sast.policy.open.by_severity')
    assert m['status'] == 'VALIDATED' and m['value'] == sev()     # zero legítimo, com coleta completa
    assert M(run_zero, 'sca.policy.open.by_severity')['value']['total'] == 0
    b = M(run_broken, 'sast.policy.open.by_severity')
    assert b['status'] == 'FAILED' and b['value'] is None and b['partial'] is None
    assert b['coverage']['contexts_failed'] == 1
    assert M(run_broken, 'sca.policy.open.by_severity')['status'] == 'FAILED'


def test_empty_population_is_a_validated_zero(env):
    c = env.client()
    env.universe(c['id'])
    sub = env.subclient(c['id'], 'Vazio')
    env.scope('subclients', sub['id'], 'applications', {'field': 'tag', 'cmp': 'eq', 'value': 'inexistente'})
    run = env.run('subclient', sub['id'])
    assert M(run, 'apps.total')['value'] == 0
    assert M(run, 'sast.policy.open.by_severity')['value'] == sev()
    assert env.findings_requests() == []


# ---------------------------------------------------------------- 14/15/16. paginação, falha parcial, 429, timeout

def test_findings_pagination_collects_every_page(db_url):
    sizes = []

    def wrap(handle):
        def h(req):
            if req.url.path.endswith('/findings'):
                sizes.append(req.url.params.get('size'))
            return handle(req)
        return h
    with metrics_env(db_url, wrap=wrap, settings=VeracodeSettings(page_size=100, findings_page_size=1)) as env:
        c = env.client()
        env.universe(c['id'])
        run = env.run('client', c['id'])
        paged = env.findings_requests()
    assert set(sizes) == {'1'}
    with metrics_env(db_url, wrap=wrap, settings=VeracodeSettings(page_size=100)) as env2:
        c2 = env2.client(name='Outro')
        env2.universe(c2['id'])
        single = env2.run('client', c2['id'])
    assert sizes[-1] == '50'                                  # padrão documentado (size=100 deu HTTP 500 no real)
    for mid in ('sast.policy.open.by_severity', 'sast.sandbox.open.by_severity', 'sca.policy.open.by_severity'):
        assert M(run, mid)['value'] == M(single, mid)['value']
    contexts = run['result']['collection']['contexts']
    assert len(paged) > contexts                              # contextos com vários findings => várias páginas


def test_partial_failure_is_incomplete_with_partial_aggregate(db_url):
    t = gamma_tenant()
    bad = t.applications[3]['guid']

    def wrap(handle):
        def h(req):
            if req.url.path.endswith(f'{bad}/findings') and req.url.params.get('scan_type') == 'STATIC' \
                    and 'context' not in req.url.params:
                return httpx.Response(503, json={})
            return handle(req)
        return h
    with metrics_env(db_url, tenant=t, wrap=wrap, settings=VeracodeSettings(page_size=50, max_retries=1)) as env:
        c = env.client()
        env.universe(c['id'])
        run = env.run('client', c['id'])
    m = M(run, 'sast.policy.open.by_severity')
    assert m['status'] == 'INCOMPLETE' and m['value'] is None
    assert m['partial'] == sev(VERY_HIGH=1, HIGH=1, MEDIUM=1, INFORMATIONAL=1)   # sem a App 004
    assert m['coverage']['contexts_failed'] == 1
    assert 'upstream_error' in m['reasons'][0]['message']
    assert M(run, 'sca.policy.open.by_severity')['status'] == 'VALIDATED'      # outro contexto não contamina


def test_429_is_retried_with_backoff_and_timeout_marks_incomplete(db_url):
    t = gamma_tenant()
    state = {'429': 0}
    slow = t.applications[1]['guid']

    def wrap(handle):
        def h(req):
            if req.url.path.endswith('/findings') and state['429'] < 2:
                state['429'] += 1
                return httpx.Response(429, headers={'Retry-After': '2'}, json={})
            if req.url.path.endswith(f'{slow}/findings') and req.url.params.get('scan_type') == 'SCA':
                raise httpx.ReadTimeout('tempo esgotado', request=req)
            return handle(req)
        return h
    with metrics_env(db_url, tenant=t, wrap=wrap, settings=VeracodeSettings(page_size=50, max_retries=2)) as env:
        c = env.client()
        env.universe(c['id'])
        run = env.run('client', c['id'])
        sleeps = list(env.sleep.calls)
    assert M(run, 'sast.policy.open.by_severity')['status'] == 'VALIDATED'
    assert sum(2 <= s <= 2.5 for s in sleeps) == 2                     # Retry-After respeitado (+ jitter)
    sca = M(run, 'sca.policy.open.by_severity')
    assert sca['status'] == 'INCOMPLETE' and sca['coverage']['contexts_failed'] == 1   # só a App 002 expirou
    assert sca['value'] is None and sca['partial'] == sev(HIGH=1, LOW=1) and 'timeout' in json.dumps(sca['reasons'])
    assert run['result']['collection']['retries'] >= 4


def test_request_budget_exceeded_is_incomplete(db_url):
    with metrics_env(db_url, settings=VeracodeSettings(page_size=50, max_retries=0,
                                                       metrics_max_requests=4)) as env:
        c = env.client()
        env.universe(c['id'])
        run = env.run('client', c['id'])
    assert run['result']['collection']['limit_reached'] == 'request_budget_exhausted'
    assert run['result']['collection']['requests'] == 4
    for mid in ('sast.policy.open.by_severity', 'sca.policy.open.by_severity'):
        m = M(run, mid)
        assert m['status'] in ('INCOMPLETE', 'FAILED') and m['value'] is None
    assert M(run, 'apps.total')['status'] == 'VALIDATED'   # aplicações vêm da descoberta (orçamento próprio)


def test_population_above_limit_is_not_collected(db_url):
    with metrics_env(db_url, settings=VeracodeSettings(page_size=50, metrics_max_applications=2)) as env:
        c = env.client()
        env.universe(c['id'])
        run = env.run('client', c['id'])
        assert env.findings_requests() == []
    m = M(run, 'sast.policy.open.by_severity')
    assert m['status'] == 'INCOMPLETE' and m['reasons'][-1]['code'] == 'findings_not_collected'


def test_sca_sandbox_rejected_by_veracode_is_unsupported(db_url):
    with metrics_env(db_url, tenant=gamma_tenant(sca_sandbox_unsupported=True)) as env:
        c = env.client()
        env.universe(c['id'])
        run = env.run('client', c['id'])
    assert M(run, 'sca.sandbox.open.by_severity')['status'] == 'UNSUPPORTED'
    distinct = M(run, 'sca.open.distinct')
    assert distinct['status'] == 'INCOMPLETE' and any(r['code'] == 'context_unsupported' for r in distinct['reasons'])
    assert M(run, 'sca.policy.open.by_severity')['status'] == 'VALIDATED'


def test_cancel_stops_collection_and_publishes_nothing(db_url):
    gate = {'hits': 0}

    def wrap(handle):
        async def h(req):
            if req.url.path.endswith('/findings'):
                gate['hits'] += 1
                await asyncio.sleep(30)
            return handle(req)
        return h
    with metrics_env(db_url, wrap=wrap) as env:
        c = env.client()
        env.universe(c['id'])
        r = env.api.post('/api/metrics/runs', json={'owner_kind': 'client', 'owner_id': c['id'],
                                                    'competence': '2026-09'})
        run_id = r.json()['run_id']
        deadline = time.monotonic() + 10
        while gate['hits'] == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert env.api.post(f'/api/metrics/runs/{run_id}/cancel').status_code == 202
        body = env.wait(run_id, timeout=5)
    assert body['status'] == 'cancelled' and body['result'] is None
    assert body['error']['code'] == 'cancelled'


def test_unknown_run_is_404(env):
    assert env.api.get('/api/metrics/runs/nao-existe').status_code == 404
    assert env.api.post('/api/metrics/runs/nao-existe/cancel').status_code == 404


# ---------------------------------------------------------------- escopos de scans/SCA aplicados aos findings

def test_scans_and_sca_scopes_filter_findings(env):
    c = env.client()
    env.universe(c['id'])
    env.scope('clients', c['id'], 'scans', {'field': 'scan.context', 'cmp': 'eq', 'value': 'policy'})
    env.scope('clients', c['id'], 'sca', {'field': 'sca.dependency', 'cmp': 'eq', 'value': 'direct'})
    run = env.run('client', c['id'])
    sandbox = M(run, 'sast.sandbox.open.by_severity')
    assert sandbox['status'] == 'VALIDATED' and sandbox['value'] == sev()
    assert sandbox['filters']['scope_rules_applied'][0]['excluded_findings'] == 6
    assert M(run, 'sast.policy.open.by_severity')['value']['total'] == 5
    assert M(run, 'sca.policy.open.by_severity')['value'] == sev(HIGH=2)        # TRANSITIVE excluído
    sca_sb = M(run, 'sca.sandbox.open.by_severity')
    assert sca_sb['status'] == 'INCOMPLETE'                                     # dep_mode ausente => indeterminado
    assert any(r['code'] == 'findings_scope_undetermined' for r in sca_sb['reasons'])
    refs = {(r['domain'], r['status']) for r in run['result']['provenance']['scope_refs']}
    assert {('scans', 'active'), ('sca', 'active'), ('applications', 'active')} <= refs


# ---------------------------------------------------------------- 17. cache e isolamento

def test_cache_reused_per_scope_and_isolated_between_scopes(env):
    c = env.client()
    env.universe(c['id'])
    first = env.run('client', c['id'])
    n1 = len(env.findings_requests())
    second = env.run('client', c['id'])
    assert len(env.findings_requests()) == n1                                   # mesmo escopo: cache
    assert second['result']['collection']['cache_hits'] == second['result']['collection']['contexts']
    assert M(first, 'sast.policy.open.by_severity')['value'] == M(second, 'sast.policy.open.by_severity')['value']
    assert first['result']['provenance']['run_id'] != second['result']['provenance']['run_id']
    assert first['result']['provenance']['input_hash'] == second['result']['provenance']['input_hash']
    sub = env.subclient(c['id'], 'Isolado')
    env.scope('subclients', sub['id'], 'applications', {'op': 'all'})
    env.run('subclient', sub['id'])
    assert len(env.findings_requests()) > n1                                    # outro escopo: nova coleta
    assert env.api.delete(f"/api/veracode/clients/{c['id']}/cache").status_code in (200, 204)
    env.run('client', c['id'])
    assert len(env.findings_requests()) > n1 * 2 - 1


# ---------------------------------------------------------------- 18. segredos e minimização

def test_no_credentials_or_finding_details_leak(env):
    c = env.client()
    env.universe(c['id'])
    run = env.run('client', c['id'])
    bodies = json.dumps(run) + json.dumps(env.api.get('/api/metrics/runs').json()) + \
        json.dumps(env.api.get('/api/metrics/catalog').json())
    for tenant in ('gamma', 'beta'):
        api_id, api_key = synthetic_credentials(tenant)
        assert api_id not in bodies and api_key not in bodies
    for forbidden in ('VC_GAMMA_API_ID', 'VC_GAMMA_API_KEY', 'credential_ref', 'Arquivo.java', 'metodoSintetico',
                      'Descrição sintética', 'anotação sintética', 'Authorization'):
        assert forbidden not in bodies
    assert {m for _, m, _ in env.fake.requests} == {'GET'}                      # somente leitura


def test_finding_normalization_minimizes_and_accepts_metadata_formats():
    from app.veracode.adapters import normalize_finding
    raw = make_finding(5, 'STATIC', severity=4, cwe=(79, 'XSS'))
    n = normalize_finding(raw)
    assert n['issue_id'] == 5 and n['severity'] == 4 and n['cwe_id'] == 79 and n['status'] == 'OPEN'
    assert 'Arquivo' not in json.dumps(n) and 'description' not in n and 'annotations' not in n
    sca = make_finding(7, 'SCA', severity=9, component=C1, vulnerability=V1, dep_mode='DIRECT')
    sca['finding_details']['metadata'] = 'sca_scan_mode: AGENT, sca_dep_mode: TRANSITIVE'  # string (spec)
    n = normalize_finding(sca)
    assert n['severity'] is None                                      # fora de 0–5 => desconhecida
    assert (n['sca_scan_mode'], n['sca_dep_mode'], n['vulnerability_id']) == ('AGENT', 'TRANSITIVE', V1)
    sca['finding_details']['metadata'] = 12
    assert normalize_finding(sca)['sca_dep_mode'] is None
    assert normalize_finding({'issue_id': True})['issue_id'] is None
