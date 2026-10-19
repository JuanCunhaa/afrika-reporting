"""F09 — homologação REAL opt-in da pilha completa (mesmo portão de test_veracode_live; somente GET).

API local (banco SQLite TEMPORÁRIO, apagado ao fim) → conexão por referência `env:` → dois clientes com escopos
DISJUNTOS sobre uma amostra PEQUENA de aplicações com scan concluído → subcliente por BU → coleta de indicadores da
competência → rascunho da competência a partir da coleta. Todo pedido HTTP à Veracode passa por um transporte que
registra método, rota (GUIDs mascarados) e status: o teste FALHA se houver qualquer método diferente de GET.

Saída no terminal: só contagens, estados e códigos. Valores agregados e a identificação da amostra (necessária para a
conferência humana no dashboard) vão SOMENTE para `private/f09/` (ignorado pelo Git). Nenhum finding é persistido.

    VERACODE_LIVE_TESTS_ENABLED=true python -m pytest backend/tests_live/test_f09_live_flow.py -q -s -rs \
        --run-veracode-live
"""
from __future__ import annotations

import dataclasses
import json
import os
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app import db
from app.main import create_app

from test_veracode_live import _settings

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / 'private' / 'f09'
SAMPLE_A, SAMPLE_B = 2, 1          # aplicações por cliente (amostra pequena e controlada)
METRICS_BUDGET = 150               # requisições por execução de métricas
COMPETENCE = os.environ.get('AFRIKA_F09_COMPETENCE', '2026-09')
_GUID = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')


