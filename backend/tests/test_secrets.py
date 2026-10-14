"""Nenhum segredo em respostas, erros ou logs."""
import logging

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

SENTINEL = 'f4c3b00c' * 16  # formato de chave hexadecimal de 128 caracteres (sintético)
FORBIDDEN_KEYS = {'secret', 'api_key', 'api_secret', 'api_key_secret', 'password', 'token', 'hmac'}


def _walk_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_keys(v)


@pytest.fixture
def debug_logs(caplog):
    caplog.set_level(logging.DEBUG)
    logging.getLogger('sqlalchemy.engine').setLevel(logging.DEBUG)  # SQL + parâmetros, se houvesse vazamento
    yield caplog
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)


def test_secret_values_never_echoed_or_logged(api, make_connection, make_client, make_subclient, debug_logs):
    conn = make_connection()
    client = make_client(connection_id=conn['id'])
    sub = make_subclient(client['id'])
    attempts = [
        ('post', '/api/connections', {'name': 'A', 'region': 'commercial', 'credential_ref': SENTINEL}),
        ('post', '/api/connections', {'name': 'A', 'region': 'commercial', 'credential_ref': f'env:{SENTINEL.upper()}'}),
        ('post', '/api/connections', {'name': 'A', 'region': 'commercial', 'credential_ref': 'env:OK_REF',
                                      'api_key': SENTINEL}),
        ('patch', f"/api/connections/{conn['id']}", {'credential_ref': SENTINEL}),
        ('patch', f"/api/connections/{conn['id']}", {'secret': SENTINEL}),
        ('post', '/api/clients', {'name': 'B', 'api_key_secret': SENTINEL}),
        ('patch', f"/api/clients/{client['id']}", {'hmac': SENTINEL}),
        ('post', f"/api/clients/{client['id']}/subclients", {'name': 'C', 'password': SENTINEL}),
        ('patch', f"/api/subclients/{sub['id']}", {'connection_id': SENTINEL}),
    ]
    for method, path, payload in attempts:
        r = getattr(api, method)(path, json=payload)
        assert r.status_code == 422, (path, r.status_code)
        assert SENTINEL not in r.text and SENTINEL.upper() not in r.text
        assert 'input' not in r.json()['error']['details'][0]

    assert any(rec.name.startswith('sqlalchemy.engine') for rec in debug_logs.records)  # captura ativa
    assert SENTINEL not in debug_logs.text and SENTINEL.upper() not in debug_logs.text

    # Nenhuma resposta de leitura expõe campos de segredo.
    for path in ('/api/connections', '/api/clients', f"/api/clients/{client['id']}/subclients",
                 f"/api/connections/{conn['id']}", f"/api/subclients/{sub['id']}"):
        keys = {k.lower() for k in _walk_keys(api.get(path).json())}
        assert not keys & FORBIDDEN_KEYS, (path, keys & FORBIDDEN_KEYS)


def test_sql_parameters_hidden_in_logs(api, debug_logs):
    r = api.post('/api/clients', json={'name': 'Nome-Marcador-Log'})
    assert r.status_code == 201
    # INFO = SQL + parâmetros (ocultos). Em DEBUG o SQLAlchemy também loga LINHAS de resultado: por isso
    # sqlalchemy.engine fica em WARNING por padrão e nunca deve ir a DEBUG com dados reais (docs/SECURITY.md).
    sql_logs = '\n'.join(rec.getMessage() for rec in debug_logs.records
                         if rec.name.startswith('sqlalchemy.engine') and rec.levelno == logging.INFO)
    assert 'INSERT INTO clients' in sql_logs
    assert 'Nome-Marcador-Log' not in sql_logs
    assert 'hidden due to hide_parameters' in sql_logs


def test_unhandled_error_returns_generic_500_without_details(db_url, monkeypatch, caplog):
    from app import registry

    def boom(*_a, **_k):
        raise RuntimeError(f'falha interna com {SENTINEL}')
    monkeypatch.setattr(registry, 'list_clients', boom)
    with TestClient(create_app(db_url), raise_server_exceptions=False) as api:
        r = api.get('/api/clients')
    assert r.status_code == 500
    assert r.json() == {'error': {'code': 'internal_error', 'message': 'Erro interno', 'details': []}}
    app_logs = [rec.getMessage() for rec in caplog.records if rec.name.startswith('afrika')]
    assert any('RuntimeError' in m for m in app_logs)
    assert all(SENTINEL not in m for m in app_logs)
