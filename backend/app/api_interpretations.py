"""Endpoints da interpretação de indicadores (F08). API local, sem autenticação (só loopback); operador DECLARADO.

Nenhum endpoint daqui escreve em snapshots/aprovações, chama a Veracode ou é usado pela exportação. Por padrão nada sai
do servidor (provedor determinístico local); provedor externo exige configuração no ambiente + consentimento por pedido.

- `GET  /api/interpretation/config`                                  provedores, tipos, níveis e limites (sem segredo)
- `GET  /api/presentations/{pid}/interpretations`                    versões + estado + desatualização + slides desabilitados
- `POST /api/presentations/{pid}/interpretations/context`            contexto e o que SERIA transmitido (nada é gravado)
- `POST /api/presentations/{pid}/interpretations`                    gera (revisão persistida da apresentação)
- `GET  /api/presentations/{pid}/interpretations/{iid}`              detalhe: texto, fatos, validação, histórico
- `POST .../{iid}/review|approve|reject`                             fluxo GENERATED → IN_REVIEW → APPROVED | REJECTED
- `POST .../{iid}/edit` | `POST .../{iid}/regenerate`                nova versão (edição humana / regeneração)
- `POST .../{iid}/apply`                                             texto aprovado → campo do slide (nova revisão)
- `GET  .../{iid}/compare/{other}`                                   diferença entre versões
- `PUT  /api/presentations/{pid}/interpretation-settings/{slide_id}` desabilita/reabilita a interpretação no slide
"""
from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.api import SessionDep
from app.interpretation import providers, service
from app.interpretation.contracts import (
    KIND_NAMES, KINDS_BY_SLIDE, PROMPT_VERSION, EditorialText, Kind, Level, Status,
)
from app.interpretation.settings import InterpretationSettings
from app.interpretation.validate import VALIDATOR_VERSION
from app.presentations import service as presentations
from app.presentations.document import SlotId

router = APIRouter(tags=['interpretations'])
_ERRORS = {404: {'description': 'Não encontrado'}, 409: {'description': 'Conflito / estado inválido'},
           422: {'description': 'Validação'}, 502: {'description': 'Falha do provedor'}}

_NO_CONTROL = r'^[^\x00-\x1f\x7f]+$'
Declared = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120, pattern=_NO_CONTROL)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
ProviderName = Annotated[str, StringConstraints(max_length=60, pattern=r'^[a-z0-9][a-z0-9-]*$')]
Target = Literal['body', 'items', 'caption', 'notes']


class _Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ContextIn(_Strict):
    slide_id: SlotId
    kind: Kind | None = None
    level: Level = Level.EXECUTIVE
    notes: list[EditorialText] = Field(default_factory=list, max_length=service.MAX_NOTES)
    provider: ProviderName | None = None
    target_field: Target | None = None


class GenerateIn(ContextIn):
    operator: Declared
    external_consent: bool = False  # só vale para provedor externo; sem ele, nada é enviado


class TransitionIn(_Strict):
    operator: Declared
    reason: Reason | None = None


class EditIn(_Strict):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    operator: Declared
    justification: Reason | None = None


class RegenerateIn(_Strict):
    operator: Declared
    level: Level | None = None
    notes: list[EditorialText] | None = Field(default=None, max_length=service.MAX_NOTES)
    provider: ProviderName | None = None
    external_consent: bool = False


class ApplyIn(_Strict):
    operator: Declared
    expected_revision: int = Field(ge=1)
    overwrite_confirmed: bool = False


class SettingIn(_Strict):
    disabled: bool
    operator: Declared
    reason: Reason | None = None


def _settings(request: Request) -> InterpretationSettings:
    return request.app.state.interpretation


@router.get('/api/interpretation/config')
def config(request: Request):
    return {'settings': _settings(request).public(), 'providers': providers.available(),
            'prompt_version': PROMPT_VERSION, 'validator_version': VALIDATOR_VERSION,
            'kinds': [{'kind': k.value, 'name': KIND_NAMES[k]} for k in Kind],
            'levels': [lv.value for lv in Level], 'statuses': [s.value for s in Status],
            'kinds_by_slide_type': {t.value: [k.value for k in ks] for t, ks in KINDS_BY_SLIDE.items()},
            'policy': 'Padrão: provedor local determinístico, nada é enviado para fora. Texto só entra no slide após '
                      'aprovação humana explícita; a exportação nunca chama provedores.'}


@router.get('/api/presentations/{pid}/interpretations', responses=_ERRORS)
def list_interpretations(pid: uuid.UUID, session: SessionDep):
    return service.list_for(session, presentations.get(session, pid))


