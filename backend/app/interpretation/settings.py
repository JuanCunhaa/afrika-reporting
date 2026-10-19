"""Configuração da interpretação (F08) — só pelo ambiente do servidor (`.env`), nunca pelo frontend.

Padrão SEGURO: provedor determinístico local; envio externo DESLIGADO. Ligar um provedor externo exige, ao mesmo
tempo: `AFRIKA_AI_EXTERNAL_ENABLED=true`, `AFRIKA_AI_PROVIDER` apontando para um adaptador externo registrado,
credencial em `AFRIKA_AI_API_KEY` e — a cada execução — consentimento explícito do operador no pedido. Limites de
custo: pedidos externos por dia e tamanho máximo do conteúdo transmitido.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_PROVIDER = 'deterministic-demo'


def _bool(v: str | None) -> bool:
    return (v or '').strip().lower() in ('1', 'true', 'yes', 'on')


def _int(v: str | None, default: int, lo: int, hi: int) -> int:
    try:
        n = int((v or '').strip())
    except ValueError:
        return default
    return max(lo, min(hi, n))


@dataclass(frozen=True)
class InterpretationSettings:
    provider: str = DEFAULT_PROVIDER
    external_enabled: bool = False
    api_key: str | None = None          # nunca exposta pela API nem registrada em log
    model: str | None = None
    max_requests_per_day: int = 20
    max_input_chars: int = 30_000
    timeout_s: int = 30

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> InterpretationSettings:
        env = os.environ if environ is None else environ
        return cls(provider=(env.get('AFRIKA_AI_PROVIDER') or DEFAULT_PROVIDER).strip(),
                   external_enabled=_bool(env.get('AFRIKA_AI_EXTERNAL_ENABLED')),
                   api_key=(env.get('AFRIKA_AI_API_KEY') or '').strip() or None,
                   model=(env.get('AFRIKA_AI_MODEL') or '').strip() or None,
                   max_requests_per_day=_int(env.get('AFRIKA_AI_MAX_REQUESTS_PER_DAY'), 20, 0, 10_000),
                   max_input_chars=_int(env.get('AFRIKA_AI_MAX_INPUT_CHARS'), 30_000, 1_000, 200_000),
                   timeout_s=_int(env.get('AFRIKA_AI_TIMEOUT_S'), 30, 1, 300))

    def public(self) -> dict:
        return {'provider': self.provider, 'external_enabled': self.external_enabled,
                'credential_configured': self.api_key is not None, 'model': self.model,
                'max_requests_per_day': self.max_requests_per_day, 'max_input_chars': self.max_input_chars,
                'timeout_s': self.timeout_s}
