"""Chromium headless controlado pelo DevTools Protocol (CDP) — motor de renderização da exportação (F07).

Segurança e isolamento:
- Executável descoberto localmente (ordem: `AFRIKA_EXPORT_BROWSER` absoluto > Chromium headless do Playwright na
  revisão do frontend — o mesmo motor da regressão visual > Chromium/Chrome/Edge do sistema). Nunca vem da requisição.
- Processo iniciado SEM shell, com lista fixa de argumentos, perfil temporário próprio (apagado no fim), porta de
  depuração efêmera só em 127.0.0.1 (lida de `DevToolsActivePort`), resolução de nomes desligada
  (`--host-resolver-rules=MAP * ~NOTFOUND`) e todas as requisições da página interceptadas (`Fetch`): o que não for
  servido explicitamente pelo backend é bloqueado. Nada sai da máquina.
- Prazo global por sessão; ao fim (ou erro/prazo), `Browser.close` e, se preciso, `kill` do processo.
"""
from __future__ import annotations

import base64
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from websockets.sync.client import connect

from app.db import REPO_ROOT
from app.export.errors import ExportError

BROWSER_ENV = 'AFRIKA_EXPORT_BROWSER'
MAX_MESSAGE = 64 * 2**20


@dataclass(frozen=True)
class BrowserExe:
    path: Path
    source: str  # configured | playwright-headless-shell | playwright-chromium | system


def _playwright_root(environ) -> Path | None:
    custom = environ.get('PLAYWRIGHT_BROWSERS_PATH')
    if custom and custom != '0':
        return Path(custom)
    if sys.platform == 'win32':
        base = environ.get('LOCALAPPDATA')
        return Path(base) / 'ms-playwright' if base else None
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Caches' / 'ms-playwright'
    return Path(environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'ms-playwright'


def _playwright_revision() -> str | None:
    """Revisão do Chromium do @playwright/test instalado no frontend (mesmo motor da regressão visual)."""
    f = REPO_ROOT / 'frontend' / 'node_modules' / 'playwright-core' / 'browsers.json'
    try:
        data = json.loads(f.read_text(encoding='utf-8'))
        return next(b['revision'] for b in data['browsers'] if b['name'] == 'chromium-headless-shell')
    except (OSError, ValueError, StopIteration, KeyError):
        return None


def _playwright_candidates(root: Path, revision: str | None) -> list[BrowserExe]:
    shells = {'win32': ['chrome-headless-shell-win64/chrome-headless-shell.exe', 'chrome-win/headless_shell.exe'],
              'darwin': ['chrome-headless-shell-mac-arm64/chrome-headless-shell',
                         'chrome-headless-shell-mac-x64/chrome-headless-shell', 'chrome-mac/headless_shell'],
              'linux': ['chrome-headless-shell-linux64/chrome-headless-shell', 'chrome-linux/headless_shell']}
    fulls = {'win32': ['chrome-win64/chrome.exe', 'chrome-win/chrome.exe'],
             'darwin': ['chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
                        'chrome-mac/Chromium.app/Contents/MacOS/Chromium'],
             'linux': ['chrome-linux64/chrome', 'chrome-linux/chrome']}
    key = 'win32' if sys.platform == 'win32' else 'darwin' if sys.platform == 'darwin' else 'linux'
    out: list[BrowserExe] = []
    for prefix, rels, source in (('chromium_headless_shell-', shells[key], 'playwright-headless-shell'),
                                 ('chromium-', fulls[key], 'playwright-chromium')):
        dirs = [root / f'{prefix}{revision}'] if revision else []
        if root.is_dir():  # outras revisões instaladas, da mais nova para a mais velha
            dirs += sorted((d for d in root.glob(f'{prefix}[0-9]*') if d not in dirs),
                           key=lambda d: int(d.name.rsplit('-', 1)[-1]), reverse=True)
        out += [BrowserExe(d / r, source) for d in dirs for r in rels]
    return out


def _system_candidates(environ) -> list[BrowserExe]:
    paths: list[str] = []
    if sys.platform == 'win32':
        for base in (environ.get('PROGRAMFILES'), environ.get('PROGRAMFILES(X86)'), environ.get('LOCALAPPDATA')):
            if base:
                paths += [rf'{base}\Google\Chrome\Application\chrome.exe', rf'{base}\Microsoft\Edge\Application\msedge.exe',
                          rf'{base}\Chromium\Application\chrome.exe']
    elif sys.platform == 'darwin':
        paths += ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                  '/Applications/Chromium.app/Contents/MacOS/Chromium',
                  '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge']
    else:
        paths += [p for p in (shutil.which(n) for n in ('chromium', 'chromium-browser', 'google-chrome',
                                                        'google-chrome-stable', 'microsoft-edge')) if p]
    return [BrowserExe(Path(p), 'system') for p in paths]


