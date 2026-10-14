"""F02 — API de descoberta Veracode por escopo, com tenant SINTÉTICO (FixtureVeracode). Nenhuma chamada real."""
import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.veracode.fixtures import FixtureVeracode, synthetic_credentials
from app.veracode.settings import VeracodeSettings

from conftest import SleepRecorder, error_code, veracode_environ


@pytest.fixture
def setup(vc_api, make_connection, make_client, make_subclient):
    """Cliente A (tenant alpha) com subcliente herdando e subcliente sobrescrevendo (tenant beta)."""
    alpha = make_connection(credential_ref='env:VC_ALPHA')
    beta = make_connection(credential_ref='env:VC_BETA', region='european')
    client = make_client(connection_id=alpha['id'])
    inherits = make_subclient(client['id'])
    overrides = make_subclient(client['id'], connection_id=beta['id'])
    return {'alpha': alpha, 'beta': beta, 'client': client, 'inherits': inherits, 'overrides': overrides}


def vc(api, kind, scope_id, path='', **params):
    return api.get(f'/api/veracode/{kind}/{scope_id}{path}', params=params)


# ---------------------------------------------------------------- escopo, herança e sobrescrita

def test_scope_info_shows_effective_connection_without_secrets(vc_api, setup, vc_env):
    r = vc(vc_api, 'clients', setup['client']['id'])
    assert r.status_code == 200
    body = r.json()
    assert body['credential_status'] == 'configured' and body['mode'] == 'live'
    assert body['scope']['connection_source'] == 'client'
    assert body['scope']['connection']['credential_ref'] == 'env:VC_ALPHA'

    inh = vc(vc_api, 'subclients', setup['inherits']['id']).json()
    assert inh['scope']['connection_source'] == 'client'
    assert inh['scope']['connection']['id'] == setup['alpha']['id']
    ovr = vc(vc_api, 'subclients', setup['overrides']['id']).json()
    assert ovr['scope']['connection_source'] == 'subclient'
    assert ovr['scope']['connection']['id'] == setup['beta']['id']
    assert ovr['scope']['connection']['region'] == 'european'

    text = json.dumps([body, inh, ovr])
    for name, value in vc_env.items():
        assert name not in text and value not in text  # nem nomes derivados, nem valores


def test_inheritance_and_override_reach_different_tenants(vc_api, setup, fake_veracode):
    client_apps = vc(vc_api, 'clients', setup['client']['id'], '/applications', limit=1).json()
    inherits = vc(vc_api, 'subclients', setup['inherits']['id'], '/applications', limit=1).json()
    overrides = vc(vc_api, 'subclients', setup['overrides']['id'], '/applications', limit=1).json()
    assert client_apps['total'] == inherits['total'] == 120  # tenant alpha
    assert overrides['total'] == 7  # tenant beta
    assert overrides['items'][0]['name'].startswith('Beta App')
    tenants = {t for t, _, _ in fake_veracode.requests}
    assert tenants == {'alpha', 'beta'}

    # Remover a sobrescrita volta a herdar do cliente (após invalidar o cache do escopo).
    assert vc_api.patch(f"/api/subclients/{setup['overrides']['id']}", json={'connection_id': None}).status_code == 200
    again = vc(vc_api, 'subclients', setup['overrides']['id'], '/applications', limit=1).json()
    assert again['scope']['connection_source'] == 'client' and again['total'] == 120


def test_scope_without_connection_and_unknown_scope(vc_api, make_client, make_subclient):
    client = make_client()
    sub = make_subclient(client['id'])
    for kind, sid in (('clients', client['id']), ('subclients', sub['id'])):
        info = vc(vc_api, kind, sid).json()
        assert info['credential_status'] == 'not_configured' and info['scope']['connection'] is None
        r = vc(vc_api, kind, sid, '/applications')
        assert r.status_code == 409 and error_code(r) == 'connection_not_configured'
        t = vc_api.post(f'/api/veracode/{kind}/{sid}/test').json()
        assert t['status'] == 'error' and t['checks'][0]['error']['code'] == 'connection_not_configured'
    missing = '00000000-0000-4000-8000-000000000000'
    assert error_code(vc(vc_api, 'clients', missing)) == 'client_not_found'
    assert error_code(vc(vc_api, 'subclients', missing, '/teams')) == 'subclient_not_found'
    assert vc(vc_api, 'outros', missing).status_code == 422
    assert vc(vc_api, 'clients', 'nao-uuid').status_code == 422


