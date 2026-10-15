"""Valores tipados dos snapshots (F05): validação, estado do valor, JSON canônico e hashes.

Zero ≠ ausente: valor efetivo NULL = sem valor; `0` = zero legítimo. O estado do valor é DERIVADO (não gravado)
da origem, do valor efetivo e do status técnico da coleta — e é independente da homologação com o dashboard.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from app.metrics.contracts import SEVERITY_LABELS, MetricContract, Shape
from app.orm import ValueType

SEVERITY_KEYS = (*SEVERITY_LABELS.values(), 'UNKNOWN')
MAX_COUNT = 10**12
MAX_VALUE_BYTES = 64 * 1024
MAX_DEPTH = 5
MAX_LIST = 1000
MAX_STRING = 500


class ValueState(StrEnum):
    VALIDATED = 'VALIDATED'                    # valor da Veracode, coleta tecnicamente válida (zero é legítimo)
    MANUAL = 'MANUAL'                          # valor efetivo informado manualmente (fonte preservada à parte)
    INCOMPLETE = 'INCOMPLETE'                  # coleta incompleta: só agregado parcial, sem valor efetivo
    SOURCE_UNAVAILABLE = 'SOURCE_UNAVAILABLE'  # fonte indisponível/falhou (UNAVAILABLE, FAILED)
    UNSUPPORTED = 'UNSUPPORTED'                # nenhuma fonte suporta o indicador
    MISSING = 'MISSING'                        # nenhum dado (sem coleta e sem entrada manual)


class InvalidValue(ValueError):
    """Valor fora do tipo declarado. Mensagens fixas: nunca ecoam o valor recebido."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def value_type_for(contract: MetricContract) -> ValueType:
    return {Shape.SCALAR: ValueType.COUNT, Shape.BY_SEVERITY: ValueType.BY_SEVERITY,
            Shape.BREAKDOWN: ValueType.BREAKDOWN, Shape.RANKING: ValueType.RANKING}[contract.shape]


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v: Any) -> bool:
    return (_is_int(v) or isinstance(v, float)) and not isinstance(v, bool) and math.isfinite(v)


def _check_count(v: Any) -> None:
    if not _is_int(v) or v < 0 or v > MAX_COUNT:
        raise InvalidValue('invalid_count', 'Contagem deve ser inteiro não negativo')


def _check_tree(v: Any, depth: int = 0) -> None:
    """Estrutura JSON limitada: números finitos não negativos, textos curtos, listas/objetos rasos."""
    if depth > MAX_DEPTH:
        raise InvalidValue('value_too_deep', 'Estrutura do valor profunda demais')
    if v is None or isinstance(v, bool):
        return
    if isinstance(v, str):
        if len(v) > MAX_STRING:
            raise InvalidValue('value_text_too_long', 'Texto dentro do valor longo demais')
        return
    if _is_number(v) or isinstance(v, float):
        if not _is_number(v) or v < 0:
            raise InvalidValue('invalid_number', 'Números do valor devem ser finitos e não negativos')
        return
    if isinstance(v, list):
        if len(v) > MAX_LIST:
            raise InvalidValue('value_list_too_long', 'Lista do valor longa demais')
        for item in v:
            _check_tree(item, depth + 1)
        return
    if isinstance(v, dict):
        if len(v) > MAX_LIST:
            raise InvalidValue('value_object_too_large', 'Objeto do valor grande demais')
        for k, item in v.items():
            if not isinstance(k, str) or len(k) > 80:
                raise InvalidValue('invalid_key', 'Chave inválida no valor')
            _check_tree(item, depth + 1)
        return
    raise InvalidValue('invalid_value', 'Tipo de valor não suportado')


def validate(value_type: str, value: Any) -> None:
    """Valida o valor EFETIVO (não nulo) contra o tipo do snapshot. Levanta InvalidValue com código fixo."""
    if value is None:
        raise InvalidValue('value_required', 'Valor ausente')
    _check_type(ValueType(value_type), value)
    try:
        size = len(canonical(value).encode())
    except ValueError:  # NaN/Infinity aninhados (json.loads do Python os aceita)
        raise InvalidValue('invalid_number', 'Números do valor devem ser finitos') from None
    if size > MAX_VALUE_BYTES:
        raise InvalidValue('value_too_large', 'Valor grande demais')


