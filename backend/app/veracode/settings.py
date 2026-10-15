"""Limites da integração Veracode, configuráveis por variável de ambiente (prefixo AFRIKA_VERACODE_).

`VERACODE_READ_ONLY` (padrão true) é uma trava efetiva: a integração só existe em modo somente leitura e
recusa iniciar com qualquer outro valor (fail-closed). Não há configuração que habilite escrita em aplicações,
findings, políticas, usuários ou scans. Única exceção (F05, autorizada pelo PO): `reporting_enabled` libera
SOMENTE o POST de geração de relatório da Reporting API, validado por `reporting_policy`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, fields

MODES = ('live', 'fixture')
READ_ONLY_VAR = 'VERACODE_READ_ONLY'


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
    # F04 — coleta de métricas (findings por aplicação/contexto): orçamento e prazo da execução inteira.
    metrics_max_requests: int = 2000       # excedido => indicadores INCOMPLETE (nunca agregado parcial definitivo)
    metrics_timeout: float = 600.0         # s, prazo total de uma execução de métricas
    metrics_max_applications: int = 1000   # população acima disso => não coleta (INCOMPLETE)
    # Findings API: padrão documentado = 50. Homologação real (F04): size=100 => HTTP 500 numa aplicação com 52
    # findings, enquanto size=50 respondeu 200. Teto 500 (documentado).
    findings_page_size: int = 50
    # F04.1 — confiabilidade da coleta de findings (evidência real: 500 "frio" passa após ~20 s; 500 persistente no
    # SCA de aplicações sem componentes de terceiros).
    circuit_breaker_threshold: int = 5      # falhas 5xx consecutivas por (recurso, tipo) => circuito aberto
    findings_retry_pass_delay: float = 20.0 # s, espera mínima antes da passada única de nova tentativa
    # Summary Report sem componentes de terceiros: 'verify' (padrão) chama a Findings SCA uma vez e, se vier 500,
    # registra ausência INFERIDA; 'skip' nem chama; 'off' ignora a pré-checagem.
    sca_precheck: str = 'verify'
    # F05 — Reporting API (única escrita autorizada: POST de geração de relatório). DESLIGADA por padrão.
    reporting_enabled: bool = False          # AFRIKA_VERACODE_REPORTING_ENABLED=true habilita o POST de geração
    reporting_max_window_days: int = 31      # janela de `last_updated_*` (teto documentado: 6 meses)
    reporting_poll_interval: float = 5.0     # s, primeira espera entre consultas de status
    reporting_poll_max_interval: float = 30.0  # s, teto do intervalo (crescimento 1,5x)
    reporting_max_polls: int = 60            # consultas de status por relatório
    reporting_timeout: float = 900.0         # s, prazo global (geração + espera + páginas)
    reporting_max_pages: int = 20            # páginas por relatório; acima disso => INCOMPLETE (sem agregado definitivo)
    reporting_max_active: int = 1            # relatórios simultâneos no processo
    reporting_max_per_hour: int = 6          # gerações por hora no processo (cota local)
    read_only: bool = True                 # VERACODE_READ_ONLY; somente True é aceito

    def __post_init__(self):
        if self.read_only is not True:
            raise SettingsError(f'{READ_ONLY_VAR} deve ser true: a integração Veracode é somente leitura')
        if self.sca_precheck not in ('verify', 'skip', 'off'):
            raise SettingsError('AFRIKA_VERACODE_SCA_PRECHECK deve ser verify, skip ou off')
        if self.mode not in MODES:
            raise SettingsError(f'AFRIKA_VERACODE_MODE deve ser um de {MODES}')
        positive = ('connect_timeout', 'read_timeout', 'backoff_base', 'backoff_max', 'max_retry_after',
                    'max_concurrency', 'max_requests_per_collection', 'collection_timeout', 'page_size',
                    'cache_max_entries', 'metrics_max_requests', 'metrics_timeout', 'metrics_max_applications',
                    'findings_page_size', 'circuit_breaker_threshold', 'reporting_max_window_days',
                    'reporting_poll_interval', 'reporting_poll_max_interval', 'reporting_max_polls',
                    'reporting_timeout', 'reporting_max_pages', 'reporting_max_active', 'reporting_max_per_hour')
        for name in positive:
            if getattr(self, name) <= 0:
                raise SettingsError(f'{name} deve ser > 0')
        if self.max_retries < 0 or self.cache_ttl < 0 or self.findings_retry_pass_delay < 0:
            raise SettingsError('max_retries e cache_ttl não podem ser negativos')
        if self.reporting_max_window_days > 184:
            raise SettingsError('reporting_max_window_days máximo é 184 (6 meses documentados)')
        if self.page_size > 500 or self.findings_page_size > 500:
            raise SettingsError('page_size máximo documentado pela Veracode é 500')

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> VeracodeSettings:
        env = os.environ if environ is None else environ
        values = {}
        raw_ro = (env.get(READ_ONLY_VAR) or '').strip().lower()
        if raw_ro not in ('', 'true', '1'):
            # 'false' ou valor desconhecido NUNCA relaxa a trava: o backend recusa iniciar a integração.
            raise SettingsError(f'{READ_ONLY_VAR} deve ser true: a integração Veracode é somente leitura')
        for f in fields(cls):
            if f.name == 'read_only':
                continue
            raw = env.get(f'AFRIKA_VERACODE_{f.name.upper()}')
            if raw is None or raw.strip() == '':
                continue
            try:
                if f.type == 'bool':
                    if raw.strip().lower() not in ('true', 'false', '1', '0'):
                        raise ValueError
                    values[f.name] = raw.strip().lower() in ('true', '1')
                    continue
                values[f.name] = raw.strip() if f.type == 'str' else (int(raw) if f.type == 'int' else float(raw))
            except ValueError:
                raise SettingsError(f'AFRIKA_VERACODE_{f.name.upper()} inválido') from None
        return cls(**values)