# ---------------------------------------------------------------- teste de conexão

def test_connection_test_ok_partial_missing_invalid(vc_api, make_connection, make_client):
    def scope(ref):
        return make_client(connection_id=make_connection(credential_ref=ref)['id'])['id']

    ok = vc_api.post(f"/api/veracode/clients/{scope('env:VC_ALPHA')}/test").json()
    assert ok['status'] == 'ok' and [c['check'] for c in ok['checks']] == [
        'credentials', 'applications', 'users', 'teams', 'business_units']

    denied = vc_api.post(f"/api/veracode/clients/{scope('env:VC_DENIED')}/test").json()
    assert denied['status'] == 'partial'
    by = {c['check']: c for c in denied['checks']}
    assert by['applications']['status'] == 'ok'
    assert {by[k]['error']['code'] for k in ('users', 'teams', 'business_units')} == {'forbidden'}
    assert by['users']['error']['upstream_status'] == 403

    missing = vc_api.post(f"/api/veracode/clients/{scope('env:VC_AUSENTE')}/test").json()
    assert missing['status'] == 'error' and missing['checks'][0]['error']['code'] == 'credentials_missing'


def test_wrong_credentials_give_auth_failed(db_url, make_connection, make_client):
    env = veracode_environ(VC_ALPHA='alpha')
    env['VC_ERRADA_API_ID'], env['VC_ERRADA_API_KEY'] = synthetic_credentials('alpha')[0], 'ab' * 64
    env['VC_FORMATO_API_ID'], env['VC_FORMATO_API_KEY'] = 'xyz', 'nao-hex'
    app = create_app(db_url, veracode_settings=VeracodeSettings(), veracode_transport=FixtureVeracode().transport(),
                     environ=env)
    with TestClient(app) as api:
        def mk(ref):
            conn = api.post('/api/connections', json={'name': ref, 'region': 'commercial',
                                                      'credential_ref': ref}).json()
            return api.post('/api/clients', json={'name': f'C {ref}', 'connection_id': conn['id']}).json()['id']
        wrong, bad_format = mk('env:VC_ERRADA'), mk('env:VC_FORMATO')
        t = api.post(f'/api/veracode/clients/{wrong}/test').json()
        assert t['status'] == 'error'
        assert {c['error']['code'] for c in t['checks'][1:]} == {'auth_failed'}
        r = api.get(f'/api/veracode/clients/{wrong}/applications')
        assert r.status_code == 502 and error_code(r) == 'auth_failed' and r.json()['error']['upstream_status'] == 401
        assert api.get(f'/api/veracode/clients/{bad_format}').json()['credential_status'] == 'invalid_format'
        r = api.get(f'/api/veracode/clients/{bad_format}/users')
        assert r.status_code == 409 and error_code(r) == 'credentials_invalid_format'
        assert 'nao-hex' not in r.text and 'xyz' not in r.text and 'VC_FORMATO_API' not in r.text


# ---------------------------------------------------------------- listagens

def test_applications_paginated_and_searchable(vc_api, setup, fake_veracode):
    cid = setup['client']['id']
    first = vc(vc_api, 'clients', cid, '/applications', limit=25, offset=0).json()
    assert first['total'] == 120 and len(first['items']) == 25 and first['complete'] is True
    col = first['collections'][0]
    assert col['pages_fetched'] == 3 and col['total_elements_reported'] == 120 and col['cached'] is False
    last = vc(vc_api, 'clients', cid, '/applications', limit=25, offset=100).json()
    assert len(last['items']) == 20 and last['collections'][0]['cached'] is True
    names = [a['name'] for a in first['items']] + [a['name'] for a in last['items']]
    assert names == sorted(names, key=str.casefold)
    found = vc(vc_api, 'clients', cid, '/applications', q='app 007').json()
    assert found['total'] == 1 and found['items'][0]['name'] == 'Alfa App 007'
    app = found['items'][0]
    assert app['business_unit']['name'] and app['teams'] and app['custom_fields'] and app['policies']
    assert vc(vc_api, 'clients', cid, '/applications', limit=201).status_code == 422
    assert len([r for r in fake_veracode.requests if r[2] == '/appsec/v1/applications']) == 3  # cache


