"""F06B.1 — temas visuais versionados (tokens completos), ativos locais de tema e temas diferentes por cliente.
Dados e ativos 100% SINTÉTICOS (PNG/SVG gerados aqui); nenhuma Veracode, nenhum recurso proprietário.
"""
from __future__ import annotations

import copy
import hashlib
import struct
import zlib

import pytest
from sqlalchemy import text

from app import db
from app.presentations import assets, themes
from conftest import error_code
from test_presentations import Env, OP, slide

NEUTRAL_HASH = '4bec90dedf9791f66ffc53594ec74f33a9d34e7a1f26fbd5b33c935c4ae6fd25'


@pytest.fixture(autouse=True)
def asset_dir(tmp_path, monkeypatch):
    d = tmp_path / 'theme-assets'
    monkeypatch.setenv(assets.ASSET_DIR_ENV, str(d))
    return d


def png(width: int = 4, height: int = 2, rgb: tuple[int, int, int] = (18, 94, 104)) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)
    raw = b''.join(b'\x00' + bytes(rgb) * width for _ in range(height))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def theme_def(**over) -> dict:
    d = copy.deepcopy(themes.NEUTRAL_DEMO_V1)
    d['name'] = 'Tema sintético de teste'
    d.update(over)
    return d


def upload(api, data: bytes, status: int = 201) -> dict:
    r = api.post('/api/theme-assets', content=data, headers={'Content-Type': 'application/octet-stream'})
    assert r.status_code == status, r.text
    return r.json()


@pytest.fixture
def env(api) -> Env:
    e = Env(api)
    e.builtin()
    return e


# ---------------------------------------------------------------- tema embutido (compatibilidade F06A)

def test_neutral_theme_is_complete_and_its_version_is_pinned(api):
    t = api.get('/api/presentation-themes/neutral-demo/versions/1').json()
    assert t['provisional'] is True and 'PROVISÓRIO' in t['notice'] and t['origin'] == 'BUILTIN'
    assert t['canvas'] == {'width': 1280, 'height': 720, 'aspect_ratio': '16:9'}
    assert set(themes.REQUIRED_COLORS) <= set(t['colors'])
    for group in ('fonts', 'weights', 'sizes', 'line_heights', 'spacing', 'radii', 'borders', 'layout', 'header',
                  'footer', 'cover', 'closing', 'backgrounds', 'charts'):
        assert t[group], group
    assert t['fonts']['body']['stack'][-1] == 'sans-serif' and t['fonts']['body']['export_family'] == 'Arial'
    # Versão publicada é imutável: qualquer mudança nos tokens exige neutral-demo@2 (e este teste falha).
    assert t['definition_hash'] == NEUTRAL_HASH
    assert t['missing_assets'] == []


def test_f06a_presentation_view_carries_full_theme_and_readable_period(env):
    c = env.client('Cliente Tema Neutro')
    p = env.present(env.approved(c['id'], '2026-09', {'apps.total': 3}))
    v = env.view(p['id'])
    assert v['theme']['id'] == 'neutral-demo' and v['theme']['version'] == 1
    assert v['theme']['layout']['mode'] == 'flow' and v['theme']['charts']['plot_width'] == 1100
    assert slide(v, 'capa')['data']['period_label'] == '01/09/2026 a 30/09/2026'
    assert not [c for c in v['checks'] if c['code'] == 'theme_asset_missing']


# ---------------------------------------------------------------- validação do esquema

