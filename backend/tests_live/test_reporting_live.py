"""F05 — homologação REAL opt-in da Reporting API: UMA geração mínima (FINDINGS ou SCANS).

Além do portão comum (`--run-veracode-live` + `VERACODE_LIVE_TESTS_ENABLED=true` + credenciais), exige
`VERACODE_REPORTING_LIVE_ENABLED=true` — por ser a única operação de escrita (gera um recurso de relatório no
serviço de reporting; não altera aplicações, findings, políticas, usuários nem scans).

Escopo mínimo: UMA aplicação (a primeira com scan concluído, por `app_id` numérico), janela de 7 dias até hoje (UTC),
no máximo 3 páginas. Imprime só status, contagens e códigos — nunca nomes, IDs, CWEs, caminhos ou conteúdo de itens.
Nada é gravado. Rodar SEPARADO da suíte unitária:

    VERACODE_REPORTING_LIVE_ENABLED=true python -m pytest backend/tests_live/test_reporting_live.py -q -s -rs \
        --run-veracode-live
"""
import asyncio
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.veracode import adapters, credentials
from app.veracode.errors import VeracodeError
from app.veracode.http import CollectionRun, VeracodeHttpPool
from app.veracode.reporting import ReportingClient
from app.veracode.reporting_policy import build

from test_veracode_live import _settings

REPORTING_LIVE_VAR = 'VERACODE_REPORTING_LIVE_ENABLED'


def test_live_minimal_report_generation(veracode_live_gate):
    if (os.environ.get(REPORTING_LIVE_VAR) or '').strip().lower() != 'true':
        pytest.skip(f'geração real de relatório não autorizada ({REPORTING_LIVE_VAR} não é true)')
    gate = veracode_live_gate
    creds = credentials.resolve(gate.credential_ref)
    report_type = (os.environ.get('AFRIKA_VC_TEST_REPORT_TYPE') or 'FINDINGS').strip().upper()
    settings = replace(_settings(), reporting_enabled=True, reporting_max_pages=3, reporting_max_polls=40,
                       reporting_poll_interval=10.0, reporting_poll_max_interval=30.0, reporting_timeout=600.0,
                       reporting_max_window_days=7, cache_ttl=0)
    today = datetime.now(timezone.utc).date()
    progress_log: list[dict] = []

    async def main():
        pool = VeracodeHttpPool(settings)
        try:
            apps = await adapters.fetch_applications(CollectionRun(pool, creds, gate.region))
            assert apps.complete, apps.error
            app = next((a for a in apps.items
                        if a['last_completed_scan_date'] and isinstance(a.get('legacy_id'), int)), None)
            assert app is not None, 'nenhuma aplicação com scan concluído no tenant de testes'
            request = build({'report_type': report_type, 'app_id': app['legacy_id'],
                             'last_updated_start_date': (today - timedelta(days=7)).isoformat(),
                             'last_updated_end_date': today.isoformat()}, max_days=7)
            client = ReportingClient(pool, creds, gate.region)
            try:
                result = await client.execute(request, lambda u: progress_log.append(
                    {k: v for k, v in u.items() if k in ('stage', 'polls', 'veracode_status', 'pages_fetched',
                                                          'total_pages', 'envelope')}))
                return result, client.run, None
            except VeracodeError as exc:
                return None, client.run, exc
        finally:
            await pool.aclose()

    result, run, error = asyncio.run(main())
    stages = [p for p in progress_log if p]
    print(f'\nReporting {report_type}: requisições={run.requests} retries={run.retries} etapas={stages[-3:]}')
    if error is not None:
        print(f'BLOQUEIO/ERRO: code={error.code} upstream_status={error.upstream_status}')
        if error.code in ('forbidden', 'auth_failed'):
            pytest.skip(f'BLOCKED_EXTERNAL: Reporting API indisponível para a credencial ({error.code})')
        raise AssertionError(f'falha na geração real: {error.code}')
    agg = result['aggregates']
    print(f"completo={result['complete']} truncado={result['truncated']} itens={result['items_processed']} "
          f"total_reportado={result['total_elements_reported']} páginas={result['pages_fetched']}/"
          f"{result['total_pages']}")
    print('agregados (exploratórios):', {k: v for k, v in agg.items() if k != 'distinct_applications'})
    assert run.requests <= settings.reporting_max_polls + settings.reporting_max_pages + 2 * (settings.max_retries + 1)
    assert result['aggregates_status'] in ('EXPLORATORY_NOT_HOMOLOGATED', 'INCOMPLETE')
