"""F03 — escopos versionados e resolução (universo, subclientes, sobreposição, não classificadas, usuários por Team)
sobre o tenant SINTÉTICO `alpha` (FixtureVeracode). Valores esperados são calculados direto dos dados brutos do
fixture, independentemente do motor. Nenhuma chamada real; somente GET na Veracode simulada.
"""
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import create_app
from app.veracode.fixtures import FixtureVeracode, default_tenants
from app.veracode.settings import VeracodeSettings

from conftest import SleepRecorder, error_code, veracode_environ

ALPHA = default_tenants()['alpha']
BU = [b['bu_id'] for b in ALPHA.business_units]
TEAM = [t['team_id'] for t in ALPHA.teams]


def raw_apps(pred) -> set[str]:
    return {a['guid'] for a in ALPHA.applications if pred(a['profile'])}


def in_bu(*bus):
    return lambda p: p['business_unit']['guid'] in bus


def in_team(*teams):
    return lambda p: any(t['guid'] in teams for t in p['teams'])


def team_members(team_id) -> set[str]:
    return {m['user_id'] for m in ALPHA.team_users[team_id]}


def leaf(field, cmp_, v):
    return {'field': field, 'cmp': cmp_, ('values' if isinstance(v, list) else 'value'): v}


def put(api, kind, owner_id, domain, rule, expected=0, **extra):
    return api.put(f'/api/scopes/{kind}/{owner_id}/{domain}',
                   json={'rule': rule, 'expected_version': expected, **extra})


def save(api, kind, owner_id, domain, rule, expected=0, **extra) -> dict:
    r = put(api, kind, owner_id, domain, rule, expected, **extra)
    assert r.status_code == 201, r.text
    return r.json()


def preview(api, client_id, domain='applications', **body) -> dict:
    r = api.post(f'/api/scope-preview/clients/{client_id}', json={'domain': domain, 'sample_limit': 200, **body})
    assert r.status_code == 200, r.text
    return r.json()


def ids(rows) -> set[str]:
    return {r['id'] for r in rows}


def sub(res, sub_id) -> dict:
    return next(s for s in res['subclients'] if s['id'] == sub_id)


@pytest.fixture
def world(vc_api, make_connection, make_client, make_subclient):
    alpha = make_connection(credential_ref='env:VC_ALPHA')
    beta = make_connection(credential_ref='env:VC_BETA')
    client = make_client(connection_id=alpha['id'])
    return {'api': vc_api, 'alpha': alpha, 'beta': beta, 'client': client,
            'sub': lambda **kw: make_subclient(client['id'], **kw)}


# ---------------------------------------------------------------- 1. cliente sem subclientes

def test_client_without_subclients(world):
    api, cid = world['api'], world['client']['id']
    res = preview(api, cid)
    assert res['status'] == 'universe_not_defined' and res['unclassified']['available'] is False
    assert {w['code'] for w in res['warnings']} >= {'universe_not_defined', 'no_subclients'}

    save(api, 'clients', cid, 'applications', leaf('business_unit.id', 'in', [BU[0], BU[1]]))
    res = preview(api, cid)
    expected = raw_apps(in_bu(BU[0], BU[1]))
    assert res['status'] == 'ok' and res['complete'] is True
    assert res['universe']['included'] == len(expected) == 60
    assert res['universe']['excluded'] == 60 and res['universe']['total_available'] == 120
    un = res['unclassified']
    assert un['count'] == 60 and un['no_subclients'] is True and un['complete'] is True
    assert ids(un['sample']) == expected
    assert res['subclients'] == [] and res['overlap']['resources_in_multiple'] == 0


# ---------------------------------------------------------------- 2/3/4/6. três subclientes, sobreposição, não classificadas