@pytest.mark.parametrize('mutate, fragment', [
    (lambda d: d['colors'].pop('series.2'), 'cores obrigatórias ausentes: series.2'),
    (lambda d: d['colors'].update({'accent': 'red'}), 'colors.accent'),
    (lambda d: d.update(header={'accent_color': 'nao-existe'}), 'cor "nao-existe" não definida'),
    (lambda d: d['layout']['body'].update(h=700), 'invade a área reservada ao rodapé'),
    (lambda d: d['layout']['body'].update(w=5000), 'body.w'),
    (lambda d: d['layout']['body'].update(x=900), 'caixa fora do canvas'),
    (lambda d: d['fonts']['body'].update(stack=['Arial']), 'deve terminar com família genérica'),
    (lambda d: d['fonts']['body'].update(stack=['Arial"; } body { x', 'sans-serif']), 'fonts.body.stack.0'),
    (lambda d: d.update(layouts={'nao-existe': {}}), 'layout inexistente no catálogo'),
    (lambda d: d['layout'].update(mode='fixed'), 'obrigatório no modo fixed'),
    (lambda d: d.update(footer={'items': ['custom_text']}), 'footer.custom_text: obrigatório'),
    (lambda d: d.update(extra_field=1), 'extra_field'),
    (lambda d: d.update(sizes={'title': -1}), 'sizes.title'),
])
def test_theme_schema_rejects_incoherent_definitions(api, mutate, fragment):
    d = theme_def()
    mutate(d)
    r = api.post('/api/presentation-themes', json={'key': 'tema-invalido', 'definition': d, 'operator': OP})
    assert r.status_code == 422, r.text
    assert error_code(r) == 'invalid_theme'
    details = ' | '.join(f"{d['field']}: {d['message']}" for d in r.json()['error']['details'])
    assert fragment in details, details


# ---------------------------------------------------------------- temas próprios versionados

def test_custom_theme_versions_are_append_only_and_conflicts_are_explicit(api, db_url):
    v1 = api.post('/api/presentation-themes', json={'key': 'tema-cliente', 'definition': theme_def(), 'operator': OP})
    assert v1.status_code == 201 and v1.json()['version'] == 1 and v1.json()['origin'] == 'CUSTOM'
    dup = api.post('/api/presentation-themes', json={'key': 'tema-cliente', 'definition': theme_def(), 'operator': OP})
    assert dup.status_code == 409 and error_code(dup) == 'theme_exists'
    same = api.post('/api/presentation-themes/tema-cliente/versions',
                    json={'definition': theme_def(), 'operator': OP, 'expected_version': 1})
    assert same.status_code == 409 and error_code(same) == 'theme_unchanged'
    d2 = theme_def()
    d2['colors']['accent'] = '#125e68'
    stale = api.post('/api/presentation-themes/tema-cliente/versions',
                     json={'definition': d2, 'operator': OP, 'expected_version': 2})
    assert stale.status_code == 409 and error_code(stale) == 'theme_conflict'
    v2 = api.post('/api/presentation-themes/tema-cliente/versions',
                  json={'definition': d2, 'operator': OP, 'expected_version': 1})
    assert v2.status_code == 201 and v2.json()['version'] == 2
    assert v2.json()['definition_hash'] != v1.json()['definition_hash']
    assert api.get('/api/presentation-themes/tema-cliente/versions/1').json()['colors']['accent'] == '#2a78d6'
    listed = {t['id']: t for t in api.get('/api/presentation-themes').json()['items']}
    assert listed['tema-cliente']['versions'] == [1, 2] and listed['neutral-demo']['origin'] == 'BUILTIN'
    builtin = api.post('/api/presentation-themes', json={'key': 'neutral-demo', 'definition': theme_def(),
                                                         'operator': OP})
    assert builtin.status_code == 409 and error_code(builtin) == 'builtin_theme_readonly'
    assert api.get('/api/presentation-themes/tema-cliente/versions/9').status_code == 404
    engine = db.make_engine(db_url)
    try:
        for sql in ("UPDATE presentation_themes SET name = 'x'", 'DELETE FROM presentation_themes'):
            with pytest.raises(Exception, match='presentation_themes_append_only'):
                with engine.begin() as conn:
                    conn.execute(text(sql))
        with engine.connect() as conn:
            events = conn.execute(text("SELECT COUNT(*) FROM audit_events WHERE event_type = "
                                       "'theme.version_created'")).scalar()
        assert events == 2
    finally:
        engine.dispose()


