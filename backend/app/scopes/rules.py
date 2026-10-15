"""Motor de filtros (F03): AST de regras por domínio, validação com limites e avaliação em lógica de 3 valores.

Gramática (JSON):
  {"op": "all"}                                   -> verdadeiro (todo o universo disponível)
  {"op": "and" | "or", "args": [nó, ...]}         -> grupo
  {"op": "not", "arg": nó}                        -> negação
  {"field": F, "cmp": C, "value": v}              -> eq | neq | contains | not_contains
  {"field": F, "cmp": C, "values": [v, ...]}      -> in | not_in
  {"field": F, "cmp": C}                          -> is_missing | is_present | is_empty
  `custom_field` exige também "key" (nome do campo personalizado).

Campos ausentes: valor desconhecido (None) torna a comparação INDETERMINADA (None), nunca falsa nem verdadeira.
AND/OR/NOT seguem a lógica de Kleene. Resultado indeterminado não inclui o recurso: ele é reportado à parte
com os campos que faltaram. Lista vazia conhecida ([]) é diferente de ausente (None).
Relacionamentos (BU, Team, aplicação, usuário, política) são SEMPRE por identificador; nome só é critério textual.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

MAX_DEPTH = 6
MAX_NODES = 120
MAX_GROUP_ARGS = 40
MAX_VALUES = 500
MAX_TOTAL_VALUES = 2000
MAX_STRING = 200
MAX_RULE_BYTES = 64_000

TRUE, FALSE, UNKNOWN = True, False, None

_UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
_CONTROL = re.compile(r'[\x00-\x1f\x7f]')

ALL = {'op': 'all'}
GROUP_OPS = ('and', 'or')
VALUE_CMPS = ('eq', 'neq', 'contains', 'not_contains')
LIST_CMPS = ('in', 'not_in')
PRESENCE_CMPS = ('is_missing', 'is_present', 'is_empty')


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    type: str  # id | string | enum | bool
    multi: bool
    cmps: tuple[str, ...]
    enum: tuple[str, ...] | None = None
    keyed: bool = False
    note: str = ''

    def public(self) -> dict:
        return {'name': self.name, 'label': self.label, 'type': self.type, 'multi': self.multi,
                'cmps': list(self.cmps), 'enum': list(self.enum) if self.enum else None, 'keyed': self.keyed,
                'note': self.note}


_ID_CMPS = ('eq', 'neq', 'in', 'not_in')
_ID_OPT = _ID_CMPS + ('is_missing', 'is_present')
_MULTI_ID = _ID_CMPS + ('is_missing', 'is_present', 'is_empty')
_TEXT = ('eq', 'neq', 'contains', 'not_contains', 'in', 'not_in', 'is_missing', 'is_present')
_CRITICALITY = ('VERY_HIGH', 'HIGH', 'MEDIUM', 'LOW', 'VERY_LOW')


def _specs(*specs: FieldSpec) -> dict[str, FieldSpec]:
    return {s.name: s for s in specs}


# Campos por domínio. Domínios NÃO compartilham regras: um Team em `users` não seleciona aplicações.
FIELDS: dict[str, dict[str, FieldSpec]] = {
    'applications': _specs(
        FieldSpec('application.id', 'Aplicação (GUID)', 'id', False, _ID_CMPS),
        FieldSpec('business_unit.id', 'Business Unit (ID)', 'id', False, _ID_OPT,
                  note='Uma BU por aplicação no perfil Veracode'),
        FieldSpec('team.id', 'Team (ID)', 'id', True, _MULTI_ID),
        FieldSpec('name', 'Nome da aplicação', 'string', False, _TEXT, note='Critério textual, não identidade'),
        FieldSpec('tag', 'Tag', 'string', True, _ID_CMPS + ('is_missing', 'is_present', 'is_empty')),
        FieldSpec('business_criticality', 'Criticidade', 'enum', False, _ID_OPT, enum=_CRITICALITY),
        FieldSpec('custom_field', 'Campo personalizado', 'string', True, _TEXT, keyed=True),
        FieldSpec('policy.id', 'Política (GUID)', 'id', True, _MULTI_ID),
    ),
    'users': _specs(
        FieldSpec('user.id', 'Usuário (ID)', 'id', False, _ID_CMPS),
        FieldSpec('team.id', 'Team (ID)', 'id', True, _MULTI_ID,
                  note='Vínculo pelo detalhe do Team (Identity API); não seleciona aplicações'),
        FieldSpec('active', 'Ativo', 'bool', False, ('eq', 'is_missing', 'is_present')),
    ),
    # scans/SCA: regras só armazenadas e validadas; avaliação real fica para a F04.
    'scans': _specs(
        FieldSpec('application.id', 'Aplicação (GUID)', 'id', False, _ID_CMPS),
        FieldSpec('application.in_scope', 'Aplicação no escopo de aplicações', 'bool', False, ('eq',),
                  note='Vínculo explícito com o escopo de aplicações do mesmo dono'),
        FieldSpec('scan.context', 'Contexto do scan', 'enum', False, _ID_CMPS, enum=('policy', 'sandbox'),
                  note='Policy = produção; Sandbox = desenvolvimento (convenção inicial)'),
        FieldSpec('scan.type', 'Tipo de scan', 'enum', False, _ID_CMPS, enum=('STATIC', 'DYNAMIC', 'MANUAL')),
    ),
    'sca': _specs(
        FieldSpec('application.id', 'Aplicação (GUID)', 'id', False, _ID_CMPS),
        FieldSpec('application.in_scope', 'Aplicação no escopo de aplicações', 'bool', False, ('eq',)),
        FieldSpec('sca.dependency', 'Dependência', 'enum', False, _ID_CMPS, enum=('direct', 'transitive')),
    ),
}
EVALUABLE_DOMAINS = ('applications', 'users')


@dataclass
class Issue:
    path: str
    code: str
    message: str

    def as_dict(self) -> dict:
        return {'field': self.path, 'type': self.code, 'message': self.message}


class RuleError(ValueError):
    def __init__(self, issues: list[Issue]):
        super().__init__(issues[0].message if issues else 'regra inválida')
        self.issues = issues


@dataclass
class _Budget:
    nodes: int = 0
    values: int = 0
    max_depth: int = 0


def _canon_value(spec: FieldSpec, v: Any, path: str, issues: list[Issue]) -> Any:
    if spec.type == 'bool':
        if not isinstance(v, bool):
            issues.append(Issue(path, 'type', 'esperado true/false'))
        return v
    if not isinstance(v, str):
        issues.append(Issue(path, 'type', 'esperado texto'))
        return v
    v = v.strip()
    if not v or len(v) > MAX_STRING or _CONTROL.search(v):
        issues.append(Issue(path, 'value', f'texto de 1 a {MAX_STRING} caracteres, sem caracteres de controle'))
    elif spec.type == 'id':
        v = v.lower()
        if not _UUID.match(v):
            issues.append(Issue(path, 'value', 'identificador inválido: use o ID/GUID da Veracode, não o nome'))
    elif spec.type == 'enum' and v not in spec.enum:
        issues.append(Issue(path, 'value', f'valor fora da lista: {", ".join(spec.enum)}'))
    return v


def _node(domain: str, node: Any, path: str, depth: int, budget: _Budget, issues: list[Issue]) -> Any:
    budget.nodes += 1
    budget.max_depth = max(budget.max_depth, depth)
    if depth > MAX_DEPTH:
        issues.append(Issue(path, 'depth', f'profundidade máxima {MAX_DEPTH} excedida'))
        return None
    if budget.nodes > MAX_NODES:
        if budget.nodes == MAX_NODES + 1:
            issues.append(Issue(path, 'complexity', f'máximo de {MAX_NODES} nós por regra'))
        return None
    if not isinstance(node, dict):
        issues.append(Issue(path, 'type', 'nó deve ser um objeto'))
        return None
    if 'op' in node:
        return _group(domain, node, path, depth, budget, issues)
    return _leaf(domain, node, path, budget, issues)


def _group(domain, node, path, depth, budget, issues):
    op = node.get('op')
    allowed = {'all': {'op'}, 'and': {'op', 'args'}, 'or': {'op', 'args'}, 'not': {'op', 'arg'}}
    if op not in allowed:
        issues.append(Issue(f'{path}.op', 'op', 'operador deve ser all, and, or ou not'))
        return None
    extra = set(node) - allowed[op]
    if extra:
        issues.append(Issue(path, 'extra', f'chaves não permitidas: {", ".join(sorted(extra))}'))
    if op == 'all':
        return dict(ALL)
    if op == 'not':
        return {'op': 'not', 'arg': _node(domain, node.get('arg'), f'{path}.arg', depth + 1, budget, issues)}
    args = node.get('args')
    if not isinstance(args, list) or not args:
        issues.append(Issue(f'{path}.args', 'args', 'grupo precisa de ao menos uma condição'))
        return None
    if len(args) > MAX_GROUP_ARGS:
        issues.append(Issue(f'{path}.args', 'complexity', f'máximo de {MAX_GROUP_ARGS} condições por grupo'))
        return None
    return {'op': op, 'args': [_node(domain, a, f'{path}.args[{i}]', depth + 1, budget, issues)
                               for i, a in enumerate(args)]}


def _leaf(domain, node, path, budget, issues):
    spec = FIELDS[domain].get(node.get('field'))
    if spec is None:
        issues.append(Issue(f'{path}.field', 'field', f'campo não suportado no domínio {domain}'))
        return None
    cmp_ = node.get('cmp')
    if cmp_ not in spec.cmps:
        issues.append(Issue(f'{path}.cmp', 'cmp', f'comparação não suportada para {spec.name}: '
                                                  f'{", ".join(spec.cmps)}'))
        return None
    keys = {'field', 'cmp'} | ({'key'} if spec.keyed else set()) | (
        {'value'} if cmp_ in VALUE_CMPS else {'values'} if cmp_ in LIST_CMPS else set())
    extra, missing = set(node) - keys, keys - set(node)
    if extra:
        issues.append(Issue(path, 'extra', f'chaves não permitidas: {", ".join(sorted(extra))}'))
    if missing:
        issues.append(Issue(path, 'missing', f'chaves obrigatórias ausentes: {", ".join(sorted(missing))}'))
        return None
    out: dict[str, Any] = {'field': spec.name, 'cmp': cmp_}
    if spec.keyed:
        key = node['key']
        if not isinstance(key, str) or not key.strip() or len(key) > MAX_STRING or _CONTROL.search(key):
            issues.append(Issue(f'{path}.key', 'value', 'nome do campo personalizado inválido'))
        else:
            out['key'] = key.strip()
    if cmp_ in VALUE_CMPS:
        out['value'] = _canon_value(spec, node['value'], f'{path}.value', issues)
        budget.values += 1
    elif cmp_ in LIST_CMPS:
        values = node['values']
        if not isinstance(values, list) or not values or len(values) > MAX_VALUES:
            issues.append(Issue(f'{path}.values', 'values', f'lista com 1 a {MAX_VALUES} valores'))
            return None
        budget.values += len(values)
        if budget.values > MAX_TOTAL_VALUES:
            issues.append(Issue(f'{path}.values', 'complexity', f'máximo de {MAX_TOTAL_VALUES} valores por regra'))
            return None
        canon = [_canon_value(spec, v, f'{path}.values[{i}]', issues) for i, v in enumerate(values)]
        out['values'] = sorted(set(canon), key=str) if all(isinstance(v, (str, bool)) for v in canon) else canon
    return out


@dataclass
class Validation:
    rule: dict | None
    issues: list[Issue]
    nodes: int
    depth: int
    values: int

    @property
    def valid(self) -> bool:
        return not self.issues

    def as_dict(self) -> dict:
        return {'valid': self.valid, 'issues': [i.as_dict() for i in self.issues],
                'complexity': {'nodes': self.nodes, 'depth': self.depth, 'values': self.values,
                               'limits': LIMITS},
                'rule': self.rule if self.valid else None, 'rule_hash': rule_hash(self.rule) if self.valid else None}


LIMITS = {'max_depth': MAX_DEPTH, 'max_nodes': MAX_NODES, 'max_group_args': MAX_GROUP_ARGS,
          'max_values': MAX_VALUES, 'max_total_values': MAX_TOTAL_VALUES, 'max_string': MAX_STRING,
          'max_rule_bytes': MAX_RULE_BYTES}


def validate(domain: str, rule: Any) -> Validation:
    """Valida e canoniza (IDs minúsculos, listas sem duplicatas e ordenadas). Nunca avalia nada."""
    if domain not in FIELDS:
        return Validation(None, [Issue('domain', 'domain', 'domínio inválido')], 0, 0, 0)
    try:
        size = len(json.dumps(rule, ensure_ascii=False))
    except (TypeError, ValueError):
        return Validation(None, [Issue('rule', 'type', 'regra não serializável')], 0, 0, 0)
    if size > MAX_RULE_BYTES:
        return Validation(None, [Issue('rule', 'complexity', f'regra maior que {MAX_RULE_BYTES} bytes')], 0, 0, 0)
    issues: list[Issue] = []
    budget = _Budget()
    canon = _node(domain, rule, 'rule', 1, budget, issues)
    return Validation(None if issues else canon, issues, budget.nodes, budget.max_depth, budget.values)


def canonical_json(rule: dict) -> str:
    return json.dumps(rule, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def rule_hash(rule: dict | None) -> str | None:
    return None if rule is None else hashlib.sha256(canonical_json(rule).encode()).hexdigest()


# ---------------------------------------------------------------- avaliação

@dataclass(frozen=True)
class Partial:
    """Lista sabidamente incompleta (ex.: usuário em Teams não visíveis): presença prova; ausência não."""
    items: tuple


@dataclass
class Outcome:
    value: bool | None
    missing: set[str] = field(default_factory=set)


def _present(spec: FieldSpec, raw: Any, key: str | None) -> Any:
    if spec.keyed:
        if raw is None:
            return None
        values = [v for k, v in raw if k is not None and k.casefold() == key.casefold()]
        return values or None  # campo personalizado não preenchido = ausente
    return raw


def _norm(spec: FieldSpec, v: Any) -> Any:
    return v.casefold() if spec.type in ('string',) and isinstance(v, str) else v


def _leaf_eval(spec: FieldSpec, node: dict, raw: Any) -> bool | None:
    cmp_ = node['cmp']
    v = _present(spec, raw, node.get('key'))
    if cmp_ == 'is_missing':
        return v is None
    if cmp_ == 'is_present':
        return v is not None
    if v is None:
        return UNKNOWN
    partial = isinstance(v, Partial)
    items = list(v.items) if partial else (v if spec.multi or spec.keyed else [v])
    items = [_norm(spec, i) for i in items if i is not None]
    if cmp_ == 'is_empty':
        return False if items else (UNKNOWN if partial else True)
    if cmp_ in ('contains', 'not_contains'):
        needle = _norm(spec, node['value'])
        hit = any(isinstance(i, str) and needle in i for i in items)
    else:
        wanted = {_norm(spec, x) for x in (node['values'] if cmp_ in LIST_CMPS else [node['value']])}
        hit = any(i in wanted for i in items)
    positive = cmp_ in ('eq', 'in', 'contains')
    if partial and not hit:
        return UNKNOWN  # o item que faltou poderia casar
    return hit if positive else not hit


def evaluate(domain: str, rule: dict, record: dict[str, Any]) -> Outcome:
    """Avalia regra JÁ VALIDADA sobre um registro {campo: valor|None|Partial}. Kleene para AND/OR/NOT."""
    specs = FIELDS[domain]

    def ev(node: dict) -> Outcome:
        op = node.get('op')
        if op == 'all':
            return Outcome(TRUE)
        if op == 'not':
            inner = ev(node['arg'])
            return Outcome(None if inner.value is None else not inner.value, inner.missing)
        if op in GROUP_OPS:
            outs = [ev(a) for a in node['args']]
            values = [o.value for o in outs]
            decisive = FALSE if op == 'and' else TRUE
            if decisive in values:
                return Outcome(decisive)
            if None in values:
                return Outcome(None, set().union(*(o.missing for o in outs if o.value is None)))
            return Outcome(not decisive)
        spec = specs[node['field']]
        value = _leaf_eval(spec, node, record.get(spec.name))
        label = spec.name if not spec.keyed else f"{spec.name}:{node['key']}"
        return Outcome(value, {label} if value is None else set())

    return ev(rule)


# ---------------------------------------------------------------- registros por domínio

def _lower(v) -> str | None:
    return v.lower() if isinstance(v, str) else None


def _id_list(refs: list[dict] | None, key: str) -> list[str] | None:
    """Lista de IDs; se algum item vier sem ID, a lista é desconhecida (nunca casar por nome)."""
    if refs is None:
        return None
    ids = [_lower(r.get(key)) for r in refs]
    return None if any(i is None for i in ids) else ids


def application_record(app: dict) -> dict[str, Any]:
    bu = app.get('business_unit')
    tags = app.get('tags')
    custom = app.get('custom_fields')
    return {
        'application.id': _lower(app.get('guid')),
        'business_unit.id': None if bu is None else _lower(bu.get('guid')),
        'team.id': _id_list(app.get('teams'), 'guid'),
        'name': app.get('name'),
        'tag': None if tags is None else [t.strip() for t in tags.split(',') if t.strip()],
        'business_criticality': app.get('business_criticality'),
        'custom_field': None if custom is None else [(c.get('name'), c.get('value')) for c in custom
                                                    if c.get('value') is not None],
        'policy.id': _id_list(app.get('policies'), 'guid'),
    }


def user_record(row: dict) -> dict[str, Any]:
    """`row` = linha de user_relationships: {'user': {...}, 'teams': [...]|None, 'teams_complete': bool}."""
    user, teams = row['user'], row.get('teams')
    team_ids = None if teams is None else [_lower(t.get('team_id')) for t in teams]
    if team_ids is not None and any(t is None for t in team_ids):
        team_ids = None
    if team_ids is not None and row.get('teams_complete') is False:
        team_ids = Partial(tuple(team_ids))
    return {'user.id': _lower(user.get('user_id')), 'team.id': team_ids, 'active': user.get('active')}


def fields_catalog() -> dict:
    return {'domains': {d: {'fields': [s.public() for s in specs.values()],
                            'evaluable': d in EVALUABLE_DOMAINS} for d, specs in FIELDS.items()},
            'limits': LIMITS,
            'operators': {'groups': ['and', 'or', 'not', 'all'], 'value': list(VALUE_CMPS),
                          'list': list(LIST_CMPS), 'presence': list(PRESENCE_CMPS)}}
