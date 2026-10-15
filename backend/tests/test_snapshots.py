"""F05 — snapshots por competência, revisões, entrada manual, aprovação, auditoria e integridade.

Tenant SINTÉTICO `gamma` (ver test_metrics.py); nenhuma Veracode real. Operador/aprovador são nomes declarados.
"""
from __future__ import annotations

import json
import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import db
from app.main import create_app
from app.metrics.registry import REGISTRY
from app.veracode.fixtures import synthetic_credentials
from app.veracode.settings import VeracodeSettings
from conftest import error_code
from test_metrics import M, gamma_tenant, metrics_env

OP = 'Operadora Sintética'
APPROVER = 'Aprovador Sintético'
JUST = 'Ajuste sintético justificado para teste'


class Flow:
    def __init__(self, env):
        self.env, self.api = env, env.api

    def owner(self, **kw):
        c = self.env.client(**kw)
        self.env.universe(c['id'])
        return c

    def from_run(self, run):
        r = self.api.post('/api/competences/from-run', json={'run_id': run['run_id'], 'operator': OP})
        assert r.status_code == 201, r.text
        return r.json()

    def detail(self, cid, n):
        r = self.api.get(f'/api/competences/{cid}/revisions/{n}')
        assert r.status_code == 200, r.text
        return r.json()

    def base(self, cid, n):
        return f'/api/competences/{cid}/revisions/{n}'

    def lock(self, cid, n):
        return self.detail(cid, n)['lock_version']

    def required(self, cid, n, ids):
        r = self.api.put(f'{self.base(cid, n)}/required',
                         json={'metric_ids': ids, 'operator': OP, 'expected_lock_version': self.lock(cid, n)})
        assert r.status_code == 200, r.text
        return r.json()

    def manual(self, cid, n, metric_id, value, *, justification=JUST, lock=None):
        return self.api.put(f'{self.base(cid, n)}/metrics/{metric_id}',
                            json={'value': value, 'justification': justification, 'operator': OP,
                                  'expected_lock_version': lock or self.lock(cid, n)})

    def submit(self, cid, n):
        r = self.api.post(f'{self.base(cid, n)}/submit', json={'operator': OP, 'expected_lock_version': self.lock(cid, n)})
        assert r.status_code == 200, r.text
        return r.json()

    def approve(self, cid, n, *, approver=APPROVER):
        return self.api.post(f'{self.base(cid, n)}/approve',
                             json={'approver': approver, 'note': 'ok', 'expected_lock_version': self.lock(cid, n)})

    def approve_ok(self, cid, n):
        r = self.approve(cid, n)
        assert r.status_code == 200, r.text
        return r.json()

    def competence(self, client_id, label, kind='client'):
        r = self.api.post('/api/competences', json={'owner_kind': kind, 'owner_id': client_id, 'competence': label,
                                                    'operator': OP})
        assert r.status_code == 201, r.text
        return r.json()


@pytest.fixture
def flow(db_url):
    with metrics_env(db_url) as env:
        yield Flow(env)


def snap(detail, metric_id):
    return next(s for s in detail['snapshots'] if s['metric_id'] == metric_id)


def approved_draft(flow, c, ids=('apps.total',)):
    run = flow.env.run('client', c['id'])
    out = flow.from_run(run)
    cid, n = out['competence_id'], out['revision']
    flow.required(cid, n, list(ids))
    flow.submit(cid, n)
    flow.approve_ok(cid, n)
    return run, cid, n


# ---------------------------------------------------------------- rascunho a partir da coleta (F04)

