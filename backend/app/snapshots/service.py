"""Competências, revisões, snapshots, entrada manual e aprovação (F05).

Regras:
- Competência = mês fechado (YYYY-MM) de um dono (cliente OU subcliente), no fuso do cliente vigente na criação.
- Revisões: DRAFT -> READY_FOR_REVIEW -> APPROVED. Só DRAFT é editável; APPROVED é imutável (aplicação + gatilhos).
  Uma revisão aberta por competência; revisão nova parte da última aprovada (cópia exata dos snapshots).
- Toda alteração exige `expected_lock_version`; a atualização é condicional no banco (WHERE lock_version = esperado)
  => alteração concorrente vira conflito 409, nunca sobrescrita.
- Valor manual exige justificativa e operador declarado; o valor observado na Veracode fica preservado em `source_*`.
- Aprovação: aprovador declarado (sem autenticação — NÃO é identidade comprovada), conjunto explícito de indicadores
  obrigatórios, valores válidos e hashes íntegros. Registro append-only com hash encadeado.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.errors import ApiError, conflict
from app.metrics import competence as competence_mod
from app.metrics.contracts import MetricStatus
from app.metrics.registry import REGISTRY
from app.orm import (
    Approval, AuditEvent, CollectionRunRecord, Competence, CompetenceRevision, ManualChange, MetricSnapshot,
    RevisionStatus, SnapshotOrigin, utcnow,
)
from app.scopes import store
from app.snapshots import audit
from app.snapshots.values import (
    InvalidValue, dumps, headline, loads, sha256, snapshot_hash, validate, value_state, value_type_for,
)

logger = logging.getLogger('afrika.snapshots')
IDENTITY_MODE = 'DECLARED_UNAUTHENTICATED'
_FAR_FUTURE = datetime(9999, 1, 1, tzinfo=timezone.utc)

# Campos copiados exatamente quando uma revisão nova parte da última aprovada.
_COPY_FIELDS = ('metric_id', 'contract_version', 'value_type', 'shape', 'unit', 'origin', 'value_json',
                'source_status', 'source_value_json', 'source_partial_json', 'source_reasons_json',
                'dashboard_homologation', 'source_name', 'endpoint', 'context', 'collected_at', 'temporal_json',
                'scope_refs_json', 'provenance_json', 'collection_run_id', 'manual_justification', 'manual_operator',
                'manual_at', 'row_hash')


def not_found(code: str, message: str) -> ApiError:
    return ApiError(404, code, message)


def _commit(session: Session) -> None:
    """Falha de unicidade/gatilho ou banco ocupado por gravação concorrente => conflito, nunca sobrescrita."""
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        reason = str(exc.orig) if exc.orig is not None else ''
        code = next((c for c in ('revision_approved_immutable', 'snapshot_revision_not_draft',
                                 'revision_status_transition', 'approval_requires_approved_revision')
                     if c in reason), 'concurrent_modification')
        raise conflict(code, 'Operação recusada: o registro foi alterado por outra operação ou está protegido '
                             '(recarregue e tente de novo)') from None
    except OperationalError:
        session.rollback()
        raise conflict('concurrent_modification', 'Banco ocupado por outra gravação; tente de novo') from None


# ---------------------------------------------------------------- carregamento

def owner_of(session: Session, kind: str, owner_id: uuid.UUID) -> store.Owner:
    return store.get_owner(session, kind, owner_id)


def get_competence(session: Session, competence_id: uuid.UUID) -> Competence:
    comp = session.get(Competence, competence_id)
    if comp is None:
        raise not_found('competence_not_found', 'Competência não encontrada')
    return comp


def get_revision(session: Session, comp: Competence, number: int) -> CompetenceRevision:
    rev = session.scalar(select(CompetenceRevision).where(CompetenceRevision.competence_id == comp.id,
                                                          CompetenceRevision.number == number))
    if rev is None:
        raise not_found('revision_not_found', 'Revisão não encontrada')
    return rev


def approvals_of(session: Session, comp: Competence) -> dict[uuid.UUID, Approval]:
    return {a.revision_id: a for a in session.scalars(select(Approval).where(Approval.competence_id == comp.id))}


def latest_approval(session: Session, competence_id: uuid.UUID) -> Approval | None:
    return session.scalar(select(Approval).where(Approval.competence_id == competence_id)
                          .order_by(Approval.sequence.desc()).limit(1))


def period(comp: Competence) -> dict:
    return competence_mod.parse(comp.label, comp.timezone, now=_FAR_FUTURE).as_dict()


def _owner_ref(comp: Competence) -> dict:
    kind, _, oid = comp.owner_key.partition(':')
    return {'kind': kind, 'id': oid, 'client_id': str(comp.client_id),
            'subclient_id': None if comp.subclient_id is None else str(comp.subclient_id)}


# ---------------------------------------------------------------- serialização

def approval_out(a: Approval | None) -> dict | None:
    if a is None:
        return None
    return {'sequence': a.sequence, 'approver': a.approver, 'identity_mode': a.identity_mode, 'note': a.note,
            'approved_at': a.approved_at.isoformat(), 'content_hash': a.content_hash,
            'previous_chain_hash': a.previous_chain_hash, 'chain_hash': a.chain_hash}


def competence_out(session: Session, comp: Competence) -> dict:
    approvals = approvals_of(session, comp)
    official = max(approvals.values(), key=lambda a: a.sequence, default=None)
    revs = [{'number': r.number, 'status': r.status, 'lock_version': r.lock_version, 'created_by': r.created_by,
             'created_at': r.created_at.isoformat(), 'submitted_by': r.submitted_by,
             'submitted_at': None if r.submitted_at is None else r.submitted_at.isoformat(),
             'approval': approval_out(approvals.get(r.id)),
             'is_official': official is not None and official.revision_id == r.id} for r in comp.revisions]
    open_rev = next((r['number'] for r in revs if r['status'] != RevisionStatus.APPROVED.value), None)
    return {'id': str(comp.id), 'owner': _owner_ref(comp), 'competence': comp.label, 'timezone': comp.timezone,
            'period': period(comp), 'created_at': comp.created_at.isoformat(), 'revisions': revs,
            'open_revision': open_rev,
            'official_revision': next((r['number'] for r in revs if r['is_official']), None)}


def snapshot_out(s: MetricSnapshot, required: set[str]) -> dict:
    c = REGISTRY.get(s.metric_id)
    value = loads(s.value_json)
    return {'metric_id': s.metric_id, 'name': c.name if c else s.metric_id, 'contract_version': s.contract_version,
            'value_type': s.value_type, 'shape': s.shape, 'unit': s.unit, 'origin': s.origin, 'value': value,
            'value_state': value_state(s.origin, value, s.source_status).value,
            'headline': headline(s.value_type, value), 'required': s.metric_id in required,
            'source': {'status': s.source_status, 'value': loads(s.source_value_json),
                       'partial': loads(s.source_partial_json), 'reasons': loads(s.source_reasons_json),
                       'name': s.source_name, 'endpoint': s.endpoint, 'context': s.context,
                       'collected_at': None if s.collected_at is None else s.collected_at.isoformat()},
            'dashboard_homologation': s.dashboard_homologation,
            'temporal': loads(s.temporal_json), 'scope_refs': loads(s.scope_refs_json),
            'provenance': loads(s.provenance_json),
            'collection_run_id': None if s.collection_run_id is None else str(s.collection_run_id),
            'manual': None if s.origin != SnapshotOrigin.MANUAL.value else {
                'justification': s.manual_justification, 'operator': s.manual_operator,
                'at': s.manual_at.isoformat()},
            'row_hash': s.row_hash}


def revision_out(session: Session, comp: Competence, rev: CompetenceRevision) -> dict:
    required = set(json.loads(rev.required_metrics_json))
    approval = session.scalar(select(Approval).where(Approval.revision_id == rev.id))
    base = None if rev.base_revision_id is None else session.get(CompetenceRevision, rev.base_revision_id)
    changes = session.scalars(select(ManualChange).where(ManualChange.revision_id == rev.id)
                              .order_by(ManualChange.changed_at, ManualChange.id)).all()
    present = {s.metric_id for s in rev.snapshots}
    official = latest_approval(session, comp.id)
    return {'competence': {'id': str(comp.id), 'competence': comp.label, 'timezone': comp.timezone,
                           'owner': _owner_ref(comp), 'period': period(comp)},
            'number': rev.number, 'status': rev.status, 'lock_version': rev.lock_version,
            'editable': rev.status == RevisionStatus.DRAFT.value,
            'is_official': official is not None and official.revision_id == rev.id,
            'base_revision': None if base is None else base.number,
            'required_metrics': sorted(required), 'required_set_version': rev.required_set_version,
            'created_by': rev.created_by, 'created_at': rev.created_at.isoformat(),
            'submitted_by': rev.submitted_by,
            'submitted_at': None if rev.submitted_at is None else rev.submitted_at.isoformat(),
            'approval': approval_out(approval),
            'snapshots': [snapshot_out(s, required) for s in rev.snapshots],
            'metrics_without_snapshot': [m for m in REGISTRY if m not in present],
            'checks': approval_blockers(rev),
            'manual_changes': [{'metric_id': c.metric_id, 'previous_value': loads(c.previous_value_json),
                                'new_value': loads(c.new_value_json), 'previous_origin': c.previous_origin,
                                'new_origin': c.new_origin, 'justification': c.justification,
                                'operator': c.operator, 'changed_at': c.changed_at.isoformat()} for c in changes]}


# ---------------------------------------------------------------- concorrência

def _touch(session: Session, rev: CompetenceRevision, expected: int, *, require_draft: bool = True) -> None:
    if require_draft and rev.status != RevisionStatus.DRAFT.value:
        raise conflict('revision_not_draft', 'Só revisões em rascunho (DRAFT) podem ser alteradas')
    if rev.lock_version != expected:
        raise conflict('revision_conflict', f'A revisão está na versão {rev.lock_version}, não {expected}: outra '
                                            'operação a alterou; recarregue antes de continuar')
    # Condicional no banco: entre a leitura e a gravação, outra transação pode ter alterado a revisão.
    res = session.execute(update(CompetenceRevision)
                          .where(CompetenceRevision.id == rev.id, CompetenceRevision.lock_version == expected,
                                 CompetenceRevision.status == rev.status)
                          .values(lock_version=expected + 1, updated_at=utcnow()))
    if res.rowcount != 1:
        session.rollback()
        raise conflict('revision_conflict', 'A revisão foi alterada por outra operação; recarregue antes de continuar')


# ---------------------------------------------------------------- competências e revisões

def create_competence(session: Session, kind: str, owner_id: uuid.UUID, label: str, operator: str, *,
                      now: datetime | None = None) -> Competence:
    owner = owner_of(session, kind, owner_id)
    try:
        competence_mod.parse(label, owner.client.timezone, now=now)
    except competence_mod.CompetenceError as exc:
        raise ApiError(422, exc.code, exc.message, [{'field': 'competence', 'message': exc.message,
                                                     'type': exc.code}]) from None
    existing = session.scalar(select(Competence).where(Competence.owner_key == owner.key, Competence.label == label))
    if existing is not None:
        raise ApiError(409, 'competence_exists', 'Competência já existe para este dono',
                       [{'field': 'competence', 'message': str(existing.id), 'type': 'competence_id'}])
    comp = Competence(client_id=owner.client.id, subclient_id=None if owner.subclient is None else owner.subclient.id,
                      owner_key=owner.key, label=label, timezone=owner.client.timezone)
    session.add(comp)
    session.flush()
    rev = CompetenceRevision(competence_id=comp.id, number=1, created_by=operator)
    session.add(rev)
    session.flush()
    audit.append(session, 'competence.created', owner_key=owner.key, competence_id=comp.id, actor=operator,
                 details={'competence': label, 'timezone': comp.timezone})
    audit.append(session, 'revision.created', owner_key=owner.key, competence_id=comp.id, revision_id=rev.id,
                 actor=operator, details={'number': 1, 'base': None})
    _commit(session)
    logger.info('competência criada dono=%s competência=%s', owner.key, label)
    return comp


def create_revision(session: Session, comp: Competence, operator: str) -> CompetenceRevision:
    """Nova revisão (DRAFT) a partir da ÚLTIMA aprovada: cópia exata (mesmos hashes); a aprovada fica intacta."""
    if any(r.status != RevisionStatus.APPROVED.value for r in comp.revisions):
        raise conflict('open_revision_exists', 'Já existe uma revisão aberta (rascunho ou em revisão) nesta '
                                               'competência')
    base_approval = latest_approval(session, comp.id)
    if base_approval is None:
        raise conflict('no_approved_revision', 'Não há revisão aprovada para servir de base')
    base = session.get(CompetenceRevision, base_approval.revision_id)
    number = (session.scalar(select(func.max(CompetenceRevision.number))
                             .where(CompetenceRevision.competence_id == comp.id)) or 0) + 1
    rev = CompetenceRevision(competence_id=comp.id, number=number, base_revision_id=base.id, created_by=operator,
                             required_metrics_json=base.required_metrics_json,
                             required_set_version=base.required_set_version)
    session.add(rev)
    session.flush()
    for s in base.snapshots:
        session.add(MetricSnapshot(revision_id=rev.id, **{f: getattr(s, f) for f in _COPY_FIELDS}))
    session.flush()
    audit.append(session, 'revision.created', owner_key=comp.owner_key, competence_id=comp.id, revision_id=rev.id,
                 actor=operator, details={'number': number, 'base': base.number,
                                          'snapshots_copied': len(base.snapshots)})
    _commit(session)
    session.refresh(comp)
    return rev


# ---------------------------------------------------------------- importação de execução (F04)

def _parse_dt(text: str | None) -> datetime | None:
    return None if not text else datetime.fromisoformat(text)


def _run_record(session: Session, comp: Competence, run: dict) -> CollectionRunRecord:
    run_id = uuid.UUID(run['run_id'])
    record = session.get(CollectionRunRecord, run_id)
    if record is not None:
        return record
    res = run['result']
    prov = res['provenance']
    record = CollectionRunRecord(
        id=run_id, kind='METRICS', client_id=comp.client_id, subclient_id=comp.subclient_id, owner_key=comp.owner_key,
        competence_label=comp.label, timezone=comp.timezone, engine_version=prov['engine'],
        input_hash=prov['input_hash'], collected_at=_parse_dt(res['collected_at']),
        started_at=_parse_dt(run.get('started_at')), finished_at=_parse_dt(run.get('finished_at')),
        scope_refs_json=dumps(prov['scope_refs']), connection_json=dumps(res.get('connection')),
        population_json=dumps(res.get('population')), collection_json=dumps(res.get('collection')),
        summary_json=dumps(res.get('summary') or {}))
    session.add(record)
    session.flush()
    return record


def _source_fields(m: dict, res: dict, record: CollectionRunRecord) -> dict:
    status = m['status']
    prov = res['provenance']
    return {
        'contract_version': m['contract_version'],
        'source_status': status,
        'source_value_json': dumps(m['value']) if status == MetricStatus.VALIDATED.value else None,
        'source_partial_json': dumps(m.get('partial')) if status == MetricStatus.INCOMPLETE.value else None,
        'source_reasons_json': dumps(m.get('reasons') or []),
        'dashboard_homologation': m['homologation'],
        'source_name': m['source'], 'endpoint': m.get('endpoint'), 'context': m.get('context'),
        'collected_at': _parse_dt(res['collected_at']),
        'temporal_json': dumps(m.get('temporal') or {}),
        'scope_refs_json': dumps(prov['scope_refs']),
        # Conexão só por id/nome/região/origem — a referência de credencial nunca entra no snapshot.
        'provenance_json': dumps({'run_id': prov['run_id'], 'engine': prov['engine'],
                                  'input_hash': prov['input_hash'], 'connection': res.get('connection'),
                                  'domain': m.get('domain'), 'scan_type': m.get('scan_type'),
                                  'coverage': m.get('coverage') or {}, 'filters': m.get('filters') or {}}),
        'collection_run_id': record.id,
    }


def import_run(session: Session, comp: Competence, rev: CompetenceRevision, run: dict, operator: str,
               expected: int) -> dict:
    if run['status'] != 'done' or not run.get('result'):
        raise conflict('run_not_done', 'Só execuções concluídas podem ser importadas')
    owner = run['owner']
    if f"{owner['kind']}:{owner['id']}" != comp.owner_key:
        raise conflict('run_owner_mismatch', 'A execução pertence a outro cliente/subcliente')
    rc = run['competence']
    if rc['competence'] != comp.label:
        raise conflict('run_competence_mismatch', 'A execução é de outra competência')
    if rc['timezone'] != comp.timezone:
        raise conflict('timezone_mismatch', f'A execução usou o fuso {rc["timezone"]}; a competência usa '
                                            f'{comp.timezone}')
    _touch(session, rev, expected)
    res = run['result']
    record = _run_record(session, comp, run)
    existing = {s.metric_id: s for s in rev.snapshots}
    counts = {'created': 0, 'veracode_replaced': 0, 'manual_kept': 0, 'skipped_unknown': 0}
    for m in res['metrics']:
        contract = REGISTRY.get(m['metric_id'])
        if contract is None:
            counts['skipped_unknown'] += 1
            continue
        fields = _source_fields(m, res, record)
        s = existing.get(m['metric_id'])
        if s is None:
            s = MetricSnapshot(revision_id=rev.id, metric_id=m['metric_id'], value_type=value_type_for(contract).value,
                               shape=contract.shape.value, unit=contract.unit.value, row_hash='')
            session.add(s)
            counts['created'] += 1
        elif s.origin == SnapshotOrigin.MANUAL.value:
            counts['manual_kept'] += 1  # valor manual continua efetivo; a fonte é atualizada à parte
        else:
            counts['veracode_replaced'] += 1
        for k, v in fields.items():
            setattr(s, k, v)
        if s.origin != SnapshotOrigin.MANUAL.value:
            s.origin = SnapshotOrigin.VERACODE.value
            s.value_json = fields['source_value_json']
        s.row_hash = snapshot_hash(s)
    session.flush()
    audit.append(session, 'run.imported', owner_key=comp.owner_key, competence_id=comp.id, revision_id=rev.id,
                 actor=operator, details={'run_id': run['run_id'], 'input_hash': res['provenance']['input_hash'],
                                          **counts})
    _commit(session)
    session.refresh(rev)
    return {'run_id': run['run_id'], **counts}


# ---------------------------------------------------------------- entrada manual

def _snapshot(rev: CompetenceRevision, metric_id: str) -> MetricSnapshot | None:
    return next((s for s in rev.snapshots if s.metric_id == metric_id), None)


def _contract(metric_id: str):
    c = REGISTRY.get(metric_id)
    if c is None:
        raise not_found('metric_not_found', 'Indicador inexistente no catálogo')
    return c


def set_manual(session: Session, comp: Competence, rev: CompetenceRevision, metric_id: str, value,
               justification: str, operator: str, expected: int) -> MetricSnapshot:
    contract = _contract(metric_id)
    s = _snapshot(rev, metric_id)
    value_type = s.value_type if s is not None else value_type_for(contract).value
    try:
        validate(value_type, value)
    except InvalidValue as exc:
        raise ApiError(422, 'invalid_value', exc.message, [{'field': 'value', 'message': exc.message,
                                                            'type': exc.code}]) from None
    _touch(session, rev, expected)
    now = utcnow()
    previous_value, previous_origin = (None, None) if s is None else (s.value_json, s.origin)
    if s is None:
        s = MetricSnapshot(revision_id=rev.id, metric_id=metric_id, contract_version=contract.version,
                           value_type=value_type, shape=contract.shape.value, unit=contract.unit.value,
                           dashboard_homologation=contract.homologation.value, source_name='Manual',
                           source_reasons_json='[]', temporal_json=dumps({'competence': comp.label,
                                                                          'period': period(comp)}),
                           scope_refs_json='[]', provenance_json='{}', row_hash='')
        session.add(s)
    s.origin = SnapshotOrigin.MANUAL.value
    s.value_json = dumps(value)
    s.manual_justification, s.manual_operator, s.manual_at = justification, operator, now
    s.row_hash = snapshot_hash(s)
    session.flush()
    session.add(ManualChange(snapshot_id=s.id, revision_id=rev.id, metric_id=metric_id,
                             previous_value_json=previous_value, new_value_json=s.value_json,
                             previous_origin=previous_origin, new_origin=SnapshotOrigin.MANUAL.value,
                             justification=justification, operator=operator, changed_at=now))
    audit.append(session, 'metric.manual_set', owner_key=comp.owner_key, competence_id=comp.id, revision_id=rev.id,
                 actor=operator, details={'metric_id': metric_id, 'previous_origin': previous_origin,
                                          'source_status': s.source_status})
    _commit(session)
    session.refresh(rev)
    return s


def revert_manual(session: Session, comp: Competence, rev: CompetenceRevision, metric_id: str, justification: str,
                  operator: str, expected: int) -> MetricSnapshot:
    _contract(metric_id)
    s = _snapshot(rev, metric_id)
    if s is None or s.origin != SnapshotOrigin.MANUAL.value:
        raise conflict('not_manual', 'O indicador não tem valor manual nesta revisão')
    if s.source_status is None:
        raise conflict('no_source_value', 'Indicador sem coleta: não há valor da fonte para restaurar')
    _touch(session, rev, expected)
    now = utcnow()
    previous = s.value_json
    s.origin, s.value_json = SnapshotOrigin.VERACODE.value, s.source_value_json
    s.manual_justification = s.manual_operator = s.manual_at = None
    s.row_hash = snapshot_hash(s)
    session.add(ManualChange(snapshot_id=s.id, revision_id=rev.id, metric_id=metric_id, previous_value_json=previous,
                             new_value_json=s.value_json, previous_origin=SnapshotOrigin.MANUAL.value,
                             new_origin=SnapshotOrigin.VERACODE.value, justification=justification,
                             operator=operator, changed_at=now))
    audit.append(session, 'metric.manual_reverted', owner_key=comp.owner_key, competence_id=comp.id,
                 revision_id=rev.id, actor=operator, details={'metric_id': metric_id})
    _commit(session)
    session.refresh(rev)
    return s


def set_required(session: Session, comp: Competence, rev: CompetenceRevision, metric_ids: list[str], operator: str,
                 expected: int) -> None:
    unknown = sorted(set(metric_ids) - set(REGISTRY))
    if unknown:
        raise ApiError(422, 'unknown_metric', 'Indicador inexistente no catálogo',
                       [{'field': 'metric_ids', 'message': m, 'type': 'unknown_metric'} for m in unknown[:20]])
    _touch(session, rev, expected)
    ids = sorted(set(metric_ids))
    rev.required_metrics_json = dumps(ids)
    rev.required_set_version += 1
    audit.append(session, 'required_set.updated', owner_key=comp.owner_key, competence_id=comp.id,
                 revision_id=rev.id, actor=operator, details={'metric_ids': ids,
                                                              'version': rev.required_set_version})
    _commit(session)


# ---------------------------------------------------------------- revisão e aprovação

def approval_blockers(rev: CompetenceRevision) -> list[dict]:
    """O que impede a aprovação. Só os indicadores do conjunto explícito são exigidos."""
    out: list[dict] = []
    required = json.loads(rev.required_metrics_json)
    by_id = {s.metric_id: s for s in rev.snapshots}
    if not required:
        out.append({'code': 'required_set_empty', 'metric_id': None,
                    'message': 'Selecione explicitamente os indicadores obrigatórios desta competência'})
    for mid in required:
        if mid not in REGISTRY:
            out.append({'code': 'unknown_metric', 'metric_id': mid, 'message': 'Indicador fora do catálogo'})
        s = by_id.get(mid)
        if s is None or s.value_json is None:
            state = 'MISSING' if s is None else value_state(s.origin, None, s.source_status).value
            out.append({'code': 'missing_required', 'metric_id': mid,
                        'message': f'Indicador obrigatório sem valor ({state}): colete de novo ou informe '
                                   'valor manual justificado'})
    for s in rev.snapshots:
        if s.row_hash != snapshot_hash(s):
            out.append({'code': 'integrity_violation', 'metric_id': s.metric_id,
                        'message': 'Hash do snapshot não confere com o conteúdo'})
        if s.value_json is not None:
            try:
                validate(s.value_type, loads(s.value_json))
            except InvalidValue as exc:
                out.append({'code': 'invalid_value', 'metric_id': s.metric_id, 'message': exc.message})
    return out


def submit(session: Session, comp: Competence, rev: CompetenceRevision, operator: str, expected: int) -> None:
    _touch(session, rev, expected)
    rev.status = RevisionStatus.READY_FOR_REVIEW.value
    rev.submitted_by, rev.submitted_at = operator, utcnow()
    audit.append(session, 'revision.submitted', owner_key=comp.owner_key, competence_id=comp.id, revision_id=rev.id,
                 actor=operator, details={'blockers': len(approval_blockers(rev))})
    _commit(session)


def return_to_draft(session: Session, comp: Competence, rev: CompetenceRevision, operator: str, reason: str,
                    expected: int) -> None:
    if rev.status != RevisionStatus.READY_FOR_REVIEW.value:
        raise conflict('revision_not_in_review', 'Só revisões em revisão (READY_FOR_REVIEW) voltam a rascunho')
    _touch(session, rev, expected, require_draft=False)
    rev.status = RevisionStatus.DRAFT.value
    audit.append(session, 'revision.returned_to_draft', owner_key=comp.owner_key, competence_id=comp.id,
                 revision_id=rev.id, actor=operator, details={'reason': reason})
    _commit(session)


def content_hash(comp: Competence, rev: CompetenceRevision) -> str:
    return sha256({'competence': {'owner_key': comp.owner_key, 'label': comp.label, 'timezone': comp.timezone},
                   'revision': {'id': str(rev.id), 'number': rev.number},
                   'required': json.loads(rev.required_metrics_json),
                   'required_set_version': rev.required_set_version,
                   'snapshots': {s.metric_id: s.row_hash for s in rev.snapshots}})


def chain_hash(previous: str | None, content: str, sequence: int, approver: str, approved_at: datetime,
               revision_id: uuid.UUID) -> str:
    return sha256({'previous': previous, 'content_hash': content, 'sequence': sequence, 'approver': approver,
                   'approved_at': approved_at.astimezone(timezone.utc).isoformat(), 'revision_id': str(revision_id),
                   'identity_mode': IDENTITY_MODE})


def approve(session: Session, comp: Competence, rev: CompetenceRevision, approver: str, note: str | None,
            expected: int) -> Approval:
    if rev.status != RevisionStatus.READY_FOR_REVIEW.value:
        raise conflict('revision_not_in_review', 'Envie a revisão para revisão (READY_FOR_REVIEW) antes de aprovar')
    if rev.lock_version != expected:
        raise conflict('revision_conflict', f'A revisão está na versão {rev.lock_version}, não {expected}: outra '
                                            'operação a alterou; recarregue antes de aprovar')
    blockers = approval_blockers(rev)
    if blockers:
        audit.append(session, 'approval.blocked', owner_key=comp.owner_key, competence_id=comp.id,
                     revision_id=rev.id, actor=approver,
                     details={'codes': sorted({b['code'] for b in blockers}), 'count': len(blockers)})
        _commit(session)
        raise ApiError(409, 'approval_blocked', 'Aprovação bloqueada: corrija as pendências',
                       [{'field': b['metric_id'] or 'required_metrics', 'message': b['message'], 'type': b['code']}
                        for b in blockers[:100]])
    _touch(session, rev, expected, require_draft=False)
    rev.status = RevisionStatus.APPROVED.value
    session.flush()
    previous = latest_approval(session, comp.id)
    sequence = 1 if previous is None else previous.sequence + 1
    approved_at = utcnow()
    content = content_hash(comp, rev)
    prev_chain = None if previous is None else previous.chain_hash
    approval = Approval(competence_id=comp.id, revision_id=rev.id, sequence=sequence, approver=approver,
                        identity_mode=IDENTITY_MODE, note=note, approved_at=approved_at, content_hash=content,
                        previous_chain_hash=prev_chain,
                        chain_hash=chain_hash(prev_chain, content, sequence, approver, approved_at, rev.id))
    session.add(approval)
    session.flush()
    audit.append(session, 'revision.approved', owner_key=comp.owner_key, competence_id=comp.id, revision_id=rev.id,
                 actor=approver, details={'number': rev.number, 'sequence': sequence, 'content_hash': content,
                                          'identity_mode': IDENTITY_MODE})
    _commit(session)
    logger.info('competência aprovada dono=%s competência=%s revisão=%s', comp.owner_key, comp.label, rev.number)
    return approval


# ---------------------------------------------------------------- integridade e auditoria

def verify_integrity(session: Session, comp: Competence) -> dict:
    approvals = approvals_of(session, comp)
    revisions, problems = [], []
    for rev in comp.revisions:
        bad = [s.metric_id for s in rev.snapshots if s.row_hash != snapshot_hash(s)]
        a = approvals.get(rev.id)
        content_ok = None if a is None else a.content_hash == content_hash(comp, rev)
        revisions.append({'number': rev.number, 'status': rev.status, 'snapshots': len(rev.snapshots),
                          'snapshot_hash_mismatches': bad, 'approval_content_ok': content_ok})
        problems += [f'revisão {rev.number}: snapshot {m}' for m in bad]
        if content_ok is False:
            problems.append(f'revisão {rev.number}: conteúdo aprovado divergente')
    prev = None
    for a in sorted(approvals.values(), key=lambda x: x.sequence):
        expected = chain_hash(prev, a.content_hash, a.sequence, a.approver, a.approved_at, a.revision_id)
        if a.previous_chain_hash != prev or a.chain_hash != expected:
            problems.append(f'aprovação {a.sequence}: cadeia de hash divergente')
        prev = a.chain_hash
    chain = audit.verify_chain(session)
    if not chain['ok']:
        problems.append('cadeia de auditoria divergente')
    return {'ok': not problems, 'problems': problems, 'revisions': revisions, 'approvals': len(approvals),
            'audit_chain': chain}


def audit_events(session: Session, comp: Competence, limit: int = 500) -> list[dict]:
    events = session.scalars(select(AuditEvent).where(AuditEvent.competence_id == comp.id)
                             .order_by(AuditEvent.id).limit(limit))
    return [audit.event_out(e) for e in events]


def compare_revisions(comp: Competence, a: CompetenceRevision, b: CompetenceRevision) -> dict:
    sa_, sb = {s.metric_id: s for s in a.snapshots}, {s.metric_id: s for s in b.snapshots}
    items = []
    for mid in sorted(set(sa_) | set(sb)):
        x, y = sa_.get(mid), sb.get(mid)
        vx, vy = (loads(x.value_json) if x else None), (loads(y.value_json) if y else None)
        changed = (x is None) != (y is None) or (x is not None and x.row_hash != y.row_hash)
        items.append({'metric_id': mid, 'changed': changed, 'value_changed': vx != vy,
                      'a': None if x is None else {'value': vx, 'origin': x.origin, 'source_status': x.source_status,
                                                    'headline': headline(x.value_type, vx)},
                      'b': None if y is None else {'value': vy, 'origin': y.origin, 'source_status': y.source_status,
                                                    'headline': headline(y.value_type, vy)}})
    return {'competence': comp.label, 'a': a.number, 'b': b.number,
            'required_changed': a.required_metrics_json != b.required_metrics_json,
            'changed': sum(i['changed'] for i in items), 'items': items}


def list_competences(session: Session, kind: str, owner_id: uuid.UUID) -> list[dict]:
    owner = owner_of(session, kind, owner_id)
    comps = session.scalars(select(Competence).where(Competence.owner_key == owner.key)
                            .order_by(Competence.label.desc())).all()
    return [competence_out(session, c) for c in comps]


def find_competence(session: Session, owner_key: str, label: str) -> Competence | None:
    return session.scalar(select(Competence).where(Competence.owner_key == owner_key, Competence.label == label))
