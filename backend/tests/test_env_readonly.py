"""F02.1 — `.env` da raiz, referência env:AFRIKA_VC_TEST, precedência do sistema, trava somente leitura,
portão da homologação real e ausência de chamadas externas. Somente dados SINTÉTICOS; nenhuma chamada real."""
import ast
import asyncio
import json
import logging
import os
import socket
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import env_loader
from app.main import create_app
from app.veracode import adapters, credentials, live_gate
from app.veracode.credentials import Credentials
from app.veracode.fixtures import FixtureVeracode, synthetic_credentials
from app.veracode.http import CollectionRun, VeracodeHttpPool
from app.veracode.readonly import ALLOWED_HOSTS, ReadOnlyTransport, ReadOnlyViolation, check_request
from app.veracode.settings import SettingsError, VeracodeSettings

from conftest import ExternalNetworkBlocked, SleepRecorder

ROOT = Path(__file__).resolve().parents[2]
ALPHA_ID, ALPHA_KEY = synthetic_credentials('alpha')  # tenant fixture (não são chaves reais)


def write_env(tmp_path, **values) -> Path:
    path = tmp_path / '.env'
    lines = ['# sintético', *(f'{k}={v}' for k, v in values.items())]
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path


def test_env_example_template(tmp_path):
    # Mesmo formato que a ordem do PO pede para o `.env` local, com valores vazios.
    path = write_env(tmp_path, AFRIKA_VC_TEST_API_ID='', AFRIKA_VC_TEST_API_KEY='',
                     AFRIKA_VC_TEST_CONNECTION='env:AFRIKA_VC_TEST', VERACODE_READ_ONLY='true',
                     VERACODE_LIVE_TESTS_ENABLED='false')
    env = {}
    env_loader.load_project_env(path, env)
    assert credentials.credential_status(env['AFRIKA_VC_TEST_CONNECTION'], env) == 'missing'
    assert VeracodeSettings.from_env(env).read_only is True
    assert live_gate.evaluate(env, requested=True).enabled is False


# ---------------------------------------------------------------- 1. carregamento do .env

def test_dotenv_path_is_repo_root_independent_of_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert env_loader.DOTENV_PATH.is_absolute()
    assert env_loader.DOTENV_PATH == ROOT / '.env'
    assert (env_loader.REPO_ROOT / 'backend' / 'app' / 'env_loader.py').is_file()


def test_load_adds_values_returns_only_names_and_does_not_interpolate(tmp_path):
    path = write_env(tmp_path, AFRIKA_VC_TEST_API_ID=ALPHA_ID, AFRIKA_VC_TEST_API_KEY=ALPHA_KEY,
                     LITERAL='${AFRIKA_VC_TEST_API_ID}')
    env = {}
    added = env_loader.load_project_env(path, env)
    assert added == ['AFRIKA_VC_TEST_API_ID', 'AFRIKA_VC_TEST_API_KEY', 'LITERAL']
    assert env['AFRIKA_VC_TEST_API_ID'] == ALPHA_ID and env['LITERAL'] == '${AFRIKA_VC_TEST_API_ID}'
    assert ALPHA_ID not in json.dumps(added) and ALPHA_KEY not in json.dumps(added)


def test_missing_file_and_disable_flag(tmp_path):
    assert env_loader.load_project_env(tmp_path / 'nao-existe.env', {}) == []
    path = write_env(tmp_path, AFRIKA_VC_TEST_API_ID=ALPHA_ID)
    env = {'AFRIKA_DOTENV_DISABLED': '1'}
    assert env_loader.load_project_env(path, env) == [] and 'AFRIKA_VC_TEST_API_ID' not in env


def test_unit_suite_runs_with_dotenv_disabled():
    assert env_loader.dotenv_disabled()  # conftest: o .env real nunca entra no processo de testes
    assert env_loader.load_project_env() == []


# ---------------------------------------------------------------- 2. env:AFRIKA_VC_TEST

def test_reference_resolves_from_loaded_dotenv(tmp_path):
    env = {}
    env_loader.load_project_env(write_env(tmp_path, AFRIKA_VC_TEST_API_ID=ALPHA_ID,
                                          AFRIKA_VC_TEST_API_KEY=ALPHA_KEY), env)
    creds = credentials.resolve('env:AFRIKA_VC_TEST', env)
    assert (creds.api_id, creds.api_key) == (ALPHA_ID, ALPHA_KEY)
    assert credentials.credential_status('env:AFRIKA_VC_TEST', env) == 'configured'
    assert ALPHA_ID not in repr(creds) and ALPHA_KEY not in str(creds)


# ---------------------------------------------------------------- 3. precedência do sistema

