"""F03 — validação REAL opt-in do motor de escopos e da reconciliação usuário–Team (mesmo portão de test_veracode_live).

Somente GET na allowlist da F02 (nenhum endpoint novo). Imprime apenas contagens e nomes de chaves — nunca nomes,
IDs ou valores do tenant. Nada é gravado. Rodar SEPARADO da suíte unitária:

    python -m pytest backend/tests_live -q -rs --run-veracode-live
"""
from collections import Counter

from app.scopes import rules
from app.veracode import adapters, discovery

from test_veracode_live import _collect, _report


def test_live_team_count_reconciliation(veracode_live_gate):
    async def fetch(run):
        users, teams = await adapters.fetch_users(run), await adapters.fetch_teams(run)
        members = await adapters.fetch_team_memberships(run, teams.items) if teams.complete else None
        return users, teams, members
    users, teams, members = _collect(veracode_live_gate, fetch)
    for c in (users, teams) + ((members,) if members else ()):
        _report(c)
    assert users.complete and teams.complete and members is not None and members.complete
    with_count = sum(m['team_count'] is not None for m in members.items)
    print(f'\nteam_count: vinculos={len(members.items)} com_team_count={with_count} '
          f'usuarios_lista_com_team_count={sum(u["team_count"] is not None for u in users.items)}')
    collected = Counter(m['user_id'] for m in members.items)
    reported = {}
    for m in members.items:
        if m['team_count'] is not None:
            reported.setdefault(m['user_id'], set()).add(m['team_count'])
    statuses = Counter(discovery._reconcile(True, collected[u['user_id']],
                                            reported.get(u['user_id']) or ({u['team_count']} if u['team_count']
                                                                            is not None else set()))
                       for u in users.items)
    print(f'reconciliação por usuário: {dict(sorted(statuses.items()))}')
    assert statuses['inconsistent'] == 0, 'team_count divergente de forma inconsistente'


def test_live_scope_engine_partitions_applications(veracode_live_gate):
    apps = _collect(veracode_live_gate, adapters.fetch_applications)
    _report(apps)
    assert apps.complete
    records = [rules.application_record(a) for a in apps.items]
    assert all(r['application.id'] for r in records)
    checks = {
        'all': rules.ALL,
        'team_is_empty': {'field': 'team.id', 'cmp': 'is_empty'},
        'bu_present': {'field': 'business_unit.id', 'cmp': 'is_present'},
        'not_team_empty_or_criticality': {'op': 'or', 'args': [
            {'op': 'not', 'arg': {'field': 'team.id', 'cmp': 'is_empty'}},
            {'field': 'business_criticality', 'cmp': 'in', 'values': ['VERY_HIGH', 'HIGH']}]},
    }
    for label, rule in checks.items():
        rule = rules.validate('applications', rule).rule
        outs = Counter(rules.evaluate('applications', rule, r).value for r in records)
        print(f'regra={label}: incluídas={outs[True]} excluídas={outs[False]} indeterminadas={outs[None]}')
        assert sum(outs.values()) == len(records)
    assert Counter(rules.evaluate('applications', rules.ALL, r).value for r in records)[True] == len(records)
