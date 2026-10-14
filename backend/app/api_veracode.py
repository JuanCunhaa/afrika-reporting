"""Endpoints de descoberta Veracode por escopo (F02). SOMENTE LEITURA na Veracode. API local, sem autenticação.

Escopo: /api/veracode/clients/{id} ou /api/veracode/subclients/{id} (conexão própria ou herdada do cliente).
Listas: coletadas por completo no backend (cache TTL), filtradas por `q` e paginadas (`limit`/`offset`) para o
navegador. Todo resultado traz `complete` e o estado de cada coleta usada (`collections`).
Credenciais: nunca aparecem em respostas — nem valores, nem nomes das variáveis derivadas.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.veracode.discovery import DiscoveryService, Result, ScopeContext, resolve_scope
from app.veracode.errors import VeracodeError

router = APIRouter(prefix='/api/veracode', tags=['veracode'])

ScopePath = Literal['clients', 'subclients']
_KIND = {'clients': 'client', 'subclients': 'subclient'}
MAX_LIMIT = 200
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
Offset = Annotated[int, Query(ge=0)]
Search = Annotated[str | None, Query(max_length=120)]
_ERRORS = {404: {'description': 'Escopo não encontrado'},
           409: {'description': 'Conexão/credencial não configurada ou inválida no ambiente'},
           502: {'description': 'Erro da Veracode (401/403/404/429/5xx/resposta inválida)'},
           504: {'description': 'Tempo esgotado'}}


def get_service(request: Request) -> DiscoveryService:
    return request.app.state.veracode


Service = Annotated[DiscoveryService, Depends(get_service)]


def _resolve_sync(request: Request, kind: str, scope_id: uuid.UUID) -> ScopeContext:
    with request.app.state.session_factory() as session:
        return resolve_scope(session, kind, scope_id)


async def scope_dep(request: Request, scope: ScopePath, scope_id: uuid.UUID) -> ScopeContext:
    return await run_in_threadpool(_resolve_sync, request, _KIND[scope], scope_id)


Scope = Annotated[ScopeContext, Depends(scope_dep)]


def install(app: FastAPI) -> None:
    @app.exception_handler(VeracodeError)
    async def _veracode_error(_req: Request, exc: VeracodeError):
        return JSONResponse({'error': {'code': exc.code, 'message': exc.message, 'details': [],
                                       'upstream_status': exc.upstream_status}}, status_code=exc.http_status)

    app.include_router(router)


def _matches(q: str | None, *values) -> bool:
    if not q:
        return True
    needle = q.strip().casefold()
    return any(needle in str(v).casefold() for v in values if v is not None)


def _sort_key(name: str | None, ident) -> tuple:
    return ((name or '').casefold(), str(ident))


def _page(ctx: ScopeContext, rows: list, limit: int, offset: int, sources: list[Result], **extra) -> dict:
    return {
        'scope': ctx.info(),
        'items': rows[offset:offset + limit],
        'total': len(rows),
        'limit': limit,
        'offset': offset,
        'complete': all(s.collection.complete for s in sources),
        'collections': [s.status() for s in sources],
        **extra,
    }


# ---------------------------------------------------------------- escopo e conexão

@router.get('/{scope}/{scope_id}', responses=_ERRORS)
def scope_info(ctx: Scope, service: Service):
    """Conexão efetiva do escopo (sem segredos) e situação local da credencial (sem chamar a Veracode)."""
    s = service.settings
    return {'scope': ctx.info(), 'credential_status': service.credential_status(ctx), 'mode': s.mode,
            'cache_ttl_seconds': s.cache_ttl, 'page_size': s.page_size, 'max_concurrency': s.max_concurrency}


@router.post('/{scope}/{scope_id}/test', responses=_ERRORS)
async def test_connection(ctx: Scope, service: Service):
    """Teste sob demanda: 1 requisição mínima por domínio (aplicações, usuários, Teams, BUs)."""
    return {'scope': ctx.info(), **(await service.test_connection(ctx))}


@router.delete('/{scope}/{scope_id}/cache', responses=_ERRORS)
def invalidate_cache(ctx: Scope, service: Service):
    return {'scope': ctx.info(), 'removed_entries': service.invalidate(ctx)}


# ---------------------------------------------------------------- recursos

@router.get('/{scope}/{scope_id}/applications', responses=_ERRORS)
async def applications(ctx: Scope, service: Service, q: Search = None, limit: Limit = 50, offset: Offset = 0):
    res = await service.applications(ctx)
    rows = sorted((a for a in res.collection.items if _matches(q, a['name'], a['guid'])),
                  key=lambda a: _sort_key(a['name'], a['guid']))
    return _page(ctx, rows, limit, offset, [res])


@router.get('/{scope}/{scope_id}/applications/{application_guid}/sandboxes', responses=_ERRORS)
async def sandboxes(ctx: Scope, service: Service, application_guid: uuid.UUID, limit: Limit = 50,
                    offset: Offset = 0):
    res = await service.sandboxes(ctx, str(application_guid))
    rows = sorted(res.collection.items, key=lambda s: _sort_key(s['name'], s['guid']))
    return _page(ctx, rows, limit, offset, [res], application_guid=str(application_guid))


@router.get('/{scope}/{scope_id}/business-units', responses=_ERRORS)
async def business_units(ctx: Scope, service: Service, q: Search = None, limit: Limit = 50, offset: Offset = 0):
    res = await service.business_units(ctx)
    rows = sorted((b for b in res.collection.items if _matches(q, b['name'], b['bu_id'])),
                  key=lambda b: _sort_key(b['name'], b['bu_id']))
    return _page(ctx, rows, limit, offset, [res])


@router.get('/{scope}/{scope_id}/teams', responses=_ERRORS)
async def teams(ctx: Scope, service: Service, q: Search = None, limit: Limit = 50, offset: Offset = 0):
    res = await service.teams(ctx)
    rows = sorted((t for t in res.collection.items
                   if _matches(q, t['name'], t['team_id'], (t['business_unit'] or {}).get('name'))),
                  key=lambda t: _sort_key(t['name'], t['team_id']))
    return _page(ctx, rows, limit, offset, [res])


@router.get('/{scope}/{scope_id}/users', responses=_ERRORS)
async def users(ctx: Scope, service: Service, q: Search = None, limit: Limit = 50, offset: Offset = 0):
    res = await service.users(ctx)
    rows = sorted((u for u in res.collection.items
                   if _matches(q, u['user_name'], u['first_name'], u['last_name'], u['user_id'])),
                  key=lambda u: _sort_key(u['user_name'], u['user_id']))
    return _page(ctx, rows, limit, offset, [res])


@router.get('/{scope}/{scope_id}/relationships/applications', responses=_ERRORS)
async def application_relationships(ctx: Scope, service: Service, q: Search = None, limit: Limit = 50,
                                    offset: Offset = 0):
    rows, summary, sources = await service.application_relationships(ctx)
    rows = sorted((r for r in rows if _matches(
        q, r['application']['name'], (r['business_unit'] or {}).get('name'),
        *[t['name'] for t in r['teams'] or []])), key=lambda r: _sort_key(r['application']['name'],
                                                                          r['application']['guid']))
    return _page(ctx, rows, limit, offset, sources, summary=summary)


@router.get('/{scope}/{scope_id}/relationships/users', responses=_ERRORS)
async def user_relationships(ctx: Scope, service: Service, q: Search = None, limit: Limit = 50,
                             offset: Offset = 0):
    rows, summary, sources = await service.user_relationships(ctx)
    rows = sorted((r for r in rows if _matches(q, r['user']['user_name'], r['user']['last_name'],
                                               *[t['team_name'] for t in r['teams'] or []])),
                  key=lambda r: _sort_key(r['user']['user_name'], r['user']['user_id']))
    return _page(ctx, rows, limit, offset, sources, summary=summary)


@router.get('/{scope}/{scope_id}/metadata', responses=_ERRORS)
async def filter_metadata(ctx: Scope, service: Service):
    meta, sources = await service.filter_metadata(ctx)
    return {'scope': ctx.info(), 'metadata': meta, 'complete': all(s.collection.complete for s in sources),
            'collections': [s.status() for s in sources]}
