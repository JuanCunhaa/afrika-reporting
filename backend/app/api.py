"""Endpoints REST do cadastro (F01). Sem autenticação: API local, NÃO expor publicamente."""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app import registry, schemas
from app.db import iter_session

router = APIRouter(prefix='/api')

MAX_PAGE_SIZE = 200


def get_session(request: Request) -> Iterator[Session]:
    yield from iter_session(request.app.state.session_factory)


SessionDep = Annotated[Session, Depends(get_session)]
Limit = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]
Offset = Annotated[int, Query(ge=0)]
Status = Annotated[Literal['all', 'active', 'inactive'], Query()]
_ERRORS = {400: {'description': 'Regra de negócio / JSON malformado'}, 404: {'description': 'Não encontrado'},
           409: {'description': 'Conflito'}, 422: {'description': 'Validação'}}


# ---------------------------------------------------------------- conexões

@router.get('/connections', response_model=schemas.Page[schemas.ConnectionOut], tags=['connections'])
def list_connections(session: SessionDep, limit: Limit = 50, offset: Offset = 0):
    return registry.list_connections(session, limit, offset)


@router.post('/connections', response_model=schemas.ConnectionOut, status_code=201, tags=['connections'],
             responses=_ERRORS)
def create_connection(data: schemas.ConnectionCreate, session: SessionDep):
    return registry.create_connection(session, data)


@router.get('/connections/{connection_id}', response_model=schemas.ConnectionOut, tags=['connections'],
            responses=_ERRORS)
def get_connection(connection_id: uuid.UUID, session: SessionDep):
    return registry.get_connection(session, connection_id)


@router.patch('/connections/{connection_id}', response_model=schemas.ConnectionOut, tags=['connections'],
              responses=_ERRORS)
def update_connection(connection_id: uuid.UUID, data: schemas.ConnectionUpdate, session: SessionDep):
    return registry.update_connection(session, connection_id, data)


@router.delete('/connections/{connection_id}', status_code=204, tags=['connections'], responses=_ERRORS)
def delete_connection(connection_id: uuid.UUID, session: SessionDep):
    registry.delete_connection(session, connection_id)
    return Response(status_code=204)


# ---------------------------------------------------------------- clientes

@router.get('/clients', response_model=schemas.Page[schemas.ClientOut], tags=['clients'])
def list_clients(session: SessionDep, limit: Limit = 50, offset: Offset = 0, status: Status = 'all',
                 q: Annotated[str | None, Query(max_length=120)] = None):
    return registry.list_clients(session, limit, offset, status, q.strip() if q else None)


@router.post('/clients', response_model=schemas.ClientOut, status_code=201, tags=['clients'], responses=_ERRORS)
def create_client(data: schemas.ClientCreate, session: SessionDep):
    return registry.create_client(session, data)


@router.get('/clients/{client_id}', response_model=schemas.ClientOut, tags=['clients'], responses=_ERRORS)
def get_client(client_id: uuid.UUID, session: SessionDep):
    return registry.get_client(session, client_id)


@router.patch('/clients/{client_id}', response_model=schemas.ClientOut, tags=['clients'], responses=_ERRORS)
def update_client(client_id: uuid.UUID, data: schemas.ClientUpdate, session: SessionDep):
    return registry.update_client(session, client_id, data)


@router.delete('/clients/{client_id}', status_code=204, tags=['clients'], responses=_ERRORS)
def delete_client(client_id: uuid.UUID, session: SessionDep):
    registry.delete_client(session, client_id)
    return Response(status_code=204)


# ---------------------------------------------------------------- subclientes

@router.get('/clients/{client_id}/subclients', response_model=schemas.Page[schemas.SubclientOut],
            tags=['subclients'], responses=_ERRORS)
def list_subclients(client_id: uuid.UUID, session: SessionDep, limit: Limit = 50, offset: Offset = 0,
                    status: Status = 'all'):
    return registry.list_subclients(session, client_id, limit, offset, status)


@router.post('/clients/{client_id}/subclients', response_model=schemas.SubclientOut, status_code=201,
             tags=['subclients'], responses=_ERRORS)
def create_subclient(client_id: uuid.UUID, data: schemas.SubclientCreate, session: SessionDep):
    return registry.create_subclient(session, client_id, data)


@router.get('/subclients/{subclient_id}', response_model=schemas.SubclientOut, tags=['subclients'],
            responses=_ERRORS)
def get_subclient(subclient_id: uuid.UUID, session: SessionDep):
    return registry.get_subclient(session, subclient_id)


@router.patch('/subclients/{subclient_id}', response_model=schemas.SubclientOut, tags=['subclients'],
              responses=_ERRORS)
def update_subclient(subclient_id: uuid.UUID, data: schemas.SubclientUpdate, session: SessionDep):
    return registry.update_subclient(session, subclient_id, data)


@router.delete('/subclients/{subclient_id}', status_code=204, tags=['subclients'], responses=_ERRORS)
def delete_subclient(subclient_id: uuid.UUID, session: SessionDep):
    registry.delete_subclient(session, subclient_id)
    return Response(status_code=204)
