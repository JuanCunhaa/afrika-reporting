"""F06A — templates versionados, apresentações a partir de revisões aprovadas, edição editorial, IR de gráficos,
persistência e integridade. Dados 100% SINTÉTICOS (valores manuais justificados); nenhuma Veracode.
"""
from __future__ import annotations

import copy
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import db
from app.main import create_app
from app.presentations import charts
from app.snapshots import history
from conftest import error_code

OP = 'Operadora Sintética'
APPROVER = 'Aprovador Sintético'
SEV = ('VERY_HIGH', 'HIGH', 'MEDIUM', 'LOW', 'VERY_LOW', 'INFORMATIONAL', 'UNKNOWN')


def sev(*counts: int) -> dict:
    v = dict(zip(SEV, counts))
    v['total'] = sum(counts)
    return v


TOP_APPS = {'top': [{'application_guid': f'g{i}', 'name': f'App Sintética {i:02d}', 'findings': 30 - i}
                    for i in range(12)], 'applications_with_findings': 12, 'total': 294}
BUS = {'items': [{'business_unit_id': 'b1', 'name': 'BU Sintética 1', 'applications': 7},
                 {'business_unit_id': 'b2', 'name': 'BU Sintética 2', 'applications': 3}],
       'unknown': 0, 'distinct_applications': 10}


def values_for(i: int) -> dict:
    return {'apps.total': 50 + i, 'sast.policy.open.by_severity': sev(1, 2, 3 + i, 4, 0, 0, 0),
            'sca.policy.open.by_severity': sev(0, 1, 1, 2, 0, 1, 0), 'sast.policy.open.top_applications': TOP_APPS,
            'apps.by_business_unit': BUS, 'licenses.usage': 40 + i}


class Env:
    def __init__(self, api: TestClient):
        self.api = api

    def call(self, method: str, url: str, expected: int = 200, **body):
        r = self.api.request(method, url, json=body or None)
        assert r.status_code == expected, r.text
        return r.json()

    def client(self, name: str) -> dict:
        return self.call('POST', '/api/clients', 201, name=name)

    def subclient(self, client_id: str, name: str) -> dict:
        return self.call('POST', f'/api/clients/{client_id}/subclients', 201, name=name)

    def competence(self, owner_id: str, label: str, kind: str = 'client') -> str:
        return self.call('POST', '/api/competences', 201, owner_kind=kind, owner_id=owner_id, competence=label,
                         operator=OP)['id']

    def lock(self, cid: str, n: int) -> int:
        return self.call('GET', f'/api/competences/{cid}/revisions/{n}')['lock_version']

    def fill(self, cid: str, n: int, values: dict) -> None:
        base = f'/api/competences/{cid}/revisions/{n}'
        for mid, v in values.items():
            self.call('PUT', f'{base}/metrics/{mid}', value=v, justification='Valor sintético justificado (F06A)',
                      operator=OP, expected_lock_version=self.lock(cid, n))

    def approve(self, cid: str, n: int = 1, required: list[str] | None = None) -> None:
        base = f'/api/competences/{cid}/revisions/{n}'
        self.call('PUT', f'{base}/required', metric_ids=required or ['apps.total'], operator=OP,
                  expected_lock_version=self.lock(cid, n))
        self.call('POST', f'{base}/submit', operator=OP, expected_lock_version=self.lock(cid, n))
        self.call('POST', f'{base}/approve', approver=APPROVER, expected_lock_version=self.lock(cid, n))

    def approved(self, owner_id: str, label: str, values: dict, kind: str = 'client') -> str:
        cid = self.competence(owner_id, label, kind)
        self.fill(cid, 1, values)
        self.approve(cid, 1, [m for m in values if m == 'apps.total'] or [next(iter(values))])
        return cid

    def builtin(self) -> None:
        self.call('POST', '/api/presentation-templates/builtin', operator=OP)

    def present(self, cid: str, expected: int = 201, **kw) -> dict:
        body = {'competence_id': cid, 'operator': OP, 'template_key': 'demo-executivo', **kw}
        r = self.api.post('/api/presentations', json={k: v for k, v in body.items() if v is not None})
        assert r.status_code == expected, r.text
        return r.json()

    def view(self, pid: str, revision: int | None = None) -> dict:
        return self.call('GET', f'/api/presentations/{pid}/view' + (f'?revision={revision}' if revision else ''))

    def document(self, pid: str, n: int | None = None) -> dict:
        p = self.call('GET', f'/api/presentations/{pid}')
        return self.call('GET', f'/api/presentations/{pid}/revisions/{n or p["current_revision"]}')['document']

    def save(self, pid: str, doc: dict, expected: int, status: int = 200, summary: str = 'edição'):
        r = self.api.put(f'/api/presentations/{pid}/document',
                         json={'document': doc, 'expected_revision': expected, 'operator': OP, 'summary': summary})
        assert r.status_code == status, r.text
        return r.json()


@pytest.fixture
def env(api) -> Env:
    e = Env(api)
    e.builtin()
    return e


def slide(view: dict, slot: str) -> dict:
    return next(s for s in view['slides'] if s['template_slot'] == slot)