def test_sandboxes_per_application(vc_api, setup):
    cid = setup['client']['id']
    apps = vc(vc_api, 'clients', cid, '/applications', q='App 001').json()['items']
    r = vc(vc_api, 'clients', cid, f"/applications/{apps[0]['guid']}/sandboxes").json()
    assert r['total'] == 3 and r['complete'] and {s['application_guid'] for s in r['items']} == {apps[0]['guid']}
    none = vc(vc_api, 'clients', cid, '/applications', q='App 002').json()['items'][0]
    assert vc(vc_api, 'clients', cid, f"/applications/{none['guid']}/sandboxes").json()['total'] == 0
    unknown = vc(vc_api, 'clients', cid, '/applications/00000000-0000-4000-8000-000000000001/sandboxes')
    assert unknown.status_code == 502 and error_code(unknown) == 'not_found'
    assert vc(vc_api, 'clients', cid, '/applications/..%2F..%2Fapi/sandboxes').status_code in (404, 422)


def test_business_units_teams_users(vc_api, setup):
    cid = setup['client']['id']
    bus = vc(vc_api, 'clients', cid, '/business-units').json()
    assert bus['total'] == 4 and all(len(b['team_ids']) == 2 for b in bus['items'])
    teams = vc(vc_api, 'clients', cid, '/teams').json()
    assert teams['total'] == 8 and all(t['business_unit']['bu_id'] for t in teams['items'])
    users = vc(vc_api, 'clients', cid, '/users', limit=10).json()
    assert users['total'] == 45 and len(users['items']) == 10
    # Minimização: e-mail e telefone presentes na resposta da Veracode não saem do backend.
    assert 'email' not in json.dumps(users) and 'example.invalid' not in json.dumps(users)
    assert vc(vc_api, 'clients', cid, '/users', q='usuario07').json()['total'] == 1


# ---------------------------------------------------------------- relacionamentos

def test_user_in_multiple_teams_and_user_without_team(vc_api, setup):
    r = vc(vc_api, 'clients', setup['client']['id'], '/relationships/users', limit=200).json()
    assert r['complete'] is True and {c['resource'] for c in r['collections']} == {'users', 'teams',
                                                                                    'team_memberships'}
    rows = {row['user']['user_name']: row for row in r['items']}
    multi = rows['alfa.usuario01']  # n=0: Teams 0 e 1
    assert sorted(t['team_name'] for t in multi['teams']) == ['Alfa Team 01', 'Alfa Team 02']
    assert {t['relationship'] for t in multi['teams']} == {'ADMIN'}
    assert rows['alfa.usuario15']['teams'] == []  # n=14: sem Team (confirmado: coleta completa)
    s = r['summary']
    assert s['users'] == 45 and s['teams'] == 8 and s['multiple_teams'] == 11 and s['without_team'] == 3  # n%4==0 exceto n=44 (sem Team)
    assert s['members_not_in_user_list'] == 0
    q = vc(vc_api, 'clients', setup['client']['id'], '/relationships/users', q='Alfa Team 08').json()
    assert q['total'] > 0 and all(any(t['team_name'] == 'Alfa Team 08' for t in row['teams']) for row in q['items'])


