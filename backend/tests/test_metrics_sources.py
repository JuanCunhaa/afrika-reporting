"""F04.1 — fontes alternativas (Summary Report, perfil `scans[]`/políticas, SCA Agent) e confiabilidade da coleta
(500 sem retry imediato + passada adiada, circuit breaker, pré-checagem SCA). Tenant SINTÉTICO `gamma`.

Valores-ouro (ver test_metrics.gamma_tenant): Policy STATIC com status OPEN (qualquer mitigação) =
001 {5, 4, 2(mitigado aprovado), 0}; 002 {3}; 004 {4} => VH1 H2 M1 L1 INFO1 (6). LOC = 1000 + 100·índice.
Conformidade: 001 DID_NOT_PASS; 002–004 PASSED. SCA Policy: 001 {C1, C2}; 002 {C1}; 003/004 sem componentes.
"""
from __future__ import annotations

import httpx
import pytest

from app.veracode import adapters
from app.veracode.settings import SettingsError, VeracodeSettings

from test_metrics import M, env, gamma_tenant, metrics_env, sev  # noqa: F401 (fixture env)


def _setup(env, **client_kw):
    c = env.client(**client_kw)
    env.universe(c['id'])
    return c


def _requests(env, suffix, scan_type=None):
    return [r for r in env.fake.requests if r[2].endswith(suffix)]


# ---------------------------------------------------------------- normalização

def test_summary_report_normalization_minimizes_and_accepts_real_variants():
    raw = {'app_name': 'Nome', 'submitter': 'Pessoa', 'business_owner': 'Dono', 'teams': 'T', 'build_id': 7,
           'is_latest_build': True, 'total_flaws': 3, 'flaws_not_mitigated': 2,
           'severity': [{'level': 5, 'category': [{'count': 2}, {'count': 1}]}, {'level': 3, 'category': []}],
           'flaw-status': {'new': 1, 'open': 2, 'total': 3, 'not_mitigated': 2},
           'static-analysis': {'published_date': '2026-08-11 17:53:42 UTC',
                               'modules': {'module': [{'loc': 10, 'numflawssev5': 3, 'numflawssev3': 0,
                                                       **{f'numflawssev{s}': 0 for s in (0, 1, 2, 4)}},
                                                      {'loc': 5, **{f'numflawssev{s}': 0 for s in range(6)}}]}},
           'software_composition_analysis': {'third_party_components': '4', 'sca_service_available': 'true',
                                             'vulnerable_components': {'component': [{'vulnerability': 2},
                                                                                     {'vulnerability': 1}]}}}
    n = adapters.normalize_summary_report(raw)
    text = str(n)
    for leaked in ('Pessoa', 'Dono', 'Nome', "'teams'"):
        assert leaked not in text
    assert n['severity'] == {'5': 3, '3': 0} and n['flaw_status']['open'] == 2
    assert n['static']['loc'] == 15 and n['static']['flaws_by_severity']['5'] == 3 and n['static']['modules'] == 2
    assert n['sca'] == {'sca_service_available': True, 'third_party_components': 4, 'components_violated_policy': None,
                        'blacklisted_components': None, 'vulnerable_components': 2, 'vulnerabilities': 3}
    raw['static-analysis']['modules']['module'][1].pop('loc')
    assert adapters.normalize_summary_report(raw)['static']['loc'] is None     # nunca soma parcial como total
    assert adapters.normalize_summary_report({})['static'] is None


def test_application_scans_and_sca_projects_are_minimized():
    app = adapters.normalize_application({'guid': 'g', 'scans': [{'scan_type': 'static', 'status': 'PUBLISHED',
                                                                  'modified_date': '2026-09-01T00:00:00Z',
                                                                  'scan_url': 'Cid:1', 'internal_status': 'x'}]})
    assert app['scans'] == [{'scan_type': 'STATIC', 'status': 'PUBLISHED', 'modified_date': '2026-09-01T00:00:00Z'}]
    assert adapters.normalize_application({'guid': 'g'})['scans'] is None       # ausente ≠ vazio
    p = adapters.normalize_sca_app_projects({'application': {'name': 'App'}, 'linked_projects': [
        {'id': 'p1', 'name': 'Projeto', 'workspace': {'id': 'w1', 'name': 'WS'}, 'last_scan_date': 'd'}]})
    assert p == {'linked_projects': [{'project_id': 'p1', 'workspace_id': 'w1', 'last_scan_date': 'd'}]}


