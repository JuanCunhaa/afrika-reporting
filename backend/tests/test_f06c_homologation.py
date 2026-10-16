"""F06C — homologação visual e preparação para exportação: preservação de hashes, semântica de cores configurável
(severidade por nível, variação comprovada por direção declarada), `afrika@2`/`afrika-modelo@2`, seleção flexível de
slots, disponibilidade por slot, ativos locais com fallback neutro e plano de exportação (contrato da F07).
Dados 100% SINTÉTICOS; nenhuma Veracode; nenhum conteúdo do PowerPoint de referência.
"""
from __future__ import annotations

import copy
import hashlib

import pytest

from app.metrics.contracts import Direction
from app.metrics.registry import DESIRED_DIRECTIONS, REGISTRY
from app.presentations import brand_assets, charts, export_plan, templates, themes
from conftest import error_code
from test_afrika_template import AFRIKA_SLOTS, has_forbidden
from test_presentations import OP, Env, sev, slide

SAST, SCA = 'sast.policy.open.by_severity', 'sca.policy.open.by_severity'

# Hashes publicados ANTES da F06C: nenhuma versão existente pode mudar (F06C cria versões novas).
FROZEN_THEMES = {('neutral-demo', 1): '4bec90dedf9791f66ffc53594ec74f33a9d34e7a1f26fbd5b33c935c4ae6fd25',
                 ('afrika', 1): 'f82acd0238eb3962662c1ed42efda4851d362a0144d0a8d591e21e52d61555eb'}
FROZEN_TEMPLATES = {('demo-executivo', 1): '879a8774cb56de398167ec4f387d22a9081cf7b856cdcbaaa0dbf943214cf420',
                    ('demo-tecnico', 1): '95c54d392e264a8538b9d0951b49696694fbc57bbaa81deac3fb279b7a619d54',
                    ('demo-minimo', 1): 'f7ed3c6b4955e02c3877a1cad5e6e4c622e818b79ece0ebf3d0c09f4466c2318',
                    ('afrika-modelo', 1): 'f30458dbd9a5b8141f59fc469bed74791e9f6bfe16d05d81fb60178e52ddc9cc'}
PNG_1PX = bytes.fromhex('89504e470d0a1a0a0000000d4948445200000001000000010806000000'
                        '1f15c4890000000d49444154789c6360f8cfc0000003010100c9fe92ef0000000049454e44ae426082')


def values(i: int = 0) -> dict:
    """Setembro: SAST cai (melhora), SCA sobe (piora), apps.total muda (direção neutra)."""
    return {'apps.total': 140 + i, 'apps.without_team': 7, SAST: sev(2, 7, 23 - 3 * i, 9, 3, 1, 1),
            SCA: sev(1, 4, 11 + 2 * i, 5, 2, 1, 0), 'sast.open.distinct': sev(2, 7, 18, 11, 3, 1, 0)}


@pytest.fixture
def env(api) -> Env:
    e = Env(api)
    e.builtin()
    return e


def presentation(env: Env, owner_id: str, version: int = 2, slots: list[str] | None = None, kind: str = 'client'):
    env.approved(owner_id, '2026-08', values(0), kind)
    cid = env.competence(owner_id, '2026-09', kind)
    env.fill(cid, 1, values(1))
    env.approve(cid, 1, ['apps.total'])
    p = env.present(cid, template_key='afrika-modelo', template_version=version, slots=slots)
    return cid, p, env.view(p['id'])


# ---------------------------------------------------------------- preservação

def test_existing_theme_and_template_versions_keep_their_hashes(env):
    for key, h in FROZEN_THEMES.items():
        assert themes.definition_hash(themes._BUILTIN_PARSED[key]) == h, key
        assert themes.resolve(None, *key)['definition_hash'] == h
    items = {t['key']: t for t in env.call('GET', '/api/presentation-templates')['items']}
    for (key, version), h in FROZEN_TEMPLATES.items():
        assert templates.definition_hash(templates.parse_definition(templates.BUILTIN[(key, version)])) == h, key
        assert env.call('GET', f'/api/presentation-templates/{key}/versions/{version}')['definition_hash'] == h
    assert items['afrika-modelo']['versions'] == [1, 2]
    # temas antigos: sem semântica e sem encaixes (visual F06B inalterado), paleta efetiva = declarada (+ neutras)
    for key in FROZEN_THEMES:
        t = themes.resolve(None, *key)
        assert t['semantics'] == {'severity': None, 'variation': None} and t['asset_slots'] == []
        assert {k: v for k, v in t['colors'].items() if not k.startswith('variation.')} == t['declared_colors']
        assert t['components']['donut_separator'] == 0 and t['components']['subtitle_color'] is None
        assert t['components']['matrix_label_size'] is None


