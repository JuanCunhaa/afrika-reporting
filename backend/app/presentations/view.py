"""Modelo de visualização (F06A): documento editorial + revisões APROVADAS fixadas -> slides resolvidos com IR.

- Fonte única: as revisões aprovadas fixadas na revisão da apresentação (`sources`): a principal (competência da
  apresentação) e as aprovações de até 11 meses anteriores vigentes no momento da fixação. Nada é consultado na
  Veracode e nada é recalculado: os valores são lidos dos snapshots aprovados tal como gravados.
- Competência sem aprovação fixada = LACUNA; indicador ausente = MISSING; versão de contrato fora do template =
  INCOMPATIBLE (valor não exibido). Valor manual é identificado como manual.
- Aprovação mais nova para a mesma competência (ou para um mês do histórico) gera aviso: a troca de fonte é uma ação
  explícita (`rebind`), registrada como nova revisão da apresentação.
"""
from __future__ import annotations

import json
import uuid

from sqlalchemy.orm import Session

from app.metrics.registry import REGISTRY
from app.orm import Approval, Competence, CompetenceRevision, Presentation, PresentationRevision, PresentationTemplate
from app.presentations import brand_assets, charts
from app.presentations.catalog import DASHBOARD_LAYOUTS, SLIDE_TYPES, SlideType, ZoneKind
from app.presentations.document import Document, Slide, TemplateDefinition, Zone, all_metrics, contract_versions
from app.presentations.templates import definition_of, template_out
from app.presentations import themes
from app.scopes import store
from app.snapshots import history, service
from app.snapshots.values import headline, loads, value_state

HISTORY_MONTHS = 12


def shift(label: str, months: int) -> str:
    return history._shift(label, months)  # mesma aritmética de meses da F05


# ---------------------------------------------------------------- fixação das fontes

def source_ref(comp: Competence, rev: CompetenceRevision, appr: Approval) -> dict:
    return {'competence_id': str(comp.id), 'competence': comp.label, 'revision_id': str(rev.id),
            'revision': rev.number, 'approval_id': str(appr.id), 'approval_sequence': appr.sequence,
            'content_hash': appr.content_hash, 'chain_hash': appr.chain_hash}


def pin_sources(session: Session, comp: Competence, rev: CompetenceRevision, appr: Approval) -> dict:
    labels = history.month_range(shift(comp.label, -(HISTORY_MONTHS - 1)), shift(comp.label, -1))
    official = history.official(session, comp.owner_key, labels)
    return {'policy': 'APPROVED_ONLY_PINNED', 'primary': source_ref(comp, rev, appr),
            'history_window': {'start': labels[0], 'end': comp.label},
            'history': {label: source_ref(*official[label]) for label in labels if label in official}}


def load_entries(session: Session, sources: dict) -> tuple[dict[str, tuple], list[str]]:
    """label -> (competência, revisão, aprovação) para as referências fixadas; problemas de referência à parte."""
    entries, problems = {}, []
    refs = {sources['primary']['competence']: sources['primary'], **sources.get('history', {})}
    for label, ref in refs.items():
        comp = session.get(Competence, uuid.UUID(ref['competence_id']))
        rev = session.get(CompetenceRevision, uuid.UUID(ref['revision_id']))
        appr = session.get(Approval, uuid.UUID(ref['approval_id']))
        if comp is None or rev is None or appr is None or appr.revision_id != rev.id or rev.competence_id != comp.id:
            problems.append(f'{label}: referência fixada inexistente ou inconsistente')
            continue
        if appr.content_hash != ref['content_hash'] or rev.status != 'APPROVED':
            problems.append(f'{label}: aprovação fixada divergente do registro')
            continue
        entries[label] = (comp, rev, appr)
    return entries, problems


# ---------------------------------------------------------------- resolução de um indicador

def resolve(entries: dict, label: str, metric_id: str, versions: list[int]) -> dict:
    c = REGISTRY.get(metric_id)
    out = {'metric_id': metric_id, 'name': c.name if c else metric_id, 'competence': label, 'value': None,
           'headline': None, 'value_type': None, 'unit': c.unit.value if c else None, 'contract_version': None,
           'value_state': None, 'origin': None, 'approval': None, 'source_name': None}
    entry = entries.get(label)
    if entry is None:
        return {**out, 'state': 'GAP'}
    comp, rev, appr = entry
    out['approval'] = {'revision': rev.number, 'sequence': appr.sequence, 'content_hash': appr.content_hash,
                       'approver': appr.approver, 'identity_mode': appr.identity_mode,
                       'approved_at': appr.approved_at.isoformat()}
    snap = next((s for s in rev.snapshots if s.metric_id == metric_id), None)
    if snap is None:
        return {**out, 'state': 'MISSING', 'value_state': 'MISSING'}
    value = loads(snap.value_json)
    out.update(value_type=snap.value_type, unit=snap.unit, contract_version=snap.contract_version,
               value_state=value_state(snap.origin, value, snap.source_status).value, origin=snap.origin,
               source_name=snap.source_name)
    if snap.contract_version not in versions:
        return {**out, 'state': 'INCOMPATIBLE'}
    if value is None:
        return {**out, 'state': 'MISSING'}
    h = headline(snap.value_type, value)
    return {**out, 'value': value, 'headline': h, 'state': 'VALUE' if h is not None else 'NOT_NUMERIC',
            'summary': None if h is not None else 'distribuição — ver dados de origem'}


