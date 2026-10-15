"""Persistência das apresentações (F06A): criação a partir de revisão APROVADA, revisões editoriais append-only,
troca explícita de fontes e verificação de integridade.

- Criar exige revisão aprovada da competência (padrão: a oficial). Rascunho/em revisão => 409.
- Salvar = nova revisão (documento validado contra o template), com concorrência otimista (`expected_revision`).
  Nada aqui escreve em snapshots/aprovações da F05: correção de indicador = nova revisão da competência (F05).
- Cada revisão guarda hash do documento, das fontes fixadas e o hash encadeado com a anterior.
"""
from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.errors import ApiError, conflict
from app.orm import (
    Approval, Competence, CompetenceRevision, Presentation, PresentationRevision, PresentationTemplate,
    RevisionStatus, utcnow,
)
from app.presentations import templates, view
from app.presentations.document import Document, initial_document, validate_document
from app.scopes import store
from app.snapshots import audit, service as snapshots
from app.snapshots.values import canonical, sha256, snapshot_hash

logger = logging.getLogger('afrika.presentations')


def _commit(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        reason = str(exc.orig) if exc.orig is not None else ''
        code = 'presentation_source_not_approved' if 'presentation_source_not_approved' in reason \
            else 'presentation_conflict'
        raise conflict(code, 'Operação recusada: a apresentação foi alterada por outra operação ou a fonte não '
                             'está aprovada (recarregue e tente de novo)') from None
    except OperationalError:
        session.rollback()
        raise conflict('presentation_conflict', 'Banco ocupado por outra gravação; tente de novo') from None


def get(session: Session, pid: uuid.UUID) -> Presentation:
    p = session.get(Presentation, pid)
    if p is None:
        raise ApiError(404, 'presentation_not_found', 'Apresentação não encontrada')
    return p


def template_of(session: Session, p: Presentation) -> PresentationTemplate:
    return session.get(PresentationTemplate, p.template_id)


def get_revision(session: Session, p: Presentation, number: int | None = None) -> PresentationRevision:
    number = number or p.current_revision
    r = session.scalar(select(PresentationRevision).where(PresentationRevision.presentation_id == p.id,
                                                          PresentationRevision.number == number))
    if r is None:
        raise ApiError(404, 'presentation_revision_not_found', 'Revisão da apresentação não encontrada')
    return r


def _approved_source(session: Session, comp: Competence, number: int | None) -> tuple[CompetenceRevision, Approval]:
    if number is None:
        appr = snapshots.latest_approval(session, comp.id)
        if appr is None:
            raise conflict('no_approved_revision', 'A competência não tem revisão aprovada: aprove-a na F05 '
                                                   '(Competências) antes de montar a apresentação')
        return session.get(CompetenceRevision, appr.revision_id), appr
    rev = snapshots.get_revision(session, comp, number)
    if rev.status != RevisionStatus.APPROVED.value:
        raise conflict('revision_not_approved', 'Apresentações só usam revisões APROVADAS (rascunhos e revisões em '
                                                'análise são recusados)')
    return rev, session.scalar(select(Approval).where(Approval.revision_id == rev.id))


def _hashes(doc_obj: dict, sources: dict) -> tuple[str, str]:
    return sha256(doc_obj), sha256(sources)


def revision_hash(p: Presentation, r: PresentationRevision, template_hash: str) -> str:
    return sha256({'presentation': str(p.id), 'number': r.number, 'previous': r.previous_hash,
                   'document_hash': r.document_hash, 'sources_hash': r.sources_hash,
                   'template_id': str(p.template_id), 'template_hash': template_hash,
                   'primary_revision_id': str(r.primary_revision_id),
                   'primary_approval_id': str(r.primary_approval_id), 'created_by': r.created_by,
                   'created_at': r.created_at.isoformat(), 'summary': r.change_summary})


def _add_revision(session: Session, p: Presentation, number: int, doc: Document, sources: dict, operator: str,
                  summary: str, previous: PresentationRevision | None) -> PresentationRevision:
    doc_obj = doc.model_dump(mode='json')
    doc_hash, src_hash = _hashes(doc_obj, sources)
    r = PresentationRevision(presentation_id=p.id, number=number, document_json=canonical(doc_obj),
                             document_hash=doc_hash, sources_json=canonical(sources), sources_hash=src_hash,
                             primary_revision_id=uuid.UUID(sources['primary']['revision_id']),
                             primary_approval_id=uuid.UUID(sources['primary']['approval_id']),
                             change_summary=summary, previous_hash=None if previous is None else previous.revision_hash,
                             created_by=operator, created_at=utcnow(), revision_hash='')
    tmpl = session.get(PresentationTemplate, p.template_id)
    r.revision_hash = revision_hash(p, r, tmpl.definition_hash)
    session.add(r)
    session.flush()
    return r


def _audit(session: Session, p: Presentation, r: PresentationRevision, event: str, operator: str, **extra) -> None:
    audit.append(session, event, owner_key=p.owner_key, competence_id=p.competence_id,
                 revision_id=r.primary_revision_id, actor=operator,
                 details={'presentation_id': str(p.id), 'presentation_revision': r.number,
                          'document_hash': r.document_hash, 'sources_hash': r.sources_hash, **extra})


# ---------------------------------------------------------------- criação, edição e fontes

def create(session: Session, competence_id: uuid.UUID, operator: str, *, revision: int | None = None,
           template_key: str | None = None, template_version: int | None = None,
           title: str | None = None) -> Presentation:
    comp = snapshots.get_competence(session, competence_id)
    rev, appr = _approved_source(session, comp, revision)
    kind, _, oid = comp.owner_key.partition(':')
    owner = store.get_owner(session, kind, uuid.UUID(oid))
    if template_key:
        tmpl = templates.get(session, template_key, template_version)
    else:
        tmpl = templates.resolve_for_owner(session, owner)
        if tmpl is None:
            raise conflict('template_required', 'Escolha um template para este cliente/subcliente (ou informe um)')
    defn = templates.definition_of(tmpl)
    doc = initial_document(defn, title or f'{defn.name} — {owner.name} — {comp.label}')
    validate_document(doc, defn)
    p = Presentation(owner_key=comp.owner_key, client_id=comp.client_id, subclient_id=comp.subclient_id,
                     competence_id=comp.id, template_id=tmpl.id, title=doc.title, current_revision=1,
                     created_by=operator)
    session.add(p)
    session.flush()
    r = _add_revision(session, p, 1, doc, view.pin_sources(session, comp, rev, appr), operator,
                      'Criada a partir do template', None)
    _audit(session, p, r, 'presentation.created', operator, template=tmpl.template_key, template_version=tmpl.version,
           competence_revision=rev.number, content_hash=appr.content_hash)
    _commit(session)
    logger.info('apresentação criada dono=%s competência=%s template=%s@%s', comp.owner_key, comp.label,
                tmpl.template_key, tmpl.version)
    return p


def _advance(session: Session, p: Presentation, expected: int, title: str) -> None:
    if p.current_revision != expected:
        raise conflict('presentation_conflict', f'A apresentação está na revisão {p.current_revision}, não '
                                                f'{expected}: recarregue antes de salvar')
    res = session.execute(update(Presentation).where(Presentation.id == p.id,
                                                     Presentation.current_revision == expected)
                          .values(current_revision=expected + 1, title=title, updated_at=utcnow()))
    if res.rowcount != 1:
        session.rollback()
        raise conflict('presentation_conflict', 'A apresentação foi alterada por outra operação; recarregue')


def save(session: Session, p: Presentation, doc: Document, operator: str, expected: int, summary: str) -> None:
    tmpl = session.get(PresentationTemplate, p.template_id)
    validate_document(doc, templates.definition_of(tmpl))
    current = get_revision(session, p)
    sources = json.loads(current.sources_json)
    if sha256(doc.model_dump(mode='json')) == current.document_hash:
        raise conflict('presentation_unchanged', 'Nenhuma alteração em relação à revisão atual')
    _advance(session, p, expected, doc.title)
    r = _add_revision(session, p, expected + 1, doc, sources, operator, summary, current)
    _audit(session, p, r, 'presentation.saved', operator)
    _commit(session)
    session.refresh(p)


def rebind(session: Session, p: Presentation, operator: str, expected: int, revision: int | None = None) -> dict:
    """Troca EXPLÍCITA das fontes para a aprovação oficial (ou outra revisão aprovada) — nova revisão."""
    comp = session.get(Competence, p.competence_id)
    rev, appr = _approved_source(session, comp, revision)
    current = get_revision(session, p)
    old = json.loads(current.sources_json)
    sources = view.pin_sources(session, comp, rev, appr)
    if sha256(sources) == current.sources_hash:
        raise conflict('sources_unchanged', 'As fontes fixadas já são as aprovações vigentes')
    doc = Document.model_validate(json.loads(current.document_json))
    _advance(session, p, expected, doc.title)
    r = _add_revision(session, p, expected + 1, doc, sources, operator, 'Fontes aprovadas atualizadas', current)
    changed = sorted(lbl for lbl in {*old.get('history', {}), *sources['history']}
                     if old.get('history', {}).get(lbl, {}).get('approval_id')
                     != sources['history'].get(lbl, {}).get('approval_id'))
    _audit(session, p, r, 'presentation.sources_rebound', operator,
           previous_primary=old['primary']['approval_id'], primary=sources['primary']['approval_id'],
           history_changed=changed)
    _commit(session)
    session.refresh(p)
    return {'primary_changed': old['primary']['approval_id'] != sources['primary']['approval_id'],
            'history_changed': changed}


# ---------------------------------------------------------------- leitura

def revision_summary(r: PresentationRevision) -> dict:
    src = json.loads(r.sources_json)['primary']
    return {'number': r.number, 'created_by': r.created_by, 'created_at': r.created_at.isoformat(),
            'change_summary': r.change_summary, 'document_hash': r.document_hash, 'sources_hash': r.sources_hash,
            'revision_hash': r.revision_hash, 'source_revision': src['revision'],
            'source_approval_sequence': src['approval_sequence'], 'source_content_hash': src['content_hash']}


def presentation_out(session: Session, p: Presentation) -> dict:
    tmpl = session.get(PresentationTemplate, p.template_id)
    comp = session.get(Competence, p.competence_id)
    kind, _, oid = p.owner_key.partition(':')
    return {'id': str(p.id), 'title': p.title, 'owner': {'kind': kind, 'id': oid, 'key': p.owner_key},
            'competence': {'id': str(comp.id), 'competence': comp.label},
            'template': templates.template_out(tmpl), 'current_revision': p.current_revision,
            'created_by': p.created_by, 'created_at': p.created_at.isoformat(),
            'updated_at': p.updated_at.isoformat(), 'revisions': [revision_summary(r) for r in p.revisions]}


def revision_out(p: Presentation, r: PresentationRevision) -> dict:
    return {'presentation_id': str(p.id), **revision_summary(r), 'document': json.loads(r.document_json),
            'sources': json.loads(r.sources_json), 'is_current': r.number == p.current_revision}


def list_for_owner(session: Session, kind: str, owner_id: uuid.UUID) -> list[dict]:
    owner = store.get_owner(session, kind, owner_id)
    rows = session.scalars(select(Presentation).where(Presentation.owner_key == owner.key)
                           .order_by(Presentation.updated_at.desc())).all()
    return [presentation_out(session, p) for p in rows]


# ---------------------------------------------------------------- integridade

def verify(session: Session, p: Presentation) -> dict:
    problems: list[str] = []
    tmpl = session.get(PresentationTemplate, p.template_id)
    if templates.definition_hash(templates.definition_of(tmpl)) != tmpl.definition_hash:
        problems.append('template: definição divergente do hash registrado')
    prev = None
    for r in p.revisions:
        doc_hash, src_hash = _hashes(json.loads(r.document_json), json.loads(r.sources_json))
        if doc_hash != r.document_hash:
            problems.append(f'revisão {r.number}: documento divergente do hash')
        if src_hash != r.sources_hash:
            problems.append(f'revisão {r.number}: fontes divergentes do hash')
        if r.previous_hash != prev or r.revision_hash != revision_hash(p, r, tmpl.definition_hash):
            problems.append(f'revisão {r.number}: cadeia de hash divergente')
        prev = r.revision_hash
    if p.current_revision != (p.revisions[-1].number if p.revisions else 0):
        problems.append('ponteiro da revisão atual divergente')
    current = get_revision(session, p)
    sources = json.loads(current.sources_json)
    entries, ref_problems = view.load_entries(session, sources)
    problems += ref_problems
    checked = []
    for label, (comp, rev, appr) in sorted(entries.items()):
        bad = [s.metric_id for s in rev.snapshots if s.row_hash != snapshot_hash(s)]
        content_ok = snapshots.content_hash(comp, rev) == appr.content_hash
        problems += [f'{label}: snapshot {m} divergente do hash' for m in bad]
        if not content_ok:
            problems.append(f'{label}: conteúdo aprovado divergente')
        checked.append({'competence': label, 'revision': rev.number, 'approval_sequence': appr.sequence,
                        'content_ok': content_ok, 'snapshot_hash_mismatches': bad})
    return {'ok': not problems, 'problems': problems, 'revisions_checked': len(p.revisions),
            'sources_checked': checked}
