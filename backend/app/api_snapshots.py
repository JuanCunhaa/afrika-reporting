"""Endpoints de competências, snapshots, aprovação e histórico (F05). API local, sem autenticação (só loopback).

Operador/aprovador são DECLARADOS pelo usuário (texto livre): servem para rastreabilidade, NÃO são identidade
autenticada. Toda alteração de revisão exige `expected_lock_version` (conflito => 409, nunca sobrescrita).

- `GET  /api/competences?owner_kind&owner_id`                         competências do dono
- `POST /api/competences`                                             cria competência + revisão 1 (DRAFT)
- `POST /api/competences/from-run`                                    rascunho a partir de execução F04 concluída
- `GET  /api/competences/{cid}`                                       competência + revisões
- `GET  /api/competences/{cid}/official`                              revisão oficial (última aprovada)
- `POST /api/competences/{cid}/revisions`                             nova revisão a partir da última aprovada
- `GET  /api/competences/{cid}/revisions/{n}`                         revisão + snapshots + pendências
- `POST /api/competences/{cid}/revisions/{n}/import-run`              importa execução F04 no rascunho
- `PUT  /api/competences/{cid}/revisions/{n}/metrics/{metric_id}`     valor manual (justificativa obrigatória)
- `POST /api/competences/{cid}/revisions/{n}/metrics/{metric_id}/revert`  volta ao valor da fonte
- `PUT  /api/competences/{cid}/revisions/{n}/required`                conjunto explícito de obrigatórios
- `POST /api/competences/{cid}/revisions/{n}/submit|return|approve`   ciclo de vida
- `GET  /api/competences/{cid}/compare?a&b`                           diferença entre revisões
- `GET  /api/competences/{cid}/audit` | `/integrity`                  trilha de auditoria e verificação de hashes
- `GET  /api/history/{kind}/{owner_id}/series?metric_id&months|start&end`  série (só aprovados; lacunas)
- `GET  /api/history/{kind}/{owner_id}/compare?competence&metric_id`  mês × mês anterior (só aprovados)
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from starlette.concurrency import run_in_threadpool

from app import backup
from app.api import SessionDep
from app.errors import ApiError, conflict
from app.snapshots import history, service

router = APIRouter(tags=['snapshots'])
_ERRORS = {404: {'description': 'Não encontrado'}, 409: {'description': 'Conflito / bloqueio / estado'},
           422: {'description': 'Validação'}}

_NO_CONTROL = r'^[^\x00-\x1f\x7f]+$'
Declared = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120, pattern=_NO_CONTROL)]
Justification = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=2000)]
Label = Annotated[str, StringConstraints(pattern=r'^\d{4}-(0[1-9]|1[0-2])$')]
MetricId = Annotated[str, StringConstraints(min_length=1, max_length=80, pattern=r'^[a-z0-9_.]+$')]
Kind = Literal['client', 'subclient']


class _Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class CompetenceIn(_Strict):
    owner_kind: Kind
    owner_id: uuid.UUID
    competence: Label
    operator: Declared


class FromRunIn(_Strict):
    run_id: uuid.UUID
    operator: Declared


class RevisionIn(_Strict):
    operator: Declared


class Locked(_Strict):
    operator: Declared
    expected_lock_version: int = Field(ge=1)


class ImportIn(Locked):
    run_id: uuid.UUID


class ManualIn(Locked):
    value: Any
    justification: Justification


class RevertIn(Locked):
    justification: Justification


class RequiredIn(Locked):
    metric_ids: list[MetricId] = Field(max_length=200)


class ReturnIn(Locked):
    reason: Justification


class ApproveIn(_Strict):
    approver: Declared
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None
    expected_lock_version: int = Field(ge=1)


def _run_snapshot(request: Request, run_id: uuid.UUID) -> dict:
    run = request.app.state.metric_runs.get(str(run_id))
    if run is None:
        raise ApiError(404, 'metric_run_not_found', 'Execução de métricas não encontrada (execuções vivem só em '
                                                    'memória; inicie e importe a coleta na mesma sessão do backend)')
    return run.public()


def _revision_detail(session, cid: uuid.UUID, number: int) -> dict:
    comp = service.get_competence(session, cid)
    return service.revision_out(session, comp, service.get_revision(session, comp, number))


# ---------------------------------------------------------------- competências

@router.get('/api/competences')
def list_competences(session: SessionDep, owner_kind: Kind, owner_id: uuid.UUID):
    return {'items': service.list_competences(session, owner_kind, owner_id)}


@router.post('/api/competences', status_code=201, responses=_ERRORS)
def create_competence(data: CompetenceIn, session: SessionDep):
    comp = service.create_competence(session, data.owner_kind, data.owner_id, data.competence, data.operator)
    return service.competence_out(session, comp)


@router.post('/api/competences/from-run', status_code=201, responses=_ERRORS)
async def from_run(data: FromRunIn, request: Request):
    run = _run_snapshot(request, data.run_id)

    def work():
        with request.app.state.session_factory() as session:
            if run['status'] != 'done' or not run.get('result'):
                raise conflict('run_not_done', 'Só execuções concluídas podem ser importadas')
            owner = run['owner']
            o = service.owner_of(session, owner['kind'], uuid.UUID(owner['id']))
            label, tz = run['competence']['competence'], run['competence']['timezone']
            if tz != o.client.timezone:
                raise conflict('timezone_mismatch', f'A execução usou o fuso {tz}; o cliente usa '
                                                    f'{o.client.timezone}. Colete de novo no fuso do cliente')
            comp = service.find_competence(session, o.key, label)
            if comp is None:
                comp = service.create_competence(session, o.kind, o.id, label, data.operator)
            open_rev = next((r for r in comp.revisions if r.status != 'APPROVED'), None)
            if open_rev is None:
                open_rev = service.create_revision(session, comp, data.operator)
            elif open_rev.status != 'DRAFT':
                raise conflict('revision_not_draft', 'A revisão aberta está em revisão: devolva-a a rascunho antes '
                                                     'de importar')
            imported = service.import_run(session, comp, open_rev, run, data.operator, open_rev.lock_version)
            return {'competence_id': str(comp.id), 'revision': open_rev.number, 'import': imported,
                    'detail': service.revision_out(session, comp, open_rev)}

    return await run_in_threadpool(work)


@router.get('/api/competences/{cid}', responses=_ERRORS)
def get_competence(cid: uuid.UUID, session: SessionDep):
    return service.competence_out(session, service.get_competence(session, cid))


@router.get('/api/competences/{cid}/official', responses=_ERRORS)
def get_official(cid: uuid.UUID, session: SessionDep):
    comp = service.get_competence(session, cid)
    approval = service.latest_approval(session, comp.id)
    if approval is None:
        raise ApiError(404, 'no_approved_revision', 'Competência sem revisão aprovada (lacuna no histórico oficial)')
    rev = next(r for r in comp.revisions if r.id == approval.revision_id)
    return service.revision_out(session, comp, rev)


@router.post('/api/competences/{cid}/revisions', status_code=201, responses=_ERRORS)
def create_revision(cid: uuid.UUID, data: RevisionIn, session: SessionDep):
    comp = service.get_competence(session, cid)
    rev = service.create_revision(session, comp, data.operator)
    return service.revision_out(session, comp, rev)


@router.get('/api/competences/{cid}/revisions/{number}', responses=_ERRORS)
def get_revision(cid: uuid.UUID, number: int, session: SessionDep):
    return _revision_detail(session, cid, number)


@router.post('/api/competences/{cid}/revisions/{number}/import-run', responses=_ERRORS)
async def import_run(cid: uuid.UUID, number: int, data: ImportIn, request: Request):
    run = _run_snapshot(request, data.run_id)

    def work():
        with request.app.state.session_factory() as session:
            comp = service.get_competence(session, cid)
            rev = service.get_revision(session, comp, number)
            imported = service.import_run(session, comp, rev, run, data.operator, data.expected_lock_version)
            return {'import': imported, 'detail': service.revision_out(session, comp, rev)}

    return await run_in_threadpool(work)


@router.put('/api/competences/{cid}/revisions/{number}/metrics/{metric_id}', responses=_ERRORS)
def set_manual(cid: uuid.UUID, number: int, metric_id: MetricId, data: ManualIn, session: SessionDep):
    comp = service.get_competence(session, cid)
    rev = service.get_revision(session, comp, number)
    service.set_manual(session, comp, rev, metric_id, data.value, data.justification, data.operator,
                       data.expected_lock_version)
    return service.revision_out(session, comp, rev)


@router.post('/api/competences/{cid}/revisions/{number}/metrics/{metric_id}/revert', responses=_ERRORS)
def revert_manual(cid: uuid.UUID, number: int, metric_id: MetricId, data: RevertIn, session: SessionDep):
    comp = service.get_competence(session, cid)
    rev = service.get_revision(session, comp, number)
    service.revert_manual(session, comp, rev, metric_id, data.justification, data.operator,
                          data.expected_lock_version)
    return service.revision_out(session, comp, rev)


@router.put('/api/competences/{cid}/revisions/{number}/required', responses=_ERRORS)
def set_required(cid: uuid.UUID, number: int, data: RequiredIn, session: SessionDep):
    comp = service.get_competence(session, cid)
    rev = service.get_revision(session, comp, number)
    service.set_required(session, comp, rev, data.metric_ids, data.operator, data.expected_lock_version)
    return service.revision_out(session, comp, rev)


@router.post('/api/competences/{cid}/revisions/{number}/submit', responses=_ERRORS)
def submit(cid: uuid.UUID, number: int, data: Locked, session: SessionDep):
    comp = service.get_competence(session, cid)
    rev = service.get_revision(session, comp, number)
    service.submit(session, comp, rev, data.operator, data.expected_lock_version)
    return service.revision_out(session, comp, rev)


@router.post('/api/competences/{cid}/revisions/{number}/return', responses=_ERRORS)
def return_to_draft(cid: uuid.UUID, number: int, data: ReturnIn, session: SessionDep):
    comp = service.get_competence(session, cid)
    rev = service.get_revision(session, comp, number)
    service.return_to_draft(session, comp, rev, data.operator, data.reason, data.expected_lock_version)
    return service.revision_out(session, comp, rev)


@router.post('/api/competences/{cid}/revisions/{number}/approve', responses=_ERRORS)
def approve(cid: uuid.UUID, number: int, data: ApproveIn, request: Request, session: SessionDep):
    comp = service.get_competence(session, cid)
    rev = service.get_revision(session, comp, number)
    made: dict = {}

    def safety_copy() -> dict:  # F11: backup verificado antes de aprovar; falha => aprovação bloqueada
        info = backup.before_approval(request.app.state.db_url, request.app.state.backup_dir)
        made.update(file=info.path.name, sha256=info.sha256, alembic_revision=info.alembic_revision,
                    integrity=info.integrity)
        return dict(made)  # só nome do arquivo (sem caminho local) na auditoria

    service.approve(session, comp, rev, data.approver, data.note or None, data.expected_lock_version,
                    backup=safety_copy)
    return {**service.revision_out(session, comp, rev), 'approval_backup': made}


@router.get('/api/competences/{cid}/compare', responses=_ERRORS)
def compare(cid: uuid.UUID, session: SessionDep, a: Annotated[int, Query(ge=1)], b: Annotated[int, Query(ge=1)]):
    comp = service.get_competence(session, cid)
    return service.compare_revisions(comp, service.get_revision(session, comp, a), service.get_revision(session, comp, b))


@router.get('/api/competences/{cid}/audit', responses=_ERRORS)
def audit_trail(cid: uuid.UUID, session: SessionDep):
    comp = service.get_competence(session, cid)
    return {'items': service.audit_events(session, comp)}


@router.get('/api/competences/{cid}/integrity', responses=_ERRORS)
def integrity(cid: uuid.UUID, session: SessionDep):
    return service.verify_integrity(session, service.get_competence(session, cid))


# ---------------------------------------------------------------- histórico (somente aprovados)

@router.get('/api/history/{kind}/{owner_id}/series', responses=_ERRORS)
def series(kind: Kind, owner_id: uuid.UUID, session: SessionDep, metric_id: MetricId,
           months: Annotated[int | None, Query(ge=1, le=history.MAX_MONTHS)] = None,
           start: str | None = None, end: str | None = None):
    return history.series(session, kind, owner_id, metric_id, months=months, start=start, end=end)


@router.get('/api/history/{kind}/{owner_id}/compare', responses=_ERRORS)
def compare_previous(kind: Kind, owner_id: uuid.UUID, session: SessionDep, competence: str,
                     metric_id: Annotated[list[MetricId] | None, Query()] = None):
    return history.compare_previous(session, kind, owner_id, competence, metric_id)
