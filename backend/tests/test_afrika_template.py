"""F06B — template de referência Afrika: tema `afrika@1`, template `afrika-modelo@1`, slides de seção e painel
composto (zonas). Dados 100% SINTÉTICOS; nenhum conteúdo do PowerPoint de referência (que não está no repositório).
"""
from __future__ import annotations

import copy
import hashlib
import json
import re

import pytest

from app.presentations import catalog, templates, themes
from conftest import error_code
from test_presentations import OP, Env, approved_numbers, numbers, sev, slide

# hashes dos templates F06A: o esquema evoluiu (zonas) sem alterar a serialização dos templates antigos
OLD_TEMPLATE_HASHES = {
    'demo-executivo': '879a8774cb56de398167ec4f387d22a9081cf7b856cdcbaaa0dbf943214cf420',
    'demo-tecnico': '95c54d392e264a8538b9d0951b49696694fbc57bbaa81deac3fb279b7a619d54',
    'demo-minimo': 'f7ed3c6b4955e02c3877a1cad5e6e4c622e818b79ece0ebf3d0c09f4466c2318',
}
AFRIKA_SLOTS = ['capa', 'secao-abertura', 'secao-indicadores', 'secao-detalhes', 'painel-kpis', 'painel-graficos',
                'painel-grupos', 'painel-severidades', 'painel-severidades-dev', 'ranking-aplicacoes',
                'ranking-componentes', 'destaque-vulnerabilidades', 'secao-plano', 'matriz-acoes',
                'matriz-acompanhamento', 'encerramento']
# Termos do cliente/unidade da referência que NÃO podem aparecer no template/tema (o produto é genérico). Guardados só
# como SHA-256 (palavra ou bigrama em minúsculas) para o próprio teste não publicar o nome.
FORBIDDEN_SHA256 = {'50d1e8ab28a0dd129a37e232c47357e20e97bada6fed3737ffa4ddb18dd1f1c3',
                    'e5cb822160e3aca3301207f8169ff47835ba65e228977637412b525e7f21222d'}


def has_forbidden(obj) -> bool:
    words = re.findall(r'[a-z0-9]+', json.dumps(obj, ensure_ascii=False).lower())
    grams = words + [f'{a} {b}' for a, b in zip(words, words[1:])]
    return any(hashlib.sha256(g.encode()).hexdigest() in FORBIDDEN_SHA256 for g in grams)
SAST, SCA = 'sast.policy.open.by_severity', 'sca.policy.open.by_severity'


def afrika_values(i: int = 0) -> dict:
    return {'apps.total': 140 + i, 'apps.without_team': 7, 'apps.multiple_teams': 3,
            SAST: sev(2, 7, 23 + i, 9, 3, 1, 1), SCA: sev(1, 4, 11, 5, 2, 1, 0),
            'sast.policy.new_in_period.by_severity': sev(0, 1, 4 + i, 2, 1, 0, 0)}


@pytest.fixture
def env(api) -> Env:
    e = Env(api)
    e.builtin()
    return e


def afrika_presentation(env: Env, owner_id: str, kind: str = 'client') -> tuple[dict, dict]:
    env.approved(owner_id, '2026-08', afrika_values(-1), kind)
    cid = env.competence(owner_id, '2026-09', kind)
    env.fill(cid, 1, afrika_values())
    env.approve(cid, 1, ['apps.total'])
    p = env.present(cid, template_key='afrika-modelo')
    return p, env.view(p['id'])


# ---------------------------------------------------------------- tema e template

def test_afrika_theme_is_builtin_complete_provisional_and_does_not_touch_neutral(api):
    neutral = themes.resolve(None, 'neutral-demo', 1)
    afrika = themes.resolve(None, 'afrika', 1)
    assert neutral['definition_hash'] == '4bec90dedf9791f66ffc53594ec74f33a9d34e7a1f26fbd5b33c935c4ae6fd25'
    assert afrika['definition_hash'] != neutral['definition_hash']
    d = afrika
    assert d['provisional'] is True  # identidade ainda não homologada pelo PO
    assert d['layout']['mode'] == 'fixed' and (d['canvas']['width'], d['canvas']['height']) == (1920, 1080)
    assert d['fonts']['heading']['stack'][0] == 'Montserrat' and d['fonts']['body']['stack'][0] == 'Poppins'
    assert set(d['components']['dashboards']) <= set(catalog.DASHBOARD_LAYOUTS)
    shapes = {s['name']: s for s in d['components']['shapes']}
    assert shapes['painel-capa']['opacity'] == 0.95 and shapes['painel-capa']['path'].startswith('M0 0')
    assert shapes['painel-encerramento']['path'].endswith('Z')
    assert not has_forbidden(d)
    # catálogo de temas lista os dois embutidos
    items = {t['id'] for t in api.get('/api/presentation-themes').json()['items']}
    assert {'neutral-demo', 'afrika'} <= items