# ---------------------------------------------------------------- slides

def period_label(period: dict) -> str:
    """'01/09/2026 a 30/09/2026' a partir do período da competência (datas locais do fuso da competência)."""
    def br(iso: str) -> str:
        return f'{iso[8:10]}/{iso[5:7]}/{iso[0:4]}'
    return f"{br(period['period_start'])} a {br(period['period_end_inclusive'])}"


def _zone_data(zid: str, z: Zone, slide: Slide, entries: dict, label: str, vers: dict,
               labels: str = 'veracode') -> tuple[dict, list[dict]]:
    """IR de uma zona do painel composto, com os MESMOS construtores dos slides simples (nada é recalculado)."""
    spec = DASHBOARD_LAYOUTS[slide.layout][zid]
    points = [resolve(entries, label, m, vers[m]) for m in z.metrics]
    data: dict | None = None
    k = spec.kind
    if k is ZoneKind.TEXT:
        data = None
    elif k in (ZoneKind.KPI_BAND,):
        data = charts.kpis(points) if points else None
    elif k in (ZoneKind.KPI_CARDS, ZoneKind.COMPARISON):
        prev = shift(label, -1)
        data = charts.comparison([(p, resolve(entries, prev, p['metric_id'], vers[p['metric_id']])) for p in points])
    elif k in (ZoneKind.SEVERITY_CARDS, ZoneKind.DONUT):
        data = charts.severity(points[0], labels=labels)
    elif k is ZoneKind.RANKING:
        data = charts.ranking(points[0], top_n=z.top_n or 10, labels=labels)
    elif k is ZoneKind.TABLE:
        data = charts.table(points)
    elif k is ZoneKind.CHART:
        chart = z.chart or spec.charts[0]
        if chart in ('line', 'combo') or z.data_mode == 'history':
            labels = history.month_range(shift(label, -((z.months or 6) - 1)), label)
            series = [[resolve(entries, lbl, m, vers[m]) for lbl in labels] for m in z.metrics]
            data = charts.monthly(chart, series, labels, show_legend=True)
            data['show_values'] = True
        else:
            data = charts.bar_categories(points[0], labels=labels)
    return {'zone': zid, 'kind': k.value, 'name': spec.name, 'title': z.title, 'text_field': spec.text_field,
            'chart': z.chart, 'metrics': list(z.metrics), 'data': data}, points


