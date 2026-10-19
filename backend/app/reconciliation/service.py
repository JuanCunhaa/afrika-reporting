"""Conferência humana dos indicadores com a plataforma Veracode (F10).

Regras:
- O valor CALCULADO vem sempre do snapshot da revisão (lido pelo servidor); o cliente envia só o valor oficial.
- Diferença por linha: Δ = calculado − oficial; Δ% = Δ / oficial × 100 (sem % quando oficial = 0 e Δ ≠ 0).
- Status: MATCH (todas as linhas informadas e Δ = 0), MISMATCH (alguma Δ ≠ 0) ou NOT_COMPARABLE (filtros não
  confirmados, conferência de estado ATUAL em data diferente da coleta, linhas faltando ou declaração do operador).
  Divergência = investigação da NOSSA consulta; nunca "corrige" o snapshot nem o dashboard.
- Conferir não altera snapshots nem aprovações (imutáveis). Registros são append-only; o vigente é o último. Se o
  snapshot mudar depois (rascunho), a conferência fica DESATUALIZADA e volta a NOT_VERIFIED.
- "Homologado" = indicador APPLICABLE com conferência vigente MATCH sobre valor de origem Veracode.
- Operador DECLARADO (sem autenticação): rastreabilidade, não identidade comprovada.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import ApiError, conflict
from app.metrics.contracts import TemporalMode
from app.metrics.registry import CONTRACTS, REGISTRY
from app.orm import Competence, CompetenceRevision, MetricConference, MetricSnapshot, SnapshotOrigin
from app.reconciliation import guide as guide_mod
from app.reconciliation.guide import GUIDES, Category
from app.snapshots import audit
from app.snapshots.service import IDENTITY_MODE, _commit
from app.snapshots.values import loads, sha256, value_state

MAX_COUNT = 10**12
REASONS = {
    'filters_not_confirmed': 'Filtros/escopo da plataforma não confirmados como iguais aos do indicador',
    'current_state_date_mismatch': 'Indicador de estado ATUAL conferido em data diferente da coleta',
    'entry_incomplete': 'Nem todas as linhas do valor calculado receberam valor oficial',
    'declared_not_comparable': 'Operador declarou que a plataforma não mostra o número com a mesma definição',
}


def _snapshot(rev: CompetenceRevision, metric_id: str) -> MetricSnapshot | None:
    return next((s for s in rev.snapshots if s.metric_id == metric_id), None)


def collected_on(comp: Competence, snap: MetricSnapshot | None) -> str | None:
    if snap is None or snap.collected_at is None:
        return None
    return snap.collected_at.astimezone(ZoneInfo(comp.timezone)).date().isoformat()


def _latest(session: Session, rev: CompetenceRevision) -> dict[str, MetricConference]:
    rows = session.scalars(select(MetricConference).where(MetricConference.revision_id == rev.id)
                           .order_by(MetricConference.metric_id, MetricConference.sequence)).all()
    return {r.metric_id: r for r in rows}  # o último de cada indicador sobrescreve no dicionário


def conference_out(r: MetricConference, snap: MetricSnapshot | None) -> dict:
    return {'sequence': r.sequence, 'status': r.status, 'reasons': json.loads(r.reasons_json),
            'entries': json.loads(r.entries_json), 'filters_confirmed': r.filters_confirmed,
            'checked_on': r.checked_on, 'collected_on': r.collected_on, 'evidence': r.evidence, 'note': r.note,
            'operator': r.operator, 'identity_mode': r.identity_mode, 'computed_origin': r.computed_origin,
            'created_at': r.created_at.isoformat(), 'record_hash': r.record_hash,
            'stale': snap is None or snap.row_hash != r.snapshot_row_hash}


def _row(comp: Competence, metric_id: str, snap: MetricSnapshot | None, conf: MetricConference | None) -> dict:
    contract = REGISTRY[metric_id]
    g = GUIDES[metric_id]
    value = None if snap is None else loads(snap.value_json)
    lines = guide_mod.computed_lines(g, value)
    current = None if conf is None else conference_out(conf, snap)
    if g.category is not Category.APPLICABLE:
        comparison = g.category.value
    elif not lines:
        comparison = 'NO_COMPUTED_VALUE'
    elif current is None or current['stale']:
        comparison = 'NOT_VERIFIED'
    else:
        comparison = current['status']
    homologated = (comparison == 'MATCH' and snap is not None and snap.origin == SnapshotOrigin.VERACODE.value)
    return {'metric_id': metric_id, 'name': contract.name, 'domain': contract.domain.value,
            'context': contract.context.value, 'temporal_mode': contract.temporal_mode.value,
            'same_day_required': contract.temporal_mode == TemporalMode.CURRENT_STATE,
            'guide': guide_mod.public(metric_id),
            'snapshot': None if snap is None else {
                'origin': snap.origin, 'value_state': value_state(snap.origin, value, snap.source_status).value,
                'source_status': snap.source_status, 'collected_on': collected_on(comp, snap),
                'endpoint': snap.endpoint, 'row_hash': snap.row_hash},
            'lines': lines, 'comparison': comparison, 'homologated': homologated, 'conference': current}


def sheet(session: Session, comp: Competence, rev: CompetenceRevision) -> dict:
    latest = _latest(session, rev)
    rows = [_row(comp, c.metric_id, _snapshot(rev, c.metric_id), latest.get(c.metric_id)) for c in CONTRACTS]
    summary: dict[str, int] = {}
    for r in rows:
        summary[r['comparison']] = summary.get(r['comparison'], 0) + 1
    summary['HOMOLOGATED'] = sum(r['homologated'] for r in rows)
    summary['APPLICABLE'] = sum(r['guide']['category'] == Category.APPLICABLE.value for r in rows)
    return {'competence': {'id': str(comp.id), 'competence': comp.label, 'timezone': comp.timezone,
                           'owner_key': comp.owner_key},
            'revision': {'number': rev.number, 'status': rev.status},
            'identity_mode': IDENTITY_MODE, 'summary': summary, 'metrics': rows}


def _validate_official(lines: list[dict], official: dict) -> None:
    keys = {line['key'] for line in lines}
    unknown = set(official) - keys
    if unknown:
        raise ApiError(422, 'unknown_line', 'Linha informada não existe no valor calculado deste indicador')
    for v in official.values():
        if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= MAX_COUNT:
            raise ApiError(422, 'invalid_official_value', 'Valor oficial deve ser inteiro não negativo')


def _entries(lines: list[dict], official: dict) -> list[dict]:
    out = []
    for line in lines:
        o = official.get(line['key'])
        diff = None if o is None else line['computed'] - o
        pct = None if diff is None else (0.0 if diff == 0 else (round(diff / o * 100, 2) if o else None))
        out.append({**line, 'official': o, 'difference': diff, 'difference_pct': pct})
    return out


def record(session: Session, comp: Competence, rev: CompetenceRevision, metric_id: str, *, official: dict,
           filters_confirmed: bool, checked_on: date, operator: str, evidence: str | None = None,
           note: str | None = None, today: date | None = None) -> dict:
    if metric_id not in REGISTRY:
        raise ApiError(404, 'metric_not_found', 'Indicador não está no catálogo')
    g = GUIDES[metric_id]
    if g.category is not Category.APPLICABLE:
        raise conflict(f'conference_{g.category.value.lower()}', 'Indicador sem valor oficial equivalente para '
                                                                  f'conferir ({g.category.value}): {g.reason}')
    snap = _snapshot(rev, metric_id)
    lines = guide_mod.computed_lines(g, None if snap is None else loads(snap.value_json))
    if not lines:
        raise conflict('no_computed_value', 'O snapshot não tem valor efetivo: não há o que conferir (registre o '
                                            'valor manualmente com justificativa, se for o caso)')
    _validate_official(lines, official)
    today = today or datetime.now(ZoneInfo(comp.timezone)).date()
    if checked_on > today:
        raise ApiError(422, 'checked_on_in_future', 'Data da conferência no futuro')
    coll = collected_on(comp, snap)
    reasons = []
    if not filters_confirmed:
        reasons.append('filters_not_confirmed')
    if REGISTRY[metric_id].temporal_mode == TemporalMode.CURRENT_STATE and coll != checked_on.isoformat():
        reasons.append('current_state_date_mismatch')
    if any(line['key'] not in official for line in lines):
        reasons.append('entry_incomplete')
    if note:
        reasons.append('declared_not_comparable')
    entries = _entries(lines, official)
    status = 'NOT_COMPARABLE' if reasons else ('MATCH' if all(e['difference'] == 0 for e in entries)
                                               else 'MISMATCH')
    seq = (session.scalar(select(func.max(MetricConference.sequence)).where(
        MetricConference.revision_id == rev.id, MetricConference.metric_id == metric_id)) or 0) + 1
    content = {'competence_id': str(comp.id), 'revision': rev.number, 'metric_id': metric_id, 'sequence': seq,
               'snapshot_row_hash': snap.row_hash, 'origin': snap.origin, 'entries': entries, 'status': status,
               'reasons': reasons, 'filters_confirmed': filters_confirmed, 'checked_on': checked_on.isoformat(),
               'collected_on': coll, 'evidence': evidence, 'note': note, 'operator': operator}
    row = MetricConference(
        competence_id=comp.id, revision_id=rev.id, owner_key=comp.owner_key, metric_id=metric_id, sequence=seq,
        snapshot_row_hash=snap.row_hash, computed_origin=snap.origin, entries_json=json.dumps(entries),
        status=status, reasons_json=json.dumps(reasons), filters_confirmed=filters_confirmed,
        checked_on=checked_on.isoformat(), collected_on=coll, evidence=evidence, note=note, operator=operator,
        identity_mode=IDENTITY_MODE, record_hash=sha256(content))
    session.add(row)
    # Auditoria sem valores (só indicador, sequência e status).
    audit.append(session, 'conference.recorded', owner_key=comp.owner_key, competence_id=comp.id,
                 revision_id=rev.id, actor=operator,
                 details={'metric_id': metric_id, 'sequence': seq, 'status': status, 'reasons': reasons})
    _commit(session)
    return _row(comp, metric_id, snap, row)


def history(session: Session, comp: Competence, rev: CompetenceRevision, metric_id: str) -> list[dict]:
    if metric_id not in REGISTRY:
        raise ApiError(404, 'metric_not_found', 'Indicador não está no catálogo')
    snap = _snapshot(rev, metric_id)
    rows = session.scalars(select(MetricConference).where(MetricConference.revision_id == rev.id,
                                                          MetricConference.metric_id == metric_id)
                           .order_by(MetricConference.sequence)).all()
    return [conference_out(r, snap) for r in rows]


def _cell(v) -> str:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v)  # números (inclusive diferenças negativas) ficam numéricos
    text = '' if v is None else str(v)
    return "'" + text if text[:1] in ('=', '+', '-', '@', '\t', '\r') else text  # sem fórmulas na planilha


def to_csv(data: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=';', lineterminator='\n')
    w.writerow(['competencia', 'revisao', 'metric_id', 'indicador', 'categoria', 'comparacao', 'homologado', 'linha',
                'calculado', 'oficial', 'diferenca', 'diferenca_pct', 'data_coleta', 'data_conferencia',
                'filtros_confirmados', 'operador', 'evidencia', 'caminho_indicativo', 'filtros', 'motivo'])
    comp, rev = data['competence']['competence'], data['revision']['number']
    for m in data['metrics']:
        conf = m['conference'] or {}
        entries = {e['key']: e for e in conf.get('entries', [])} if conf and not conf.get('stale') else {}
        base = [comp, rev, m['metric_id'], m['name'], m['guide']['category'], m['comparison'],
                'sim' if m['homologated'] else 'não']
        tail = [(m['snapshot'] or {}).get('collected_on'), conf.get('checked_on'),
                None if not conf else ('sim' if conf.get('filters_confirmed') else 'não'), conf.get('operator'),
                conf.get('evidence'), m['guide']['path'], ' | '.join(m['guide']['filters']),
                m['guide']['reason'] or ' | '.join(REASONS.get(r, r) for r in conf.get('reasons', []))]
        for line in m['lines'] or [{'key': '', 'label': '', 'computed': None}]:
            e = entries.get(line['key'], {})
            w.writerow([_cell(x) for x in base + [line['label'], line['computed'], e.get('official'),
                                                  e.get('difference'), e.get('difference_pct')] + tail])
    return buf.getvalue()
