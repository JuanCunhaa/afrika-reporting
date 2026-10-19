"""F11 — validação REAL opt-in da correção SCA da F10 (mesmo portão de test_veracode_live). SOMENTE GET.

Perguntas: (1) a coleta SCA sem `issue_id` termina COMPLETA pelos metadados oficiais de paginação (`total_elements` =
itens recebidos, `total_pages` = páginas lidas) em Policy e sandboxes? (2) qual a semântica observável do campo
`count` dos findings SCA (pendência F10 nº 6) — todos 1, ou há agregação? (3) componentes do Summary Report ×
componentes distintos na Findings SCA (só contagens).

Grava só contagens/booleanos em `private/f11/` (ignorado pelo Git) e imprime apenas booleanos e códigos — nunca
nomes, GUIDs, componentes, CVEs nem caminhos.

    python -m pytest tests_live/test_f11_sca_completeness.py -q -s -rs --run-veracode-live   (a partir de backend/)
"""
import asyncio
import json
import math
from collections import Counter
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

from app.veracode import adapters, credentials
from app.veracode.http import CollectionRun, VeracodeHttpPool

from test_veracode_live import _settings

SAMPLE_APPS = 3
MAX_CANDIDATES = 8
MAX_SANDBOXES = 2
OUT_DIR = Path(__file__).resolve().parents[2] / 'private' / 'f11'


def _count_bucket(v) -> str:
    if not isinstance(v, int) or isinstance(v, bool):
        return 'missing_or_not_int'
    return '1' if v == 1 else ('0' if v == 0 else ('2-5' if v <= 5 else '>5'))


def test_live_sca_completeness_and_count_semantics(veracode_live_gate):
    gate = veracode_live_gate
    creds = credentials.resolve(gate.credential_ref)
    settings = replace(_settings(), cache_ttl=0, max_requests_per_collection=90, collection_timeout=900.0,
                       read_timeout=90.0, max_retries=1)

    async def main():
        pool = VeracodeHttpPool(settings)
        report: dict = {'contexts': []}
        try:
            run = CollectionRun(pool, creds, gate.region)
            apps = await adapters.fetch_applications(run)
            assert apps.complete, apps.error
            chosen = []
            for app in [a for a in apps.items if a['last_completed_scan_date']][:MAX_CANDIDATES]:
                summary = await adapters.fetch_summary_report(run, app['guid'])
                sca = (summary.items[0].get('sca') or {}) if summary.complete and summary.items else {}
                if sca.get('third_party_components'):
                    chosen.append((app['guid'], sca))
                if len(chosen) == SAMPLE_APPS:
                    break
            report['candidates_checked'] = MAX_CANDIDATES
            for n, (guid, sca) in enumerate(chosen, 1):
                sandboxes = await adapters.fetch_sandboxes(run, guid)
                contexts = [('POLICY', None)] + [('SANDBOX', sb['guid']) for sb in sandboxes.items[:MAX_SANDBOXES]]
                for context, sb in contexts:
                    # o MESMO paginador do adaptador (id_field=None), sem normalizar, para ler `count`
                    col = await run.paginate(adapters.FINDINGS.format(guid=quote(guid, safe='')), 'findings',
                                             label='f11:findings:sca',
                                             params={'scan_type': 'SCA', **({'context': sb} if sb else {})},
                                             id_field=None, page_size=settings.findings_page_size,
                                             no_retry_status=adapters.FINDINGS_NO_RETRY)
                    items = col.items
                    counts = [i.get('count') for i in items]
                    ints = [c for c in counts if isinstance(c, int) and not isinstance(c, bool)]
                    comps = {(i.get('finding_details') or {}).get('component_id') for i in items
                             if isinstance(i.get('finding_details'), dict)} - {None}
                    expected_pages = (math.ceil(col.total_elements / settings.findings_page_size)
                                      if col.total_elements else 1)
                    report['contexts'].append({
                        'app': f'app{n}', 'context': context, 'complete': col.complete,
                        'error': col.error.code if col.error else None,
                        'pages_fetched': col.pages_fetched, 'total_pages': col.total_pages,
                        'pages_match': col.pages_fetched == max(col.total_pages or 0, 1) == expected_pages,
                        'total_elements': col.total_elements, 'items': len(items),
                        'items_match_total': col.total_elements == len(items),
                        'count_buckets': dict(Counter(_count_bucket(c) for c in counts)),
                        'sum_count': sum(ints), 'all_count_one': bool(items) and all(c == 1 for c in counts),
                        'distinct_component_id': len(comps),
                        'summary_third_party_components': sca.get('third_party_components') if context == 'POLICY'
                        else None,
                        'requests': col.requests, 'retries': col.retries})
            report['requests'], report['retries'] = run.requests, run.retries
            return report
        finally:
            await pool.aclose()

    report = asyncio.run(main())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / 'sca_completeness.json').write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                                   encoding='utf-8')
    ctx = report['contexts']
    print(f"\nrequisições={report['requests']} retries={report['retries']} contextos={len(ctx)}")
    for c in ctx:
        print(c['app'], c['context'], 'completo=', c['complete'], 'erro=', c['error'], 'itens=total:',
              c['items_match_total'], 'páginas ok:', c['pages_match'], 'count todos 1:', c['all_count_one'],
              'buckets:', sorted(c['count_buckets']))
    assert ctx, 'nenhuma aplicação com componentes SCA na amostra'
    assert all(c['complete'] and c['items_match_total'] and c['pages_match'] for c in ctx), \
        [(c['app'], c['context'], c['error']) for c in ctx]