def test_afrika_v2_reuses_v1_layouts_and_only_adds_po_semantics():
    v1, v2 = themes.resolve(None, 'afrika', 1), themes.resolve(None, 'afrika', 2)
    changed = {'id', 'version', 'definition_hash', 'description', 'notice', 'colors', 'declared_colors',
               'semantics', 'asset_slots', 'components'}
    assert {k: v for k, v in v1.items() if k not in changed} == {k: v for k, v in v2.items() if k not in changed}
    assert {**v1['components'], 'donut_separator': 3, 'subtitle_color': 'brand.deep', 'subtitle_font': 'heading',
            'subtitle_weight': 900, 'subtitle_line_height': 1.5, 'matrix_label_size': themes._pt(22)} == v2['components']
    assert v2['provisional'] is True and not has_forbidden(v2)
    pal = v2['colors']
    assert (pal['severity.VERY_HIGH'], pal['severity.HIGH'], pal['severity.MEDIUM'], pal['severity.LOW'],
            pal['severity.INFORMATIONAL']) == ('#C00000', '#F26B1D', '#FFC000', '#2F6FD6', '#8C8C8C')
    assert pal['severity.VERY_LOW'] == pal['severity.LOW']  # "Muito baixa" agrupada em Baixa (pendência do PO)
    assert (pal['variation.improvement'], pal['variation.worsening']) == ('#2E9E5B', '#C00000')
    assert not [k for k in v2['declared_colors'] if k.startswith('severity.')]  # fonte única: o nível semântico
    t1 = templates.BUILTIN[('afrika-modelo', 1)]
    t2 = templates.BUILTIN[('afrika-modelo', 2)]
    assert t2['slides'] == t1['slides'] and [s['slot_id'] for s in t2['slides']] == AFRIKA_SLOTS
    assert t2['theme'] == {'id': 'afrika', 'version': 2} and t1['theme'] == {'id': 'afrika', 'version': 1}
    assert {s['slot_id'] for s in t2['slides'] if s.get('required')} == {'capa', 'encerramento'}


@pytest.mark.parametrize('mutate, fragment', [
    (lambda d: d['colors'].update({'severity.HIGH': '#000000'}), 'são derivados'),
    (lambda d: d['semantics']['severity']['levels'].pop('medium'), 'medium'),
    (lambda d: d['semantics']['severity']['mapping'].pop('VERY_LOW'), 'VERY_LOW'),
    (lambda d: d['semantics']['severity']['levels'].update(low='nao.existe'), 'não definida em colors'),
    (lambda d: d['semantics']['variation'].update(improvement='nao.existe'), 'semantics.variation.improvement'),
    (lambda d: d['asset_slots'].append({**d['asset_slots'][0]}), 'asset_slots: nomes repetidos'),
    (lambda d: d['asset_slots'][0].update(box={'x': 1900, 'y': 0, 'w': 100, 'h': 10}), 'caixa fora do canvas'),
    (lambda d: d['asset_slots'][0].update(name='../fora'), 'asset_slots'),
])
def test_semantics_and_asset_slots_are_validated(api, mutate, fragment):
    d = copy.deepcopy(themes.AFRIKA_V2)
    mutate(d)
    r = api.post('/api/presentation-themes', json={'key': 'tema-semantico', 'definition': d, 'operator': OP})
    assert r.status_code == 422 and error_code(r) == 'invalid_theme', r.text
    assert fragment in r.text


def test_severity_semantics_is_configurable_in_a_custom_theme(api):
    d = copy.deepcopy(themes.AFRIKA_V2)
    d['name'] = 'Tema próprio sintético'
    d['colors']['status.verylow'] = '#9DB9EA'
    d['semantics']['severity']['levels']['low'] = 'status.verylow'  # reconfigura um nível
    d['semantics']['severity']['mapping']['MEDIUM'] = 'high'         # reconfigura um mapeamento
    r = api.post('/api/presentation-themes', json={'key': 'tema-proprio', 'definition': d, 'operator': OP})
    assert r.status_code == 201, r.text
    pal = r.json()['colors']
    assert pal['severity.LOW'] == '#9DB9EA' and pal['severity.MEDIUM'] == pal['severity.HIGH'] == '#F26B1D'


# ---------------------------------------------------------------- direção desejável e tendência comprovada

