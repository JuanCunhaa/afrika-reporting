from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import create_app


def sqlite_url(path) -> str:
    return f'sqlite:///{path.as_posix()}'


@pytest.fixture
def db_url(tmp_path) -> str:
    url = sqlite_url(tmp_path / 'test.sqlite3')
    db.upgrade(url)
    return url


@pytest.fixture
def api(db_url) -> TestClient:
    with TestClient(create_app(db_url)) as client:
        yield client


@pytest.fixture
def make_connection(api):
    counter = iter(range(1, 10_000))

    def _make(**overrides) -> dict:
        n = next(counter)
        payload = {'name': f'Conexão {n}', 'region': 'commercial', 'credential_ref': f'env:AFRIKA_TEST_CONN_{n}'}
        payload.update(overrides)
        r = api.post('/api/connections', json=payload)
        assert r.status_code == 201, r.text
        return r.json()
    return _make


@pytest.fixture
def make_client(api):
    counter = iter(range(1, 10_000))

    def _make(**overrides) -> dict:
        payload = {'name': f'Cliente Sintético {next(counter)}'}
        payload.update(overrides)
        r = api.post('/api/clients', json=payload)
        assert r.status_code == 201, r.text
        return r.json()
    return _make


@pytest.fixture
def make_subclient(api):
    counter = iter(range(1, 10_000))

    def _make(client_id: str, **overrides) -> dict:
        payload = {'name': f'BU {next(counter)}'}
        payload.update(overrides)
        r = api.post(f'/api/clients/{client_id}/subclients', json=payload)
        assert r.status_code == 201, r.text
        return r.json()
    return _make


def error_code(response) -> str:
    return response.json()['error']['code']
