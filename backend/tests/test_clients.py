"""CRUD de clientes, validações, paginação e regras de exclusão."""
import uuid

from conftest import error_code


def test_client_crud_full_cycle(api, make_connection):
    conn = make_connection()
    r = api.post('/api/clients', json={'name': '  Cliente Alfa  ', 'description': 'Sintético',
                                       'report_mode': 'both', 'connection_id': conn['id']})
    assert r.status_code == 201
    created = r.json()
    cid = created['id']
    assert uuid.UUID(cid).version == 4
    assert created['name'] == 'Cliente Alfa'  # trim
    assert created['display_name'] == 'Cliente Alfa'  # padrão = name
    assert created['is_active'] is True
    assert created['report_mode'] == 'both'
    assert created['connection']['id'] == conn['id']
    assert created['subclient_count'] == 0
    assert created['created_at'] == created['updated_at']

    assert api.get(f'/api/clients/{cid}').json() == created

    r = api.patch(f'/api/clients/{cid}', json={'display_name': 'Alfa S.A.', 'report_mode': 'per_subclient',
                                               'description': None, 'connection_id': None})
    assert r.status_code == 200
    updated = r.json()
    assert updated['id'] == cid
    assert updated['display_name'] == 'Alfa S.A.'
    assert updated['report_mode'] == 'per_subclient'
    assert updated['description'] is None
    assert updated['connection'] is None and updated['connection_id'] is None
    assert updated['created_at'] == created['created_at']
    assert updated['updated_at'] > created['updated_at']

    assert api.patch(f'/api/clients/{cid}', json={'is_active': False}).json()['is_active'] is False
    assert api.delete(f'/api/clients/{cid}').status_code == 204
    r = api.get(f'/api/clients/{cid}')
    assert r.status_code == 404 and error_code(r) == 'client_not_found'


def test_report_modes_accepted_and_invalid_rejected(api, make_client):
    for mode in ('consolidated', 'per_subclient', 'both'):
        assert make_client(report_mode=mode)['report_mode'] == mode
    assert make_client()['report_mode'] == 'consolidated'  # padrão
    r = api.post('/api/clients', json={'name': 'X', 'report_mode': 'mensal'})
    assert r.status_code == 422


def test_id_and_timestamps_are_immutable(api, make_client):
    c = make_client()
    for field in ('id', 'created_at', 'updated_at', 'subclient_count'):
        r = api.patch(f"/api/clients/{c['id']}", json={field: str(uuid.uuid4())})
        assert r.status_code == 422, field
    assert api.get(f"/api/clients/{c['id']}").json() == c


def test_list_pagination_filters_and_search(api, make_client):
    for i in range(5):
        make_client(name=f'Pag {i}', is_active=i % 2 == 0)
    page = api.get('/api/clients', params={'limit': 2, 'offset': 0}).json()
    assert page['total'] == 5 and page['limit'] == 2 and page['offset'] == 0
    assert [c['name'] for c in page['items']] == ['Pag 0', 'Pag 1']
    page = api.get('/api/clients', params={'limit': 2, 'offset': 4}).json()
    assert [c['name'] for c in page['items']] == ['Pag 4']
    assert api.get('/api/clients', params={'status': 'active'}).json()['total'] == 3
    assert api.get('/api/clients', params={'status': 'inactive'}).json()['total'] == 2
    assert api.get('/api/clients', params={'q': 'pag 3'}).json()['total'] == 1
    assert api.get('/api/clients', params={'q': '%'}).json()['total'] == 0  # curinga escapado
    for bad in ({'limit': 0}, {'limit': 201}, {'offset': -1}, {'status': 'deleted'}):
        assert api.get('/api/clients', params=bad).status_code == 422, bad