def test_application_with_multiple_teams_and_business_unit(vc_api, setup):
    r = vc(vc_api, 'clients', setup['client']['id'], '/relationships/applications', limit=200).json()
    assert r['complete'] is True and r['total'] == 120
    rows = {row['application']['name']: row for row in r['items']}
    multi = rows['Alfa App 001']  # i=0: Teams 0 e 3
    assert sorted(t['name'] for t in multi['teams']) == ['Alfa Team 01', 'Alfa Team 04']
    assert all(t['identity_match'] is True for t in multi['teams'])
    assert multi['business_unit']['name'] == 'Alfa BU 1' and multi['business_unit']['identity_match'] is True
    assert rows['Alfa App 017']['teams'] == []  # i=16: sem Team
    s = r['summary']
    assert s['multiple_teams'] == 23 and s['without_teams'] == 7  # i%5==0 exceto i=50 (sem Team) and s['unmatched_team_refs'] == 0
    assert s['with_business_unit'] == 120 and s['identity_check_error'] is None
    # Uma aplicação pertence a uma única BU no perfil Veracode; BUs distintas aparecem entre aplicações.
    assert len({row['business_unit']['name'] for row in r['items']}) == 4


def test_application_relationships_survive_identity_forbidden(vc_api, make_connection, make_client):
    cid = make_client(connection_id=make_connection(credential_ref='env:VC_DENIED')['id'])['id']
    r = vc(vc_api, 'clients', cid, '/relationships/applications').json()
    assert r['total'] == 3 and r['summary']['identity_check_error']['code'] == 'forbidden'
    assert all(t['identity_match'] is None for row in r['items'] for t in row['teams'])
    u = vc(vc_api, 'clients', cid, '/relationships/users')
    assert u.status_code == 502 and error_code(u) == 'forbidden'


def test_application_team_matched_by_id_never_by_name(db_url, make_connection, make_client):
    tenants = FixtureVeracode().tenants
    alpha = tenants['alpha']
    # Perfil cita um Team com o MESMO nome de um Team existente, mas IDs desconhecidos.
    alpha.applications[0]['profile']['teams'] = [{'guid': 'aaaaaaaa-0000-4000-8000-000000000000',
                                                  'team_id': 999999, 'team_name': 'Alfa Team 01'}]
    app = create_app(db_url, veracode_settings=VeracodeSettings(page_size=50),
                     veracode_transport=FixtureVeracode(tenants).transport(),
                     environ=veracode_environ(VC_ALPHA='alpha'))
    with TestClient(app) as api:
        conn = api.post('/api/connections', json={'name': 'A', 'region': 'commercial',
                                                  'credential_ref': 'env:VC_ALPHA'}).json()
        cid = api.post('/api/clients', json={'name': 'C', 'connection_id': conn['id']}).json()['id']
        r = api.get(f'/api/veracode/clients/{cid}/relationships/applications', params={'q': 'App 001'}).json()
        assert r['items'][0]['teams'][0]['identity_match'] is False
        assert r['summary']['unmatched_team_refs'] == 1


def test_filter_metadata(vc_api, setup):
    m = vc(vc_api, 'clients', setup['client']['id'], '/metadata').json()
    assert m['complete'] is True
    meta = m['metadata']
    assert meta['applications'] == 120
    fields = {f['name']: f for f in meta['custom_fields']}
    assert set(fields) == {'Ambiente', 'Centro de custo'} and fields['Centro de custo']['distinct_values'] == 6
    assert {t['value'] for t in meta['tags']} == {'sintetico', 'web', 'api'}
    assert sum(c['applications'] for c in meta['business_criticality']) == 120
    assert meta['domains']['scans']['available'] == [] and meta['domains']['sca']['available'] == []


# ---------------------------------------------------------------- coleta incompleta via API

def test_incomplete_collection_is_flagged_and_not_cached(db_url):
    calls = {'n': 0}
    base = FixtureVeracode()

    def handler(req):
        if req.url.path == '/appsec/v1/applications' and req.url.params.get('page') == '2':
            calls['n'] += 1
            if calls['n'] == 1:
                return httpx.Response(403)  # falha só na 1ª tentativa da 3ª página
        return base.handle(req)

    app = create_app(db_url, veracode_settings=VeracodeSettings(page_size=50, max_retries=0),
                     veracode_transport=httpx.MockTransport(handler), environ=veracode_environ(VC_ALPHA='alpha'))
    with TestClient(app) as api:
        conn = api.post('/api/connections', json={'name': 'A', 'region': 'commercial',
                                                  'credential_ref': 'env:VC_ALPHA'}).json()
        cid = api.post('/api/clients', json={'name': 'C', 'connection_id': conn['id']}).json()['id']
        r = api.get(f'/api/veracode/clients/{cid}/applications').json()
        assert r['complete'] is False and r['total'] == 100
        col = r['collections'][0]
        assert col['status'] == 'incomplete' and col['reason']['code'] == 'forbidden'
        assert col['pages_fetched'] == 2 and col['total_pages_reported'] == 3 and col['cached'] is False
        again = api.get(f'/api/veracode/clients/{cid}/applications').json()  # não veio do cache
        assert again['complete'] is True and again['total'] == 120 and again['collections'][0]['cached'] is False


