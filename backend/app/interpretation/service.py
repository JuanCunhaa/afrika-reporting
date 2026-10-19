"""Persistência e revisão humana das interpretações (F08).

- Linha de interpretação = (apresentação, slide, tipo). Cada geração, regeneração ou edição humana é uma VERSÃO nova
  (append-only, encadeada ao pai); o estado vem dos eventos append-only: GENERATED → IN_REVIEW → APPROVED | REJECTED.
- Só a versão mais recente da linha avança no fluxo. Aprovar exige validação sem bloqueios e contexto atual (fatos e
  fontes iguais aos da geração); senão a versão é sinalizada como desatualizada e fica bloqueada.
- Aplicar = gravar o texto APROVADO num campo editorial do slide como NOVA revisão da apresentação (caminho normal da
  F06A, mesma transação do evento APPLIED). Texto existente diferente só é substituído com confirmação explícita.
- Nada aqui escreve em snapshots/aprovações nem chama a Veracode; a exportação (F07) só lê o documento persistido.
- Logs e auditoria nunca levam o texto nem valores: só ids, hashes, tipo, nível e provedor.
"""
from __future__ import annotations

import difflib
import json
import logging
import re
import uuid
from datetime import datetime, time, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.errors import ApiError, conflict
from app.interpretation import context as ctx_mod
from app.interpretation import providers, validate
from app.interpretation.contracts import (
    KIND_NAMES, KINDS_BY_SLIDE, Context, Kind, Level, Origin, Statement, Status, budget_for,
)
from app.interpretation.settings import DEFAULT_PROVIDER, InterpretationSettings
from app.orm import (
    InterpretationEvent, InterpretationSlideSetting, InterpretationVersion, Presentation, PresentationRevision,
    utcnow,
)
from app.presentations import service as presentations
from app.presentations.catalog import SlideType
from app.presentations.document import Document, validate_document
from app.presentations.templates import definition_of
from app.snapshots import audit
from app.snapshots import service as snapshots
from app.snapshots.values import canonical, sha256

logger = logging.getLogger('afrika.interpretation')

MAX_NOTES = 5
HUMAN = 'human'
_SENSITIVE_NOTE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+|https?://\S+|www\.\S+|\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-'
                             r'[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b|\b[0-9a-fA-F]{24,}\b|'
                             r'[A-Za-z0-9+/=_-]{40,}')
STALE_CODES = ('sources_changed', 'facts_changed', 'slide_missing')


