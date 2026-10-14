from __future__ import annotations

import ipaddress
import os
import socket

# F02.1: a suíte unitária NUNCA carrega o `.env` real (credenciais de teste não entram neste processo).
# Definido antes de importar app.main, que carrega o `.env` na importação.
os.environ['AFRIKA_DOTENV_DISABLED'] = '1'

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import create_app  # noqa: E402


# ---------------------------------------------------------------- F02.1: nenhuma chamada externa

class ExternalNetworkBlocked(RuntimeError):
    """Teste tentou resolver/conectar host fora do loopback."""


_LOCAL_NAMES = {'localhost', 'testserver'}


def _is_local(host) -> bool:
    if host is None:
        return True
    host = host.decode() if isinstance(host, bytes) else str(host)
    if host in _LOCAL_NAMES or host == '':
        return True
    try:
        return ipaddress.ip_address(host.split('%', 1)[0]).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True, scope='session')
def block_external_network():
    """DNS e connect só para loopback durante toda a suíte (socketpair do event loop continua funcionando)."""
    real_getaddrinfo, real_connect, real_connect_ex = socket.getaddrinfo, socket.socket.connect, \
        socket.socket.connect_ex

    def getaddrinfo(host, *args, **kwargs):
        if not _is_local(host):
            raise ExternalNetworkBlocked('resolução de host externo bloqueada nos testes')
        return real_getaddrinfo(host, *args, **kwargs)

    def _check(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6) and not _is_local(address[0]):
            raise ExternalNetworkBlocked('conexão externa bloqueada nos testes')

    def connect(self, address):
        _check(self, address)
        return real_connect(self, address)

    def connect_ex(self, address):
        _check(self, address)
        return real_connect_ex(self, address)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(socket, 'getaddrinfo', getaddrinfo)
        mp.setattr(socket.socket, 'connect', connect)
        mp.setattr(socket.socket, 'connect_ex', connect_ex)
        yield


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
