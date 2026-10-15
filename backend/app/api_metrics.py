"""Endpoints de indicadores (F04). API local, sem autenticação (somente loopback). Veracode: SOMENTE LEITURA.

- `GET  /api/metrics/catalog`              contratos dos indicadores (implementados e lacunas)
- `POST /api/metrics/runs`                 inicia uma execução EXPLÍCITA (dono + competência) => 202
- `GET  /api/metrics/runs`                 execuções retidas em memória (sem os indicadores)
- `GET  /api/metrics/runs/{run_id}`        status, progresso e (ao terminar) indicadores com proveniência
- `POST /api/metrics/runs/{run_id}/cancel` cancela a execução (nenhum indicador é publicado)

Endpoints de execução são `async`: o estado das execuções e `Task.cancel()` só são tocados na thread do event loop.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from app.errors import ApiError
from app.metrics import competence as competence_mod
from app.metrics import registry
from app.metrics.population import load_inputs
from app.metrics.runs import RunManager

router = APIRouter(prefix='/api/metrics', tags=['metrics'])
_ERRORS = {404: {'description': 'Dono ou execução não encontrado'},
           422: {'description': 'Competência/fuso inválidos'}, 429: {'description': 'Execuções demais em curso'}}


class RunIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    owner_kind: Literal['client', 'subclient']
    owner_id: uuid.UUID
    competence: str = Field(min_length=7, max_length=7)
    timezone: str | None = Field(default=None, min_length=1, max_length=64,
                                 description='Fuso IANA; padrão = fuso do cliente')


def get_runs(request: Request) -> RunManager:
    return request.app.state.metric_runs


Runs = Annotated[RunManager, Depends(get_runs)]


def _run_or_404(runs: RunManager, run_id: str):
    run = runs.get(run_id)
    if run is None:
        raise ApiError(404, 'metric_run_not_found', 'Execução de métricas não encontrada (execuções vivem só em '
                                                    'memória e somem ao reiniciar o backend)')
    return run


@router.get('/catalog')
def catalog():
    return registry.catalog()


@router.post('/runs', status_code=202, responses=_ERRORS)
async def start_run(data: RunIn, request: Request, runs: Runs):
    if runs.active() >= runs.max_active:
        raise ApiError(429, 'too_many_metric_runs', 'Há execuções de métricas demais em curso; aguarde ou cancele')

    def load():
        with request.app.state.session_factory() as session:
            return load_inputs(session, data.owner_kind, data.owner_id)

    inputs = await run_in_threadpool(load)
    try:
        comp = competence_mod.parse(data.competence, data.timezone or inputs.timezone)
    except competence_mod.CompetenceError as exc:
        raise ApiError(422, exc.code, exc.message,
                       [{'field': 'competence' if 'competence' in exc.code else 'timezone',
                         'message': exc.message, 'type': exc.code}]) from None
    return runs.start(inputs, comp).public()


@router.get('/runs')
async def list_runs(runs: Runs):
    return {'items': [r.public(with_result=False) for r in runs.list()]}


@router.get('/runs/{run_id}', responses=_ERRORS)
async def get_run(run_id: str, runs: Runs):
    return _run_or_404(runs, run_id).public()


@router.post('/runs/{run_id}/cancel', responses=_ERRORS)
async def cancel_run(run_id: str, runs: Runs, response: Response):
    run = _run_or_404(runs, run_id)
    already = run.finished
    runs.cancel(run_id)
    response.status_code = 200 if already else 202
    return run.public(with_result=False)
