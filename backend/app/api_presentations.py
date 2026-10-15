"""Endpoints do motor de apresentações (F06A). API local, sem autenticação (só loopback); operador DECLARADO.

Nenhum endpoint daqui escreve em snapshots, aprovações ou execuções da F05/F04 nem chama a Veracode.

- `GET  /api/presentation-catalog`                                tipos de slide, temas, indicadores compatíveis
- `GET  /api/presentation-templates`                              templates (versão vigente + versões)
- `POST /api/presentation-templates`                              cria template próprio (v1)
- `POST /api/presentation-templates/builtin`                      instala templates demonstrativos (idempotente)
- `GET  /api/presentation-templates/{key}/versions/{v}`           definição de uma versão
- `POST /api/presentation-templates/{key}/versions`               publica nova versão
- `GET|PUT /api/template-selection/{kind}/{owner_id}`              template escolhido pelo cliente/subcliente
- `GET  /api/presentations?owner_kind&owner_id` | `POST /api/presentations`
- `GET  /api/presentations/{pid}`                                 metadados + revisões
- `GET  /api/presentations/{pid}/revisions/{n}`                   documento + fontes fixadas
- `PUT  /api/presentations/{pid}/document`                        salva nova revisão (expected_revision)
- `POST /api/presentations/{pid}/rebind`                          atualiza fontes aprovadas (nova revisão)
- `GET  /api/presentations/{pid}/view[?revision=n]`               modelo de visualização (slides + IR)
- `POST /api/presentations/{pid}/preview`                         visualização de documento NÃO salvo (sem gravar)
- `GET  /api/presentations/{pid}/integrity`                       verificação de hashes e referências
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.api import SessionDep
from app.presentations import catalog, service, templates, view
from app.presentations.document import Document, TemplateKey, validate_document
from app.presentations.themes import public_themes
from app.scopes import store

router = APIRouter(tags=['presentations'])
_ERRORS = {404: {'description': 'Não encontrado'}, 409: {'description': 'Conflito / fonte não aprovada'},
           422: {'description': 'Validação'}}

_NO_CONTROL = r'^[^\x00-\x1f\x7f]+$'
Declared = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120, pattern=_NO_CONTROL)]
Summary = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Kind = Literal['client', 'subclient']


class _Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class TemplateIn(_Strict):
    key: TemplateKey
    definition: dict[str, Any]
    operator: Declared


class TemplateVersionIn(_Strict):
    definition: dict[str, Any]
    operator: Declared
    expected_version: int = Field(ge=1)


class OperatorIn(_Strict):
    operator: Declared


class SelectionIn(_Strict):
    template_key: TemplateKey
    template_version: int = Field(ge=1)
    operator: Declared


class PresentationIn(_Strict):
    competence_id: uuid.UUID
    revision: int | None = Field(default=None, ge=1)
    template_key: TemplateKey | None = None
    template_version: int | None = Field(default=None, ge=1)
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)] | None = None
    operator: Declared


class DocumentIn(_Strict):
    document: Document
    expected_revision: int = Field(ge=1)
    operator: Declared
    summary: Summary = ''


class PreviewIn(_Strict):
    document: Document


class RebindIn(_Strict):
    expected_revision: int = Field(ge=1)
    operator: Declared
    revision: int | None = Field(default=None, ge=1)


# ---------------------------------------------------------------- catálogo e templates

@router.get('/api/presentation-catalog')
def get_catalog():
    return {**catalog.public_catalog(), 'themes': public_themes()}


@router.get('/api/presentation-templates')
def list_templates(session: SessionDep):
    return {'items': templates.list_all(session)}


@router.post('/api/presentation-templates', status_code=201, responses=_ERRORS)
def create_template(data: TemplateIn, session: SessionDep):
    return templates.template_out(templates.create(session, data.key, data.definition, data.operator),
                                  with_definition=True)


@router.post('/api/presentation-templates/builtin', responses=_ERRORS)
def install_builtin(data: OperatorIn, session: SessionDep):
    return templates.install_builtin(session, data.operator)


@router.get('/api/presentation-templates/{key}/versions/{version}', responses=_ERRORS)
def get_template(key: TemplateKey, version: int, session: SessionDep):
    return templates.template_out(templates.get(session, key, version), with_definition=True)


@router.post('/api/presentation-templates/{key}/versions', status_code=201, responses=_ERRORS)
def create_template_version(key: TemplateKey, data: TemplateVersionIn, session: SessionDep):
    t = templates.create_version(session, key, data.definition, data.operator, data.expected_version)
    return templates.template_out(t, with_definition=True)


@router.get('/api/template-selection/{kind}/{owner_id}', responses=_ERRORS)
def get_selection(kind: Kind, owner_id: uuid.UUID, session: SessionDep):
    return templates.selection_of(session, store.get_owner(session, kind, owner_id))


@router.put('/api/template-selection/{kind}/{owner_id}', responses=_ERRORS)
def put_selection(kind: Kind, owner_id: uuid.UUID, data: SelectionIn, session: SessionDep):
    return templates.select_for_owner(session, kind, owner_id, data.template_key, data.template_version,
                                      data.operator)


# ---------------------------------------------------------------- apresentações

@router.get('/api/presentations')
def list_presentations(session: SessionDep, owner_kind: Kind, owner_id: uuid.UUID):
    return {'items': service.list_for_owner(session, owner_kind, owner_id)}


@router.post('/api/presentations', status_code=201, responses=_ERRORS)
def create_presentation(data: PresentationIn, session: SessionDep):
    p = service.create(session, data.competence_id, data.operator, revision=data.revision,
                       template_key=data.template_key, template_version=data.template_version, title=data.title)
    return service.presentation_out(session, p)


@router.get('/api/presentations/{pid}', responses=_ERRORS)
def get_presentation(pid: uuid.UUID, session: SessionDep):
    return service.presentation_out(session, service.get(session, pid))


@router.get('/api/presentations/{pid}/revisions/{number}', responses=_ERRORS)
def get_presentation_revision(pid: uuid.UUID, number: int, session: SessionDep):
    p = service.get(session, pid)
    return service.revision_out(p, service.get_revision(session, p, number))


@router.put('/api/presentations/{pid}/document', responses=_ERRORS)
def save_document(pid: uuid.UUID, data: DocumentIn, session: SessionDep):
    p = service.get(session, pid)
    service.save(session, p, data.document, data.operator, data.expected_revision, data.summary)
    return service.presentation_out(session, p)


@router.post('/api/presentations/{pid}/rebind', responses=_ERRORS)
def rebind(pid: uuid.UUID, data: RebindIn, session: SessionDep):
    p = service.get(session, pid)
    changes = service.rebind(session, p, data.operator, data.expected_revision, data.revision)
    return {'changes': changes, **service.presentation_out(session, p)}


@router.get('/api/presentations/{pid}/view', responses=_ERRORS)
def get_view(pid: uuid.UUID, session: SessionDep, revision: Annotated[int | None, Query(ge=1)] = None):
    p = service.get(session, pid)
    return view.build(session, p, service.get_revision(session, p, revision))


@router.post('/api/presentations/{pid}/preview', responses=_ERRORS)
def preview(pid: uuid.UUID, data: PreviewIn, session: SessionDep):
    p = service.get(session, pid)
    validate_document(data.document, templates.definition_of(service.template_of(session, p)))
    return view.build(session, p, service.get_revision(session, p), draft=data.document)


@router.get('/api/presentations/{pid}/integrity', responses=_ERRORS)
def integrity(pid: uuid.UUID, session: SessionDep):
    return service.verify(session, service.get(session, pid))