def test_only_open_backlog_declares_direction_and_contract_versions_do_not_change():
    declared = {m for m, c in REGISTRY.items() if c.desired_direction is not Direction.NEUTRAL}
    assert declared == set(DESIRED_DIRECTIONS) == {
        'sast.policy.open.by_severity', 'sast.sandbox.open.by_severity', 'sast.sandbox.open.distinct',
        'sast.open.distinct', 'sca.policy.open.by_severity', 'sca.sandbox.open.by_severity', 'sca.open.distinct'}
    assert all(REGISTRY[m].desired_direction is Direction.LOWER_IS_BETTER and REGISTRY[m].direction_rationale
               for m in declared)
    for neutral in ('apps.total', 'apps.loc.total', 'sast.policy.new_in_period.by_severity', 'apps.without_team'):
        assert REGISTRY[neutral].desired_direction is Direction.NEUTRAL
    assert all(c.version == 1 for c in REGISTRY.values())  # metadado de apresentação: versão inalterada


@pytest.mark.parametrize('metric, delta, reason, expected', [
    (SAST, -3, None, ('improvement', None)),
    (SAST, 2, None, ('worsening', None)),
    (SAST, 0, None, ('unchanged', None)),
    (SAST, None, 'gap', ('unknown', 'gap')),
    ('apps.total', 5, None, ('unknown', 'direction_not_declared')),
    ('apps.total', -5, None, ('unknown', 'direction_not_declared')),
    ('inexistente', 1, None, ('unknown', 'direction_not_declared')),
])
def test_trend_is_only_colored_when_proven_and_direction_declared(metric, delta, reason, expected):
    t = charts.trend(metric, delta, reason)
    assert (t['trend'], t['trend_reason']) == expected
    assert t['trend_color'] == {'improvement': 'variation.improvement', 'worsening': 'variation.worsening'}.get(
        expected[0], 'variation.neutral')


def test_view_comparisons_carry_proven_trend_and_gaps_stay_unknown(env):
    c = env.client('Cliente Semântica Sintético')
    _, _, v = presentation(env, c['id'])
    assert v['theme']['version'] == 2 and v['theme']['semantics']['variation']['improvement'] == 'trend.improvement'
    rows = {r['metric_id']: r for r in slide(v, 'painel-severidades')['data']['zones']['detail']['data']['rows']}
    assert (rows[SAST]['delta'], rows[SAST]['trend']) == (-3, 'improvement')
    assert (rows[SCA]['delta'], rows[SCA]['trend']) == (2, 'worsening')
    detail = {r['metric_id']: r for r in slide(v, 'painel-graficos')['data']['zones']['detail']['data']['rows']}
    assert detail['apps.total']['delta'] == 1 and detail['apps.total']['trend'] == 'unknown'
    assert detail['apps.total']['trend_reason'] == 'direction_not_declared'
    # sem competência anterior aprovada: variação indisponível => tendência desconhecida (neutra), nunca inventada
    c2 = env.client('Cliente Sem Histórico Sintético')
    cid = env.competence(c2['id'], '2026-09')
    env.fill(cid, 1, values(1))
    env.approve(cid, 1, ['apps.total'])
    v2 = env.view(env.present(cid, template_key='afrika-modelo', template_version=2)['id'])
    r = next(x for x in slide(v2, 'painel-severidades')['data']['zones']['detail']['data']['rows']
             if x['metric_id'] == SAST)
    assert r['delta'] is None and (r['trend'], r['trend_reason']) == ('unknown', 'gap')


def test_presentations_on_v1_keep_their_theme_and_render_neutral(env):
    c = env.client('Cliente Versão Antiga Sintético')
    _, p, v = presentation(env, c['id'], version=1)
    assert v['theme']['id'] == 'afrika' and v['theme']['version'] == 1
    assert v['theme']['semantics'] == {'severity': None, 'variation': None} and v['brand_assets'] == {}
    assert v['template']['definition_hash'] == FROZEN_TEMPLATES[('afrika-modelo', 1)]
    assert env.call('GET', f'/api/presentations/{p["id"]}/integrity')['ok'] is True


# ---------------------------------------------------------------- seleção flexível e disponibilidade

