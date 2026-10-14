"""CRUD de subclientes, hierarquia de dois níveis e herança de conexão."""
import uuid

from conftest import error_code


def test_subclient_crud_full_cycle(api, make_client):
    c = make_client()
    r = api.post(f"/api/clients/{c['id']}/subclients", json={'name': 'BU Pagamentos'})
    assert r.status_code == 201
    sub = r.json()
    sid = sub['id']
    assert uuid.UUID(sid).version == 4
    assert sub['client_id'] == c['id']
    assert sub['display_name'] == 'BU Pagamentos'
    assert sub['is_active'] is True and sub['effective_active'] is True

    assert api.get(f'/api/subclients/{sid}').json() == sub
    page = api.get(f"/api/clients/{c['id']}/subclients").json()
    assert page['total'] == 1 and page['items'][0]['id'] == sid
    assert api.get(f"/api/clients/{c['id']}").json()['subclient_count'] == 1

    r = api.patch(f'/api/subclients/{sid}', json={'name': 'BU Pagamentos Digitais', 'display_name': 'Pagamentos'})
    assert r.status_code == 200
    updated = r.json()
    assert (updated['name'], updated['display_name']) == ('BU Pagamentos Digitais', 'Pagamentos')
    assert updated['created_at'] == sub['created_at'] and updated['updated_at'] > sub['updated_at']

    r = api.delete(f'/api/subclients/{sid}')
    assert r.status_code == 409 and error_code(r) == 'subclient_active'
    api.patch(f'/api/subclients/{sid}', json={'is_active': False})
    assert api.delete(f'/api/subclients/{sid}').status_code == 204
    r = api.get(f'/api/subclients/{sid}')
    assert r.status_code == 404 and error_code(r) == 'subclient_not_found'
    assert api.get(f"/api/clients/{c['id']}").json()['subclient_count'] == 0


def test_subclient_belongs_to_exactly_one_client_and_cannot_move(api, make_client, make_subclient):
    a, b = make_client(), make_client()
    sub = make_subclient(a['id'])
    r = api.patch(f"/api/subclients/{sub['id']}", json={'client_id': b['id']})
    assert r.status_code == 422  # vínculo imutável
    r = api.post(f"/api/clients/{a['id']}/subclients", json={'name': 'X', 'client_id': b['id']})
    assert r.status_code == 422
    assert api.get(f"/api/subclients/{sub['id']}").json()['client_id'] == a['id']


def test_same_name_allowed_in_different_clients_but_not_in_same(api, make_client, make_subclient):
    a, b = make_client(), make_client()
    make_subclient(a['id'], name='Financeiro')
    make_subclient(b['id'], name='Financeiro')
    r = api.post(f"/api/clients/{a['id']}/subclients", json={'name': 'FINANCEIRO'})
    assert r.status_code == 409 and error_code(r) == 'duplicate_name'


def test_no_subclient_inside_subclient(api, make_client, make_subclient):
    c = make_client()
    sub = make_subclient(c['id'])
    # 1) usar o id de um subcliente como "cliente pai" é recusado explicitamente
    r = api.post(f"/api/clients/{sub['id']}/subclients", json={'name': 'Neto'})
    assert r.status_code == 400 and error_code(r) == 'nested_subclient_not_allowed'
    r = api.get(f"/api/clients/{sub['id']}/subclients")
    assert r.status_code == 400
    # 2) não existe rota de subclientes sob subcliente
    assert api.post(f"/api/subclients/{sub['id']}/subclients", json={'name': 'Neto'}).status_code in (404, 405)
    # 3) campos de hierarquia extra são rejeitados
    for field in ('parent_id', 'parent_subclient_id', 'subclients'):
        r = api.post(f"/api/clients/{c['id']}/subclients", json={'name': 'Neto', field: sub['id']})
        assert r.status_code == 422, field
    assert api.get(f"/api/clients/{c['id']}/subclients").json()['total'] == 1


