"""F08 — interpretação dos indicadores: geração determinística, validação, revisão humana, versões, desatualização,
integração com o editor, isolamento, falhas do provedor e confidencialidade. Dados 100% SINTÉTICOS; nenhuma
Veracode; nenhuma chamada externa (o conftest bloqueia DNS/conexões fora do loopback).
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.interpretation import providers
from app.interpretation.contracts import Budget, Context, Kind, Level, Origin, ProviderOutput, Statement
from app.interpretation.settings import InterpretationSettings
from app.interpretation.validate import validate
from conftest import error_code
from test_presentations import OP, Env, TOP_APPS, sev, values_for

REVIEWER = 'Revisora Sintética'


@pytest.fixture
def env(api) -> Env:
    e = Env(api)
    e.builtin()
    return e


@pytest.fixture
def demo(env):
    """Cliente sintético: 2026-08 e 2026-09 aprovados (manual justificado) + apresentação demo-executivo de 2026-09."""
    c = env.client('Cliente Interpretação Sintético')
    env.approved(c['id'], '2026-08', values_for(0))
    cid = env.approved(c['id'], '2026-09', values_for(1))
    p = env.present(cid)
    return {'client': c, 'cid': cid, 'pid': p['id'], 'env': env}


def gen(api, pid: str, slide: str, kind: str | None = None, level: str = 'EXECUTIVE', status: int = 201, **kw):
    body = {'slide_id': slide, 'level': level, 'operator': OP, **({'kind': kind} if kind else {}), **kw}
    r = api.post(f'/api/presentations/{pid}/interpretations', json=body)
    assert r.status_code == status, r.text
    return r.json()


def act(api, pid: str, iid: str, action: str, status: int = 200, **body):
    r = api.post(f'/api/presentations/{pid}/interpretations/{iid}/{action}', json={'operator': REVIEWER, **body})
    assert r.status_code == status, r.text
    return r.json()


def approve(api, pid: str, iid: str) -> dict:
    act(api, pid, iid, 'review')
    return act(api, pid, iid, 'approve')


_NUM = re.compile(r'(?<![\w.,\[])(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+))?(?![\w\]-])')


def numbers_in(text_: str) -> set[Decimal]:
    clean = re.sub(r'\b20\d{2}-\d{2}\b', ' ', text_)
    return {Decimal(m.group(1).replace('.', '') + ('.' + m.group(2) if m.group(2) else '')) for m in _NUM.finditer(clean)}


def codes(iv: dict, level: str | None = None) -> set[str]:
    return {i['code'] for i in iv['validation']['issues'] if level is None or i['level'] == level}


# ---------------------------------------------------------------- 1–3: geração determinística e níveis

def test_deterministic_generation_is_repeatable_and_local(api, demo):
    pid = demo['pid']
    a = gen(api, pid, 'sumario', 'EXECUTIVE_SUMMARY')
    b = gen(api, pid, 'sumario', 'EXECUTIVE_SUMMARY')
    assert a['text'] == b['text'] and a['context_hash'] == b['context_hash'] and a['statements'] == b['statements']
    assert (a['version'], b['version']) == (1, 2)  # mesma linha, versões novas; nada sobrescrito
    assert a['provider'] == 'deterministic-demo' and a['model'] == 'regras-f08@1'
    assert a['prompt_version'] == 'f08-interp-1' and len(a['prompt_hash']) == 64


def test_executive_summary_uses_only_approved_values_and_full_output_contract(api, demo):
    pid = demo['pid']
    iv = gen(api, pid, 'sumario', 'EXECUTIVE_SUMMARY')
    assert iv['valid'] is True and iv['status'] == 'GENERATED' and iv['origin'] == 'GENERATED'
    # contrato de saída (§6)
    for key in ('id', 'owner', 'competence', 'presentation_id', 'presentation_revision', 'slide_id', 'kind', 'text',
                'indicators', 'provider', 'model', 'prompt_version', 'created_at', 'status', 'sources_hash',
                'context_hash', 'content_hash', 'statements', 'validation', 'level', 'target_field'):
        assert key in iv, key
    assert iv['owner']['client_id'] == demo['client']['id'] and iv['owner']['subclient_id'] is None
    assert iv['competence']['competence'] == '2026-09' and iv['presentation_revision'] == 1
    assert iv['slide_id'] == 'sumario' and iv['target_field'] == 'body' and iv['level'] == 'EXECUTIVE'
    ind = {i['metric_id']: i for i in iv['indicators']}
    assert ind['apps.total']['current']['value'] == 51 and ind['apps.total']['previous']['value'] == 50
    assert ind['apps.total']['provenance']['current']['revision'] == 1
    assert ind['apps.total']['provenance']['current']['content_hash']
    # todo número do texto vem dos fatos (valores aprovados, variações e percentuais do backend)
    t = iv['text']
    assert '51 aplicações' in t and 'aumento de 1 aplicação (2,0%)' in t and '2026-08' in t
    assert numbers_in(t) <= {Decimal(x) for x in ('51', '1', '2.0', '11', '10.0', '5')}  # 5 = SCA estável
    assert 'porque' not in t and 'devido' not in t


def test_technical_level_is_detailed_and_cites_metric_ids_and_quality(api, demo):
    pid = demo['pid']
    ex = gen(api, pid, 'sumario', 'EXECUTIVE_SUMMARY')
    te = gen(api, pid, 'sumario', 'EXECUTIVE_SUMMARY', 'TECHNICAL')
    assert te['valid'] and '[apps.total]' in te['text'] and '[apps.total]' not in ex['text']
    assert 'valor manual aprovado' in te['text']
    assert 'Sem direção desejável declarada' in te['text']  # neutro: não classifica melhora/piora
    assert te['level'] == 'TECHNICAL' and te['kind'] == ex['kind']


@pytest.mark.parametrize('slide,kind,field', [
    ('kpis', 'CHART_EXPLANATION', 'caption'), ('comparacao', 'PERIOD_COMPARISON', 'caption'),
    ('severidade-sast', 'CHART_EXPLANATION', 'caption'), ('serie-sast', 'SAST_TRENDS', 'caption'),
    ('top-apps', 'RANKING_HIGHLIGHTS', 'caption'), ('recomendacoes', 'TECHNICAL_RECOMMENDATIONS', 'items'),
    ('sumario', 'IMPROVEMENTS', 'body'), ('sumario', 'ATTENTION_POINTS', 'body'), ('sumario', 'SCA_TRENDS', 'body'),
    ('sumario', 'COMPLIANCE_EVOLUTION', 'body'), ('sumario', 'SCAN_COVERAGE_EVOLUTION', 'body'),
])
@pytest.mark.parametrize('level', ['EXECUTIVE', 'TECHNICAL'])
def test_every_kind_generates_valid_text_for_its_slide(api, demo, slide, kind, field, level):
    iv = gen(api, demo['pid'], slide, kind, level)
    assert iv['target_field'] == field
    assert iv['valid'], iv['validation']['issues']


def test_kind_and_target_are_checked_per_slide(api, demo):
    pid = demo['pid']
    assert error_code(api.post(f'/api/presentations/{pid}/interpretations',
                               json={'slide_id': 'capa', 'operator': OP})) == 'interpretation_kind_not_applicable'
    r = api.post(f'/api/presentations/{pid}/interpretations',
                 json={'slide_id': 'top-apps', 'kind': 'COMPLIANCE_EVOLUTION', 'operator': OP})
    assert r.status_code == 422 and error_code(r) == 'interpretation_kind_not_applicable'
    assert error_code(api.post(f'/api/presentations/{pid}/interpretations',
                               json={'slide_id': 'nao-existe', 'operator': OP})) == 'interpretation_slide_not_found'
    assert gen(api, pid, 'top-apps')['kind'] == 'RANKING_HIGHLIGHTS'  # padrão por tipo de slide
    assert gen(api, pid, 'kpis', target_field='notes')['target_field'] == 'notes'


# ---------------------------------------------------------------- 4–8: ausentes, manuais, percentuais, períodos

def test_missing_indicators_are_declared_never_numbered(api, env):
    c = env.client('Cliente Ausente')
    env.approved(c['id'], '2026-08', {'apps.total': 10})
    cid = env.approved(c['id'], '2026-09', {'apps.total': 12})  # SAST/SCA sem valor aprovado
    pid = env.present(cid)['id']
    iv = gen(api, pid, 'kpis', 'CHART_EXPLANATION', target_field='notes')
    assert iv['valid'], iv['validation']['issues']
    ind = {i['metric_id']: i for i in iv['indicators']}
    assert ind['sast.policy.open.by_severity']['state'] == 'MISSING' and not ind['sast.policy.open.by_severity'][
        'definitive']
    line = next(s['text'] for s in iv['statements'] if 'SAST abertos' in s['text'])
    assert 'sem valor aprovado' in line and 'não é interpretado' in line and not numbers_in(line)


def _ctx(facts: list[dict], kind=Kind.EXECUTIVE_SUMMARY) -> Context:
    return Context(kind=kind, level=Level.EXECUTIVE, competence='2026-09', previous_competence='2026-08',
                   history_window=['2026-04', '2026-05', '2026-06', '2026-07', '2026-08', '2026-09'],
                   slide={'slide_id': 's', 'type': 'executive_summary', 'layout': 'text-only', 'target_field': 'body',
                          'budget': {'max_chars': 1400, 'max_items': 0, 'item_chars': 0}},
                   facts=facts, rules=[])


def _fact(fid='M1', *, cur=46, prev=45, state='VALUE', value_state='VALIDATED', origin='VEX', direction='NEUTRAL',
          trend='unknown', vt='count') -> dict:
    delta = None if cur is None or prev is None else cur - prev
    return {'id': fid, 'type': 'metric', 'metric_id': 'sast.policy.open.by_severity', 'name': 'SAST abertos',
            'unit': 'findings', 'unit_label': 'findings', 'value_type': vt, 'desired_direction': direction,
            'state': state, 'value_state': value_state, 'origin': origin,
            'definitive': state == 'VALUE' and value_state in ('VALIDATED', 'MANUAL'),
            'current': {'competence': '2026-09', 'state': state, 'value_state': value_state, 'origin': origin,
                        'value': cur, 'label': None if cur is None else str(cur)},
            'previous': {'competence': '2026-08', 'state': 'VALUE', 'value_state': 'VALIDATED', 'origin': origin,
                         'value': prev, 'label': None if prev is None else str(prev)},
            'delta': delta, 'delta_label': None if delta is None else f'+{delta}',
            'delta_pct': None if delta is None or not prev else round(delta / prev * 100, 1),
            'delta_pct_label': None, 'delta_unavailable_reason': None if delta is not None else 'no_numeric_value',
            'trend': trend, 'trend_reason': None, 'severity': None, 'categories': None, 'previous_categories': None,
            'history': None, 'provenance': {}}


BODY = Budget('body', 1400)


def _check(facts, *texts, origin=Origin.GENERATED, ids=None, justification=None, budget=BODY):
    sts = [Statement(text=t, fact_ids=ids if ids is not None else [f['id'] for f in facts]) for t in texts]
    return validate(_ctx(facts), sts, origin=origin, budget=budget, justification=justification)


@pytest.mark.parametrize('value_state', ['INCOMPLETE', 'SOURCE_UNAVAILABLE', 'MISSING', 'UNSUPPORTED'])
def test_incomplete_or_unavailable_values_are_never_read_as_definitive(value_state):
    f = _fact(cur=None, state='MISSING', value_state=value_state)
    r = _check([f], 'SAST abertos: 46 findings em 2026-09.')
    assert {'missing_value_not_declared', 'number_for_missing_value'} <= {i['code'] for i in r['issues']}
    ok = _check([f], 'SAST abertos: sem valor aprovado em 2026-09 (coleta incompleta); o indicador não é '
                     'interpretado.')
    assert ok['valid'], ok['issues']


def test_manual_values_are_disclosed_and_flagged_when_hidden(api, demo):
    pid = demo['pid']
    iv = gen(api, pid, 'sumario', 'EXECUTIVE_SUMMARY')
    assert 'manualmente' in iv['text'] and 'manual_not_disclosed' not in codes(iv)
    assert all(i['origin'] == 'MANUAL' for i in iv['indicators'] if i['definitive'])
    hidden = act(api, pid, iv['id'], 'edit', 201, text='Aplicações no escopo: 51 aplicações em 2026-09.')
    assert hidden['valid'] is True and 'manual_not_disclosed' in codes(hidden, 'warning')


def test_percentages_are_backend_computed_rounded_and_unit_checked(api, demo):
    pid = demo['pid']
    iv = gen(api, pid, 'comparacao', 'PERIOD_COMPARISON', target_field='notes')
    ind = {i['metric_id']: i for i in iv['indicators']}
    assert ind['sast.policy.open.by_severity']['delta'] == 1
    assert ind['sast.policy.open.by_severity']['delta_pct'] == 10.0  # (11 − 10) / 10, 1 casa, meio-par
    assert ind['sca.policy.open.by_severity']['delta'] == 0 and ind['sca.policy.open.by_severity']['delta_pct'] == 0
    assert '(10,0%)' in iv['text'] and 'estável em relação a 2026-08' in iv['text']
    wrong = act(api, pid, iv['id'], 'edit', 201, text='SAST abertos subiu 12,5% em 2026-09.')
    assert 'unverified_number' in codes(wrong, 'blocker')
    unit = act(api, pid, wrong['id'], 'edit', 201, text='SAST abertos: 11% em 2026-09.')
    assert 'unit_mismatch' in codes(unit, 'blocker')  # 11 é contagem, não percentual
    rounded = act(api, pid, unit['id'], 'edit', 201, text='SAST abertos: aumento de 10% em relação a 2026-08.')
    assert rounded['valid'], rounded['validation']['issues']  # 10,0% → 10% (menos casas, meio-par)


def test_previous_zero_has_no_percentage():
    f = _fact(cur=5, prev=0)
    assert f['delta_pct'] is None
    r = _check([f], 'SAST abertos: aumento de 5 findings em relação a 2026-08 (anterior 0).')
    assert r['valid'], r['issues']
    bad = _check([f], 'SAST abertos: aumento de 100% em relação a 2026-08.')
    assert 'unverified_number' in {i['code'] for i in bad['issues']}


def test_period_comparison_with_gap_and_out_of_context_periods(api, env):
    c = env.client('Cliente Lacuna')
    env.approved(c['id'], '2026-07', values_for(0))
    cid = env.approved(c['id'], '2026-09', values_for(1))  # 2026-08 sem aprovação: LACUNA
    pid = env.present(cid)['id']
    iv = gen(api, pid, 'comparacao', 'PERIOD_COMPARISON', target_field='notes')
    assert iv['valid'], iv['validation']['issues']
    ind = {i['metric_id']: i for i in iv['indicators']}
    assert ind['apps.total']['delta'] is None and ind['apps.total']['delta_unavailable_reason'] == 'gap'
    assert 'sem comparação com 2026-08' in iv['text'] and 'lacuna' in iv['text']
    other = act(api, pid, iv['id'], 'edit', 201, text='Aplicações no escopo: 51 aplicações em 2025-03.')
    assert 'period_not_in_context' in codes(other, 'blocker')


def test_every_number_in_generated_text_is_traceable_to_a_fact(api, demo):
    pid = demo['pid']
    for slide, kind in (('sumario', 'EXECUTIVE_SUMMARY'), ('serie-sast', 'SAST_TRENDS'),
                        ('top-apps', 'RANKING_HIGHLIGHTS'), ('severidade-sast', 'CHART_EXPLANATION')):
        iv = gen(api, pid, slide, kind, 'TECHNICAL', target_field='notes')
        assert iv['valid'], iv['validation']['issues']
        assert iv['validation']['checked']['numbers'] >= 1 and iv['validation']['checked']['statements'] >= 1


# ---------------------------------------------------------------- 9–11: invenções, causas, tamanho

def test_invented_values_are_rejected_and_block_approval(api, demo):
    pid = demo['pid']
    iv = gen(api, pid, 'sumario', 'EXECUTIVE_SUMMARY')
    bad = act(api, pid, iv['id'], 'edit', 201, text='SAST abertos: 47 findings em 2026-09, 3.200 linhas analisadas.')
    assert bad['valid'] is False and bad['status'] == 'IN_REVIEW'
    tokens = {i.get('token') for i in bad['validation']['issues'] if i['code'] == 'unverified_number'}
    assert {'47', '3.200'} <= tokens
    r = api.post(f'/api/presentations/{pid}/interpretations/{bad["id"]}/approve', json={'operator': REVIEWER})
    assert r.status_code == 409 and error_code(r) == 'interpretation_not_valid'


def test_unknown_fact_and_uncited_numbers_are_blocked():
    f = _fact()
    r = _check([f], 'SAST abertos: 46 findings em 2026-09.', ids=['M9'])
    assert {'unknown_fact', 'uncited_number'} <= {i['code'] for i in r['issues']}
    bare = _check([f], 'SAST abertos aumentou.', ids=[])
    assert 'statement_without_evidence' in {i['code'] for i in bare['issues']}


@pytest.mark.parametrize('claim,code', [
    ('O aumento ocorreu porque os desenvolvedores deixaram de tratar vulnerabilidades.', 'unsupported_causal_claim'),
    ('A queda se deve-se ao novo pipeline.', 'unsupported_causal_claim'),
    ('Os findings críticos foram corrigidos pela equipe.', 'unsupported_remediation_claim'),
    ('Duas aplicações foram removidas do escopo.', 'unsupported_removal_claim'),
    ('O programa ganhou maturidade no mês.', 'unsupported_maturity_claim'),
    ('Há risco de negócio elevado de vazamento.', 'unsupported_business_risk_claim'),
    ('A aplicação está garantidamente livre de vulnerabilidades.', 'unsupported_absolute_claim'),
])
def test_unsupported_claims_are_blocked(claim, code):
    r = _check([_fact()], claim)
    assert code in {i['code'] for i in r['issues'] if i['level'] == 'blocker'}


def test_direction_and_trend_must_match_facts():
    f = _fact(cur=46, prev=45, direction='LOWER_IS_BETTER', trend='worsening')
    assert 'direction_mismatch' in {i['code'] for i in _check([f], 'SAST abertos: redução em 2026-09.')['issues']}
    assert 'trend_not_proven' in {i['code'] for i in _check([f], 'SAST abertos: variação favorável.')['issues']}
    neutral = _fact(cur=46, prev=45)
    assert 'trend_not_proven' in {i['code'] for i in _check([neutral], 'SAST abertos: houve melhora.')['issues']}
    assert _check([neutral], 'SAST abertos: aumento de 1 finding; não há melhora comprovada.')['valid']


def test_causal_claim_with_editorial_note_or_editor_justification_is_a_visible_warning(api, demo):
    pid = demo['pid']
    note = 'Operador informa: migração de pipelines concluída em setembro.'
    iv = gen(api, pid, 'sumario', 'EXECUTIVE_SUMMARY', notes=[note])
    assert any(f['type'] == 'editorial' and f['text'] == note for f in
               api.get(f'/api/presentations/{pid}/interpretations/{iv["id"]}').json()['context']['facts'])
    edited = act(api, pid, iv['id'], 'edit', 201,
                 text='O aumento de SAST ocorreu devido à migração de pipelines informada pelo operador.')
    assert edited['valid'] is True and 'claim_justified_by_editor' not in codes(edited)  # nota citada (E1)
    assert 'claim_from_operator_note' in codes(edited, 'warning')
    plain = gen(api, pid, 'kpis', 'CHART_EXPLANATION', target_field='notes')
    no = act(api, pid, plain['id'], 'edit', 201, text='O aumento ocorreu devido à troca de equipe.')
    assert 'unsupported_causal_claim' in codes(no, 'blocker')
    yes = act(api, pid, no['id'], 'edit', 201, text='O aumento ocorreu devido à troca de equipe (confirmado).',
              justification='Confirmado em reunião com o cliente (ata sintética).')
    assert yes['valid'] and 'claim_justified_by_editor' in codes(yes, 'warning')
    assert yes['justification'].startswith('Confirmado')


def test_character_limits_and_item_counts_are_enforced():
    f = _fact()
    long_ = 'SAST abertos: 46 findings em 2026-09. ' * 10
    r = _check([f], long_, budget=Budget('caption', 240))
    assert 'too_long' in {i['code'] for i in r['issues']}
    items = Budget('items', 5 * 150, 5, 150)
    many = _check([f], *(['SAST abertos: 46 findings.'] * 6), budget=items)
    assert 'too_many_items' in {i['code'] for i in many['issues']}
    one_long = _check([f], 'SAST abertos: 46 findings. ' + 'x' * 200, budget=items)
    assert 'too_long' in {i['code'] for i in one_long['issues']}


def test_generated_text_respects_each_slide_budget(api, demo):
    pid = demo['pid']
    cap = gen(api, pid, 'kpis', 'CHART_EXPLANATION', 'TECHNICAL')
    assert cap['target_field'] == 'caption' and len(cap['text']) <= 240 and cap['valid']
    recs = gen(api, pid, 'recomendacoes', 'TECHNICAL_RECOMMENDATIONS', 'TECHNICAL')
    assert len(recs['statements']) <= 8 and all(len(s['text']) <= 220 for s in recs['statements'])
    too_long = act(api, pid, cap['id'], 'edit', 201, text='Aplicações no escopo: 51 aplicações. ' * 12)
    assert 'too_long' in codes(too_long, 'blocker')


# ---------------------------------------------------------------- 12–16: revisão humana, versões, desatualização

def _snapshot_state(api, cid: str) -> tuple:
    rev = api.get(f'/api/competences/{cid}/revisions/1').json()
    return rev['status'], json.dumps(rev, sort_keys=True), api.get(f'/api/competences/{cid}/integrity').json()['ok']


def test_human_approval_flow_and_snapshots_untouched(api, demo):
    pid, cid = demo['pid'], demo['cid']
    before = _snapshot_state(api, cid)
    iv = gen(api, pid, 'sumario', 'EXECUTIVE_SUMMARY')
    r = api.post(f'/api/presentations/{pid}/interpretations/{iv["id"]}/approve', json={'operator': REVIEWER})
    assert r.status_code == 409 and error_code(r) == 'interpretation_invalid_transition'  # sem revisão, sem aprovação
    assert act(api, pid, iv['id'], 'review')['status'] == 'IN_REVIEW'
    ok = act(api, pid, iv['id'], 'approve', reason='Conferido com os dados de origem')
    assert ok['status'] == 'APPROVED'
    assert [(e['event'], e['actor']) for e in ok['events']] == [('GENERATED', OP), ('IN_REVIEW', REVIEWER),
                                                                ('APPROVED', REVIEWER)]
    assert _snapshot_state(api, cid) == before  # revisão não altera snapshots/indicadores
    assert api.get(f'/api/presentations/{pid}').json()['current_revision'] == 1  # nada entra sozinho no slide
    assert api.get(f'/api/presentations/{pid}/integrity').json()['ok'] is True


def test_rejection_requires_reason_and_regeneration_keeps_history(api, demo):
    pid = demo['pid']
    iv = gen(api, pid, 'sumario', 'EXECUTIVE_SUMMARY')
    r = api.post(f'/api/presentations/{pid}/interpretations/{iv["id"]}/reject', json={'operator': REVIEWER})
    assert r.status_code == 422 and error_code(r) == 'interpretation_reason_required'
    rej = act(api, pid, iv['id'], 'reject', reason='Tom inadequado para a diretoria')
    assert rej['status'] == 'REJECTED' and rej['events'][-1]['reason'] == 'Tom inadequado para a diretoria'
    regen = act(api, pid, iv['id'], 'regenerate', 201, level='TECHNICAL')
    assert regen['version'] == 2 and regen['parent_id'] == iv['id'] and regen['level'] == 'TECHNICAL'
    assert regen['status'] == 'GENERATED'
    hist = api.get(f'/api/presentations/{pid}/interpretations/{regen["id"]}').json()['history']
    assert [(h['version'], h['status']) for h in hist] == [(1, 'REJECTED'), (2, 'GENERATED')]
    old = api.post(f'/api/presentations/{pid}/interpretations/{iv["id"]}/review', json={'operator': REVIEWER})
    assert old.status_code == 409 and error_code(old) == 'interpretation_superseded'


def test_manual_edit_creates_authored_version_in_review(api, demo):
    pid = demo['pid']
    iv = gen(api, pid, 'sumario', 'EXECUTIVE_SUMMARY')
    r = api.post(f'/api/presentations/{pid}/interpretations/{iv["id"]}/edit',
                 json={'text': 'Aplicações no escopo: 51 aplicações em 2026-09 (valor manual aprovado).',
                       'operator': 'Editora Sintética', 'justification': 'Texto mais curto para a diretoria'})
    assert r.status_code == 201, r.text
    ed = r.json()
    assert ed['origin'] == 'EDITED' and ed['provider'] == 'human' and ed['created_by'] == 'Editora Sintética'
    assert ed['status'] == 'IN_REVIEW' and ed['parent_id'] == iv['id'] and ed['valid']
    assert ed['context_hash'] == iv['context_hash']  # revalidada contra os MESMOS fatos
    first = api.get(f'/api/presentations/{pid}/interpretations/{iv["id"]}').json()
    assert first['text'] == iv['text'] and first['is_latest'] is False
    same = api.post(f'/api/presentations/{pid}/interpretations/{ed["id"]}/edit',
                    json={'text': ed['text'], 'operator': OP})
    assert same.status_code == 409 and error_code(same) == 'interpretation_unchanged'


def test_versions_are_append_only_and_comparable(api, demo, db_url):
    pid = demo['pid']
    v1 = gen(api, pid, 'sumario', 'EXECUTIVE_SUMMARY')
    v2 = act(api, pid, v1['id'], 'edit', 201, text='Aplicações no escopo: 51 aplicações em 2026-09.')
    v3 = act(api, pid, v2['id'], 'regenerate', 201)
    assert [v['version'] for v in (v1, v2, v3)] == [1, 2, 3]
    diff = api.get(f'/api/presentations/{pid}/interpretations/{v1["id"]}/compare/{v2["id"]}').json()
    assert diff['from']['version'] == 1 and diff['to']['version'] == 2 and diff['same_facts'] is True
    assert any(op['op'] != 'equal' for op in diff['diff'])
    other = gen(api, pid, 'kpis')
    r = api.get(f'/api/presentations/{pid}/interpretations/{v1["id"]}/compare/{other["id"]}')
    assert r.status_code == 422
    listing = api.get(f'/api/presentations/{pid}/interpretations').json()['items']
    assert len(listing) == 4
    from app import db
    engine = db.make_engine(db_url)
    try:
        for stmt in ("UPDATE interpretation_versions SET text = 'x'", 'DELETE FROM interpretation_versions',
                     "UPDATE interpretation_events SET actor = 'x'", 'DELETE FROM interpretation_events'):
            with pytest.raises(Exception, match='append_only'):
                with engine.begin() as conn:
                    conn.execute(text(stmt))
    finally:
        engine.dispose()


def test_snapshot_or_source_change_flags_stale_and_blocks_approval(api, demo):
    pid, cid, env = demo['pid'], demo['cid'], demo['env']
    iv = gen(api, pid, 'sumario', 'EXECUTIVE_SUMMARY')
    act(api, pid, iv['id'], 'review')
    approved_other = approve(api, pid, gen(api, pid, 'kpis')['id'])
    assert approved_other['status'] == 'APPROVED'
    # nova revisão da competência (F05) com valor corrigido, aprovada; a apresentação troca as fontes explicitamente
    env.call('POST', f'/api/competences/{cid}/revisions', 201, operator=OP)
    env.fill(cid, 2, {'apps.total': 60})
    env.approve(cid, 2, ['apps.total'])
    listed = {i['id']: i for i in api.get(f'/api/presentations/{pid}/interpretations').json()['items']}
    assert listed[iv['id']]['stale'] == []  # fontes fixadas ainda são as antigas: nada bloqueia até o rebind
    assert {n['code'] for n in listed[iv['id']]['notices']} == {'newer_approval_available'}  # mas avisa
    env.call('POST', f'/api/presentations/{pid}/rebind', expected_revision=1, operator=OP)
    detail = api.get(f'/api/presentations/{pid}/interpretations/{iv["id"]}').json()
    assert {s['code'] for s in detail['stale']} == {'sources_changed', 'facts_changed'}
    r = api.post(f'/api/presentations/{pid}/interpretations/{iv["id"]}/approve', json={'operator': REVIEWER})
    assert r.status_code == 409 and error_code(r) == 'interpretation_stale'
    r = api.post(f'/api/presentations/{pid}/interpretations/{approved_other["id"]}/apply',
                 json={'operator': OP, 'expected_revision': 2})
    assert r.status_code == 409 and error_code(r) == 'interpretation_stale'
    fresh = act(api, pid, iv['id'], 'regenerate', 201)
    assert fresh['stale'] == [] and '60 aplicações' in fresh['text']


# ---------------------------------------------------------------- 17: integração com o editor (aplicação)

def test_apply_writes_a_new_presentation_revision_and_never_overwrites_silently(api, demo):
    pid, env = demo['pid'], demo['env']
    iv = approve(api, pid, gen(api, pid, 'sumario', 'EXECUTIVE_SUMMARY')['id'])
    r = api.post(f'/api/presentations/{pid}/interpretations/{iv["id"]}/apply',
                 json={'operator': OP, 'expected_revision': 1})
    assert r.status_code == 200, r.text
    assert r.json()['presentation_revision'] == 2
    view = env.view(pid)
    sumario = next(s for s in view['slides'] if s['slide_id'] == 'sumario')
    assert sumario['fields']['body'] == iv['text']
    assert view['revision']['change_summary'].startswith('Interpretação aprovada aplicada')
    assert view['sources']['primary']['revision'] == 1  # indicadores e proveniência intocados
    assert api.get(f'/api/presentations/{pid}/integrity').json()['ok'] is True
    applied = api.get(f'/api/presentations/{pid}/interpretations/{iv["id"]}').json()
    assert applied['applied'][0]['presentation_revision'] == 2 and applied['stale'] == []
    # nova interpretação aprovada não substitui texto existente sem confirmação explícita
    tech = approve(api, pid, gen(api, pid, 'sumario', 'EXECUTIVE_SUMMARY', 'TECHNICAL')['id'])
    r = api.post(f'/api/presentations/{pid}/interpretations/{tech["id"]}/apply',
                 json={'operator': OP, 'expected_revision': 2})
    assert r.status_code == 409 and error_code(r) == 'interpretation_overwrite_requires_confirmation'
    assert r.json()['error']['details'][0]['message'] == iv['text'][:500]
    r = api.post(f'/api/presentations/{pid}/interpretations/{tech["id"]}/apply',
                 json={'operator': OP, 'expected_revision': 2, 'overwrite_confirmed': True})
    assert r.status_code == 200 and r.json()['presentation_revision'] == 3
    # edição manual posterior é preservada e apenas sinalizada
    doc = env.document(pid)
    doc['slides'][[s['slide_id'] for s in doc['slides']].index('sumario')]['fields']['body'] = 'Texto final da editora.'
    env.save(pid, doc, 3)
    after = api.get(f'/api/presentations/{pid}/interpretations/{tech["id"]}').json()
    assert {n['code'] for n in after['notices']} == {'applied_text_edited'} and after['stale'] == []
    assert env.document(pid)['slides'][1]['fields']['body'] == 'Texto final da editora.'


def test_only_approved_latest_interpretations_are_applied_with_concurrency(api, demo):
    pid = demo['pid']
    iv = gen(api, pid, 'recomendacoes', 'TECHNICAL_RECOMMENDATIONS')
    r = api.post(f'/api/presentations/{pid}/interpretations/{iv["id"]}/apply',
                 json={'operator': OP, 'expected_revision': 1})
    assert r.status_code == 409 and error_code(r) == 'interpretation_not_approved'
    approve(api, pid, iv['id'])
    r = api.post(f'/api/presentations/{pid}/interpretations/{iv["id"]}/apply',
                 json={'operator': OP, 'expected_revision': 7})
    assert r.status_code == 409 and error_code(r) == 'presentation_conflict'
    r = api.post(f'/api/presentations/{pid}/interpretations/{iv["id"]}/apply',
                 json={'operator': OP, 'expected_revision': 1})
    assert r.status_code == 200
    doc_items = [s for s in demo['env'].document(pid)['slides'] if s['slide_id'] == 'recomendacoes'][0]['fields']['items']
    assert doc_items == [s['text'] for s in iv['statements']]


def test_interpretation_can_be_disabled_per_slide(api, demo):
    pid = demo['pid']
    r = api.put(f'/api/presentations/{pid}/interpretation-settings/sumario',
                json={'disabled': True, 'operator': OP, 'reason': 'Texto escrito pela equipe'})
    assert r.status_code == 200 and 'sumario' in r.json()['disabled_slides']
    r = api.post(f'/api/presentations/{pid}/interpretations', json={'slide_id': 'sumario', 'operator': OP})
    assert r.status_code == 409 and error_code(r) == 'interpretation_disabled'
    assert gen(api, pid, 'kpis')['slide_id'] == 'kpis'  # outros slides seguem habilitados
    assert api.get(f'/api/presentations/{pid}/interpretations').json()['disabled_slides']['sumario']['reason']
    api.put(f'/api/presentations/{pid}/interpretation-settings/sumario', json={'disabled': False, 'operator': OP})
    assert gen(api, pid, 'sumario')['slide_id'] == 'sumario'


# ---------------------------------------------------------------- 19–22: externo, isolamento, falhas, sigilo

def test_no_external_provider_or_transmission_by_default(api, demo):
    cfg = api.get('/api/interpretation/config').json()
    assert cfg['settings']['provider'] == 'deterministic-demo' and cfg['settings']['external_enabled'] is False
    assert cfg['settings']['credential_configured'] is False and 'api_key' not in cfg['settings']
    assert [p['external'] for p in cfg['providers']] == [False] and providers.EXTERNAL_PROVIDERS == {}
    pid = demo['pid']
    prev = api.post(f'/api/presentations/{pid}/interpretations/context', json={'slide_id': 'sumario'}).json()
    assert prev['external'] is False and prev['transmission']['transmitted'] is False
    r = api.post(f'/api/presentations/{pid}/interpretations',
                 json={'slide_id': 'sumario', 'operator': OP, 'provider': 'outro-fornecedor', 'external_consent': True})
    assert r.status_code == 422 and error_code(r) == 'provider_not_available'


def test_clients_and_subclients_are_isolated(api, env):
    a = env.client('Cliente Alfa Sintético')
    b = env.client('Cliente Beta Sintético')
    sub = env.subclient(a['id'], 'Unidade Alfa Norte')
    pa = env.present(env.approved(a['id'], '2026-09', {'apps.total': 321}))['id']
    pb = env.present(env.approved(b['id'], '2026-09', {'apps.total': 987}))['id']
    ps = env.present(env.approved(sub['id'], '2026-09', {'apps.total': 555}, 'subclient'))['id']
    ia, ib, isub = (gen(api, p, 'sumario') for p in (pa, pb, ps))
    assert '321' in ia['text'] and '987' not in ia['text'] and '555' not in ia['text']
    assert '987' in ib['text'] and '555' in isub['text'] and '321' not in isub['text']
    assert isub['owner']['kind'] == 'subclient' and isub['owner']['subclient_id'] == sub['id']
    for name in ('Alfa', 'Beta', 'Unidade'):
        assert name not in ia['text'] + ib['text'] + isub['text']  # nome do dono não entra no contexto
    assert api.get(f'/api/presentations/{pb}/interpretations/{ia["id"]}').status_code == 404
    assert api.post(f'/api/presentations/{pb}/interpretations/{ia["id"]}/review',
                    json={'operator': OP}).status_code == 404
    assert api.get(f'/api/presentations/{pb}/interpretations').json()['items'][0]['id'] == ib['id']
    assert len(api.get(f'/api/presentations/{pb}/interpretations').json()['items']) == 1


class _FakeExternal(providers.ExternalProvider):
    name = 'fake-externo'
    behaviour = 'ok'
    sent: list = []

    def _send(self, payload):
        type(self).sent.append(payload)
        if self.behaviour == 'error':
            raise RuntimeError('detalhe interno do fornecedor que não pode vazar')
        if self.behaviour == 'timeout':
            raise TimeoutError
        if self.behaviour == 'garbage':
            return {'texto': 'fora do contrato'}
        if self.behaviour == 'invented':
            return {'statements': [{'text': 'Aplicações no escopo: 999 aplicações porque sim.', 'fact_ids': ['M1']}]}
        return {'statements': [{'text': 'Aplicações no escopo: 51 aplicações em 2026-09 (valor manual aprovado).',
                                'fact_ids': ['M1']}]}


@pytest.fixture
def external(api, monkeypatch):
    monkeypatch.setitem(providers.EXTERNAL_PROVIDERS, 'fake-externo', _FakeExternal)
    _FakeExternal.sent = []

    def configure(**kw):
        base = {'provider': 'fake-externo', 'external_enabled': True, 'api_key': 'chave-sintetica-de-teste',
                'max_requests_per_day': 5, 'max_input_chars': 200_000}
        api.app.state.interpretation = InterpretationSettings(**{**base, **kw})
    return configure


def _count(api, pid) -> int:
    return len(api.get(f'/api/presentations/{pid}/interpretations').json()['items'])


@pytest.mark.parametrize('settings,consent,status,code', [
    ({'external_enabled': False}, True, 409, 'external_ai_disabled'),
    ({'api_key': None}, True, 409, 'external_ai_not_configured'),
    ({}, False, 409, 'external_ai_consent_required'),
    ({'max_requests_per_day': 0}, True, 429, 'external_ai_budget_exceeded'),
    ({'max_input_chars': 1000}, True, 413, 'external_ai_payload_too_large'),
])
def test_external_provider_gates_send_nothing(api, demo, external, settings, consent, status, code):
    external(**settings)
    pid = demo['pid']
    r = api.post(f'/api/presentations/{pid}/interpretations',
                 json={'slide_id': 'sumario', 'operator': OP, 'external_consent': consent})
    assert r.status_code == status and error_code(r) == code
    assert _FakeExternal.sent == [] and _count(api, pid) == 0


@pytest.mark.parametrize('behaviour,code', [('error', 'provider_failed'), ('timeout', 'provider_timeout'),
                                            ('garbage', 'provider_invalid_output')])
def test_provider_failures_are_reported_without_leaking_or_persisting(api, demo, external, behaviour, code, caplog):
    external()
    _FakeExternal.behaviour = behaviour
    pid = demo['pid']
    with caplog.at_level(logging.INFO):
        r = api.post(f'/api/presentations/{pid}/interpretations',
                     json={'slide_id': 'sumario', 'operator': OP, 'external_consent': True})
    _FakeExternal.behaviour = 'ok'
    assert r.status_code == 502 and error_code(r) == code
    assert 'detalhe interno' not in r.text and 'detalhe interno' not in caplog.text
    assert _count(api, pid) == 0
    assert gen(api, pid, 'sumario', provider='deterministic-demo')['valid']  # editor segue funcionando


def test_external_output_is_validated_like_any_other(api, demo, external):
    external()
    pid = demo['pid']
    _FakeExternal.behaviour = 'invented'
    bad = gen(api, pid, 'sumario', external_consent=True)
    _FakeExternal.behaviour = 'ok'
    assert bad['provider'] == 'fake-externo' and bad['valid'] is False
    assert {'unverified_number', 'unsupported_causal_claim'} <= codes(bad, 'blocker')
    good = gen(api, pid, 'sumario', external_consent=True)
    assert good['valid'] and good['provider'] == 'fake-externo'
    sent = _FakeExternal.sent[-1]
    blob = json.dumps(sent, ensure_ascii=False)
    assert 'content_hash' not in blob and 'Cliente Interpretação' not in blob and 'chave-sintetica' not in blob
    assert sent['instructions'].startswith('Você redige') and sent['context']['kind'] == 'EXECUTIVE_SUMMARY'
    prev = api.post(f'/api/presentations/{pid}/interpretations/context',
                    json={'slide_id': 'sumario', 'provider': 'fake-externo'}).json()
    assert prev['transmission']['transmitted'] is True and prev['transmission']['payload'] == sent


def test_unexpected_local_provider_failure_is_contained(api, demo, monkeypatch):
    def boom(self, ctx, *, consent=False):
        raise RuntimeError('falha sintética')
    monkeypatch.setattr(providers.DeterministicProvider, 'generate', boom)
    r = api.post(f'/api/presentations/{demo["pid"]}/interpretations', json={'slide_id': 'sumario', 'operator': OP})
    assert r.status_code == 502 and error_code(r) == 'provider_failed' and 'falha sintética' not in r.text
    assert api.get(f'/api/presentations/{demo["pid"]}/view').status_code == 200


def test_confidentiality_no_names_no_secrets_no_content_in_logs_or_audit(api, demo, caplog, db_url):
    pid = demo['pid']
    with caplog.at_level(logging.DEBUG, logger='afrika'):
        iv = gen(api, pid, 'top-apps', 'RANKING_HIGHLIGHTS', 'TECHNICAL', target_field='notes')
    names = [row['name'] for row in TOP_APPS['top']] + ['BU Sintética', 'Cliente Interpretação']
    detail = api.get(f'/api/presentations/{pid}/interpretations/{iv["id"]}').json()
    blob = json.dumps(detail, ensure_ascii=False)
    assert not any(n in blob for n in names)  # ranking por aplicação entra SEM rótulos
    assert detail['indicators'][0]['labels_redacted'] is True and 'não são usados' in iv['text']
    assert iv['text'] not in caplog.text and '30' not in ''.join(r.getMessage() for r in caplog.records
                                                                if 'interpreta' in r.getMessage())
    for bad in ('contato: pessoa@exemplo.com', 'ver https://exemplo.invalid/x', str(uuid.uuid4())):
        r = api.post(f'/api/presentations/{pid}/interpretations',
                     json={'slide_id': 'sumario', 'operator': OP, 'notes': [bad]})
        assert r.status_code == 422 and error_code(r) == 'editorial_note_sensitive'
        assert bad not in r.text
    from app import db
    engine = db.make_engine(db_url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT details_json FROM audit_events WHERE event_type LIKE 'interpretation.%'"))
            details = [r[0] for r in rows]
    finally:
        engine.dispose()
    assert details and all(iv['text'] not in d and 'Sintética' not in d for d in details)


def test_external_payload_refuses_sensitive_patterns():
    ctx = _ctx([_fact(), {'id': 'E1', 'type': 'editorial', 'text': 'token ' + 'a' * 48}])
    prov = providers.ExternalProvider(InterpretationSettings(external_enabled=True, api_key='k'), lambda: 0)
    with pytest.raises(providers.ProviderError) as exc:
        prov.generate(ctx, consent=True)
    assert exc.value.code == 'external_ai_payload_sensitive'


def test_provider_output_contract_is_strict():
    with pytest.raises(Exception):
        ProviderOutput.model_validate({'statements': [], 'provider': 'x'})
    with pytest.raises(Exception):
        ProviderOutput.model_validate({'statements': [{'text': 'a', 'fact_ids': ['m1; drop']}], 'provider': 'x'})
