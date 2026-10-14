"""Regressão F00: health, métricas demo sintéticas, demo de clientes (agora via seed explícito) e CORS."""
from fastapi.testclient import TestClient

from app import db
from app.main import create_app
from app.seed import seed_demo


def test_health(api):
    r = api.get('/api/health')
    assert r.status_code == 200
    body = r.json()
    assert body.pop('veracode_mode') in ('live', 'fixture')
    assert body == {'status': 'ok', 'phase': 'F02', 'data': 'local', 'auth': 'none'}


def test_demo_metrics_are_explicitly_synthetic(api):
    r = api.get('/api/demo/metrics')
    assert r.status_code == 200
    assert all(x['source'] == 'SYNTHETIC' and x['status'] == 'DEMO_ONLY' for x in r.json())


def test_new_database_starts_empty_no_automatic_seed(api):
    assert api.get('/api/clients').json()['total'] == 0
    assert api.get('/api/connections').json()['total'] == 0


def test_explicit_seed_recreates_f00_demo_clients_idempotently(db_url):
    engine = db.make_engine(db_url)
    try:
        with db.session_factory(engine)() as s:
            assert seed_demo(s) == {'connections': 1, 'clients': 2, 'subclients': 2}
        with db.session_factory(engine)() as s:
            assert seed_demo(s) == {'connections': 0, 'clients': 0, 'subclients': 0}
    finally:
        engine.dispose()
    with TestClient(create_app(db_url)) as api:
        rows = api.get('/api/clients').json()['items']
        by_name = {c['name']: c for c in rows}
        assert by_name['Cliente Demonstração']['subclient_count'] == 0  # cliente sem subclientes
        bus = by_name['Cliente com BUs (Sintético)']
        assert bus['subclient_count'] == 2
        subs = api.get(f"/api/clients/{bus['id']}/subclients").json()['items']
        assert sorted(s['name'] for s in subs) == ['Marketing', 'TI']
        assert all(s['connection_source'] == 'client' for s in subs)


def test_cors_allows_local_frontend_only(api):
    ok = api.options('/api/clients', headers={'Origin': 'http://localhost:5173', 'Access-Control-Request-Method': 'POST'})
    assert ok.headers.get('access-control-allow-origin') == 'http://localhost:5173'
    bad = api.options('/api/clients', headers={'Origin': 'http://evil.example', 'Access-Control-Request-Method': 'POST'})
    assert 'access-control-allow-origin' not in bad.headers
