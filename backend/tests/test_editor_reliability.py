"""F06B.1 — confiabilidade do salvamento do editor no backend: leitura imediatamente após HTTP 200 (sob leitores e
pré-visualizações concorrentes), edições em sequência rápida, resposta antiga (expected_revision vencido) e
persistência após reinício. Dados sintéticos; mede latências em vez de presumir a causa de intermitências.
"""
from __future__ import annotations

import copy
import threading
import time

from fastapi.testclient import TestClient

from app.main import create_app
from test_presentations import OP, Env


def _setup(api: TestClient) -> tuple[Env, str, dict]:
    env = Env(api)
    env.builtin()
    c = env.client('Cliente Confiabilidade Backend')
    p = env.present(env.approved(c['id'], '2026-09', {'apps.total': 5}), template_key='demo-minimo')
    return env, p['id'], env.document(p['id'])


def test_read_after_write_is_consistent_under_concurrent_readers_and_previews(api):
    env, pid, doc = _setup(api)
    stop = threading.Event()
    errors: list[str] = []
    latencies: list[float] = []

    def reader(i: int) -> None:
        while not stop.is_set():
            t0 = time.perf_counter()
            r = api.get(f'/api/presentations/{pid}/view') if i % 2 else \
                api.post(f'/api/presentations/{pid}/preview', json={'document': doc})
            latencies.append(time.perf_counter() - t0)
            if r.status_code != 200:
                errors.append(f'leitor {i}: HTTP {r.status_code}')

    readers = [threading.Thread(target=reader, args=(i,)) for i in range(4)]
    for t in readers:
        t.start()
    try:
        for n in range(1, 11):
            d = copy.deepcopy(doc)
            d['title'] = f'Título salvo {n}'
            t0 = time.perf_counter()
            r = api.put(f'/api/presentations/{pid}/document', json={'document': d, 'expected_revision': n, 'operator': OP})
            latencies.append(time.perf_counter() - t0)
            assert r.status_code == 200, r.text
            assert r.json()['current_revision'] == n + 1
            # releitura imediata após o 200: já enxerga a revisão gravada (sem leitura antiga)
            assert api.get(f'/api/presentations/{pid}').json()['current_revision'] == n + 1
            view = api.get(f'/api/presentations/{pid}/view').json()
            assert view['revision']['number'] == n + 1 and view['presentation']['title'] == f'Título salvo {n}'
            rev = api.get(f'/api/presentations/{pid}/revisions/{n + 1}').json()
            assert rev['document']['title'] == f'Título salvo {n}'
    finally:
        stop.set()
        for t in readers:
            t.join()
    assert errors == []
    assert max(latencies) < 5, f'latência máxima {max(latencies):.2f}s'  # nenhuma espera de bloqueio (timeout 5 s)
    assert env.call('GET', f'/api/presentations/{pid}/integrity')['ok'] is True


def test_stale_expected_revision_never_overwrites_a_newer_save(api):
    env, pid, doc = _setup(api)
    first, second = copy.deepcopy(doc), copy.deepcopy(doc)
    first['title'], second['title'] = 'Edição 1', 'Edição 2'
    env.save(pid, first, 1)
    env.save(pid, second, 2)  # duas edições em sequência rápida, cada uma com a revisão vigente
    stale = copy.deepcopy(doc)
    stale['title'] = 'Resposta antiga'
    r = api.put(f'/api/presentations/{pid}/document', json={'document': stale, 'expected_revision': 1, 'operator': OP})
    assert r.status_code == 409 and r.json()['error']['code'] == 'presentation_conflict'
    meta = env.call('GET', f'/api/presentations/{pid}')
    assert meta['current_revision'] == 3 and [x['number'] for x in meta['revisions']] == [1, 2, 3]
    assert env.document(pid)['title'] == 'Edição 2'
    same = api.put(f'/api/presentations/{pid}/document', json={'document': second, 'expected_revision': 3, 'operator': OP})
    assert same.status_code == 409 and same.json()['error']['code'] == 'presentation_unchanged'  # duplo envio idêntico


def test_saved_revision_survives_restart_and_reads_identically(db_url):
    with TestClient(create_app(db_url)) as api:
        env, pid, doc = _setup(api)
        d = copy.deepcopy(doc)
        d['title'] = 'Persistido antes do reinício'
        env.save(pid, d, 1)
        before = env.view(pid)
    with TestClient(create_app(db_url)) as api:  # novo processo de aplicação, novo engine/conexões
        env = Env(api)
        after = env.view(pid)
        assert after['presentation']['title'] == 'Persistido antes do reinício'
        assert after['revision'] == before['revision'] and after['slides'] == before['slides']
        assert env.call('GET', f'/api/presentations/{pid}/integrity')['ok'] is True
