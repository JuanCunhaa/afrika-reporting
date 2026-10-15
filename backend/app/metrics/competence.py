"""Competência = mês FECHADO no fuso do cliente: [1º dia 00:00 local, 1º dia do mês seguinte 00:00 local).

Fuso IANA (padrão `America/Sao_Paulo`, configurável por cliente) com as regras HISTÓRICAS da zona (`zoneinfo` +
pacote `tzdata`): o deslocamento de cada limite é o vigente naquela data (ex.: horário de verão até 2019). Datas da
Veracode vêm em UTC (`...Z`) e são comparadas no instante absoluto, contra o intervalo UTC equivalente.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

DEFAULT_TIMEZONE = 'America/Sao_Paulo'
_COMPETENCE = re.compile(r'^(\d{4})-(0[1-9]|1[0-2])$')
_TZ_NAME = re.compile(r'^[A-Za-z][A-Za-z0-9_+\-]*(/[A-Za-z0-9_+\-]+){0,2}$')


class CompetenceError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@lru_cache(maxsize=1)
def _known_zones() -> frozenset[str]:
    return frozenset(available_timezones())


def zone(name: str) -> ZoneInfo:
    """Valida o nome IANA (lista oficial da base instalada) antes de abrir a zona — nunca caminho de arquivo."""
    if not isinstance(name, str) or len(name) > 64 or not _TZ_NAME.fullmatch(name) or name not in _known_zones():
        raise CompetenceError('invalid_timezone', 'Fuso deve ser um nome IANA válido (ex.: America/Sao_Paulo)')
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise CompetenceError('invalid_timezone', 'Fuso deve ser um nome IANA válido (ex.: America/Sao_Paulo)') \
            from None


def _local_midnight(year: int, month: int, tz: ZoneInfo) -> datetime:
    # Meia-noite inexistente (início do horário de verão exatamente às 00:00) => primeiro instante válido do dia.
    naive = datetime(year, month, 1)
    moment = naive.replace(tzinfo=tz)
    roundtrip = moment.astimezone(timezone.utc).astimezone(tz)
    if roundtrip.replace(tzinfo=None) != naive:
        return roundtrip
    return moment


@dataclass(frozen=True)
class Competence:
    label: str            # YYYY-MM
    timezone: str         # nome IANA
    start: datetime       # inclusivo (hora local do fuso)
    end: datetime         # exclusivo (hora local do fuso)

    @property
    def utc_start(self) -> datetime:
        return self.start.astimezone(timezone.utc)

    @property
    def utc_end(self) -> datetime:
        return self.end.astimezone(timezone.utc)

    def contains(self, moment: datetime) -> bool:
        return self.utc_start <= moment.astimezone(timezone.utc) < self.utc_end

    def month_label(self, moment: datetime) -> str:
        local = moment.astimezone(ZoneInfo(self.timezone))
        return f'{local.year:04d}-{local.month:02d}'

    def as_dict(self) -> dict:
        return {'competence': self.label, 'timezone': self.timezone,
                'period_start': self.start.isoformat(), 'period_end_exclusive': self.end.isoformat(),
                'period_end_inclusive': (self.end - timedelta(microseconds=1)).isoformat(),
                'utc_start': self.utc_start.isoformat(), 'utc_end_exclusive': self.utc_end.isoformat(),
                'utc_offset_start': self.start.strftime('%z'), 'utc_offset_end': self.end.strftime('%z')}


def parse(label: str, tz_name: str = DEFAULT_TIMEZONE, *, now: datetime | None = None) -> Competence:
    m = _COMPETENCE.fullmatch(label or '')
    if not m:
        raise CompetenceError('invalid_competence', 'Competência deve estar no formato YYYY-MM (ex.: 2026-09)')
    year, month = int(m.group(1)), int(m.group(2))
    if year < 2000:
        raise CompetenceError('invalid_competence', 'Competência anterior a 2000 não é suportada')
    tz = zone(tz_name)
    start = _local_midnight(year, month, tz)
    end = _local_midnight(year + (month == 12), month % 12 + 1, tz)
    current = now or datetime.now(timezone.utc)
    if end > current:
        raise CompetenceError('competence_not_closed', 'A competência precisa ser um mês já encerrado no fuso do '
                                                       'cliente')
    return Competence(label, tz_name, start, end)


def parse_timestamp(value: str | None) -> datetime | None:
    """ISO-8601 da Veracode (`2026-09-30T23:59:59.999Z`; Summary Report: `2026-08-11 17:53:42 UTC`).
    Sem fuso explícito => desconhecido (None)."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith(' UTC'):
        text = text[:-4] + '+00:00'
    try:
        moment = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None