def test_system_environment_wins_over_dotenv(tmp_path):
    system_id, system_key = synthetic_credentials('beta')
    path = write_env(tmp_path, AFRIKA_VC_TEST_API_ID=ALPHA_ID, AFRIKA_VC_TEST_API_KEY=ALPHA_KEY,
                     VERACODE_LIVE_TESTS_ENABLED='true')
    env = {'AFRIKA_VC_TEST_API_ID': system_id, 'AFRIKA_VC_TEST_API_KEY': system_key,
           'VERACODE_LIVE_TESTS_ENABLED': ''}  # definida vazia no sistema também prevalece
    added = env_loader.load_project_env(path, env)
    assert added == []
    assert credentials.resolve('env:AFRIKA_VC_TEST', env).api_id == system_id
    assert env['VERACODE_LIVE_TESTS_ENABLED'] == ''


def test_os_environ_is_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.delenv('AFRIKA_DOTENV_DISABLED')
    monkeypatch.setenv('AFRIKA_F021_PRECEDENCE', 'sistema')
    monkeypatch.delenv('AFRIKA_F021_NEW', raising=False)
    path = write_env(tmp_path, AFRIKA_F021_PRECEDENCE='dotenv', AFRIKA_F021_NEW='dotenv')
    try:
        assert env_loader.load_project_env(path) == ['AFRIKA_F021_NEW']
        assert os.environ['AFRIKA_F021_PRECEDENCE'] == 'sistema' and os.environ['AFRIKA_F021_NEW'] == 'dotenv'
    finally:
        os.environ.pop('AFRIKA_F021_NEW', None)


# ---------------------------------------------------------------- 4. credenciais fora de respostas e logs

def test_credentials_from_dotenv_never_in_responses_or_logs(tmp_path, db_url, caplog):
    caplog.set_level(logging.DEBUG)
    env = {}
    env_loader.load_project_env(write_env(tmp_path, AFRIKA_VC_TEST_API_ID=ALPHA_ID,
                                          AFRIKA_VC_TEST_API_KEY=ALPHA_KEY,
                                          AFRIKA_VC_TEST_CONNECTION='env:AFRIKA_VC_TEST'), env)
    app = create_app(db_url, veracode_settings=VeracodeSettings(page_size=50),
                     veracode_transport=FixtureVeracode().transport(), environ=env, sleep=SleepRecorder())
    bodies = []
    with TestClient(app) as api:
        conn = api.post('/api/connections', json={'name': 'Teste', 'region': 'commercial',
                                                  'credential_ref': env['AFRIKA_VC_TEST_CONNECTION']})
        client = api.post('/api/clients', json={'name': 'Cliente Sintético', 'connection_id': conn.json()['id']})
        cid = client.json()['id']
        test = api.post(f'/api/veracode/clients/{cid}/test')
        assert test.status_code == 200 and test.json()['status'] == 'ok'
        responses = [conn, client, test, api.get(f'/api/veracode/clients/{cid}'), api.get('/api/connections'),
                     api.get(f'/api/veracode/clients/{cid}/applications', params={'limit': 5}),
                     api.get(f'/api/veracode/clients/{cid}/users'), api.get('/api/health')]
        for r in responses:
            assert r.status_code in (200, 201), r.text
            bodies.append(r.text + json.dumps(dict(r.headers)))
    text = '\n'.join(bodies) + caplog.text
    for secret in (ALPHA_ID, ALPHA_KEY, ALPHA_ID.upper(), ALPHA_KEY[:24], 'AFRIKA_VC_TEST_API_ID',
                   'AFRIKA_VC_TEST_API_KEY'):
        assert secret not in text


# ---------------------------------------------------------------- 5. somente GET, host e endpoints autorizados

BLOCKED_METHODS = ('POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS', 'TRACE')


def _with_client(fn):
    sent = []

    async def main():
        pool = VeracodeHttpPool(VeracodeSettings(), httpx.MockTransport(
            lambda req: sent.append(req) or httpx.Response(200, json={})))
        try:
            await fn(pool.client('commercial'))
        finally:
            await pool.aclose()
    asyncio.run(main())
    return sent


@pytest.mark.parametrize('method', BLOCKED_METHODS)
def test_non_get_blocked_via_request_send_and_stream(method):
    async def attempt(client):
        with pytest.raises(ReadOnlyViolation):
            await client.request(method, adapters.APPLICATIONS)
        with pytest.raises(ReadOnlyViolation):
            await client.send(client.build_request(method, adapters.APPLICATIONS))
        with pytest.raises(ReadOnlyViolation):
            async with client.stream(method, adapters.USERS):
                pass
    assert _with_client(attempt) == []