def numbers(obj) -> list:
    """Todos os números da IR (y, delta, total), para provar que só valores aprovados aparecem."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ('y', 'delta') and isinstance(v, (int, float)) and not isinstance(v, bool):
                out.append(v)
            else:
                out += numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            out += numbers(v)
    return out


def keys(obj) -> set:
    if isinstance(obj, dict):
        return set(obj) | {k for v in obj.values() for k in keys(v)}
    return {k for v in obj for k in keys(v)} if isinstance(obj, list) else set()


def approved_numbers(values: dict) -> set:
    out = set()
    for v in values.values():
        if isinstance(v, int):
            out.add(v)
        elif isinstance(v, dict):
            out |= {x for x in v.values() if isinstance(x, int)}
            for row in v.get('top', []) + v.get('items', []):
                out |= {x for x in row.values() if isinstance(x, int) and not isinstance(x, bool)}
    return out


# ---------------------------------------------------------------- templates

def test_builtin_templates_are_idempotent_versioned_and_immutable_in_db(env, db_url):
    again = env.call('POST', '/api/presentation-templates/builtin', operator=OP)
    assert again['created'] == [] and len(again['existing']) == 5  # F06C: + afrika-modelo@2
    items = {t['key']: t for t in env.call('GET', '/api/presentation-templates')['items']}
    assert set(items) == {'demo-executivo', 'demo-tecnico', 'demo-minimo', 'afrika-modelo'}  # F06B: + Afrika
    assert items['afrika-modelo']['versions'] == [1, 2] and items['afrika-modelo']['version'] == 2
    assert all(t['origin'] == 'BUILTIN' for t in items.values())
    assert {k: t['theme']['id'] for k, t in items.items()} == {'demo-executivo': 'neutral-demo',
                                                                'demo-tecnico': 'neutral-demo',
                                                                'demo-minimo': 'neutral-demo',
                                                                'afrika-modelo': 'afrika'}
    d = env.call('GET', '/api/presentation-templates/demo-executivo/versions/1')['definition']
    assert [s['type'] for s in d['slides']] == ['cover', 'executive_summary', 'kpis', 'month_comparison',
                                                'severity_distribution', 'line_chart', 'top10_ranking',
                                                'recommendations', 'closing']
    assert not keys(d) & {'value', 'values', 'number', 'headline'}  # nenhum campo de valor no template
    r = env.api.post('/api/presentation-templates/demo-executivo/versions',
                     json={'definition': d, 'operator': OP, 'expected_version': 1})
    assert r.status_code == 409 and error_code(r) == 'builtin_template_readonly'
    engine = db.make_engine(db_url)
    try:
        with engine.begin() as conn, pytest.raises(Exception, match='presentation_templates_append_only'):
            conn.execute(text("UPDATE presentation_templates SET name = 'x'"))
        with engine.begin() as conn, pytest.raises(Exception, match='presentation_templates_append_only'):
            conn.execute(text('DELETE FROM presentation_templates'))
    finally:
        engine.dispose()


def _custom_definition(env) -> dict:
    d = copy.deepcopy(env.call('GET', '/api/presentation-templates/demo-minimo/versions/1')['definition'])
    d['name'] = 'Próprio sintético'
    return d


def test_custom_template_versions_keep_existing_presentations_on_their_version(env):
    d = _custom_definition(env)
    t1 = env.call('POST', '/api/presentation-templates', 201, key='meu-template', definition=d, operator=OP)
    assert t1['version'] == 1 and t1['origin'] == 'CUSTOM'
    r = env.api.post('/api/presentation-templates', json={'key': 'meu-template', 'definition': d, 'operator': OP})
    assert r.status_code == 409 and error_code(r) == 'template_exists'
    c = env.client('Cliente Versões')
    cid = env.approved(c['id'], '2026-09', {'apps.total': 10})
    p1 = env.present(cid, template_key='meu-template')
    d2 = copy.deepcopy(d)
    d2['slides'].insert(1, {'slot_id': 'kpis', 'type': 'kpis', 'fields': {'title': 'KPIs'},
                            'metrics': ['apps.total']})
    r = env.api.post('/api/presentation-templates/meu-template/versions',
                     json={'definition': d2, 'operator': OP, 'expected_version': 2})
    assert r.status_code == 409 and error_code(r) == 'template_conflict'
    t2 = env.call('POST', '/api/presentation-templates/meu-template/versions', 201, definition=d2, operator=OP,
                  expected_version=1)
    assert t2['version'] == 2 and t2['definition_hash'] != t1['definition_hash']
    r = env.api.post('/api/presentation-templates/meu-template/versions',
                     json={'definition': d2, 'operator': OP, 'expected_version': 2})
    assert r.status_code == 409 and error_code(r) == 'template_unchanged'
    assert env.view(p1['id'])['template']['version'] == 1
    assert len(env.view(p1['id'])['slides']) == 3
    p2 = env.present(env.approved(c['id'], '2026-08', {'apps.total': 9}), template_key='meu-template')
    assert p2['template']['version'] == 2 and len(env.view(p2['id'])['slides']) == 4
    assert env.call('GET', '/api/presentation-templates/meu-template/versions/1')['definition_hash'] == \
        t1['definition_hash']


@pytest.mark.parametrize('mutate, code', [
    (lambda d: d['slides'][1].update(value=42), 'invalid_template'),                     # número no template
    (lambda d: d['slides'][1]['fields'].update(value=1), 'invalid_template'),
    (lambda d: d['slides'][1].update(type='severity_distribution'), 'invalid_template'),  # apps.total ≠ severidade
    (lambda d: d['metric_contracts'].clear(), 'invalid_template'),                      # versões de contrato
    (lambda d: d['slides'][1].update(metrics=['nao.existe']), 'invalid_template'),
    (lambda d: d.update(theme={'id': 'marca-afrika', 'version': 1}), 'invalid_template'),
    (lambda d: d['slides'][0].update(layout='inexistente'), 'invalid_template'),
    (lambda d: d['slides'].append(dict(d['slides'][0])), 'invalid_template'),          # slot repetido
])
def test_template_validation_rejects_values_and_incompatible_definitions(env, mutate, code):
    d = _custom_definition(env)
    mutate(d)
    r = env.api.post('/api/presentation-templates', json={'key': 'invalido', 'definition': d, 'operator': OP})
    assert r.status_code == 422 and error_code(r) == code, r.text


def test_each_client_and_subclient_can_choose_its_template(env):
    a, b = env.client('Cliente A'), env.client('Cliente B')
    sub_a, sub_b = env.subclient(a['id'], 'Sub A1'), env.subclient(a['id'], 'Sub A2')
    assert env.call('GET', f'/api/template-selection/client/{a["id"]}')['template'] is None
    env.call('PUT', f'/api/template-selection/client/{a["id"]}', template_key='demo-executivo', template_version=1,
             operator=OP)
    env.call('PUT', f'/api/template-selection/client/{b["id"]}', template_key='demo-tecnico', template_version=1,
             operator=OP)
    env.call('PUT', f'/api/template-selection/subclient/{sub_b["id"]}', template_key='demo-minimo',
             template_version=1, operator=OP)
    inherited = env.call('GET', f'/api/template-selection/subclient/{sub_a["id"]}')
    assert inherited['inherited'] is True and inherited['template']['key'] == 'demo-executivo'
    made = {}
    for owner, kind in ((a, 'client'), (b, 'client'), (sub_a, 'subclient'), (sub_b, 'subclient')):
        cid = env.approved(owner['id'], '2026-09', {'apps.total': 5}, kind=kind)
        r = env.api.post('/api/presentations', json={'competence_id': cid, 'operator': OP})
        assert r.status_code == 201, r.text
        made[owner['name']] = r.json()['template']['key']
    assert made == {'Cliente A': 'demo-executivo', 'Cliente B': 'demo-tecnico', 'Sub A1': 'demo-executivo',
                    'Sub A2': 'demo-minimo'}
    # cliente sem subclientes e sem escolha: exige template explícito
    c = env.client('Sem escolha')
    cid = env.approved(c['id'], '2026-09', {'apps.total': 1})
    r = env.api.post('/api/presentations', json={'competence_id': cid, 'operator': OP})
    assert r.status_code == 409 and error_code(r) == 'template_required'
    sub_view = env.view(env.call('GET', f'/api/presentations?owner_kind=subclient&owner_id={sub_b["id"]}')
                        ['items'][0]['id'])
    assert sub_view['owner'] == {'kind': 'subclient', 'id': sub_b['id'], 'name': 'Sub A2',
                                 'key': f'subclient:{sub_b["id"]}'}


# ---------------------------------------------------------------- fonte: só aprovados

def test_presentations_only_use_approved_revisions(env):
    c = env.client('Cliente Rascunho')
    draft = env.competence(c['id'], '2026-09')
    env.fill(draft, 1, {'apps.total': 3})
    r = env.api.post('/api/presentations', json={'competence_id': draft, 'operator': OP,
                                                 'template_key': 'demo-minimo'})
    assert r.status_code == 409 and error_code(r) == 'no_approved_revision'
    base = f'/api/competences/{draft}/revisions/1'
    env.call('PUT', f'{base}/required', metric_ids=['apps.total'], operator=OP, expected_lock_version=env.lock(draft, 1))
    env.call('POST', f'{base}/submit', operator=OP, expected_lock_version=env.lock(draft, 1))
    r = env.api.post('/api/presentations', json={'competence_id': draft, 'operator': OP, 'revision': 1,
                                                 'template_key': 'demo-minimo'})
    assert r.status_code == 409 and error_code(r) == 'revision_not_approved'  # em revisão também é recusado
    env.call('POST', f'{base}/approve', approver=APPROVER, expected_lock_version=env.lock(draft, 1))
    env.call('POST', f'/api/competences/{draft}/revisions', 201, operator=OP)  # revisão 2 em rascunho
    r = env.api.post('/api/presentations', json={'competence_id': draft, 'operator': OP, 'revision': 2,
                                                 'template_key': 'demo-minimo'})
    assert r.status_code == 409 and error_code(r) == 'revision_not_approved'
    p = env.present(draft, template_key='demo-minimo')
    v = env.view(p['id'])
    assert v['sources']['primary']['revision'] == 1 and v['sources']['policy'] == 'APPROVED_ONLY_PINNED'
    assert v['sources']['primary']['content_hash'] == \
        env.call('GET', f'/api/competences/{draft}/official')['approval']['content_hash']


def test_db_refuses_presentation_revision_pointing_to_unapproved_source(env, db_url):
    c = env.client('Cliente Gatilho')
    cid = env.approved(c['id'], '2026-09', {'apps.total': 2})
    p = env.present(cid, template_key='demo-minimo')
    env.call('POST', f'/api/competences/{cid}/revisions', 201, operator=OP)
    engine = db.make_engine(db_url)
    try:
        with engine.begin() as conn:
            draft_id = conn.execute(text("SELECT id FROM competence_revisions WHERE status = 'DRAFT'")).scalar()
        with engine.begin() as conn, pytest.raises(Exception, match='presentation_source_not_approved'):
            conn.execute(text("INSERT INTO presentation_revisions (id, presentation_id, number, document_json, "
                              "document_hash, sources_json, sources_hash, primary_revision_id, primary_approval_id, "
                              "change_summary, revision_hash, created_by, created_at) SELECT 'x', presentation_id, 9, "
                              "document_json, document_hash, sources_json, sources_hash, :d, primary_approval_id, '', "
                              "'h', 'x', created_at FROM presentation_revisions LIMIT 1"), {'d': draft_id})
        with engine.begin() as conn, pytest.raises(Exception, match='presentation_revisions_append_only'):
            conn.execute(text("UPDATE presentation_revisions SET document_json = '{}'"))
        with engine.begin() as conn, pytest.raises(Exception, match='presentation_identity_immutable'):
            conn.execute(text("UPDATE presentations SET created_by = 'outro'"))
        with engine.begin() as conn, pytest.raises(Exception, match='presentation_delete_forbidden'):
            conn.execute(text('DELETE FROM presentations'))
    finally:
        engine.dispose()
    assert env.call('GET', f'/api/presentations/{p["id"]}/integrity')['ok'] is True


# ---------------------------------------------------------------- valores, lacunas, manuais, gráficos

def test_view_shows_exact_approved_values_manual_identified_and_no_invented_numbers(env):
    c = env.client('Cliente Valores')
    vals = values_for(0)
    prev_vals = values_for(-2)
    env.approved(c['id'], '2026-08', prev_vals)
    cid = env.approved(c['id'], '2026-09', vals)
    v = env.view(env.present(cid)['id'])
    assert v['theme']['provisional'] is True and 'PROVISÓRIO' in v['theme']['notice']
    kpis = slide(v, 'kpis')['data']['items']
    assert [(k['metric_id'], k['y'], k['label']) for k in kpis] == [
        ('apps.total', 50, '50'), ('sast.policy.open.by_severity', 10, '10'),
        ('sca.policy.open.by_severity', 5, '5')]
    assert all(k['origin'] == 'MANUAL' and k['value_state'] == 'MANUAL' for k in kpis)
    assert {i['code'] for i in slide(v, 'kpis')['issues']} == {'manual_value'}
    sev_ir = slide(v, 'severidade-sast')['data']
    assert [p['y'] for p in sev_ir['series'][0]['points']] == [1, 2, 3, 4, 0, 0, 0]
    assert [p['color'] for p in sev_ir['series'][0]['points']] == [f'severity.{k}' for k in SEV]
    assert sev_ir['total'] == {'y': 10, 'label': '10'}
    rank = slide(v, 'top-apps')['data']
    assert len(rank['rows']) == 10 and rank['rows'][0] == {'rank': 1, 'label': 'App Sintética 00', 'y': 30,
                                                           'value': '30', 'extra': {}}
    assert [r['y'] for r in rank['rows']] == [30 - i for i in range(10)]  # ordem da fonte, sem reordenar
    cmp_ir = slide(v, 'comparacao')['data']
    assert [(r['metric_id'], r['previous']['y'], r['current']['y'], r['delta'], r['delta_label'])
            for r in cmp_ir['rows']] == [('apps.total', 48, 50, 2, '+2'),
                                         ('sast.policy.open.by_severity', 8, 10, 2, '+2'),
                                         ('sca.policy.open.by_severity', 5, 5, 0, '0')]
    allowed = approved_numbers(vals) | approved_numbers(prev_vals) | {2, 0}  # deltas = diferenças aprovadas
    for s in v['slides']:
        assert set(numbers(s['data'])) <= allowed, s['slide_id']
    src = {m['metric_id']: m for m in v['sources']['metrics']}
    assert src['apps.total']['value'] == 50 and src['apps.total']['manual']['operator'] == OP
    assert src['apps.total']['dashboard_homologation'] == 'NOT_VERIFIED'
    assert 'credential_ref' not in str(v)


def test_series_of_6_and_12_months_keep_gaps_without_interpolation(env):
    c = env.client('Cliente Séries')
    months = history.month_range('2025-10', '2026-09')
    expected = {}
    for i, label in enumerate(months):
        if label in ('2026-02', '2026-06'):
            continue
        expected[label] = 50 + i
        env.approved(c['id'], label, {'apps.total': 50 + i, 'sast.policy.open.by_severity': sev(i, 0, 0, 0, 0, 0, 0)})
    cid = env.call('GET', f'/api/competences?owner_kind=client&owner_id={c["id"]}')['items'][0]['id']
    p = env.present(cid, template_key='demo-tecnico')
    v = env.view(p['id'])
    bars = slide(v, 'serie-apps')['data']
    assert bars['kind'] == 'bar' and bars['categories'] == months and len(bars['series'][0]['points']) == 12
    pts = {pt['x']: pt for pt in bars['series'][0]['points']}
    assert pts['2026-02'] == {**pts['2026-02'], 'y': None, 'state': 'GAP', 'label': 'lacuna'}
    assert {x: pt['y'] for x, pt in pts.items() if pt['state'] == 'VALUE'} == expected
    assert bars['gaps'] == ['2026-02', '2026-06']
    lines = slide(v, 'serie-findings')['data']
    assert [s['key'] for s in lines['series']] == ['sast.policy.open.by_severity', 'sca.policy.open.by_severity']
    assert [s['color'] for s in lines['series']] == ['series.1', 'series.2']
    assert all(pt['state'] == 'MISSING' and pt['y'] is None for pt in lines['series'][1]['points']
               if pt['x'] not in ('2026-02', '2026-06'))  # SCA nunca aprovado: ausente, nunca zero
    doc = env.document(p['id'])
    serie = next(s for s in doc['slides'] if s['slide_id'] == 'serie-apps')
    serie['options']['months'] = 6
    env.save(p['id'], doc, 1)
    six = slide(env.view(p['id']), 'serie-apps')['data']
    assert six['categories'] == months[6:] and six['gaps'] == ['2026-06']
    assert [pt['y'] for pt in six['series'][0]['points']] == [expected.get(m) for m in months[6:]]


def test_missing_incompatible_and_unrecognized_values_are_explicit(env):
    d = copy.deepcopy(env.call('GET', '/api/presentation-templates/demo-executivo/versions/1')['definition'])
    d['metric_contracts']['sast.policy.open.top_applications'] = [2]  # exige v2 (snapshot é v1)
    env.call('POST', '/api/presentation-templates', 201, key='exige-v2', definition=d, operator=OP)
    c = env.client('Cliente Lacunas')
    cid = env.approved(c['id'], '2026-09', {'apps.total': 7, 'sast.policy.open.top_applications': {'top': [
        {'application_guid': 'g', 'findings': 'muitos'}]}})
    v = env.view(env.present(cid, template_key='exige-v2')['id'])
    kpis = slide(v, 'kpis')
    assert [(i['metric_id'], i['state'], i['y'], i['label']) for i in kpis['data']['items']] == [
        ('apps.total', 'VALUE', 7, '7'), ('sast.policy.open.by_severity', 'MISSING', None, 'ausente'),
        ('sca.policy.open.by_severity', 'MISSING', None, 'ausente')]
    assert [i['level'] for i in kpis['issues'] if i['code'] == 'metric_missing'] == ['blocker', 'blocker']
    assert v['ready'] is False and v['blockers'] == 2
    rank = slide(v, 'top-apps')
    assert rank['data'] == {**rank['data'], 'available': False, 'reason': 'incompatible'}
    assert any(i['code'] == 'contract_incompatible' for i in rank['issues'])
    sev_slide = slide(v, 'severidade-sast')
    assert sev_slide['data']['available'] is False and sev_slide['data']['reason'] == 'missing'
    cmp_rows = slide(v, 'comparacao')['data']['rows']
    assert cmp_rows[0]['previous']['state'] == 'GAP' and cmp_rows[0]['delta'] is None
    assert cmp_rows[0]['delta_unavailable_reason'] == 'gap'
    line = slide(v, 'serie-sast')['data']
    assert len(line['categories']) == 6 and all(pt['y'] is None for pt in line['series'][0]['points'])
    assert line['gaps'] == history.month_range('2026-04', '2026-08')
    # estrutura não reconhecida (manual sem campo numérico) => indisponível, nada presumido
    assert charts.ranking({'metric_id': 'sast.policy.open.top_applications', 'name': 'x', 'state': 'NOT_NUMERIC',
                           'value': {'top': [{'name': 'a', 'findings': 'muitos'}]}})['reason'] == \
        'unrecognized_structure'


# ---------------------------------------------------------------- edição

def test_editing_reorders_removes_and_adds_slides_without_touching_metrics(env):
    c = env.client('Cliente Edição')
    cid = env.approved(c['id'], '2026-09', values_for(1))
    before = env.call('GET', f'/api/competences/{cid}/official')
    p = env.present(cid)
    doc = env.document(p['id'])
    ids = [s['slide_id'] for s in doc['slides']]
    doc['title'] = 'Relatório editado'
    doc['presenters'] = [{'name': 'Pessoa Apresentadora', 'role': 'AppSec'}]
    doc['slides'][0]['fields']['title'] = 'Título editado da capa'
    sev_slide = next(s for s in doc['slides'] if s['slide_id'] == 'severidade-sast')
    sev_slide['fields'].update(chart_title='Gráfico renomeado', legend_title='Severidades', caption='Observação X')
    doc['slides'] = [s for s in doc['slides'] if s['slide_id'] != 'recomendacoes']       # remove opcional
    doc['slides'].insert(1, doc['slides'].pop(doc['slides'].index(sev_slide)))            # reordena
    doc['slides'].insert(3, {'slide_id': 'novo-ranking', 'type': 'bar_chart', 'layout': 'chart-full',
                             'fields': {'title': 'BUs'}, 'metrics': ['apps.by_business_unit'],
                             'options': {'data_mode': 'breakdown'}})                       # inclui
    saved = env.save(p['id'], doc, 1, summary='reordenação')
    assert saved['current_revision'] == 2 and saved['title'] == 'Relatório editado'
    v = env.view(p['id'])
    assert [s['slide_id'] for s in v['slides']] == ['capa', 'severidade-sast', 'sumario', 'novo-ranking', 'kpis',
                                                    'comparacao', 'serie-sast', 'top-apps', 'encerramento']
    assert slide(v, 'capa')['fields']['title'] == 'Título editado da capa'
    assert slide(v, 'capa')['data']['presenters'] == [{'name': 'Pessoa Apresentadora', 'role': 'AppSec'}]
    assert slide(v, 'severidade-sast')['data']['title'] == 'Gráfico renomeado'
    bus = next(s for s in v['slides'] if s['slide_id'] == 'novo-ranking')['data']
    assert bus['categories'] == ['BU Sintética 1', 'BU Sintética 2'] and \
        [pt['y'] for pt in bus['series'][0]['points']] == [7, 3]
    # revisão anterior preservada
    old = env.view(p['id'], revision=1)
    assert [s['slide_id'] for s in old['slides']] == ids
    # obrigatório não sai; indicador obrigatório não sai; valor não entra no documento
    bad = copy.deepcopy(doc)
    bad['slides'] = [s for s in bad['slides'] if s['slide_id'] != 'encerramento']
    r = env.save(p['id'], bad, 2, 422)
    assert r['error']['code'] == 'invalid_document' and r['error']['details'][0]['type'] == 'required_slide_removed'
    bad = copy.deepcopy(doc)
    next(s for s in bad['slides'] if s['slide_id'] == 'kpis')['metrics'] = ['apps.total']
    assert env.save(p['id'], bad, 2, 422)['error']['details'][0]['type'] == 'required_metric_removed'
    bad = copy.deepcopy(doc)
    bad['slides'][2]['value'] = 999
    assert env.save(p['id'], bad, 2, 422)['error']['code'] == 'validation_error'
    bad = copy.deepcopy(doc)
    next(s for s in bad['slides'] if s['slide_id'] == 'novo-ranking')['metrics'] = ['apps.total']
    assert env.save(p['id'], bad, 2, 422)['error']['details'][0]['type'] == 'incompatible_metric'
    bad = copy.deepcopy(doc)
    bad['slides'][0]['fields']['title'] = ''
    assert env.save(p['id'], bad, 2, 422)['error']['details'][0]['type'] == 'required_field'
    assert env.save(p['id'], doc, 2, 409)['error']['code'] == 'presentation_unchanged'
    assert env.save(p['id'], {**doc, 'title': 'Outro'}, 1, 409)['error']['code'] == 'presentation_conflict'
    # snapshots aprovados intactos
    after = env.call('GET', f'/api/competences/{cid}/official')
    assert [s['row_hash'] for s in after['snapshots']] == [s['row_hash'] for s in before['snapshots']]
    assert after['approval'] == before['approval']
    assert env.call('GET', f'/api/competences/{cid}/integrity')['ok'] is True
    assert env.call('GET', f'/api/presentations/{p["id"]}/integrity')['ok'] is True
    events = [e['event_type'] for e in env.call('GET', f'/api/competences/{cid}/audit')['items']]
    assert events[-2:] == ['presentation.created', 'presentation.saved']


def test_concurrent_saves_one_wins_others_conflict(env):
    c = env.client('Cliente Concorrência')
    p = env.present(env.approved(c['id'], '2026-09', {'apps.total': 1}), template_key='demo-minimo')
    doc = env.document(p['id'])
    results = []

    def worker(i):
        d = copy.deepcopy(doc)
        d['title'] = f'Título concorrente {i}'
        r = env.api.put(f'/api/presentations/{p["id"]}/document',
                        json={'document': d, 'expected_revision': 1, 'operator': OP})
        results.append(r.status_code)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [200, 409, 409, 409]
    assert env.call('GET', f'/api/presentations/{p["id"]}')['current_revision'] == 2


# ---------------------------------------------------------------- persistência, fixação e integridade

def test_presentation_survives_restart_with_identical_view(db_url):
    with TestClient(create_app(db_url)) as api:
        env = Env(api)
        env.builtin()
        c = env.client('Cliente Reinício')
        cid = env.approved(c['id'], '2026-09', values_for(2))
        p = env.present(cid)
        doc = env.document(p['id'])
        doc['slides'][0]['fields']['subtitle'] = 'Persistido'
        env.save(p['id'], doc, 1)
        first = env.view(p['id'])
    with TestClient(create_app(db_url)) as api:
        env = Env(api)
        again = env.view(p['id'])
        assert again == first
        assert slide(again, 'capa')['fields']['subtitle'] == 'Persistido'
        assert [r['number'] for r in env.call('GET', f'/api/presentations/{p["id"]}')['revisions']] == [1, 2]
        assert env.call('GET', f'/api/presentations/{p["id"]}/integrity')['ok'] is True


def test_pinned_sources_do_not_move_until_explicit_rebind(env):
    c = env.client('Cliente Fixação')
    aug = env.approved(c['id'], '2026-08', {'apps.total': 20})
    sep = env.approved(c['id'], '2026-09', {'apps.total': 30})
    p = env.present(sep, template_key='demo-tecnico')
    v1 = env.view(p['id'])
    assert {pt['x']: pt['y'] for pt in slide(v1, 'serie-apps')['data']['series'][0]['points']
            if pt['state'] == 'VALUE'} == {'2026-08': 20, '2026-09': 30}
    # nova revisão aprovada de agosto e de setembro, e julho aprovado depois
    for cid, value in ((aug, 21), (sep, 31)):
        env.call('POST', f'/api/competences/{cid}/revisions', 201, operator=OP)
        env.fill(cid, 2, {'apps.total': value})
        env.approve(cid, 2)
    env.approved(c['id'], '2026-07', {'apps.total': 10})
    v2 = env.view(p['id'])
    assert slide(v2, 'serie-apps')['data'] == slide(v1, 'serie-apps')['data']  # fonte fixada não muda sozinha
    codes = {c_['code'] for c_ in v2['checks']}
    assert codes == {'newer_approval_available', 'history_refs_outdated'}
    r = env.call('POST', f'/api/presentations/{p["id"]}/rebind', operator=OP, expected_revision=1)
    assert r['changes'] == {'primary_changed': True, 'history_changed': ['2026-07', '2026-08']}
    v3 = env.view(p['id'])
    assert {pt['x']: pt['y'] for pt in slide(v3, 'serie-apps')['data']['series'][0]['points']
            if pt['state'] == 'VALUE'} == {'2026-07': 10, '2026-08': 21, '2026-09': 31}
    assert v3['checks'] == [] and v3['sources']['primary']['revision'] == 2
    assert env.view(p['id'], revision=1)['sources']['primary']['revision'] == 1  # revisão antiga preservada
    r = env.api.post(f'/api/presentations/{p["id"]}/rebind', json={'operator': OP, 'expected_revision': 2})
    assert r.status_code == 409 and error_code(r) == 'sources_unchanged'
    r = env.api.post(f'/api/presentations/{p["id"]}/rebind', json={'operator': OP, 'expected_revision': 2,
                                                                   'revision': 1})
    assert r.status_code == 200 and env.view(p['id'])['sources']['primary']['revision'] == 1  # outra aprovada


def test_integrity_detects_tampering_of_presentation_and_pinned_snapshots(env, db_url):
    c = env.client('Cliente Integridade')
    cid = env.approved(c['id'], '2026-09', {'apps.total': 4})
    p = env.present(cid, template_key='demo-minimo')
    assert env.call('GET', f'/api/presentations/{p["id"]}/integrity')['ok'] is True
    engine = db.make_engine(db_url)
    try:
        with engine.begin() as conn:
            conn.execute(text('DROP TRIGGER trg_presentation_revisions_no_update'))
            conn.execute(text("UPDATE presentation_revisions SET document_json = "
                              "replace(document_json, 'Relatório AppSec', 'Adulterado')"))
            conn.execute(text('DROP TRIGGER trg_metric_snapshots_update_draft'))
            conn.execute(text("UPDATE metric_snapshots SET value_json = '999' WHERE metric_id = 'apps.total'"))
    finally:
        engine.dispose()
    report = env.call('GET', f'/api/presentations/{p["id"]}/integrity')
    assert report['ok'] is False
    assert 'revisão 1: documento divergente do hash' in report['problems']
    assert '2026-09: snapshot apps.total divergente do hash' in report['problems']


def test_downgrade_refuses_to_drop_saved_presentations(env, db_url, monkeypatch):
    c = env.client('Cliente Downgrade')
    env.present(env.approved(c['id'], '2026-09', {'apps.total': 1}), template_key='demo-minimo')
    monkeypatch.delenv('AFRIKA_ALLOW_DESTRUCTIVE_DOWNGRADE', raising=False)
    with pytest.raises(RuntimeError, match='downgrade recusado'):
        db.downgrade(db_url, '0004_snapshots')
    engine = db.make_engine(db_url)
    try:
        assert db.current_revision(engine) == '0005_presentations'  # 0006 (sem temas próprios) desceu; 0005 recusou
    finally:
        engine.dispose()


def test_catalog_lists_all_slide_types_and_compatible_metrics(env):
    cat = env.call('GET', '/api/presentation-catalog')
    assert [t['type'] for t in cat['slide_types']] == [
        'cover', 'executive_summary', 'kpis', 'month_comparison', 'bar_chart', 'line_chart', 'severity_distribution',
        'top10_ranking', 'metric_table', 'recommendations', 'closing', 'section', 'dashboard']  # F06B: + 2
    m = {x['metric_id']: x for x in cat['metrics']}
    assert 'severity_distribution' in m['sast.policy.open.by_severity']['slide_types']
    assert 'severity_distribution' not in m['apps.total']['slide_types']
    assert 'top10_ranking' in m['sca.policy.open.top_components']['slide_types']
    # F06B.1: o catálogo lista RESUMOS de temas (embutidos + próprios); o tema completo vem por versão
    assert cat['themes'][0]['id'] == 'neutral-demo' and cat['themes'][0]['provisional'] is True
    theme = env.call('GET', '/api/presentation-themes/neutral-demo/versions/1')
    assert theme['canvas'] == {'width': 1280, 'height': 720, 'aspect_ratio': '16:9'}


# ---------------------------------------------------------------- IR (unidade)

def test_number_format_contract_rounds_only_labels():
    assert charts.fmt(1234567, 'count') == '1.234.567'
    assert charts.fmt(0, 'count') == '0'
    assert charts.fmt(12.25, 'percentage') == '12,2%' and charts.fmt(12.35, 'percentage') == '12,4%'  # meio-par
    assert charts.fmt(1234.5, 'decimal') == '1.234,50'
    assert charts.fmt(None, 'count') == '—' and charts.fmt(True, 'count') == '—'
    pt = charts.point({'metric_id': 'm', 'state': 'VALUE', 'headline': 12.25, 'value_type': 'percentage'}, 'x')
    assert pt['y'] == 12.25 and pt['label'] == '12,2%'  # valor bruto preservado


def test_comparison_delta_only_between_comparable_approved_values():
    def p(state, h, vt='count', cv=1, comp='2026-09'):
        return {'metric_id': 'm', 'name': 'M', 'state': state, 'headline': h, 'value_type': vt,
                'contract_version': cv, 'competence': comp}
    rows = charts.comparison([(p('VALUE', 5), p('VALUE', 7)), (p('VALUE', 5), p('GAP', None)),
                              (p('VALUE', 5), p('VALUE', 5, cv=2)), (p('VALUE', 5), p('VALUE', 5, vt='decimal')),
                              (p('VALUE', 5), p('MISSING', None))])['rows']
    assert [(r['delta'], r['delta_label'], r['delta_unavailable_reason']) for r in rows] == [
        (-2, '−2', None), (None, None, 'gap'), (None, None, 'contract_version_changed'),
        (None, None, 'value_type_changed'), (None, None, 'no_numeric_value')]


def test_preview_of_unsaved_document_writes_nothing(env):
    c = env.client('Cliente Pré-visualização')
    p = env.present(env.approved(c['id'], '2026-09', {'apps.total': 3}), template_key='demo-minimo')
    doc = env.document(p['id'])
    doc['slides'][0]['fields']['title'] = 'Só na pré-visualização'
    v = env.call('POST', f'/api/presentations/{p["id"]}/preview', document=doc)
    assert v['draft'] is True and v['slides'][0]['fields']['title'] == 'Só na pré-visualização'
    assert env.call('GET', f'/api/presentations/{p["id"]}')['current_revision'] == 1
    assert env.view(p['id'])['slides'][0]['fields']['title'] == 'Relatório AppSec'
    doc['slides'] = doc['slides'][1:]  # sem a capa obrigatória
    r = env.api.post(f'/api/presentations/{p["id"]}/preview', json={'document': doc})
    assert r.status_code == 422 and error_code(r) == 'invalid_document'


def test_upgrade_from_f05_database_with_approved_history(db_url):
    """Banco F05 (0004) com histórico aprovado recebe a 0005 sem perder nada e já gera apresentação."""
    with TestClient(create_app(db_url)) as api:
        env = Env(api)
        c = env.client('Cliente Legado F05')
        cid = env.approved(c['id'], '2026-09', {'apps.total': 8})
        official = env.call('GET', f'/api/competences/{cid}/official')
    db.downgrade(db_url, '0004_snapshots')  # sem apresentações: permitido
    engine = db.make_engine(db_url)
    try:
        assert db.current_revision(engine) == '0004_snapshots'
        with engine.connect() as conn:
            assert conn.execute(text('SELECT COUNT(*) FROM approvals')).scalar() == 1
        db.upgrade(db_url)
        assert db.current_revision(engine) == db.head_revision() == '0008_metric_conferences'
    finally:
        engine.dispose()
    with TestClient(create_app(db_url)) as api:
        env = Env(api)
        assert env.call('GET', f'/api/competences/{cid}/official')['approval'] == official['approval']
        env.builtin()
        v = env.view(env.present(cid, template_key='demo-minimo')['id'])
        assert v['slides'][1]['data']['rows'][0]['y'] == 8
        assert env.call('GET', f'/api/competences/{cid}/integrity')['ok'] is True
