"""População de aplicações de um dono (cliente ou subcliente) a partir dos escopos versionados da F03.

- Cliente: universo = regra ativa do cliente. Sem regra => UNAVAILABLE (nunca o tenant inteiro implícito).
- Subcliente na mesma conexão: critérios próprios ∩ universo do cliente (universo obrigatório).
- Subcliente em conexão própria (`separate`, abrangência confirmada): só o próprio tenant, sem interseção.
- Indeterminados (campos ausentes) ficam fora e tornam a população INCOMPLETE.
- Regras dos domínios `scans` (SAST) e `sca` (SCA), quando ativas, filtram os findings das aplicações da
  população (cliente + subcliente na mesma conexão; só o subcliente em conexão própria). Elas nunca ampliam a
  coleta além do escopo de aplicações.
A referência exata das versões de escopo usadas vai para a proveniência.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from sqlalchemy.orm import Session

from app.metrics.contracts import Reason
from app.scopes import resolver, rules, store
from app.scopes.store import OwnerRule
from app.veracode.discovery import DiscoveryService, ScopeContext, resolve_scope
from app.veracode.errors import VeracodeError

CONFIG_ERRORS = {'connection_not_configured', 'credentials_missing', 'credentials_invalid_format',
                 'unsupported_credential_ref'}


class PopulationStatus(StrEnum):
    OK = 'ok'
    INCOMPLETE = 'incomplete'
    UNAVAILABLE = 'unavailable'
    FAILED = 'failed'


_SUB_STATUS_MESSAGE = {
    'inactive': 'Subcliente (ou cliente) inativo',
    'not_defined': 'Subcliente sem escopo de aplicações ativo',
    'disabled': 'Escopo de aplicações do subcliente desativado',
    'no_connection': 'Subcliente sem conexão Veracode efetiva',
    'coverage_unconfirmed': 'Subcliente em outra conexão sem confirmação de abrangência',
    'connection_changed': 'A conexão do subcliente mudou desde a versão de escopo salva: salve uma nova versão',
}


@dataclass
class Inputs:
    """Tudo o que vem do banco (carregado de forma síncrona, fora do event loop)."""
    kind: str
    owner_id: uuid.UUID
    owner_name: str
    client_ctx: ScopeContext
    target_ctx: ScopeContext
    client: OwnerRule
    target: OwnerRule
    subs: list[OwnerRule]
    finding_rules: dict[str, list[OwnerRule]]  # 'scans'|'sca' -> regras que se aplicam aos findings
    timezone: str = 'America/Sao_Paulo'        # fuso do cliente (subclientes herdam)


def load_inputs(session: Session, kind: str, owner_id: uuid.UUID) -> Inputs:
    owner = store.get_owner(session, kind, owner_id)
    client_id = owner.client.id
    client, subs = store.owner_rules(session, client_id, 'applications')
    target = client if kind == 'client' else next(s for s in subs if s.owner.id == owner_id)
    client_ctx = resolve_scope(session, 'client', client_id)
    target_ctx = client_ctx if kind == 'client' else resolve_scope(session, 'subclient', owner_id)
    finding_rules = {}
    for domain in ('scans', 'sca'):
        c, ss = store.owner_rules(session, client_id, domain)
        t = c if kind == 'client' else next(s for s in ss if s.owner.id == owner_id)
        applicable = [t] if (kind == 'client' or target.mode == 'separate') else [c, t]
        finding_rules[domain] = applicable
    return Inputs(kind, owner_id, owner.name, client_ctx, target_ctx, client, target, subs, finding_rules,
                  owner.client.timezone)


def scope_ref(o: OwnerRule, domain: str) -> dict:
    return {'owner_key': o.owner.key, 'owner_name': o.owner.name, 'domain': domain, 'status': o.status,
            'version': o.version if o.status == 'active' else None,
            'rule_hash': rules.rule_hash(o.rule) if o.rule is not None else None,
            'connection_mode': o.mode, 'saved_connection_mode': o.saved_mode}


@dataclass
class Population:
    status: PopulationStatus
    reasons: list[Reason] = field(default_factory=list)
    applications: list[dict] = field(default_factory=list)
    ctx: ScopeContext | None = None
    total_available: int | None = None
    undetermined: int = 0
    missing_fields: dict[str, int] = field(default_factory=dict)
    collections: list[dict] = field(default_factory=list)
    scope_refs: list[dict] = field(default_factory=list)
    unclassified: dict | None = None
    collected_at: str | None = None


def _error_population(exc: VeracodeError, refs: list[dict]) -> Population:
    status = PopulationStatus.UNAVAILABLE if exc.code in CONFIG_ERRORS else PopulationStatus.FAILED
    return Population(status, [Reason(exc.code, exc.message)], scope_refs=refs)


def _merge_undetermined(*evs: resolver.Evaluation) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for ev in evs:
        for rid, missing in ev.undetermined.items():
            out.setdefault(rid, set()).update(missing)
    return out


async def resolve_population(service: DiscoveryService, inp: Inputs) -> Population:
    refs = [scope_ref(inp.client, 'applications')]
    if inp.kind == 'subclient':
        refs.append(scope_ref(inp.target, 'applications'))
    for domain, owners in inp.finding_rules.items():
        refs += [scope_ref(o, domain) for o in owners]

    if inp.kind == 'subclient':
        sub_status = resolver._sub_status(inp.target)
        if sub_status not in ('shared', 'separate_tenant'):
            return Population(PopulationStatus.UNAVAILABLE,
                              [Reason(f'subclient_{sub_status}', _SUB_STATUS_MESSAGE.get(sub_status, sub_status))],
                              scope_refs=refs)
    else:
        sub_status = None
    separate = sub_status == 'separate_tenant'
    if not separate and inp.client.rule is None:
        return Population(PopulationStatus.UNAVAILABLE,
                          [Reason('universe_not_defined', 'O cliente principal não tem escopo de aplicações ativo: '
                                                          'universo não definido (o tenant inteiro nunca é usado '
                                                          'implicitamente)')], scope_refs=refs)
    data_ctx = inp.target_ctx if separate else inp.client_ctx
    try:
        if data_ctx.connection_id is None:
            raise VeracodeError('connection_not_configured')
        data = await resolver.load_dataset(service, data_ctx, 'applications')
    except VeracodeError as exc:
        return _error_population(exc, refs)

    by_id = {it.id: it.record for it in data.items}
    apps_by_id = {}
    for src in data.sources:
        for a in src.collection.items:
            if isinstance(a.get('guid'), str):
                apps_by_id[a['guid'].lower()] = a
    reasons: list[Reason] = []
    if separate:
        ev = resolver.evaluate('applications', inp.target.rule, inp.target.options, data)
        included, undetermined = ev.included, _merge_undetermined(ev)
    else:
        universe_ev = resolver.evaluate('applications', inp.client.rule, inp.client.options, data)
        if inp.kind == 'client':
            included, undetermined = universe_ev.included, _merge_undetermined(universe_ev)
        else:
            ev = resolver.evaluate('applications', inp.target.rule, inp.target.options, data)
            included = ev.included & universe_ev.included
            # Pode pertencer ao subcliente: indeterminado no subcliente e possivelmente no universo, ou
            # selecionado pelo subcliente e indeterminado no universo.
            maybe_universe = universe_ev.included | set(universe_ev.undetermined)
            undetermined = {k: v for k, v in _merge_undetermined(universe_ev, ev).items()
                            if (k in ev.undetermined and k in maybe_universe)
                            or (k in universe_ev.undetermined and k in ev.included)}
    status = PopulationStatus.OK
    if not data.complete:
        status = PopulationStatus.INCOMPLETE
        reasons.append(Reason('applications_collection_incomplete',
                              'Coleta de aplicações incompleta: população não validada'))
    if undetermined:
        status = PopulationStatus.INCOMPLETE
        reasons.append(Reason('applications_undetermined',
                              f'{len(undetermined)} aplicação(ões) indeterminada(s) pelas regras de escopo '
                              '(campos ausentes): fora da população'))
    missing = {}
    for fields in undetermined.values():
        for f in fields:
            missing[f] = missing.get(f, 0) + 1
    unclassified = _unclassified(inp, data, universe_ev.included) if (inp.kind == 'client' and not separate) \
        else None
    return Population(status, reasons, [apps_by_id[i] for i in sorted(included) if i in apps_by_id],
                      inp.target_ctx, len(by_id), len(undetermined), dict(sorted(missing.items())),
                      [s.status() for s in data.sources], refs, unclassified,
                      data.sources[0].collection.fetched_at.isoformat() if data.sources else None)


def _unclassified(inp: Inputs, data: resolver.Dataset, universe: set[str]) -> dict:
    """Universo − ∪(subclientes ativos na mesma conexão). Bloqueios tornam o número incompleto."""
    classified: set[str] = set()
    blocking: list[Reason] = []
    active = [s for s in inp.subs if s.owner.effective_active]
    for s in active:
        st = resolver._sub_status(s)
        if st == 'shared':
            ev = resolver.evaluate('applications', s.rule, s.options, data)
            classified |= ev.included & universe
            if any(k in universe for k in ev.undetermined):
                blocking.append(Reason('undetermined_in_subclients', f'Indeterminados no subcliente {s.owner.name}'))
        elif st in ('not_defined', 'disabled', 'coverage_unconfirmed', 'connection_changed'):
            blocking.append(Reason(f'subclient_{st}', f'{s.owner.name}: {_SUB_STATUS_MESSAGE[st]}'))
    return {'count': len(universe - classified), 'no_subclients': not active, 'blocking': blocking}
