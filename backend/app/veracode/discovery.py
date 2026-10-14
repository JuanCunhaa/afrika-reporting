"""Descoberta Veracode por escopo (cliente ou subcliente) — orquestra conexão efetiva, credenciais, cache e coletas.

Escopo -> conexão efetiva: subcliente usa a própria conexão (sobrescrita) ou herda a do cliente (F01).
Toda coleta é SOMENTE LEITURA. Coletas incompletas são devolvidas marcadas (`complete=False`) e nunca cacheadas;
se nada foi coletado, o erro é propagado (a API responde com o código correspondente).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from app.errors import not_found
from app.orm import Client, Connection, Subclient
from app.veracode import adapters, credentials
from app.veracode.cache import DiscoveryCache
from app.veracode.errors import VeracodeError
from app.veracode.http import Collection, CollectionRun, VeracodeHttpPool
from app.veracode.settings import VeracodeSettings

logger = logging.getLogger('afrika.veracode')
ScopeKind = Literal['client', 'subclient']


@dataclass(frozen=True)
class ScopeContext:
    kind: ScopeKind
    id: uuid.UUID
    name: str
    client_id: uuid.UUID
    connection_id: uuid.UUID | None
    connection_name: str | None
    region: str | None
    credential_ref: str | None
    connection_source: Literal['subclient', 'client', 'none']

    def info(self) -> dict:
        return {'kind': self.kind, 'id': str(self.id), 'name': self.name, 'client_id': str(self.client_id),
                'connection_source': self.connection_source,
                'connection': None if self.connection_id is None else {
                    'id': str(self.connection_id), 'name': self.connection_name, 'region': self.region,
                    'credential_ref': self.credential_ref}}


def _ctx(kind: ScopeKind, scope_id: uuid.UUID, name: str, client_id: uuid.UUID, conn: Connection | None,
         source: str) -> ScopeContext:
    return ScopeContext(kind, scope_id, name, client_id, conn.id if conn else None, conn.name if conn else None,
                        conn.region if conn else None, conn.credential_ref if conn else None,
                        source if conn else 'none')


def resolve_scope(session: Session, kind: ScopeKind, scope_id: uuid.UUID) -> ScopeContext:
    if kind == 'client':
        client = session.get(Client, scope_id)
        if client is None:
            raise not_found('client')
        return _ctx('client', client.id, client.name, client.id, client.connection, 'client')
    sub = session.get(Subclient, scope_id)
    if sub is None:
        raise not_found('subclient')
    if sub.connection is not None:
        return _ctx('subclient', sub.id, sub.name, sub.client_id, sub.connection, 'subclient')
    return _ctx('subclient', sub.id, sub.name, sub.client_id, sub.client.connection, 'client')


@dataclass
class Result:
    """Coleta + metadados de cache para a resposta da API."""
    collection: Collection
    cached: bool
    cache_ttl_remaining: float | None

    def status(self) -> dict:
        return {**self.collection.status(), 'cached': self.cached,
                'cache_ttl_remaining': None if self.cache_ttl_remaining is None else round(self.cache_ttl_remaining)}


class DiscoveryService:
    def __init__(self, settings: VeracodeSettings, pool: VeracodeHttpPool, cache: DiscoveryCache, *,
                 environ=None, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep):
        self.settings = settings
        self.pool = pool
        self.cache = cache
        self._environ = environ
        self._sleep = sleep

    # ------------------------------------------------------------ infraestrutura

    def credential_status(self, ctx: ScopeContext) -> str:
        if ctx.connection_id is None:
            return 'not_configured'
        return credentials.credential_status(ctx.credential_ref, self._environ)

    def _credentials(self, ctx: ScopeContext) -> credentials.Credentials:
        if ctx.connection_id is None:
            raise VeracodeError('connection_not_configured')
        return credentials.resolve(ctx.credential_ref, self._environ)

    def _run(self, ctx: ScopeContext, creds: credentials.Credentials) -> CollectionRun:
        return CollectionRun(self.pool, creds, ctx.region, sleep=self._sleep)

    async def _cached(self, ctx: ScopeContext, resource: str, params: tuple,
                      fetch: Callable[[CollectionRun], Awaitable[Collection]]) -> Result:
        creds = self._credentials(ctx)
        key = (ctx.kind, str(ctx.id), str(ctx.connection_id), ctx.region, ctx.credential_ref, creds.fingerprint,
               resource, params)
        col, cached, ttl = await self.cache.get_or_collect(
            key, lambda: fetch(self._run(ctx, creds)), lambda c: c.complete)
        if not col.complete and col.pages_fetched == 0:
            raise col.error  # nada coletado: erro explícito, não lista vazia
        if not cached:
            logger.info('descoberta escopo=%s:%s conexão=%s recurso=%s status=%s', ctx.kind, ctx.id,
                        ctx.connection_id, resource, 'complete' if col.complete else 'incomplete')
        return Result(col, cached, ttl)

    def invalidate(self, ctx: ScopeContext) -> int:
        removed = self.cache.invalidate_scope(ctx.kind, str(ctx.id))
        logger.info('cache invalidado escopo=%s:%s entradas=%s', ctx.kind, ctx.id, removed)
        return removed

    # ------------------------------------------------------------ teste de conexão

    async def test_connection(self, ctx: ScopeContext) -> dict:
        """Uma requisição mínima (size=1) por domínio. Nunca cacheado. Identifica permissões por domínio."""
        checks = [{'check': 'credentials', 'status': 'ok', 'error': None}]
        try:
            creds = self._credentials(ctx)
        except VeracodeError as exc:
            checks[0].update(status='error', error=exc.as_dict())
            return {'status': 'error', 'checks': checks}
        run = self._run(ctx, creds)
        probes = [('applications', adapters.APPLICATIONS, {}), ('users', adapters.USERS, {}),
                  ('teams', adapters.TEAMS, {'all_for_org': 'true'}),
                  ('business_units', adapters.BUSINESS_UNITS, {})]

        async def probe(name: str, path: str, params: dict) -> dict:
            try:
                await run.get_json(path, {**params, 'page': 0, 'size': 1}, label=f'test:{name}')
            except VeracodeError as exc:
                return {'check': name, 'status': 'error', 'error': exc.as_dict()}
            return {'check': name, 'status': 'ok', 'error': None}

        checks += await asyncio.gather(*(probe(*p) for p in probes))
        ok = sum(c['status'] == 'ok' for c in checks[1:])
        status = 'ok' if ok == len(probes) else ('partial' if ok else 'error')
        logger.info('teste de conexão escopo=%s:%s conexão=%s status=%s', ctx.kind, ctx.id, ctx.connection_id,
                    status)
        return {'status': status, 'checks': checks, 'requests': run.requests, 'retries': run.retries}

    # ------------------------------------------------------------ coleções simples

    async def applications(self, ctx: ScopeContext) -> Result:
        return await self._cached(ctx, 'applications', (), adapters.fetch_applications)

    async def sandboxes(self, ctx: ScopeContext, application_guid: str) -> Result:
        return await self._cached(ctx, 'sandboxes', (application_guid,),
                                  lambda run: adapters.fetch_sandboxes(run, application_guid))

    async def business_units(self, ctx: ScopeContext) -> Result:
        return await self._cached(ctx, 'business_units', (), adapters.fetch_business_units)

    async def teams(self, ctx: ScopeContext) -> Result:
        return await self._cached(ctx, 'teams', (), adapters.fetch_teams)

    async def users(self, ctx: ScopeContext) -> Result:
        return await self._cached(ctx, 'users', (), adapters.fetch_users)

    async def team_memberships(self, ctx: ScopeContext, teams: Result) -> Result:
        team_ids = tuple(sorted(str(t['team_id']) for t in teams.collection.items))
        res = await self._cached(ctx, 'team_memberships', (team_ids,),
                                 lambda run: adapters.fetch_team_memberships(run, teams.collection.items))
        return res

    # ------------------------------------------------------------ relacionamentos

    async def application_relationships(self, ctx: ScopeContext) -> tuple[list[dict], dict, list[Result]]:
        """Aplicação -> BU (única por perfil) e Teams (0..N), vindos do perfil da aplicação.

        A correspondência com os Teams/BUs da Identity API é feita SOMENTE por identificador
        (guid do perfil == team_id/bu_id da Identity; ou id legado), nunca por nome.
        """
        apps = await self.applications(ctx)
        sources = [apps]
        teams, bus = await _gather_results(self.teams(ctx), self.business_units(ctx))
        # Falha na Identity API não invalida a relação (vem do perfil); só a conferência de IDs fica indisponível.
        identity_error = next((r.as_dict() for r in (teams, bus) if isinstance(r, VeracodeError)), None)
        teams_idx = None if isinstance(teams, VeracodeError) else _index(teams.collection.items, 'team_id')
        bus_idx = None if isinstance(bus, VeracodeError) else _index(bus.collection.items, 'bu_id')
        sources += [r for r in (teams, bus) if isinstance(r, Result)]

        rows = []
        for app in apps.collection.items:
            bu = app['business_unit']
            rows.append({
                'application': {'guid': app['guid'], 'name': app['name']},
                'business_unit': None if bu is None else {**bu, 'identity_match': _match(bus_idx, bu)},
                'teams': None if app['teams'] is None else [{**t, 'identity_match': _match(teams_idx, t)}
                                                            for t in app['teams']],
            })
        summary = {
            'applications': len(rows),
            'with_business_unit': sum(r['business_unit'] is not None for r in rows),
            'teams_unknown': sum(r['teams'] is None for r in rows),
            'without_teams': sum(r['teams'] == [] for r in rows),
            'multiple_teams': sum(len(r['teams'] or []) > 1 for r in rows),
            'unmatched_team_refs': None if teams_idx is None else sum(
                1 for r in rows for t in (r['teams'] or []) if t['identity_match'] is False),
            'identity_check_error': identity_error,
        }
        return rows, summary, sources

    async def user_relationships(self, ctx: ScopeContext) -> tuple[list[dict], dict, list[Result]]:
        """Usuário -> Teams (0..N) a partir do detalhe de cada Team. Join por user_id, nunca por nome."""
        users, teams = await _gather_results(self.users(ctx), self.teams(ctx))
        for r in (users, teams):
            if isinstance(r, VeracodeError):
                raise r
        members = await self.team_memberships(ctx, teams)
        by_user: dict = defaultdict(list)
        for m in members.collection.items:
            by_user[m['user_id']].append({'team_id': m['team_id'], 'team_name': m['team_name'],
                                          'relationship': m['relationship']})
        known = {u['user_id'] for u in users.collection.items}
        reliable = members.collection.complete and teams.collection.complete
        rows = []
        for u in users.collection.items:
            memberships = by_user.get(u['user_id'], [])
            rows.append({'user': u, 'teams': memberships if (memberships or reliable) else None})
        summary = {
            'users': len(rows),
            'teams': len(teams.collection.items),
            'memberships': len(members.collection.items),
            'multiple_teams': sum(len(r['teams'] or []) > 1 for r in rows),
            'without_team': sum(r['teams'] == [] for r in rows) if reliable else None,
            'members_not_in_user_list': len({m['user_id'] for m in members.collection.items} - known),
        }
        return rows, summary, [users, teams, members]

    async def filter_metadata(self, ctx: ScopeContext) -> tuple[dict, list[Result]]:
        """Metadados presentes nos perfis de aplicação, para os filtros da F03. Nada é inferido."""
        apps = await self.applications(ctx)
        items = apps.collection.items
        custom: dict[str, Counter] = defaultdict(Counter)
        tags: Counter = Counter()
        criticality: Counter = Counter()
        policies: Counter = Counter()
        for a in items:
            for c in a['custom_fields'] or []:
                if c['name']:
                    custom[c['name']][c['value'] or ''] += 1
            for tag in (a['tags'] or '').split(','):
                if tag.strip():
                    tags[tag.strip()] += 1
            criticality[a['business_criticality'] or 'UNKNOWN'] += 1
            for p in a['policies'] or []:
                if p['name']:
                    policies[p['name']] += 1
        cap = 50
        meta = {
            'applications': len(items),
            'custom_fields': [{'name': n, 'applications': sum(v.values()), 'distinct_values': len(v),
                               'values': [{'value': k, 'applications': c} for k, c in v.most_common(cap)],
                               'values_truncated': len(v) > cap} for n, v in sorted(custom.items())],
            'tags': [{'value': k, 'applications': c} for k, c in tags.most_common()],
            'business_criticality': [{'value': k, 'applications': c} for k, c in criticality.most_common()],
            'policies': [{'value': k, 'applications': c} for k, c in policies.most_common()],
            'domains': DOMAIN_FILTERS,
        }
        return meta, [apps]


async def _gather_results(*coros: Awaitable[Result]) -> list[Result | VeracodeError]:
    """Executa em paralelo; VeracodeError vira valor (as demais coletas não ficam órfãs). Outros erros propagam."""
    results = await asyncio.gather(*coros, return_exceptions=True)
    for r in results:
        if isinstance(r, BaseException) and not isinstance(r, VeracodeError):
            raise r
    return results


def _index(items: list[dict], key: str) -> dict:
    idx = {}
    for it in items:
        if it.get(key) is not None:
            idx[('id', str(it[key]))] = it
        if it.get('legacy_id') is not None:
            idx[('legacy', it['legacy_id'])] = it
    return idx


def _match(idx: dict | None, ref: dict) -> bool | None:
    if idx is None:
        return None
    if ref.get('guid') and ('id', ref['guid']) in idx:
        return True
    if ref.get('legacy_id') is not None and ('legacy', ref['legacy_id']) in idx:
        return True
    return False


# Filtros que cada domínio PODE suportar com base nos dados descobertos na F02 (regras: F03).
DOMAIN_FILTERS = {
    'applications': {'available': ['business_unit', 'teams', 'tags', 'custom_fields', 'business_criticality',
                                   'policies'],
                     'source': 'Applications API (perfil da aplicação)'},
    # `account_type` não vem na lista de usuários da API real (homologação F02.1): não anunciado.
    'users': {'available': ['teams', 'active'],
              'source': 'Identity API (usuários + detalhe de Teams)'},
    'scans': {'available': [], 'source': 'não coletado na F02 (sandboxes listados apenas como metadado)'},
    'sca': {'available': [], 'source': 'não coletado na F02'},
}
