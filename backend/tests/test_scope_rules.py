"""F03 — motor de filtros: validação do AST (limites), canonização e avaliação em lógica de 3 valores (Kleene)."""
import random
import uuid

import pytest

from app.scopes import rules
from app.scopes.rules import Partial

T1, T2, T3 = (str(uuid.uuid5(uuid.NAMESPACE_DNS, f'team{i}')) for i in range(3))
BU1, BU2 = (str(uuid.uuid5(uuid.NAMESPACE_DNS, f'bu{i}')) for i in range(2))
APP = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'app'))


def leaf(field, cmp_, value=None, values=None, **extra):
    node = {'field': field, 'cmp': cmp_, **extra}
    if isinstance(value, list):
        value, values = None, value
    if value is not None:
        node['value'] = value
    if values is not None:
        node['values'] = values
    return node


def ok(domain, rule) -> dict:
    v = rules.validate(domain, rule)
    assert v.valid, v.issues
    return v.rule


def issues(domain, rule) -> list[str]:
    v = rules.validate(domain, rule)
    assert not v.valid
    return [i.code for i in v.issues]


def app(**over):
    base = {'guid': APP, 'name': 'Portal Sintético', 'business_unit': {'guid': BU1}, 'teams': [{'guid': T1}],
            'tags': 'web, api', 'business_criticality': 'HIGH', 'custom_fields': [{'name': 'Ambiente',
                                                                                   'value': 'Produção'}],
            'policies': []}
    base.update(over)
    return rules.application_record(base)


def ev(rule, record, domain='applications'):
    return rules.evaluate(domain, ok(domain, rule), record).value


# ---------------------------------------------------------------- validação

def test_valid_nested_rule_is_canonicalized():
    rule = {'op': 'and', 'args': [
        leaf('business_unit.id', 'eq', BU1.upper()),
        {'op': 'or', 'args': [leaf('team.id', 'in', [T2, T1, T1.upper()]),
                              {'op': 'not', 'arg': leaf('tag', 'in', ['web'])}]},
        leaf('custom_field', 'eq', ' Produção ', key=' Ambiente ')]}
    canon = ok('applications', rule)
    assert canon['args'][0]['value'] == BU1  # IDs minúsculos
    assert canon['args'][1]['args'][0]['values'] == sorted([T1, T2])  # sem duplicatas, ordenado
    assert canon['args'][2] == {'field': 'custom_field', 'cmp': 'eq', 'key': 'Ambiente', 'value': 'Produção'}
    assert rules.rule_hash(canon) == rules.rule_hash(ok('applications', canon))  # idempotente


@pytest.mark.parametrize('rule, code', [
    ([], 'type'),
    ({'op': 'xor', 'args': []}, 'op'),
    ({'op': 'and', 'args': []}, 'args'),
    ({'op': 'all', 'args': []}, 'extra'),
    (leaf('team.name', 'eq', 'Time A'), 'field'),
    (leaf('team.id', 'eq', 'Time A'), 'value'),  # nome no lugar de ID: recusado
    (leaf('team.id', 'contains', T1), 'cmp'),
    (leaf('business_criticality', 'eq', 'ALTISSIMA'), 'value'),
    (leaf('custom_field', 'eq', 'x'), 'missing'),  # sem `key`
    ({'field': 'name', 'cmp': 'eq', 'value': 'a', 'values': ['b']}, 'extra'),
    (leaf('name', 'eq', 'a\x00b'), 'value'),
    (leaf('team.id', 'in', []), 'values'),
])
def test_invalid_rules_are_rejected(rule, code):
    assert code in issues('applications', rule)


def test_domains_do_not_share_fields():
    # BU/criticidade não existem em usuários; Team em usuários não é Team de aplicações.
    assert 'field' in issues('users', leaf('business_unit.id', 'eq', BU1))
    assert 'field' in issues('applications', leaf('active', 'eq', True))
    assert 'field' in issues('scans', leaf('team.id', 'in', [T1]))
    ok('users', leaf('team.id', 'in', [T1]))
    ok('scans', leaf('scan.context', 'eq', 'policy'))
    ok('sca', leaf('application.in_scope', 'eq', True))