def test_settings_validate_new_reliability_knobs():
    assert VeracodeSettings.from_env({}).sca_precheck == 'verify'
    for env in ({'AFRIKA_VERACODE_SCA_PRECHECK': 'talvez'}, {'AFRIKA_VERACODE_CIRCUIT_BREAKER_THRESHOLD': '0'},
                {'AFRIKA_VERACODE_FINDINGS_RETRY_PASS_DELAY': '-1'}):
        with pytest.raises(SettingsError):
            VeracodeSettings.from_env(env)


# ---------------------------------------------------------------- indicadores de fontes alternativas

def test_alternative_source_metrics(db_url):
    t = gamma_tenant()
    t.sca_projects[t.applications[0]['guid']] = [
        {'id': 'p1', 'site_id': 's', 'name': 'Projeto 1', 'workspace': {'id': 'w1', 'name': 'WS'}},
        {'id': 'p2', 'site_id': 's', 'name': 'Projeto 2', 'workspace': {'id': 'w1', 'name': 'WS'}}]
    with metrics_env(db_url, tenant=t) as env:
        c = _setup(env)
        run = env.run('client', c['id'])
        old = env.run('client', c['id'], competence='2026-08')
    summary = M(run, 'sast.policy.summary.by_severity')
    assert summary['status'] == 'VALIDATED'
    assert summary['value'] == sev(VERY_HIGH=1, HIGH=2, MEDIUM=1, LOW=1, INFORMATIONAL=1)
    assert summary['source'] == 'Veracode Summary Report API v2'
    recon = M(run, 'sast.policy.reconciliation')
    assert recon['status'] == 'VALIDATED'
    assert recon['value'] == {'compared': 4, 'matching': 4, 'mismatching': 0, 'not_comparable': 0, 'items': []}
    assert M(run, 'apps.loc.total')['value'] == 1000 + 1100 + 1200 + 1300
    assert M(run, 'apps.by_policy_compliance')['value']['items'] == [
        {'status': 'DID_NOT_PASS', 'applications': 1}, {'status': 'PASSED', 'applications': 3}]
    assert M(run, 'sca.policy.summary.components')['value'] == {
        'third_party_components': 3, 'components_violated_policy': 2, 'applications_with_components': 2,
        'applications_without_components': 2}
    assert M(run, 'sca.agent.linked_projects')['value'] == {
        'applications_with_linked_projects': 1, 'linked_projects': 2, 'workspaces': 1}
    covered = M(run, 'scans.covered_apps')
    assert covered['status'] == 'VALIDATED' and covered['value'] == {'covered': 4, 'not_covered': 0,
                                                                      'indeterminate': 0}
    # agosto: o último scan (setembro) pode esconder um scan de agosto => indeterminado, nunca "não coberto"
    aug = M(old, 'scans.covered_apps')
    assert aug['status'] == 'INCOMPLETE' and aug['partial'] == {'covered': 0, 'not_covered': 0, 'indeterminate': 4}
    assert any(r['code'] == 'later_scan_hides_period' for r in aug['reasons'])
    assert M(run, 'scans.count')['status'] == 'UNSUPPORTED'
    assert 'POST' in M(run, 'scans.count')['reasons'][0]['message']


def test_reconciliation_flags_disagreement_without_correcting_either_source(db_url):
    t = gamma_tenant()
    bad = t.applications[1]['guid']

    def wrap(handle):
        def h(req):
            resp = handle(req)
            if req.url.path.endswith(f'{bad}/summary_report'):
                body = resp.json()
                body['static_analysis']['modules']['module'][0]['numflawssev3'] += 5
                return httpx.Response(200, json=body)
            return resp
        return h
    with metrics_env(db_url, tenant=t, wrap=wrap) as env:
        c = _setup(env)
        run = env.run('client', c['id'])
    recon = M(run, 'sast.policy.reconciliation')
    assert recon['status'] == 'INCOMPLETE' and recon['partial']['mismatching'] == 1
    assert recon['partial']['items'][0]['application_guid'] == bad
    assert any(r['code'] == 'sources_disagree' for r in recon['reasons'])
    assert M(run, 'sast.policy.open.by_severity')['status'] == 'VALIDATED'     # Findings API não é "corrigida"
    assert M(run, 'sast.policy.summary.by_severity')['value']['MEDIUM'] == 1 + 5