def test_draft_from_run_preserves_source_status_provenance_scope_and_contract(flow):
    c = flow.owner()
    run = flow.env.run('client', c['id'])
    out = flow.from_run(run)
    assert out['revision'] == 1 and out['import']['created'] == len(REGISTRY)
    d = out['detail']
    assert d['status'] == 'DRAFT' and d['editable'] and d['competence']['competence'] == '2026-09'
    assert d['competence']['timezone'] == 'UTC'
    total = snap(d, 'apps.total')
    assert total['value'] == M(run, 'apps.total')['value'] == 4
    assert total['origin'] == 'VERACODE' and total['value_state'] == 'VALIDATED'
    assert total['source']['status'] == 'VALIDATED' and total['source']['name'] == 'Veracode Applications API 1.0'
    assert total['dashboard_homologation'] == 'NOT_VERIFIED'  # técnico VALIDATED ≠ homologado
    assert total['contract_version'] == REGISTRY['apps.total'].version and total['value_type'] == 'count'
    prov = total['provenance']
    assert prov['run_id'] == run['run_id'] and prov['input_hash'] == run['result']['provenance']['input_hash']
    assert total['scope_refs'] == run['result']['provenance']['scope_refs']
    assert total['scope_refs'][0]['rule_hash'] and total['scope_refs'][0]['version'] == 1
    assert total['temporal']['period']['utc_start'] == '2026-09-01T00:00:00+00:00'
    assert total['collection_run_id'] == run['run_id'] and total['source']['collected_at']
    sev = snap(d, 'sast.policy.open.by_severity')
    assert sev['value'] == M(run, 'sast.policy.open.by_severity')['value']
    assert sev['source']['context'] == 'POLICY' and sev['value_type'] == 'by_severity'
    inc = snap(d, 'sast.open.distinct')
    assert inc['value'] is None and inc['value_state'] == 'INCOMPLETE'
    assert inc['source']['partial'] == M(run, 'sast.open.distinct')['partial']
    assert inc['source']['reasons']  # motivo da incompletude preservado


def test_drafts_survive_backend_restart(db_url):
    with metrics_env(db_url) as env:
        f = Flow(env)
        c = f.owner()
        out = f.from_run(env.run('client', c['id']))
        f.manual(out['competence_id'], 1, 'licenses.usage', 12)
    # Processo novo (execuções em memória perdidas): o rascunho continua no banco.
    with TestClient(create_app(db_url)) as api:
        d = api.get(f'/api/competences/{out["competence_id"]}/revisions/1').json()
        assert d['status'] == 'DRAFT' and len(d['snapshots']) == len(REGISTRY)
        assert snap(d, 'apps.total')['value'] == 4 and snap(d, 'licenses.usage')['value'] == 12
        assert api.get(f'/api/competences/{out["competence_id"]}/integrity').json()['ok']


def test_import_rejects_other_owner_other_competence_and_unfinished(flow):
    c1, c2 = flow.owner(name='Dono A'), flow.owner(name='Dono B')
    run2 = flow.env.run('client', c2['id'])
    comp = flow.competence(c1['id'], '2026-09')
    body = {'run_id': run2['run_id'], 'operator': OP, 'expected_lock_version': 1}
    r = flow.api.post(f'/api/competences/{comp["id"]}/revisions/1/import-run', json=body)
    assert r.status_code == 409 and error_code(r) == 'run_owner_mismatch'
    run_aug = flow.env.run('client', c1['id'], competence='2026-08')
    r = flow.api.post(f'/api/competences/{comp["id"]}/revisions/1/import-run', json={**body, 'run_id': run_aug['run_id']})
    assert r.status_code == 409 and error_code(r) == 'run_competence_mismatch'
    r = flow.api.post('/api/competences/from-run', json={'run_id': str(uuid.uuid4()), 'operator': OP})
    assert r.status_code == 404 and error_code(r) == 'metric_run_not_found'


# ---------------------------------------------------------------- cliente/subcliente, competência e fuso

