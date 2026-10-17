"""Captura da apresentação renderizada (F07): layout por slide, overflow, fontes efetivas e PDF — uma única sessão.

A página é a rota `#/render/{id}/{revisão}` do build do frontend, carregada de uma origem FICTÍCIA
(`http://afrika-export.invalid`) cujas requisições são todas interceptadas:
- arquivos do `dist` (somente dentro da pasta, resolvidos e conferidos);
- `GET /api/presentations/{id}/view?revision=n` => a MESMA visualização (bytes) que alimenta o PPTX;
- ativos do tema (`/api/theme-assets/{sha256}`) e de marca do tema da apresentação (`/api/brand-assets/...`);
- qualquer outra coisa => bloqueada e registrada (sem query string).
"""
from __future__ import annotations

import json
import mimetypes
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlsplit

from app.errors import ApiError
from app.export import browser
from app.export.errors import ExportError
from app.export.renderer import Renderer
from app.presentations import assets, brand_assets

ORIGIN = 'http://afrika-export.invalid'
LAYOUT_VERSION = 1
MAX_PDF_BYTES = 100 * 2**20
_TYPES = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
          '.json': 'application/json', '.woff2': 'font/woff2', '.woff': 'font/woff', '.ttf': 'font/ttf',
          '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.ico': 'image/x-icon'}


@dataclass
class Capture:
    layouts: list[dict]
    overflow: list[dict]
    fonts: dict[int, dict]  # slide index -> {xid: [fontes de plataforma usadas]}
    webfonts: list[str]  # famílias @font-face CARREGADAS
    pdf: bytes | None
    engine: dict
    blocked: list[str] = field(default_factory=list)
    timings: dict = field(default_factory=dict)
    declared_fonts: list[str] = field(default_factory=list)  # famílias @font-face declaradas (carregadas ou não)
    rasters: dict[str, bytes] = field(default_factory=dict)  # PNG de reserva de ativos SVG (o PPTX exige)


class _Server:
    """Responde às requisições interceptadas da página (nada além do necessário)."""

    def __init__(self, s: browser.Session, renderer: Renderer, pid: str, revision: int, view_bytes: bytes,
                 theme_id: str, slots: set[str], block_fonts: bool = False):
        self.s, self.dist, self.pid, self.revision = s, renderer.dist, pid, revision
        self.view_bytes, self.theme_id, self.slots, self.block_fonts = view_bytes, theme_id, slots, block_fonts
        self.blocked: list[str] = []
        self.served = 0

    def _fulfill(self, rid: str, body: bytes, ctype: str, status: int = 200) -> None:
        import base64
        self.s.send('Fetch.fulfillRequest', {'requestId': rid, 'responseCode': status, 'responseHeaders': [
            {'name': 'Content-Type', 'value': ctype}, {'name': 'Cache-Control', 'value': 'no-store'},
            {'name': 'X-Content-Type-Options', 'value': 'nosniff'}], 'body': base64.b64encode(body).decode()},
                    page=True, wait=False)
        self.served += 1

    def _block(self, rid: str, url: str) -> None:
        parts = urlsplit(url)
        self.blocked.append(f'{parts.scheme}://{parts.netloc}{parts.path}'[:200])
        self.s.send('Fetch.failRequest', {'requestId': rid, 'errorReason': 'BlockedByClient'}, page=True, wait=False)

    def _dist_file(self, path: str) -> Path | None:
        rel = unquote(path).lstrip('/') or 'index.html'
        if '\x00' in rel or rel.startswith(('.', '/')) or '..' in rel.split('/'):
            return None
        target = (self.dist / rel).resolve()
        return target if target.is_relative_to(self.dist) and target.is_file() else None

    def on_request(self, event: dict) -> None:
        p = event['params']
        rid, url, method = p['requestId'], p['request']['url'], p['request']['method']
        parts = urlsplit(url)
        if method != 'GET' or f'{parts.scheme}://{parts.netloc}' != ORIGIN:
            return self._block(rid, url)
        path = parts.path
        try:
            if path == f'/api/presentations/{self.pid}/view':
                if parts.query != f'revision={self.revision}':
                    return self._block(rid, url)
                return self._fulfill(rid, self.view_bytes, 'application/json')
            m = re.fullmatch(r'/api/theme-assets/([0-9a-f]{64})', path)
            if m:
                data, media = assets.read(m.group(1))
                return self._fulfill(rid, data, media)
            m = re.fullmatch(r'/api/brand-assets/([a-z0-9-]+)/([a-z0-9-]+)', path)
            if m:
                if m.group(1) != self.theme_id or m.group(2) not in self.slots:
                    return self._block(rid, url)
                data, media, _ = brand_assets.read(m.group(1), m.group(2))
                return self._fulfill(rid, data, media)
        except ApiError:
            return self._fulfill(rid, b'', 'text/plain', 404)
        if path.startswith('/api/'):
            return self._block(rid, url)
        f = self._dist_file(path)
        if f is None:
            return self._block(rid, url)
        if self.block_fonts and f.suffix in ('.woff', '.woff2', '.ttf'):  # simulação de fontes ausentes (testes)
            return self._fulfill(rid, b'', 'text/plain', 404)
        self._fulfill(rid, f.read_bytes(), _TYPES.get(f.suffix, mimetypes.guess_type(f.name)[0] or 'application/octet-stream'))