@pytest.mark.parametrize('method', BLOCKED_METHODS)
def test_transport_layer_blocks_even_without_client_hooks(method):
    sent = []
    transport = ReadOnlyTransport(httpx.MockTransport(lambda req: sent.append(req) or httpx.Response(200)))
    req = httpx.Request(method, 'https://api.veracode.com/appsec/v1/applications')

    async def main():
        # um cliente sem event hooks (como uma biblioteca montaria) continua barrado no transporte
        async with httpx.AsyncClient(transport=transport) as raw:
            with pytest.raises(ReadOnlyViolation):
                await raw.send(req)
    asyncio.run(main())
    assert sent == []


@pytest.mark.parametrize('url', [
    'https://api.veracode.com/appsec/v1/applications/abc/findings',      # v1 não é a Findings API homologada
    'https://api.veracode.com/appsec/v2/applications/abc/findings/123',  # F04: só a lista por aplicação
    'https://api.veracode.com/appsec/v2/applications/../x/findings',
    'https://api.veracode.com/appsec/v1/cwes',
    'https://api.veracode.com/srcclr/v3/workspaces',                     # SCA Agent: não homologado (F04)
    'https://api.veracode.com/api/authn/v2/api_credentials',
    'https://api.veracode.com/appsec/v1/policies',
    'https://api.veracode.com/appsec/v1/applications/../policies/sandboxes',
    'https://api.veracode.com/api/authn/v2/teams/x/y',
    'https://api.veracode.com/',
    'http://api.veracode.com/appsec/v1/applications',                     # sem TLS
    'https://api.veracode.com' + ':8443/appsec/v1/applications',        # porta não padrão
    'https://evil.example/appsec/v1/applications',
    'https://api.veracode.com.evil.example/appsec/v1/applications',
])
def test_get_outside_allowlist_is_blocked(url):
    with pytest.raises(ReadOnlyViolation):
        check_request(httpx.Request('GET', url))

    async def attempt(client):
        with pytest.raises(ReadOnlyViolation):
            await client.get(url)
    assert _with_client(attempt) == []


def test_allowlist_covers_every_adapter_endpoint_on_every_region():
    paths = [adapters.APPLICATIONS, adapters.SANDBOXES.format(guid='00000000-aaaa'), adapters.BUSINESS_UNITS,
             adapters.TEAMS, adapters.TEAM_DETAIL.format(team_id='t%2F1'), adapters.USERS,
             adapters.FINDINGS.format(guid='00000000-aaaa')]
    for host in ALLOWED_HOSTS:
        for path in paths:
            check_request(httpx.Request('GET', f'https://{host}{path}', params={'page': 0, 'size': 1}))


@pytest.mark.parametrize('value', ['false', 'False', '0', 'no', 'maybe'])
def test_read_only_flag_cannot_be_disabled(value, db_url, monkeypatch):
    with pytest.raises(SettingsError):
        VeracodeSettings.from_env({'VERACODE_READ_ONLY': value})
    monkeypatch.setenv('VERACODE_READ_ONLY', value)
    with pytest.raises(SettingsError):
        create_app(db_url)  # backend recusa iniciar: não existe modo com escrita


def test_read_only_flag_true_or_absent_and_pool_refuses_relaxed_settings():
    assert VeracodeSettings.from_env({}).read_only is True
    assert VeracodeSettings.from_env({'VERACODE_READ_ONLY': 'true'}).read_only is True
    with pytest.raises(SettingsError):
        VeracodeSettings(read_only=False)
    relaxed = object.__new__(VeracodeSettings)  # contorna __post_init__ de propósito
    object.__setattr__(relaxed, 'read_only', False)
    with pytest.raises(ReadOnlyViolation):
        VeracodeHttpPool(relaxed)


def test_app_code_uses_no_other_http_library():
    forbidden = {'requests', 'urllib.request', 'urllib3', 'http.client', 'aiohttp', 'pycurl'}
    for py in (ROOT / 'backend' / 'app').rglob('*.py'):
        tree = ast.parse(py.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module] if isinstance(node, ast.ImportFrom) and node.module else []
            assert not forbidden.intersection(names), f'{py.name} importa cliente HTTP fora da trava'


# ---------------------------------------------------------------- 6. homologação real desligada por padrão

def _live_env(**overrides):
    env = {'AFRIKA_VC_TEST_API_ID': ALPHA_ID, 'AFRIKA_VC_TEST_API_KEY': ALPHA_KEY,
           'AFRIKA_VC_TEST_CONNECTION': 'env:AFRIKA_VC_TEST', 'VERACODE_READ_ONLY': 'true',
           'VERACODE_LIVE_TESTS_ENABLED': 'true'}
    env.update(overrides)
    return {k: v for k, v in env.items() if v is not None}