def _slide_data(slide: Slide, entries: dict, label: str, defn: TemplateDefinition, doc: Document,
                owner: store.Owner, comp: Competence) -> tuple[dict | None, list[dict]]:
    o, f = slide.options, slide.fields
    vers = {m: contract_versions(defn, m) for m in all_metrics(slide)}
    points = [resolve(entries, label, m, vers[m]) for m in slide.metrics]
    t = slide.type
    if t is SlideType.DASHBOARD:
        zones, pts = {}, []
        for zid in DASHBOARD_LAYOUTS[slide.layout]:
            if zid in slide.zones:
                zones[zid], zp = _zone_data(zid, slide.zones[zid], slide, entries, label, vers, doc.severity_labels)
                pts += zp
        return {'kind': 'dashboard', 'layout': slide.layout, 'zones': zones}, pts
    if t is SlideType.SECTION:
        return {'kind': 'section', 'owner': owner.name, 'competence': comp.label}, points
    if t in (SlideType.COVER, SlideType.CLOSING):
        data = {'kind': 'cover' if t is SlideType.COVER else 'closing', 'owner': owner.name,
                'owner_kind': owner.kind, 'competence': comp.label, 'period': service.period(comp),
                'period_label': period_label(service.period(comp)),
                'presenters': [p.model_dump() for p in doc.presenters] if o.show_presenters else []}
    elif t is SlideType.RECOMMENDATIONS:
        data = None
    elif t in (SlideType.KPIS, SlideType.EXECUTIVE_SUMMARY):
        data = charts.kpis(points) if points else None
    elif t is SlideType.MONTH_COMPARISON:
        prev = shift(label, -1)
        data = charts.comparison([(p, resolve(entries, prev, p['metric_id'], vers[p['metric_id']]))
                                  for p in points], f.chart_title)
    elif t is SlideType.LINE_CHART or (t is SlideType.BAR_CHART and o.data_mode == 'history'):
        labels = history.month_range(shift(label, -((o.months or 6) - 1)), label)
        series = [[resolve(entries, lbl, m, vers[m]) for lbl in labels] for m in slide.metrics]
        data = charts.monthly('line' if t is SlideType.LINE_CHART else 'bar', series, labels, f.chart_title,
                              legend_title=f.legend_title, show_legend=o.show_legend is not False)
        data['show_values'] = o.show_values is not False
    elif t is SlideType.BAR_CHART:
        data = charts.bar_categories(points[0], f.chart_title, show_values=o.show_values is not False,
                                     labels=doc.severity_labels)
    elif t is SlideType.SEVERITY_DISTRIBUTION:
        data = charts.severity(points[0], f.chart_title, show_values=o.show_values is not False,
                               labels=doc.severity_labels)
    elif t is SlideType.TOP10_RANKING:
        data = charts.ranking(points[0], f.chart_title, top_n=o.top_n or 10, show_values=o.show_values is not False,
                              labels=doc.severity_labels)
    else:
        data = charts.table(points, f.chart_title)
    return data, points


def _issues(slide: Slide, points: list[dict], defn: TemplateDefinition, data: dict | None) -> list[dict]:
    slot = next((s for s in defn.slides if s.slot_id == slide.template_slot), None)
    required = set(all_metrics(slot)) if slot is not None and slot.required_metrics else set()
    out = []
    for p in points:
        mid = p['metric_id']
        level = 'blocker' if mid in required else 'warning'
        if p['state'] == 'MISSING':
            out.append({'level': level, 'code': 'metric_missing', 'metric_id': mid,
                        'message': f'{mid}: sem valor na revisão aprovada ({p["value_state"] or "MISSING"}). Para '
                                   'corrigir, crie uma nova revisão da competência (Competências) e aprove-a.'})
        elif p['state'] == 'INCOMPATIBLE':
            out.append({'level': level, 'code': 'contract_incompatible', 'metric_id': mid,
                        'message': f'{mid}: contrato v{p["contract_version"]} fora das versões aceitas pelo '
                                   'template; valor não exibido'})
        if p['origin'] == 'MANUAL':
            out.append({'level': 'info', 'code': 'manual_value', 'metric_id': mid,
                        'message': f'{mid}: valor manual justificado (aprovado na F05)'})
    parts = [z['data'] for z in (data or {}).get('zones', {}).values() if z.get('data')] \
        if (data or {}).get('kind') == 'dashboard' else [data] if data is not None else []
    for part in parts:
        if part.get('available') is False:
            out.append({'level': 'warning', 'code': f'chart_{part["reason"]}', 'metric_id': None,
                        'message': part['message']})
    for g in sorted({g for part in parts for g in part.get('gaps', [])}):
        out.append({'level': 'info', 'code': 'history_gap', 'metric_id': None,
                    'message': f'{g}: competência sem revisão aprovada (lacuna; preenchimento só pela F05)'})
    return out


def _freshness(session: Session, comp: Competence, sources: dict) -> list[dict]:
    out = []
    latest = service.latest_approval(session, comp.id)
    if latest is not None and str(latest.id) != sources['primary']['approval_id']:
        out.append({'level': 'warning', 'code': 'newer_approval_available', 'metric_id': None,
                    'message': f'A competência {comp.label} tem aprovação mais recente (sequência {latest.sequence}). '
                               'A apresentação continua na revisão fixada até "Atualizar fontes aprovadas".'})
    window = sources.get('history_window') or {}
    if window:
        labels = history.month_range(window['start'], shift(window['end'], -1))
        now = history.official(session, comp.owner_key, labels)
        pinned = sources.get('history', {})
        changed = [lbl for lbl in labels if (lbl in now) != (lbl in pinned)
                   or (lbl in now and str(now[lbl][2].id) != pinned[lbl]['approval_id'])]
        if changed:
            out.append({'level': 'info', 'code': 'history_refs_outdated', 'metric_id': None,
                        'message': 'Há aprovações mais recentes para meses do histórico: ' + ', '.join(changed)})
    return out


