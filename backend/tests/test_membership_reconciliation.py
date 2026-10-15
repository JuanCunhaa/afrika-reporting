"""F03 (correções F02.1) — reconciliação usuário–Team por `team_count`, sem inventar vínculos. Tenant SINTÉTICO."""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.veracode.fixtures import FixtureVeracode, default_tenants
from app.veracode.settings import VeracodeSettings

from conftest import SleepRecorder, veracode_environ


def _api(db_url, tenants):
    app = create_app(db_url, veracode_settings=VeracodeSettings(page_size=50),
                     veracode_transport=FixtureVeracode(tenants).transport(),
                     environ=veracode_environ(VC_ALPHA='alpha'), sleep=SleepRecorder())
    return TestClient(app)


def _client(api) -> str:
    conn = api.post('/api/connections', json={'name': 'A', 'region': 'commercial',
                                              'credential_ref': 'env:VC_ALPHA'}).json()
    return api.post('/api/clients', json={'name': 'C', 'connection_id': conn['id']}).json()['id']


def _relationships(api, cid) -> dict:
    r = api.get(f'/api/veracode/clients/{cid}/relationships/users', params={'limit': 200})
    assert r.status_code == 200, r.text
    return r.json()


def test_hidden_team_is_detected_and_membership_marked_partial(db_url):
    tenants = default_tenants()
    alpha = tenants['alpha']
    hidden = alpha.teams.pop(1)  # Team não visível para a conta (ex.: sem all_for_org efetivo)
    members = alpha.team_users[hidden['team_id']]
    hidden_members = {m['user_id'] for m in members if m['team_count'] == 2}  # também em Team visível
    only_hidden = {m['user_id'] for m in members if m['team_count'] == 1}
    with _api(db_url, tenants) as api:
        cid = _client(api)
        body = _relationships(api, cid)
        rec = body['summary']['reconciliation']
        assert rec['status'] == 'mismatch' and rec['missing_teams'] == len(hidden_members) == 6
        rows = {r['user']['user_id']: r for r in body['items']}
        for uid in hidden_members:
            assert rows[uid]['reconciliation'] == 'missing_teams' and rows[uid]['teams_complete'] is False
        # Só no Team invisível: nenhum membro visível traz team_count => não comprovável (limitação documentada)
        for uid in only_hidden:
            assert rows[uid]['reconciliation'] == 'unverifiable' and rows[uid]['teams'] == []
        assert body['summary']['members_per_team'].get(hidden['team_id']) is None  # nada inventado

        # Na resolução: presença nos Teams visíveis prova; ausência não prova (indeterminado).
        api.put(f'/api/scopes/clients/{cid}/users', json={'rule': {'op': 'all'}, 'expected_version': 0})
        visible = alpha.teams[1]['team_id']  # Team 3 original: nenhum usuário com Team oculto está nele
        rule = {'op': 'not', 'arg': {'field': 'team.id', 'cmp': 'in', 'values': [visible]}}
        sid = api.post(f'/api/clients/{cid}/subclients', json={'name': 'S'}).json()['id']
        api.put(f'/api/scopes/subclients/{sid}/users', json={'rule': rule, 'expected_version': 0})
        res = api.post(f'/api/scope-preview/clients/{cid}', json={'domain': 'users', 'sample_limit': 200}).json()
        s = res['subclients'][0]
        partial_outside = {uid for uid in hidden_members
                           if visible not in {t['team_id'] for t in rows[uid]['teams']}}
        assert s['undetermined'] >= 1 and s['missing_fields'].get('team.id', 0) >= 1
        assert not (partial_outside & {r['id'] for r in s['sample']})
        assert {w['code'] for w in res['warnings']} >= {'membership_unverified'}


def test_without_team_count_completeness_is_not_claimed(db_url):
    tenants = default_tenants()
    for members in tenants['alpha'].team_users.values():
        for m in members:
            m.pop('team_count', None)
    with _api(db_url, tenants) as api:
        body = _relationships(api, _client(api))
    rec = body['summary']['reconciliation']
    assert rec['status'] == 'unverifiable' and rec['verified'] == 0
    assert 'não comprovada' in rec['reason']
    # Contagem por Team continua só para Teams cujo detalhe foi obtido (todos aqui)
    assert body['summary']['members_per_team_complete'] is True


def test_team_count_from_user_list_is_used_when_member_has_none(db_url):
    tenants = default_tenants()
    alpha = tenants['alpha']
    for members in alpha.team_users.values():
        for m in members:
            m.pop('team_count', None)
    lonely = alpha.users[14]  # usuário sem Team no fixture
    lonely['team_count'] = 2  # a Veracode diz que ele tem 2 Teams, nenhum visível
    with _api(db_url, tenants) as api:
        body = _relationships(api, _client(api))
    row = next(r for r in body['items'] if r['user']['user_id'] == lonely['user_id'])
    assert row['reconciliation'] == 'missing_teams' and row['team_count_reported'] == 2
    assert body['summary']['reconciliation']['status'] == 'mismatch'


@pytest.mark.parametrize('value', [-1, 'x', True, None])
def test_invalid_team_count_is_ignored(value):
    from app.veracode.adapters import normalize_membership
    assert normalize_membership({'user_id': 'u', 'team_count': value})['team_count'] is None
