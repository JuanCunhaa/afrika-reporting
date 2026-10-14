"""F02 — autenticação HMAC, resolução de credenciais e configurações (somente dados sintéticos)."""
import hashlib
import hmac

import pytest

from app.veracode import credentials
from app.veracode.credentials import Credentials
from app.veracode.errors import VeracodeError
from app.veracode.fixtures import synthetic_credentials
from app.veracode.hmac_auth import authorization_header, signature, signing_data
from app.veracode.settings import SettingsError, VeracodeSettings

API_ID, API_KEY = synthetic_credentials('unit-test')


def _reference_signature(key_hex: str, nonce: bytes, ts: str, data: str) -> str:
    """Cadeia documentada pela Veracode, escrita de forma independente para comparação."""
    k1 = hmac.new(bytes.fromhex(key_hex), nonce, hashlib.sha256).digest()
    k2 = hmac.new(k1, ts.encode(), hashlib.sha256).digest()
    k3 = hmac.new(k2, b'vcode_request_version_1', hashlib.sha256).digest()
    return hmac.new(k3, data.encode(), hashlib.sha256).hexdigest()


def test_hmac_header_matches_documented_algorithm():
    nonce, ts = bytes(range(16)), '1760000000000'
    creds = Credentials(API_ID, API_KEY)
    header = authorization_header(creds, 'api.veracode.com', '/appsec/v1/applications?page=0&size=50', 'get',
                                  nonce=nonce, timestamp_ms=ts)
    data = f'id={API_ID}&host=api.veracode.com&url=/appsec/v1/applications?page=0&size=50&method=GET'
    assert signing_data(API_ID, 'api.veracode.com', '/appsec/v1/applications?page=0&size=50', 'get') == data
    expected_sig = _reference_signature(API_KEY, nonce, ts, data)
    assert header == f'VERACODE-HMAC-SHA-256 id={API_ID},ts={ts},nonce={nonce.hex()},sig={expected_sig}'
    assert signature(API_KEY, nonce, ts, data) == expected_sig


def test_hmac_uses_fresh_nonce_and_signature_depends_on_url():
    creds = Credentials(API_ID, API_KEY)
    a = authorization_header(creds, 'api.veracode.com', '/x?page=0', 'GET')
    b = authorization_header(creds, 'api.veracode.com', '/x?page=0', 'GET')
    assert a != b  # nonce novo a cada assinatura (anti-replay)
    nonce, ts = b'\x01' * 16, '1'
    s1 = authorization_header(creds, 'api.veracode.com', '/x?page=0', 'GET', nonce=nonce, timestamp_ms=ts)
    s2 = authorization_header(creds, 'api.veracode.com', '/x?page=1', 'GET', nonce=nonce, timestamp_ms=ts)
    s3 = authorization_header(creds, 'api.veracode.eu', '/x?page=0', 'GET', nonce=nonce, timestamp_ms=ts)
    assert len({s1, s2, s3}) == 3


def test_resolve_env_reference_to_api_id_and_key():
    env = {'CLIENTE_X_API_ID': API_ID, 'CLIENTE_X_API_KEY': API_KEY}
    creds = credentials.resolve('env:CLIENTE_X', env)
    assert (creds.api_id, creds.api_key) == (API_ID, API_KEY)
    assert credentials.credential_status('env:CLIENTE_X', env) == 'configured'


@pytest.mark.parametrize('env,code,status', [
    ({}, 'credentials_missing', 'missing'),
    ({'CX_API_ID': API_ID}, 'credentials_missing', 'missing'),
    ({'CX_API_ID': API_ID, 'CX_API_KEY': '   '}, 'credentials_missing', 'missing'),
    ({'CX_API_ID': API_ID, 'CX_API_KEY': 'nao-hex'}, 'credentials_invalid_format', 'invalid_format'),
    ({'CX_API_ID': 'id com espaço', 'CX_API_KEY': API_KEY}, 'credentials_invalid_format', 'invalid_format'),
    ({'CX_API_ID': API_ID, 'CX_API_KEY': API_KEY[:-1]}, 'credentials_invalid_format', 'invalid_format'),
])
def test_missing_or_invalid_credentials(env, code, status):
    with pytest.raises(VeracodeError) as exc:
        credentials.resolve('env:CX', env)
    assert exc.value.code == code
    assert credentials.credential_status('env:CX', env) == status
    for value in env.values():
        if value.strip():
            assert value not in exc.value.message and value not in repr(exc.value)


@pytest.mark.parametrize('ref', ['', 'C', 'vault:C', 'env:c', 'env:', 'env:C D', f'env:{"A" * 64}'])
def test_unsupported_reference(ref):
    with pytest.raises(VeracodeError) as exc:
        credentials.resolve(ref, {})
    assert exc.value.code == 'unsupported_credential_ref'


def test_credentials_repr_and_fingerprint_never_reveal_values():
    creds = Credentials(API_ID, API_KEY)
    for text in (repr(creds), str(creds), f'{creds}', repr([creds])):
        assert API_ID not in text and API_KEY not in text
    fp = creds.fingerprint
    assert len(fp) == 16 and fp not in API_ID and fp not in API_KEY
    assert fp == Credentials(API_ID, 'ff' * 64).fingerprint  # depende só do API ID
    assert fp != Credentials(synthetic_credentials('outro')[0], API_KEY).fingerprint


def test_settings_from_env_and_validation():
    s = VeracodeSettings.from_env({'AFRIKA_VERACODE_MAX_RETRIES': '5', 'AFRIKA_VERACODE_PAGE_SIZE': '200',
                                   'AFRIKA_VERACODE_CACHE_TTL': '0', 'AFRIKA_VERACODE_MODE': 'fixture',
                                   'AFRIKA_VERACODE_READ_TIMEOUT': '2.5'})
    assert (s.max_retries, s.page_size, s.cache_ttl, s.mode, s.read_timeout) == (5, 200, 0.0, 'fixture', 2.5)
    assert VeracodeSettings.from_env({}) == VeracodeSettings()
    for bad in ({'AFRIKA_VERACODE_PAGE_SIZE': '501'}, {'AFRIKA_VERACODE_MAX_CONCURRENCY': '0'},
                {'AFRIKA_VERACODE_MODE': 'prod'}, {'AFRIKA_VERACODE_MAX_RETRIES': 'x'}):
        with pytest.raises(SettingsError):
            VeracodeSettings.from_env(bad)