def test_summary_report_failure_only_affects_its_metrics(db_url):
    def wrap(handle):
        def h(req):
            if req.url.path.endswith('/summary_report'):
                return httpx.Response(503, json={})
            return handle(req)
        return h
    with metrics_env(db_url, wrap=wrap, settings=VeracodeSettings(page_size=50, max_retries=0)) as env:
        c = _setup(env)
        run = env.run('client', c['id'])
    for mid in ('sast.policy.summary.by_severity', 'apps.loc.total', 'sca.policy.summary.components'):
        assert M(run, mid)['status'] == 'FAILED' and M(run, mid)['value'] is None
    assert M(run, 'sast.policy.open.by_severity')['status'] == 'VALIDATED'
    assert M(run, 'sca.policy.open.by_severity')['status'] == 'VALIDATED'      # sem pré-checagem, chamada normal


# ---------------------------------------------------------------- SCA sem componentes (comportamento real)

@pytest.mark.parametrize('mode', ['verify', 'skip'])
def test_sca_500_without_components_is_inferred_absence_not_zero(db_url, mode):
    t = gamma_tenant(sca_500_without_components=True)
    with metrics_env(db_url, tenant=t, settings=VeracodeSettings(page_size=50, max_retries=2, sca_precheck=mode,
                                                                 circuit_breaker_threshold=1)) as env:
        c = _setup(env)
        run = env.run('client', c['id'])
        sca_calls = [r for r in env.fake.requests if r[2].endswith('/findings')]
    m = M(run, 'sca.policy.open.by_severity')
    assert m['status'] == 'INCOMPLETE' and m['value'] is None
    assert m['partial'] == sev(HIGH=2, LOW=1)
    assert m['coverage']['contexts_no_sca_components'] == 2
    assert [r['code'] for r in m['reasons']] == ['sca_absence_inferred']
    assert run['result']['collection']['circuits_opened'] == []                # 500 explicado não abre o circuito
    assert run['result']['collection']['retry_pass']['attempted'] == (2 if mode == 'verify' else 0)
    assert run['result']['collection']['retry_pass']['recovered'] == 0
    absent = t.applications[2]['guid']                     # App 003: sem sandboxes => só a chamada da Policy
    # verify: 1 chamada + 1 na passada adiada (sem retry imediato do 500); skip: nenhuma. (+1 = STATIC)
    assert len([r for r in sca_calls if absent in r[2]]) == (3 if mode == 'verify' else 1)
    assert M(run, 'sast.policy.open.by_severity')['status'] == 'VALIDATED'


def test_sca_precheck_skip_never_calls_findings_sca_policy_for_absent_apps(db_url):
    seen = []

    def wrap(handle):
        def h(req):
            if req.url.path.endswith('/findings'):
                seen.append((req.url.path, req.url.params.get('scan_type'), req.url.params.get('context')))
            return handle(req)
        return h
    t = gamma_tenant(sca_500_without_components=True)
    with metrics_env(db_url, tenant=t, wrap=wrap, settings=VeracodeSettings(page_size=50, sca_precheck='skip')) as env:
        c = _setup(env)
        env.run('client', c['id'])
    absent = t.applications[2]['guid']                     # App 003: sem sandboxes e sem componentes
    assert [s for s in seen if absent in s[0] and s[1] == 'SCA'] == []


# ---------------------------------------------------------------- 500: sem retry imediato, passada adiada, circuito

def test_findings_500_is_not_retried_immediately_and_recovers_in_deferred_pass(db_url):
    t = gamma_tenant()
    cold = t.applications[1]['guid']
    calls = {'n': 0}

    def wrap(handle):
        def h(req):
            if req.url.path.endswith(f'{cold}/findings') and req.url.params.get('scan_type') == 'STATIC':
                calls['n'] += 1
                if calls['n'] == 1:
                    return httpx.Response(500, headers={'Content-Type': 'application/json'})
            return handle(req)
        return h
    with metrics_env(db_url, tenant=t, wrap=wrap, settings=VeracodeSettings(page_size=50, max_retries=3)) as env:
        c = _setup(env)
        run = env.run('client', c['id'])
        sleeps = list(env.sleep.calls)
    assert calls['n'] == 2                                  # 1ª passada (sem retry imediato) + passada adiada
    assert run['result']['collection']['retry_pass'] == {'attempted': 1, 'recovered': 1}
    assert any(19 <= s <= 20.0 for s in sleeps)             # espera mínima da passada adiada (20 s)
    m = M(run, 'sast.policy.open.by_severity')
    assert m['status'] == 'VALIDATED' and m['value']['total'] == 5 and m['coverage']['contexts_retried'] == 1