def build(session: Session, p: Presentation, prev: PresentationRevision, draft: Document | None = None) -> dict:
    """`draft` = documento ainda não salvo (pré-visualização do editor): mesmas fontes fixadas, nada é gravado."""
    tmpl = session.get(PresentationTemplate, p.template_id)
    defn = definition_of(tmpl)
    doc = draft or Document.model_validate(json.loads(prev.document_json))
    sources = json.loads(prev.sources_json)
    comp = session.get(Competence, p.competence_id)
    kind, _, oid = p.owner_key.partition(':')
    owner = store.get_owner(session, kind, uuid.UUID(oid))
    entries, ref_problems = load_entries(session, sources)
    label = comp.label
    slides, used = [], set()
    for i, slide in enumerate(doc.slides):
        data, points = _slide_data(slide, entries, label, defn, doc, owner, comp)
        used |= set(all_metrics(slide))
        spec = SLIDE_TYPES[slide.type]
        slides.append({'index': i + 1, 'slide_id': slide.slide_id, 'template_slot': slide.template_slot,
                       'type': slide.type.value, 'type_name': spec.name, 'layout': slide.layout,
                       'required': any(s.required and s.slot_id == slide.template_slot for s in defn.slides),
                       'fields': slide.fields.model_dump(), 'options': slide.options.model_dump(),
                       'metrics': list(slide.metrics), 'data': data,
                       **({'zones': {k: z.model_dump(mode='json') for k, z in slide.zones.items()}}
                          if slide.zones else {}),
                       'issues': _issues(slide, points, defn, data)})
    primary = entries.get(label)
    metrics_out = []
    if primary is not None:
        _, rev, _ = primary
        required = set(json.loads(rev.required_metrics_json))
        by_id = {s.metric_id: s for s in rev.snapshots}
        for mid in sorted(used):
            s = by_id.get(mid)
            metrics_out.append(service.snapshot_out(s, required) if s is not None else
                               {'metric_id': mid, 'name': REGISTRY[mid].name if mid in REGISTRY else mid,
                                'value_state': 'MISSING', 'value': None})
    checks = [{'level': 'blocker', 'code': 'source_reference_broken', 'metric_id': None, 'message': m}
              for m in ref_problems] + _freshness(session, comp, sources)
    blockers = sum(1 for s in slides for i in s['issues'] if i['level'] == 'blocker') + \
        sum(1 for c in checks if c['level'] == 'blocker')
    theme_defn, theme = themes.load(session, tmpl.theme_id, tmpl.theme_version)
    missing = themes.missing_assets(theme_defn)
    checks += [{'level': 'warning', 'code': 'theme_asset_missing', 'metric_id': None,
                'message': f'Ativo do tema ausente no armazenamento local ({a[:12]}…): o elemento não é exibido.'}
               for a in missing]
    # F06C: encaixes de ativos autorizados da pasta local (fora do Git); ausência = fallback neutro (informativo)
    brand = brand_assets.status(tmpl.theme_id, [s.name for s in theme_defn.asset_slots])
    absent = [s for s, b in brand.items() if b['status'] == 'missing']
    if absent:
        checks.append({'level': 'info', 'code': 'brand_asset_missing', 'metric_id': None,
                       'message': 'Ativos visuais locais ausentes (encaixes vazios, fallback neutro): '
                                  + ', '.join(absent)})
    checks += [{'level': 'warning', 'code': 'brand_asset_invalid', 'metric_id': None,
                'message': f'Ativo visual local "{s}" ignorado: {b["message"]}'}
               for s, b in brand.items() if b['status'] == 'invalid']
    return {'presentation': {'id': str(p.id), 'title': doc.title, 'current_revision': p.current_revision},
            'draft': draft is not None,
            'revision': {'number': prev.number, 'created_by': prev.created_by,
                         'created_at': prev.created_at.isoformat(), 'change_summary': prev.change_summary,
                         'document_hash': prev.document_hash, 'sources_hash': prev.sources_hash,
                         'revision_hash': prev.revision_hash},
            'owner': {'kind': owner.kind, 'id': str(owner.id), 'name': owner.name, 'key': owner.key},
            'competence': {'id': str(comp.id), 'competence': comp.label, 'timezone': comp.timezone,
                           'period': service.period(comp)},
            'template': template_out(tmpl), 'theme': theme, 'brand_assets': brand,
            'presenters': [x.model_dump() for x in doc.presenters],
            'sources': {**sources, 'metrics': metrics_out}, 'slides': slides, 'checks': checks,
            'ready': blockers == 0, 'blockers': blockers, 'ir_version': charts.IR_VERSION,
            'severity_labels': doc.severity_labels,
            'data_policy': 'Somente revisões aprovadas fixadas; nenhum número inventado, interpolado ou recalculado.'}