def _check_type(vt: ValueType, value: Any) -> None:
    if vt is ValueType.COUNT:
        if isinstance(value, dict):  # ex.: apps.unclassified = {"count": n, ...}
            _check_count(value.get('count'))
            _check_tree(value)
        else:
            _check_count(value)
    elif vt is ValueType.DECIMAL:
        if not _is_number(value) or value < 0:
            raise InvalidValue('invalid_decimal', 'Número deve ser finito e não negativo')
    elif vt is ValueType.PERCENTAGE:
        if not _is_number(value) or not 0 <= value <= 100:
            raise InvalidValue('invalid_percentage', 'Percentual deve estar entre 0 e 100')
    elif vt is ValueType.BY_SEVERITY:
        if not isinstance(value, dict) or set(value) != {*SEVERITY_KEYS, 'total'}:
            raise InvalidValue('invalid_by_severity', 'Severidades devem conter exatamente: '
                                                     + ', '.join(SEVERITY_KEYS) + ' e total')
        for k in (*SEVERITY_KEYS, 'total'):
            _check_count(value[k])
        if value['total'] != sum(value[k] for k in SEVERITY_KEYS):
            raise InvalidValue('severity_total_mismatch', 'Total difere da soma das severidades')
    elif vt in (ValueType.BREAKDOWN, ValueType.RANKING):
        if not isinstance(value, dict):
            raise InvalidValue('invalid_breakdown', 'Distribuição/ranking deve ser um objeto JSON')
        key = 'items' if vt is ValueType.BREAKDOWN else 'top'
        if key in value and not isinstance(value[key], list):
            raise InvalidValue('invalid_breakdown', f'"{key}" deve ser uma lista')
        _check_tree(value)


def headline(value_type: str, value: Any) -> int | float | None:
    """Número principal para séries/gráficos: contagem, total por severidade ou número. Nunca inventa."""
    if value is None:
        return None
    vt = ValueType(value_type)
    if vt is ValueType.COUNT:
        return value.get('count') if isinstance(value, dict) else value
    if vt is ValueType.BY_SEVERITY:
        return value.get('total')
    if vt in (ValueType.DECIMAL, ValueType.PERCENTAGE):
        return value
    return None


def value_state(origin: str, value: Any, source_status: str | None) -> ValueState:
    if origin == 'MANUAL':
        return ValueState.MANUAL
    if value is not None:
        return ValueState.VALIDATED
    return {'INCOMPLETE': ValueState.INCOMPLETE, 'UNAVAILABLE': ValueState.SOURCE_UNAVAILABLE,
            'FAILED': ValueState.SOURCE_UNAVAILABLE, 'UNSUPPORTED': ValueState.UNSUPPORTED}.get(
        source_status or '', ValueState.MISSING)


# ---------------------------------------------------------------- JSON canônico e hashes

def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def dumps(obj: Any) -> str | None:
    return None if obj is None else canonical(obj)


def loads(text: str | None) -> Any:
    return None if text is None else json.loads(text)


def sha256(obj: Any) -> str:
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


def _iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.astimezone(timezone.utc).isoformat()


HASHED_FIELDS = ('metric_id', 'contract_version', 'value_type', 'shape', 'unit', 'origin', 'value_json',
                 'source_status', 'source_value_json', 'source_partial_json', 'source_reasons_json',
                 'dashboard_homologation', 'source_name', 'endpoint', 'context', 'temporal_json', 'scope_refs_json',
                 'provenance_json', 'manual_justification', 'manual_operator')


def snapshot_hash(s) -> str:
    """Hash do CONTEÚDO de um snapshot (independe da revisão: cópia exata => mesmo hash)."""
    payload = {f: getattr(s, f) for f in HASHED_FIELDS}
    payload['collected_at'] = _iso(s.collected_at)
    payload['manual_at'] = _iso(s.manual_at)
    payload['collection_run_id'] = None if s.collection_run_id is None else str(s.collection_run_id)
    return sha256(payload)