def test_client_and_subclient_have_independent_competences(flow):
    c = flow.owner(name='Holding')
    sub = flow.env.subclient(c['id'], 'Filial')
    flow.env.scope('subclients', sub['id'], 'applications',
                   {'field': 'business_unit.id', 'cmp': 'in', 'values': flow.env.ids['bu'][:1]})
    cc = flow.from_run(flow.env.run('client', c['id']))
    sc = flow.from_run(flow.env.run('subclient', sub['id']))
    assert cc['competence_id'] != sc['competence_id']
    assert snap(cc['detail'], 'apps.total')['value'] == 4 and snap(sc['detail'], 'apps.total')['value'] == 2
    assert sc['detail']['competence']['owner'] == {'kind': 'subclient', 'id': sub['id'], 'client_id': c['id'],
                                                   'subclient_id': sub['id']}
    lst = flow.api.get(f'/api/competences?owner_kind=subclient&owner_id={sub["id"]}').json()['items']
    assert [x['competence'] for x in lst] == ['2026-09']
    # cliente sem subclientes funciona e não enxerga competências do subcliente
    lone = flow.owner(name='Sem subclientes')
    assert flow.from_run(flow.env.run('client', lone['id']))['revision'] == 1
    assert len(flow.api.get(f'/api/competences?owner_kind=client&owner_id={c["id"]}').json()['items']) == 1


def test_competence_must_be_closed_month_in_client_timezone_and_run_timezone_must_match(flow):
    c = flow.env.client(name='Fuso padrão', timezone='America/Sao_Paulo')
    flow.env.universe(c['id'])
    r = flow.api.post('/api/competences', json={'owner_kind': 'client', 'owner_id': c['id'], 'competence': '2999-01',
                                                'operator': OP})
    assert r.status_code == 422 and error_code(r) == 'competence_not_closed'
    r = flow.api.post('/api/competences', json={'owner_kind': 'client', 'owner_id': c['id'], 'competence': '2026-13',
                                                'operator': OP})
    assert r.status_code == 422
    comp = flow.competence(c['id'], '2026-09')
    assert comp['timezone'] == 'America/Sao_Paulo'
    assert comp['period']['utc_start'] == '2026-09-01T03:00:00+00:00'
    r = flow.api.post('/api/competences', json={'owner_kind': 'client', 'owner_id': c['id'], 'competence': '2026-09',
                                                'operator': OP})
    assert r.status_code == 409 and error_code(r) == 'competence_exists'
    run_utc = flow.env.run('client', c['id'], tz='UTC')
    r = flow.api.post('/api/competences/from-run', json={'run_id': run_utc['run_id'], 'operator': OP})
    assert r.status_code == 409 and error_code(r) == 'timezone_mismatch'
    run_sp = flow.env.run('client', c['id'])
    assert flow.from_run(run_sp)['competence_id'] == comp['id']


# ---------------------------------------------------------------- zero × ausência e entrada manual

def test_zero_is_value_and_absence_is_not_zero(db_url):
    t = gamma_tenant()
    for k in list(t.findings):
        if k[1] is None and k[2] == 'STATIC':
            t.findings[k] = []
    with metrics_env(db_url, tenant=t) as env:
        f = Flow(env)
        c = f.owner()
        d = f.from_run(env.run('client', c['id']))['detail']
    zero = snap(d, 'sast.policy.open.by_severity')
    assert zero['value_state'] == 'VALIDATED' and zero['value']['total'] == 0 and zero['headline'] == 0
    unavailable = snap(d, 'apps.total.at_period_end')
    assert unavailable['value'] is None and unavailable['headline'] is None
    assert unavailable['value_state'] == 'SOURCE_UNAVAILABLE'
    unsupported = snap(d, 'licenses.usage')
    assert unsupported['value'] is None and unsupported['value_state'] == 'UNSUPPORTED'
    assert snap(d, 'sast.open.distinct')['value_state'] == 'INCOMPLETE'