def capture(renderer: Renderer, view: dict, *, pdf: bool, timeout: float = 120.0,
            environ: dict | None = None, block_fonts: bool = False) -> Capture:
    pid, revision = str(uuid.UUID(view['presentation']['id'])), int(view['revision']['number'])
    canvas = view['theme']['canvas']
    view_bytes = json.dumps(view, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    exe = browser.discover(environ)
    t0 = time.monotonic()
    timings: dict = {}
    with browser.Session(exe, time.monotonic() + timeout) as s:
        timings['launch_s'] = round(time.monotonic() - t0, 3)
        server = _Server(s, renderer, pid, revision, view_bytes, view['theme']['id'],
                         {a['name'] for a in view['theme'].get('asset_slots', [])}, block_fonts)
        s.handlers['Fetch.requestPaused'] = server.on_request
        s.send('Fetch.enable', {'patterns': [{'urlPattern': '*', 'requestStage': 'Request'}]}, page=True)
        s.send('Page.enable', page=True)
        s.send('Runtime.enable', page=True)
        s.send('Emulation.setDeviceMetricsOverride', {'width': int(canvas['width']), 'height': int(canvas['height']),
                                                      'deviceScaleFactor': 1, 'mobile': False}, page=True)
        s.send('Emulation.setEmulatedMedia', {'media': 'screen'}, page=True)
        s.send('Page.navigate', {'url': f'{ORIGIN}/index.html#/render/{pid}/{revision}'}, page=True)
        state = {'ready': False, 'error': None}

        def poll() -> None:
            # durante a navegação o contexto pode estar sendo trocado: erro transitório = continuar esperando
            try:
                r = s.evaluate("document.documentElement?.dataset?.renderReady === '1' ? 'ready' : "
                               "(document.querySelector?.('[data-testid=render-error]') ? 'error' : 'wait')", timeout=10)
            except ExportError as exc:
                if exc.code == 'export_timeout':
                    raise
                r = 'wait'
            state['ready'] = r == 'ready'
            state['error'] = r == 'error' or None

        s.pump(lambda: bool(state['ready'] or state['error']), timeout=max(5.0, min(60.0, s.remaining())), poll=poll)
        if state['error']:
            raise ExportError('render_failed', 'A rota de renderização não carregou a apresentação', status=500)
        timings['render_s'] = round(time.monotonic() - t0, 3)
        hooks = s.evaluate('window.__afrikaExport ? window.__afrikaExport.version : 0')
        if hooks != LAYOUT_VERSION:
            raise ExportError('renderer_incompatible', 'O build do renderizador não expõe a versão de layout esperada: '
                                                       'refaça o build do frontend.', status=503)
        count = int(s.evaluate('window.__afrikaExport.slides()'))
        if count != len(view['slides']):
            raise ExportError('render_failed', f'Renderização com {count} slides; o documento tem {len(view["slides"])}',
                              status=500)
        layouts = [json.loads(s.evaluate(f'JSON.stringify(window.__afrikaExport.layout({i}))'))
                   for i in range(1, count + 1)]
        overflow = json.loads(s.evaluate('JSON.stringify(window.__afrikaExport.overflow())'))
        faces = s.evaluate('Array.from(document.fonts).map(f => [f.family.replace(/^[\\x22\\x27]|[\\x22\\x27]$/g, ""), '
                           'f.status])') or []
        webfonts = sorted({f for f, st in faces if st == 'loaded'})
        declared = sorted({f for f, _ in faces})
        fonts = _platform_fonts(s)
        rasters = _svg_rasters(s, view, layouts)
        timings['layout_s'] = round(time.monotonic() - t0, 3)
        data = None
        if pdf:
            r = s.send('Page.printToPDF', {'printBackground': True, 'preferCSSPageSize': True, 'marginTop': 0,
                                           'marginBottom': 0, 'marginLeft': 0, 'marginRight': 0, 'scale': 1,
                                           'displayHeaderFooter': False, 'generateTaggedPDF': True,
                                           'transferMode': 'ReturnAsStream'}, page=True, timeout=120)
            data = s.read_stream(r['stream'], MAX_PDF_BYTES)
            timings['pdf_s'] = round(time.monotonic() - t0, 3)
        return Capture(layouts, overflow, fonts, webfonts, data, browser.engine_info(exe, s.version),
                       blocked=server.blocked, timings=timings, declared_fonts=declared, rasters=rasters)


def _svg_rasters(s: browser.Session, view: dict, layouts: list[dict]) -> dict[str, bytes]:
    """Ativos SVG (marca/tema): PNG de reserva capturado da própria renderização (2×), exigido pelo PPTX."""
    import base64
    theme = view['theme']
    media = {f'brand:{k}': v.get('media_type') for k, v in (view.get('brand_assets') or {}).items()}
    media.update({f'image:{i["name"]}': i['asset']['media_type'] for i in theme.get('images', [])})
    height = theme['canvas']['height']
    out: dict[str, bytes] = {}
    for lay in layouts:
        for op in lay['ops']:
            if op['op'] == 'image' and media.get(op['key']) == 'image/svg+xml' and op['key'] not in out:
                b = op['box']
                shot = s.send('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': True, 'clip': {
                    'x': b['x'], 'y': (lay['index'] - 1) * height + b['y'], 'width': b['w'], 'height': b['h'],
                    'scale': 2}}, page=True, timeout=30)
                out[op['key']] = base64.b64decode(shot['data'])
    return out


