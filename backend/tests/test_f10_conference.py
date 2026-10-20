"""F10 — conferência humana dos indicadores com a plataforma Veracode (dados SINTÉTICOS).

O operador informa só o valor oficial; o servidor lê o calculado do snapshot, calcula Δ e status, registra de forma
append-only e nunca altera snapshot/aprovação. Categorias APPLICABLE / NOT_APPLICABLE / BLOCKED_EXTERNAL separadas.
"""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import db
from app.metrics.registry import REGISTRY
from app.reconciliation import guide, service
from conftest import error_code
from test_snapshots import OP, Flow, approved_draft, snap  # noqa: F401 (fixture `flow`)
from test_snapshots import flow  # noqa: F401

CHECKER = 'Conferente Sintética'


def base(cid, n):
    return f'/api/competences/{cid}/revisions/{n}/conference'


def sheet(flow, cid, n):
    r = flow.api.get(base(cid, n))
    assert r.status_code == 200, r.text
    return r.json()


def row(data, metric_id):
    return next(m for m in data['metrics'] if m['metric_id'] == metric_id)


def draft(flow):
    c = flow.owner()
    out = flow.from_run(flow.env.run('client', c['id']))
    return out['competence_id'], out['revision']


def post(flow, cid, n, metric_id, official, *, checked_on=None, filters=True, note=None, **extra):
    data = sheet(flow, cid, n)
    day = checked_on or row(data, metric_id)['snapshot']['collected_on']
    body = {'operator': CHECKER, 'checked_on': day, 'filters_confirmed': filters, 'official': official,
            'evidence': 'Captura local em private/conferencia (sintética)', **extra}
    if note:
        body['not_comparable_note'] = note
    return flow.api.post(f'{base(cid, n)}/{metric_id}', json=body)


def computed(data, metric_id):
    return {line['key']: line['computed'] for line in row(data, metric_id)['lines']}


def test_guide_covers_catalog_with_separate_categories():
    cats = {}
    for mid, g in guide.GUIDES.items():
        cats.setdefault(g.category.value, []).append(mid)
        if g.category is guide.Category.APPLICABLE:
            assert g.path and g.filters, mid
        else:
            assert g.reason, mid
    assert set(guide.GUIDES) == set(REGISTRY)
    # F12: + apps.scanned (BLOCKED_EXTERNAL: relatório SCANS da Reporting API)
    assert {k: len(v) for k, v in cats.items()} == {'APPLICABLE': 21, 'NOT_APPLICABLE': 12, 'BLOCKED_EXTERNAL': 3}
    assert sorted(cats['BLOCKED_EXTERNAL']) == ['apps.scanned', 'sast.policy.resolved_in_period', 'scans.count']


def test_sheet_starts_not_verified_and_nothing_is_homologated(flow):
    cid, n = draft(flow)
    data = sheet(flow, cid, n)
    assert len(data['metrics']) == len(REGISTRY) and data['identity_mode'] == 'DECLARED_UNAUTHENTICATED'
    s = data['summary']
    assert s['HOMOLOGATED'] == 0 and s['APPLICABLE'] == 21
    assert s['NOT_APPLICABLE'] == 12 and s['BLOCKED_EXTERNAL'] == 3  # F12: + apps.scanned
    assert s.get('NOT_VERIFIED', 0) + s.get('NO_COMPUTED_VALUE', 0) == 21
    total = row(data, 'apps.total')
    assert total['comparison'] == 'NOT_VERIFIED' and total['lines'] == [{'key': 'value', 'label': 'Valor',
                                                                        'computed': 4}]
    assert total['same_day_required'] and total['guide']['path_is_indicative']
    sev = row(data, 'sast.policy.open.by_severity')
    assert [line['key'] for line in sev['lines']] == ['VERY_HIGH', 'HIGH', 'MEDIUM', 'LOW', 'VERY_LOW',
                                                      'INFORMATIONAL', 'total']
    # F10: com o formato real (SCA sem issue_id) a coleta SCA sintética fica completa e o valor existe.
    assert row(data, 'sca.policy.open.by_severity')['snapshot']['value_state'] == 'VALIDATED'
    assert row(data, 'sast.open.distinct')['comparison'] == 'NOT_APPLICABLE'
    assert row(data, 'scans.count')['comparison'] == 'BLOCKED_EXTERNAL'


