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


# ---------------------------------------------------------------- F02: Veracode (somente transporte simulado)

from app.veracode.fixtures import FixtureVeracode, synthetic_credentials  # noqa: E402
from app.veracode.settings import VeracodeSettings  # noqa: E402


def veracode_environ(**tenants: str) -> dict[str, str]:
    """Ambiente SINTÉTICO: {'ALPHA': 'alpha'} -> ALPHA_API_ID/ALPHA_API_KEY do tenant fixture 'alpha'."""
    env = {}
    for var, tenant in tenants.items():
        api_id, api_key = synthetic_credentials(tenant)
        env[f'{var}_API_ID'], env[f'{var}_API_KEY'] = api_id, api_key
    return env


class SleepRecorder:
    def __init__(self):
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


@pytest.fixture
def fake_veracode() -> FixtureVeracode:
    return FixtureVeracode()


@pytest.fixture
def vc_env() -> dict[str, str]:
    return veracode_environ(VC_ALPHA='alpha', VC_BETA='beta', VC_DENIED='denied')


@pytest.fixture
def vc_api(db_url, fake_veracode, vc_env):
    settings = VeracodeSettings(page_size=50, max_retries=2)
    app = create_app(db_url, veracode_settings=settings, veracode_transport=fake_veracode.transport(),
                     environ=vc_env, sleep=SleepRecorder())
    with TestClient(app) as client:
        yield client