@pytest.mark.parametrize('requested,overrides,fragment', [
    (False, {}, 'não solicitada'),
    (True, {'VERACODE_LIVE_TESTS_ENABLED': None}, 'VERACODE_LIVE_TESTS_ENABLED'),
    (True, {'VERACODE_LIVE_TESTS_ENABLED': 'false'}, 'VERACODE_LIVE_TESTS_ENABLED'),
    (True, {'VERACODE_READ_ONLY': 'false'}, 'VERACODE_READ_ONLY'),
    (True, {'AFRIKA_VC_TEST_API_KEY': ''}, 'missing'),
    (True, {'AFRIKA_VC_TEST_API_ID': 'nao-hex'}, 'invalid_format'),
    (True, {'AFRIKA_VC_TEST_CONNECTION': 'segredo-colado-aqui'}, 'AFRIKA_VC_TEST_CONNECTION'),
    (True, {'AFRIKA_VC_TEST_REGION': 'marte'}, 'AFRIKA_VC_TEST_REGION'),
])
def test_live_gate_requires_every_condition(requested, overrides, fragment):
    gate = live_gate.evaluate(_live_env(**overrides), requested=requested)
    assert gate.enabled is False and fragment in gate.reason
    for secret in (ALPHA_ID, ALPHA_KEY, 'nao-hex', 'segredo-colado-aqui'):
        assert secret not in gate.reason


def test_live_gate_opens_only_with_everything():
    gate = live_gate.evaluate(_live_env(), requested=True)
    assert (gate.enabled, gate.credential_ref, gate.region) == (True, 'env:AFRIKA_VC_TEST', 'commercial')
    assert live_gate.evaluate({}, requested=True).enabled is False


@pytest.mark.parametrize('extra_args', [[], ['--run-veracode-live']])
def test_live_suite_is_skipped_by_default(extra_args):
    """Executa o pytest do diretório tests_live em subprocesso SEM rede liberada: tudo ignorado."""
    env = {**os.environ, 'AFRIKA_DOTENV_DISABLED': '1', 'VERACODE_LIVE_TESTS_ENABLED': 'false',
           'PYTHONDONTWRITEBYTECODE': '1',
           'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
    out = subprocess.run([sys.executable, '-m', 'pytest', 'backend/tests_live', '-q', '-rs', '-p',
                          'no:cacheprovider', *extra_args], cwd=ROOT, env=env, capture_output=True, text=True,
                         encoding='utf-8', timeout=120)
    assert out.returncode == 0, out.stdout[-2000:]
    collected = int(subprocess.run([sys.executable, '-m', 'pytest', 'backend/tests_live', '--collect-only', '-q',
                                    '-p', 'no:cacheprovider'], cwd=ROOT, env=env, capture_output=True, text=True,
                                   encoding='utf-8', timeout=120).stdout.count('::'))
    assert collected > 0 and f'{collected} skipped' in out.stdout  # todos, sem depender do total de testes live
    assert 'passed' not in out.stdout and 'failed' not in out.stdout
    assert ('não solicitada' if not extra_args else 'VERACODE_LIVE_TESTS_ENABLED') in out.stdout


def test_default_pytest_config_excludes_live_suite():
    assert 'testpaths = backend/tests' in (ROOT / 'pytest.ini').read_text(encoding='utf-8')


# ---------------------------------------------------------------- 7. nenhuma chamada externa

def test_external_dns_and_connect_are_blocked_in_tests():
    with pytest.raises(ExternalNetworkBlocked):
        socket.getaddrinfo('api.veracode.com', 443)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(ExternalNetworkBlocked):
            s.connect(('203.0.113.10', 443))  # TEST-NET-3 (documentação)
    finally:
        s.close()


def test_real_transport_cannot_reach_veracode_during_tests():
    async def main():
        pool = VeracodeHttpPool(VeracodeSettings(max_retries=0))  # transporte REAL (sem simulação)
        try:
            run = CollectionRun(pool, Credentials(ALPHA_ID, ALPHA_KEY), 'commercial')
            with pytest.raises(ExternalNetworkBlocked):
                await run.get_json(adapters.APPLICATIONS, {'page': 0, 'size': 1}, label='guard')
        finally:
            await pool.aclose()
    asyncio.run(main())


def test_e2e_backend_runs_fixture_mode_without_dotenv():
    creds = (ROOT / 'frontend' / 'e2e' / 'fixture-creds.ts').read_text(encoding='utf-8')
    assert "AFRIKA_VERACODE_MODE: 'fixture'" in creds and "AFRIKA_DOTENV_DISABLED: '1'" in creds
    assert 'veracodeFixtureEnv' in (ROOT / 'frontend' / 'playwright.config.ts').read_text(encoding='utf-8')