def test_match_mismatch_and_difference_are_computed_by_server(flow):
    cid, n = draft(flow)
    lock = flow.lock(cid, n)
    before = snap(flow.detail(cid, n), 'apps.total')['row_hash']
    r = post(flow, cid, n, 'apps.total', {'value': 4})
    assert r.status_code == 201, r.text
    out = r.json()
    assert out['comparison'] == 'MATCH' and out['homologated'] is True
    e = out['conference']['entries'][0]
    assert (e['computed'], e['official'], e['difference'], e['difference_pct']) == (4, 4, 0, 0.0)
    assert out['conference']['sequence'] == 1 and out['conference']['operator'] == CHECKER
    # conferir não muda snapshot nem a revisão
    assert snap(flow.detail(cid, n), 'apps.total')['row_hash'] == before and flow.lock(cid, n) == lock

    data = sheet(flow, cid, n)
    sev = computed(data, 'sast.policy.open.by_severity')
    official = {**sev, 'HIGH': sev['HIGH'] + 2, 'total': sev['total'] + 2}
    out = post(flow, cid, n, 'sast.policy.open.by_severity', official).json()
    assert out['comparison'] == 'MISMATCH' and not out['homologated']
    by_key = {x['key']: x for x in out['conference']['entries']}
    assert by_key['HIGH']['difference'] == -2 and by_key['VERY_HIGH']['difference'] == 0
    assert by_key['total']['difference_pct'] == round(-2 / (sev['total'] + 2) * 100, 2)
    assert sheet(flow, cid, n)['summary']['HOMOLOGATED'] == 1


@pytest.mark.parametrize('case,reason', [
    ('date', 'current_state_date_mismatch'), ('filters', 'filters_not_confirmed'),
    ('partial', 'entry_incomplete'), ('note', 'declared_not_comparable')])
def test_not_comparable_cases_never_count_as_homologated(flow, case, reason):
    cid, n = draft(flow)
    sev = computed(sheet(flow, cid, n), 'sast.policy.open.by_severity')
    kw = {}
    if case == 'date':
        kw['checked_on'] = '2026-10-01'
    elif case == 'filters':
        kw['filters'] = False
    elif case == 'partial':
        sev.pop('INFORMATIONAL')
    else:
        kw['note'] = 'O portal agrupa por categoria, não por severidade'
    out = post(flow, cid, n, 'sast.policy.open.by_severity', sev, **kw)
    assert out.status_code == 201, out.text
    out = out.json()
    assert out['comparison'] == 'NOT_COMPARABLE' and reason in out['conference']['reasons']
    assert not out['homologated']


def test_refusals_and_validation(flow):
    cid, n = draft(flow)
    r = post(flow, cid, n, 'sast.open.distinct', {'total': 1})
    assert r.status_code == 409 and error_code(r) == 'conference_not_applicable'
    r = post(flow, cid, n, 'scans.count', {'value': 1})
    assert r.status_code == 409 and error_code(r) == 'conference_blocked_external'
    assert post(flow, cid, n, 'apps.inexistente', {'value': 1}, checked_on='2026-10-01').status_code == 404
    assert error_code(post(flow, cid, n, 'apps.total', {'outra': 1})) == 'unknown_line'
    assert error_code(post(flow, cid, n, 'apps.total', {'value': -1})) == 'invalid_official_value'
    future = (dt.date.today() + dt.timedelta(days=3)).isoformat()
    assert error_code(post(flow, cid, n, 'apps.total', {'value': 4}, checked_on=future)) == 'checked_on_in_future'
    # o cliente NÃO pode enviar o valor calculado
    assert post(flow, cid, n, 'apps.total', {'value': 4}, computed={'value': 99}).status_code == 422
    # indicador aplicável sem valor efetivo: nada a conferir
    rows = {m['metric_id']: m for m in sheet(flow, cid, n)['metrics']}
    empty = [m for m, x in rows.items() if x['comparison'] == 'NO_COMPUTED_VALUE']
    for mid in empty:
        r = post(flow, cid, n, mid, {})
        assert r.status_code == 409 and error_code(r) == 'no_computed_value'


