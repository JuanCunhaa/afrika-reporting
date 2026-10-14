"""Portão da homologação REAL com a Veracode (tests_live) — desligado por padrão.

Só libera quando TODAS as condições valem:
1. o operador pediu explicitamente (`--run-veracode-live` no pytest);
2. `VERACODE_LIVE_TESTS_ENABLED=true` no ambiente (ou no `.env` da raiz);
3. `VERACODE_READ_ONLY` ausente ou true;
4. a referência (`AFRIKA_VC_TEST_CONNECTION`, padrão `env:AFRIKA_VC_TEST`) resolve credenciais válidas.

Os motivos de bloqueio citam apenas nomes de variáveis/referências — nunca valores.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.veracode import credentials
from app.veracode.http import REGION_BASE_URLS
from app.veracode.settings import READ_ONLY_VAR

LIVE_FLAG_VAR = 'VERACODE_LIVE_TESTS_ENABLED'
CONNECTION_VAR = 'AFRIKA_VC_TEST_CONNECTION'
REGION_VAR = 'AFRIKA_VC_TEST_REGION'
DEFAULT_REF = 'env:AFRIKA_VC_TEST'
DEFAULT_REGION = 'commercial'
CLI_FLAG = '--run-veracode-live'


@dataclass(frozen=True)
class LiveGate:
    enabled: bool
    reason: str
    credential_ref: str | None = None
    region: str | None = None


def evaluate(environ: Mapping[str, str], *, requested: bool) -> LiveGate:
    if not requested:
        return LiveGate(False, f'integração real não solicitada pelo operador (use {CLI_FLAG})')
    if (environ.get(LIVE_FLAG_VAR) or '').strip().lower() != 'true':
        return LiveGate(False, f'{LIVE_FLAG_VAR} não é true')
    if (environ.get(READ_ONLY_VAR) or 'true').strip().lower() not in ('true', '1'):
        return LiveGate(False, f'{READ_ONLY_VAR} precisa ser true')
    ref = (environ.get(CONNECTION_VAR) or DEFAULT_REF).strip()
    status = credentials.credential_status(ref, environ)
    if status != 'configured':
        return LiveGate(False, f'credenciais da referência {ref if status != "unsupported_ref" else CONNECTION_VAR}'
                               f' indisponíveis ({status})')
    region = (environ.get(REGION_VAR) or DEFAULT_REGION).strip()
    if region not in REGION_BASE_URLS:
        return LiveGate(False, f'{REGION_VAR} inválida')
    return LiveGate(True, 'ok', ref, region)