def test_manual_values_are_typed_and_preserve_source_value(flow):
    c = flow.owner()
    out = flow.from_run(flow.env.run('client', c['id']))
    cid = out['competence_id']
    for bad in (-1, 1.5, '3', True, None, [1], {'count': -2}):
        r = flow.manual(cid, 1, 'apps.total', bad)
        assert r.status_code == 422 and error_code(r) == 'invalid_value', bad
    bad_sev = {'VERY_HIGH': 1, 'HIGH': 0, 'MEDIUM': 0, 'LOW': 0, 'VERY_LOW': 0, 'INFORMATIONAL': 0, 'UNKNOWN': 0,
               'total': 5}
    r = flow.manual(cid, 1, 'sast.policy.open.by_severity', bad_sev)
    assert r.status_code == 422 and r.json()['error']['details'][0]['type'] == 'severity_total_mismatch'
    r = flow.manual(cid, 1, 'sast.policy.open.by_severity', {k: 0 for k in ('HIGH', 'total')})
    assert r.status_code == 422
    r = flow.manual(cid, 1, 'sast.policy.open.by_cwe', ['não', 'objeto'])
    assert r.status_code == 422
    r = flow.manual(cid, 1, 'nao.existe', 1)
    assert r.status_code == 404 and error_code(r) == 'metric_not_found'
    r = flow.manual(cid, 1, 'apps.total', 0)
    assert r.status_code == 200, r.text
    s = snap(r.json(), 'apps.total')
    assert s['origin'] == 'MANUAL' and s['value'] == 0 and s['value_state'] == 'MANUAL'
    assert s['source']['status'] == 'VALIDATED' and s['source']['value'] == 4  # Veracode preservada
    assert s['manual'] == {'justification': JUST, 'operator': OP, 'at': s['manual']['at']}
    change = r.json()['manual_changes'][-1]
    assert change['previous_value'] == 4 and change['new_value'] == 0 and change['previous_origin'] == 'VERACODE'
    # reverter volta exatamente ao valor da fonte e também fica registrado
    r = flow.api.post(f'/api/competences/{cid}/revisions/1/metrics/apps.total/revert',
                      json={'justification': JUST, 'operator': OP, 'expected_lock_version': flow.lock(cid, 1)})
    s = snap(r.json(), 'apps.total')
    assert s['origin'] == 'VERACODE' and s['value'] == 4 and len(r.json()['manual_changes']) == 2
    # métrica sem coleta (UNSUPPORTED) aceita valor manual de contagem
    r = flow.manual(cid, 1, 'licenses.usage', 37)
    s = snap(r.json(), 'licenses.usage')
    assert s['value'] == 37 and s['source']['status'] == 'UNSUPPORTED' and s['source']['value'] is None


def test_manual_change_requires_justification_and_declared_operator(flow):
    c = flow.owner()
    cid = flow.from_run(flow.env.run('client', c['id']))['competence_id']
    base = {'value': 3, 'operator': OP, 'expected_lock_version': flow.lock(cid, 1)}
    url = f'/api/competences/{cid}/revisions/1/metrics/apps.total'
    assert flow.api.put(url, json=base).status_code == 422
    assert flow.api.put(url, json={**base, 'justification': '   curta  '}).status_code == 422
    r = flow.api.put(url, json={'value': 3, 'justification': JUST, 'expected_lock_version': flow.lock(cid, 1)})
    assert r.status_code == 422
    r = flow.api.put(url, json={**base, 'justification': JUST, 'operator': ' '})
    assert r.status_code == 422
    r = flow.api.put(url, json={**base, 'justification': JUST, 'operator': 'x\u0000y'})
    assert r.status_code == 422
    assert snap(flow.detail(cid, 1), 'apps.total')['origin'] == 'VERACODE'


# ---------------------------------------------------------------- aprovação