def _platform_fonts(s: browser.Session) -> dict[int, dict]:
    """Fontes REAIS usadas pelo Chromium em cada elemento de texto exportado (marcado com `data-xid`)."""
    s.send('DOM.enable', page=True)
    s.send('CSS.enable', page=True)
    root = s.send('DOM.getDocument', {'depth': 0}, page=True)['root']['nodeId']
    out: dict[int, dict] = {}
    slots = s.send('DOM.querySelectorAll', {'nodeId': root, 'selector': '[data-render-slide]'}, page=True)['nodeIds']
    for slot in slots:
        attrs = s.send('DOM.getAttributes', {'nodeId': slot}, page=True)['attributes']
        index = int(dict(zip(attrs[::2], attrs[1::2]))['data-render-slide'])
        per: dict[str, list[dict]] = {}
        for node in s.send('DOM.querySelectorAll', {'nodeId': slot, 'selector': '[data-xid]'}, page=True)['nodeIds']:
            a = s.send('DOM.getAttributes', {'nodeId': node}, page=True)['attributes']
            xid = dict(zip(a[::2], a[1::2])).get('data-xid')
            fonts = s.send('CSS.getPlatformFontsForNode', {'nodeId': node}, page=True).get('fonts', [])
            per[str(xid)] = [{'family': f.get('familyName'), 'custom': bool(f.get('isCustomFont')),
                              'glyphs': f.get('glyphCount', 0)} for f in fonts]
        out[index] = per
    return out
