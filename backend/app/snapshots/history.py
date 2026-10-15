"""Séries históricas e comparação mês a mês (F05) — SOMENTE snapshots aprovados.

- Referência de cada competência = aprovação mais recente (`v_official_revisions`); versões antigas seguem consultáveis.
- Competência sem aprovação = LACUNA explícita: sem interpolação, sem zero no lugar de ausência, sem número inventado.
  O preenchimento é manual e auditado (nova competência/revisão com valor manual justificado e aprovação).
- Os valores vêm do banco tal como aprovados: consultar setembro em outubro devolve exatamente o aprovado em setembro,
  independentemente do estado atual da Veracode.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.metrics import competence as competence_mod
from app.metrics.registry import REGISTRY
from app.orm import Approval, Competence, CompetenceRevision
from app.snapshots import service
from app.snapshots.values import headline, loads, value_state

MAX_MONTHS = 60
_LABEL = re.compile(r'^\d{4}-(0[1-9]|1[0-2])$')


def _shift(label: str, months: int) -> str:
    y, m = int(label[:4]), int(label[5:])
    idx = y * 12 + (m - 1) + months
    return f'{idx // 12:04d}-{idx % 12 + 1:02d}'


def month_range(start: str, end: str) -> list[str]:
    out, cur = [], start
    while cur <= end:
        out.append(cur)
        cur = _shift(cur, 1)
    return out


def last_closed_month(tz_name: str, now: datetime | None = None) -> str:
    local = (now or datetime.now(timezone.utc)).astimezone(competence_mod.zone(tz_name))
    return _shift(f'{local.year:04d}-{local.month:02d}', -1)


def resolve_range(tz_name: str, *, months: int | None, start: str | None, end: str | None,
                  now: datetime | None = None) -> tuple[str, str]:
    for name, value in (('start', start), ('end', end)):
        if value is not None and not _LABEL.fullmatch(value):
            raise ApiError(422, 'invalid_competence', 'Competência deve estar no formato YYYY-MM',
                           [{'field': name, 'message': 'formato YYYY-MM', 'type': 'invalid_competence'}])
    end = end or last_closed_month(tz_name, now)
    if start is None:
        start = _shift(end, -((months or 6) - 1))
    if start > end:
        raise ApiError(422, 'invalid_range', 'Início posterior ao fim do intervalo')
    if len(month_range(start, end)) > MAX_MONTHS:
        raise ApiError(422, 'range_too_large', f'Intervalo máximo de {MAX_MONTHS} meses')
    return start, end


def official(session: Session, owner_key: str, labels: list[str]) -> dict[str, tuple[Competence, CompetenceRevision,
                                                                                     Approval]]:
    """Por competência: (competência, revisão oficial, aprovação) — a aprovação de maior sequência."""
    rows = session.execute(
        select(Competence, CompetenceRevision, Approval)
        .join(Approval, Approval.competence_id == Competence.id)
        .join(CompetenceRevision, CompetenceRevision.id == Approval.revision_id)
        .where(Competence.owner_key == owner_key, Competence.label.in_(labels))).all()
    out: dict = {}
    for comp, rev, appr in rows:
        if comp.label not in out or appr.sequence > out[comp.label][2].sequence:
            out[comp.label] = (comp, rev, appr)
    return out


def _point(label: str, entry, metric_id: str) -> dict:
    if entry is None:
        return {'competence': label, 'state': 'GAP', 'value': None, 'headline': None, 'value_state': None,
                'origin': None, 'approval': None}
    comp, rev, appr = entry
    snap = next((s for s in rev.snapshots if s.metric_id == metric_id), None)
    base = {'competence': label, 'state': 'APPROVED', 'timezone': comp.timezone,
            'approval': {'sequence': appr.sequence, 'revision': rev.number, 'approver': appr.approver,
                         'identity_mode': appr.identity_mode, 'approved_at': appr.approved_at.isoformat(),
                         'content_hash': appr.content_hash}}
    if snap is None:
        return {**base, 'value': None, 'headline': None, 'value_state': 'MISSING', 'origin': None,
                'value_type': None, 'contract_version': None}
    value = loads(snap.value_json)
    return {**base, 'value': value, 'headline': headline(snap.value_type, value),
            'value_state': value_state(snap.origin, value, snap.source_status).value, 'origin': snap.origin,
            'value_type': snap.value_type, 'contract_version': snap.contract_version,
            'dashboard_homologation': snap.dashboard_homologation}


def series(session: Session, kind: str, owner_id: uuid.UUID, metric_id: str, *, months: int | None = None,
           start: str | None = None, end: str | None = None, now: datetime | None = None) -> dict:
    if metric_id not in REGISTRY:
        raise service.not_found('metric_not_found', 'Indicador inexistente no catálogo')
    owner = service.owner_of(session, kind, owner_id)
    tz = owner.client.timezone
    start, end = resolve_range(tz, months=months, start=start, end=end, now=now)
    labels = month_range(start, end)
    ref = official(session, owner.key, labels)
    points = [_point(label, ref.get(label), metric_id) for label in labels]
    approved = [p for p in points if p['state'] == 'APPROVED' and p.get('value_type')]
    warnings = []
    if len({p['value_type'] for p in approved}) > 1:
        warnings.append({'code': 'inconsistent_value_types', 'message': 'Tipos de valor diferentes na série'})
    if len({p['contract_version'] for p in approved}) > 1:
        warnings.append({'code': 'contract_version_changed',
                         'message': 'Versões de contrato diferentes na série: compare com cautela'})
    return {'owner': {'kind': kind, 'id': str(owner_id), 'name': owner.name, 'key': owner.key},
            'metric_id': metric_id, 'metric_name': REGISTRY[metric_id].name, 'timezone': tz,
            'start': start, 'end': end, 'points': points,
            'gaps': [p['competence'] for p in points if p['state'] == 'GAP'],
            'without_value': [p['competence'] for p in points if p['state'] == 'APPROVED' and p['value'] is None],
            'warnings': warnings, 'source': 'approved_snapshots_only', 'interpolation': 'none'}


def _delta(cur: dict, prev: dict) -> tuple[float | int | None, str | None]:
    if cur['state'] != 'APPROVED' or prev['state'] != 'APPROVED':
        return None, 'gap'
    if cur['headline'] is None or prev['headline'] is None:
        return None, 'no_numeric_value'
    if cur.get('value_type') != prev.get('value_type'):
        return None, 'value_type_changed'
    if cur.get('contract_version') != prev.get('contract_version'):
        return None, 'contract_version_changed'
    return cur['headline'] - prev['headline'], None


def compare_previous(session: Session, kind: str, owner_id: uuid.UUID, label: str,
                     metric_ids: list[str] | None = None) -> dict:
    if not _LABEL.fullmatch(label or ''):
        raise ApiError(422, 'invalid_competence', 'Competência deve estar no formato YYYY-MM')
    owner = service.owner_of(session, kind, owner_id)
    previous = _shift(label, -1)
    ref = official(session, owner.key, [label, previous])
    ids = metric_ids or sorted({s.metric_id for lbl in (label, previous) if lbl in ref
                                for s in ref[lbl][1].snapshots})
    items = []
    for mid in ids:
        if mid not in REGISTRY:
            raise service.not_found('metric_not_found', 'Indicador inexistente no catálogo')
        cur, prev = _point(label, ref.get(label), mid), _point(previous, ref.get(previous), mid)
        delta, reason = _delta(cur, prev)
        items.append({'metric_id': mid, 'name': REGISTRY[mid].name, 'current': cur, 'previous': prev,
                      'delta': delta, 'delta_unavailable_reason': reason})
    return {'owner': {'kind': kind, 'id': str(owner_id), 'name': owner.name}, 'competence': label,
            'previous_competence': previous, 'current_state': 'APPROVED' if label in ref else 'GAP',
            'previous_state': 'APPROVED' if previous in ref else 'GAP', 'items': items}

