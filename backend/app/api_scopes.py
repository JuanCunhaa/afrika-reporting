"""Endpoints de escopos (F03). API local, sem autenticação (somente loopback). Veracode: SOMENTE LEITURA.

- `GET  /api/scopes/fields`                                   catálogo de campos/operadores/limites por domínio
- `POST /api/scopes/validate`                                 valida uma regra (não grava, não consulta a Veracode)
- `GET  /api/scopes/clients/{client_id}`                      visão geral: cliente + subclientes × domínios
- `GET  /api/scopes/{kind}/{owner_id}/{domain}`               definição + histórico de versões
- `PUT  /api/scopes/{kind}/{owner_id}/{domain}`               salva NOVA versão (expected_version obrigatório)
- `PATCH /api/scopes/{kind}/{owner_id}/{domain}`              ativa/desativa o escopo (status)
- `POST /api/scopes/{kind}/{owner_id}/{domain}/versions/{n}/restore`  nova versão com a regra da versão n
- `POST /api/scope-preview/clients/{client_id}`               resolução (salva ou com rascunho) sobre a descoberta
"""
from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api import SessionDep
from app.errors import ApiError, bad_request
from app.schemas import Description
from app.scopes import resolver, rules, store
from app.veracode.discovery import DiscoveryService, resolve_scope

router = APIRouter(tags=['scopes'])

OwnerPath = Literal['clients', 'subclients']
DomainPath = Literal['applications', 'users', 'scans', 'sca']
_KIND = {'clients': 'client', 'subclients': 'subclient'}
_ERRORS = {404: {'description': 'Não encontrado'}, 409: {'description': 'Conflito de versão / abrangência'},
           422: {'description': 'Regra ou opções inválidas'}}


class _Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ValidateIn(_Strict):
    domain: DomainPath
    rule: Any
    options: dict = Field(default_factory=dict)


class SaveIn(_Strict):
    rule: Any
    options: dict = Field(default_factory=dict)
    note: Description = None
    coverage_ack: bool = False
    expected_version: int = Field(ge=0)


class RestoreIn(_Strict):
    note: Description = None
    coverage_ack: bool = False
    expected_version: int = Field(ge=0)


class StatusIn(_Strict):
    status: Literal['active', 'disabled']


class DraftIn(_Strict):
    owner_kind: Literal['client', 'subclient']
    owner_id: uuid.UUID
    rule: Any
    options: dict = Field(default_factory=dict)
    coverage_ack: bool = False


class PreviewIn(_Strict):
    domain: DomainPath
    draft: DraftIn | None = None
    sample_limit: int = Field(default=25, ge=0, le=resolver.MAX_SAMPLE)


def get_service(request: Request) -> DiscoveryService:
    return request.app.state.veracode


@router.get('/api/scopes/fields')
def fields():
    return rules.fields_catalog()


@router.post('/api/scopes/validate', responses=_ERRORS)
def validate(data: ValidateIn):
    result = rules.validate(data.domain, data.rule).as_dict()
    try:
        store.validate_options(data.domain, data.options)
    except ApiError as exc:
        result['valid'] = False
        result['issues'] += exc.details or []
        result['rule'] = result['rule_hash'] = None
    return result


@router.get('/api/scopes/clients/{client_id}', responses=_ERRORS)
def overview(client_id: uuid.UUID, session: SessionDep):
    return store.client_overview(session, client_id)


@router.get('/api/scopes/{kind}/{owner_id}/{domain}', responses=_ERRORS)
def get_scope(kind: OwnerPath, owner_id: uuid.UUID, domain: DomainPath, session: SessionDep):
    return store.get_scope(session, _KIND[kind], owner_id, domain)


@router.put('/api/scopes/{kind}/{owner_id}/{domain}', responses=_ERRORS)
def save_scope(kind: OwnerPath, owner_id: uuid.UUID, domain: DomainPath, data: SaveIn, session: SessionDep,
               response: Response):
    out, created = store.save_scope(session, _KIND[kind], owner_id, domain, rule=data.rule, options=data.options,
                                    note=data.note, coverage_ack=data.coverage_ack,
                                    expected_version=data.expected_version)
    response.status_code = 201 if created else 200
    return {**out, 'created': created}


@router.patch('/api/scopes/{kind}/{owner_id}/{domain}', responses=_ERRORS)
def set_status(kind: OwnerPath, owner_id: uuid.UUID, domain: DomainPath, data: StatusIn, session: SessionDep):
    return store.set_status(session, _KIND[kind], owner_id, domain, data.status)


@router.post('/api/scopes/{kind}/{owner_id}/{domain}/versions/{number}/restore', responses=_ERRORS)
def restore(kind: OwnerPath, owner_id: uuid.UUID, domain: DomainPath, number: int, data: RestoreIn,
            session: SessionDep, response: Response):
    out, created = store.restore_version(session, _KIND[kind], owner_id, domain, number, note=data.note,
                                         coverage_ack=data.coverage_ack, expected_version=data.expected_version)
    response.status_code = 201 if created else 200
    return {**out, 'created': created}


def _load(session: Session, client_id: uuid.UUID, data: PreviewIn):
    client, subs = store.owner_rules(session, client_id, data.domain)
    if data.draft is not None:
        d = data.draft
        owners = [client] + subs
        target = next((o for o in owners if o.owner.kind == d.owner_kind and o.owner.id == d.owner_id), None)
        if target is None:
            raise bad_request('draft_owner_mismatch', 'O rascunho não pertence a este cliente')
        rule = store.validated_rule(data.domain, d.rule)
        options = store.validate_options(data.domain, d.options)
        drafted = replace(target, rule=rule, options=options, status='active', draft=True, saved_mode=target.mode,
                          coverage_ack=d.coverage_ack and target.mode == 'separate')
        client = drafted if target is client else client
        subs = [drafted if o is target else o for o in subs]
    ctx_client = resolve_scope(session, 'client', client_id)
    ctx_subs = {s.owner.id: resolve_scope(session, 'subclient', s.owner.id) for s in subs}
    return client, subs, ctx_client, ctx_subs


@router.post('/api/scope-preview/clients/{client_id}', responses=_ERRORS, tags=['scopes'])
async def preview(client_id: uuid.UUID, data: PreviewIn, request: Request,
                  service: Annotated[DiscoveryService, Depends(get_service)]):
    """Resolve os escopos do cliente (versões ativas; opcionalmente com UM rascunho não salvo). Não grava nada."""
    def load():
        with request.app.state.session_factory() as session:
            return _load(session, client_id, data)

    client, subs, ctx_client, ctx_subs = await run_in_threadpool(load)
    return await resolver.resolve_client(service, ctx_client, client, subs, ctx_subs, data.domain, data.sample_limit)
