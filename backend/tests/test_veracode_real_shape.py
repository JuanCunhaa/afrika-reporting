"""F02.1 — regressões das diferenças observadas entre a API Veracode REAL (tenant de teste, homologação
2026-10-14) e os contratos/mocks da F02. Somente dados SINTÉTICOS; nenhuma chamada real.

Observado no tenant real (só formato, nunca valores):
- detalhe de Team: `users[].relationship` é OBJETO `{name, display_name}` (`name` = ADMIN | MEMBER), embora a
  especificação Identity 1.5 declare `string`;
- lista e detalhe de Team: sem `user_count`;
- lista de usuários: sem `account_type`;
- `page` da Identity API em snake_case (`total_elements`/`total_pages`), igual à Applications API.
"""
import asyncio
import json

import httpx
import pytest

from app.veracode import adapters, discovery
from app.veracode.credentials import Credentials
from app.veracode.fixtures import FixtureVeracode, default_tenants, synthetic_credentials
from app.veracode.hmac_auth import VeracodeHmacAuth
from app.veracode.http import CollectionRun, VeracodeHttpPool
from app.veracode.settings import VeracodeSettings


@pytest.mark.parametrize('relationship,expected', [
    ({'name': 'ADMIN', 'display_name': 'Administrador sintético'}, 'ADMIN'),  # formato real
    ({'name': 'MEMBER', 'display_name': 'Membro sintético'}, 'MEMBER'),
    ('ADMIN', 'ADMIN'),  # formato da especificação 1.5 continua aceito
    ({'display_name': 'sem name'}, None),
    ({'name': 7}, None),
    (None, None),
    (['ADMIN'], None),
])
def test_membership_relationship_accepts_real_object_and_spec_string(relationship, expected):
    raw = {'user_id': 'u-1', 'user_name': 'sintetico.u1', 'relationship': relationship}
    assert adapters.normalize_membership(raw)['relationship'] == expected


def test_membership_relationship_absent_is_unknown_not_member():
    assert adapters.normalize_membership({'user_id': 'u-1'})['relationship'] is None


def test_fixture_mirrors_real_identity_shapes():
    """O tenant sintético reproduz o formato real: sem `user_count`/`account_type`, relationship objeto."""
    alpha = default_tenants()['alpha']
    assert all('user_count' not in t for t in alpha.teams)
    assert all('account_type' not in u for u in alpha.users)
    members = [m for ms in alpha.team_users.values() for m in ms]
    assert members and all(isinstance(m['relationship'], dict) and m['relationship']['name'] in ('ADMIN', 'MEMBER')
                           for m in members)


def test_fixture_identity_page_is_snake_case_like_real_api():
    handler = FixtureVeracode(default_tenants()).handle
    auth = VeracodeHmacAuth(Credentials(*synthetic_credentials('alpha')))
    req = httpx.Request('GET', 'https://api.veracode.com/api/authn/v2/users', params={'page': 0, 'size': 5})
    req = next(auth.auth_flow(req))
    body = json.loads(handler(req).content)
    assert {'total_elements', 'total_pages'} <= set(body['page'])
    assert 'totalElements' not in body['page']


def test_team_memberships_complete_without_user_count():
    """Sem `user_count` (formato real) a relação é coletada e marcada completa; nada é presumido."""
    async def scenario():
        fx = FixtureVeracode(default_tenants())
        pool = VeracodeHttpPool(VeracodeSettings(), transport=fx.transport())
        try:
            run = CollectionRun(pool, Credentials(*synthetic_credentials('alpha')), 'commercial')
            teams = await adapters.fetch_teams(run)
            return teams, await adapters.fetch_team_memberships(run, teams.items)
        finally:
            await pool.aclose()

    teams, members = asyncio.run(scenario())
    assert teams.complete and all(t['user_count'] is None for t in teams.items)
    assert members.complete and members.items
    assert {m['relationship'] for m in members.items} == {'ADMIN', 'MEMBER'}


def test_user_filter_metadata_does_not_advertise_fields_absent_in_real_api():
    # `account_type` não vem na lista de usuários real: não pode ser anunciado como filtro disponível.
    assert 'account_type' not in discovery.DOMAIN_FILTERS['users']['available']
    assert {'teams', 'active'} <= set(discovery.DOMAIN_FILTERS['users']['available'])