class RecordingTransport(httpx.AsyncBaseTransport):
    """Registra (método, rota mascarada, status) de cada pedido real. Sem query, cabeçalhos ou corpo."""

    def __init__(self):
        self.inner = httpx.AsyncHTTPTransport()
        self.calls: list[tuple[str, str, int]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        route = re.sub(r'/\d+(?=/|$)', '/{id}', _GUID.sub('{guid}', request.url.path))
        try:
            response = await self.inner.handle_async_request(request)
        except Exception:
            self.calls.append((request.method, route, -1))
            raise
        self.calls.append((request.method, route, response.status_code))
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()


_SEV = ('VERY_HIGH', 'HIGH', 'MEDIUM', 'LOW', 'VERY_LOW', 'INFORMATIONAL', 'UNKNOWN')
_HUMAN_CHECK = ('apps.total', 'apps.by_policy_compliance', 'apps.loc.total', 'sast.policy.open.by_severity',
                'sast.policy.summary.by_severity', 'sast.sandbox.open.by_severity',
                'sast.policy.new_in_period.by_severity', 'sast.policy.open.by_cwe', 'sca.policy.open.by_severity',
                'sca.policy.summary.components', 'sca.agent.linked_projects', 'scans.covered_apps')


def _checklist(d: dict) -> str:
    """Planilha PRIVADA de conferência humana com o dashboard (docs/F09_METRIC_RECONCILIATION.md §5)."""
    def fmt(v):
        if isinstance(v, dict) and all(k in v for k in _SEV + ('total',)):
            return ' / '.join(f'{k}={v[k]}' for k in _SEV) + f' (total={v["total"]})'
        s = json.dumps(v, ensure_ascii=False)
        return s if len(s) < 400 else s[:400] + '…'
    out = ['# CONFERÊNCIA HUMANA F09 — PRIVADO (não versionar, não compartilhar fora do PO)', '',
           f'Coleta: {d["started_at"]} · competência {d["competence"]} · região {d["region"]}', '',
           'Estado ATUAL: comparar com o dashboard NO MESMO DIA da coleta. Policy = produção; Sandbox = '
           'desenvolvimento. Aberto = OPEN e mitigação não aprovada.', '']
    for c in ('A', 'B'):
        out += [f'## Cliente {c} — amostra', '']
        out += [f'- {a["name"]} · GUID {a["guid"]} · BU {a.get("business_unit")} · último scan '
                f'{a.get("last_completed_scan_date")}' for a in d['sample'][c]]
        out += ['', '| ID | Status Afrika | Valor Afrika | Valor no dashboard | Δ abs | Δ % | Observação |',
                '|---|---|---|---|---|---|---|']
        for mid in _HUMAN_CHECK:
            m = d['metrics'][c].get(mid)
            if m is not None:
                val = fmt(m['value']) if m['status'] == 'VALIDATED' else f'— ({",".join(m["reasons"])})'
                out.append(f'| {mid} | {m["status"]} | {val} | ______ | | | |')
        out.append('')
    return '\n'.join(out)


def _call(api: TestClient, method: str, url: str, expected: int = 200, **body) -> dict:
    r = api.request(method, url, json=body or None)
    assert r.status_code == expected, f'{method} {url.split("?")[0]} -> {r.status_code}'
    return r.json()


def _all(api: TestClient, url: str) -> dict:
    """Todas as páginas da listagem local (a descoberta é coletada uma vez e servida do cache)."""
    first = _call(api, 'GET', f'{url}?limit=200&offset=0')
    items = list(first['items'])
    while len(items) < first['total']:
        items += _call(api, 'GET', f'{url}?limit=200&offset={len(items)}')['items']
    return {**first, 'items': items}


def _wait(api: TestClient, run_id: str, timeout: float = 900) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        body = _call(api, 'GET', f'/api/metrics/runs/{run_id}')
        if body['status'] in ('done', 'cancelled', 'failed'):
            return body
        time.sleep(1)
    raise AssertionError('execução de métricas não terminou no prazo')


def test_live_f09_full_stack_small_sample(veracode_live_gate, tmp_path):
    gate = veracode_live_gate
    settings = dataclasses.replace(_settings(), metrics_max_requests=METRICS_BUDGET, cache_ttl=600,
                                   reporting_enabled=False)
    assert settings.read_only is True and settings.reporting_enabled is False
    url = f'sqlite:///{(tmp_path / "f09-live.sqlite3").as_posix()}'
    db.upgrade(url)
    transport = RecordingTransport()
    started = datetime.now(timezone.utc).isoformat()
    with TestClient(create_app(url, veracode_settings=settings, veracode_transport=transport)) as api:
        conn = _call(api, 'POST', '/api/connections', 201, name='Conexão de testes F09', region=gate.region,
                     credential_ref=gate.credential_ref)
        a = _call(api, 'POST', '/api/clients', 201, name='Cliente F09 A', connection_id=conn['id'])
        b = _call(api, 'POST', '/api/clients', 201, name='Cliente F09 B', connection_id=conn['id'])
        test = _call(api, 'POST', f'/api/veracode/clients/{a["id"]}/test')
        apps = _all(api, f'/api/veracode/clients/{a["id"]}/applications')
        bus = _call(api, 'GET', f'/api/veracode/clients/{a["id"]}/business-units?limit=1')
        teams = _call(api, 'GET', f'/api/veracode/clients/{a["id"]}/teams?limit=1')
        users = _call(api, 'GET', f'/api/veracode/clients/{a["id"]}/users?limit=1')
        scanned = sorted((x for x in apps['items'] if x.get('last_completed_scan_date')), key=lambda x: x['guid'])
        assert len(scanned) >= SAMPLE_A + SAMPLE_B, 'tenant de testes sem aplicações escaneadas suficientes'
        sample_a, sample_b = scanned[:SAMPLE_A], scanned[SAMPLE_A:SAMPLE_A + SAMPLE_B]

        def scope(kind, owner, domain, rule, version=0):
            r = api.put(f'/api/scopes/{kind}/{owner}/{domain}', json={'rule': rule, 'expected_version': version})
            assert r.status_code == 201, r.text
        scope('clients', a['id'], 'applications',
              {'field': 'application.id', 'cmp': 'in', 'values': [x['guid'] for x in sample_a]})
        scope('clients', b['id'], 'applications',
              {'field': 'application.id', 'cmp': 'in', 'values': [x['guid'] for x in sample_b]})
        bu0 = (sample_a[0].get('business_unit') or {}).get('guid')
        sub = _call(api, 'POST', f'/api/clients/{a["id"]}/subclients', 201, name='Subcliente F09 por BU')
        if bu0:
            scope('subclients', sub['id'], 'applications', {'field': 'business_unit.id', 'cmp': 'eq', 'value': bu0})
        prev_a = _call(api, 'POST', f'/api/scope-preview/clients/{a["id"]}', domain='applications', sample_limit=50)
        prev_b = _call(api, 'POST', f'/api/scope-preview/clients/{b["id"]}', domain='applications', sample_limit=50)
        ids_a = {r['id'] for r in prev_a['universe']['sample']} if 'sample' in prev_a['universe'] else None
        ids_b = {r['id'] for r in prev_b['universe']['sample']} if 'sample' in prev_b['universe'] else None

        runs = {}
        for key, owner in (('A', a), ('B', b)):
            started_run = _call(api, 'POST', '/api/metrics/runs', 202, owner_kind='client', owner_id=owner['id'],
                                competence=COMPETENCE)
            runs[key] = _wait(api, started_run['run_id'])
        draft = _call(api, 'POST', '/api/competences/from-run', 201, run_id=runs['A']['run_id'],
                      operator='Operador F09 (homologação real)')
        detail = _call(api, 'GET', f'/api/competences/{draft["competence_id"]}/revisions/{draft["revision"]}')

    methods = Counter(m for m, _, _ in transport.calls)
    statuses = Counter(s for _, _, s in transport.calls)
    routes = Counter(f'{m} {r} -> {s}' for m, r, s in transport.calls)
    metrics = {k: {m['metric_id']: m for m in run['result']['metrics']} for k, run in runs.items()}

    # ---- terminal: só contagens, estados e códigos
    print(f'\nteste de conexão: {test["status"]}; checks={[c["status"] for c in test["checks"]]}')
    print(f'descoberta: apps={apps["total"]} completo={apps["complete"]} BUs={bus["total"]} Teams={teams["total"]} '
          f'usuários={users["total"]} completo={users["complete"]}')
    print(f'amostra: A={len(sample_a)} B={len(sample_b)}; subcliente por BU definido={bool(bu0)}')
    print(f'isolamento (prévia): A={prev_a["universe"]["included"]} B={prev_b["universe"]["included"]} '
          f'interseção={len(ids_a & ids_b) if ids_a is not None and ids_b is not None else "n/d"}')
    print(f'HTTP: métodos={dict(methods)} status={dict(statuses)} total={len(transport.calls)}')
    for k, run in runs.items():
        st = Counter(m['status'] for m in run['result']['metrics'])
        print(f'execução {k}: status={run["status"]} indicadores={dict(st)} coleta={run["result"].get("collection", {})}'
              .replace(', ', ','))
    print('rascunho da competência: status', detail['status'], 'snapshots', len(detail['snapshots']))

    # ---- privado (ignorado pelo Git): necessário para a conferência humana com o dashboard
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    private = {
        'warning': 'PRIVADO — dados do tenant de testes; nunca versionar nem compartilhar fora do PO',
        'started_at': started, 'competence': COMPETENCE, 'region': gate.region,
        'sample': {'A': [{'guid': x['guid'], 'name': x['name'],
                          'business_unit': (x.get('business_unit') or {}).get('name'),
                          'last_completed_scan_date': x.get('last_completed_scan_date')} for x in sample_a],
                   'B': [{'guid': x['guid'], 'name': x['name'],
                          'last_completed_scan_date': x.get('last_completed_scan_date')} for x in sample_b]},
        'discovery': {'applications': apps['total'], 'business_units': bus['total'], 'teams': teams['total'],
                      'users': users['total']},
        'http': {'methods': dict(methods), 'statuses': {str(k): v for k, v in statuses.items()},
                 'routes': dict(routes)},
        'metrics': {k: {mid: {'status': m['status'], 'value': m['value'], 'partial': m['partial'],
                              'reasons': [r['code'] for r in m['reasons']], 'filters': m['filters'],
                              'temporal': m['temporal']} for mid, m in ms.items()} for k, ms in metrics.items()},
        'collection': {k: run['result'].get('collection') for k, run in runs.items()},
    }
    (OUT_DIR / 'live_flow.json').write_text(json.dumps(private, ensure_ascii=False, indent=2, default=str),
                                             encoding='utf-8')
    (OUT_DIR / 'CONFERENCIA_HUMANA.md').write_text(_checklist(private), encoding='utf-8')

    # ---- critérios
    assert set(methods) == {'GET'}, f'método não autorizado usado: {dict(methods)}'
    assert test['status'] in ('ok', 'partial')
    assert apps['complete'] is True
    assert prev_a['universe']['included'] == SAMPLE_A and prev_b['universe']['included'] == SAMPLE_B
    if ids_a is not None and ids_b is not None:
        assert not ids_a & ids_b
    assert metrics['A']['apps.total']['status'] == 'VALIDATED' and metrics['A']['apps.total']['value'] == SAMPLE_A
    assert metrics['B']['apps.total']['status'] == 'VALIDATED' and metrics['B']['apps.total']['value'] == SAMPLE_B
    for ms in metrics.values():
        for m in ms.values():  # zero != ausente: nada não-validado carrega valor
            assert m['status'] == 'VALIDATED' or m['value'] is None
    assert detail['status'] == 'DRAFT' and detail['snapshots']