# ---------------------------------------------------------------- cache

def test_cache_hit_ttl_and_manual_invalidation(vc_api, setup, fake_veracode):
    cid = setup['client']['id']
    count = lambda: len([r for r in fake_veracode.requests if r[2] == '/api/authn/v2/teams'])  # noqa: E731
    vc(vc_api, 'clients', cid, '/teams')
    vc(vc_api, 'clients', cid, '/teams')
    assert count() == 1
    r = vc_api.delete(f'/api/veracode/clients/{cid}/cache')
    assert r.status_code == 200 and r.json()['removed_entries'] >= 1
    assert vc(vc_api, 'clients', cid, '/teams').json()['collections'][0]['cached'] is False
    assert count() == 2


def test_cache_isolated_between_tenants_and_scopes(vc_api, setup, fake_veracode):
    sub_a, sub_b = setup['inherits']['id'], setup['overrides']['id']
    a = vc(vc_api, 'subclients', sub_a, '/applications', limit=200).json()
    b = vc(vc_api, 'subclients', sub_b, '/applications', limit=200).json()
    assert {x['guid'] for x in a['items']}.isdisjoint({x['guid'] for x in b['items']})
    # Escopos distintos com a MESMA conexão (cliente e subcliente herdeiro) não compartilham entrada.
    c = vc(vc_api, 'clients', setup['client']['id'], '/applications').json()
    assert c['collections'][0]['cached'] is False
    # Invalidar um escopo não afeta os demais.
    vc_api.delete(f'/api/veracode/subclients/{sub_a}/cache')
    assert vc(vc_api, 'subclients', sub_b, '/applications').json()['collections'][0]['cached'] is True
    assert vc(vc_api, 'clients', setup['client']['id'], '/applications').json()['collections'][0]['cached'] is True


def test_cache_never_serves_other_tenant_after_credential_change(db_url):
    env = veracode_environ(VC_X='alpha')
    fake = FixtureVeracode()
    app = create_app(db_url, veracode_settings=VeracodeSettings(page_size=50),
                     veracode_transport=fake.transport(), environ=env)
    with TestClient(app) as api:
        conn = api.post('/api/connections', json={'name': 'X', 'region': 'commercial',
                                                  'credential_ref': 'env:VC_X'}).json()
        cid = api.post('/api/clients', json={'name': 'C', 'connection_id': conn['id']}).json()['id']
        assert api.get(f'/api/veracode/clients/{cid}/applications').json()['total'] == 120
        # Operador troca a credencial da mesma referência para outro tenant: a chave do cache muda.
        env.update(veracode_environ(VC_X='beta'))
        r = api.get(f'/api/veracode/clients/{cid}/applications').json()
        assert r['total'] == 7 and r['collections'][0]['cached'] is False
        # Mudar a região/referência da conexão também gera nova chave.
        api.patch(f"/api/connections/{conn['id']}", json={'region': 'federal'})
        assert api.get(f'/api/veracode/clients/{cid}/applications').json()['collections'][0]['cached'] is False


def test_cache_keys_and_values_hold_no_credentials(vc_api, setup, vc_env):
    vc(vc_api, 'clients', setup['client']['id'], '/applications')
    vc(vc_api, 'subclients', setup['overrides']['id'], '/relationships/users')
    cache = vc_api.app.state.veracode.cache
    dump = repr(list(cache._data.keys())) + repr([e.value for e in cache._data.values()])
    for value in vc_env.values():
        assert value not in dump
    for name in vc_env:
        assert name not in dump