def test_validation_errors(api):
    cases = [
        {},  # name obrigatório
        {'name': ''},
        {'name': '   '},
        {'name': 'x' * 121},
        {'name': 'Linha\nquebrada'},
        {'name': 'Ok', 'display_name': ''},
        {'name': 'Ok', 'is_active': 'talvez'},
        {'name': 'Ok', 'connection_id': 'nao-e-uuid'},
        {'name': 'Ok', 'campo_extra': 1},
    ]
    for payload in cases:
        r = api.post('/api/clients', json=payload)
        assert r.status_code == 422, payload
        body = r.json()['error']
        assert body['code'] == 'validation_error' and body['details'], payload
    r = api.post('/api/clients', content=b'{"name": ', headers={'Content-Type': 'application/json'})
    assert r.status_code == 400 and error_code(r) == 'malformed_json'


def test_patch_rejects_null_on_required_fields(api, make_client):
    c = make_client()
    for field in ('name', 'display_name', 'is_active', 'report_mode'):
        r = api.patch(f"/api/clients/{c['id']}", json={field: None})
        assert r.status_code == 422, field


def test_invalid_and_unknown_uuid(api):
    r = api.get('/api/clients/123')
    assert r.status_code == 422 and error_code(r) == 'validation_error'
    r = api.get(f'/api/clients/{uuid.uuid4()}')
    assert r.status_code == 404 and error_code(r) == 'client_not_found'
    assert api.patch(f'/api/clients/{uuid.uuid4()}', json={'name': 'x'}).status_code == 404
    assert api.delete(f'/api/clients/{uuid.uuid4()}').status_code == 404


def test_duplicate_name_is_conflict_case_insensitive(api, make_client):
    a = make_client(name='Cliente Único')
    r = api.post('/api/clients', json={'name': 'CLIENTE ÚNICO'})  # caixa também em letras acentuadas
    assert r.status_code == 409 and error_code(r) == 'duplicate_name'
    make_client(name='Beta')
    r = api.post('/api/clients', json={'name': 'BETA'})
    assert r.status_code == 409 and error_code(r) == 'duplicate_name'
    b = make_client(name='Gama')
    r = api.patch(f"/api/clients/{b['id']}", json={'name': 'beta'})
    assert r.status_code == 409
    assert api.patch(f"/api/clients/{a['id']}", json={'name': 'Cliente Único'}).status_code == 200  # mesmo registro


def test_unknown_connection_reference_is_400(api, make_client):
    r = api.post('/api/clients', json={'name': 'Sem conexão', 'connection_id': str(uuid.uuid4())})
    assert r.status_code == 400 and error_code(r) == 'connection_not_found'
    c = make_client()
    r = api.patch(f"/api/clients/{c['id']}", json={'connection_id': str(uuid.uuid4())})
    assert r.status_code == 400


def test_delete_rules_prefer_deactivation(api, make_client, make_subclient):
    c = make_client()
    r = api.delete(f"/api/clients/{c['id']}")
    assert r.status_code == 409 and error_code(r) == 'client_active'

    parent = make_client()
    sub = make_subclient(parent['id'])
    api.patch(f"/api/clients/{parent['id']}", json={'is_active': False})
    r = api.delete(f"/api/clients/{parent['id']}")
    assert r.status_code == 409 and error_code(r) == 'client_has_subclients'
    # Referências preservadas: cliente e subcliente continuam consultáveis.
    assert api.get(f"/api/clients/{parent['id']}").json()['subclient_count'] == 1
    assert api.get(f"/api/subclients/{sub['id']}").status_code == 200

    # Caminho explícito: desativar e excluir subclientes, depois o cliente.
    api.patch(f"/api/subclients/{sub['id']}", json={'is_active': False})
    assert api.delete(f"/api/subclients/{sub['id']}").status_code == 204
    assert api.delete(f"/api/clients/{parent['id']}").status_code == 204


def test_client_without_subclients_works_in_all_reads(api, make_client):
    c = make_client(report_mode='consolidated')
    assert api.get(f"/api/clients/{c['id']}").json()['subclient_count'] == 0
    page = api.get(f"/api/clients/{c['id']}/subclients").json()
    assert page == {'items': [], 'total': 0, 'limit': 50, 'offset': 0}