def test_approval_requires_explicit_required_set_values_and_review_state(flow):
    c = flow.owner()
    cid = flow.from_run(flow.env.run('client', c['id']))['competence_id']
    r = flow.approve(cid, 1)
    assert r.status_code == 409 and error_code(r) == 'revision_not_in_review'
    flow.submit(cid, 1)
    r = flow.approve(cid, 1)
    assert r.status_code == 409 and error_code(r) == 'approval_blocked'
    assert {d['type'] for d in r.json()['error']['details']} == {'required_set_empty'}
    r = flow.api.post(f'/api/competences/{cid}/revisions/1/approve',
                      json={'approver': '', 'expected_lock_version': flow.lock(cid, 1)})
    assert r.status_code == 422  # aprovador obrigatório
    # devolve a rascunho, define obrigatórios (um deles INCOMPLETE) e tenta de novo
    r = flow.api.post(f'/api/competences/{cid}/revisions/1/return',
                      json={'operator': OP, 'reason': 'Faltou selecionar obrigatórios', 'expected_lock_version':
                            flow.lock(cid, 1)})
    assert r.status_code == 200 and r.json()['status'] == 'DRAFT'
    r = flow.api.put(f'/api/competences/{cid}/revisions/1/required',
                     json={'metric_ids': ['apps.total', 'nao.existe'], 'operator': OP,
                           'expected_lock_version': flow.lock(cid, 1)})
    assert r.status_code == 422 and error_code(r) == 'unknown_metric'
    d = flow.required(cid, 1, ['apps.total', 'sast.open.distinct', 'licenses.usage'])
    assert d['required_set_version'] == 1
    assert {(x['code'], x['metric_id']) for x in d['checks']} == {('missing_required', 'sast.open.distinct'),
                                                                  ('missing_required', 'licenses.usage')}
    flow.submit(cid, 1)
    r = flow.approve(cid, 1)
    assert r.status_code == 409 and error_code(r) == 'approval_blocked'
    assert {d['field'] for d in r.json()['error']['details']} == {'sast.open.distinct', 'licenses.usage'}
    # em revisão não se edita
    assert flow.manual(cid, 1, 'licenses.usage', 5).status_code == 409
    flow.api.post(f'/api/competences/{cid}/revisions/1/return',
                  json={'operator': OP, 'reason': 'Preencher valores manuais', 'expected_lock_version': flow.lock(cid, 1)})
    partial = snap(flow.detail(cid, 1), 'sast.open.distinct')['source']['partial']
    assert flow.manual(cid, 1, 'sast.open.distinct', partial,
                       justification='Distintos conferidos manualmente contra o dashboard').status_code == 200
    assert flow.manual(cid, 1, 'licenses.usage', 25).status_code == 200
    flow.submit(cid, 1)
    d = flow.approve_ok(cid, 1)  # aprovação com valores manuais válidos e justificados
    assert d['status'] == 'APPROVED' and d['is_official'] and not d['editable']
    assert d['approval']['approver'] == APPROVER and d['approval']['identity_mode'] == 'DECLARED_UNAUTHENTICATED'
    assert d['approval']['sequence'] == 1 and d['approval']['previous_chain_hash'] is None
    assert len(d['approval']['content_hash']) == 64


def test_approved_revision_is_immutable_and_repeated_collection_creates_new_revision(db_url):
    with metrics_env(db_url, settings=VeracodeSettings(page_size=50, max_retries=2, cache_ttl=0)) as env:
        _immutable_and_recollect(Flow(env))


def _immutable_and_recollect(flow):
    c = flow.owner()
    run, cid, n = approved_draft(flow, c)
    before = flow.detail(cid, 1)
    assert flow.manual(cid, 1, 'apps.total', 9).status_code == 409
    r = flow.api.post(f'/api/competences/{cid}/revisions/1/import-run',
                      json={'run_id': run['run_id'], 'operator': OP, 'expected_lock_version': before['lock_version']})
    assert r.status_code == 409 and error_code(r) == 'revision_not_draft'
    r = flow.api.post(f'/api/competences/{cid}/revisions/1/return',
                      json={'operator': OP, 'reason': 'Tentativa de reabrir aprovada', 'expected_lock_version':
                            before['lock_version']})
    assert r.status_code == 409
    # coleta repetida (dados da Veracode mudaram) vai para uma NOVA revisão; a aprovada não muda
    flow.env.tenant.applications[3]['profile']['business_unit'] = flow.env.tenant.applications[0]['profile'][
        'business_unit']
    flow.env.tenant.applications.pop(1)
    again = flow.from_run(flow.env.run('client', c['id']))
    assert again['revision'] == 2 and snap(again['detail'], 'apps.total')['value'] == 3
    assert flow.detail(cid, 1) == {**before, 'is_official': True}
    assert flow.api.get(f'/api/competences/{cid}/official').json()['number'] == 1  # 2 ainda não aprovada


