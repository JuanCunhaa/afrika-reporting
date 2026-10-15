"""F05 — tipos de valor dos snapshots (unidade): contagem, decimal, percentual, severidades, distribuições."""
import math

import pytest

from app.metrics.registry import CONTRACTS
from app.snapshots.values import InvalidValue, ValueState, headline, validate, value_state, value_type_for

SEV = {'VERY_HIGH': 1, 'HIGH': 2, 'MEDIUM': 0, 'LOW': 0, 'VERY_LOW': 0, 'INFORMATIONAL': 0, 'UNKNOWN': 0, 'total': 3}


@pytest.mark.parametrize('value_type,value', [
    ('count', 0), ('count', 10**12), ('count', {'count': 4, 'no_subclients': True}),
    ('decimal', 0), ('decimal', 12.5), ('percentage', 0), ('percentage', 100), ('percentage', 37.5),
    ('by_severity', SEV), ('breakdown', {'items': [{'name': 'BU', 'applications': 2}], 'unknown': 0}),
    ('ranking', {'top': [{'cwe_id': 79, 'findings': 2}], 'others': 0}),
])
def test_valid_values(value_type, value):
    validate(value_type, value)


@pytest.mark.parametrize('value_type,value,code', [
    ('count', -1, 'invalid_count'), ('count', 2.0, 'invalid_count'), ('count', True, 'invalid_count'),
    ('count', '1', 'invalid_count'), ('count', 10**12 + 1, 'invalid_count'), ('count', None, 'value_required'),
    ('decimal', -0.1, 'invalid_decimal'), ('decimal', math.inf, 'invalid_decimal'),
    ('decimal', False, 'invalid_decimal'),
    ('percentage', 100.01, 'invalid_percentage'), ('percentage', -1, 'invalid_percentage'),
    ('percentage', math.nan, 'invalid_percentage'),
    ('by_severity', {**SEV, 'total': 4}, 'severity_total_mismatch'),
    ('by_severity', {k: v for k, v in SEV.items() if k != 'UNKNOWN'}, 'invalid_by_severity'),
    ('by_severity', {**SEV, 'EXTRA': 0}, 'invalid_by_severity'),
    ('breakdown', [1, 2], 'invalid_breakdown'), ('breakdown', {'items': 'x'}, 'invalid_breakdown'),
    ('breakdown', {'items': [{'applications': -1}]}, 'invalid_number'),
    ('ranking', {'top': [{'name': 'x' * 501}]}, 'value_text_too_long'),
    ('ranking', {'a': {'b': {'c': {'d': {'e': {'f': 1}}}}}}, 'value_too_deep'),
])
def test_invalid_values_have_fixed_codes(value_type, value, code):
    with pytest.raises(InvalidValue) as info:
        validate(value_type, value)
    assert info.value.code == code
    assert repr(value)[:20] not in info.value.message or code == 'invalid_by_severity'  # não ecoa o valor


def test_headline_and_state_distinguish_zero_from_absence():
    assert headline('count', 0) == 0 and headline('count', None) is None
    assert headline('count', {'count': 3}) == 3 and headline('by_severity', SEV) == 3
    assert headline('breakdown', {'items': []}) is None  # sem número principal: não inventa
    assert value_state('VERACODE', 0, 'VALIDATED') is ValueState.VALIDATED
    assert value_state('VERACODE', None, 'INCOMPLETE') is ValueState.INCOMPLETE
    assert value_state('VERACODE', None, 'UNAVAILABLE') is ValueState.SOURCE_UNAVAILABLE
    assert value_state('VERACODE', None, 'FAILED') is ValueState.SOURCE_UNAVAILABLE
    assert value_state('VERACODE', None, 'UNSUPPORTED') is ValueState.UNSUPPORTED
    assert value_state('VERACODE', None, None) is ValueState.MISSING
    assert value_state('MANUAL', 0, 'VALIDATED') is ValueState.MANUAL


def test_every_contract_maps_to_a_value_type():
    assert {value_type_for(c).value for c in CONTRACTS} <= {'count', 'by_severity', 'breakdown', 'ranking'}
