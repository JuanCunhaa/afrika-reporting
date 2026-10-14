"""Integração REAL com a Veracode — OPT-IN, fora da suíte padrão e do CI (pytest.ini só coleta backend/tests).

Executa SOMENTE com autorização do operador e credenciais de TESTE read-only com papéis mínimos.
Credenciais e flags vêm do `.env` da raiz (ou do ambiente do sistema, que tem precedência):

    AFRIKA_VC_TEST_API_ID / AFRIKA_VC_TEST_API_KEY   (referência AFRIKA_VC_TEST_CONNECTION=env:AFRIKA_VC_TEST)
    VERACODE_READ_ONLY=true
    VERACODE_LIVE_TESTS_ENABLED=true
    AFRIKA_VC_TEST_REGION=commercial                  (opcional: commercial | european | federal)

    python -m pytest backend/tests_live -q -rs --run-veracode-live

Escopo limitado: autenticação + descoberta (aplicações, BUs, Teams, usuários, membros de Team). Nenhum
finding é coletado. Somente GET em endpoints da allowlist. Orçamento padrão de 25 requisições por coleta
(AFRIKA_VERACODE_MAX_REQUESTS_PER_COLLECTION ajusta). Nada é gravado em disco nem cacheado. A saída mostra
apenas contagens e completude — nunca nomes, IDs, credenciais ou respostas. Não redirecione a saída ao Git.
"""
import asyncio
import dataclasses
import os
from collections import Counter

import pytest

from app.veracode import adapters, credentials, discovery
from app.veracode.http import CollectionRun, VeracodeHttpPool
from app.veracode.settings import VeracodeSettings

LIVE_DEFAULT_REQUEST_BUDGET = 25


def _settings() -> VeracodeSettings:
    settings = VeracodeSettings.from_env()
    if not (os.environ.get('AFRIKA_VERACODE_MAX_REQUESTS_PER_COLLECTION') or '').strip():
        settings = dataclasses.replace(settings, max_requests_per_collection=LIVE_DEFAULT_REQUEST_BUDGET)
    return settings


def _collect(gate, fetch):
    creds = credentials.resolve(gate.credential_ref)

    async def main():
        pool = VeracodeHttpPool(_settings())
        try:
            return await fetch(CollectionRun(pool, creds, gate.region))
        finally:
            await pool.aclose()
    return asyncio.run(main())


def _report(col):
    s = col.status()
    print(f"\n{s['resource']}: status={s['status']} itens={s['items_collected']} "
          f"total_informado={s['total_elements_reported']} páginas={s['pages_fetched']} "
          f"requisições={s['requests']} retries={s['retries']} motivo={(s['reason'] or {}).get('code')}")


def test_live_authentication_single_request(veracode_live_gate):
    async def probe(run):
        await run.get_json(adapters.APPLICATIONS, {'page': 0, 'size': 1}, label='live:auth')
        return run.requests
    assert _collect(veracode_live_gate, probe) >= 1


@pytest.mark.parametrize('name', ['applications', 'business_units', 'teams', 'users'])
def test_live_collection_is_complete_or_explicitly_incomplete(veracode_live_gate, name):
    col = _collect(veracode_live_gate, getattr(adapters, f'fetch_{name}'))
    _report(col)
    if not col.complete:
        pytest.fail(f'coleta incompleta: {col.error.code} (upstream={col.error.upstream_status})')
    if col.total_elements is not None:
        assert len(col.items) == col.total_elements  # reconciliação com o total informado pela própria API


def test_live_team_memberships(veracode_live_gate):
    async def both(run):
        teams = await adapters.fetch_teams(run)
        return teams, await adapters.fetch_team_memberships(run, teams.items) if teams.complete else None
    teams, members = _collect(veracode_live_gate, both)
    _report(teams)
    if members is None:
        pytest.fail('lista de Teams incompleta; relação usuário-Team não avaliada')
    _report(members)
    assert members.complete, members.error.code if members.error else ''


# ---------------------------------------------------------------- F02.1: formato real x contrato
# Só NOMES de chaves do schema da API e contagens são impressos — nunca valores, nomes ou IDs do tenant.

_LIST_ENDPOINTS = [
    ('applications', adapters.APPLICATIONS, {}),
    ('business_units', adapters.BUSINESS_UNITS, {}),
    ('teams', adapters.TEAMS, {'all_for_org': 'true'}),
    ('users', adapters.USERS, {}),
]


