"""Resolução dos escopos de um cliente (F03) sobre a descoberta Veracode da F02 (somente leitura, cache por conexão).

Semântica:
- O cliente principal define o UNIVERSO do domínio (sem regra ativa => universo não definido; nunca "tenant inteiro"
  implícito).
- Subcliente com a MESMA conexão do cliente (herdada ou igual): resultado = critérios próprios ∩ universo.
- Subcliente com conexão PRÓPRIA diferente: avaliado só no próprio tenant, se a abrangência foi confirmada
  (`coverage_ack`); nunca entra na interseção, na sobreposição nem nas não classificadas do cliente.
- Recursos podem pertencer a vários subclientes (sobreposição reportada, nunca removida).
- Não classificadas = universo − ∪(subclientes ativos com a mesma conexão), por identificador.
- Indeterminados (campo ausente) não são incluídos e tornam as não classificadas incompletas.
- Coleta incompleta => `complete=false`: nada é apresentado como validado.
- Domínios não compartilham regras; scans/SCA são só validados (consulta real na F04).
Nenhum recurso Veracode é gravado: tudo vem do cache transitório da descoberta.
"""
from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from app.scopes import rules
from app.scopes.store import OwnerRule
from app.veracode.discovery import DiscoveryService, Result, ScopeContext
from app.veracode.errors import VeracodeError

MAX_SAMPLE = 200

_WARNINGS = {
    'no_subclients': 'Cliente sem subclientes ativos: todo o universo aparece como não classificado.',
    'universe_not_defined': 'O cliente principal não tem escopo ativo neste domínio: universo não definido.',
    'collection_incomplete': 'Coleta Veracode incompleta: contagens NÃO validadas.',
    'universe_undetermined': 'Há recursos com campos ausentes no critério do cliente (indeterminados).',
    'undetermined_in_subclients': 'Há recursos indeterminados em subclientes: não classificadas podem estar '
                                  'superestimadas.',
    'subclients_without_scope': 'Há subclientes ativos sem escopo ativo neste domínio.',
    'separate_tenant_subclients': 'Há subclientes em outra conexão: avaliados à parte, fora das não classificadas.',
    'coverage_unconfirmed': 'Há subclientes em outra conexão sem confirmação de abrangência: não avaliados.',
    'connection_changed': 'A conexão de algum subcliente mudou desde a versão salva: salve uma nova versão.',
    'inactive_subclients_ignored': 'Subclientes inativos não classificam recursos.',
    'membership_unverified': 'Vínculos usuário–Team sem reconciliação completa (ver reconciliação).',
}
# Avisos que tornam as não classificadas incompletas.
_BLOCKING = {'collection_incomplete', 'universe_undetermined', 'undetermined_in_subclients',
             'subclients_without_scope', 'coverage_unconfirmed', 'connection_changed'}


@dataclass
class Item:
    id: str
    name: str | None
    record: dict
    active: bool | None = None


@dataclass
class Dataset:
    items: list[Item]
    sources: list[Result]
    extra: dict = field(default_factory=dict)  # users: teams, summary

    @property
    def complete(self) -> bool:
        return all(s.collection.complete for s in self.sources)


@dataclass
class Evaluation:
    included: set[str]
    excluded: set[str]
    undetermined: dict[str, set[str]]
    inactive: set[str] = field(default_factory=set)


async def load_dataset(service: DiscoveryService, ctx: ScopeContext, domain: str) -> Dataset:
    if domain == 'applications':
        res = await service.applications(ctx)
        return Dataset([Item(a['guid'].lower(), a['name'], rules.application_record(a))
                        for a in res.collection.items if isinstance(a.get('guid'), str)], [res])
    rows, summary, sources = await service.user_relationships(ctx)
    teams = sources[1].collection.items
    return Dataset([Item(r['user']['user_id'].lower(), r['user']['user_name'], rules.user_record(r),
                         r['user']['active']) for r in rows if isinstance(r['user'].get('user_id'), str)],
                   sources, {'summary': summary, 'teams': teams, 'rows': rows})


def evaluate(domain: str, rule: dict, options: dict, data: Dataset) -> Evaluation:
    ev = Evaluation(set(), set(), {})
    exclude_inactive = domain == 'users' and options.get('inactive_users', 'exclude') == 'exclude'
    for it in data.items:
        out = rules.evaluate(domain, rule, it.record)
        if out.value is True and exclude_inactive and it.active is not True:
            if it.active is False:
                ev.inactive.add(it.id)
            else:
                ev.undetermined[it.id] = {'active'}
        elif out.value is True:
            ev.included.add(it.id)
        elif out.value is False:
            ev.excluded.add(it.id)
        else:
            ev.undetermined[it.id] = out.missing
    return ev


