"""Política da ÚNICA escrita autorizada na Veracode (F05): solicitar geração de relatório na Reporting API.

Fonte: especificação oficial SwaggerHub `Veracode/veracode-reporting_api_specification` 1.12.0 e
https://docs.veracode.com/r/Reporting_REST_API (consultadas em 2026-10-15):
- `POST /appsec/v1/analytics/report` (corpo JSON = filtros) -> `_embedded.id` (UUID) e `_embedded.status`;
- `GET  /appsec/v1/analytics/report/{id}?page=N` -> `_embedded.status` (QUEUED|SUBMITTED|PROCESSING|COMPLETED|FAILED),
  `_embedded.findings[]` ou `_embedded.scans[]`, `_embedded.page_metadata` (number, size, total_elements, total_pages);
- obrigatórios: `report_type` e `last_updated_start_date` (data UTC, YYYY-MM-DD); no máximo 6 meses de dados.

Gerar um recurso de relatório não altera aplicações, findings, políticas, usuários nem scans. Mesmo assim, só passa
um corpo que esta política valida (deny-by-default): tipos FINDINGS e SCANS, campos e valores da especificação,
janela de datas fechada e limitada. DELETEDSCANS e AUDIT foram estudados e NÃO estão habilitados.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

GENERATION_PATH = '/appsec/v1/analytics/report'
KNOWN_TYPES = ('FINDINGS', 'SCANS', 'DELETEDSCANS', 'AUDIT')
ENABLED_TYPES = ('FINDINGS', 'SCANS')
FINDINGS_SCAN_TYPES = ('Static Analysis', 'Dynamic Analysis', 'Manual Analysis', 'SCA')
SCANS_SCAN_TYPES = ('Dynamic Analysis', 'Static Analysis', 'Dynamic Analysis - Scan Linked', 'DynamicDS',
                    'DynamicMP - Scan Linked', 'Manual Penetration Testing')
_COMMON = {'report_type', 'last_updated_start_date', 'last_updated_end_date', 'app_id', 'policy_sandbox', 'scan_type'}
ALLOWED_FIELDS = {'FINDINGS': _COMMON | {'status', 'severity', 'policy_rule_passed'},
                  'SCANS': _COMMON | {'most_recent_scan'}}
HARD_MAX_DAYS = 184  # "a maximum of six months of data" (documentação oficial)
_DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
MAX_BODY_BYTES = 4096


class ReportPolicyError(ValueError):
    """Pedido fora da política. Mensagens fixas: nunca ecoam o valor recebido."""

    def __init__(self, code: str, message: str, field: str | None = None):
        super().__init__(message)
        self.code, self.message, self.field = code, message, field


@dataclass(frozen=True)
class ReportRequest:
    report_type: str
    last_updated_start_date: date
    last_updated_end_date: date
    app_id: int | None = None
    policy_sandbox: str | None = None
    scan_type: tuple[str, ...] = ()
    status: str | None = None
    severity: tuple[str, ...] = ()
    policy_rule_passed: str | None = None
    most_recent_scan: bool | None = None

    def body(self) -> dict:
        out: dict[str, Any] = {'report_type': self.report_type,
                               'last_updated_start_date': self.last_updated_start_date.isoformat(),
                               'last_updated_end_date': self.last_updated_end_date.isoformat()}
        for key in ('app_id', 'policy_sandbox', 'status', 'policy_rule_passed', 'most_recent_scan'):
            if getattr(self, key) is not None:
                out[key] = getattr(self, key)
        for key in ('scan_type', 'severity'):
            if getattr(self, key):
                out[key] = list(getattr(self, key))
        return out

    def public(self) -> dict:
        """Parâmetros do pedido para exibição/auditoria (só filtros; nenhum dado de finding)."""
        return self.body()


def _date(raw: Mapping, key: str) -> date:
    value = raw.get(key)
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise ReportPolicyError('invalid_date', 'Data deve estar no formato YYYY-MM-DD (UTC)', key)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ReportPolicyError('invalid_date', 'Data inexistente', key) from None


def _choice(raw: Mapping, key: str, options: tuple) -> Any:
    value = raw.get(key)
    if value is None:
        return None
    if value not in options or isinstance(value, bool) != isinstance(options[0], bool):
        raise ReportPolicyError('invalid_value', 'Valor fora da especificação da Reporting API', key)
    return value


def _list(raw: Mapping, key: str, options: tuple[str, ...]) -> tuple[str, ...]:
    value = raw.get(key)
    if value is None:
        return ()
    if not isinstance(value, list) or not value or len(value) != len(set(map(str, value))) \
            or any(not isinstance(v, str) or v not in options for v in value):
        raise ReportPolicyError('invalid_value', 'Lista fora da especificação da Reporting API', key)
    return tuple(value)


def _add_months(d: date, months: int) -> date:
    idx = d.year * 12 + d.month - 1 + months
    y, m = divmod(idx, 12)
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m + 1, day)
        except ValueError:
            continue
    raise AssertionError('inalcançável')


def build(raw: Any, *, max_days: int = HARD_MAX_DAYS, today: date | None = None) -> ReportRequest:
    if not isinstance(raw, Mapping):
        raise ReportPolicyError('invalid_body', 'Pedido deve ser um objeto JSON')
    rtype = raw.get('report_type')
    if rtype not in KNOWN_TYPES:
        raise ReportPolicyError('invalid_report_type', 'Tipo de relatório desconhecido', 'report_type')
    if rtype not in ENABLED_TYPES:
        raise ReportPolicyError('report_type_not_enabled', 'Tipo de relatório não habilitado (só FINDINGS e SCANS)',
                                'report_type')
    extra = sorted(set(raw) - ALLOWED_FIELDS[rtype])
    if extra:
        raise ReportPolicyError('unknown_field', 'Campo não permitido para este tipo de relatório', extra[0])
    start = _date(raw, 'last_updated_start_date')
    end = _date(raw, 'last_updated_end_date')  # exigido por NÓS (a API aceita sem) para janela sempre limitada
    today = today or datetime.now(timezone.utc).date()
    if end <= start:
        raise ReportPolicyError('invalid_range', 'Data final deve ser posterior à inicial', 'last_updated_end_date')
    if end > today + timedelta(days=1):
        raise ReportPolicyError('invalid_range', 'Data final no futuro', 'last_updated_end_date')
    limit = min(max_days, HARD_MAX_DAYS)
    if (end - start).days > limit or end > _add_months(start, 6):
        raise ReportPolicyError('range_too_large', f'Janela máxima de {limit} dias (limite documentado: 6 meses)',
                                'last_updated_end_date')
    app_id = raw.get('app_id')
    if app_id is not None and (not isinstance(app_id, int) or isinstance(app_id, bool) or not 0 < app_id < 2**53):
        raise ReportPolicyError('invalid_value', 'app_id deve ser o ID numérico positivo da aplicação', 'app_id')
    common = dict(report_type=rtype, last_updated_start_date=start, last_updated_end_date=end, app_id=app_id,
                  policy_sandbox=_choice(raw, 'policy_sandbox', ('Policy', 'Sandbox')))
    if rtype == 'FINDINGS':
        return ReportRequest(**common, scan_type=_list(raw, 'scan_type', FINDINGS_SCAN_TYPES),
                             status=_choice(raw, 'status', ('Open', 'Closed')),
                             severity=_list(raw, 'severity', ('0', '1', '2', '3', '4', '5')),
                             policy_rule_passed=_choice(raw, 'policy_rule_passed', ('yes', 'no')))
    return ReportRequest(**common, scan_type=_list(raw, 'scan_type', SCANS_SCAN_TYPES),
                         most_recent_scan=_choice(raw, 'most_recent_scan', (True, False)))


def check_generation_body(content: bytes) -> ReportRequest:
    """Revalida, no transporte, o corpo que vai sair do processo (defesa em profundidade)."""
    if not isinstance(content, bytes | bytearray) or not content or len(content) > MAX_BODY_BYTES:
        raise ReportPolicyError('invalid_body', 'Corpo ausente ou grande demais')
    try:
        raw = json.loads(content)
    except (ValueError, UnicodeDecodeError):
        raise ReportPolicyError('invalid_body', 'Corpo não é JSON') from None
    request = build(raw)
    if request.body() != raw:  # nada além do que a política reconstrói (sem chaves duplicadas/alteradas)
        raise ReportPolicyError('invalid_body', 'Corpo diverge do pedido validado')
    return request