def discover(environ: dict | None = None) -> BrowserExe:
    env = os.environ if environ is None else environ
    configured = env.get(BROWSER_ENV)
    if configured:
        p = Path(configured)
        if not p.is_absolute() or not p.is_file():
            raise ExportError('export_engine_unavailable', f'{BROWSER_ENV} não aponta para um executável existente '
                                                           '(caminho absoluto).', status=503)
        return BrowserExe(p, 'configured')
    cands = []
    root = _playwright_root(env)
    if root is not None:
        cands += _playwright_candidates(root, _playwright_revision())
    cands += _system_candidates(env)
    for c in cands:
        if c.path.is_file():
            return c
    raise ExportError('export_engine_unavailable', 'Nenhum Chromium/Chrome/Edge encontrado para renderizar a '
                                                   'exportação. Instale com "npx playwright install chromium" em '
                                                   f'frontend/ ou defina {BROWSER_ENV}.', status=503)


def _args(exe: BrowserExe, profile: Path) -> list[str]:
    args = [str(exe.path), '--headless' if exe.source == 'playwright-headless-shell' else '--headless=new',
            f'--user-data-dir={profile}', '--remote-debugging-port=0', '--remote-debugging-address=127.0.0.1',
            '--no-first-run', '--no-default-browser-check', '--disable-extensions', '--disable-default-apps',
            '--disable-component-extensions-with-background-pages', '--disable-background-networking',
            '--disable-component-update', '--disable-sync', '--disable-client-side-phishing-detection',
            '--disable-breakpad', '--disable-domain-reliability', '--metrics-recording-only', '--mute-audio',
            '--no-pings', '--password-store=basic', '--use-mock-keychain', '--hide-scrollbars',
            '--force-color-profile=srgb', '--disable-features=Translate,MediaRouter,OptimizationHints,'
            'AutofillServerCommunication,InterestFeedContentSuggestions,CalculateNativeWinOcclusion',
            '--host-resolver-rules=MAP * ~NOTFOUND']
    if sys.platform.startswith('linux'):
        # mesmo comportamento padrão do Playwright em contêineres/CI (namespaces de usuário restritos); a página é
        # local, sem rede e só com conteúdo servido pelo próprio backend
        args += ['--no-sandbox', '--disable-dev-shm-usage']
    return args + ['about:blank']