def _sample(ids, names: dict[str, str | None], limit: int) -> list[dict]:
    rows = sorted(((names.get(i) or '', i) for i in ids), key=lambda r: (r[0].casefold(), r[1]))
    return [{'id': i, 'name': n or None} for n, i in rows[:limit]]


def _missing_counts(undetermined: dict[str, set[str]]) -> dict[str, int]:
    c = Counter(f for fields in undetermined.values() for f in fields)
    return dict(sorted(c.items()))


def _users_per_team(domain: str, data: Dataset, ids: set[str]) -> dict | None:
    if domain != 'users':
        return None
    summary = data.extra['summary']
    per_team_known = summary['members_per_team']
    members: dict[str, set[str]] = defaultdict(set)
    for row in data.extra['rows']:
        uid = (row['user'].get('user_id') or '').lower()
        if uid in ids:
            for t in row['teams'] or []:
                members[str(t['team_id'])].add(uid)
    teams = []
    for t in data.extra['teams']:
        tid = str(t['team_id'])
        known = per_team_known.get(tid) is not None and data.complete
        teams.append({'team_id': tid, 'name': t.get('name'), 'unique_users': len(members[tid]) if known else None})
    complete = data.complete and summary['members_per_team_complete']
    return {'complete': complete,
            'reason': None if complete else 'Detalhe de algum Team não foi obtido: contagem indisponível',
            'teams': sorted((t for t in teams if t['unique_users'] != 0), key=lambda t: ((t['name'] or '').casefold(),
                                                                                       t['team_id'])),
            'unique_users_total': len(ids) if complete else None}


def _owner_head(o: OwnerRule) -> dict:
    return {'kind': o.owner.kind, 'id': str(o.owner.id), 'name': o.owner.name,
            'effective_active': o.owner.effective_active, 'connection_mode': o.mode, 'scope_status': o.status,
            'version': o.version, 'draft': o.draft, 'options': o.options}


def _counts(ev: Evaluation, names, limit: int, domain: str, data: Dataset, ids: set[str] | None = None) -> dict:
    ids = ev.included if ids is None else ids
    out = {'included': len(ids), 'excluded': len(ev.excluded), 'undetermined': len(ev.undetermined),
           'missing_fields': _missing_counts(ev.undetermined), 'sample': _sample(ids, names, limit)}
    if domain == 'users':
        out['inactive_excluded'] = len(ev.inactive)
        out['users_per_team'] = _users_per_team(domain, data, ids)
    return out