def test_three_subclients_overlap_and_unclassified(world):
    api, cid = world['api'], world['client']['id']
    s1, s2, s3 = world['sub'](), world['sub'](), world['sub']()
    # Universo restrito: BUs 0, 1 e 2 (BU 3 nunca pode aparecer como não classificada).
    save(api, 'clients', cid, 'applications', leaf('business_unit.id', 'in', BU[:3]))
    save(api, 'subclients', s1['id'], 'applications', leaf('business_unit.id', 'eq', BU[0]))
    save(api, 'subclients', s2['id'], 'applications', leaf('team.id', 'in', [TEAM[0], TEAM[3]]))
    # s3 seleciona também apps fora do universo (BU 3): só a interseção conta
    save(api, 'subclients', s3['id'], 'applications', leaf('business_unit.id', 'in', [BU[1], BU[3]]))
    res = preview(api, cid)

    universe = raw_apps(in_bu(*BU[:3]))
    e1 = raw_apps(in_bu(BU[0]))
    e2 = raw_apps(in_team(TEAM[0], TEAM[3])) & universe
    e3 = raw_apps(in_bu(BU[1]))
    assert ids(sub(res, s1['id'])['sample']) == e1
    assert ids(sub(res, s2['id'])['sample']) == e2
    assert ids(sub(res, s3['id'])['sample']) == e3
    assert sub(res, s3['id'])['outside_universe'] == len(raw_apps(in_bu(BU[3])))
    assert sub(res, s1['id'])['excluded'] == len(universe - e1)  # excluídos medidos dentro do universo
    assert all(s['status'] == 'shared' and s['intersected'] for s in res['subclients'])

    multi = {g for g in universe if sum(g in e for e in (e1, e2, e3)) > 1}
    assert multi, 'o cenário precisa de aplicação em mais de um subcliente'
    assert res['overlap']['resources_in_multiple'] == len(multi)
    assert ids(res['overlap']['sample']) == multi
    pair = {(p['a'], p['b']): p['count'] for p in res['overlap']['pairs']}
    assert pair[tuple(sorted([s1['id'], s2['id']]))] == len(e1 & e2)

    unclassified = universe - (e1 | e2 | e3)
    un = res['unclassified']
    assert un['count'] == len(unclassified) and ids(un['sample']) == unclassified
    assert un['complete'] is True and not un['no_subclients']
    assert not (ids(un['sample']) & raw_apps(in_bu(BU[3])))  # nunca o tenant inteiro


def test_nested_and_or_not_through_api(world):
    api, cid = world['api'], world['client']['id']
    s1 = world['sub']()
    save(api, 'clients', cid, 'applications', {'op': 'all'})
    rule = {'op': 'or', 'args': [
        {'op': 'and', 'args': [leaf('business_unit.id', 'eq', BU[0]),
                               {'op': 'not', 'arg': leaf('tag', 'in', ['web'])}]},
        {'op': 'and', 'args': [leaf('business_criticality', 'in', ['VERY_HIGH']),
                               leaf('custom_field', 'eq', 'Homologação') | {'key': 'Ambiente'}]}]}
    save(api, 'subclients', s1['id'], 'applications', rule)
    expected = {a['guid'] for i, a in enumerate(ALPHA.applications)
                if (i % 4 == 0 and i % 2 == 1) or (i % 5 == 0 and i % 3 == 0)}
    assert ids(sub(preview(api, cid), s1['id'])['sample']) == expected


# ---------------------------------------------------------------- 7/8/9. usuários: filtros independentes, dedup, inativos

def test_user_scopes_are_independent_from_applications(world):
    api, cid = world['api'], world['client']['id']
    s1 = world['sub']()
    save(api, 'clients', cid, 'applications', {'op': 'all'})
    save(api, 'clients', cid, 'users', {'op': 'all'})
    save(api, 'subclients', s1['id'], 'users', leaf('team.id', 'in', [TEAM[0]]))
    # Team de usuários NÃO seleciona aplicações: o subcliente não tem escopo de aplicações
    apps = preview(api, cid)
    assert sub(apps, s1['id'])['status'] == 'not_defined'
    assert apps['unclassified']['count'] == 120
    assert any(w['code'] == 'subclients_without_scope' for w in apps['warnings'])
    # campos de aplicações são recusados no domínio de usuários
    r = put(api, 'subclients', s1['id'], 'users', leaf('business_unit.id', 'eq', BU[0]), expected=1)
    assert r.status_code == 422 and error_code(r) == 'invalid_rule'


