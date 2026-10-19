"""F10 — diagnóstico REAL opt-in da completude SCA (mesmo portão de test_veracode_live). SOMENTE GET.

Pergunta: por que os contextos SCA com componentes ficam `incomplete` com `upstream_status` ausente (F09)?
Mede, na amostra da F04.1/F09 (até 3 aplicações com scan concluído), a FORMA da primeira página da Findings SCA
(Policy e sandboxes): metadados de paginação, presença/tipo de `issue_id`, repetições, nomes de campos (esquema, sem
valores) e o código de erro devolvido pelo adaptador. Imprime/grava só contagens, códigos e nomes de campos — nunca
nomes, GUIDs, componentes, CVEs ou caminhos. Saída em `private/f10/` (ignorado pelo Git).

    python -m pytest tests_live/test_f10_sca_diagnostics.py -q -s -rs --run-veracode-live   (a partir de backend/)
"""
import asyncio
import json
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

from app.veracode import adapters, credentials
from app.veracode.errors import VeracodeError
from app.veracode.http import CollectionRun, VeracodeHttpPool

from test_veracode_live import _settings

SAMPLE_APPS = 3
MAX_SANDBOXES = 2
OUT_DIR = Path(__file__).resolve().parents[2] / 'private' / 'f10'


def _shape(data: dict) -> dict:
    page = data.get('page') if isinstance(data.get('page'), dict) else None
    items = (data.get('_embedded') or {}).get('findings') or []
    ids = [i.get('issue_id') for i in items]
    ints = [x for x in ids if isinstance(x, int) and not isinstance(x, bool)]
    details = [i.get('finding_details') if isinstance(i.get('finding_details'), dict) else {} for i in items]
    composite = [(d.get('component_id'), (d.get('cve') or {}).get('name') if isinstance(d.get('cve'), dict) else None)
                 for d in details]
    return {
        'page_meta': None if page is None else {k: page.get(k) for k in ('size', 'number', 'total_pages',
                                                                         'total_elements')},
        'items': len(items),
        'issue_id': {'int': len(ints), 'missing': sum(x is None for x in ids),
                     'other_type': len(ids) - len(ints) - sum(x is None for x in ids),
                     'distinct_int': len(set(ints))},
        'composite_component_cve': {'distinct': len(set(composite)),
                                    'missing_part': sum(None in c for c in composite)},
        'item_keys': sorted({k for i in items for k in i}),
        'finding_details_keys': sorted({k for d in details for k in d}),
        'finding_status_keys': sorted({k for i in items if isinstance(i.get('finding_status'), dict)
                                       for k in i['finding_status']}),
    }


def test_live_sca_findings_shape(veracode_live_gate):
    gate = veracode_live_gate
    creds = credentials.resolve(gate.credential_ref)
    settings = replace(_settings(), cache_ttl=0, max_requests_per_collection=60, collection_timeout=600.0,
                       read_timeout=90.0, max_retries=1)

    async def main():
        pool = VeracodeHttpPool(settings)
        report: dict = {'settings': {'read_timeout': settings.read_timeout, 'findings_page_size':
                                     settings.findings_page_size, 'max_retries': settings.max_retries},
                        'contexts': []}
        try:
            run = CollectionRun(pool, creds, gate.region)
            apps = await adapters.fetch_applications(run)
            assert apps.complete, apps.error
            scanned = [a for a in apps.items if a['last_completed_scan_date']][:SAMPLE_APPS]
            for n, app in enumerate(scanned, 1):
                guid = app['guid']
                summary = await adapters.fetch_summary_report(run, guid)
                sca = (summary.items[0].get('sca') or {}) if summary.complete and summary.items else {}
                sandboxes = await adapters.fetch_sandboxes(run, guid)
                contexts = [('POLICY', None)] + [('SANDBOX', sb['guid']) for sb in sandboxes.items[:MAX_SANDBOXES]]
                for context, sb in contexts:
                    entry = {'app': f'app{n}', 'context': context,
                             'summary_third_party_components': sca.get('third_party_components')}
                    params = {'scan_type': 'SCA', 'page': 0, 'size': settings.findings_page_size,
                              **({'context': sb} if sb else {})}
                    t0 = time.monotonic()
                    try:
                        data = await run.get_json(adapters.FINDINGS.format(guid=quote(guid, safe='')), params,
                                                  label='diag:findings:sca',
                                                  no_retry_status=adapters.FINDINGS_NO_RETRY)
                        entry['raw_first_page'] = _shape(data)
                    except VeracodeError as exc:
                        entry['raw_first_page'] = {'error': exc.code, 'upstream_status': exc.upstream_status}
                    entry['raw_seconds'] = round(time.monotonic() - t0, 1)
                    t0 = time.monotonic()
                    col = await adapters.fetch_findings(run, guid, 'SCA', sb)
                    entry['adapter'] = {'complete': col.complete, 'pages_fetched': col.pages_fetched,
                                        'items': len(col.items), 'error': col.error.code if col.error else None,
                                        'upstream_status': col.error.upstream_status if col.error else None,
                                        'requests': col.requests, 'retries': col.retries,
                                        'seconds': round(time.monotonic() - t0, 1)}
                    report['contexts'].append(entry)
            report['requests'], report['retries'] = run.requests, run.retries
            return report
        finally:
            await pool.aclose()

    report = asyncio.run(main())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / 'sca_diagnostics.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\nrequisições={report['requests']} retries={report['retries']}")
    for c in report['contexts']:
        raw = c['raw_first_page']
        print(c['app'], c['context'], 'componentes(summary)=', c['summary_third_party_components'],
              '| 1ª página:', {k: raw.get(k) for k in ('error', 'upstream_status', 'page_meta', 'items', 'issue_id',
                                                      'composite_component_cve') if k in raw},
              f"({c['raw_seconds']}s)", '| adaptador:', c['adapter'])
    print('campos dos itens SCA:', sorted({k for c in report['contexts'] for k in c['raw_first_page'].get('item_keys',
                                                                                                         [])}))
    print('campos de finding_details SCA:', sorted({k for c in report['contexts']
                                                    for k in c['raw_first_page'].get('finding_details_keys', [])}))
    print('ocorrências de erro:', dict(Counter(c['adapter']['error'] for c in report['contexts'])))
