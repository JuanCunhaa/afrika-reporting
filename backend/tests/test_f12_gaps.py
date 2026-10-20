"""F12 — fechamento de lacunas Veracode (dados SINTÉTICOS; nenhuma chamada real).

1. Diagnóstico da PRÓPRIA conta (GET /api/authn/v2/users/self): allowlist exata, minimização, papel ausente ×
   habilitação não confirmada, leitura do 403 sem presumir licença.
2. `apps.scanned` v1: relatório SCANS (um item por scan), GUID, Policy/Sandbox, SCA indisponível, competência no fuso
   do cliente com datas "EDT" como intervalo, deduplicação, completude e visibilidade.
3. Conferência: bloco `review` com os 10 itens da ordem do PO para os 21 aplicáveis.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timezone

import httpx
import pytest

from app.metrics import competence as comp_mod
from app.metrics import engine, scans_published
from app.metrics.collector import CollectionOutcome
from app.metrics.contracts import MetricStatus
from app.metrics.population import Population, PopulationStatus
from app.metrics.registry import REGISTRY
from app.metrics.scans_published import ScansEvidence, classify, evaluate, published_interval
from app.reconciliation import guide
from app.reconciliation.service import REVIEW_FIELDS
from app.veracode import self_diagnostic as sd
from app.veracode.credentials import Credentials
from app.veracode.errors import VeracodeError
from app.veracode.fixtures import FixtureVeracode, build_tenant, synthetic_credentials, synthetic_self_account
from app.veracode.http import CollectionRun, VeracodeHttpPool
from app.veracode.readonly import ReadOnlyViolation, check_request
from app.veracode.reporting import ReportingClient
from app.veracode.reporting_policy import ReportPolicyError
from app.veracode.settings import VeracodeSettings
from test_f10_conference import draft, sheet
from test_metrics import M, metrics_env
from test_snapshots import flow  # noqa: F401 (fixture)

NOW = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
SEP = comp_mod.parse('2026-09', 'America/Sao_Paulo', now=NOW)   # [09-01T03:00Z, 10-01T03:00Z)
OK_REQUEST = {'report_type': 'SCANS', 'last_updated_start_date': '2026-09-01', 'last_updated_end_date': '2026-10-16'}
GEN = date(2026, 10, 15)


def get(path):
    return httpx.Request('GET', 'https://api.veracode.com' + path)


# ---------------------------------------------------------------- 1. allowlist GET

def test_allowlist_accepts_only_own_account_endpoint():
    check_request(get('/api/authn/v2/users/self'))
    for path in ('/api/authn/v2/principal', '/api/authn/v2/users/0b9b5c1e-1111-4222-8333-444455556666',
                 '/api/authn/v2/users/self/x', '/api/authn/v2/users/api_credentials', '/api/authn/v2/roles',
                 '/api/authn/v2/users/self/../principal'):
        with pytest.raises(ReadOnlyViolation):
            check_request(get(path))
    for method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        with pytest.raises(ReadOnlyViolation):
            check_request(httpx.Request(method, 'https://api.veracode.com/api/authn/v2/users/self'),
                          allow_report_generation=True)
    with pytest.raises(ReadOnlyViolation):
        check_request(httpx.Request('GET', 'https://api.veracode.example/api/authn/v2/users/self'))
    for host in ('api.veracode.eu', 'api.veracode.us'):   # regiões documentadas
        check_request(httpx.Request('GET', f'https://{host}/api/authn/v2/users/self'))


# ---------------------------------------------------------------- 1. diagnóstico (unidade)

_SENSITIVE = ('conta.sintetica', 'exemplo.invalid', 'Sintética', 'f' * 32, 'org-sintetica', '203.0.113.7',
              'Team Sintético', '424242', 'user_id', 'email', 'last_login', 'api_id', '_links')


def test_diagnosis_is_minimized_and_flags_missing_reporting_role():
    raw = synthetic_self_account(teams=2)
    for key in ('user_id', 'email_address', 'api_credentials', 'teams'):
        assert key in raw  # o corpo sintético traz os campos que precisam ser descartados
    out = sd.diagnose(raw, now=NOW)
    text = json.dumps(out, ensure_ascii=False)
    for leaked in _SENSITIVE:
        assert leaked not in text, leaked
    assert out['account'] == {'account_type': 'API', 'api_user': True, 'active': True, 'login_enabled': True,
                              'saml_user': False, 'ip_restricted': False, 'teams_count': 2, 'team_restricted': False}
    assert out['credential'] == {'expiration': 'VALID', 'days_to_expiration': 77}
    assert [r['role_name'] for r in out['roles']] == ['noteamrestrictionapi', 'resultsapi']
    assert out['reporting_api']['role_state'] == 'ROLE_NOT_FOUND'
    assert out['reporting_api']['enablement'] == 'NOT_OBSERVABLE'
    reading = sd.interpret_reporting_403(out)
    assert reading['cause'] == 'MISSING_ROLE' and reading['license_assumed'] is False


def test_role_present_means_enablement_not_confirmed_never_enabled():
    raw = synthetic_self_account(roles=(('resultsapi', 'Results API'), ('reportingapi', 'Reporting API')))
    out = sd.diagnose(raw, now=NOW)
    assert out['reporting_api']['role_state'] == 'ROLE_PRESENT_ENABLEMENT_NOT_CONFIRMED'
    assert out['reporting_api']['matching_roles'] == ['reportingapi']
    assert sd.interpret_reporting_403(out)['cause'] == 'ENABLEMENT_NOT_CONFIRMED'
    assert 'habilitad' not in out['reporting_api']['role_state'].lower()
    # papel desabilitado não conta
    raw['roles'][1]['role_disabled'] = True
    assert sd.diagnose(raw, now=NOW)['reporting_api']['role_state'] == 'ROLE_NOT_FOUND'


def test_ui_account_uses_ui_roles_and_team_restriction_is_reported():
    raw = synthetic_self_account(roles=(('extseclead', 'Security Lead'),), account_type='USER', teams=1)
    out = sd.diagnose(raw, now=NOW)
    assert out['reporting_api']['role_state'] == 'ROLE_PRESENT_ENABLEMENT_NOT_CONFIRMED'
    assert out['account']['team_restricted'] is True
    assert any('1 Team(s)' in x for x in out['limitations'])
    # conta de API com "Reporting" no nome de um papel de UI não é confundida
    api = synthetic_self_account(roles=(('extseclead', 'Security Lead'),))
    assert sd.diagnose(api, now=NOW)['reporting_api']['role_state'] == 'ROLE_NOT_FOUND'


def test_real_shape_without_account_type_evaluates_both_documented_criteria():
    # Formato observado na API real (F12): sem account_type/api_user; papéis de interface ext*.
    raw = synthetic_self_account(roles=(('extadmin', 'Administrator'), ('extexecutive', 'Executive'),
                                        ('extreviewer', 'Reviewer'), ('deletescans', 'Delete Scans')))
    del raw['account_type'], raw['api_user']
    for r in raw['roles']:
        del r['is_api']
        r['ignore_team_restrictions'] = r['role_name'] in ('extadmin', 'extexecutive')
    out = sd.diagnose(raw, now=NOW)
    rep = out['reporting_api']
    assert rep['account_kind_evaluated'] == 'UNKNOWN' and 'OU' in rep['required']
    assert rep['role_state'] == 'ROLE_PRESENT_ENABLEMENT_NOT_CONFIRMED' and rep['matching_roles'] == ['extexecutive']
    assert sd.interpret_reporting_403(out)['cause'] == 'ENABLEMENT_NOT_CONFIRMED'
    assert out['least_privilege']['write_or_admin_roles'] == ['deletescans', 'extadmin']
    assert any('account_type' in x for x in out['limitations'])
    # sem papel compatível em nenhum dos critérios ⇒ ausente
    raw['roles'] = [r for r in raw['roles'] if r['role_name'] == 'extreviewer']
    assert sd.diagnose(raw, now=NOW)['reporting_api']['role_state'] == 'ROLE_NOT_FOUND'


def test_missing_roles_or_bad_shapes_are_unknown_not_absent():
    raw = synthetic_self_account()
    del raw['roles']
    out = sd.diagnose(raw, now=NOW)
    assert out['roles'] is None and out['reporting_api']['role_state'] == 'UNKNOWN'
    assert sd.interpret_reporting_403(out)['cause'] == 'UNDETERMINED'
    expired = synthetic_self_account()
    expired['api_credentials']['expiration_ts'] = '2026-01-01T00:00:00Z'
    assert sd.diagnose(expired, now=NOW)['credential']['expiration'] == 'EXPIRED'
    expired['api_credentials']['expiration_ts'] = 'amanhã'
    assert sd.diagnose(expired, now=NOW)['credential'] == {'expiration': 'UNKNOWN', 'days_to_expiration': None}
    with pytest.raises(VeracodeError):
        sd.diagnose(['não', 'objeto'])


# ---------------------------------------------------------------- 1. diagnóstico (API local + tenant sintético)

def test_self_diagnostic_endpoint_one_get_and_no_personal_data(db_url):
    with metrics_env(db_url) as env:
        env.tenant.identity_forbidden = True   # sem papel de administrador: /users/self continua acessível
        c = env.client()
        before = len(env.fake.requests)
        r = env.api.post(f'/api/veracode/clients/{c["id"]}/self-diagnostic')
        assert r.status_code == 200, r.text
        body = r.json()
        calls = env.fake.requests[before:]
        assert calls == [('gamma', 'GET', '/api/authn/v2/users/self')]
        assert body['status'] == 'ok' and body['requests'] == 1
        assert body['reporting_api']['role_state'] == 'ROLE_NOT_FOUND'
        assert body['reporting_403_reading']['license_assumed'] is False
        for leaked in _SENSITIVE:
            assert leaked not in r.text, leaked


def test_self_diagnostic_error_is_safe(db_url):
    def wrap(handle):
        def inner(request):
            if request.url.path.endswith('/users/self'):
                return httpx.Response(401, json={'message': 'segredo-sintetico'})
            return handle(request)
        return inner
    with metrics_env(db_url, wrap=wrap) as env:
        c = env.client()
        body = env.api.post(f'/api/veracode/clients/{c["id"]}/self-diagnostic').json()
        assert body['status'] == 'error' and body['error']['code'] == 'auth_failed'
        assert 'segredo-sintetico' not in json.dumps(body)


# ---------------------------------------------------------------- 2. apps.scanned — datas e fuso

@pytest.mark.parametrize('published,expected', [
    ('2026-09-15 10:00:00', 'IN'),
    ('2026-08-31 23:30:00', 'IN'),          # 23:30 EDT = 00:30 de 01/09 em São Paulo (EST: 01:30)
    ('2026-08-31 22:30:00', 'AMBIGUOUS'),   # EDT ⇒ 23:30 de 31/08 (fora); EST ⇒ 00:30 de 01/09 (dentro)
    ('2026-08-31 21:00:00', 'OUT'),
    ('2026-09-01', 'IN'),                   # data sem hora = o dia inteiro
    ('2026-08-31', 'AMBIGUOUS'),
    ('2026-09-30', 'AMBIGUOUS'),            # o fim do dia 30 (EDT/EST) passa das 00:00 de 01/10 em São Paulo
    ('2026-10-01T02:59:59Z', 'IN'),         # fuso explícito é respeitado: 23:59:59 de 30/09 em São Paulo
    ('2026-10-01T03:00:00Z', 'OUT'),
])
def test_publication_interval_against_client_timezone(published, expected):
    assert classify(published_interval(published), SEP) == expected


def test_unreadable_dates_are_not_guessed():
    for v in (None, '', 'ontem', '15/09/2026', 42):
        assert published_interval(v) is None


def _apps(*legacy, scans=None):
    return [{'guid': f'G{n}', 'legacy_id': n, 'scans': (scans or {}).get(n)} for n in legacy]


def _scan(sid, app, published, ctx='Policy', stype='Static Analysis'):
    return {'scan_id': str(sid), 'app_id': str(app), 'scan_type': stype, 'policy_sandbox': ctx,
            'published': published}


def _ev(items, request=None, **kw):
    return ScansEvidence({**OK_REQUEST, **(request or {})}, GEN, kw.pop('complete', True), items, **kw)


GOLDEN = [
    _scan(1, 101, '2026-09-10 08:00:00'), _scan(1, 101, '2026-09-10 08:00:00'),   # mesmo scan em 2 páginas
    _scan(2, 101, '2026-09-20 08:00:00'), _scan(3, 101, '2026-08-10', ctx='Sandbox'),
    _scan(4, 102, '2026-09-05', ctx='Sandbox'),
    _scan(5, 103, '2026-08-15 12:00:00'), {**_scan(6, 103, None)},
    _scan(7, 104, '2026-09-12', stype='Dynamic Analysis'),
    _scan(8, 999, '2026-09-12'),                                                    # fora do escopo
]


def test_golden_distinct_apps_by_context_with_dedup():
    value, blockers, cov = evaluate(_apps(101, 102, 103, 104), SEP, _ev(GOLDEN))
    assert blockers == []
    assert value == {'scanned': 2, 'scanned_policy': 1, 'scanned_sandbox': 1, 'not_scanned': 2, 'indeterminate': 0,
                     'applications_in_scope': 4, 'sca_scanned': None, 'sca_status': 'UNAVAILABLE',
                     'sca_reason': scans_published.SCA_UNAVAILABLE}
    assert cov['duplicate_items'] == 1 and cov['out_of_scope_items'] == 1
    assert cov['other_scan_type_items'] == 1 and cov['unpublished_items'] == 1


def test_scan_near_boundary_is_indeterminate_not_counted_or_zeroed():
    value, blockers, _ = evaluate(_apps(101, 105), SEP, _ev(GOLDEN + [_scan(9, 105, '2026-08-31 22:30:00')]))
    assert value['scanned'] == 1 and value['indeterminate'] == 1 and value['not_scanned'] == 0
    assert [c for c, _ in blockers] == ['publication_near_boundary']
    # um scan inequívoco no período resolve a aplicação
    value, blockers, _ = evaluate(_apps(105), SEP, _ev([_scan(9, 105, '2026-08-31 22:30:00'),
                                                        _scan(10, 105, '2026-09-02 10:00:00')]))
    assert value['scanned'] == 1 and blockers == []


@pytest.mark.parametrize('request_patch,complete,code', [
    ({'most_recent_scan': True}, True, 'most_recent_only'),
    ({'last_updated_start_date': '2026-09-02'}, True, 'report_window_starts_late'),
    ({'last_updated_end_date': '2026-10-15'}, True, 'report_window_ends_early'),
    ({'app_id': 101}, True, 'report_filtered'),
    ({'policy_sandbox': 'Policy'}, True, 'report_filtered'),
    ({'scan_type': ['Dynamic Analysis']}, True, 'report_without_static'),
    ({'last_updated_start_date': None}, True, 'report_window_unknown'),
    ({}, False, 'report_incomplete'),
])
def test_report_that_cannot_prove_the_period_blocks(request_patch, complete, code):
    _, blockers, _ = evaluate(_apps(101), SEP, _ev(GOLDEN, request_patch, complete=complete))
    assert code in [c for c, _ in blockers]


def test_visibility_gap_and_identity_gaps_block():
    profile = {102: [{'scan_type': 'STATIC', 'status': 'PUBLISHED', 'modified_date': '2026-09-20T10:00:00.000Z'}]}
    _, blockers, _ = evaluate(_apps(101, 102, scans=profile), SEP, _ev([_scan(1, 101, '2026-09-10')]))
    assert [c for c, _ in blockers] == ['report_missing_application']
    apps = _apps(101) + [{'guid': 'G0', 'legacy_id': None}]
    _, blockers, _ = evaluate(apps, SEP, _ev([_scan(1, 101, '2026-09-10'), {'scan_id': '9', 'scan_type': 'x'}]))
    assert {'application_legacy_id_missing', 'scan_without_application'} <= {c for c, _ in blockers}
    _, blockers, _ = evaluate(_apps(101), SEP, _ev([_scan(1, 101, 'data ruim'),
                                                    _scan(2, 101, '2026-09-10', ctx='Outro')]))
    assert {'published_date_invalid', 'scan_context_unknown'} <= {c for c, _ in blockers}
    _, blockers, _ = evaluate(_apps(101), SEP, _ev([], data_refresh_date='2026-09-20T00:00:00Z'))
    assert 'report_data_not_refreshed' in [c for c, _ in blockers]


def test_names_are_never_identity():
    items = [{**_scan(1, 555, '2026-09-10'), 'app_name': 'App 101'}]
    value, _, cov = evaluate([{'guid': 'G101', 'legacy_id': 101, 'name': 'App 101'}], SEP, _ev(items))
    assert value['scanned'] == 0 and cov['out_of_scope_items'] == 1


# ---------------------------------------------------------------- 2. contrato e motor

def test_contract_is_versioned_and_declares_the_source():
    c = REGISTRY['apps.scanned']
    assert c.version == 1 and c.dedup.value == 'APPLICATION_GUID' and c.context.value == 'POLICY_AND_SANDBOX'
    assert c.temporal_mode.value == 'EVENT_IN_PERIOD' and 'Reporting' in c.source.value
    assert any('SCA indisponível' in x for x in c.limitations)
    assert guide.GUIDES['apps.scanned'].category is guide.Category.BLOCKED_EXTERNAL


def _ctx(outcome):
    pop = Population(PopulationStatus.OK, applications=_apps(101, 102, 103, 104))
    return engine.Context(SEP, pop, outcome, {}, NOW.isoformat(), 'client')


def test_engine_unavailable_without_report_and_validated_with_it():
    c = REGISTRY['apps.scanned']
    res = engine._alt_metric(c, _ctx(CollectionOutcome()))
    assert res.status == MetricStatus.UNAVAILABLE and res.value is None
    assert [r.code for r in res.reasons] == ['scans_report_not_collected']
    res = engine._alt_metric(c, _ctx(None))
    assert res.status == MetricStatus.UNAVAILABLE
    res = engine._alt_metric(c, _ctx(CollectionOutcome(scans_report=_ev(GOLDEN))))
    assert res.status == MetricStatus.VALIDATED and res.value['scanned'] == 2
    res = engine._alt_metric(c, _ctx(CollectionOutcome(scans_report=_ev(GOLDEN, {'most_recent_scan': True}))))
    assert res.status == MetricStatus.INCOMPLETE and res.value is None and res.partial['scanned'] == 2


def test_metrics_run_marks_apps_scanned_unavailable_and_never_posts(db_url):
    with metrics_env(db_url) as env:
        c = env.client()
        env.universe(c['id'])
        run = env.run('client', c['id'])
        m = M(run, 'apps.scanned')
        assert m['status'] == 'UNAVAILABLE' and m['value'] is None
        assert m['reasons'][0]['code'] == 'scans_report_not_collected'
        assert all(method == 'GET' for _, method, _ in env.fake.requests)


# ---------------------------------------------------------------- 2. coleta ponta a ponta (mock)

def _client_run(tenant, settings, coro):
    async def main():
        fake = FixtureVeracode({'gamma': tenant})
        pool = VeracodeHttpPool(settings, httpx.MockTransport(fake.handle))
        try:
            client = ReportingClient(pool, Credentials(*synthetic_credentials('gamma')), 'commercial',
                                     sleep=lambda _s: asyncio.sleep(0))
            return await coro(client), fake
        finally:
            await pool.aclose()
    return asyncio.run(main())


def test_collect_evidence_end_to_end_with_synthetic_report():
    tenant = build_tenant('gamma', apps=8, bus=1, teams=1, users=1, label='Gama')
    s = VeracodeSettings(reporting_enabled=True, reporting_poll_interval=0.01, reporting_max_window_days=62)
    ev, fake = _client_run(tenant, s, lambda cl: scans_published.collect_evidence(cl, SEP, today=GEN))
    assert ev.request == OK_REQUEST and ev.complete is True
    assert [m for _, m, _ in fake.requests].count('POST') == 1
    assert all(set(i) <= {'app_id', 'scan_id', 'scan_type', 'policy_sandbox', 'scan_state', 'submitted',
                          'published', 'last_updated_date', 'most_recent_scan', 'first_scan', 'promoted_scan'}
               for i in ev.items)   # submitter_* e app_name descartados
    apps = [{'guid': a['guid'], 'legacy_id': a['id'], 'scans': a.get('scans')} for a in tenant.applications]
    value, blockers, _ = evaluate(apps, SEP, ev)
    with_scan = sum(bool(a.get('last_completed_scan_date')) for a in tenant.applications)
    assert blockers == [] and value['scanned'] == value['scanned_policy'] == with_scan
    assert value['not_scanned'] == len(apps) - with_scan


def test_collect_evidence_respects_window_policy_and_403():
    tenant = build_tenant('gamma', apps=2, bus=1, teams=1, users=1, label='Gama')
    with pytest.raises(ReportPolicyError):   # padrão 31 dias < início da competência → dia seguinte à geração
        _client_run(tenant, VeracodeSettings(reporting_enabled=True),
                    lambda cl: scans_published.collect_evidence(cl, SEP, today=GEN))
    tenant.reporting_forbidden = True
    s = VeracodeSettings(reporting_enabled=True, reporting_max_window_days=62)
    with pytest.raises(VeracodeError) as info:
        _client_run(tenant, s, lambda cl: scans_published.collect_evidence(cl, SEP, today=GEN))
    assert info.value.code == 'forbidden'
    with pytest.raises(ReadOnlyViolation):   # geração desligada (padrão) ⇒ POST barrado antes da rede
        _client_run(tenant, VeracodeSettings(reporting_max_window_days=62),
                    lambda cl: scans_published.collect_evidence(cl, SEP, today=GEN))


# ---------------------------------------------------------------- 3. conferência — bloco de revisão

def test_review_block_lists_the_ten_items_for_every_applicable_metric(flow):  # noqa: F811
    cid, n = draft(flow)
    data = sheet(flow, cid, n)
    applicable = [m for m in data['metrics'] if m['guide']['category'] == 'APPLICABLE']
    assert len(applicable) == 21
    for m in applicable:
        rv = m['review']
        assert set(REVIEW_FIELDS) <= set(rv), m['metric_id']
        assert rv['status'] == m['comparison'] and rv['difference'] is None    # nada conferido ainda
        assert rv['competence']['timezone'] == data['competence']['timezone']
        assert rv['definition'] and rv['filters'] and rv['official_path']['path_is_indicative'] is True
        if m['lines']:
            assert rv['missing'] == [], (m['metric_id'], rv['missing'])
            assert [f['key'] for f in rv['dashboard_value_fields']] == [line['key'] for line in m['lines']]
        else:
            assert {'collected_value', 'dashboard_value_fields'} <= set(rv['missing'])
    scanned = next(m for m in data['metrics'] if m['metric_id'] == 'apps.scanned')
    assert scanned['comparison'] == 'BLOCKED_EXTERNAL' and scanned['homologated'] is False
    assert data['summary']['HOMOLOGATED'] == 0
