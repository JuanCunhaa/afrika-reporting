"""Endpoints da conferência humana com a plataforma Veracode (F10). API local, sem autenticação (só loopback).

- `GET  /api/competences/{cid}/revisions/{n}/conference`                        planilha (35 indicadores, guia, status)
- `GET  /api/competences/{cid}/revisions/{n}/conference.csv`                    a mesma planilha em CSV (evidência local)
- `POST /api/competences/{cid}/revisions/{n}/conference/{metric_id}`            registra valor oficial (append-only)
- `GET  /api/competences/{cid}/revisions/{n}/conference/{metric_id}/history`    registros anteriores do indicador

O valor calculado nunca vem do cliente: é lido do snapshot da revisão. Conferir não altera snapshot nem aprovação.
"""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.api import SessionDep
from app.api_snapshots import Declared, MetricId
from app.reconciliation import service
from app.snapshots import service as snapshots

router = APIRouter(tags=['conference'])
_ERRORS = {404: {'description': 'Não encontrado'}, 409: {'description': 'Sem valor oficial equivalente / conflito'},
           422: {'description': 'Validação'}}
LineKey = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)]


class ConferenceIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operator: Declared
    checked_on: dt.date
    filters_confirmed: bool
    official: dict[LineKey, int] = Field(max_length=500)
    evidence: Text | None = None
    not_comparable_note: Text | None = None


def _load(session, cid: uuid.UUID, number: int):
    comp = snapshots.get_competence(session, cid)
    return comp, snapshots.get_revision(session, comp, number)


@router.get('/api/competences/{cid}/revisions/{number}/conference', responses=_ERRORS)
def get_sheet(cid: uuid.UUID, number: int, session: SessionDep):
    return service.sheet(session, *_load(session, cid, number))


@router.get('/api/competences/{cid}/revisions/{number}/conference.csv', responses=_ERRORS)
def get_sheet_csv(cid: uuid.UUID, number: int, session: SessionDep):
    comp, rev = _load(session, cid, number)
    body = '﻿' + service.to_csv(service.sheet(session, comp, rev))  # BOM: acentos corretos no Excel
    name = f'conferencia-{comp.label}-r{rev.number}.csv'
    return Response(body.encode('utf-8'), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{name}"', 'Cache-Control': 'no-store',
                             'X-Content-Type-Options': 'nosniff'})


@router.post('/api/competences/{cid}/revisions/{number}/conference/{metric_id}', status_code=201, responses=_ERRORS)
def post_conference(cid: uuid.UUID, number: int, metric_id: MetricId, data: ConferenceIn, session: SessionDep):
    comp, rev = _load(session, cid, number)
    return service.record(session, comp, rev, metric_id, official=data.official,
                          filters_confirmed=data.filters_confirmed, checked_on=data.checked_on,
                          operator=data.operator, evidence=data.evidence, note=data.not_comparable_note)


@router.get('/api/competences/{cid}/revisions/{number}/conference/{metric_id}/history', responses=_ERRORS)
def get_history(cid: uuid.UUID, number: int, metric_id: MetricId, session: SessionDep):
    comp, rev = _load(session, cid, number)
    return service.history(session, comp, rev, metric_id)