def test_each_client_gets_its_own_theme_through_its_template(env):
    """Temas diferentes por cliente: cada dono escolhe um template; cada template aponta para um tema versionado."""
    logo = upload(env.api, png())
    alt = theme_def(canvas={'width': 960, 'height': 720},
                    layout={'mode': 'fixed', 'body': {'x': 48, 'y': 96, 'w': 864, 'h': 528},
                            'header': {'x': 48, 'y': 96, 'w': 864, 'h': 80},
                            'content': {'x': 48, 'y': 184, 'w': 864, 'h': 440},
                            'footer': {'x': 48, 'w': 864, 'bottom': 16, 'reserve': 30}},
                    images=[{'name': 'logo', 'asset': {'asset_id': logo['asset_id'], 'media_type': 'image/png'},
                             'box': {'x': 840, 'y': 24, 'w': 72, 'h': 48}}])
    alt['colors']['accent'] = '#125e68'
    env.call('POST', '/api/presentation-themes', 201, key='tema-alt', definition=alt, operator=OP)
    tmpl = env.call('GET', '/api/presentation-templates/demo-minimo/versions/1')['definition']
    tmpl['theme'] = {'id': 'tema-alt', 'version': 1}
    env.call('POST', '/api/presentation-templates', 201, key='minimo-alt', definition=tmpl, operator=OP)
    a, b = env.client('Cliente Tema A'), env.client('Cliente Tema B')
    env.call('PUT', f"/api/template-selection/client/{a['id']}", template_key='demo-minimo', template_version=1,
             operator=OP)
    env.call('PUT', f"/api/template-selection/client/{b['id']}", template_key='minimo-alt', template_version=1,
             operator=OP)
    va = env.view(env.present(env.approved(a['id'], '2026-09', {'apps.total': 1}), template_key=None)['id'])
    vb = env.view(env.present(env.approved(b['id'], '2026-09', {'apps.total': 2}), template_key=None)['id'])
    assert (va['theme']['id'], va['theme']['canvas']['aspect_ratio']) == ('neutral-demo', '16:9')
    assert (vb['theme']['id'], vb['theme']['canvas']['aspect_ratio']) == ('tema-alt', '4:3')
    assert vb['theme']['layout']['mode'] == 'fixed' and vb['theme']['images'][0]['asset']['asset_id'] == logo['asset_id']
    assert va['theme']['colors']['accent'] != vb['theme']['colors']['accent']
    # template com tema inexistente é recusado
    tmpl['theme'] = {'id': 'tema-alt', 'version': 7}
    r = env.api.post('/api/presentation-templates', json={'key': 'tema-fantasma', 'definition': tmpl, 'operator': OP})
    assert r.status_code == 422 and 'unknown_theme' in r.text


# ---------------------------------------------------------------- ativos locais (logos/fontes)

def test_assets_are_content_addressed_typed_by_signature_and_served_safely(api, asset_dir):
    data = png()
    a = upload(api, data)
    assert a == {'asset_id': hashlib.sha256(data).hexdigest(), 'media_type': 'image/png', 'size_bytes': len(data)}
    assert upload(api, data) == a  # idempotente (mesmo conteúdo, mesmo id)
    assert [p.name for p in asset_dir.iterdir()] == [f"{a['asset_id']}.png"]  # sem nome original
    r = api.get(f"/api/theme-assets/{a['asset_id']}")
    assert r.status_code == 200 and r.content == data and r.headers['content-type'] == 'image/png'
    assert r.headers['x-content-type-options'] == 'nosniff' and 'sandbox' in r.headers['content-security-policy']
    assert api.get('/api/theme-assets/' + '0' * 64).status_code == 404
    assert api.get('/api/theme-assets/../../etc').status_code in (404, 422)
    (asset_dir / f"{a['asset_id']}.png").write_bytes(data + b'adulterado')
    assert api.get(f"/api/theme-assets/{a['asset_id']}").status_code == 409  # não serve arquivo adulterado


