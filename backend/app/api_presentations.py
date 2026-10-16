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
- `GET  /api/presentation-themes` | `POST`                        temas (embutidos + próprios) / cria tema próprio
- `GET  /api/presentation-themes/{key}/versions/{v}`              tema completo (tokens)
- `POST /api/presentation-themes/{key}/versions`                  publica nova versão de tema próprio
- `POST /api/theme-assets` | `GET /api/theme-assets/{sha256}`     ativos locais do tema (logo/fonte; fora do Git)
- `GET  /api/brand-assets/{tema}/{encaixe}`                       F06C: ativo autorizado da pasta local (fora do Git)
- `GET  /api/presentation-templates/{key}/versions/{v}/availability?competence_id`  F06C: slots × indicadores
- `GET  /api/presentations/{pid}/export-plan[?revision=n]`        F06C: contrato de exportação (sem gerar arquivo)
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.api import SessionDep
from app.errors import ApiError
from app.presentations import assets, brand_assets, catalog, export_plan, service, templates, themes, view
from app.presentations.document import Document, TemplateKey, validate_document
from app.presentations.themes import ThemeKey
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
    # F06C: slots do template a incluir (None = todos). Obrigatórios do template entram sempre.
    slots: list[Annotated[str, StringConstraints(pattern=r'^[a-z0-9][a-z0-9-]*$', max_length=60)]] | None =         Field(default=None, max_length=60)
    operator: Declared


class DocumentIn(_Strict):
    document: Document
    expected_revision: int = Field(ge=1)
    operator: Declared
    summary: Summary = ''


class PreviewIn(_Strict):
    document: Document


class ThemeIn(_Strict):
    key: ThemeKey
    definition: dict[str, Any]
    operator: Declared


class ThemeVersionIn(_Strict):
    definition: dict[str, Any]
    operator: Declared
    expected_version: int = Field(ge=1)


class RebindIn(_Strict):
    expected_revision: int = Field(ge=1)
    operator: Declared
    revision: int | None = Field(default=None, ge=1)


# ---------------------------------------------------------------- catálogo e templates

@router.get('/api/presentation-catalog')
def get_catalog(session: SessionDep):
    return {**catalog.public_catalog(), 'themes': themes.list_all(session)}


# ---------------------------------------------------------------- temas e ativos (F06B.1)

@router.get('/api/presentation-themes')
def list_themes(session: SessionDep):
    return {'items': themes.list_all(session)}


@router.get('/api/presentation-themes/{key}/versions/{version}', responses=_ERRORS)
def get_theme(key: ThemeKey, version: int, session: SessionDep):
    if not themes.exists(session, key, version):
        raise ApiError(404, 'theme_not_found', 'Tema (ou versão) não encontrado')
    defn, public = themes.load(session, key, version)
    return {**public, 'missing_assets': themes.missing_assets(defn)}


@router.post('/api/presentation-themes', status_code=201, responses=_ERRORS)
def create_theme(data: ThemeIn, session: SessionDep):
    return themes.create(session, data.key, data.definition, data.operator)


@router.post('/api/presentation-themes/{key}/versions', status_code=201, responses=_ERRORS)
def create_theme_version(key: ThemeKey, data: ThemeVersionIn, session: SessionDep):
    return themes.create_version(session, key, data.definition, data.operator, data.expected_version)


@router.post('/api/theme-assets', status_code=201, responses={**_ERRORS, 413: {'description': 'Arquivo grande demais'}})
async def upload_asset(request: Request):
    """Corpo = bytes do arquivo (PNG, JPEG, SVG, WOFF2, WOFF, TTF, OTF). Tipo detectado pela assinatura."""
    declared = request.headers.get('content-length')
    if declared and declared.isdigit() and int(declared) > assets.MAX_ASSET_BYTES:
        raise ApiError(413, 'asset_too_large', 'Arquivo maior que o limite')
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > assets.MAX_ASSET_BYTES:
            raise ApiError(413, 'asset_too_large', 'Arquivo maior que o limite')
    return assets.add(bytes(data))


@router.get('/api/theme-assets/{asset_id}', responses=_ERRORS)
def get_asset(asset_id: str):
    data, media_type = assets.read(asset_id)
    # Conteúdo endereçado por hash (imutável). SVG nunca executa script: CSP restritiva + sandbox + nosniff.
    return Response(content=data, media_type=media_type, headers={
        'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, max-age=31536000, immutable',
        'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; sandbox"})


@router.get('/api/brand-assets/{theme_id}/{slot}', responses=_ERRORS)
def get_brand_asset(theme_id: str, slot: str):
    """F06C: ativo AUTORIZADO da pasta local (fora do Git) para um encaixe do tema. Sem arquivo => 404 (fallback
    neutro no slide). Revalidado a cada leitura; SVG nunca executa script (CSP + sandbox + nosniff)."""
    data, media_type, digest = brand_assets.read(theme_id, slot)
    return Response(content=data, media_type=media_type, headers={
        'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, no-cache', 'ETag': f'"{digest}"',
        'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; sandbox"})


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


@router.get('/api/presentation-templates/{key}/versions/{version}/availability', responses=_ERRORS)
def template_availability(key: TemplateKey, version: int, session: SessionDep, competence_id: uuid.UUID,
                          revision: Annotated[int | None, Query(ge=1)] = None):
    """F06C: situação de cada slot do template na revisão aprovada da competência (para escolher os slides)."""
    return service.slot_availability(session, templates.get(session, key, version), competence_id, revision)


@router.get('/api/presentations/{pid}/export-plan', responses=_ERRORS)
def get_export_plan(pid: uuid.UUID, session: SessionDep, revision: Annotated[int | None, Query(ge=1)] = None):
    """F06C (preparação da F07): como cada elemento do slide SERIA exportado (texto, forma, tabela, gráfico nativo,
    imagem). Contrato apenas — nenhum arquivo PPTX/PDF é gerado."""
    p = service.get(session, pid)
    return export_plan.plan(view.build(session, p, service.get_revision(session, p, revision)))


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
                       template_key=data.template_key, template_version=data.template_version, title=data.title,
                       slots=data.slots)
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