def test_unknown_client_for_subclient_is_404(api):
    r = api.post(f'/api/clients/{uuid.uuid4()}/subclients', json={'name': 'Órfão'})
    assert r.status_code == 404 and error_code(r) == 'client_not_found'


def test_connection_inheritance_and_override(api, make_client, make_subclient, make_connection):
    conn_client = make_connection(name='Conexão do cliente')
    conn_sub = make_connection(name='Conexão da BU')
    c = make_client(connection_id=conn_client['id'])

    inherited = make_subclient(c['id'])
    assert inherited['connection_id'] is None
    assert inherited['connection_source'] == 'client'
    assert inherited['effective_connection']['id'] == conn_client['id']

    overridden = make_subclient(c['id'], connection_id=conn_sub['id'])
    assert overridden['connection_source'] == 'subclient'
    assert overridden['effective_connection']['id'] == conn_sub['id']

    # Trocar a conexão do cliente propaga para quem herda, não para quem sobrescreve.
    conn_new = make_connection(name='Nova conexão do cliente')
    api.patch(f"/api/clients/{c['id']}", json={'connection_id': conn_new['id']})
    assert api.get(f"/api/subclients/{inherited['id']}").json()['effective_connection']['id'] == conn_new['id']
    assert api.get(f"/api/subclients/{overridden['id']}").json()['effective_connection']['id'] == conn_sub['id']

    # Remover a sobrescrita (null) volta a herdar.
    r = api.patch(f"/api/subclients/{overridden['id']}", json={'connection_id': None})
    assert r.json()['connection_source'] == 'client' and r.json()['effective_connection']['id'] == conn_new['id']

    # Cliente sem conexão e subcliente sem sobrescrita => nenhuma.
    api.patch(f"/api/clients/{c['id']}", json={'connection_id': None})
    r = api.get(f"/api/subclients/{inherited['id']}").json()
    assert r['connection_source'] == 'none' and r['effective_connection'] is None

    # Sobrescrita com conexão inexistente => 400
    r = api.patch(f"/api/subclients/{inherited['id']}", json={'connection_id': str(uuid.uuid4())})
    assert r.status_code == 400 and error_code(r) == 'connection_not_found'


def test_client_deactivation_reflects_in_effective_status_without_overwriting(api, make_client, make_subclient):
    c = make_client()
    active_sub = make_subclient(c['id'])
    inactive_sub = make_subclient(c['id'], is_active=False)
    api.patch(f"/api/clients/{c['id']}", json={'is_active': False})
    a = api.get(f"/api/subclients/{active_sub['id']}").json()
    assert a['is_active'] is True and a['effective_active'] is False  # status próprio preservado
    api.patch(f"/api/clients/{c['id']}", json={'is_active': True})
    assert api.get(f"/api/subclients/{active_sub['id']}").json()['effective_active'] is True
    assert api.get(f"/api/subclients/{inactive_sub['id']}").json()['effective_active'] is False
    assert api.get(f"/api/clients/{c['id']}").json()['active_subclient_count'] == 1


def test_subclient_list_pagination_and_status(api, make_client, make_subclient):
    c = make_client()
    for i in range(4):
        make_subclient(c['id'], name=f'BU {i}', is_active=i < 3)
    page = api.get(f"/api/clients/{c['id']}/subclients", params={'limit': 3}).json()
    assert page['total'] == 4 and len(page['items']) == 3
    assert api.get(f"/api/clients/{c['id']}/subclients", params={'status': 'inactive'}).json()['total'] == 1
    assert api.get(f"/api/clients/{c['id']}/subclients", params={'limit': 500}).status_code == 422


def test_subclient_validation(api, make_client):
    c = make_client()
    for payload in ({}, {'name': ''}, {'name': 'x' * 121}, {'name': 'ok', 'connection_id': 'abc'},
                    {'name': 'ok', 'description': 'subcliente não tem descrição'}):
        assert api.post(f"/api/clients/{c['id']}/subclients", json=payload).status_code == 422, payload
    assert api.get('/api/subclients/nao-uuid').status_code == 422
