"""Limites da integração Veracode, todos configuráveis por variável de ambiente (prefixo AFRIKA_VERACODE_)."""
from __future__ import annotations

import os
from dataclasses import dataclass, fields

MODES = ('live', 'fixture')


class SettingsError(ValueError):
    pass


@dataclass(frozen=True)
class VeracodeSettings:
    # 'live' = API oficial (somente leitura); 'fixture' = tenant SINTÉTICO em processo (testes/E2E/demo).
    mode: str = 'live'
    connect_timeout: float = 5.0           # s, estabelecer conexão TCP/TLS
    read_timeout: float = 30.0             # s, aguardar resposta
    max_retries: int = 3                   # tentativas extras por requisição (429, 5xx, timeout, rede)
    backoff_base: float = 0.5              # s, base do backoff exponencial (full jitter)
    backoff_max: float = 8.0               # s, teto do backoff
    max_retry_after: float = 30.0          # s, Retry-After acima disso => desiste (rate_limited)
    max_concurrency: int = 4               # requisições simultâneas à Veracode (processo inteiro)
    max_requests_per_collection: int = 300 # orçamento por coleta; esgotado => coleta incompleta
    collection_timeout: float = 120.0      # s, prazo total de uma coleta; excedido => incompleta
    page_size: int = 100                   # itens por página (máximo documentado: 500)
    cache_ttl: float = 300.0               # s, validade do cache de descoberta (0 desativa)
    cache_max_entries: int = 256

    def __post_init__(self):
        if self.mode not in MODES:
            raise SettingsError(f'AFRIKA_VERACODE_MODE deve ser um de {MODES}')
        positive = ('connect_timeout', 'read_timeout', 'backoff_base', 'backoff_max', 'max_retry_after',
                    'max_concurrency', 'max_requests_per_collection', 'collection_timeout', 'page_size',
                    'cache_max_entries')
        for name in positive:
            if getattr(self, name) <= 0:
                raise SettingsError(f'{name} deve ser > 0')
        if self.max_retries < 0 or self.cache_ttl < 0:
            raise SettingsError('max_retries e cache_ttl não podem ser negativos')
        if self.page_size > 500:
            raise SettingsError('page_size máximo documentado pela Veracode é 500')

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> VeracodeSettings:
        env = os.environ if environ is None else environ
        values = {}
        for f in fields(cls):
            raw = env.get(f'AFRIKA_VERACODE_{f.name.upper()}')
            if raw is None or raw.strip() == '':
                continue
            try:
                values[f.name] = raw.strip() if f.type == 'str' else (int(raw) if f.type == 'int' else float(raw))
            except ValueError:
                raise SettingsError(f'AFRIKA_VERACODE_{f.name.upper()} inválido') from None
        return cls(**values)
