"""Cálculo determinístico dos indicadores a partir da população (F03) e da coleta de findings (F04).

Regras transversais:
- Valor só com VALIDATED. Qualquer bloqueio (coleta parcial, limite, indeterminado, campo ausente, identidade de
  deduplicação não comprovada) => INCOMPLETE com o agregado observado em `partial` (não definitivo).
- População indisponível => UNAVAILABLE; erro da fonte sem nenhum dado => FAILED.
- SAST e SCA têm identidades distintas; nada é somado entre eles.
- Estado atual ≠ fechamento da competência: métricas de estado trazem `as_of` (data da coleta); o estado no
  fechamento é UNAVAILABLE (exige snapshot aprovado da F05).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from app.metrics.collector import CollectionOutcome, CollectState, ContextData
from app.metrics.competence import Competence, parse_timestamp
from app.metrics.contracts import (
    SEVERITY_LABELS, Dedup, Domain, IdentityProof, MetricContract, MetricResult, MetricStatus, Reason, ScanContext,
    StatusCriterion, Support, TemporalMode,
)
from app.metrics.population import Population, PopulationStatus
from app.metrics.registry import CONTRACTS, TOP_N
from app.scopes import rules
from app.scopes.store import OwnerRule

_CURRENT_NOTE = 'Estado atual na data da coleta (as_of); não é o estado no fechamento da competência'


@dataclass
class Blockers:
    reasons: list[Reason] = field(default_factory=list)

    def add(self, code: str, message: str) -> None:
        if all(r.code != code for r in self.reasons):
            self.reasons.append(Reason(code, message))

    def __bool__(self) -> bool:
        return bool(self.reasons)


@dataclass
class Context:
    """Entradas de cálculo de uma execução."""
    competence: Competence
    population: Population
    outcome: CollectionOutcome | None
    finding_rules: dict[str, list[OwnerRule]]
    collected_at: str
    owner_kind: str


# ---------------------------------------------------------------- utilidades

def empty_severity() -> dict:
    return {**{label: 0 for label in SEVERITY_LABELS.values()}, 'UNKNOWN': 0, 'total': 0}


def _add_severity(acc: dict, severity: int | None) -> None:
    acc[SEVERITY_LABELS.get(severity, 'UNKNOWN') if severity is not None else 'UNKNOWN'] += 1
    acc['total'] += 1


def _open(f: dict) -> bool | None:
    status = f.get('status')
    if status == 'CLOSED':
        return False
    if status != 'OPEN':
        return None  # status ausente/desconhecido: não presumir
    return f.get('resolution_status') != 'APPROVED'


def _dep_mode(f: dict) -> str | None:
    mode = f.get('sca_dep_mode')
    return {'DIRECT': 'direct', 'TRANSITIVE': 'transitive'}.get(mode)


def _scope_record(domain: Domain, c: ContextData, f: dict) -> dict:
    if domain == Domain.SAST:
        return {'application.id': c.app_guid, 'application.in_scope': True,
                'scan.context': c.context.lower(), 'scan.type': c.scan_type}
    return {'application.id': c.app_guid, 'application.in_scope': True, 'sca.dependency': _dep_mode(f)}


def _scope_filter(domain: Domain, owners: list[OwnerRule]) -> tuple[Callable[[ContextData, dict], bool | None], list]:
    scope_domain = 'scans' if domain == Domain.SAST else 'sca'
    active = [o for o in owners if o.status == 'active' and o.rule is not None]
    applied = [{'owner_key': o.owner.key, 'domain': scope_domain, 'version': o.version,
                'rule_hash': rules.rule_hash(o.rule)} for o in active]

    def check(c: ContextData, f: dict) -> bool | None:
        record = _scope_record(domain, c, f)
        value: bool | None = True
        for o in active:
            out = rules.evaluate(scope_domain, o.rule, record).value
            if out is False:
                return False
            if out is None:
                value = None
        return value
    return check, applied


# ---------------------------------------------------------------- resultado

def _temporal(c: MetricContract, ctx: Context) -> dict:
    return {'mode': c.temporal_mode.value, 'competence': ctx.competence.label,
            'period': ctx.competence.as_dict(), 'date_field': c.date_field.value, 'as_of': ctx.collected_at,
            'historical_state': False,
            'note': {TemporalMode.CURRENT_STATE: _CURRENT_NOTE,
                     TemporalMode.EVENT_IN_PERIOD: f'Filtro: {c.date_field.value} dentro da competência '
                                                   f'(fuso {ctx.competence.utc_offset}); demais datas ignoradas',
                     TemporalMode.STATE_AT_PERIOD_END: 'Estado no fechamento da competência (histórico)'}
            [c.temporal_mode]}


def _filters(c: MetricContract, applied: list | None = None) -> dict:
    return {'scan_type': c.scan_type.value, 'context': c.context.value, 'status': c.status_criterion.value,
            'severity': c.severity_criterion.value, 'date_field': c.date_field.value, 'dedup': c.dedup.value,
            'identity_proof': c.identity_proof.value, 'scope_rules_applied': applied or []}


def _result(c: MetricContract, ctx: Context, status: MetricStatus, *, value=None, partial=None,
            reasons: Iterable[Reason] = (), coverage: dict | None = None, applied: list | None = None) -> MetricResult:
    return MetricResult(c.metric_id, c.version, status, value=value if status == MetricStatus.VALIDATED else None,
                        partial=partial if status == MetricStatus.INCOMPLETE else None, reasons=list(reasons),
                        coverage=coverage or {}, filters=_filters(c, applied), temporal=_temporal(c, ctx))


def _finish(c: MetricContract, ctx: Context, value, blockers: Blockers, *, coverage: dict,
            applied: list | None = None, failed: bool = False) -> MetricResult:
    if failed:
        return _result(c, ctx, MetricStatus.FAILED, reasons=blockers.reasons, coverage=coverage, applied=applied)
    if c.identity_proof == IdentityProof.NOT_PROVEN:
        blockers.add('dedup_identity_not_proven',
                     f'Identidade de deduplicação {c.dedup.value} não comprovada: valor candidato, não definitivo')
    if blockers:
        return _result(c, ctx, MetricStatus.INCOMPLETE, partial=value, reasons=blockers.reasons, coverage=coverage,
                       applied=applied)
    return _result(c, ctx, MetricStatus.VALIDATED, value=value, coverage=coverage, applied=applied)


def _population_blockers(pop: Population) -> Blockers:
    b = Blockers()
    if pop.status == PopulationStatus.INCOMPLETE:
        for r in pop.reasons:
            b.add(r.code, r.message)
    return b


# ---------------------------------------------------------------- aplicações

def _apps_metric(c: MetricContract, ctx: Context) -> MetricResult:
    pop = ctx.population
    apps = pop.applications
    b = _population_blockers(pop)
    coverage = {'applications': len(apps), 'total_available_in_tenant_view': pop.total_available,
                'undetermined': pop.undetermined, 'missing_fields': pop.missing_fields}
    mid = c.metric_id
    if mid == 'apps.total':
        value = len(apps)
    elif mid == 'apps.by_business_unit':
        groups: dict = {}
        unknown = 0
        for a in apps:
            bu = a.get('business_unit')
            if not bu or not bu.get('guid'):
                unknown += 1
                continue
            g = groups.setdefault(bu['guid'].lower(), {'business_unit_id': bu['guid'].lower(),
                                                        'name': bu.get('name'), 'applications': 0})
            g['applications'] += 1
        if unknown:
            b.add('business_unit_missing', f'{unknown} aplicação(ões) sem BU identificável no perfil')
        value = {'items': sorted(groups.values(), key=lambda g: (-g['applications'], (g['name'] or '').casefold(),
                                                                 g['business_unit_id'])),
                 'unknown': unknown, 'distinct_applications': len(apps)}
    elif mid in ('apps.by_team', 'apps.without_team', 'apps.multiple_teams'):
        unknown = [a for a in apps if a.get('teams') is None or any(not t.get('guid') for t in a['teams'])]
        if unknown:
            b.add('teams_unknown', f'{len(unknown)} aplicação(ões) com lista de Teams ausente ou sem ID')
        known = [a for a in apps if a not in unknown]
        if mid == 'apps.without_team':
            value = sum(a['teams'] == [] for a in known)
        elif mid == 'apps.multiple_teams':
            value = sum(len(a['teams']) >= 2 for a in known)
        else:
            groups = {}
            for a in known:
                for t in a['teams']:
                    g = groups.setdefault(t['guid'].lower(), {'team_id': t['guid'].lower(), 'name': t.get('name'),
                                                              'applications': 0})
                    g['applications'] += 1
            value = {'items': sorted(groups.values(), key=lambda g: (-g['applications'], (g['name'] or '').casefold(),
                                                                     g['team_id'])),
                     'distinct_applications': len(apps),
                     'distinct_applications_with_team': sum(bool(a['teams']) for a in known),
                     'team_assignments': sum(g['applications'] for g in groups.values()),
                     'without_team': sum(a['teams'] == [] for a in known), 'teams_unknown': len(unknown)}
    elif mid == 'apps.unclassified':
        if ctx.owner_kind != 'client' or pop.unclassified is None:
            return _result(c, ctx, MetricStatus.UNAVAILABLE, coverage=coverage, reasons=[Reason(
                'not_applicable_for_owner', 'Não classificadas só existem para o cliente principal na própria '
                                            'conexão')])
        for r in pop.unclassified['blocking']:
            b.add(r.code, r.message)
        value = {'count': pop.unclassified['count'], 'no_subclients': pop.unclassified['no_subclients']}
    else:  # pragma: no cover - registro e cálculo andam juntos
        raise KeyError(mid)
    return _finish(c, ctx, value, b, coverage=coverage)


# ---------------------------------------------------------------- findings

def _contexts(ctx: Context, c: MetricContract) -> list[ContextData]:
    contexts = {ScanContext.POLICY: ('POLICY',), ScanContext.SANDBOX: ('SANDBOX',),
                ScanContext.POLICY_AND_SANDBOX: ('POLICY', 'SANDBOX')}[c.context]
    return [x for x in ctx.outcome.contexts if x.scan_type == c.scan_type.value and x.context in contexts]


def _collection_check(ctx: Context, c: MetricContract, selected: list[ContextData], b: Blockers) -> tuple[dict, bool,
                                                                                                         bool]:
    """Devolve (cobertura, falhou_tudo, não_suportado)."""
    out = ctx.outcome
    states = Counter(x.state for x in selected)
    needs_sandboxes = c.context in (ScanContext.SANDBOX, ScanContext.POLICY_AND_SANDBOX)
    listings_failed = [lst for lst in out.listings.values() if lst.state != CollectState.COMPLETE]
    apps = {a['guid'].lower() for a in ctx.population.applications}
    coverage = {'applications': len(apps), 'contexts_expected': len(selected),
                **{f'contexts_{s.value}': states.get(s, 0) for s in CollectState},
                'applications_with_findings_collected': len({x.app_guid for x in selected
                                                             if x.state == CollectState.COMPLETE})}
    if needs_sandboxes:
        coverage['sandbox_listings_failed'] = len(listings_failed)
        coverage['sandboxes'] = len({x.sandbox_guid for x in selected if x.sandbox_guid})
        if listings_failed:
            b.add('sandbox_listing_incomplete', f'Lista de sandboxes indisponível para {len(listings_failed)} '
                                                'aplicação(ões): contextos de desenvolvimento desconhecidos')
    if out.limit_reached:
        b.add('collection_limit_exceeded', f'Limite da coleta atingido ({out.limit_reached}): agregados parciais')
    unsupported = states.get(CollectState.UNSUPPORTED, 0)
    if unsupported and unsupported == len(selected):
        return coverage, False, True
    if unsupported:
        b.add('context_unsupported', f'{unsupported} contexto(s) recusado(s) pela Veracode (HTTP 400)')
    bad = states.get(CollectState.INCOMPLETE, 0) + states.get(CollectState.FAILED, 0)
    if bad:
        codes = sorted({x.error for x in selected if x.state in (CollectState.INCOMPLETE, CollectState.FAILED)
                        and x.error})
        b.add('findings_collection_incomplete', f'{bad} contexto(s) com coleta incompleta ou falha '
                                                f'({", ".join(codes)})')
    failed_all = bool(selected) and states.get(CollectState.FAILED, 0) == len(selected)
    return coverage, failed_all, False


def _evaluated(ctx: Context, c: MetricContract, selected: list[ContextData], b: Blockers, *,
               criterion: Callable[[dict], bool | None]) -> tuple[list[tuple[ContextData, dict]], list]:
    check, applied = _scope_filter(c.domain, ctx.finding_rules.get('scans' if c.domain == Domain.SAST else 'sca', []))
    kept, scope_undet, status_unknown, excluded = [], 0, 0, 0
    for x in selected:
        for f in x.findings:
            in_scope = check(x, f)
            if in_scope is None:
                scope_undet += 1
                continue
            if in_scope is False:
                excluded += 1
                continue
            ok = criterion(f)
            if ok is None:
                status_unknown += 1
            elif ok:
                kept.append((x, f))
    if scope_undet:
        b.add('findings_scope_undetermined', f'{scope_undet} finding(s) indeterminado(s) pelas regras de escopo '
                                             '(campo ausente)')
    if status_unknown:
        b.add('finding_status_unknown', f'{status_unknown} finding(s) sem status reconhecido (OPEN/CLOSED)')
    applied = [{**a, 'excluded_findings': excluded} for a in applied] if applied else []
    return kept, applied


def _severity_blocker(acc: dict, b: Blockers) -> None:
    if acc['UNKNOWN']:
        b.add('severity_missing', f'{acc["UNKNOWN"]} finding(s) sem severidade (0–5) informada')


def _findings_metric(c: MetricContract, ctx: Context) -> MetricResult:
    pop = ctx.population
    b = _population_blockers(pop)
    out = ctx.outcome
    if out is None or out.skipped_reason:
        reason = out.skipped_reason if out else 'collection_not_run'
        return _result(c, ctx, MetricStatus.INCOMPLETE, reasons=b.reasons + [Reason(
            'findings_not_collected', f'Findings não coletados: {reason}')],
            coverage={'applications': len(pop.applications)})
    selected = _contexts(ctx, c)
    coverage, failed_all, unsupported = _collection_check(ctx, c, selected, b)
    if unsupported:
        return _result(c, ctx, MetricStatus.UNSUPPORTED, coverage=coverage, reasons=[Reason(
            'context_unsupported', 'A Veracode recusou este contexto (HTTP 400): suporte não disponível')])
    if failed_all:
        return _finish(c, ctx, None, b, coverage=coverage, failed=True)
    any_status = c.status_criterion == StatusCriterion.ANY_STATUS
    kept, applied = _evaluated(ctx, c, selected, b, criterion=(lambda f: True) if any_status else _open)
    excluded_mitigations = sum(1 for x in selected for f in x.findings
                               if f.get('status') == 'OPEN' and f.get('resolution_status') == 'APPROVED')
    if not any_status:
        coverage['excluded_approved_mitigations'] = excluded_mitigations
    mid = c.metric_id
    compute = _FINDING_COMPUTE[mid.split('.', 1)[1] if mid.startswith(('sast.', 'sca.')) else mid]
    value = compute(c, ctx, kept, b, coverage)
    return _finish(c, ctx, value, b, coverage=coverage, applied=applied)


def _by_severity(c, ctx, kept, b, coverage) -> dict:
    acc = empty_severity()
    for _, f in kept:
        _add_severity(acc, f.get('severity'))
    _severity_blocker(acc, b)
    if c.context == ScanContext.SANDBOX:
        per = defaultdict(lambda: {'total': 0})
        for x, _ in kept:
            per[(x.app_guid, x.sandbox_guid)]['total'] += 1
        coverage['occurrences_by_sandbox'] = [
            {'application_guid': a, 'sandbox_guid': s, 'findings': v['total']} for (a, s), v in sorted(per.items())]
    return acc


def _distinct(c, ctx, kept, b, coverage) -> dict:
    groups: dict[tuple, list[int | None]] = defaultdict(list)
    unidentified = 0
    for x, f in kept:
        if c.dedup == Dedup.APP_ISSUE_ID_ACROSS_CONTEXTS:
            key = (x.app_guid, f.get('issue_id')) if f.get('issue_id') is not None else None
        else:
            key = (x.app_guid, f.get('component_id'), f.get('vulnerability_id')) \
                if f.get('component_id') and f.get('vulnerability_id') else None
        if key is None:
            unidentified += 1
            continue
        groups[key].append(f.get('severity'))
    if unidentified:
        b.add('identity_fields_missing', f'{unidentified} finding(s) sem os campos de identidade da deduplicação')
    acc = empty_severity()
    conflicts = 0
    for sevs in groups.values():
        known = [s for s in sevs if s is not None]
        if len(set(known)) > 1:
            conflicts += 1
        _add_severity(acc, max(known) if known else None)
    _severity_blocker(acc, b)
    coverage.update(occurrences=len(kept), duplicates_removed=len(kept) - unidentified - len(groups),
                    severity_conflicts=conflicts)
    if conflicts:
        b.add('dedup_severity_conflict', f'{conflicts} grupo(s) deduplicado(s) com severidades diferentes entre '
                                         'contextos (indício de identidade incorreta)')
    return acc


def _by_cwe(c, ctx, kept, b, coverage) -> dict:
    groups: dict[int, dict] = {}
    unknown = 0
    for _, f in kept:
        if f.get('cwe_id') is None:
            unknown += 1
            continue
        g = groups.setdefault(f['cwe_id'], {'cwe_id': f['cwe_id'], 'name': f.get('cwe_name'), 'findings': 0})
        g['findings'] += 1
    if unknown:
        b.add('cwe_missing', f'{unknown} finding(s) sem CWE')
    ranked = sorted(groups.values(), key=lambda g: (-g['findings'], g['cwe_id']))
    return {'top': ranked[:TOP_N], 'others': sum(g['findings'] for g in ranked[TOP_N:]),
            'distinct_cwes': len(ranked), 'unknown_cwe': unknown, 'total': len(kept)}


def _top_apps(c, ctx, kept, b, coverage) -> dict:
    names = {a['guid'].lower(): a.get('name') for a in ctx.population.applications}
    counts = Counter(x.app_guid for x, _ in kept)
    ranked = sorted(({'application_guid': g, 'name': names.get(g), 'findings': n} for g, n in counts.items()),
                    key=lambda r: (-r['findings'], (r['name'] or '').casefold(), r['application_guid']))
    return {'top': ranked[:TOP_N], 'applications_with_findings': len(ranked), 'total': len(kept)}


def _new_in_period(c, ctx, kept, b, coverage) -> dict:
    acc = empty_severity()
    unknown_date = outside = 0
    for _, f in kept:
        moment = parse_timestamp(f.get('first_found_date'))
        if moment is None:
            unknown_date += 1
        elif ctx.competence.contains(moment):
            _add_severity(acc, f.get('severity'))
        else:
            outside += 1
    if unknown_date:
        b.add('date_missing', f'{unknown_date} finding(s) sem first_found_date válida (com fuso)')
    _severity_blocker(acc, b)
    coverage.update(evaluated=len(kept), outside_period=outside, date_unknown=unknown_date)
    return acc


def _by_found_month(c, ctx, kept, b, coverage) -> dict:
    months = Counter()
    unknown = 0
    for _, f in kept:
        moment = parse_timestamp(f.get('first_found_date'))
        if moment is None:
            unknown += 1
        else:
            months[ctx.competence.month_label(moment)] += 1
    if unknown:
        b.add('date_missing', f'{unknown} finding(s) sem first_found_date válida (com fuso)')
    return {'items': [{'month': m, 'findings': n} for m, n in sorted(months.items())], 'unknown_date': unknown,
            'total': len(kept)}


def _top_components(c, ctx, kept, b, coverage) -> dict:
    groups: dict[str, dict] = {}
    unknown = 0
    for x, f in kept:
        cid = f.get('component_id')
        if not cid:
            unknown += 1
            continue
        g = groups.setdefault(cid, {'component_id': cid, 'filename': f.get('component_filename'),
                                    'version': f.get('component_version'), 'findings': 0, '_apps': set()})
        g['findings'] += 1
        g['_apps'].add(x.app_guid)
    if unknown:
        b.add('component_missing', f'{unknown} finding(s) SCA sem component_id')
    rows = [{**{k: v for k, v in g.items() if k != '_apps'}, 'applications': len(g['_apps'])} for g in groups.values()]
    ranked = sorted(rows, key=lambda r: (-r['findings'], (r['filename'] or '').casefold(), r['component_id']))
    return {'top': ranked[:TOP_N], 'distinct_components': len(ranked), 'unknown_component': unknown,
            'total': len(kept)}


def _top_vulnerabilities(c, ctx, kept, b, coverage) -> dict:
    groups: dict[str, dict] = {}
    unknown = 0
    for x, f in kept:
        vid = f.get('vulnerability_id')
        if not vid:
            unknown += 1
            continue
        g = groups.setdefault(vid, {'vulnerability_id': vid, 'findings': 0, 'max_severity': None, '_apps': set()})
        g['findings'] += 1
        g['_apps'].add(x.app_guid)
        sev = f.get('severity')
        if sev is not None and (g['max_severity'] is None or sev > g['max_severity']):
            g['max_severity'] = sev
    if unknown:
        b.add('vulnerability_id_missing', f'{unknown} finding(s) SCA sem identificador de vulnerabilidade')
    rows = [{'vulnerability_id': g['vulnerability_id'], 'applications': len(g['_apps']), 'findings': g['findings'],
             'max_severity': SEVERITY_LABELS.get(g['max_severity'], 'UNKNOWN') if g['max_severity'] is not None
             else 'UNKNOWN'} for g in groups.values()]
    ranked = sorted(rows, key=lambda r: (-r['applications'], -r['findings'], r['vulnerability_id']))
    return {'top': ranked[:TOP_N], 'distinct_vulnerabilities': len(ranked), 'unknown_vulnerability': unknown,
            'total': len(kept)}


def _by_dep_mode(c, ctx, kept, b, coverage) -> dict:
    counts = Counter()
    for _, f in kept:
        counts[f.get('sca_dep_mode') or 'NOT_INFORMED'] += 1
    if counts['NOT_INFORMED']:
        b.add('dependency_mode_missing', f'{counts["NOT_INFORMED"]} finding(s) SCA sem sca_dep_mode')
    return {'items': [{'mode': m, 'findings': n} for m, n in sorted(counts.items())], 'total': len(kept)}


_FINDING_COMPUTE = {
    'policy.open.by_severity': _by_severity,
    'sandbox.open.by_severity': _by_severity,
    'sandbox.open.distinct': _distinct,
    'open.distinct': _distinct,
    'policy.open.by_cwe': _by_cwe,
    'policy.open.top_applications': _top_apps,
    'policy.new_in_period.by_severity': _new_in_period,
    'policy.open.by_first_found_month': _by_found_month,
    'policy.open.top_components': _top_components,
    'policy.open.top_vulnerabilities': _top_vulnerabilities,
    'policy.open.by_dependency_mode': _by_dep_mode,
}


# ---------------------------------------------------------------- orquestração

def compute_all(ctx: Context) -> list[MetricResult]:
    out = []
    pop = ctx.population
    for c in CONTRACTS:
        if c.temporal_mode == TemporalMode.STATE_AT_PERIOD_END:
            out.append(_result(c, ctx, MetricStatus.UNAVAILABLE, reasons=[Reason('historical_state_unavailable',
                                                                                  c.unsupported_reason)]))
        elif c.support == Support.UNSUPPORTED:
            out.append(_result(c, ctx, MetricStatus.UNSUPPORTED, reasons=[Reason('source_not_supported',
                                                                                 c.unsupported_reason)]))
        elif pop.status in (PopulationStatus.UNAVAILABLE, PopulationStatus.FAILED):
            status = MetricStatus.UNAVAILABLE if pop.status == PopulationStatus.UNAVAILABLE else MetricStatus.FAILED
            out.append(_result(c, ctx, status, reasons=pop.reasons))
        elif c.domain == Domain.APPLICATIONS:
            out.append(_apps_metric(c, ctx))
        else:
            out.append(_findings_metric(c, ctx))
    return out
