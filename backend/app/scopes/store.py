"""Persistência versionada dos escopos (F03).

- Uma definição por dono (cliente OU subcliente) e domínio; os critérios ficam em versões append-only.
- Salvar = nova versão (a anterior vira `superseded`). Regra idêntica à ativa não gera versão.
- `expected_version` (concorrência otimista): salvar sobre uma versão diferente da esperada => 409, nunca
  sobrescrita silenciosa. O banco reforça: conteúdo de versão imutável e versões não excluíveis (gatilhos).
- Subcliente com conexão PRÓPRIA diferente da do cliente (`separate`) exige `coverage_ack` explícito.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ApiError, bad_request, conflict, not_found
from app.orm import (
    Client, ScopeDefinition, ScopeDomain, ScopeStatus, ScopeVersion, ScopeVersionStatus, Subclient, utcnow,
)
from app.scopes import rules

logger = logging.getLogger('afrika.scopes')
OwnerKind = Literal['client', 'subclient']
DOMAINS = tuple(d.value for d in ScopeDomain)

# Regra padrão de usuários inativos (configurável por versão): excluídos da contagem e reportados à parte.
DEFAULT_OPTIONS: dict[str, dict[str, Any]] = {'applications': {}, 'users': {'inactive_users': 'exclude'},
                                              'scans': {}, 'sca': {}}
_OPTION_VALUES = {'inactive_users': ('exclude', 'include')}


@dataclass(frozen=True)
class Owner:
    kind: OwnerKind
    id: uuid.UUID
    name: str
    client: Client
    subclient: Subclient | None

    @property
    def key(self) -> str:
        return f'{self.kind}:{self.id}'

    @property
    def effective_active(self) -> bool:
        return self.client.is_active and (self.subclient is None or self.subclient.is_active)


def get_owner(session: Session, kind: OwnerKind, owner_id: uuid.UUID) -> Owner:
    if kind == 'client':
        client = session.get(Client, owner_id)
        if client is None:
            raise not_found('client')
        return Owner('client', client.id, client.name, client, None)
    sub = session.get(Subclient, owner_id)
    if sub is None:
        raise not_found('subclient')
    return Owner('subclient', sub.id, sub.name, sub.client, sub)


def connection_mode(owner: Owner) -> str:
    """client: dono é o cliente; shared: subcliente usa a MESMA conexão do cliente (herdada ou igual);
    separate: conexão própria diferente (outro tenant possível); none: sem conexão efetiva."""
    client_conn = owner.client.connection_id
    if owner.kind == 'client':
        return 'client' if client_conn else 'none'
    own = owner.subclient.connection_id
    if own is None:
        return 'shared' if client_conn else 'none'
    return 'shared' if own == client_conn else 'separate'


def validate_options(domain: str, options: Any) -> dict:
    if not isinstance(options, dict):
        raise ApiError(422, 'invalid_options', 'Opções inválidas',
                       [{'field': 'options', 'type': 'type', 'message': 'esperado objeto'}])
    allowed = DEFAULT_OPTIONS[domain]
    details = [{'field': f'options.{k}', 'type': 'extra', 'message': 'opção não suportada neste domínio'}
               for k in options if k not in allowed]
    details += [{'field': f'options.{k}', 'type': 'value', 'message': f'use: {", ".join(_OPTION_VALUES[k])}'}
                for k, v in options.items() if k in allowed and v not in _OPTION_VALUES[k]]
    if details:
        raise ApiError(422, 'invalid_options', 'Opções inválidas', details)
    return {**allowed, **options}


def validated_rule(domain: str, rule: Any) -> dict:
    result = rules.validate(domain, rule)
    if not result.valid:
        raise ApiError(422, 'invalid_rule', 'Regra de escopo inválida', [i.as_dict() for i in result.issues])
    return result.rule


def _definition(session: Session, owner: Owner, domain: str) -> ScopeDefinition | None:
    return session.scalar(select(ScopeDefinition).where(ScopeDefinition.owner_key == owner.key,
                                                        ScopeDefinition.domain == domain))


def _active(defn: ScopeDefinition | None) -> ScopeVersion | None:
    if defn is None:
        return None
    return next((v for v in defn.versions if v.status == ScopeVersionStatus.ACTIVE.value), None)


def version_out(v: ScopeVersion) -> dict:
    return {'version': v.version, 'status': v.status, 'rule': json.loads(v.rule_json),
            'options': json.loads(v.options_json), 'rule_hash': v.rule_hash, 'connection_mode': v.connection_mode,
            'coverage_ack': v.coverage_ack, 'note': v.note, 'created_at': v.created_at.isoformat()}


def scope_out(owner: Owner, domain: str, defn: ScopeDefinition | None, *, history: bool = True) -> dict:
    active = _active(defn)
    out = {'owner': {'kind': owner.kind, 'id': str(owner.id), 'name': owner.name,
                     'client_id': str(owner.client.id), 'effective_active': owner.effective_active},
           'domain': domain, 'evaluable': domain in rules.EVALUABLE_DOMAINS,
           'connection_mode': connection_mode(owner),
           'defined': defn is not None, 'status': defn.status if defn else 'not_defined',
           'active_version': version_out(active) if active else None,
           'latest_version': max((v.version for v in defn.versions), default=0) if defn else 0}
    if history:
        out['versions'] = [version_out(v) for v in reversed(defn.versions)] if defn else []
    return out


def get_scope(session: Session, kind: OwnerKind, owner_id: uuid.UUID, domain: str) -> dict:
    owner = get_owner(session, kind, owner_id)
    return scope_out(owner, domain, _definition(session, owner, domain))


def client_overview(session: Session, client_id: uuid.UUID) -> dict:
    owner = get_owner(session, 'client', client_id)
    subs = sorted(owner.client.subclients, key=lambda s: (s.name_key, str(s.id)))
    owners = [owner] + [Owner('subclient', s.id, s.name, owner.client, s) for s in subs]
    defs = session.scalars(select(ScopeDefinition).where(ScopeDefinition.client_id == client_id)).all()
    by_key = {(d.owner_key, d.domain): d for d in defs}
    return {'client_id': str(client_id), 'domains': list(DOMAINS),
            'owners': [{'kind': o.kind, 'id': str(o.id), 'name': o.name, 'effective_active': o.effective_active,
                        'connection_mode': connection_mode(o),
                        'scopes': {d: scope_out(o, d, by_key.get((o.key, d)), history=False) for d in DOMAINS}}
                       for o in owners]}


def _check_coverage(owner: Owner, coverage_ack: bool) -> str:
    mode = connection_mode(owner)
    if mode == 'separate' and not coverage_ack:
        raise conflict('coverage_ack_required',
                       'O subcliente usa conexão própria diferente da do cliente: confirme explicitamente a '
                       'abrangência (os tenants nunca são misturados; não há interseção com o universo do cliente)')
    return mode


def _commit(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise conflict('version_conflict', 'O escopo foi alterado por outra operação; recarregue e tente de novo') \
            from None


def save_scope(session: Session, kind: OwnerKind, owner_id: uuid.UUID, domain: str, *, rule: Any,
               options: Any, note: str | None, coverage_ack: bool, expected_version: int) -> tuple[dict, bool]:
    owner = get_owner(session, kind, owner_id)
    canon = validated_rule(domain, rule)
    opts = validate_options(domain, options or {})
    mode = _check_coverage(owner, coverage_ack)
    defn = _definition(session, owner, domain)
    active = _active(defn)
    current = active.version if active else 0
    if expected_version != current:
        raise conflict('version_conflict', f'Versão ativa é {current}, não {expected_version}: recarregue o escopo '
                                           'antes de salvar (nenhuma versão é sobrescrita)')
    digest = rules.rule_hash(canon)
    options_json = json.dumps(opts, sort_keys=True)
    if active and active.rule_hash == digest and active.options_json == options_json \
            and active.connection_mode == mode and active.coverage_ack == (coverage_ack and mode == 'separate'):
        return scope_out(owner, domain, defn), False
    if defn is None:
        defn = ScopeDefinition(client_id=owner.client.id, subclient_id=owner.subclient.id if owner.subclient else None,
                               owner_key=owner.key, domain=domain, status=ScopeStatus.ACTIVE.value)
        session.add(defn)
        session.flush()
    if active:
        active.status = ScopeVersionStatus.SUPERSEDED.value
        session.flush()
    latest = max((v.version for v in defn.versions), default=0)
    version = ScopeVersion(definition_id=defn.id, version=latest + 1, status=ScopeVersionStatus.ACTIVE.value,
                           rule_json=rules.canonical_json(canon), options_json=options_json, rule_hash=digest,
                           connection_mode=mode, coverage_ack=bool(coverage_ack and mode == 'separate'), note=note)
    defn.versions.append(version)
    defn.updated_at = version.created_at = utcnow()
    _commit(session)
    session.refresh(defn)
    logger.info('escopo salvo dono=%s domínio=%s versão=%s', owner.key, domain, version.version)
    return scope_out(owner, domain, defn), True


def restore_version(session: Session, kind: OwnerKind, owner_id: uuid.UUID, domain: str, number: int, *,
                    note: str | None, coverage_ack: bool, expected_version: int) -> tuple[dict, bool]:
    owner = get_owner(session, kind, owner_id)
    defn = _definition(session, owner, domain)
    old = next((v for v in defn.versions if v.version == number), None) if defn else None
    if old is None:
        raise not_found('scope_version')
    return save_scope(session, kind, owner_id, domain, rule=json.loads(old.rule_json),
                      options=json.loads(old.options_json), note=note or f'Restaurada da versão {number}',
                      coverage_ack=coverage_ack, expected_version=expected_version)


def set_status(session: Session, kind: OwnerKind, owner_id: uuid.UUID, domain: str, status: str) -> dict:
    owner = get_owner(session, kind, owner_id)
    defn = _definition(session, owner, domain)
    if defn is None:
        raise not_found('scope')
    if status not in (s.value for s in ScopeStatus):
        raise bad_request('invalid_status', 'Status deve ser active ou disabled')
    if defn.status != status:
        defn.status = status
        _commit(session)
        logger.info('escopo dono=%s domínio=%s status=%s', owner.key, domain, status)
    session.refresh(defn)
    return scope_out(owner, domain, defn)


# ---------------------------------------------------------------- leitura para a resolução

@dataclass
class OwnerRule:
    owner: Owner
    mode: str
    status: str  # active | disabled | not_defined
    rule: dict | None
    options: dict
    version: int | None
    saved_mode: str | None
    coverage_ack: bool
    draft: bool = False


def owner_rules(session: Session, client_id: uuid.UUID, domain: str) -> tuple[OwnerRule, list[OwnerRule]]:
    """Regra ativa de cada dono do cliente para o domínio (sem rascunhos)."""
    client_owner = get_owner(session, 'client', client_id)
    defs = session.scalars(select(ScopeDefinition).where(ScopeDefinition.client_id == client_id,
                                                         ScopeDefinition.domain == domain)).all()
    by_key = {d.owner_key: d for d in defs}

    def build(owner: Owner) -> OwnerRule:
        defn = by_key.get(owner.key)
        active = _active(defn)
        status = 'not_defined' if defn is None or active is None else defn.status
        usable = status == 'active'
        return OwnerRule(owner, connection_mode(owner), status,
                         json.loads(active.rule_json) if usable else None,
                         json.loads(active.options_json) if active else dict(DEFAULT_OPTIONS[domain]),
                         active.version if active else None, active.connection_mode if active else None,
                         active.coverage_ack if active else False)

    subs = sorted(client_owner.client.subclients, key=lambda s: (s.name_key, str(s.id)))
    return build(client_owner), [build(Owner('subclient', s.id, s.name, client_owner.client, s)) for s in subs]
