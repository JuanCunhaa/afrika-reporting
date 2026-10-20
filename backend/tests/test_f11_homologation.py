"""F11 — homologação de métricas e piloto assistido (dados SINTÉTICOS; nenhuma chamada real).

Cobre: definições oficiais/prioridades da conferência, diagnóstico automático de divergência (ordem do PO §4),
CSV na ordem de prioridade, backup automático e verificado ANTES de aprovar (falha bloqueia a aprovação) e a
equivalência semântica da versão 1 dos contratos SCA após a correção da F10 (coleta sem `issue_id`).
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app import backup, db
from app.metrics import engine
from app.metrics.contracts import Dedup, IdentityProof
from app.metrics.registry import REGISTRY
from app.reconciliation import diagnostics, guide, official
from app.veracode import adapters
from app.veracode.credentials import Credentials
from app.veracode.fixtures import make_finding, synthetic_credentials
from app.veracode.http import CollectionRun, VeracodeHttpPool
from app.veracode.settings import VeracodeSettings
from conftest import error_code
from test_f10_conference import base, draft, post, row, sheet
from test_snapshots import flow  # noqa: F401 (fixture)

APPLICABLE = {m for m, g in guide.GUIDES.items() if g.category is guide.Category.APPLICABLE}


# ---------------------------------------------------------------- definições oficiais e prioridades

def test_official_covers_exactly_the_21_applicable_with_po_priorities():
    assert len(APPLICABLE) == 21 and set(official.OFFICIAL) == APPLICABLE
    by_priority: dict[int, set[str]] = {}
    for mid, o in official.OFFICIAL.items():
        if o.priority is not None:
            by_priority.setdefault(o.priority, set()).add(mid)
    assert by_priority == {
        1: {'apps.total'}, 2: {'apps.by_business_unit', 'apps.by_team'}, 3: {'apps.by_policy_compliance'},
        4: {'sast.policy.open.by_severity'}, 5: {'sast.sandbox.open.by_severity'},
        6: {'sca.policy.open.by_severity'}, 7: {'sca.sandbox.open.by_severity'}, 8: {'apps.loc.total'}}
    # prioridade 9 (aplicações com scans) não tem indicador aplicável: lacuna declarada, não um indicador inventado
    assert set(official.PRIORITIES) == set(range(1, 10)) and 9 not in by_priority and official.PRIORITY_GAPS[9]
    assert guide.GUIDES['scans.covered_apps'].category is guide.Category.NOT_APPLICABLE


def test_official_definitions_are_sourced_never_presumed():
    for mid, o in official.OFFICIAL.items():
        assert all(d.startswith('https://docs.veracode.com/') for d in o.docs), mid
        if o.definition:
            assert o.docs, f'{mid}: definição sem referência documental'
    # LOC não é definido pela documentação consultada: fica vazio e a planilha diz isso
    assert official.public('apps.loc.total')['definition_documented'] is False
    assert official.public('apps.total')['priority_label'] == 'Total de aplicações'
    assert official.public('scans.count') is None


# ---------------------------------------------------------------- planilha: prioridades e diagnóstico

def test_sheet_has_priorities_official_and_diagnostics(flow):
    cid, n = draft(flow)
    data = sheet(flow, cid, n)
    pr = {p['priority']: p for p in data['priorities']}
    assert set(pr) == set(range(1, 10)) and all(p['homologated'] == 0 for p in pr.values())
    assert pr[9]['metric_ids'] == [] and pr[9]['gap']
    assert pr[4]['metric_ids'] == ['sast.policy.open.by_severity'] and pr[4]['comparisons'] == ['NOT_VERIFIED']
    for m in data['metrics']:
        if m['metric_id'] in APPLICABLE:
            assert [c['code'] for c in m['diagnostics']] == [c for c, _ in diagnostics.CHECKS], m['metric_id']
            assert m['official'] is not None and not m['needs_investigation']
        else:
            assert m['diagnostics'] == [] and m['official'] is None
    sast = row(data, 'sast.policy.open.by_severity')
    checks = {c['code']: c for c in sast['diagnostics']}
    assert checks['completeness']['status'] == 'OK' and 'contextos completos' in checks['completeness']['detail']
    assert checks['context']['status'] == 'INFO' and 'Policy' in checks['context']['detail']
    assert checks['identity']['status'] == 'OK' and checks['origin']['status'] == 'OK'
    sca = {c['code']: c for c in row(data, 'sca.policy.open.by_severity')['diagnostics']}
    assert sca['identity']['status'] == 'INFO' and 'issue_id' in sca['identity']['detail']
    apps = {c['code']: c for c in row(data, 'apps.total')['diagnostics']}
    assert apps['severity']['status'] == 'NOT_APPLICABLE' and apps['status']['status'] == 'NOT_APPLICABLE'


def test_divergence_is_flagged_for_investigation_with_period_check(flow):
    cid, n = draft(flow)
    data = sheet(flow, cid, n)
    computed = {x['key']: x['computed'] for x in row(data, 'apps.total')['lines']}
    assert post(flow, cid, n, 'apps.total', {'value': computed['value'] + 1}).status_code == 201
    r = post(flow, cid, n, 'sast.policy.open.by_severity',
             {x['key']: x['computed'] for x in row(data, 'sast.policy.open.by_severity')['lines']},
             checked_on='2026-01-02')
    assert r.status_code == 201
    after = sheet(flow, cid, n)
    mism = row(after, 'apps.total')
    assert mism['comparison'] == 'MISMATCH' and mism['needs_investigation']
    nc = row(after, 'sast.policy.open.by_severity')
    assert nc['comparison'] == 'NOT_COMPARABLE' and nc['needs_investigation']
    assert 'period' in nc['diagnosis']['attention']
    # conferir/diagnosticar nunca muda o snapshot
    assert flow.detail(cid, n)['status'] == 'DRAFT'


def _snap(**kw):
    defaults = dict(provenance_json=json.dumps({'coverage': {'applications': 3, 'contexts_expected': 3,
                                                             'contexts_complete': 3}, 'scan_type': 'STATIC'}),
                    source_reasons_json='[]', scope_refs_json='[]', source_status='VALIDATED', origin='VERACODE')
    return SimpleNamespace(**{**defaults, **kw})


COMP = SimpleNamespace(label='2026-09', timezone='America/Sao_Paulo', owner_key='client:x')


@pytest.mark.parametrize('metric_id, snap_kw, code', [
    ('sast.policy.open.by_severity', {'source_status': 'INCOMPLETE'}, 'completeness'),
    ('sast.policy.open.by_severity', {'provenance_json': json.dumps(
        {'coverage': {'applications': 3, 'contexts_expected': 3, 'contexts_complete': 2}})}, 'completeness'),
    ('sast.sandbox.open.by_severity', {'provenance_json': json.dumps(
        {'coverage': {'applications': 3, 'sandbox_listings_failed': 1}})}, 'context'),
    ('sast.policy.open.by_severity', {'source_reasons_json': json.dumps([{'code': 'severity_missing'}])},
     'severity'),
    ('apps.by_team', {'provenance_json': json.dumps({'coverage': {'applications': 3, 'undetermined': 2}})},
     'classification'),
    ('apps.total', {'origin': 'MANUAL'}, 'origin'),
    ('apps.total', {'provenance_json': '{}'}, 'universe'),
    ('sast.open.distinct', {}, 'identity'),
])
def test_diagnosis_flags_each_documented_cause(metric_id, snap_kw, code):
    checks = diagnostics.diagnose(COMP, REGISTRY[metric_id], _snap(**snap_kw), '2026-10-01', None)
    assert code in diagnostics.summary(checks)['attention'], checks


def test_diagnosis_clean_snapshot_has_no_attention():
    for mid in APPLICABLE:
        checks = diagnostics.diagnose(COMP, REGISTRY[mid], _snap(), '2026-10-01', {'checked_on': '2026-10-01'})
        assert diagnostics.summary(checks)['attention'] == [], (mid, checks)


def test_csv_follows_priority_order_with_official_columns(flow):
    cid, n = draft(flow)
    body = flow.api.get(f'{base(cid, n)}.csv').content.decode('utf-8-sig')
    header, *lines = body.strip().split('\n')
    cols = header.split(';')
    assert cols[-5:] == ['prioridade', 'definicao_oficial', 'local_analytics', 'diferencas_conhecidas',
                         'diagnostico_atencao']
    order = []
    for line in lines:
        mid = line.split(';')[2]
        if not order or order[-1] != mid:
            order.append(mid)
    assert order[:9] == ['apps.total', 'apps.by_business_unit', 'apps.by_team', 'apps.by_policy_compliance',
                         'sast.policy.open.by_severity', 'sast.sandbox.open.by_severity',
                         'sca.policy.open.by_severity', 'sca.sandbox.open.by_severity', 'apps.loc.total']
    assert set(order[-3:]) == {'apps.scanned', 'sast.policy.resolved_in_period', 'scans.count'} and len(order) == 36


# ---------------------------------------------------------------- backup automático antes da aprovação

def _ready(flow):
    c = flow.owner()
    out = flow.from_run(flow.env.run('client', c['id']))
    cid, n = out['competence_id'], out['revision']
    flow.required(cid, n, ['apps.total'])
    flow.submit(cid, n)
    return cid, n


def _events(flow, cid, kind):
    return [e for e in flow.api.get(f'/api/competences/{cid}/audit').json()['items'] if e['event_type'] == kind]


def test_approval_makes_verified_backup_of_pre_approval_state(flow, tmp_path):
    out_dir = tmp_path / 'bk'
    flow.api.app.state.backup_dir = out_dir
    cid, n = _ready(flow)
    r = flow.approve(cid, n)
    assert r.status_code == 200, r.text
    made = r.json()['approval_backup']
    assert made['integrity'] == 'ok' and made['alembic_revision'] == db.head_revision()
    assert '/' not in made['file'] and '\\' not in made['file']  # só o nome, sem caminho local
    file = out_dir / made['file']
    info = backup.inspect(file)
    assert info.sha256 == made['sha256'] and file.with_suffix('.json').is_file()
    con = sqlite3.connect(f'file:{file.as_posix()}?mode=ro', uri=True)
    try:  # cópia consistente do estado ANTERIOR à aprovação
        assert con.execute('SELECT COUNT(*) FROM approvals').fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM competence_revisions WHERE status='READY_FOR_REVIEW'"
                           ).fetchone()[0] == 1
    finally:
        con.close()
    approved = _events(flow, cid, 'revision.approved')
    assert approved and approved[-1]['details']['backup']['sha256'] == made['sha256']
    assert flow.api.get(f'/api/competences/{cid}/integrity').json()['ok']


def test_backup_failure_blocks_approval_and_manual_backup_still_works(flow, tmp_path):
    cid, n = _ready(flow)
    flow.api.app.state.backup_dir = db.REPO_ROOT / 'docs'  # área versionada: o backup é recusado
    r = flow.approve(cid, n)
    assert r.status_code == 409 and error_code(r) == 'approval_backup_failed'
    assert 'backup-db' in r.json()['error']['message']
    assert flow.detail(cid, n)['status'] == 'READY_FOR_REVIEW'
    assert _events(flow, cid, 'revision.approved') == []
    assert _events(flow, cid, 'approval.blocked')[-1]['details']['codes'] == ['backup_failed']
    assert not list((db.REPO_ROOT / 'docs').glob('afrika-reporting-*.sqlite3'))
    # backup manual (CLI/módulo) continua disponível; corrigido o destino, a aprovação passa
    manual = backup.backup(flow.api.app.state.db_url, tmp_path / 'manual')
    assert manual.integrity == 'ok'
    flow.api.app.state.backup_dir = tmp_path / 'ok'
    assert flow.approve(cid, n).status_code == 200


def test_io_error_during_backup_blocks_approval(flow, tmp_path, monkeypatch):
    cid, n = _ready(flow)
    flow.api.app.state.backup_dir = tmp_path / 'bk'

    def broken(*_a, **_k):
        raise OSError('disco cheio (sintético)')
    monkeypatch.setattr(backup, '_copy', broken)
    r = flow.approve(cid, n)
    assert r.status_code == 409 and error_code(r) == 'approval_backup_failed'
    assert 'OSError' in r.json()['error']['message']
    assert flow.detail(cid, n)['status'] == 'READY_FOR_REVIEW'


def test_default_backup_dir_rules(tmp_path):
    url = f'sqlite:///{(tmp_path / "x.sqlite3").as_posix()}'
    assert backup.default_dir(url, {}) == tmp_path / 'backups'
    assert backup.default_dir(url, {backup.BACKUP_DIR_ENV: str(tmp_path / 'y')}) == tmp_path / 'y'
    assert backup.default_dir(f'sqlite:///{db.DEFAULT_DB_PATH.as_posix()}', {}) == backup.BACKUP_DIR


# ---------------------------------------------------------------- SCA: versão 1 com semântica idêntica

CREDS = Credentials(*synthetic_credentials('f11-sca'))
APP = '00000000-0000-4000-8000-0000000000b1'


def _collect(items, id_field):
    def handle(request: httpx.Request) -> httpx.Response:
        page, size = int(request.url.params['page']), int(request.url.params['size'])
        total = len(items)
        body = {'page': {'size': size, 'number': page, 'total_elements': total,
                         'total_pages': (total + size - 1) // size}}
        chunk = items[page * size:(page + 1) * size]
        if chunk:
            body['_embedded'] = {'findings': chunk}
        return httpx.Response(200, json=body)

    async def main():
        pool = VeracodeHttpPool(VeracodeSettings(max_retries=0), httpx.MockTransport(handle))
        try:
            run = CollectionRun(pool, CREDS, 'commercial')
            return await run.paginate(adapters.FINDINGS.format(guid=APP), 'findings', label='f11', params={},
                                      id_field=id_field, page_size=50)
        finally:
            await pool.aclose()
    return asyncio.run(main())


@pytest.mark.parametrize('n', [0, 1, 50, 51, 137])
def test_sca_v1_semantics_identical_with_and_without_issue_id(n):
    """Mesmo conjunto de findings (únicos): a regra antiga (identificador por item) e a nova (total anunciado) aceitam
    a coleta e produzem o MESMO valor por severidade => contrato SCA mantém `version` 1."""
    unique = [make_finding(i, 'SCA', severity=i % 6, status='OPEN' if i % 4 else 'CLOSED', component=f'c{i % 5}',
                           vulnerability=f'SYNTH-{i}') for i in range(n)]
    with_id = [{**f, 'issue_id': f['_order']} for f in unique]  # formato presumido até a F09
    old, new = _collect(with_id, 'issue_id'), _collect(unique, None)
    assert old.complete and new.complete and len(old.items) == len(new.items) == n

    def by_sev(items):
        acc = engine.empty_severity()
        for f in map(adapters.normalize_finding, items):
            if engine._open(f):  # mesmo critério de aberto do motor
                engine._add_severity(acc, f.get('severity'))
        return acc
    assert by_sev(old.items) == by_sev(new.items)
    for mid in ('sca.policy.open.by_severity', 'sca.sandbox.open.by_severity', 'sca.policy.open.top_components',
                'sca.policy.open.top_vulnerabilities', 'sca.policy.open.by_dependency_mode'):
        c = REGISTRY[mid]
        assert c.version == 1 and c.dedup == Dedup.NONE and c.identity_proof == IdentityProof.NOT_REQUIRED, mid


def test_sca_incomplete_is_never_zero():
    col = _collect([], None)
    assert col.complete and col.items == []  # zero comprovado pela paginação (total_elements = 0)

    def short(request):
        return httpx.Response(200, json={'page': {'size': 50, 'number': 0, 'total_elements': 3, 'total_pages': 1}})

    async def main():
        pool = VeracodeHttpPool(VeracodeSettings(max_retries=0), httpx.MockTransport(short))
        try:
            return await CollectionRun(pool, CREDS, 'commercial').paginate(
                adapters.FINDINGS.format(guid=APP), 'findings', label='f11', params={}, id_field=None, page_size=50)
        finally:
            await pool.aclose()
    col = asyncio.run(main())
    assert not col.complete and col.error.code == 'inconsistent_pagination'


def test_no_real_backup_or_value_written_to_repo():
    tracked_like = [p for p in (db.REPO_ROOT / 'docs').glob('*') if p.suffix in ('.sqlite3', '.db')]
    assert tracked_like == []
    assert Path(backup.BACKUP_DIR).relative_to(db.REPO_ROOT).parts[0] == 'data'