def test_users_multiple_teams_unique_and_inactive(world):
    api, cid = world['api'], world['client']['id']
    s1 = world['sub']()
    save(api, 'clients', cid, 'users', {'op': 'all'})
    save(api, 'subclients', s1['id'], 'users', leaf('team.id', 'in', [TEAM[0], TEAM[1]]))
    res = preview(api, cid, 'users')
    users = {u['user_id']: u for u in ALPHA.users}
    active = {u for u, row in users.items() if row['active']}
    inactive = set(users) - active
    assert res['universe']['included'] == len(active) and res['universe']['inactive_excluded'] == len(inactive) == 4

    members = team_members(TEAM[0]) | team_members(TEAM[1])
    both = team_members(TEAM[0]) & team_members(TEAM[1])
    assert both, 'o cenário precisa de usuário em dois Teams'
    s = sub(res, s1['id'])
    assert ids(s['sample']) == members & active  # cada usuário uma vez
    upt = s['users_per_team']
    assert upt['complete'] is True and upt['unique_users_total'] == len(members & active)
    per = {t['team_id']: t['unique_users'] for t in upt['teams']}
    assert per[TEAM[0]] == len(team_members(TEAM[0]) & active)
    assert sum(per.values()) > upt['unique_users_total']  # soma por Team ≠ únicos (dedup)
    # Usuários sem Team não aparecem em nenhum detalhe => sem team_count => completude não comprovada.
    rec = res['reconciliation']
    no_team = sum(1 for u in users if not any(u in team_members(t) for t in TEAM))
    assert rec['status'] == 'partial' and rec['unverifiable'] == no_team == 3
    assert rec['verified'] == 45 - no_team and rec['missing_teams'] == rec['inconsistent'] == 0

    # regra configurável: incluir inativos
    save(api, 'clients', cid, 'users', {'op': 'all'}, expected=1, options={'inactive_users': 'include'})
    res = preview(api, cid, 'users')
    assert res['universe']['included'] == 45 and res['universe']['inactive_excluded'] == 0
    r = put(api, 'clients', cid, 'users', {'op': 'all'}, expected=2, options={'inactive_users': 'maybe'})
    assert r.status_code == 422 and error_code(r) == 'invalid_options'


# ---------------------------------------------------------------- 10. campos ausentes

def test_missing_fields_are_reported_as_undetermined(db_url, make_connection, make_client, make_subclient):
    tenants = default_tenants()
    apps = tenants['alpha'].applications
    del apps[0]['profile']['teams']  # Teams desconhecidos
    apps[1]['profile']['business_unit'] = None
    apps[2]['profile']['teams'] = []  # sem Team (conhecido)
    fake = FixtureVeracode(tenants)
    app = create_app(db_url, veracode_settings=VeracodeSettings(page_size=50), veracode_transport=fake.transport(),
                     environ=veracode_environ(VC_ALPHA='alpha'), sleep=SleepRecorder())
    with TestClient(app) as api:
        conn = api.post('/api/connections', json={'name': 'A', 'region': 'commercial',
                                                  'credential_ref': 'env:VC_ALPHA'}).json()
        cid = api.post('/api/clients', json={'name': 'C', 'connection_id': conn['id']}).json()['id']
        s1 = api.post(f'/api/clients/{cid}/subclients', json={'name': 'S'}).json()
        save(api, 'clients', cid, 'applications', leaf('business_unit.id', 'in', BU))
        save(api, 'subclients', s1['id'], 'applications', leaf('team.id', 'in', TEAM))
        res = preview(api, cid)
    assert res['universe']['undetermined'] == 1 and res['universe']['missing_fields'] == {'business_unit.id': 1}
    s = sub(res, s1['id'])
    assert s['missing_fields'] == {'team.id': 1}
    assert apps[2]['guid'] not in ids(s['sample'])  # [] => excluída, não indeterminada
    un = res['unclassified']
    assert un['complete'] is False
    assert set(un['reasons']) == {'universe_undetermined', 'undetermined_in_subclients'}


# ---------------------------------------------------------------- 11. conexão herdada e sobrescrita