async def resolve_client(service: DiscoveryService, client_ctx: ScopeContext, client: OwnerRule,
                         subs: list[OwnerRule], sub_ctx: dict[uuid.UUID, ScopeContext], domain: str,
                         sample_limit: int) -> dict:
    limit = max(0, min(sample_limit, MAX_SAMPLE))
    head = {'client': client_ctx.info(), 'domain': domain, 'evaluable': domain in rules.EVALUABLE_DOMAINS}
    warnings: list[str] = []
    active_subs = [s for s in subs if s.owner.effective_active]
    if not active_subs:
        warnings.append('no_subclients')
    if len(active_subs) != len(subs):
        warnings.append('inactive_subclients_ignored')

    if domain not in rules.EVALUABLE_DOMAINS:
        return {**head, 'status': 'deferred_f04', 'complete': False,
                'message': 'Regras de scans/SCA são armazenadas e validadas; a consulta real fica para a F04.',
                'universe': _owner_head(client), 'subclients': [_owner_head(s) for s in subs],
                'warnings': _warn(warnings), 'collections': []}

    if client.rule is None:
        warnings.append('universe_not_defined')
    if client_ctx.connection_id is None:
        raise VeracodeError('connection_not_configured')
    data = await load_dataset(service, client_ctx, domain)
    names = {it.id: it.name for it in data.items}
    collections = [s.status() for s in data.sources]
    if not data.complete:
        warnings.append('collection_incomplete')

    universe_eval = evaluate(domain, client.rule, client.options, data) if client.rule else None
    universe = universe_eval.included if universe_eval else None
    if universe_eval and universe_eval.undetermined:
        warnings.append('universe_undetermined')
    universe_out = {**_owner_head(client), 'defined': universe is not None, 'total_available': len(data.items),
                    **(_counts(universe_eval, names, limit, domain, data) if universe_eval else {})}

    sub_out, membership = [], defaultdict(list)
    for s in subs:
        row = _owner_head(s)
        status = _sub_status(s)
        row['status'] = status
        if status in ('not_defined', 'disabled') and s.owner.effective_active:
            warnings.append('subclients_without_scope')
        if status in ('coverage_unconfirmed', 'connection_changed'):
            warnings.append(status)
        if status == 'shared':
            ev = evaluate(domain, s.rule, s.options, data)
            if universe is None:
                row.update(_counts(ev, names, limit, domain, data), intersected=False)
            else:
                inside = ev.included & universe
                undet = {k: v for k, v in ev.undetermined.items() if k in universe}
                # Excluídos = dentro do universo e não selecionados; fora do universo é contado à parte.
                ev_in = Evaluation(inside, universe - inside - set(undet), undet, ev.inactive & universe)
                row.update(_counts(ev_in, names, limit, domain, data), intersected=True,
                           outside_universe=len(ev.included - universe))
                if undet:
                    warnings.append('undetermined_in_subclients')
                if s.owner.effective_active:
                    for rid in inside:
                        membership[rid].append(s)
        elif status == 'separate_tenant':
            warnings.append('separate_tenant_subclients')
            row.update(await _separate(service, sub_ctx[s.owner.id], s, domain, limit))
        sub_out.append(row)

    unclassified = None
    overlap = None
    if universe is not None:
        classified = set(membership)
        blocking = sorted(set(warnings) & _BLOCKING)
        unclassified_ids = universe - classified
        unclassified = {'available': True, 'count': len(unclassified_ids), 'complete': not blocking,
                        'reasons': blocking, 'no_subclients': 'no_subclients' in warnings,
                        'sample': _sample(unclassified_ids, names, limit)}
        multi = {rid: owners for rid, owners in membership.items() if len(owners) > 1}
        pairs = Counter()
        for owners in multi.values():
            ids = sorted(str(o.owner.id) for o in owners)
            for i, a in enumerate(ids):
                for b in ids[i + 1:]:
                    pairs[(a, b)] += 1
        overlap = {'resources_in_multiple': len(multi),
                   'pairs': [{'a': a, 'b': b, 'count': c} for (a, b), c in sorted(pairs.items())],
                   'sample': [{**r, 'subclients': sorted(o.owner.name for o in multi[r['id']])}
                              for r in _sample(multi, names, limit)]}
    else:
        unclassified = {'available': False, 'count': None, 'complete': False, 'reasons': ['universe_not_defined'],
                        'no_subclients': 'no_subclients' in warnings, 'sample': []}

    extra = {}
    if domain == 'users':
        extra['reconciliation'] = data.extra['summary']['reconciliation']
        extra['members_not_in_user_list'] = data.extra['summary']['members_not_in_user_list']
        if extra['reconciliation']['status'] != 'verified':
            warnings.append('membership_unverified')

    complete = data.complete and all(r.get('complete', True) for r in sub_out if r['status'] == 'separate_tenant')
    status = 'universe_not_defined' if universe is None else ('ok' if complete else 'incomplete')
    return {**head, 'status': status, 'complete': complete, 'universe': universe_out, 'subclients': sub_out,
            'unclassified': unclassified, 'overlap': overlap, 'warnings': _warn(warnings),
            'collections': collections, **extra}


def _sub_status(s: OwnerRule) -> str:
    if not s.owner.effective_active:
        return 'inactive'
    if s.status != 'active' or s.rule is None:
        return s.status
    if s.mode == 'none':
        return 'no_connection'
    if s.saved_mode is not None and s.saved_mode != s.mode and 'separate' in (s.saved_mode, s.mode):
        return 'connection_changed'
    if s.mode == 'separate':
        return 'separate_tenant' if s.coverage_ack else 'coverage_unconfirmed'
    return 'shared'


async def _separate(service: DiscoveryService, ctx: ScopeContext, s: OwnerRule, domain: str, limit: int) -> dict:
    """Outro tenant: só os critérios do próprio subcliente, no próprio tenant. Sem interseção, sem mistura."""
    try:
        data = await load_dataset(service, ctx, domain)
    except VeracodeError as exc:
        return {'tenant': 'separate', 'complete': False, 'error': exc.as_dict()}
    names = {it.id: it.name for it in data.items}
    ev = evaluate(domain, s.rule, s.options, data)
    return {'tenant': 'separate', 'complete': data.complete, 'intersected': False,
            'total_available': len(data.items), 'collections': [x.status() for x in data.sources],
            **_counts(ev, names, limit, domain, data)}


def _warn(codes: list[str]) -> list[dict]:
    seen = []
    for c in codes:
        if c not in seen:
            seen.append(c)
    return [{'code': c, 'message': _WARNINGS[c], 'blocking': c in _BLOCKING} for c in seen]