def test_slots_can_be_selected_at_creation_and_required_ones_are_always_kept(env, api):
    c = env.client('Cliente Seleção Sintético')
    comp, p, v = presentation(env, c['id'], slots=['painel-kpis', 'painel-severidades'])
    assert [s['template_slot'] for s in v['slides']] == ['capa', 'painel-kpis', 'painel-severidades', 'encerramento']
    events = api.get(f'/api/competences/{comp}/audit').json()['items']
    ev = next(e for e in events if e['event_type'] == 'presentation.created'
              and e['details']['presentation_id'] == p['id'])
    assert ev['details']['required_added'] == ['capa', 'encerramento']
    assert ev['details']['selected_slots'] == ['capa', 'painel-kpis', 'painel-severidades', 'encerramento']
    # só capa + encerramento: apresentação mínima válida (não precisa de 16 slides)
    sub = env.subclient(c['id'], 'Subcliente Seleção Sintético')
    _, _, v2 = presentation(env, sub['id'], slots=[], kind='subclient')
    assert [s['template_slot'] for s in v2['slides']] == ['capa', 'encerramento']
    cid = env.competence(c['id'], '2026-07')
    env.fill(cid, 1, values(1))
    env.approve(cid, 1, ['apps.total'])
    r = env.present(cid, 422, template_key='afrika-modelo', template_version=2, slots=['nao-existe'])
    assert r['error']['details'][0]['type'] == 'unknown_slot'


def test_slot_availability_reports_states_without_writing(env, api):
    c = env.client('Cliente Disponibilidade Sintético')
    cid, p, _ = presentation(env, c['id'])
    before = env.call('GET', f'/api/presentations/{p["id"]}')['current_revision']
    a = env.call('GET', f'/api/presentation-templates/afrika-modelo/versions/2/availability?competence_id={cid}')
    by = {s['slot_id']: s for s in a['slots']}
    assert [s['slot_id'] for s in a['slots']] == AFRIKA_SLOTS
    assert by['capa']['status'] == 'editorial' and by['capa']['required'] and by['capa']['suggested']
    assert by['painel-severidades']['status'] == 'complete'
    assert by['painel-kpis']['status'] == 'partial'  # apps.unclassified etc. sem valor
    assert by['ranking-componentes']['status'] == 'none' and by['ranking-componentes']['suggested'] is False
    missing = {m['metric_id']: m['state'] for m in by['painel-kpis']['metrics']}
    assert missing['apps.unclassified'] == 'MISSING' and missing['apps.total'] == 'VALUE'
    assert env.call('GET', f'/api/presentations/{p["id"]}')['current_revision'] == before
    pending = env.competence(c['id'], '2026-06')
    r = api.get(f'/api/presentation-templates/afrika-modelo/versions/2/availability?competence_id={pending}')
    assert r.status_code == 409 and error_code(r) == 'no_approved_revision'


# ---------------------------------------------------------------- ativos locais (pasta fora do Git)

def test_brand_assets_fall_back_to_neutral_when_absent(env, tmp_path, monkeypatch):
    monkeypatch.setenv(brand_assets.BRAND_DIR_ENV, str(tmp_path))
    c = env.client('Cliente Sem Ativos Sintético')
    _, p, v = presentation(env, c['id'])
    assert set(v['brand_assets']) == {s['name'] for s in themes.AFRIKA_V2['asset_slots']}
    assert all(b['status'] == 'missing' and 'url' not in b for b in v['brand_assets'].values())
    info = [x for x in v['checks'] if x['code'] == 'brand_asset_missing']
    assert len(info) == 1 and info[0]['level'] == 'info'  # informativo: não bloqueia nem vira aviso
    assert not [x for x in v['checks'] if x['code'].startswith('brand_asset') and x['level'] != 'info']
    assert env.api.get('/api/brand-assets/afrika/logo-capa').status_code == 404


def test_brand_assets_are_loaded_validated_and_served_safely(env, tmp_path, monkeypatch):
    monkeypatch.setenv(brand_assets.BRAND_DIR_ENV, str(tmp_path))
    folder = tmp_path / 'afrika'
    folder.mkdir()
    (folder / 'foto-capa.png').write_bytes(PNG_1PX)
    (folder / 'logo-capa.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>x()</script></svg>')
    (folder / 'logo-conteudo.png').write_text('não é imagem')
    c = env.client('Cliente Com Ativos Sintético')
    _, p, v = presentation(env, c['id'])
    b = v['brand_assets']
    assert b['foto-capa']['status'] == 'available' and b['foto-capa']['media_type'] == 'image/png'
    assert b['foto-capa']['sha256'] == hashlib.sha256(PNG_1PX).hexdigest()
    assert b['foto-capa']['url'].startswith('/api/brand-assets/afrika/foto-capa?v=')
    assert b['logo-capa']['status'] == 'invalid' and b['logo-conteudo']['status'] == 'invalid'
    warns = {x['message'].split('"')[1] for x in v['checks'] if x['code'] == 'brand_asset_invalid'}
    assert warns == {'logo-capa', 'logo-conteudo'}
    r = env.api.get(b['foto-capa']['url'])
    assert r.status_code == 200 and r.content == PNG_1PX and r.headers['content-type'] == 'image/png'
    assert r.headers['x-content-type-options'] == 'nosniff' and 'sandbox' in r.headers['content-security-policy']
    assert env.api.get('/api/brand-assets/afrika/logo-capa').status_code == 404  # inválido nunca é servido
    for bad in ('..%2Fafrika%2Ffoto-capa', 'FOTO', 'foto-capa.png'):
        assert env.api.get(f'/api/brand-assets/afrika/{bad}').status_code == 404
    assert env.api.get('/api/brand-assets/..%2F..%2Fsecret/foto-capa').status_code == 404