def test_database_triggers_block_changes_to_approved_history(flow, db_url):
    c = flow.owner()
    cid = flow.from_run(flow.env.run('client', c['id']))['competence_id']
    assert flow.manual(cid, 1, 'licenses.usage', 3).status_code == 200  # para existir linha em manual_changes
    flow.required(cid, 1, ['apps.total'])
    flow.submit(cid, 1)
    flow.approve_ok(cid, 1)
    engine = db.make_engine(db_url)
    try:
        stmts = ["UPDATE metric_snapshots SET value_json = '99'",
                 'DELETE FROM metric_snapshots',
                 "UPDATE competence_revisions SET required_metrics_json = '[]'",
                 "UPDATE competence_revisions SET status = 'DRAFT'",
                 'DELETE FROM competence_revisions',
                 "UPDATE approvals SET approver = 'outro'",
                 'DELETE FROM approvals',
                 "UPDATE audit_events SET actor = 'outro'",
                 'DELETE FROM audit_events',
                 "UPDATE manual_changes SET justification = 'x'",
                 "UPDATE collection_runs SET input_hash = 'x'",
                 'DELETE FROM collection_runs',
                 'DELETE FROM competences',
                 "UPDATE competences SET label = '2026-08'"]
        for stmt in stmts:
            with pytest.raises(IntegrityError), engine.begin() as conn:
                conn.execute(text(stmt))
        # revisão nunca nasce aprovada; aprovação só para revisão APPROVED
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(text("INSERT INTO competence_revisions (id, competence_id, number, status, lock_version, "
                              "required_metrics_json, required_set_version, created_by, created_at, updated_at) "
                              "VALUES (:id, :c, 7, 'APPROVED', 1, '[]', 0, 'x', '2026-01-01', '2026-01-01')"),
                         {'id': uuid.uuid4().hex, 'c': uuid.UUID(cid).hex})
    finally:
        engine.dispose()
    assert flow.api.get(f'/api/competences/{cid}/integrity').json()['ok']


def test_later_revision_copies_exactly_and_keeps_old_versions_queryable(flow):
    c = flow.owner()
    _, cid, _ = approved_draft(flow, c, ids=('apps.total', 'sast.policy.open.by_severity'))
    v1 = flow.detail(cid, 1)
    r = flow.api.post(f'/api/competences/{cid}/revisions', json={'operator': OP})
    assert r.status_code == 201 and r.json()['number'] == 2 and r.json()['base_revision'] == 1
    assert flow.api.post(f'/api/competences/{cid}/revisions', json={'operator': OP}).status_code == 409
    v2 = r.json()
    assert [(s['metric_id'], s['row_hash'], s['value']) for s in v2['snapshots']] == \
        [(s['metric_id'], s['row_hash'], s['value']) for s in v1['snapshots']]
    assert v2['required_metrics'] == v1['required_metrics']
    assert flow.manual(cid, 2, 'apps.total', 5, justification='Correção posterior auditada').status_code == 200
    flow.submit(cid, 2)
    a2 = flow.approve_ok(cid, 2)['approval']
    a1 = flow.detail(cid, 1)['approval']
    assert a2['sequence'] == 2 and a2['previous_chain_hash'] == a1['chain_hash']
    comp = flow.api.get(f'/api/competences/{cid}').json()
    assert comp['official_revision'] == 2 and [r['status'] for r in comp['revisions']] == ['APPROVED', 'APPROVED']
    assert snap(flow.detail(cid, 1), 'apps.total')['value'] == 4  # versão antiga intacta
    diff = flow.api.get(f'/api/competences/{cid}/compare?a=1&b=2').json()
    changed = [i for i in diff['items'] if i['changed']]
    assert [i['metric_id'] for i in changed] == ['apps.total'] and changed[0]['b']['origin'] == 'MANUAL'
    integ = flow.api.get(f'/api/competences/{cid}/integrity').json()
    assert integ['ok'] and integ['approvals'] == 2


# ---------------------------------------------------------------- integridade e auditoria