class Session:
    """Conexão CDP síncrona (uma página). Eventos são despachados para handlers durante a espera de respostas."""

    def __init__(self, exe: BrowserExe, deadline: float):
        self.exe, self.deadline = exe, deadline
        self.profile = Path(tempfile.mkdtemp(prefix='afrika-chromium-'))
        self.proc: subprocess.Popen | None = None
        self.ws = None
        self._ctx = None
        self.next_id = 0
        self.responses: dict[int, dict] = {}  # respostas que chegaram durante chamadas aninhadas (handlers)
        self.ignored: set[int] = set()  # ids enviados sem espera (respostas descartadas ao chegar)
        self.handlers: dict[str, Callable[[dict], None]] = {}
        self.page: str | None = None
        self.version: dict = {}

    # ------------------------------------------------------------ ciclo de vida
    def __enter__(self) -> Session:
        try:
            self._start()
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def remaining(self) -> float:
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise ExportError('export_timeout', 'Tempo limite da renderização excedido', status=504)
        return left

    def _start(self) -> None:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        self.proc = subprocess.Popen(_args(self.exe, self.profile), stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False,
                                     creationflags=flags)
        port_file = self.profile / 'DevToolsActivePort'
        start = time.monotonic()
        while not port_file.is_file() or len(port_file.read_text(errors='ignore').split()) < 2:
            if self.proc.poll() is not None:
                raise ExportError('export_engine_failed', 'O navegador de renderização encerrou ao iniciar', status=503)
            if time.monotonic() - start > min(20.0, self.remaining()):
                raise ExportError('export_engine_failed', 'O navegador de renderização não iniciou a tempo', status=503)
            time.sleep(0.05)
        port, path = port_file.read_text().split()[:2]
        if not port.isdigit() or not path.startswith('/devtools/browser/'):
            raise ExportError('export_engine_failed', 'Porta de depuração inválida', status=503)
        self._ctx = connect(f'ws://127.0.0.1:{int(port)}{path}', max_size=MAX_MESSAGE, open_timeout=10,
                            close_timeout=2, compression=None)
        self.ws = self._ctx.__enter__()
        self.version = self.send('Browser.getVersion')
        target = self.send('Target.createTarget', {'url': 'about:blank'})['targetId']
        self.page = self.send('Target.attachToTarget', {'targetId': target, 'flatten': True})['sessionId']

    def close(self) -> None:
        if self.ws is not None:
            try:
                self._send_raw({'id': self._id(), 'method': 'Browser.close', 'params': {}})
            except Exception:  # noqa: BLE001 — encerramento melhor esforço; o kill abaixo garante
                pass
            try:
                self._ctx.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
            self.ws = None
        if self.proc is not None:
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            self.proc = None
        for _ in range(20):  # Windows: arquivos do perfil podem ficar presos por instantes após o encerramento
            shutil.rmtree(self.profile, ignore_errors=True)
            if not self.profile.exists():
                break
            time.sleep(0.1)

    # ------------------------------------------------------------ protocolo
    def _id(self) -> int:
        self.next_id += 1
        return self.next_id

    def _send_raw(self, msg: dict) -> None:
        self.ws.send(json.dumps(msg))

    def _handle(self, data: dict) -> None:
        """Mensagem recebida: resposta (guardada por id) ou evento (despachado; o handler pode chamar `send`)."""
        if 'id' in data:
            if data['id'] in self.ignored:
                self.ignored.discard(data['id'])
            else:
                self.responses[data['id']] = data
        elif 'method' in data:
            handler = self.handlers.get(data['method'])
            if handler is not None:
                handler(data)

    def send(self, method: str, params: dict | None = None, *, page: bool = False, timeout: float | None = None,
             wait: bool = True) -> Any:
        mid = self._id()
        msg: dict = {'id': mid, 'method': method, 'params': params or {}}
        if page:
            msg['sessionId'] = self.page
        if not wait:
            self.ignored.add(mid)
            self._send_raw(msg)
            return None
        self._send_raw(msg)
        limit = time.monotonic() + (timeout if timeout is not None else 60.0)
        while mid not in self.responses:
            left = min(limit - time.monotonic(), self.remaining())
            if left <= 0:
                raise ExportError('export_timeout', f'Sem resposta do navegador ({method})', status=504)
            try:
                raw = self.ws.recv(timeout=left)
            except TimeoutError:
                raise ExportError('export_timeout', f'Sem resposta do navegador ({method})', status=504) from None
            self._handle(json.loads(raw))
        data = self.responses.pop(mid)
        if 'error' in data:
            raise ExportError('export_engine_failed', f'Erro do navegador em {method}: '
                                                      f'{data["error"].get("message", "")[:200]}', status=503)
        return data.get('result', {})

    def pump(self, until: Callable[[], bool], timeout: float, poll: Callable[[], None] | None = None) -> None:
        """Processa eventos até `until()` (ou prazo). `poll` roda entre leituras (ex.: consulta do sinal de pronto)."""
        limit = time.monotonic() + timeout
        while not until():
            wait = min(limit - time.monotonic(), self.remaining())
            if wait <= 0:
                raise ExportError('export_timeout', 'Tempo limite aguardando a renderização', status=504)
            if poll is not None:
                poll()
                if until():
                    return
            try:
                raw = self.ws.recv(timeout=min(wait, 0.1))
            except TimeoutError:
                continue
            self._handle(json.loads(raw))

    def evaluate(self, expression: str, timeout: float = 60.0) -> Any:
        r = self.send('Runtime.evaluate', {'expression': expression, 'returnByValue': True, 'awaitPromise': True},
                      page=True, timeout=timeout)
        if 'exceptionDetails' in r:
            text = r['exceptionDetails'].get('exception', {}).get('description') or r['exceptionDetails'].get('text')
            raise ExportError('render_script_failed', f'Falha no script de exportação da página: {str(text)[:300]}',
                              status=500)
        return r.get('result', {}).get('value')

    def read_stream(self, handle: str, max_bytes: int) -> bytes:
        out = bytearray()
        try:
            while True:
                chunk = self.send('IO.read', {'handle': handle, 'size': 1 << 20}, page=True, timeout=60)
                data = chunk.get('data', '')
                out += base64.b64decode(data) if chunk.get('base64Encoded') else data.encode('latin-1')
                if len(out) > max_bytes:
                    raise ExportError('export_too_large', 'Arquivo gerado maior que o limite', status=413)
                if chunk.get('eof'):
                    return bytes(out)
        finally:
            try:
                self.send('IO.close', {'handle': handle}, page=True, timeout=10)
            except ExportError:
                pass


def engine_info(exe: BrowserExe, version: dict) -> dict:
    return {'source': exe.source, 'product': version.get('product'), 'revision': version.get('revision'),
            'platform': f'{platform.system()} {platform.machine()}'}
