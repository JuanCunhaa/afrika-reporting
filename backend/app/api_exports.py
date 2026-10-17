"""Endpoints da exportação PPTX/PDF (F07). API local, sem autenticação (só loopback); operador DECLARADO.

- `GET  /api/export-engine`                         disponibilidade (build do renderizador atualizado? navegador?)
- `POST /api/presentations/{pid}/exports`           cria exportação da revisão PERSISTIDA informada (202)
- `GET  /api/presentations/{pid}/exports`           exportações recentes da apresentação (status/erros)
- `GET  /api/exports/{job_id}`                      status, erros, avisos e relatório de validação
- `GET  /api/exports/{job_id}/file`                 download (só concluída com sucesso)

Nada aqui altera snapshots, aprovações ou revisões; nenhuma chamada à Veracode. O cliente não informa caminhos nem
nomes de arquivo: o nome é gerado no servidor e o download é pelo id aleatório do job.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.api import SessionDep
from app.errors import ApiError
from app.export import browser, renderer
from app.export import service as export_service
from app.export.errors import ExportError
from app.presentations import service

router = APIRouter(tags=['exports'])
_ERRORS = {404: {'description': 'Não encontrado'}, 409: {'description': 'Exportação recusada'},
           422: {'description': 'Validação'}, 429: {'description': 'Fila cheia'},
           503: {'description': 'Motor de renderização indisponível'}}
Declared = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120,
                                            pattern=r'^[^\x00-\x1f\x7f]+$')]


class ExportIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    format: Literal['pptx', 'pdf']
    revision: int = Field(ge=1)  # revisão PERSISTIDA, explícita (nunca o rascunho do editor)
    operator: Declared


def _api(exc: ExportError) -> ApiError:
    return ApiError(exc.status, exc.code, exc.message, exc.details)


@router.get('/api/export-engine')
def export_engine():
    out: dict = {'formats': sorted(export_service.FORMATS), 'available': True}
    try:
        r = renderer.locate()
        out['renderer'] = {'ok': True, 'source_hash': r.source_hash, 'stamp_check': r.stamp_check}
    except ExportError as exc:
        out['renderer'], out['available'] = {'ok': False, 'code': exc.code, 'message': exc.message}, False
    try:
        exe = browser.discover()
        out['browser'] = {'ok': True, 'source': exe.source}
    except ExportError as exc:
        out['browser'], out['available'] = {'ok': False, 'code': exc.code, 'message': exc.message}, False
    return out


@router.post('/api/presentations/{pid}/exports', status_code=202, responses=_ERRORS)
def create_export(pid: uuid.UUID, data: ExportIn, request: Request, session: SessionDep):
    p = service.get(session, pid)
    rev = service.get_revision(session, p, data.revision)
    try:
        v = export_service.precheck(session, p, rev)
        job = request.app.state.exports.submit(v, data.format, data.operator)
    except ExportError as exc:
        raise _api(exc) from None
    return job.public()


@router.get('/api/presentations/{pid}/exports', responses=_ERRORS)
def list_exports(pid: uuid.UUID, request: Request, session: SessionDep):
    service.get(session, pid)
    return {'items': [j.public() for j in request.app.state.exports.list_for(str(pid))]}


@router.get('/api/exports/{job_id}', responses=_ERRORS)
def get_export(job_id: uuid.UUID, request: Request):
    try:
        return request.app.state.exports.get(str(job_id)).public()
    except ExportError as exc:
        raise _api(exc) from None


@router.get('/api/exports/{job_id}/file', responses=_ERRORS)
def download_export(job_id: uuid.UUID, request: Request):
    try:
        job = request.app.state.exports.file(str(job_id))
    except ExportError as exc:
        raise _api(exc) from None
    return FileResponse(job.path, media_type=job.media_type, filename=job.filename,
                        headers={'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store',
                                 'X-Export-Sha256': job.sha256 or ''})
