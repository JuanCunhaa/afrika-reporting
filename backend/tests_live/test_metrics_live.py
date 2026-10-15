"""F04 — homologação REAL opt-in da Findings API e do motor de indicadores (mesmo portão de test_veracode_live).

Somente GET. Amostra PEQUENA: até 3 aplicações com scan concluído (Policy STATIC/SCA + até 2 sandboxes cada).
Imprime apenas contagens, nomes de chaves do schema e valores de enumerações — nunca nomes, IDs, CWEs, CVEs,
caminhos ou descrições do tenant. Nada é gravado. Rodar SEPARADO da suíte unitária:

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
MAX_SANDBOXES = 2
BUDGET = 80


def _keys(dicts):
    return sorted({k for d in dicts if isinstance(d, dict) for k in d})


def test_live_findings_format_and_metric_pipeline(veracode_live_gate):
    gate = veracode_live_gate
    creds = credentials.resolve(gate.credential_ref)
    settings = replace(_settings(), metrics_max_requests=BUDGET, metrics_timeout=300.0, cache_ttl=0, page_size=100)

    async def main():
        pool = VeracodeHttpPool(settings)
        try:
            run = CollectionRun(pool, creds, gate.region, max_requests=BUDGET)
            apps = await adapters.fetch_applications(run)
            assert apps.complete, apps.error
            scanned = [a for a in apps.items if a['last_completed_scan_date']][:SAMPLE_APPS]
            raw = {}
            for a in scanned:
                sbs = await adapters.fetch_sandboxes(run, a['guid'])
                contexts = [None] + [s['guid'] for s in sbs.items[:MAX_SANDBOXES]]
                for sb in contexts:
                    for st in adapters.FINDING_SCAN_TYPES:
                        params = {'scan_type': st, **({'context': sb} if sb else {})}
                        col = await run.paginate(adapters.FINDINGS.format(guid=a['guid']), 'findings',
                                                 label=f'live:findings:{st}', id_field='issue_id', params=params,
                                                 page_size=settings.findings_page_size)
                        raw[(a['guid'], sb, st)] = col
            # pipeline completo do motor sobre a mesma amostra (população sintética = amostra)
            service = DiscoveryService(settings, pool, DiscoveryCache(0, 1))
            ctx = ScopeContext('client', uuid.uuid4(), 'amostra', uuid.uuid4(), uuid.uuid4(), 'live', gate.region,
                               gate.credential_ref, 'client')
            outcome = await collector.collect(service, ctx, scanned)
            return apps, scanned, raw, outcome, run.requests
        finally:
            await pool.aclose()

    apps, scanned, raw, outcome, requests = asyncio.run(main())
    print(f'\naplicações no tenant={len(apps.items)} amostra={len(scanned)} requisições_diretas={requests} '
          f'requisições_motor={outcome.requests} retries_motor={outcome.retries}')
    by_kind = Counter()
    for (app, sb, st), col in raw.items():
        by_kind[(st, 'SANDBOX' if sb else 'POLICY', 'complete' if col.complete else f'incomplete:{col.error.code}')] += 1
    print(f'contextos: {dict(sorted(by_kind.items()))}')
    items = [i for col in raw.values() for i in col.items]
    print(f'findings brutos={len(items)} chaves={_keys(items)}')
    print(f'finding_status chaves={_keys(i.get("finding_status") for i in items)}')
    for st in adapters.FINDING_SCAN_TYPES:
        sub = [i for i in items if i.get('scan_type') == st]
        details = [i.get('finding_details') for i in sub]
        print(f'{st}: n={len(sub)} finding_details chaves={_keys(details)}')
        norm = [adapters.normalize_finding(i) for i in sub]
        for field in ('status', 'resolution', 'resolution_status', 'context_type', 'severity'):
            print(f'  {field}: {dict(Counter(n[field] for n in norm))}')
        print(f'  sem first_found_date={sum(n["first_found_date"] is None for n in norm)} '
              f'first_found_date_com_fuso={sum(1 for n in norm if (n["first_found_date"] or "").endswith(("Z", "+00:00")))}')
        if st == 'SCA':
            print(f'  metadata tipos={dict(Counter(type((d or {}).get("metadata")).__name__ for d in details))} '
                  f'sca_dep_mode={dict(Counter(n.get("sca_dep_mode") for n in norm))} '
                  f'sca_scan_mode={dict(Counter(n.get("sca_scan_mode") for n in norm))} '
                  f'sem_component_id={sum(not n.get("component_id") for n in norm)} '
                  f'sem_vulnerability_id={sum(not n.get("vulnerability_id") for n in norm)}')
    # Evidência (não prova) de identidade entre contextos: mesmo issue_id em Policy e sandbox da mesma aplicação
    same, diff = 0, 0
    for (app, sb, st), col in raw.items():
        if sb is None or st != 'STATIC':
            continue
        policy = {i['issue_id']: adapters.normalize_finding(i) for i in raw[(app, None, 'STATIC')].items}
        for i in col.items:
            p = policy.get(i['issue_id'])
            if p is not None:
                n = adapters.normalize_finding(i)
                same += (p['cwe_id'], p['severity']) == (n['cwe_id'], n['severity'])
                diff += (p['cwe_id'], p['severity']) != (n['cwe_id'], n['severity'])
    print(f'issue_id repetido Policy×Sandbox: mesmo CWE+severidade={same} diferente={diff}')

    comp = parse('2026-09')
    pop = Population(PopulationStatus.OK, applications=scanned, total_available=len(apps.items))
    results = engine.compute_all(engine.Context(comp, pop, outcome, {}, datetime.now(timezone.utc).isoformat(),
                                                'client'))
    print('status por indicador (amostra): ' + ', '.join(f'{m.metric_id}={m.status.value}'
                                                         + (f'[{",".join(r.code for r in m.reasons)}]'
                                                            if m.reasons else '') for m in results))
    assert outcome.requests <= BUDGET
    assert all(col.complete or col.error is not None for col in raw.values())