def test_persistent_500_opens_circuit_and_stops_requests(db_url):
    sca = []

    def wrap(handle):
        def h(req):
            if req.url.path.endswith('/findings') and req.url.params.get('scan_type') == 'SCA':
                sca.append(req.url.path)
                return httpx.Response(500, headers={'Content-Type': 'application/json'})
            return handle(req)
        return h
    settings = VeracodeSettings(page_size=50, max_retries=3, max_concurrency=1, circuit_breaker_threshold=2,
                                sca_precheck='off')
    with metrics_env(db_url, wrap=wrap, settings=settings) as env:
        c = _setup(env)
        run = env.run('client', c['id'])
    # Policy: 2 falhas abrem o circuito da Policy; Sandbox tem circuito próprio (2 falhas também); sem passada adiada
    assert len(sca) == 4
    assert sorted(run['result']['collection']['circuits_opened']) == ['findings:SCA:POLICY', 'findings:SCA:SANDBOX']
    m = M(run, 'sca.policy.open.by_severity')
    assert m['status'] == 'FAILED' and any(r['code'] == 'circuit_open' for r in m['reasons'])
    assert M(run, 'sast.policy.open.by_severity')['status'] == 'VALIDATED'     # outro tipo não é afetado


# ---------------------------------------------------------------- fuso por cliente

def test_client_timezone_default_validation_and_update(env):
    conn = env.connection('env:VC_GAMMA')
    r = env.api.post('/api/clients', json={'name': 'Fuso padrão', 'connection_id': conn['id']})
    assert r.status_code == 201 and r.json()['timezone'] == 'America/Sao_Paulo'
    cid = r.json()['id']
    for bad in ('-03:00', 'America/Nowhere', '../../etc/passwd'):
        r = env.api.patch(f'/api/clients/{cid}', json={'timezone': bad})
        assert r.status_code == 422 and bad not in r.text
    r = env.api.patch(f'/api/clients/{cid}', json={'timezone': 'America/Manaus'})
    assert r.status_code == 200 and r.json()['timezone'] == 'America/Manaus'
    env.universe(cid)
    run = env.run('client', cid)
    assert run['competence']['timezone'] == 'America/Manaus'
    assert run['competence']['utc_start'] == '2026-09-01T04:00:00+00:00'      # Manaus = UTC-4
    override = env.run('client', cid, tz='UTC')
    assert override['competence']['utc_start'] == '2026-09-01T00:00:00+00:00'
    sub = env.subclient(cid, 'Herda fuso')
    env.scope('subclients', sub['id'], 'applications', {'op': 'all'})
    assert env.run('subclient', sub['id'])['competence']['timezone'] == 'America/Manaus'


def test_findings_page_cache_is_shared_but_retry_pass_is_not_cached_as_failure(db_url):
    with metrics_env(db_url) as env:
        c = _setup(env)
        env.run('client', c['id'])
        first = len(env.findings_requests()) + len(_requests(env, '/summary_report'))
        env.run('client', c['id'])
        assert len(env.findings_requests()) + len(_requests(env, '/summary_report')) == first   # tudo do cache


def test_inferred_absence_recovered_by_deferred_pass_becomes_real_zero(db_url):
    seen = set()

    def wrap(handle):
        def h(req):
            key = (req.url.path, req.url.params.get('scan_type'), req.url.params.get('context'))
            if req.url.path.endswith('/findings') and key[1] == 'SCA' and key[2] is None and key not in seen:
                seen.add(key)
                return httpx.Response(500, headers={'Content-Type': 'application/json'})
            return handle(req)
        return h
    with metrics_env(db_url, wrap=wrap, settings=VeracodeSettings(page_size=50, sca_precheck='verify')) as env:
        c = _setup(env)
        run = env.run('client', c['id'])
    # 1ª chamada SCA de cada aplicação dá 500; a passada adiada recupera todas (inclusive as sem componentes)
    assert run['result']['collection']['retry_pass'] == {'attempted': 4, 'recovered': 4}
    m = M(run, 'sca.policy.open.by_severity')
    assert m['status'] == 'VALIDATED' and m['value'] == sev(HIGH=2, LOW=1) and m['coverage']['contexts_retried'] == 4