@pytest.mark.parametrize('name,path,params', _LIST_ENDPOINTS, ids=[e[0] for e in _LIST_ENDPOINTS])
def test_live_list_shape_matches_contract(veracode_live_gate, name, path, params):
    """`page` (snake/camel) e chave `_embedded` esperada pelo adaptador — itens NOT_VERIFIED da F02."""
    async def probe(run):
        return await run.get_json(path, {**params, 'page': 0, 'size': 1}, label=f'shape:{name}')
    data = _collect(veracode_live_gate, probe)
    page = data.get('page') if isinstance(data.get('page'), dict) else {}
    emb = data.get('_embedded') if isinstance(data.get('_embedded'), dict) else None
    print(f'\n{name}: chaves_raiz={sorted(data)} chaves_page={sorted(page)} '
          f'chaves_embedded={None if emb is None else sorted(emb)}')
    assert {'total_pages', 'total_elements'} <= set(page) or {'totalPages', 'totalElements'} <= set(page)
    if emb is not None:
        assert list(emb) == [name]
        if emb[name]:
            print(f'{name}: chaves_item={sorted(emb[name][0])}')


def test_live_team_detail_shape_and_all_for_org(veracode_live_gate):
    """Detalhe de Team (`users[]`, `user_count`, `relationship`) e efeito real de `all_for_org` (só contagens)."""
    async def probe(run):
        default = await run.get_json(adapters.TEAMS, {'page': 0, 'size': 1}, label='shape:teams_default')
        org = await run.get_json(adapters.TEAMS, {'all_for_org': 'true', 'page': 0, 'size': 1}, label='shape:teams')
        first = (org.get('_embedded') or {}).get('teams') or []
        detail = await run.get_json(adapters.TEAM_DETAIL.format(team_id=first[0]['team_id']),
                                    label='shape:team_detail') if first else None
        return default, org, detail
    default, org, detail = _collect(veracode_live_gate, probe)
    print(f"\nteams total sem all_for_org={default['page']['total_elements']} "
          f"com all_for_org={org['page']['total_elements']}")
    if detail is None:
        pytest.skip('tenant sem Teams')
    users = detail.get('users') if isinstance(detail.get('users'), list) else []
    print(f"team_detail: chaves={sorted(detail)} chaves_users_item={sorted(users[0]) if users else None}")
    assert isinstance(detail.get('users'), list)


