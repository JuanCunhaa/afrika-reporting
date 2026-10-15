"""F04/F04.1 — homologação REAL opt-in do motor de indicadores (mesmo portão de test_veracode_live).

Somente GET. Amostra PEQUENA: até 3 aplicações com scan concluído. Exercita o pipeline completo da coleta
(sandboxes, Summary Report, SCA Agent, Findings com pré-checagem SCA, passada adiada para HTTP 500 e circuit
breaker) e o cálculo. Imprime apenas contagens, estados e códigos — nunca nomes, IDs, CWEs, CVEs ou caminhos.
Nada é gravado. Rodar SEPARADO da suíte unitária:

    python -m pytest backend/tests_live/test_metrics_live.py -q -s -rs --run-veracode-live
"""
import asyncio
import uuid
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone

from app.metrics import collector, engine
from app.metrics.competence import parse
from app.metrics.population import Population, PopulationStatus
from app.veracode import adapters, credentials
from app.veracode.cache import DiscoveryCache
from app.veracode.discovery import DiscoveryService, ScopeContext
from app.veracode.http import CollectionRun, VeracodeHttpPool

from test_veracode_live import _settings

SAMPLE_APPS = 3
BUDGET = 60


def test_live_metric_pipeline_with_alternative_sources(veracode_live_gate):
    gate = veracode_live_gate
    creds = credentials.resolve(gate.credential_ref)
    settings = replace(_settings(), metrics_max_requests=BUDGET, metrics_timeout=300.0, cache_ttl=0,
                       circuit_breaker_threshold=4)

    async def main():
        pool = VeracodeHttpPool(settings)
        try:
            run = CollectionRun(pool, creds, gate.region)
            apps = await adapters.fetch_applications(run)
            assert apps.complete, apps.error
            scanned = [a for a in apps.items if a['last_completed_scan_date']][:SAMPLE_APPS]
            service = DiscoveryService(settings, pool, DiscoveryCache(0, 1))
            ctx = ScopeContext('client', uuid.uuid4(), 'amostra', uuid.uuid4(), uuid.uuid4(), 'live', gate.region,
                               gate.credential_ref, 'client')
            outcome = await collector.collect(service, ctx, scanned)
            return apps, scanned, outcome
        finally:
            await pool.aclose()

    apps, scanned, outcome = asyncio.run(main())
    s = outcome.summary()
    print(f'\naplicações no tenant={len(apps.items)} amostra={len(scanned)}')
    print(f"coleta: requisições={s['requests']} retries={s['retries']} contextos={s['by_state']} "
          f"passada_adiada={s['retry_pass']} circuitos={s['circuits_opened']} limite={s['limit_reached']}")
    print(f"summary_reports_falhos={s['summary_reports_failed']} sca_agent_falhos={s['sca_project_lookups_failed']} "
          f"listas_sandbox_falhas={s['sandbox_listings_failed']}")
    print('scans[] no perfil:', dict(Counter(f"{x['scan_type']}:{x['status']}" for a in scanned
                                             for x in a['scans'] or [])))
    sca_flags = Counter(collector.no_sca_components(f) for f in outcome.summaries.values())
    print(f'Summary Report sem componentes SCA (pré-checagem): {dict(sca_flags)}')
    print('estado por (tipo, contexto):', dict(Counter((c.scan_type, c.context, c.state.value, c.upstream_status,
                                                         c.retried) for c in outcome.contexts)))
    pop = Population(PopulationStatus.OK, applications=scanned, total_available=len(apps.items))
    results = engine.compute_all(engine.Context(parse('2026-09'), pop, outcome, {},
                                                datetime.now(timezone.utc).isoformat(), 'client'))
    recon = next(m for m in results if m.metric_id == 'sast.policy.reconciliation')
    print('reconciliação Findings × Summary:', {k: v for k, v in (recon.value or recon.partial or {}).items()
                                               if k != 'items'})
    print('status por indicador (amostra): ' + ', '.join(
        f'{m.metric_id}={m.status.value}' + (f'[{",".join(r.code for r in m.reasons)}]' if m.reasons else '')
        for m in results))
    assert outcome.requests <= BUDGET
    assert all(c.state.value in {x.value for x in collector.CollectState} for c in outcome.contexts)