def _commit(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise conflict('interpretation_conflict', 'A interpretação foi alterada por outra operação; recarregue e '
                                                  'tente de novo') from None
    except OperationalError:
        session.rollback()
        raise conflict('interpretation_conflict', 'Banco ocupado por outra gravação; tente de novo') from None


def check_notes(notes: list[str]) -> list[str]:
    if len(notes) > MAX_NOTES:
        raise ApiError(422, 'editorial_notes_too_many', f'No máximo {MAX_NOTES} notas editoriais')
    bad = [i for i, n in enumerate(notes) if _SENSITIVE_NOTE.search(n)]
    if bad:
        raise ApiError(422, 'editorial_note_sensitive', 'Nota editorial com padrão sensível (e-mail, URL, '
                                                        'identificador ou segredo): remova antes de gerar',
                       [{'field': f'notes[{i}]', 'message': 'padrão sensível', 'type': 'sensitive'} for i in bad])
    return notes


# ---------------------------------------------------------------- leitura de estado

def status_of(iv: InterpretationVersion) -> Status:
    states = [e.event for e in iv.events if e.event != 'APPLIED']
    return Status(states[-1]) if states else Status.GENERATED


def applied_events(iv: InterpretationVersion) -> list[InterpretationEvent]:
    return [e for e in iv.events if e.event == 'APPLIED']


def get(session: Session, p: Presentation, iid: uuid.UUID) -> InterpretationVersion:
    iv = session.get(InterpretationVersion, iid)
    if iv is None or iv.presentation_id != p.id:  # isolamento: nunca por outra apresentação/dono
        raise ApiError(404, 'interpretation_not_found', 'Interpretação não encontrada nesta apresentação')
    return iv


def thread(session: Session, iv: InterpretationVersion) -> list[InterpretationVersion]:
    return list(session.scalars(select(InterpretationVersion).where(
        InterpretationVersion.presentation_id == iv.presentation_id, InterpretationVersion.slide_id == iv.slide_id,
        InterpretationVersion.kind == iv.kind).order_by(InterpretationVersion.version)))


def is_latest(session: Session, iv: InterpretationVersion) -> bool:
    top = session.scalar(select(func.max(InterpretationVersion.version)).where(
        InterpretationVersion.presentation_id == iv.presentation_id, InterpretationVersion.slide_id == iv.slide_id,
        InterpretationVersion.kind == iv.kind))
    return top == iv.version


def disabled_slides(session: Session, p: Presentation) -> dict[str, dict]:
    rows = session.scalars(select(InterpretationSlideSetting).where(InterpretationSlideSetting.presentation_id == p.id)
                           .order_by(InterpretationSlideSetting.slide_id, InterpretationSlideSetting.sequence)).all()
    last: dict[str, InterpretationSlideSetting] = {}
    for r in rows:
        last[r.slide_id] = r
    return {k: {'disabled': v.disabled, 'actor': v.actor, 'reason': v.reason, 'at': v.created_at.isoformat()}
            for k, v in last.items() if v.disabled}


def used_today(session: Session) -> int:
    start = datetime.combine(utcnow().date(), time(0), tzinfo=timezone.utc)
    return session.scalar(select(func.count()).select_from(InterpretationVersion).where(
        InterpretationVersion.provider.notin_([DEFAULT_PROVIDER, HUMAN]),
        InterpretationVersion.created_at >= start)) or 0


def context_of(iv: InterpretationVersion) -> Context:
    return Context.model_validate(json.loads(iv.facts_json))


def staleness(session: Session, p: Presentation, iv: InterpretationVersion) -> list[dict]:
    """Interpretação potencialmente desatualizada: fontes aprovadas fixadas trocadas, fatos recalculados diferentes
    (snapshot/aprovação/histórico/slide mudaram) ou slide removido. Texto aplicado e depois editado à mão = informativo."""
    out = []
    current = presentations.get_revision(session, p)
    if current.sources_hash != iv.presentation_sources_hash:
        out.append({'level': 'warning', 'code': 'sources_changed',
                    'message': 'As fontes aprovadas fixadas na apresentação mudaram desde a geração (nova aprovação '
                               'ou troca explícita de fontes): gere a interpretação novamente.'})
    stored = context_of(iv)
    notes = [f['text'] for f in stored.facts if f['type'] == 'editorial']
    try:
        fresh, _ = ctx_mod.build(session, p, current, iv.slide_id, Kind(iv.kind), Level(iv.level), notes,
                                 iv.target_field)
    except ApiError as exc:
        out.append({'level': 'warning', 'code': 'slide_missing' if exc.status == 404 else 'facts_changed',
                    'message': f'O slide de destino não aceita mais esta interpretação: {exc.message}'})
    else:
        if sha256(fresh.model_dump(mode='json')) != iv.context_hash:
            out.append({'level': 'warning', 'code': 'facts_changed',
                        'message': 'Os indicadores, o histórico aprovado ou o slide mudaram desde a geração: o texto '
                                   'pode não refletir os valores atuais.'})
    latest = snapshots.latest_approval(session, p.competence_id)
    if latest is not None and str(latest.id) != json.loads(current.sources_json)['primary']['approval_id']:
        out.append({'level': 'info', 'code': 'newer_approval_available',
                    'message': f'A competência tem aprovação mais recente (sequência {latest.sequence}): a apresentação '
                               'e esta interpretação seguem na aprovação fixada até "Atualizar fontes aprovadas".'})
    if applied_events(iv):
        doc = Document.model_validate(json.loads(current.document_json))
        slide = next((s for s in doc.slides if s.slide_id == iv.slide_id), None)
        if slide is not None and _field_text(slide, iv.target_field) != iv.text:
            out.append({'level': 'info', 'code': 'applied_text_edited',
                        'message': 'O texto aplicado foi alterado depois no editor (edição manual preservada).'})
    return out


# ---------------------------------------------------------------- serialização

def out(session: Session, p: Presentation, iv: InterpretationVersion, *, with_stale: bool = True,
        detail: bool = False) -> dict:
    stale = staleness(session, p, iv) if with_stale else []
    kind, _, oid = iv.owner_key.partition(':')
    res = {'id': str(iv.id), 'presentation_id': str(iv.presentation_id),
           'owner': {'kind': kind, 'id': oid, 'client_id': str(iv.client_id),
                     'subclient_id': None if iv.subclient_id is None else str(iv.subclient_id)},
           'competence': {'id': str(iv.competence_id), 'competence': iv.competence},
           'presentation_revision': iv.presentation_revision, 'slide_id': iv.slide_id,
           'target_field': iv.target_field, 'kind': iv.kind, 'kind_name': KIND_NAMES[Kind(iv.kind)],
           'level': iv.level, 'version': iv.version, 'parent_id': None if iv.parent_id is None else str(iv.parent_id),
           'origin': iv.origin, 'text': iv.text, 'statements': json.loads(iv.statements_json),
           'provider': iv.provider, 'model': iv.model, 'prompt_version': iv.prompt_version,
           'prompt_hash': iv.prompt_hash, 'context_hash': iv.context_hash,
           'sources_hash': iv.presentation_sources_hash, 'content_hash': iv.content_hash,
           'validation': json.loads(iv.validation_json), 'valid': iv.valid, 'justification': iv.justification,
           'created_by': iv.created_by, 'created_at': iv.created_at.isoformat(), 'status': status_of(iv).value,
           'is_latest': is_latest(session, iv), 'stale': [s for s in stale if s['code'] in STALE_CODES],
           'notices': [s for s in stale if s['code'] not in STALE_CODES],
           'applied': [{'presentation_revision': e.presentation_revision, 'actor': e.actor,
                        'at': e.created_at.isoformat()} for e in applied_events(iv)],
           'events': [{'sequence': e.sequence, 'event': e.event, 'actor': e.actor, 'reason': e.reason,
                       'presentation_revision': e.presentation_revision, 'at': e.created_at.isoformat()}
                      for e in iv.events]}
    if detail:
        ctx = context_of(iv)
        res['context'] = ctx.model_dump(mode='json')
        res['indicators'] = [_indicator(f) for f in ctx.facts if f['type'] == 'metric']
        res['editorial_notes'] = [f['text'] for f in ctx.facts if f['type'] == 'editorial']
        res['history'] = [{'id': str(v.id), 'version': v.version, 'origin': v.origin, 'level': v.level,
                           'status': status_of(v).value, 'valid': v.valid, 'created_by': v.created_by,
                           'created_at': v.created_at.isoformat()} for v in thread(session, iv)]
    return res


def _indicator(f: dict) -> dict:
    """Resumo legível do fato (dados de origem exibidos ao revisor)."""
    return {'fact_id': f['id'], 'metric_id': f['metric_id'], 'name': f['name'], 'state': f['state'],
            'value_state': f['value_state'], 'origin': f['origin'], 'definitive': f['definitive'],
            'current': f['current'], 'previous': f['previous'], 'delta': f['delta'], 'delta_label': f['delta_label'],
            'delta_pct': f['delta_pct'], 'delta_unavailable_reason': f['delta_unavailable_reason'],
            'trend': f['trend'], 'provenance': f['provenance'],
            'labels_redacted': bool(f['categories'] and f['categories'].get('labels_redacted'))}


# ---------------------------------------------------------------- gravação

def _content_hash(iv: InterpretationVersion) -> str:
    return sha256({'presentation_id': str(iv.presentation_id), 'slide_id': iv.slide_id, 'kind': iv.kind,
                   'version': iv.version, 'parent_id': None if iv.parent_id is None else str(iv.parent_id),
                   'origin': iv.origin, 'level': iv.level, 'target_field': iv.target_field, 'text': iv.text,
                   'statements': iv.statements_json, 'context_hash': iv.context_hash,
                   'sources_hash': iv.presentation_sources_hash, 'presentation_revision': iv.presentation_revision,
                   'provider': iv.provider, 'model': iv.model, 'prompt_version': iv.prompt_version,
                   'prompt_hash': iv.prompt_hash, 'validation': iv.validation_json, 'justification': iv.justification,
                   'created_by': iv.created_by, 'created_at': iv.created_at.isoformat()})


def _next_version(session: Session, p: Presentation, slide_id: str, kind: str) -> int:
    top = session.scalar(select(func.max(InterpretationVersion.version)).where(
        InterpretationVersion.presentation_id == p.id, InterpretationVersion.slide_id == slide_id,
        InterpretationVersion.kind == kind))
    return (top or 0) + 1


def _event(session: Session, iv: InterpretationVersion, event: str, actor: str, reason: str | None = None,
           presentation_revision: int | None = None) -> None:
    seq = (max((e.sequence for e in iv.events), default=0)) + 1
    ev = InterpretationEvent(interpretation_id=iv.id, sequence=seq, event=event, actor=actor, reason=reason,
                             presentation_revision=presentation_revision, created_at=utcnow())
    session.add(ev)
    iv.events.append(ev)
    session.flush()


def _audit(session: Session, p: Presentation, iv: InterpretationVersion, event: str, actor: str, **extra) -> None:
    r = presentations.get_revision(session, p, iv.presentation_revision)
    audit.append(session, event, owner_key=p.owner_key, competence_id=p.competence_id,
                 revision_id=r.primary_revision_id, actor=actor,
                 details={'presentation_id': str(p.id), 'interpretation_id': str(iv.id), 'slide_id': iv.slide_id,
                          'kind': iv.kind, 'level': iv.level, 'version': iv.version, 'origin': iv.origin,
                          'provider': iv.provider, 'context_hash': iv.context_hash, 'content_hash': iv.content_hash,
                          'valid': iv.valid, **extra})


def _store(session: Session, p: Presentation, r: PresentationRevision, ctx: Context, *, slide_id: str, field: str,
           statements: list[Statement], validation: dict, origin: Origin, provider: str, model: str | None,
           prompt_hash: str, operator: str, parent: InterpretationVersion | None,
           justification: str | None = None) -> InterpretationVersion:
    iv = InterpretationVersion(
        presentation_id=p.id, owner_key=p.owner_key, client_id=p.client_id, subclient_id=p.subclient_id,
        competence_id=p.competence_id, competence=ctx.competence, presentation_revision=r.number,
        presentation_sources_hash=r.sources_hash, slide_id=slide_id, target_field=field, kind=ctx.kind.value,
        level=ctx.level.value, version=_next_version(session, p, slide_id, ctx.kind.value),
        parent_id=None if parent is None else parent.id, origin=origin.value,
        text=validate.join([s.text for s in statements], field),
        statements_json=canonical([s.model_dump() for s in statements]),
        facts_json=canonical(ctx.model_dump(mode='json')),
        editorial_json=canonical([f['text'] for f in ctx.facts if f['type'] == 'editorial']),
        provider=provider, model=model, prompt_version=ctx.prompt_version, prompt_hash=prompt_hash,
        context_hash=sha256(ctx.model_dump(mode='json')), validation_json=canonical(validation),
        valid=validation['valid'], justification=justification, created_by=operator, created_at=utcnow(),
        content_hash='')
    iv.content_hash = _content_hash(iv)
    session.add(iv)
    session.flush()
    return iv


def _provider(session: Session, settings: InterpretationSettings, name: str | None, labels: str):
    try:
        return providers.resolve(settings, name, lambda: used_today(session), labels)
    except providers.ProviderError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from None


def default_kind(session: Session, p: Presentation, slide_id: str) -> Kind:
    doc = Document.model_validate(json.loads(presentations.get_revision(session, p).document_json))
    slide = next((s for s in doc.slides if s.slide_id == slide_id), None)
    if slide is None:
        raise ApiError(404, 'interpretation_slide_not_found', 'Slide inexistente na revisão da apresentação')
    kinds = KINDS_BY_SLIDE.get(slide.type, ())
    if not kinds:
        raise ApiError(422, 'interpretation_kind_not_applicable', 'Este tipo de slide não recebe interpretação')
    return kinds[0]


def _ensure_enabled(session: Session, p: Presentation, slide_id: str) -> None:
    if slide_id in disabled_slides(session, p):
        raise conflict('interpretation_disabled', 'Interpretação desabilitada para este slide (reabilite para gerar)')


def preview(session: Session, settings: InterpretationSettings, p: Presentation, *, slide_id: str,
            kind: Kind | None, level: Level, notes: list[str], provider: str | None,
            target_field: str | None = None) -> dict:
    """Contexto que SERIA usado e o que SERIA transmitido (nada é gravado nem enviado)."""
    check_notes(notes)
    r = presentations.get_revision(session, p)
    kind = kind or default_kind(session, p, slide_id)
    ctx, meta = ctx_mod.build(session, p, r, slide_id, kind, level, notes, target_field)
    prov = _provider(session, settings, provider, meta['severity_labels'])
    return {'context': ctx.model_dump(mode='json'), 'context_hash': sha256(ctx.model_dump(mode='json')),
            'target_field': meta['field'], 'provider': prov.name, 'external': prov.external,
            'transmission': prov.preview(ctx), 'presentation_revision': r.number}


def generate(session: Session, settings: InterpretationSettings, p: Presentation, *, slide_id: str,
             kind: Kind | None, level: Level, notes: list[str], operator: str, provider: str | None = None,
             consent: bool = False, target_field: str | None = None,
             parent: InterpretationVersion | None = None) -> InterpretationVersion:
    _ensure_enabled(session, p, slide_id)
    check_notes(notes)
    r = presentations.get_revision(session, p)  # SEMPRE a revisão persistida (nunca rascunho do editor)
    kind = kind or default_kind(session, p, slide_id)
    ctx, meta = ctx_mod.build(session, p, r, slide_id, kind, level, notes, target_field)
    prov = _provider(session, settings, provider, meta['severity_labels'])
    try:
        result = prov.generate(ctx, consent=consent)
    except providers.ProviderError as exc:
        logger.warning('interpretação não gerada: provedor=%s código=%s', prov.name, exc.code)
        raise ApiError(exc.status, exc.code, exc.message) from None
    except Exception:  # noqa: BLE001 — falha inesperada do provedor não derruba o editor nem vaza conteúdo
        logger.warning('interpretação não gerada: provedor=%s código=provider_failed', prov.name)
        raise ApiError(502, 'provider_failed', 'Falha do provedor de interpretação') from None
    validation = validate.validate(ctx, result.statements, origin=Origin.GENERATED, budget=meta['budget'])
    iv = _store(session, p, r, ctx, slide_id=slide_id, field=meta['field'], statements=result.statements,
                validation=validation, origin=Origin.GENERATED, provider=result.provider, model=result.model,
                prompt_hash=providers.prompt_hash(ctx), operator=operator, parent=parent)
    _event(session, iv, Status.GENERATED.value, operator)
    _audit(session, p, iv, 'interpretation.generated', operator, external=prov.external,
           regenerated_from=None if parent is None else str(parent.id))
    _commit(session)
    logger.info('interpretação gerada: apresentação=%s slide=%s tipo=%s versão=%d válida=%s', p.id, slide_id,
                kind.value, iv.version, iv.valid)
    return iv


def _require_latest(session: Session, iv: InterpretationVersion) -> None:
    if not is_latest(session, iv):
        raise conflict('interpretation_superseded', 'Há uma versão mais recente desta interpretação: revise a última')


def regenerate(session: Session, settings: InterpretationSettings, p: Presentation, iv: InterpretationVersion, *,
               operator: str, level: Level | None, notes: list[str] | None, provider: str | None,
               consent: bool) -> InterpretationVersion:
    _require_latest(session, iv)
    stored = [f['text'] for f in context_of(iv).facts if f['type'] == 'editorial']
    return generate(session, settings, p, slide_id=iv.slide_id, kind=Kind(iv.kind), level=level or Level(iv.level),
                    notes=stored if notes is None else notes, operator=operator, provider=provider, consent=consent,
                    target_field=iv.target_field, parent=iv)


def _split(text: str, field: str) -> list[str]:
    if field == 'items':
        return [line.strip() for line in text.splitlines() if line.strip()]
    return [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]


def edit(session: Session, p: Presentation, iv: InterpretationVersion, *, text: str, operator: str,
         justification: str | None) -> InterpretationVersion:
    """Edição humana = nova versão (autoria declarada, justificativa opcional), revalidada contra os MESMOS fatos da
    versão de origem; entra direto em revisão (IN_REVIEW)."""
    _require_latest(session, iv)
    _ensure_enabled(session, p, iv.slide_id)
    ctx = context_of(iv)
    ids = [f['id'] for f in ctx.facts]
    statements = [Statement(text=t, fact_ids=ids) for t in _split(text, iv.target_field)]
    if not statements:
        raise ApiError(422, 'interpretation_text_empty', 'Texto vazio')
    if [s.text for s in statements] == [s['text'] for s in json.loads(iv.statements_json)]:
        raise conflict('interpretation_unchanged', 'Texto igual ao da versão atual')
    budget = budget_for(SlideType(ctx.slide['type']), ctx.slide['layout'], iv.target_field)
    validation = validate.validate(ctx, statements, origin=Origin.EDITED, budget=budget, justification=justification)
    r = presentations.get_revision(session, p, iv.presentation_revision)
    new = _store(session, p, r, ctx, slide_id=iv.slide_id, field=iv.target_field, statements=statements,
                 validation=validation, origin=Origin.EDITED, provider=HUMAN, model=None, prompt_hash=iv.prompt_hash,
                 operator=operator, parent=iv, justification=justification)
    _event(session, new, Status.IN_REVIEW.value, operator, reason='Edição manual')
    _audit(session, p, new, 'interpretation.edited', operator, edited_from=str(iv.id),
           justified=justification is not None)
    _commit(session)
    return new


_TRANSITIONS = {Status.IN_REVIEW: {Status.GENERATED}, Status.APPROVED: {Status.IN_REVIEW},
                Status.REJECTED: {Status.GENERATED, Status.IN_REVIEW}}


def transition(session: Session, p: Presentation, iv: InterpretationVersion, to: Status, operator: str,
               reason: str | None) -> InterpretationVersion:
    _require_latest(session, iv)
    current = status_of(iv)
    if current not in _TRANSITIONS[to]:
        raise conflict('interpretation_invalid_transition', f'Transição inválida: {current.value} → {to.value}')
    if to is Status.REJECTED and not (reason or '').strip():
        raise ApiError(422, 'interpretation_reason_required', 'Informe o motivo da rejeição')
    if to is Status.APPROVED:
        if not iv.valid:
            raise conflict('interpretation_not_valid', 'A validação automática encontrou bloqueios: corrija (edição '
                                                       'ou regeneração) antes de aprovar')
        stale = [s for s in staleness(session, p, iv) if s['code'] in STALE_CODES]
        if stale:
            raise conflict('interpretation_stale', 'Interpretação desatualizada: ' + ' '.join(s['message']
                                                                                             for s in stale))
    _event(session, iv, to.value, operator, reason=reason)
    _audit(session, p, iv, f'interpretation.{to.value.lower()}', operator)
    _commit(session)
    return iv


def _field_text(slide, field: str) -> str:
    value = getattr(slide.fields, field)
    if field == 'items':
        return '\n'.join(value)
    return value or ''


def apply(session: Session, p: Presentation, iv: InterpretationVersion, *, operator: str, expected: int,
          overwrite_confirmed: bool) -> int:
    """Grava o texto APROVADO no campo do slide como nova revisão da apresentação (mesma transação do evento)."""
    if status_of(iv) is not Status.APPROVED:
        raise conflict('interpretation_not_approved', 'Só interpretações APROVADAS por revisão humana entram no slide')
    _require_latest(session, iv)
    stale = [s for s in staleness(session, p, iv) if s['code'] in STALE_CODES]
    if stale:
        raise conflict('interpretation_stale', 'Interpretação desatualizada: ' + ' '.join(s['message'] for s in stale))
    current = presentations.get_revision(session, p)
    doc = Document.model_validate(json.loads(current.document_json))
    slide = next((s for s in doc.slides if s.slide_id == iv.slide_id), None)
    if slide is None:
        raise conflict('interpretation_slide_missing', 'O slide de destino não existe mais na apresentação')
    existing = _field_text(slide, iv.target_field)
    if existing == iv.text:
        raise conflict('interpretation_already_applied', 'O slide já contém este texto')
    if existing.strip() and not overwrite_confirmed:
        raise ApiError(409, 'interpretation_overwrite_requires_confirmation',
                       'O campo do slide já tem texto (possivelmente revisado): confirme a substituição explícita',
                       [{'field': iv.target_field, 'message': existing[:500], 'type': 'existing_text'}])
    if iv.target_field == 'items':
        slide.fields.items = [s['text'] for s in json.loads(iv.statements_json)]
    else:
        setattr(slide.fields, iv.target_field, iv.text)
    tmpl = presentations.template_of(session, p)
    validate_document(doc, definition_of(tmpl))
    presentations._advance(session, p, expected, doc.title)
    r = presentations._add_revision(session, p, expected + 1, doc, json.loads(current.sources_json), operator,
                                    f'Interpretação aprovada aplicada: {KIND_NAMES[Kind(iv.kind)]} '
                                    f'(v{iv.version}) no slide {iv.slide_id}', current)
    presentations._audit(session, p, r, 'presentation.saved', operator, interpretation_id=str(iv.id))
    _event(session, iv, 'APPLIED', operator, reason='Aplicada ao slide', presentation_revision=r.number)
    _audit(session, p, iv, 'interpretation.applied', operator, presentation_revision=r.number,
           overwrite=bool(existing.strip()))
    _commit(session)
    session.refresh(p)
    return r.number


def set_disabled(session: Session, p: Presentation, slide_id: str, disabled: bool, operator: str,
                 reason: str | None) -> dict:
    doc = Document.model_validate(json.loads(presentations.get_revision(session, p).document_json))
    if all(s.slide_id != slide_id for s in doc.slides):
        raise ApiError(404, 'interpretation_slide_not_found', 'Slide inexistente na revisão da apresentação')
    seq = (session.scalar(select(func.max(InterpretationSlideSetting.sequence)).where(
        InterpretationSlideSetting.presentation_id == p.id, InterpretationSlideSetting.slide_id == slide_id)) or 0) + 1
    session.add(InterpretationSlideSetting(presentation_id=p.id, slide_id=slide_id, sequence=seq, disabled=disabled,
                                           actor=operator, reason=reason, created_at=utcnow()))
    r = presentations.get_revision(session, p)
    audit.append(session, 'interpretation.slide_disabled' if disabled else 'interpretation.slide_enabled',
                 owner_key=p.owner_key, competence_id=p.competence_id, revision_id=r.primary_revision_id,
                 actor=operator, details={'presentation_id': str(p.id), 'slide_id': slide_id})
    _commit(session)
    return disabled_slides(session, p)


def list_for(session: Session, p: Presentation) -> dict:
    rows = session.scalars(select(InterpretationVersion).where(InterpretationVersion.presentation_id == p.id)
                           .order_by(InterpretationVersion.slide_id, InterpretationVersion.kind,
                                     InterpretationVersion.version)).all()
    latest: dict[tuple[str, str], InterpretationVersion] = {}
    for iv in rows:
        latest[(iv.slide_id, iv.kind)] = iv
    keep = {iv.id for iv in latest.values()}
    return {'items': [out(session, p, iv, with_stale=iv.id in keep) for iv in rows],
            'disabled_slides': disabled_slides(session, p)}


def compare(a: InterpretationVersion, b: InterpretationVersion) -> dict:
    """Diferença por palavra entre duas versões da MESMA linha (presentação, slide, tipo)."""
    if (a.presentation_id, a.slide_id, a.kind) != (b.presentation_id, b.slide_id, b.kind):
        raise ApiError(422, 'interpretation_compare_mismatch', 'Compare versões da mesma interpretação')
    wa, wb = a.text.split(), b.text.split()
    ops = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=wa, b=wb, autojunk=False).get_opcodes():
        ops.append({'op': tag, 'from': ' '.join(wa[i1:i2]), 'to': ' '.join(wb[j1:j2])})
    return {'from': {'id': str(a.id), 'version': a.version, 'text': a.text},
            'to': {'id': str(b.id), 'version': b.version, 'text': b.text}, 'diff': ops,
            'same_facts': a.context_hash == b.context_hash}
