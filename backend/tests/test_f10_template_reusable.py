"""F10 — revisão do modelo reutilizável `afrika-modelo@2` + tema `afrika@2` (sem nova versão: nada a remover).

Fixa que o modelo NÃO carrega: nome/referência de cliente, dados históricos, valores numéricos fixos, recomendações
de outros clientes ou informação confidencial. Só estrutura, títulos genéricos, placeholders editoriais e indicadores
por `metric_id` (os valores entram da revisão aprovada do dono). As versões publicadas seguem imutáveis (hash fixado
em test_f06c_homologation/test_afrika_template).
"""
from __future__ import annotations

import re

from app.presentations import templates, themes

PLACEHOLDER_HINTS = ('editorial', 'Descreva', 'Defina', 'Tema', 'editável', 'Contato', 'Próxima reunião', 'Dúvidas',
                     'Materiais')
STRUCTURAL_NUMBERS = {'01', '02', '03', '04', '1', '2', '3', '5', '6', '10'}  # seções, "Top 5", "6 meses", "Tema 1"


def _strings(obj, path=''):
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(v, f'{path}.{k}')
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _strings(v, f'{path}[{i}]')


def test_reusable_model_has_no_client_data_numbers_or_foreign_recommendations():
    defn = templates.BUILTIN[('afrika-modelo', 2)]
    texts = [(p, s) for p, s in _strings(defn['slides']) if not p.endswith(('.slot_id', '.type', '.layout', '.chart',
                                                                           '.data_mode'))
             and '.metrics[' not in p]
    assert texts
    for path, s in texts:
        nums = set(re.findall(r'\d+', s))
        assert nums <= STRUCTURAL_NUMBERS, (path, s)              # nenhum valor numérico fixo
        assert not re.search(r'\b(19|20)\d{2}\b|%|R\$|@|https?://|www\.', s), (path, s)  # datas, valores, contatos
    # textos de lista (recomendações, observações, matriz, encerramento) são placeholders genéricos
    items = [s for p, s in texts if '.items[' in p]
    assert items and all(any(h in s for h in PLACEHOLDER_HINTS) or s.startswith('Tema |') for s in items), items
    # indicadores só por metric_id; nenhum valor embutido no modelo
    assert all(isinstance(m, str) for s in defn['slides'] for m in s.get('metrics', []))
    assert not any('value' in z for s in defn['slides'] for z in (s.get('zones') or {}).values())


def test_reusable_theme_has_only_tokens_and_neutral_brand_fallback():
    defn, _ = themes.load(None, 'afrika', 2)
    dumped = defn.model_dump_json()
    assert not re.search(r'https?://|@[a-z0-9-]+\.|\b(19|20)\d{2}-\d{2}\b', dumped)
    assert [s.name for s in defn.asset_slots]  # encaixes de marca existem, mas os arquivos ficam fora do Git
    assert defn.provisional is True