@pytest.mark.parametrize('mutate, fragment', [
    (lambda c: c['zone_frames'].update({'inexistente': {'band': 'card'}}), 'layout de painel inexistente'),
    (lambda c: c['zone_frames'].update({'painel-kpis': {'nao-ha': 'card'}}), 'zona inexistente'),
    (lambda c: c['header_valign_by_layout'].update({'inexistente': 'top'}), 'layout inexistente'),
    (lambda c: c.update(comparison_fill='nao.existe'), 'não definida em colors'),
    (lambda c: c['shapes'][0].update(path='M0 0 <script>'), 'shapes'),
    (lambda c: c['shapes'][0].update(opacity=0), 'opacity'),
    (lambda c: c['dashboards'].update({'painel-kpis': {'fantasma': {'x': 0, 'y': 0, 'w': 1, 'h': 1}}}),
     'fantasma'),
])
def test_afrika_component_tokens_are_validated(api, mutate, fragment):
    d = copy.deepcopy(themes.AFRIKA_V1)
    mutate(d['components'])
    d['name'] = 'Tema inválido sintético'
    r = api.post('/api/presentation-themes', json={'key': 'tema-invalido', 'definition': d, 'operator': OP})
    assert r.status_code == 422 and error_code(r) == 'invalid_theme', r.text
    assert fragment in r.text


def test_afrika_template_is_generic_versioned_and_old_templates_keep_their_hashes(env):
    items = {t['key']: t for t in env.call('GET', '/api/presentation-templates')['items']}
    for key, h in OLD_TEMPLATE_HASHES.items():
        assert items[key]['definition_hash'] == h, key
    t = env.call('GET', '/api/presentation-templates/afrika-modelo/versions/1')
    assert t['theme'] == {'id': 'afrika', 'version': 1} and t['origin'] == 'BUILTIN'
    d = t['definition']
    assert [s['slot_id'] for s in d['slides']] == AFRIKA_SLOTS
    assert [s['type'] for s in d['slides']].count('dashboard') == 8
    assert [s['type'] for s in d['slides']].count('section') == 4
    assert {s['slot_id'] for s in d['slides'] if s.get('required')} == {'capa', 'encerramento'}
    assert not has_forbidden(d)
    assert not {'value', 'values', 'number', 'headline'} & {k for s in d['slides'] for k in s.get('fields', {})}
    for s in d['slides']:  # toda zona do template é válida no catálogo
        for zid, z in s.get('zones', {}).items():
            spec = catalog.DASHBOARD_LAYOUTS[s['layout']][zid]
            assert all(catalog.zone_compatible(spec, m, z.get('chart') or (spec.charts[0] if spec.charts else None),
                                               z.get('data_mode')) for m in z.get('metrics', [])), (s['slot_id'], zid)
    # documento de um template antigo continua sem a chave nova (hash de documento inalterado)
    c = env.client('Cliente Retrocompatível')
    doc = env.document(env.present(env.approved(c['id'], '2026-09', {'apps.total': 5}))['id'])
    assert all('zones' not in s for s in doc['slides'])


def test_catalog_exposes_section_and_dashboard_with_zone_specs(env):
    cat = env.call('GET', '/api/presentation-catalog')
    types = {t['type']: t for t in cat['slide_types']}
    assert 'section' in types and 'dashboard' in types
    dash = types['dashboard']
    assert set(dash['layouts']) == set(catalog.DASHBOARD_LAYOUTS)
    assert [z['zone'] for z in dash['zones']['painel-severidades']] == ['group_a', 'group_b', 'detail', 'list']
    z = next(z for z in dash['zones']['painel-graficos'] if z['zone'] == 'chart')
    assert z['kind'] == 'chart' and z['charts'] == ['combo', 'bar', 'line'] and z['max_metrics'] == 2
    assert 'matrix' in types['recommendations']['layouts']
    assert {'kpi-band'} <= set(types['kpis']['layouts'])
    assert {'severity-cards', 'donut'} <= set(types['severity_distribution']['layouts'])