def test_inherited_and_overridden_connections(world):
    api, cid = world['api'], world['client']['id']
    inherits = world['sub']()
    same = world['sub'](connection_id=world['alpha']['id'])
    other = world['sub'](connection_id=world['beta']['id'])
    save(api, 'clients', cid, 'applications', leaf('business_unit.id', 'eq', BU[0]))
    save(api, 'subclients', inherits['id'], 'applications', {'op': 'all'})
    save(api, 'subclients', same['id'], 'applications', leaf('team.id', 'in', [TEAM[0]]))
    r = put(api, 'subclients', other['id'], 'applications', {'op': 'all'})
    assert r.status_code == 409 and error_code(r) == 'coverage_ack_required'
    saved = save(api, 'subclients', other['id'], 'applications', {'op': 'all'}, coverage_ack=True)
    assert saved['active_version']['connection_mode'] == 'separate' and saved['active_version']['coverage_ack']

    res = preview(api, cid)
    assert sub(res, inherits['id'])['connection_mode'] == sub(res, same['id'])['connection_mode'] == 'shared'
    o = sub(res, other['id'])
    assert o['status'] == 'separate_tenant' and o['tenant'] == 'separate' and o['intersected'] is False
    assert o['included'] == o['total_available'] == 7  # tenant beta, sem interseção com o universo alpha
    assert all(r['name'].startswith('Beta') for r in o['sample'])
    universe = raw_apps(in_bu(BU[0]))
    assert res['unclassified']['count'] == 0  # `inherits` cobre todo o universo; beta não entra na união
    assert not (ids(res['overlap']['sample']) & {r['id'] for r in o['sample']})
    assert ids(sub(res, inherits['id'])['sample']) == universe

    # A conexão mudou depois de salvar (separate -> shared): exige nova versão, nada é misturado
    api.patch(f"/api/subclients/{other['id']}", json={'connection_id': world['alpha']['id']})
    res = preview(api, cid)
    assert sub(res, other['id'])['status'] == 'connection_changed'
    assert res['unclassified']['complete'] is False and 'connection_changed' in res['unclassified']['reasons']


# ---------------------------------------------------------------- 12. coletas incompletas

def test_incomplete_collection_is_never_presented_as_validated(db_url):
    settings = VeracodeSettings(page_size=50, max_requests_per_collection=2, max_retries=0)
    app = create_app(db_url, veracode_settings=settings, veracode_transport=FixtureVeracode().transport(),
                     environ=veracode_environ(VC_ALPHA='alpha'), sleep=SleepRecorder())
    with TestClient(app) as api:
        conn = api.post('/api/connections', json={'name': 'A', 'region': 'commercial',
                                                  'credential_ref': 'env:VC_ALPHA'}).json()
        cid = api.post('/api/clients', json={'name': 'C', 'connection_id': conn['id']}).json()['id']
        save(api, 'clients', cid, 'applications', {'op': 'all'})
        save(api, 'clients', cid, 'users', {'op': 'all'})
        res = preview(api, cid)
        assert res['complete'] is False and res['status'] == 'incomplete'
        assert res['universe']['included'] == 100  # 2 páginas de 50: parcial, sinalizado
        assert res['unclassified']['complete'] is False
        assert 'collection_incomplete' in res['unclassified']['reasons']
        assert any(c['status'] == 'incomplete' for c in res['collections'])
        users = preview(api, cid, 'users')  # 8 detalhes de Team > orçamento de 2: vínculos incompletos
        assert users['complete'] is False
        assert users['universe']['users_per_team']['unique_users_total'] is None
        assert users['reconciliation']['status'] == 'collection_incomplete'


# ---------------------------------------------------------------- 13. versionamento

def test_versioning_is_append_only_with_optimistic_concurrency(world, db_url):
    api, cid = world['api'], world['client']['id']
    v1 = save(api, 'clients', cid, 'applications', leaf('business_unit.id', 'eq', BU[0]), note='inicial')
    assert v1['active_version']['version'] == 1
    assert put(api, 'clients', cid, 'applications', {'op': 'all'}, expected=0).status_code == 409  # versão obsoleta
    same = put(api, 'clients', cid, 'applications', leaf('business_unit.id', 'eq', BU[0].upper()), expected=1)
    assert same.status_code == 200 and same.json()['created'] is False  # canonicamente idêntica
    save(api, 'clients', cid, 'applications', {'op': 'all'}, expected=1)
    r = api.post(f'/api/scopes/clients/{cid}/applications/versions/1/restore', json={'expected_version': 2})
    assert r.status_code == 201
    hist = api.get(f'/api/scopes/clients/{cid}/applications').json()
    assert [v['version'] for v in hist['versions']] == [3, 2, 1]
    assert [v['status'] for v in hist['versions']] == ['active', 'superseded', 'superseded']
    assert hist['versions'][0]['rule'] == hist['versions'][2]['rule']  # v1 preservada e reaplicada
    assert hist['versions'][2]['note'] == 'inicial'
    assert api.post(f'/api/scopes/clients/{cid}/applications/versions/9/restore',
                    json={'expected_version': 3}).status_code == 404

    assert api.patch(f'/api/scopes/clients/{cid}/applications', json={'status': 'disabled'}).json()['status'] \
        == 'disabled'
    assert preview(api, cid)['status'] == 'universe_not_defined'
    overview = api.get(f'/api/scopes/clients/{cid}').json()
    assert overview['owners'][0]['scopes']['applications']['status'] == 'disabled'
    assert set(overview['owners'][0]['scopes']) == {'applications', 'users', 'scans', 'sca'}

    # Nenhuma cópia de recurso Veracode no banco: só regras (IDs) e metadados.
    with sqlite3.connect(db.sqlite_file(db_url)) as conn:
        dump = '\n'.join(conn.iterdump())
    assert 'Alfa App' not in dump and 'Alfa Team' not in dump and 'usuario' not in dump


