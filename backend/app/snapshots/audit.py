"""Eventos de auditoria append-only encadeados por hash (F05).

Cada evento guarda o hash do anterior (`prev_hash`, ÚNICO no banco => cadeia linear: duas gravações concorrentes
sobre o mesmo elo falham em vez de bifurcar). Detalhes têm só identificadores, códigos e contagens — nunca valores
de credencial, respostas HTTP ou findings.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.orm import AuditEvent, utcnow
from app.snapshots.values import canonical, sha256

GENESIS = '0' * 64


def _payload(prev_hash: str, occurred_at: datetime, event_type: str, owner_key: str | None,
             competence_id: uuid.UUID | None, revision_id: uuid.UUID | None, actor: str | None,
             details_json: str) -> dict:
    return {'prev': prev_hash, 'at': occurred_at.astimezone(timezone.utc).isoformat(), 'type': event_type,
            'owner': owner_key,
            'competence': None if competence_id is None else str(competence_id),
            'revision': None if revision_id is None else str(revision_id), 'actor': actor, 'details': details_json}


def append(session: Session, event_type: str, *, owner_key: str | None = None,
           competence_id: uuid.UUID | None = None, revision_id: uuid.UUID | None = None, actor: str | None = None,
           details: dict | None = None) -> AuditEvent:
    prev = session.scalar(select(AuditEvent.event_hash).order_by(AuditEvent.id.desc()).limit(1)) or GENESIS
    occurred = utcnow()
    details_json = canonical(details or {})
    event = AuditEvent(occurred_at=occurred, event_type=event_type, owner_key=owner_key, competence_id=competence_id,
                       revision_id=revision_id, actor=actor, details_json=details_json, prev_hash=prev,
                       event_hash=sha256(_payload(prev, occurred, event_type, owner_key, competence_id, revision_id,
                                                  actor, details_json)))
    session.add(event)
    session.flush()
    return event


def verify_chain(session: Session) -> dict:
    """Recalcula a cadeia inteira. Qualquer alteração fora da aplicação (ex.: gatilho removido) é detectada."""
    prev, checked, broken = GENESIS, 0, []
    for e in session.scalars(select(AuditEvent).order_by(AuditEvent.id)):
        expected = sha256(_payload(e.prev_hash, e.occurred_at, e.event_type, e.owner_key, e.competence_id,
                                   e.revision_id, e.actor, e.details_json))
        if e.prev_hash != prev or e.event_hash != expected:
            broken.append(e.id)
        prev = e.event_hash
        checked += 1
    return {'ok': not broken, 'events_checked': checked, 'broken_event_ids': broken[:50]}


def event_out(e: AuditEvent) -> dict:
    return {'id': e.id, 'occurred_at': e.occurred_at.isoformat(), 'event_type': e.event_type, 'actor': e.actor,
            'revision_id': None if e.revision_id is None else str(e.revision_id),
            'details': json.loads(e.details_json), 'event_hash': e.event_hash}