# ---------------------------------------------------------------- apresentação (qualquer cliente/subcliente)

def test_afrika_presentation_works_for_client_without_subclients_and_for_subclient(env):
    plain = env.client('Cliente Sem Subclientes Sintético')
    p1, v1 = afrika_presentation(env, plain['id'])
    assert [s['template_slot'] for s in v1['slides']] == AFRIKA_SLOTS
    assert v1['theme']['id'] == 'afrika'
    parent = env.client('Cliente Com Subclientes Sintético')
    sub = env.subclient(parent['id'], 'Subcliente Sintético A')
    p2, v2 = afrika_presentation(env, sub['id'], 'subclient')
    assert [s['template_slot'] for s in v2['slides']] == AFRIKA_SLOTS
    assert slide(v2, 'capa')['data']['owner'] == 'Subcliente Sintético A'
    assert slide(v2, 'secao-abertura')['data'] == {'kind': 'section', 'owner': 'Subcliente Sintético A',
                                                   'competence': '2026-09'}


def test_dashboard_zones_show_only_approved_values_and_explicit_gaps(env):
    c = env.client('Cliente Painel Sintético')
    _, v = afrika_presentation(env, c['id'])
    kp = slide(v, 'painel-kpis')['data']
    assert kp['kind'] == 'dashboard' and list(kp['zones']) == ['band', 'cards', 'table', 'text']
    band = kp['zones']['band']['data']['items']
    assert [(k['metric_id'], k['y']) for k in band] == [('apps.total', 140), (SAST, 46), (SCA, 24)]
    cards = {r['metric_id']: r for r in kp['zones']['cards']['data']['rows']}
    assert cards['apps.without_team']['current']['y'] == 7 and cards['apps.without_team']['delta'] == 0
    # apps.unclassified não foi preenchido: MISSING explícito, nunca zero inventado
    assert cards['apps.unclassified']['current']['state'] == 'MISSING'
    assert cards['apps.unclassified']['current']['y'] is None and cards['apps.unclassified']['delta'] is None
    issues = {(i['code'], i['metric_id']): i['level'] for i in slide(v, 'painel-kpis')['issues']}
    assert issues[('metric_missing', 'apps.unclassified')] == 'blocker'  # slot com required_metrics
    sev_zone = slide(v, 'painel-severidades')['data']['zones']['group_a']['data']
    assert [p['y'] for p in sev_zone['series'][0]['points']] == [2, 7, 23, 9, 3, 1, 1]
    assert sev_zone['total']['y'] == 46
    detail = slide(v, 'painel-severidades')['data']['zones']['detail']['data']['rows']
    assert [(r['metric_id'], r['previous']['y'], r['current']['y'], r['delta']) for r in detail] == [
        (SAST, 45, 46, 1), (SCA, 24, 24, 0)]
    chart = slide(v, 'painel-graficos')['data']['zones']['chart']['data']
    assert chart['kind'] == 'combo' and len(chart['series']) == 2 and len(chart['series'][0]['points']) == 6
    assert sum(1 for p in chart['series'][0]['points'] if p['y'] is None) == 4  # lacunas, sem interpolação
    # ranking sem valor aprovado: indisponível com motivo (nada inventado)
    rank = slide(v, 'ranking-aplicacoes')['data']['zones']['table']['data']
    assert rank['available'] is False
    allowed = approved_numbers(afrika_values()) | approved_numbers(afrika_values(-1)) | {0, 1}
    for s in v['slides']:
        assert set(numbers(s['data'])) <= allowed, s['template_slot']