def test_subclient_with_scopes_cannot_be_deleted(world):
    api, cid = world['api'], world['client']['id']
    s1 = world['sub'](is_active=False)
    save(api, 'subclients', s1['id'], 'applications', {'op': 'all'})
    r = api.delete(f"/api/subclients/{s1['id']}")
    assert r.status_code == 409  # escopos (e seu histórico) preservados


# ---------------------------------------------------------------- scans/SCA, validação, segurança

def test_scans_and_sca_are_stored_and_validated_only(world, fake_veracode):
    api, cid = world['api'], world['client']['id']
    save(api, 'clients', cid, 'scans', {'op': 'and', 'args': [leaf('scan.context', 'eq', 'policy'),
                                                              leaf('application.in_scope', 'eq', True)]})
    r = put(api, 'clients', cid, 'sca', leaf('scan.context', 'eq', 'policy'))
    assert r.status_code == 422
    before = len(fake_veracode.requests)
    res = preview(api, cid, 'scans')
    assert res['status'] == 'deferred_f04' and res['evaluable'] is False
    assert len(fake_veracode.requests) == before  # nenhuma consulta de scans/SCA


def test_validate_endpoint_and_draft_preview(world):
    api, cid = world['api'], world['client']['id']
    s1 = world['sub']()
    r = api.post('/api/scopes/validate', json={'domain': 'applications', 'rule': leaf('team.id', 'eq', 'Time 1')})
    body = r.json()
    assert r.status_code == 200 and body['valid'] is False and body['issues'][0]['field'] == 'rule.value'
    body = api.post('/api/scopes/validate', json={'domain': 'users', 'rule': {'op': 'all'},
                                                  'options': {'inactive_users': 'x'}}).json()
    assert body['valid'] is False
    save(api, 'clients', cid, 'applications', {'op': 'all'})
    draft = {'owner_kind': 'subclient', 'owner_id': s1['id'], 'rule': leaf('business_unit.id', 'eq', BU[2])}
    res = preview(api, cid, draft=draft)
    s = sub(res, s1['id'])
    assert s['draft'] is True and ids(s['sample']) == raw_apps(in_bu(BU[2]))
    assert api.get(f"/api/scopes/subclients/{s1['id']}/applications").json()['defined'] is False  # nada gravado
    other = world['client']  # rascunho de dono de outro cliente => 400
    c2 = api.post('/api/clients', json={'name': 'Outro cliente'}).json()
    r = api.post(f"/api/scope-preview/clients/{c2['id']}", json={'domain': 'applications', 'draft': draft})
    assert r.status_code == 400 and other


def test_only_get_requests_and_no_secrets_in_responses(world, fake_veracode, vc_env):
    api, cid = world['api'], world['client']['id']
    s1 = world['sub']()
    save(api, 'clients', cid, 'applications', {'op': 'all'})
    save(api, 'clients', cid, 'users', {'op': 'all'})
    save(api, 'subclients', s1['id'], 'users', leaf('team.id', 'in', [TEAM[2]]))
    bodies = [json.dumps(preview(api, cid)), json.dumps(preview(api, cid, 'users')),
              api.get(f'/api/scopes/clients/{cid}').text]
    assert fake_veracode.requests and {m for _, m, _ in fake_veracode.requests} == {'GET'}
    for text in bodies:
        for name, value in vc_env.items():
            assert name not in text and value not in text