def test_depth_nodes_values_and_size_limits():
    deep = leaf('name', 'eq', 'x')
    for _ in range(rules.MAX_DEPTH):
        deep = {'op': 'not', 'arg': deep}
    assert 'depth' in issues('applications', deep)

    wide = {'op': 'or', 'args': [{'op': 'and', 'args': [leaf('name', 'eq', f'n{i}{j}') for j in range(30)]}
                                 for i in range(5)]}
    assert 'complexity' in issues('applications', wide)
    assert 'complexity' in issues('applications', {'op': 'or', 'args': [leaf('name', 'eq', 'x')] * 41})
    many = [str(uuid.uuid4()) for _ in range(rules.MAX_VALUES + 1)]
    assert 'values' in issues('applications', leaf('application.id', 'in', many))
    huge = leaf('name', 'in', ['x' * 199 + str(i) for i in range(400)])
    assert 'complexity' in issues('applications', huge)  # > MAX_RULE_BYTES


# ---------------------------------------------------------------- avaliação

def test_equality_inclusion_exclusion_by_id():
    assert ev(leaf('business_unit.id', 'eq', BU1), app()) is True
    assert ev(leaf('business_unit.id', 'neq', BU1), app()) is False
    assert ev(leaf('team.id', 'in', [T2, T1]), app()) is True
    assert ev(leaf('team.id', 'not_in', [T1]), app()) is False
    assert ev(leaf('application.id', 'in', [APP]), app()) is True
    assert ev(leaf('tag', 'in', ['WEB']), app()) is True  # tags sem diferenciar caixa
    assert ev(leaf('name', 'contains', 'portal'), app()) is True
    assert ev(leaf('custom_field', 'eq', 'produção', key='ambiente'), app()) is True
    assert ev(leaf('business_criticality', 'in', ['HIGH', 'VERY_HIGH']), app()) is True


def test_missing_fields_are_undetermined_not_false():
    no_teams = app(teams=None)
    assert ev(leaf('team.id', 'in', [T1]), no_teams) is None
    assert ev({'op': 'not', 'arg': leaf('team.id', 'in', [T1])}, no_teams) is None
    assert ev(leaf('team.id', 'is_missing'), no_teams) is True
    out = rules.evaluate('applications', ok('applications', leaf('team.id', 'in', [T1])), no_teams)
    assert out.missing == {'team.id'}
    # lista vazia conhecida != ausente
    assert ev(leaf('team.id', 'in', [T1]), app(teams=[])) is False
    assert ev(leaf('team.id', 'is_empty'), app(teams=[])) is True
    # Team sem ID na resposta: identidade desconhecida (nunca casar por nome)
    assert ev(leaf('team.id', 'in', [T1]), app(teams=[{'guid': None, 'name': 'Time'}])) is None
    assert ev(leaf('business_unit.id', 'eq', BU1), app(business_unit=None)) is None
    assert ev(leaf('custom_field', 'eq', 'x', key='Inexistente'), app()) is None
    assert ev(leaf('custom_field', 'is_missing', key='Inexistente'), app()) is True
    # Kleene: FALSE decide o AND e TRUE decide o OR mesmo com indeterminados
    assert ev({'op': 'and', 'args': [leaf('team.id', 'in', [T1]), leaf('name', 'eq', 'Outro')]}, no_teams) is False
    assert ev({'op': 'or', 'args': [leaf('team.id', 'in', [T1]), leaf('name', 'contains', 'portal')]},
              no_teams) is True


def test_partial_membership_proves_presence_only():
    rec = {'user.id': APP, 'team.id': Partial((T1,)), 'active': True}
    assert ev(leaf('team.id', 'in', [T1]), rec, 'users') is True
    assert ev(leaf('team.id', 'in', [T2]), rec, 'users') is None  # pode estar num Team não visível
    assert ev(leaf('team.id', 'not_in', [T1]), rec, 'users') is False
    assert ev(leaf('team.id', 'not_in', [T2]), rec, 'users') is None
    assert ev(leaf('team.id', 'is_empty'), rec, 'users') is False


