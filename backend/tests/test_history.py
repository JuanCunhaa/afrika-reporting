"""F05 — séries históricas e comparação mês a mês: só snapshots aprovados, lacunas explícitas, sem interpolação."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.snapshots import history
from app.veracode.settings import VeracodeSettings
from conftest import error_code
from test_metrics import metrics_env
from test_snapshots import OP, Flow


def approve_manual(flow: Flow, owner_id: str, label: str, value: int, *, kind='client', metric='licenses.usage'):
    comp = flow.competence(owner_id, label, kind=kind)
    cid = comp['id']
    flow.required(cid, 1, [metric])
    assert flow.manual(cid, 1, metric, value, justification=f'Histórico informado manualmente {label}').status_code \
        == 200
    flow.submit(cid, 1)
    flow.approve_ok(cid, 1)
    return cid


@pytest.fixture
def flow(db_url):
    with metrics_env(db_url, settings=VeracodeSettings(page_size=50, max_retries=2, cache_ttl=0)) as env:
        yield Flow(env)


def series(flow, owner_id, query, kind='client'):
    r = flow.api.get(f'/api/history/{kind}/{owner_id}/series?{query}')
    assert r.status_code == 200, r.text
    return r.json()


def test_six_and_twelve_month_series_show_gaps_without_interpolation(flow):
    c = flow.owner()
    months = history.month_range('2025-10', '2026-09')
    values = {}
    for i, label in enumerate(months):
        if label in ('2026-02', '2026-06'):
            continue
        values[label] = 10 + i
        approve_manual(flow, c['id'], label, values[label])
    six = series(flow, c['id'], 'metric_id=licenses.usage&months=6&end=2026-09')
    assert [p['competence'] for p in six['points']] == history.month_range('2026-04', '2026-09')
    assert six['gaps'] == ['2026-06']
    gap = next(p for p in six['points'] if p['competence'] == '2026-06')
    assert gap == {'competence': '2026-06', 'state': 'GAP', 'value': None, 'headline': None, 'value_state': None,
                   'origin': None, 'approval': None}  # ausência nunca vira zero nem média dos vizinhos
    twelve = series(flow, c['id'], 'metric_id=licenses.usage&months=12&end=2026-09')
    assert len(twelve['points']) == 12 and twelve['gaps'] == ['2026-02', '2026-06']
    assert {p['competence']: p['value'] for p in twelve['points'] if p['state'] == 'APPROVED'} == values
    assert all(p['value_state'] == 'MANUAL' and p['approval']['identity_mode'] == 'DECLARED_UNAUTHENTICATED'
               for p in twelve['points'] if p['state'] == 'APPROVED')
    custom = series(flow, c['id'], 'metric_id=licenses.usage&start=2026-01&end=2026-03')
    assert [(p['competence'], p['value']) for p in custom['points']] == \
        [('2026-01', values['2026-01']), ('2026-02', None), ('2026-03', values['2026-03'])]


def test_gap_can_be_filled_by_audited_manual_entry_and_drafts_never_enter_history(flow):
    c = flow.owner()
    approve_manual(flow, c['id'], '2026-07', 5)
    approve_manual(flow, c['id'], '2026-09', 9)
    draft = flow.competence(c['id'], '2026-08')
    flow.manual(draft['id'], 1, 'licenses.usage', 7)  # só rascunho: continua lacuna
    s = series(flow, c['id'], 'metric_id=licenses.usage&start=2026-07&end=2026-09')
    assert s['gaps'] == ['2026-08']
    flow.required(draft['id'], 1, ['licenses.usage'])
    flow.submit(draft['id'], 1)
    flow.approve_ok(draft['id'], 1)
    s = series(flow, c['id'], 'metric_id=licenses.usage&start=2026-07&end=2026-09')
    assert s['gaps'] == [] and [p['value'] for p in s['points']] == [5, 7, 9]
    events = flow.api.get(f'/api/competences/{draft["id"]}/audit').json()['items']
    assert 'metric.manual_set' in [e['event_type'] for e in events]


def test_previous_month_is_reused_exactly_even_after_veracode_changes(flow):
    c = flow.owner()
    aug = flow.from_run(flow.env.run('client', c['id'], competence='2026-08'))
    flow.required(aug['competence_id'], 1, ['apps.total', 'sast.policy.open.by_severity'])
    flow.submit(aug['competence_id'], 1)
    approved_aug = flow.approve_ok(aug['competence_id'], 1)
    aug_values = {s['metric_id']: s['value'] for s in approved_aug['snapshots']}
    # A Veracode muda depois da aprovação (aplicação removida, findings novos).
    tenant = flow.env.tenant
    tenant.applications.pop(1)
    sep = flow.from_run(flow.env.run('client', c['id']))
    assert next(s for s in sep['detail']['snapshots'] if s['metric_id'] == 'apps.total')['value'] == 3
    flow.required(sep['competence_id'], 1, ['apps.total'])
    flow.submit(sep['competence_id'], 1)
    flow.approve_ok(sep['competence_id'], 1)
    cmp_ = flow.api.get(f'/api/history/client/{c["id"]}/compare?competence=2026-09').json()
    by = {i['metric_id']: i for i in cmp_['items']}
    assert by['apps.total']['previous']['value'] == aug_values['apps.total'] == 4
    assert by['apps.total']['current']['value'] == 3 and by['apps.total']['delta'] == -1
    assert by['sast.policy.open.by_severity']['previous']['value'] == aug_values['sast.policy.open.by_severity']
    # Recoleta de agosto com a Veracode já alterada não muda o oficial (vai para revisão 2 em rascunho).
    again = flow.from_run(flow.env.run('client', c['id'], competence='2026-08'))
    assert again['revision'] == 2
    s = series(flow, c['id'], 'metric_id=apps.total&start=2026-08&end=2026-09')
    assert [p['value'] for p in s['points']] == [4, 3]
    assert s['points'][0]['approval']['revision'] == 1


def test_latest_approval_is_the_series_reference(flow):
    c = flow.owner()
    cid = approve_manual(flow, c['id'], '2026-09', 30)
    flow.api.post(f'/api/competences/{cid}/revisions', json={'operator': OP})
    flow.manual(cid, 2, 'licenses.usage', 31, justification='Correção de contagem auditada')
    flow.submit(cid, 2)
    flow.approve_ok(cid, 2)
    p = series(flow, c['id'], 'metric_id=licenses.usage&start=2026-09&end=2026-09')['points'][0]
    assert p['value'] == 31 and p['approval']['revision'] == 2 and p['approval']['sequence'] == 2
    old = flow.detail(cid, 1)
    assert next(s for s in old['snapshots'] if s['metric_id'] == 'licenses.usage')['value'] == 30


def test_series_are_isolated_per_owner_and_validate_inputs(flow):
    c = flow.owner()
    sub = flow.env.subclient(c['id'], 'Filial')
    approve_manual(flow, c['id'], '2026-09', 50)
    approve_manual(flow, sub['id'], '2026-09', 5, kind='subclient')
    assert series(flow, c['id'], 'metric_id=licenses.usage&start=2026-09&end=2026-09')['points'][0]['value'] == 50
    assert series(flow, sub['id'], 'metric_id=licenses.usage&start=2026-09&end=2026-09', kind='subclient')[
        'points'][0]['value'] == 5
    base = f'/api/history/client/{c["id"]}/series'
    assert error_code(flow.api.get(f'{base}?metric_id=nao.existe')) == 'metric_not_found'
    assert error_code(flow.api.get(f'{base}?metric_id=licenses.usage&start=2026-09&end=2026-01')) == 'invalid_range'
    assert error_code(flow.api.get(f'{base}?metric_id=licenses.usage&start=2020-01&end=2026-01')) == 'range_too_large'
    assert error_code(flow.api.get(f'{base}?metric_id=licenses.usage&start=2026-13')) == 'invalid_competence'
    assert flow.api.get(f'{base}?metric_id=licenses.usage&months=0').status_code == 422


def test_default_end_is_last_closed_month_in_client_timezone():
    # 2026-10-01 02:00 UTC = 2026-09-30 23:00 em São Paulo: setembro ainda não fechou lá.
    now = datetime(2026, 10, 1, 2, 0, tzinfo=timezone.utc)
    assert history.last_closed_month('America/Sao_Paulo', now) == '2026-08'
    assert history.last_closed_month('UTC', now) == '2026-09'
    assert history.resolve_range('America/Sao_Paulo', months=6, start=None, end=None, now=now) == ('2026-03', '2026-08')
    assert history.resolve_range('UTC', months=12, start=None, end=None, now=now) == ('2025-10', '2026-09')
    assert history.month_range('2025-11', '2026-02') == ['2025-11', '2025-12', '2026-01', '2026-02']