def test_cache_ttl_zero_disables_cache(db_url):
    fake = FixtureVeracode()
    app = create_app(db_url, veracode_settings=VeracodeSettings(cache_ttl=0), veracode_transport=fake.transport(),
                     environ=veracode_environ(VC_ALPHA='alpha'))
    with TestClient(app) as api:
        conn = api.post('/api/connections', json={'name': 'A', 'region': 'commercial',
                                                  'credential_ref': 'env:VC_ALPHA'}).json()
        cid = api.post('/api/clients', json={'name': 'C', 'connection_id': conn['id']}).json()['id']
        api.get(f'/api/veracode/clients/{cid}/teams')
        api.get(f'/api/veracode/clients/{cid}/teams')
        assert len([r for r in fake.requests if r[2] == '/api/authn/v2/teams']) == 2


def test_cache_expires_after_ttl():
    import asyncio

    from app.veracode.cache import DiscoveryCache
    now = [0.0]
    cache = DiscoveryCache(ttl=10, max_entries=2, clock=lambda: now[0])
    cache.put(('client', 'a', 'r'), 1)
    assert cache.get(('client', 'a', 'r'))[0] == 1
    now[0] = 10.1
    assert cache.get(('client', 'a', 'r')) is None
    for k in 'xyz':
        cache.put(('client', k), k)
    assert len(cache) == 2  # limite de entradas (LRU)

    async def single_flight():
        calls = []

        async def collect():
            calls.append(1)
            await asyncio.sleep(0.01)
            return 'v'
        results = await asyncio.gather(*(cache.get_or_collect(('k',), collect, lambda v: True) for _ in range(5)))
        return calls, results
    calls, results = asyncio.run(single_flight())
    assert len(calls) == 1 and [r[0] for r in results] == ['v'] * 5


# ---------------------------------------------------------------- segredos, logs e loopback

def test_no_credentials_in_logs_or_responses(vc_api, setup, vc_env, caplog):
    caplog.set_level(logging.DEBUG)
    cid, sub = setup['client']['id'], setup['overrides']['id']
    bodies = [vc_api.post(f'/api/veracode/clients/{cid}/test').text,
              vc_api.post(f'/api/veracode/subclients/{sub}/test').text]
    for path in ('', '/applications', '/business-units', '/teams', '/users', '/relationships/applications',
                 '/relationships/users', '/metadata'):
        bodies.append(vc(vc_api, 'clients', cid, path).text)
        bodies.append(vc(vc_api, 'subclients', sub, path).text)
    text = '\n'.join(bodies) + caplog.text
    for name, value in vc_env.items():
        assert value not in text and value.upper() not in text and value.lower() not in text
        assert name not in text
    for forbidden in ('VERACODE-HMAC', 'sig=', 'Authorization', 'api_key', 'api_id'):
        assert forbidden not in text
    assert 'descoberta escopo=' in caplog.text  # logs operacionais continuam existindo


def test_local_only_rejects_non_loopback_clients_and_hosts(db_url):
    with TestClient(create_app(db_url), client=('203.0.113.7', 4000)) as remote:
        r = remote.get('/api/health')
        assert r.status_code == 403 and r.json()['error']['code'] == 'local_only'
    with TestClient(create_app(db_url), client=('127.0.0.1', 4000)) as local:
        assert local.get('/api/health').status_code == 200
        assert local.get('/api/health', headers={'Host': 'localhost:8000'}).status_code == 200
        assert local.get('/api/health', headers={'Host': '[::1]:8000'}).status_code == 200
        rebinding = local.get('/api/health', headers={'Host': 'attacker.example'})
        assert rebinding.status_code == 403
    with TestClient(create_app(db_url), client=('::1', 4000)) as v6:
        assert v6.get('/api/health').status_code == 200


def test_fixture_mode_is_explicit_and_never_default(db_url):
    assert VeracodeSettings().mode == 'live'
    with TestClient(create_app(db_url, veracode_settings=VeracodeSettings(mode='fixture'))) as api:
        assert api.get('/api/health').json()['veracode_mode'] == 'fixture'