def test_tampering_is_detected_and_blocks_approval(flow, db_url):
    c = flow.owner()
    cid = flow.from_run(flow.env.run('client', c['id']))['competence_id']
    flow.required(cid, 1, ['apps.total'])
    engine = db.make_engine(db_url)
    try:
        with engine.begin() as conn:  # adulteração direta no banco (fora da aplicação) de um rascunho
            conn.execute(text("UPDATE metric_snapshots SET value_json = '400' WHERE metric_id = 'apps.total'"))
    finally:
        engine.dispose()
    integ = flow.api.get(f'/api/competences/{cid}/integrity').json()
    assert not integ['ok'] and integ['revisions'][0]['snapshot_hash_mismatches'] == ['apps.total']
    flow.submit(cid, 1)
    r = flow.approve(cid, 1)
    assert r.status_code == 409 and {d['type'] for d in r.json()['error']['details']} == {'integrity_violation'}


def test_audit_chain_records_lifecycle_and_detects_tampering(flow, db_url):
    c = flow.owner()
    run, cid, _ = approved_draft(flow, c)
    events = flow.api.get(f'/api/competences/{cid}/audit').json()['items']
    assert [e['event_type'] for e in events] == ['competence.created', 'revision.created', 'run.imported',
                                                 'required_set.updated', 'revision.submitted', 'revision.approved']
    assert events[2]['details']['run_id'] == run['run_id'] and events[0]['actor'] == OP
    assert events[-1]['actor'] == APPROVER and events[-1]['details']['identity_mode'] == 'DECLARED_UNAUTHENTICATED'
    assert flow.api.get(f'/api/competences/{cid}/integrity').json()['audit_chain']['ok']
    engine = db.make_engine(db_url)
    try:
        with engine.begin() as conn:  # simula adulteração com o gatilho removido
            conn.execute(text('DROP TRIGGER trg_audit_events_no_update'))
            conn.execute(text("UPDATE audit_events SET actor = 'Outra pessoa' WHERE event_type = 'revision.approved'"))
    finally:
        engine.dispose()
    integ = flow.api.get(f'/api/competences/{cid}/integrity').json()
    assert not integ['ok'] and not integ['audit_chain']['ok']


# ---------------------------------------------------------------- concorrência

def test_stale_lock_version_is_conflict_not_overwrite(flow):
    c = flow.owner()
    cid = flow.from_run(flow.env.run('client', c['id']))['competence_id']
    stale = flow.lock(cid, 1)
    assert flow.manual(cid, 1, 'apps.total', 7, lock=stale).status_code == 200
    r = flow.manual(cid, 1, 'apps.total', 8, lock=stale)
    assert r.status_code == 409 and error_code(r) == 'revision_conflict'
    assert snap(flow.detail(cid, 1), 'apps.total')['value'] == 7
    r = flow.api.post(f'/api/competences/{cid}/revisions/1/submit', json={'operator': OP, 'expected_lock_version': stale})
    assert r.status_code == 409