def test_nested_and_or_not():
    rule = {'op': 'or', 'args': [
        {'op': 'and', 'args': [leaf('business_unit.id', 'eq', BU1),
                               {'op': 'not', 'arg': leaf('team.id', 'in', [T2])}]},
        {'op': 'and', 'args': [leaf('business_unit.id', 'eq', BU2), leaf('tag', 'in', ['api'])]}]}
    assert ev(rule, app()) is True
    assert ev(rule, app(teams=[{'guid': T2}])) is False
    assert ev(rule, app(business_unit={'guid': BU2}, teams=[{'guid': T2}])) is True
    assert ev(rule, app(business_unit={'guid': BU2}, tags='web')) is False
    assert ev({'op': 'not', 'arg': rule}, app(business_unit={'guid': BU2}, tags='web')) is True


# ---------------------------------------------------------------- propriedades (geração determinística)

_K = {True: 1.0, None: 0.5, False: 0.0}


def _random_rule(rnd: random.Random, depth: int):
    if depth == 0 or rnd.random() < 0.3:
        return rnd.choice([leaf('team.id', 'in', [rnd.choice([T1, T2, T3])]),
                           leaf('business_unit.id', 'eq', rnd.choice([BU1, BU2])),
                           leaf('tag', 'in', [rnd.choice(['web', 'api', 'x'])]),
                           leaf('team.id', 'is_empty')])
    op = rnd.choice(['and', 'or', 'not'])
    if op == 'not':
        return {'op': 'not', 'arg': _random_rule(rnd, depth - 1)}
    return {'op': op, 'args': [_random_rule(rnd, depth - 1) for _ in range(rnd.randint(1, 3))]}


def _reference(rule, record) -> float:
    """Kleene como min/max sobre {0, ½, 1}, independente do motor."""
    if 'op' in rule:
        if rule['op'] == 'not':
            return 1 - _reference(rule['arg'], record)
        vals = [_reference(a, record) for a in rule['args']]
        return min(vals) if rule['op'] == 'and' else max(vals)
    return _K[rules.evaluate('applications', rule, record).value]


def _random_record(rnd: random.Random) -> dict:
    teams = rnd.choice([None, [], [{'guid': T1}], [{'guid': T2}, {'guid': T3}]])
    bu = rnd.choice([None, {'guid': BU1}, {'guid': BU2}])
    tags = rnd.choice([None, '', 'web', 'api,web'])
    return app(teams=teams, business_unit=bu, tags=tags)


def test_property_engine_matches_kleene_reference_and_de_morgan():
    rnd = random.Random(20261014)
    for _ in range(400):
        rule = ok('applications', _random_rule(rnd, 4))
        rec = _random_record(rnd)
        got = rules.evaluate('applications', rule, rec).value
        assert _K[got] == _reference(rule, rec)
        assert rules.evaluate('applications', {'op': 'not', 'arg': {'op': 'not', 'arg': rule}}, rec).value == got
        other = ok('applications', _random_rule(rnd, 2))
        lhs = rules.evaluate('applications', {'op': 'not', 'arg': {'op': 'and', 'args': [rule, other]}}, rec).value
        rhs = rules.evaluate('applications', {'op': 'or', 'args': [{'op': 'not', 'arg': rule},
                                                                    {'op': 'not', 'arg': other}]}, rec).value
        assert lhs == rhs
        # `all` é neutro do AND e absorvente do OR
        assert rules.evaluate('applications', {'op': 'and', 'args': [rules.ALL, rule]}, rec).value == got
        assert rules.evaluate('applications', {'op': 'or', 'args': [rules.ALL, rule]}, rec).value is True


def test_fields_catalog_lists_domains_and_limits():
    cat = rules.fields_catalog()
    assert set(cat['domains']) == {'applications', 'users', 'scans', 'sca'}
    assert cat['domains']['scans']['evaluable'] is False and cat['domains']['users']['evaluable'] is True
    assert cat['limits']['max_depth'] == rules.MAX_DEPTH
