"""Integração REAL com a Veracode — OPT-IN, fora da suíte padrão e do CI (pytest.ini só coleta backend/tests).

Executa SOMENTE com autorização do operador e credenciais de leitura com papéis mínimos:

    $env:AFRIKA_VERACODE_LIVE = "1"
    $env:AFRIKA_VERACODE_LIVE_REF = "env:NOME"          # NOME_API_ID / NOME_API_KEY já no ambiente
    $env:AFRIKA_VERACODE_LIVE_REGION = "commercial"     # commercial | european | federal
    python -m pytest backend/tests_live -q -rs

Somente GET. Nada é gravado em disco nem cacheado. A saída mostra apenas contagens e estado de completude —
nunca nomes de aplicações/usuários, IDs, credenciais ou respostas. Não redirecione a saída para o Git.
"""
import asyncio
import os

import pytest

from app.veracode import adapters, credentials
from app.veracode.http import CollectionRun, VeracodeHttpPool
from app.veracode.settings import VeracodeSettings

pytestmark = pytest.mark.skipif(os.getenv('AFRIKA_VERACODE_LIVE') != '1',
                                reason='integração real desativada (defina AFRIKA_VERACODE_LIVE=1 com autorização)')


def _collect(fetch):
    ref = os.environ.get('AFRIKA_VERACODE_LIVE_REF', '')
    region = os.environ.get('AFRIKA_VERACODE_LIVE_REGION', 'commercial')
    creds = credentials.resolve(ref)

    async def main():
        pool = VeracodeHttpPool(VeracodeSettings.from_env())
        try:
            return await fetch(CollectionRun(pool, creds, region))
        finally:
            await pool.aclose()
    return asyncio.run(main())


def _report(col):
    s = col.status()
    print(f"\n{s['resource']}: status={s['status']} itens={s['items_collected']} "
          f"total_informado={s['total_elements_reported']} páginas={s['pages_fetched']} "
          f"requisições={s['requests']} retries={s['retries']} motivo={(s['reason'] or {}).get('code')}")


@pytest.mark.parametrize('name', ['applications', 'business_units', 'teams', 'users'])
def test_live_collection_is_complete_or_explicitly_incomplete(name):
    col = _collect(getattr(adapters, f'fetch_{name}'))
    _report(col)
    if not col.complete:
        pytest.fail(f'coleta incompleta: {col.error.code} (upstream={col.error.upstream_status})')
    if col.total_elements is not None:
        assert len(col.items) == col.total_elements  # reconciliação com o total informado pela própria API


def test_live_team_memberships():
    async def both(run):
        teams = await adapters.fetch_teams(run)
        return teams, await adapters.fetch_team_memberships(run, teams.items) if teams.complete else None
    teams, members = _collect(both)
    _report(teams)
    if members is None:
        pytest.fail('lista de Teams incompleta; relação usuário-Team não avaliada')
    _report(members)
    assert members.complete, members.error.code if members.error else ''