@pytest.mark.parametrize('payload, fragment', [
    (b'GIF89a....', 'Tipo de arquivo não aceito'),
    (b'', 'Arquivo vazio'),
    (b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', '<script>'),
    (b'<svg xmlns="http://www.w3.org/2000/svg" onload="x()"></svg>', 'on*'),
    (b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
     b'<image xlink:href="https://exemplo.invalid/a.png"/></svg>', 'Referências externas'),
    (b'<svg xmlns="http://www.w3.org/2000/svg"><rect style="fill:url(https://x.invalid/a)"/></svg>',
     'Referências externas'),
    (b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY a "b">]><svg xmlns="http://www.w3.org/2000/svg"/>', 'DOCTYPE'),
    (b'<svg xmlns="http://www.w3.org/2000/svg"><foreignObject/></svg>', 'foreignobject'),
])
def test_unsafe_or_unknown_assets_are_rejected(api, payload, fragment):
    r = api.post('/api/theme-assets', content=payload)
    assert r.status_code == 422, r.text
    assert error_code(r) == 'invalid_asset' and fragment in r.text


def test_safe_svg_is_accepted_and_oversized_upload_is_refused(api, monkeypatch):
    svg = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><defs><linearGradient id="g"/></defs>'
           b'<rect width="10" height="10" fill="url(#g)"/><use href="#g"/></svg>')
    assert upload(api, svg)['media_type'] == 'image/svg+xml'
    monkeypatch.setattr(assets, 'MAX_ASSET_BYTES', 10)
    r = api.post('/api/theme-assets', content=png())
    assert r.status_code == 413 and error_code(r) == 'asset_too_large'


def test_theme_requires_existing_assets_and_view_warns_when_one_disappears(env, asset_dir):
    missing = {'asset_id': 'a' * 64, 'media_type': 'image/png'}
    r = env.api.post('/api/presentation-themes', json={'key': 'tema-sem-logo', 'operator': OP, 'definition': theme_def(
        images=[{'name': 'logo', 'asset': missing, 'box': {'x': 0, 'y': 0, 'w': 10, 'h': 10}}])})
    assert r.status_code == 422 and error_code(r) == 'theme_asset_missing'
    logo = upload(env.api, png())
    ref = {'asset_id': logo['asset_id'], 'media_type': 'image/png'}
    font_as_logo = env.api.post('/api/presentation-themes', json={'key': 'tema-ruim', 'operator': OP, 'definition':
                                theme_def(fonts={r: {'stack': ['Sintetica', 'sans-serif'], 'asset': ref}
                                                 for r in ('heading', 'body', 'numeric')})})
    assert font_as_logo.status_code == 422 and 'deve ser arquivo de fonte' in font_as_logo.text
    env.call('POST', '/api/presentation-themes', 201, key='tema-logo', operator=OP, definition=theme_def(
        images=[{'name': 'logo', 'asset': ref, 'box': {'x': 0, 'y': 0, 'w': 10, 'h': 10}}]))
    tmpl = env.call('GET', '/api/presentation-templates/demo-minimo/versions/1')['definition']
    tmpl['theme'] = {'id': 'tema-logo', 'version': 1}
    env.call('POST', '/api/presentation-templates', 201, key='minimo-logo', definition=tmpl, operator=OP)
    c = env.client('Cliente Logo')
    p = env.present(env.approved(c['id'], '2026-09', {'apps.total': 1}), template_key='minimo-logo')
    assert not [x for x in env.view(p['id'])['checks'] if x['code'] == 'theme_asset_missing']
    (asset_dir / f"{logo['asset_id']}.png").unlink()  # banco copiado sem os ativos locais
    checks = [x for x in env.view(p['id'])['checks'] if x['code'] == 'theme_asset_missing']
    assert len(checks) == 1 and checks[0]['level'] == 'warning'
    assert env.view(p['id'])['ready'] is True  # aviso visual, não bloqueia dados


def test_downgrade_refuses_to_drop_custom_themes(api, db_url, monkeypatch):
    api.post('/api/presentation-themes', json={'key': 'tema-persistente', 'definition': theme_def(), 'operator': OP})
    monkeypatch.delenv('AFRIKA_ALLOW_DESTRUCTIVE_DOWNGRADE', raising=False)
    with pytest.raises(RuntimeError, match='Downgrade recusado'):
        db.downgrade(db_url, '0005_presentations')
    engine = db.make_engine(db_url)
    try:
        assert db.current_revision(engine) == '0006_themes'
    finally:
        engine.dispose()