# ---------------------------------------------------------------- plano de exportação (preparação da F07)

def test_export_plan_maps_every_element_to_editable_kinds_and_keeps_gaps(env):
    c = env.client('Cliente Exportação Sintético')
    _, p, v = presentation(env, c['id'])
    plan = env.call('GET', f'/api/presentations/{p["id"]}/export-plan')
    assert plan['status'] == 'CONTRACT_ONLY' and plan['export_plan_version'] == export_plan.PLAN_VERSION
    assert [s['slide_id'] for s in plan['slides']] == [s['slide_id'] for s in v['slides']]
    assert plan['canvas'] == {'width_px': 1920, 'height_px': 1080, 'width_emu': 18288000, 'height_emu': 10287000,
                              'emu_per_px': 9525}
    elements = [e for s in plan['slides'] for e in s['elements']]
    assert {e['export_as'] for e in elements} <= set(export_plan.EXPORT_KINDS)
    assert all(e['component'] in export_plan.MATRIX for e in elements)
    assert all(s['data_as_image'] == [] for s in plan['slides'])
    assert plan['totals']['image'] == 0  # sem ativos locais: nenhuma imagem
    charts_ = {e['chart']['type'] for e in elements if e['export_as'] == 'native_chart'}
    assert {'combo', 'doughnut', 'bar'} <= charts_
    combo = next(e for e in elements if e['component'] == 'combo_chart')['chart']
    assert [s['render'] for s in combo['series']] == ['bar', 'line'] and combo['blanks_as'] == 'gap'
    gaps = [(val, st) for s in combo['series'] for val, st in zip(s['values'], s['states']) if st != 'VALUE']
    assert gaps and all(val is None for val, _ in gaps)  # lacuna nunca vira 0
    donut = next(e for e in elements if e['component'] == 'donut')['chart']
    assert donut['series'][0]['point_colors'][0] == 'severity.VERY_HIGH'
    kpis = [e for e in elements if e['component'] == 'kpi' and e['state'] != 'VALUE']
    assert all(e['value'] is None for e in kpis)
    pills = [e for e in elements if e['component'] == 'variation_pill']
    assert {e['trend'] for e in pills} >= {'improvement', 'unknown'}
    assert any(e['component'] == 'matrix' and e['export_as'] == 'table' for e in elements)
    assert any(e['component'] == 'section_title' and e['vertical'] for e in elements)
    assert any(e['component'] == 'theme_shape' and e['custom_geometry'] for e in elements)
    assert set(plan['palette']) >= {'severity.VERY_HIGH', 'variation.improvement'}


def test_export_plan_uses_image_only_for_authorized_brand_assets(env, tmp_path, monkeypatch):
    monkeypatch.setenv(brand_assets.BRAND_DIR_ENV, str(tmp_path))
    (tmp_path / 'afrika').mkdir()
    (tmp_path / 'afrika' / 'logo-conteudo.png').write_bytes(PNG_1PX)
    c = env.client('Cliente Exportação Ativos Sintético')
    _, p, v = presentation(env, c['id'], slots=['painel-kpis'])
    plan = env.call('GET', f'/api/presentations/{p["id"]}/export-plan')
    images = [(s['slide_id'], e['component']) for s in plan['slides'] for e in s['elements']
              if e['export_as'] == 'image']
    assert images == [('painel-kpis', 'brand_asset')]  # só no slide de conteúdo, só o ativo autorizado
    capa = next(s for s in plan['slides'] if s['slide_id'] == 'capa')
    assert {'logo-capa', 'foto-capa'} <= set(capa['brand_fallbacks'])