def test_zones_are_editable_and_validated(env):
    c = env.client('Cliente Edição de Zonas Sintético')
    p, _ = afrika_presentation(env, c['id'])
    doc = env.document(p['id'])
    i = next(n for n, s in enumerate(doc['slides']) if s['template_slot'] == 'painel-graficos')
    ok = copy.deepcopy(doc)
    ok['slides'][i]['zones']['chart'].update(chart='line', metrics=['apps.total'], months=12,
                                             title='Aplicações — 12 meses')
    ok['slides'][i]['fields']['title'] = 'Título editado'
    env.save(p['id'], ok, 1)
    v = env.view(p['id'])
    z = slide(v, 'painel-graficos')['data']['zones']['chart']
    assert z['title'] == 'Aplicações — 12 meses' and z['data']['kind'] == 'line'
    assert len(z['data']['series'][0]['points']) == 12
    assert slide(v, 'painel-graficos')['fields']['title'] == 'Título editado'

    def bad(mut) -> str:
        d = copy.deepcopy(env.document(p['id']))
        mut(d['slides'][i])
        return env.save(p['id'], d, 2, 422)['error']['details'][0]['type']

    assert bad(lambda s: s['zones'].update(fantasma={'metrics': ['apps.total']})) == 'unknown_zone'
    assert bad(lambda s: s['zones']['donut_a'].update(metrics=['apps.total'])) == 'incompatible_metric'
    assert bad(lambda s: s['zones']['band'].update(metrics=['apps.total'] * 2)) == 'duplicate_metric'
    assert bad(lambda s: s['zones']['band'].update(metrics=['apps.total', SAST, SCA, 'apps.without_team']))\
        == 'metric_count'
    assert bad(lambda s: s['zones']['detail'].update(top_n=3)) == 'option_not_applicable'
    assert bad(lambda s: s['zones']['chart'].update(chart='donut')) in ('option_not_applicable', 'literal_error')
    # slot com required_metrics não perde indicadores do template
    k = next(n for n, s in enumerate(env.document(p['id'])['slides']) if s['template_slot'] == 'painel-kpis')
    d = copy.deepcopy(env.document(p['id']))
    d['slides'][k]['zones']['band']['metrics'] = ['apps.total']
    assert env.save(p['id'], d, 2, 422)['error']['details'][0]['type'] == 'required_metric_removed'


def test_zones_are_rejected_outside_dashboard_and_section_has_no_metrics(env):
    c = env.client('Cliente Seção Sintético')
    p, _ = afrika_presentation(env, c['id'])
    doc = env.document(p['id'])
    j = next(n for n, s in enumerate(doc['slides']) if s['template_slot'] == 'matriz-acoes')
    d = copy.deepcopy(doc)
    d['slides'][j]['zones'] = {'band': {'metrics': ['apps.total']}}
    assert env.save(p['id'], d, 1, 422)['error']['details'][0]['type'] == 'zones_not_applicable'
    s = next(n for n, x in enumerate(doc['slides']) if x['template_slot'] == 'secao-plano')
    d = copy.deepcopy(doc)
    d['slides'][s]['metrics'] = ['apps.total']
    assert env.save(p['id'], d, 1, 422)['error']['details'][0]['type'] in ('metric_count', 'metrics_not_applicable')


def test_number_of_slides_is_configurable_optional_slots_can_be_removed(env):
    c = env.client('Cliente Enxuto Sintético')
    p, _ = afrika_presentation(env, c['id'])
    doc = env.document(p['id'])
    keep = {'capa', 'painel-kpis', 'painel-severidades', 'encerramento'}
    d = copy.deepcopy(doc)
    d['slides'] = [s for s in d['slides'] if s['template_slot'] in keep]
    env.save(p['id'], d, 1)
    assert [s['template_slot'] for s in env.view(p['id'])['slides']] == ['capa', 'painel-kpis',
                                                                         'painel-severidades', 'encerramento']


def test_forbidden_term_check_works():
    assert has_forbidden({'x': 'Relatório BU TI'}) and not has_forbidden({'x': 'Relatório sintético'})


def test_builtin_definitions_parse_and_hash_deterministically():
    for key in ('demo-executivo', 'demo-tecnico', 'demo-minimo', 'afrika-modelo'):
        a = templates.definition_hash(templates.parse_definition(templates.BUILTIN[(key, 1)]))
        b = templates.definition_hash(templates.parse_definition(copy.deepcopy(templates.BUILTIN[(key, 1)])))
        assert a == b
        if key in OLD_TEMPLATE_HASHES:
            assert a == OLD_TEMPLATE_HASHES[key]
