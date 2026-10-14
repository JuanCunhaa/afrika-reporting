"""Cadastro de conexões: somente metadados + referência ao segredo."""
import uuid

import pytest

from conftest import error_code


def test_connection_crud_full_cycle(api):
    r = api.post('/api/connections', json={'name': 'Tenant principal', 'region': 'european',
                                           'credential_ref': 'env:VERACODE_TENANT_A', 'description': 'Sintética'})
    assert r.status_code == 201
    conn = r.json()
    assert set(conn) == {'id', 'name', 'description', 'region', 'credential_ref', 'client_count',
                         'subclient_count', 'created_at', 'updated_at'}
    assert conn['client_count'] == conn['subclient_count'] == 0
    cid = conn['id']
    assert api.get(f'/api/connections/{cid}').json() == conn
    assert api.get('/api/connections').json()['total'] == 1

    r = api.patch(f'/api/connections/{cid}', json={'region': 'federal', 'credential_ref': 'env:VERACODE_TENANT_B'})
    assert r.status_code == 200
    assert (r.json()['region'], r.json()['credential_ref']) == ('federal', 'env:VERACODE_TENANT_B')

    assert api.delete(f'/api/connections/{cid}').status_code == 204
    r = api.get(f'/api/connections/{cid}')
    assert r.status_code == 404 and error_code(r) == 'connection_not_found'


def test_connection_in_use_cannot_be_deleted(api, make_connection, make_client, make_subclient):
    used_by_client = make_connection()
    used_by_sub = make_connection()
    c = make_client(connection_id=used_by_client['id'])
    make_subclient(c['id'], connection_id=used_by_sub['id'])

    assert api.get(f"/api/connections/{used_by_client['id']}").json()['client_count'] == 1
    assert api.get(f"/api/connections/{used_by_sub['id']}").json()['subclient_count'] == 1
    for conn in (used_by_client, used_by_sub):
        r = api.delete(f"/api/connections/{conn['id']}")
        assert r.status_code == 409 and error_code(r) == 'connection_in_use'
    assert api.get(f"/api/clients/{c['id']}").json()['connection']['id'] == used_by_client['id']


def test_connection_duplicate_name_and_unknown_id(api, make_connection):
    make_connection(name='Única')
    r = api.post('/api/connections', json={'name': 'ÚNICA', 'region': 'commercial', 'credential_ref': 'env:X_Y'})
    assert r.status_code == 409
    assert api.patch(f'/api/connections/{uuid.uuid4()}', json={'name': 'x'}).status_code == 404
    assert api.delete(f'/api/connections/{uuid.uuid4()}').status_code == 404


@pytest.mark.parametrize('ref', [
    'VERACODE_API_KEY',                       # sem prefixo env:
    'env:veracode_lower',                     # minúsculas
    'env:1ABC',                               # começa com dígito
    'env:A',                                  # curto demais
    'env:' + 'A' * 70,                        # longo demais
    'env:NOME COM ESPACO',
    'vault:secret/path',                      # esquema não suportado ainda
    'env:ABCDEF0123456789ABCDEF0123456789',   # parece chave hexadecimal
    'env:KEY_DEADBEEFDEADBEEFDEADBEEFDEADBEEF',
])
def test_credential_ref_rejects_invalid_or_secret_like(api, ref):
    r = api.post('/api/connections', json={'name': 'Teste', 'region': 'commercial', 'credential_ref': ref})
    assert r.status_code == 422
    assert ref not in r.text


@pytest.mark.parametrize('payload', [
    {'name': 'X', 'region': 'commercial'},                                       # falta referência
    {'name': 'X', 'region': 'mars', 'credential_ref': 'env:OK_REF'},             # região inválida
    {'name': 'X', 'region': 'commercial', 'credential_ref': 'env:OK_REF', 'api_key': 'x'},
    {'name': 'X', 'region': 'commercial', 'credential_ref': 'env:OK_REF', 'api_secret': 'x'},
    {'name': 'X', 'region': 'commercial', 'credential_ref': 'env:OK_REF', 'api_id': 'x'},
])
def test_connection_payload_validation(api, payload):
    assert api.post('/api/connections', json=payload).status_code == 422