@router.post('/api/presentations/{pid}/interpretations/context', responses=_ERRORS)
def interpretation_context(pid: uuid.UUID, data: ContextIn, request: Request, session: SessionDep):
    p = presentations.get(session, pid)
    return service.preview(session, _settings(request), p, slide_id=data.slide_id, kind=data.kind, level=data.level,
                           notes=data.notes, provider=data.provider, target_field=data.target_field)


@router.post('/api/presentations/{pid}/interpretations', status_code=201, responses=_ERRORS)
def generate(pid: uuid.UUID, data: GenerateIn, request: Request, session: SessionDep):
    p = presentations.get(session, pid)
    iv = service.generate(session, _settings(request), p, slide_id=data.slide_id, kind=data.kind, level=data.level,
                          notes=data.notes, operator=data.operator, provider=data.provider,
                          consent=data.external_consent, target_field=data.target_field)
    return service.out(session, p, iv, detail=True)


@router.get('/api/presentations/{pid}/interpretations/{iid}', responses=_ERRORS)
def get_interpretation(pid: uuid.UUID, iid: uuid.UUID, session: SessionDep):
    p = presentations.get(session, pid)
    return service.out(session, p, service.get(session, p, iid), detail=True)


def _transition(pid, iid, to: Status, data: TransitionIn, session):
    p = presentations.get(session, pid)
    iv = service.transition(session, p, service.get(session, p, iid), to, data.operator, data.reason)
    return service.out(session, p, iv, detail=True)


@router.post('/api/presentations/{pid}/interpretations/{iid}/review', responses=_ERRORS)
def review(pid: uuid.UUID, iid: uuid.UUID, data: TransitionIn, session: SessionDep):
    return _transition(pid, iid, Status.IN_REVIEW, data, session)


@router.post('/api/presentations/{pid}/interpretations/{iid}/approve', responses=_ERRORS)
def approve(pid: uuid.UUID, iid: uuid.UUID, data: TransitionIn, session: SessionDep):
    return _transition(pid, iid, Status.APPROVED, data, session)


@router.post('/api/presentations/{pid}/interpretations/{iid}/reject', responses=_ERRORS)
def reject(pid: uuid.UUID, iid: uuid.UUID, data: TransitionIn, session: SessionDep):
    return _transition(pid, iid, Status.REJECTED, data, session)


@router.post('/api/presentations/{pid}/interpretations/{iid}/edit', status_code=201, responses=_ERRORS)
def edit(pid: uuid.UUID, iid: uuid.UUID, data: EditIn, session: SessionDep):
    p = presentations.get(session, pid)
    iv = service.edit(session, p, service.get(session, p, iid), text=data.text, operator=data.operator,
                      justification=data.justification)
    return service.out(session, p, iv, detail=True)


@router.post('/api/presentations/{pid}/interpretations/{iid}/regenerate', status_code=201, responses=_ERRORS)
def regenerate(pid: uuid.UUID, iid: uuid.UUID, data: RegenerateIn, request: Request, session: SessionDep):
    p = presentations.get(session, pid)
    iv = service.regenerate(session, _settings(request), p, service.get(session, p, iid), operator=data.operator,
                            level=data.level, notes=data.notes, provider=data.provider,
                            consent=data.external_consent)
    return service.out(session, p, iv, detail=True)


@router.post('/api/presentations/{pid}/interpretations/{iid}/apply', responses=_ERRORS)
def apply(pid: uuid.UUID, iid: uuid.UUID, data: ApplyIn, session: SessionDep):
    p = presentations.get(session, pid)
    iv = service.get(session, p, iid)
    number = service.apply(session, p, iv, operator=data.operator, expected=data.expected_revision,
                           overwrite_confirmed=data.overwrite_confirmed)
    return {'presentation_revision': number, 'interpretation': service.out(session, p, iv, detail=True),
            'presentation': presentations.presentation_out(session, p)}


@router.get('/api/presentations/{pid}/interpretations/{iid}/compare/{other}', responses=_ERRORS)
def compare(pid: uuid.UUID, iid: uuid.UUID, other: uuid.UUID, session: SessionDep):
    p = presentations.get(session, pid)
    return service.compare(service.get(session, p, iid), service.get(session, p, other))


@router.put('/api/presentations/{pid}/interpretation-settings/{slide_id}', responses=_ERRORS)
def set_setting(pid: uuid.UUID, slide_id: SlotId, data: SettingIn, session: SessionDep):
    p = presentations.get(session, pid)
    return {'disabled_slides': service.set_disabled(session, p, slide_id, data.disabled, data.operator,
                                                    data.reason)}