def test_concurrent_writers_get_exactly_one_success(flow):
    c = flow.owner()
    cid = flow.from_run(flow.env.run('client', c['id']))['competence_id']
    lock = flow.lock(cid, 1)
    results, barrier = [], threading.Barrier(4)

    def write(v):
        barrier.wait()
        results.append(flow.manual(cid, 1, 'apps.total', v, lock=lock).status_code)

    threads = [threading.Thread(target=write, args=(v,)) for v in (10, 11, 12, 13)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [200, 409, 409, 409]
    d = flow.detail(cid, 1)
    assert d['lock_version'] == lock + 1 and len(d['manual_changes']) == 1
    assert snap(d, 'apps.total')['value'] == d['manual_changes'][0]['new_value']


# ---------------------------------------------------------------- integridade referencial e segredos

def test_referential_integrity_of_history(flow, db_url):
    c = flow.owner()
    _, cid, _ = approved_draft(flow, c)
    assert flow.api.patch(f'/api/clients/{c["id"]}', json={'is_active': False}).status_code == 200
    r = flow.api.delete(f'/api/clients/{c["id"]}')
    assert r.status_code == 409 and error_code(r) == 'reference_conflict'
    engine = db.make_engine(db_url)
    try:
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(text("INSERT INTO competences (id, client_id, subclient_id, owner_key, label, timezone, "
                              "created_at, updated_at) VALUES (:id, :c, NULL, 'client:x', '2026-01', 'UTC', "
                              "'2026-01-01', '2026-01-01')"), {'id': uuid.uuid4().hex, 'c': uuid.uuid4().hex})
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(text("INSERT INTO manual_changes (id, snapshot_id, revision_id, metric_id, new_origin, "
                              "justification, operator, changed_at) VALUES (:id, :s, :r, 'm', 'MANUAL', 'j', 'o', "
                              "'2026-01-01')"), {'id': uuid.uuid4().hex, 's': uuid.uuid4().hex,
                                                 'r': uuid.uuid4().hex})
    finally:
        engine.dispose()
    assert flow.api.get(f'/api/competences/{cid}').status_code == 200


def test_snapshot_tables_never_store_credentials(flow, db_url):
    c = flow.owner()
    approved_draft(flow, c)
    api_id, api_key = synthetic_credentials('gamma')
    engine = db.make_engine(db_url)
    try:
        dump = []
        with engine.connect() as conn:
            for table in ('competences', 'competence_revisions', 'metric_snapshots', 'manual_changes', 'approvals',
                          'audit_events', 'collection_runs'):
                dump += [json.dumps([str(v) for v in row]) for row in conn.execute(text(f'SELECT * FROM {table}'))]
    finally:
        engine.dispose()
    blob = '\n'.join(dump)
    assert blob and 'apps.total' in blob
    for secret in (api_id, api_key, 'credential_ref', 'Authorization', 'VERACODE-HMAC'):
        assert secret not in blob
    d = flow.detail(flow.api.get(f'/api/competences?owner_kind=client&owner_id={c["id"]}').json()['items'][0]['id'], 1)
    # conexão só por id/nome/região/origem — nunca a referência de credencial (env:NOME)
    assert set(snap(d, 'apps.total')['provenance']['connection']) == {'connection_source', 'id', 'name', 'region'}


# ---------------------------------------------------------------- fluxo completo (E2E da API)

def test_end_to_end_collect_draft_manual_approve_history(flow):
    c = flow.owner()
    run_aug = flow.env.run('client', c['id'], competence='2026-08')
    aug = flow.from_run(run_aug)
    flow.required(aug['competence_id'], 1, ['apps.total', 'licenses.usage'])
    flow.manual(aug['competence_id'], 1, 'licenses.usage', 20)
    flow.submit(aug['competence_id'], 1)
    flow.approve_ok(aug['competence_id'], 1)
    sep = flow.from_run(flow.env.run('client', c['id']))
    flow.required(sep['competence_id'], 1, ['apps.total', 'licenses.usage'])
    flow.manual(sep['competence_id'], 1, 'licenses.usage', 23)
    flow.submit(sep['competence_id'], 1)
    flow.approve_ok(sep['competence_id'], 1)
    cmp_ = flow.api.get(f'/api/history/client/{c["id"]}/compare?competence=2026-09&metric_id=licenses.usage'
                        '&metric_id=apps.total').json()
    by = {i['metric_id']: i for i in cmp_['items']}
    assert by['licenses.usage']['current']['value'] == 23 and by['licenses.usage']['previous']['value'] == 20
    assert by['licenses.usage']['delta'] == 3 and by['apps.total']['delta'] == 0
    s = flow.api.get(f'/api/history/client/{c["id"]}/series?metric_id=licenses.usage&start=2026-07&end=2026-09').json()
    assert [(p['competence'], p['state'], p['value']) for p in s['points']] == \
        [('2026-07', 'GAP', None), ('2026-08', 'APPROVED', 20), ('2026-09', 'APPROVED', 23)]
    assert s['gaps'] == ['2026-07'] and s['interpolation'] == 'none'