def test_live_multi_page_pagination(veracode_live_gate):
    """Força páginas pequenas (aplicações) para exercitar a paginação real em >= 2 páginas, dentro do orçamento."""
    async def probe(run):
        return await run.get_json(adapters.APPLICATIONS, {'page': 0, 'size': 1}, label='live:count')
    total = _collect(veracode_live_gate, probe)['page']['total_elements']
    if total < 2:
        pytest.skip(f'tenant com {total} aplicação(ões): paginação multipágina não exercitável')
    pages = min(total, 4)
    size = -(-total // pages)  # teto: ~4 páginas
    gate = veracode_live_gate
    creds = credentials.resolve(gate.credential_ref)

    async def main():
        pool = VeracodeHttpPool(dataclasses.replace(_settings(), page_size=size))
        try:
            return await adapters.fetch_applications(CollectionRun(pool, creds, gate.region))
        finally:
            await pool.aclose()
    col = asyncio.run(main())
    _report(col)
    assert col.complete, col.error.code if col.error else ''
    assert col.pages_fetched >= 2 and col.total_pages == col.pages_fetched
    assert len(col.items) == col.total_elements == total


def _missing(items, keys):
    return {k: sum(1 for i in items if i.get(k) is None) for k in keys}


def test_live_application_relationships_by_id(veracode_live_gate):
    """Aplicação -> BU e Teams (perfil) conferidos com a Identity API SOMENTE por ID (guid ou id legado)."""
    async def all3(run):
        return (await adapters.fetch_applications(run), await adapters.fetch_business_units(run),
                await adapters.fetch_teams(run))
    apps, bus, teams = _collect(veracode_live_gate, all3)
    for c in (apps, bus, teams):
        _report(c)
        assert c.complete, c.error.code if c.error else ''
    bus_idx, teams_idx = discovery._index(bus.items, 'bu_id'), discovery._index(teams.items, 'team_id')
    a = apps.items
    bu_refs = [x['business_unit'] for x in a if x['business_unit'] is not None]
    team_refs = [t for x in a for t in (x['teams'] or [])]
    by_guid = lambda idx, r: bool(r.get('guid')) and ('id', r['guid']) in idx  # noqa: E731
    print(f"\napp->BU: apps={len(a)} com_bu={len(bu_refs)} bu_ausente={len(a) - len(bu_refs)} "
          f"match_guid={sum(by_guid(bus_idx, r) for r in bu_refs)} "
          f"match_total={sum(bool(discovery._match(bus_idx, r)) for r in bu_refs)}")
    print(f"app->Teams: teams_ausente={sum(x['teams'] is None for x in a)} "
          f"sem_team={sum(x['teams'] == [] for x in a)} varios_teams={sum(len(x['teams'] or []) > 1 for x in a)} "
          f"refs={len(team_refs)} match_guid={sum(by_guid(teams_idx, r) for r in team_refs)} "
          f"match_total={sum(bool(discovery._match(teams_idx, r)) for r in team_refs)}")
    print(f"campos ausentes (apps): {_missing(a, ['guid', 'name', 'business_unit', 'teams', 'tags', 'business_criticality', 'custom_fields', 'policies'])}")
    print(f"campos ausentes (BUs): {_missing(bus.items, ['bu_id', 'legacy_id', 'name', 'is_default', 'team_ids'])}")
    print(f"campos ausentes (Teams): {_missing(teams.items, ['team_id', 'legacy_id', 'name', 'business_unit', 'user_count'])}")
    unmatched = sum(not discovery._match(teams_idx, r) for r in team_refs) + \
        sum(not discovery._match(bus_idx, r) for r in bu_refs)
    assert unmatched == 0, f'{unmatched} referência(s) do perfil sem correspondência por ID na Identity API'


def test_live_user_team_relationships(veracode_live_gate):
    async def all3(run):
        users, teams = await adapters.fetch_users(run), await adapters.fetch_teams(run)
        members = await adapters.fetch_team_memberships(run, teams.items) if teams.complete else None
        return users, teams, members
    users, teams, members = _collect(veracode_live_gate, all3)
    for c in (users, teams) + ((members,) if members else ()):
        _report(c)
    assert users.complete and teams.complete and members is not None and members.complete
    known = {u['user_id'] for u in users.items}
    per_user = Counter(m['user_id'] for m in members.items)
    print(f"\nuser->Teams: usuarios={len(known)} vinculos={len(members.items)} "
          f"usuarios_com_team={sum(1 for u in known if per_user[u])} varios_teams={sum(1 for c in per_user.values() if c > 1)} "
          f"membros_fora_da_lista_users={len(set(per_user) - known)} "
          f"relationship_valores={sorted({m['relationship'] or 'None' for m in members.items})}")
    print(f"campos ausentes (users): {_missing(users.items, ['user_id', 'legacy_id', 'user_name', 'active', 'login_enabled', 'account_type'])}")
    print(f"account_type valores={sorted({u['account_type'] or 'None' for u in users.items})}")


def test_live_sandboxes_sample(veracode_live_gate):
    """Sandboxes de uma AMOSTRA de até 3 aplicações (sem extração massiva)."""
    async def sample(run):
        apps = await adapters.fetch_applications(run)
        cols = [await adapters.fetch_sandboxes(run, a['guid']) for a in apps.items[:3]] if apps.complete else []
        return apps, cols
    apps, cols = _collect(veracode_live_gate, sample)
    assert apps.complete, apps.error.code if apps.error else ''
    if not cols:
        pytest.skip('tenant sem aplicações: sandboxes não exercitáveis')
    for c in cols:
        _report(c)
        assert c.complete, c.error.code if c.error else ''
    sbx = [s for c in cols for s in c.items]
    owner_ok = sum(s['application_guid'] == a['guid'] for c, a in zip(cols, apps.items) for s in c.items)
    print(f"\nsandboxes: apps_amostra={len(cols)} sandboxes={len(sbx)} application_guid_confere={owner_ok} "
          f"campos ausentes={_missing(sbx, ['guid', 'legacy_id', 'name', 'application_guid', 'created', 'modified'])}")


def test_live_filter_metadata_counts(veracode_live_gate):
    """Metadados de filtro presentes nos perfis (somente contagens; nomes/valores não são impressos)."""
    apps = _collect(veracode_live_gate, adapters.fetch_applications)
    assert apps.complete, apps.error.code if apps.error else ''
    a = apps.items
    cf_names = {c['name'] for x in a for c in (x['custom_fields'] or []) if c['name']}
    tags = {t.strip() for x in a for t in (x['tags'] or '').split(',') if t.strip()}
    crit = Counter(x['business_criticality'] or 'UNKNOWN' for x in a)
    pols = {p['name'] for x in a for p in (x['policies'] or []) if p['name']}
    print(f"\nmetadados: apps={len(a)} custom_fields_distintos={len(cf_names)} "
          f"apps_com_custom_fields={sum(bool(x['custom_fields']) for x in a)} tags_distintas={len(tags)} "
          f"apps_com_tags={sum(bool(x['tags']) for x in a)} criticidade={dict(crit)} politicas_distintas={len(pols)} "
          f"apps_com_politica={sum(bool(x['policies']) for x in a)}")
