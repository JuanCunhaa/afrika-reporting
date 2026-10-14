"""Persistência real após reiniciar o processo do backend (uvicorn em subprocesso).

Também captura stdout/stderr do servidor para comprovar ausência de segredos em logs.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from app import db
from conftest import sqlite_url

BACKEND = Path(__file__).resolve().parents[1]
SENTINEL = 'SENTINELA_SEGREDO_7f3a9c'


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class Server:
    def __init__(self, url: str, log_path: Path, extra_args: tuple[str, ...] = ('--log-level', 'debug')):
        self.port = _free_port()
        self.base = f'http://127.0.0.1:{self.port}'
        env = {**os.environ, db.DATABASE_URL_ENV: url}
        self.log = open(log_path, 'ab')
        self.proc = subprocess.Popen(
            [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(self.port),
             *extra_args],
            cwd=BACKEND, env=env, stdout=self.log, stderr=subprocess.STDOUT)

    def __enter__(self) -> httpx.Client:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError('servidor encerrou ao iniciar')
            try:
                if httpx.get(f'{self.base}/api/health', timeout=1).status_code == 200:
                    self.http = httpx.Client(base_url=self.base, timeout=10)
                    return self.http
            except httpx.TransportError:
                time.sleep(0.2)
        raise RuntimeError('servidor não respondeu')

    def __exit__(self, *exc):
        if hasattr(self, 'http'):
            self.http.close()
        self.proc.terminate()
        self.proc.wait(timeout=15)
        self.log.close()


def test_data_survives_backend_restart_and_logs_have_no_secrets(tmp_path):
    url = sqlite_url(tmp_path / 'restart.sqlite3')
    db.upgrade(url)
    log_path = tmp_path / 'server.log'

    with Server(url, log_path) as http:
        conn = http.post('/api/connections', json={'name': 'Persistida', 'region': 'commercial',
                                                   'credential_ref': 'env:AFRIKA_PERSIST'}).json()
        client = http.post('/api/clients', json={'name': 'Cliente persistido', 'report_mode': 'both',
                                                 'connection_id': conn['id']}).json()
        sub = http.post(f"/api/clients/{client['id']}/subclients", json={'name': 'BU persistida'}).json()
        # Tentativas de enviar segredo: devem falhar sem eco e sem log.
        r1 = http.post('/api/connections', json={'name': 'Vazamento', 'region': 'commercial',
                                                 'credential_ref': 'env:OK_REF', 'api_key_secret': SENTINEL})
        r2 = http.patch(f"/api/connections/{conn['id']}", json={'credential_ref': SENTINEL})
        assert (r1.status_code, r2.status_code) == (422, 422)
        assert SENTINEL not in r1.text + r2.text

    with Server(url, log_path) as http:  # novo processo, mesmo arquivo
        c2 = http.get(f"/api/clients/{client['id']}").json()
        assert c2 == client | {'subclient_count': 1, 'active_subclient_count': 1}
        s2 = http.get(f"/api/subclients/{sub['id']}").json()
        assert s2 == sub
        assert s2['connection_source'] == 'client'
        assert http.get('/api/connections').json()['total'] == 1

    logs = log_path.read_text(encoding='utf-8', errors='replace')
    assert 'Application startup complete' in logs  # o log foi realmente capturado
    assert SENTINEL not in logs


def test_accidental_sqlalchemy_debug_log_config_does_not_leak_rows(tmp_path):
    """Servidor real iniciado com --log-config que liga sqlalchemy.engine em DEBUG (erro de operação)."""
    url = sqlite_url(tmp_path / 'debuglog.sqlite3')
    db.upgrade(url)
    log_config = tmp_path / 'log.json'
    log_config.write_text(json.dumps({
        'version': 1, 'disable_existing_loggers': False,
        'handlers': {'out': {'class': 'logging.StreamHandler', 'stream': 'ext://sys.stderr'}},
        'root': {'level': 'DEBUG', 'handlers': ['out']},
        'loggers': {'sqlalchemy.engine': {'level': 'DEBUG'}, 'sqlalchemy.engine.Engine': {'level': 'DEBUG'}},
    }), encoding='utf-8')
    log_path = tmp_path / 'server.log'
    marker = 'Cliente-Marcador-Linha'

    with Server(url, log_path, extra_args=('--log-config', str(log_config))) as http:
        cid = http.post('/api/clients', json={'name': marker}).json()['id']
        assert http.get(f'/api/clients/{cid}').json()['name'] == marker
        assert http.get('/api/clients').json()['items'][0]['name'] == marker

    logs = log_path.read_text(encoding='utf-8', errors='replace')
    assert 'SELECT clients.id' in logs  # o SQL do engine foi de fato logado (config DEBUG ativa)
    assert 'hidden due to hide_parameters' in logs
    assert marker not in logs and marker.lower() not in logs
