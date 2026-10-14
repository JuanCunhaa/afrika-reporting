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

import pytest

from app.veracode import adapters, credentials
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
