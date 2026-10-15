"""Endpoints da Reporting API (F05). API local, sem autenticação (somente loopback).

A geração de relatório é a ÚNICA escrita autorizada na Veracode, desligada por padrão
(`AFRIKA_VERACODE_REPORTING_ENABLED=true` habilita). Execuções vivem só em memória e guardam apenas metadados e
agregados exploratórios — nenhum finding individual.

- `GET  /api/reporting/status`             política, limites, cota e se a geração está habilitada
- `POST /api/reporting/jobs`               gera relatório FINDINGS/SCANS para a conexão do dono => 202
- `GET  /api/reporting/jobs`               execuções retidas
- `GET  /api/reporting/jobs/{job_id}`      status, progresso, metadados do relatório e agregados
- `POST /api/reporting/jobs/{job_id}/cancel`  cancela localmente (a API não oferece cancelamento remoto)
"""
from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool

from app.errors import ApiError
from app.veracode import reporting_policy as policy
from app.veracode.discovery import DiscoveryService, resolve_scope
from app.veracode.errors import VeracodeError
from app.veracode.reporting import ReportingJobs

router = APIRouter(prefix='/api/reporting', tags=['reporting'])
_ERRORS = {404: {'description': 'Não encontrado'}, 409: {'description': 'Geração desabilitada / sem conexão'},
           422: {'description': 'Pedido fora da política'}, 429: {'description': 'Limite/cota de relatórios'}}
NOT_ENABLED = {
    'DELETEDSCANS': 'Estudado (scans excluídos permanentemente); sem uso nos dashboards atuais — não habilitado',
    'AUDIT': 'Estudado (log de auditoria com ações e IDs de usuários = dados pessoais) — não habilitado',
}


class JobIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    owner_kind: Literal['client', 'subclient']
    owner_id: uuid.UUID
    request: dict


def get_jobs(request: Request) -> ReportingJobs:
    return request.app.state.reporting


Jobs = Annotated[ReportingJobs, Depends(get_jobs)]


def _job_or_404(jobs: ReportingJobs, job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise ApiError(404, 'report_job_not_found', 'Execução de relatório não encontrada (vive só em memória)')
    return job


@router.get('/status')
async def status(jobs: Jobs):
    s = jobs.settings
    return {'enabled': s.reporting_enabled, 'mode': s.mode, 'enabled_types': list(policy.ENABLED_TYPES),
            'known_types': list(policy.KNOWN_TYPES), 'not_enabled_types': NOT_ENABLED,
            'allowed_operations': [f'POST {policy.GENERATION_PATH} (somente geração; corpo validado; desligado por '
                                   'padrão)', f'GET {policy.GENERATION_PATH}/{{id}}?page=N'],
            'limits': {'max_window_days': s.reporting_max_window_days, 'max_polls': s.reporting_max_polls,
                       'poll_interval_seconds': s.reporting_poll_interval,
                       'poll_max_interval_seconds': s.reporting_poll_max_interval,
                       'timeout_seconds': s.reporting_timeout, 'max_pages': s.reporting_max_pages,
                       'max_active': s.reporting_max_active, 'max_per_hour': s.reporting_max_per_hour},
            'active': jobs.active(), 'quota_left_this_hour': max(jobs.quota_left(), 0),
            'fields': {t: sorted(policy.ALLOWED_FIELDS[t]) for t in policy.ENABLED_TYPES},
            'scan_types': {'FINDINGS': list(policy.FINDINGS_SCAN_TYPES), 'SCANS': list(policy.SCANS_SCAN_TYPES)}}


@router.post('/jobs', status_code=202, responses=_ERRORS)
async def start_job(data: JobIn, request: Request, jobs: Jobs):
    s = jobs.settings
    if not s.reporting_enabled:
        raise VeracodeError('reporting_disabled')
    try:
        report = policy.build(data.request, max_days=s.reporting_max_window_days)
    except policy.ReportPolicyError as exc:
        raise ApiError(422, exc.code, exc.message, [{'field': f'request.{exc.field or ""}'.rstrip('.'),
                                                     'message': exc.message, 'type': exc.code}]) from None
    if jobs.active() >= s.reporting_max_active:
        raise ApiError(429, 'too_many_reports', 'Já há relatório em processamento; aguarde ou cancele')
    if jobs.quota_left() <= 0:
        raise ApiError(429, 'report_quota_exceeded', 'Cota local de gerações por hora atingida')
    service: DiscoveryService = request.app.state.veracode

    def load():
        with request.app.state.session_factory() as session:
            return resolve_scope(session, data.owner_kind, data.owner_id)

    ctx = await run_in_threadpool(load)
    creds = service.credentials_for(ctx)  # VeracodeError (sem conexão/credencial) => 409 pelo handler
    owner = {'kind': ctx.kind, 'id': str(ctx.id), 'name': ctx.name, 'connection_source': ctx.connection_source,
             'connection': {'id': str(ctx.connection_id), 'name': ctx.connection_name, 'region': ctx.region}}
    return jobs.start(owner, report, creds, ctx.region).public()


@router.get('/jobs')
async def list_jobs(jobs: Jobs):
    return {'items': [j.public() for j in jobs.list()]}


@router.get('/jobs/{job_id}', responses=_ERRORS)
async def get_job(job_id: str, jobs: Jobs):
    return _job_or_404(jobs, job_id).public()


@router.post('/jobs/{job_id}/cancel', responses=_ERRORS)
async def cancel_job(job_id: str, jobs: Jobs, response: Response):
    job = _job_or_404(jobs, job_id)
    already = job.finished
    jobs.cancel(job_id)
    response.status_code = 200 if already else 202
    return job.public()