def test_append_only_history_stale_after_manual_change_and_triggers(flow, db_url):
    cid, n = draft(flow)
    assert post(flow, cid, n, 'apps.total', {'value': 5}).json()['comparison'] == 'MISMATCH'
    assert post(flow, cid, n, 'apps.total', {'value': 4}).json()['comparison'] == 'MATCH'
    hist = flow.api.get(f'{base(cid, n)}/apps.total/history').json()
    assert [(h['sequence'], h['status']) for h in hist] == [(1, 'MISMATCH'), (2, 'MATCH')]
    # valor manual no rascunho => conferência anterior desatualizada (volta a NOT_VERIFIED)
    r = flow.manual(cid, n, 'apps.total', 7)
    assert r.status_code == 200, r.text
    total = row(sheet(flow, cid, n), 'apps.total')
    assert total['comparison'] == 'NOT_VERIFIED' and total['conference']['stale']
    # manual conferido e igual: MATCH, mas NÃO homologa o cálculo (origem MANUAL)
    out = post(flow, cid, n, 'apps.total', {'value': 7}).json()
    assert out['comparison'] == 'MATCH' and out['homologated'] is False
    engine = db.make_engine(db_url)
    try:
        for sql in ('UPDATE metric_conferences SET status = \'MATCH\'', 'DELETE FROM metric_conferences'):
            with engine.begin() as conn, pytest.raises(IntegrityError, match='metric_conferences_append_only'):
                conn.execute(text(sql))
        with engine.connect() as conn:
            details = [r[0] for r in conn.execute(text(
                "SELECT details_json FROM audit_events WHERE event_type = 'conference.recorded'"))]
    finally:
        engine.dispose()
    assert len(details) == 3 and all('"value"' not in d and 'official' not in d for d in details)


def test_conference_on_approved_revision_keeps_approval_intact(flow):
    c = flow.owner()
    _, cid, n = approved_draft(flow, c)
    before = flow.api.get(f'/api/competences/{cid}/integrity').json()
    assert post(flow, cid, n, 'apps.total', {'value': 4}).json()['comparison'] == 'MATCH'
    after = flow.api.get(f'/api/competences/{cid}/integrity').json()
    assert after['ok'] and before['ok']
    assert flow.detail(cid, n)['approval'] == flow.detail(cid, n)['approval']
    assert flow.detail(cid, n)['status'] == 'APPROVED'


def test_csv_export_is_local_evidence_without_formulas(flow):
    cid, n = draft(flow)
    post(flow, cid, n, 'apps.total', {'value': 4})
    r = flow.api.get(f'{base(cid, n)}.csv')
    assert r.status_code == 200 and r.headers['cache-control'] == 'no-store'
    assert r.headers['x-content-type-options'] == 'nosniff' and 'attachment' in r.headers['content-disposition']
    body = r.content.decode('utf-8-sig')
    header, *lines = body.strip().split('\n')
    assert header.startswith('competencia;revisao;metric_id')
    assert any(';apps.total;' in x and ';MATCH;sim;' in x for x in lines)
    assert any(';scans.count;' in x and 'BLOCKED_EXTERNAL' in x for x in lines)
    assert service._cell('=HYPERLINK("x")') == '\'=HYPERLINK("x")' and service._cell('-3') == "'-3"
