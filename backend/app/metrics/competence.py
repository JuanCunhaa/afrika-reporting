"""Competência = mês FECHADO (primeiro dia 00:00 até o primeiro dia do mês seguinte, exclusivo).

Fuso por deslocamento fixo (`±HH:MM`, padrão `+00:00`): datas da Veracode vêm em UTC (`...Z`) e são comparadas
no instante absoluto. Deslocamento fixo evita depender de base de fusos (tzdata) — limitação: sem horário de verão.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

_COMPETENCE = re.compile(r'^(\d{4})-(0[1-9]|1[0-2])$')
_OFFSET = re.compile(r'^([+-])(0\d|1[0-4]):([0-5]\d)$')


class CompetenceError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Competence:
    label: str            # YYYY-MM
    utc_offset: str       # ±HH:MM
    start: datetime       # inclusivo (com fuso)
    end: datetime         # exclusivo (com fuso)

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment < self.end

    def month_label(self, moment: datetime) -> str:
        local = moment.astimezone(self.start.tzinfo)
        return f'{local.year:04d}-{local.month:02d}'

    def as_dict(self) -> dict:
        return {'competence': self.label, 'utc_offset': self.utc_offset, 'period_start': self.start.isoformat(),
                'period_end_exclusive': self.end.isoformat(),
                'period_end_inclusive': (self.end - timedelta(microseconds=1)).isoformat()}


def parse_offset(value: str) -> timezone:
    m = _OFFSET.fullmatch(value or '')
    if not m:
        raise CompetenceError('invalid_utc_offset', 'Fuso deve estar no formato ±HH:MM (ex.: -03:00)')
    sign, hours, minutes = m.groups()
    delta = timedelta(hours=int(hours), minutes=int(minutes))
    return timezone(-delta if sign == '-' else delta)


def parse(label: str, utc_offset: str = '+00:00', *, now: datetime | None = None) -> Competence:
    m = _COMPETENCE.fullmatch(label or '')
    if not m:
        raise CompetenceError('invalid_competence', 'Competência deve estar no formato YYYY-MM (ex.: 2026-09)')
    year, month = int(m.group(1)), int(m.group(2))
    if year < 2000:
        raise CompetenceError('invalid_competence', 'Competência anterior a 2000 não é suportada')
    tz = parse_offset(utc_offset)
    start = datetime(year, month, 1, tzinfo=tz)
    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=tz)
    current = now or datetime.now(timezone.utc)
    if end > current:
        raise CompetenceError('competence_not_closed', 'A competência precisa ser um mês já encerrado')
    return Competence(label, utc_offset, start, end)


def parse_timestamp(value: str | None) -> datetime | None:
    """ISO-8601 da Veracode (`2026-09-30T23:59:59.999Z`). Sem fuso explícito => desconhecido (None)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None
