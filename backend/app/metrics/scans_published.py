"""`apps.scanned` v1 (F12): aplicações DISTINTAS do escopo com ao menos um scan PUBLICADO na competência.

Fonte comprovada documentalmente: relatório SCANS da Reporting API (SwaggerHub `veracode-reporting_api_specification`
1.12.0 + https://docs.veracode.com/r/Reporting_REST_API, consultados em 2026-10-19) — um item POR SCAN (não só o
último), com `app_id`, `scan_id`, `scan_type`, `policy_sandbox`, `published` e `last_updated_date`.
Fontes estudadas e INSUFICIENTES sozinhas (nunca usadas para o mês): Applications API `scans[]` e
`last_completed_scan_date` (só o ÚLTIMO scan por tipo) e Summary Report (só o build mais recente por contexto) — um
scan posterior esconde o do período. Elas só servem de CONFERÊNCIA de visibilidade (ver `_visibility`).

Regras (determinísticas; incerteza nunca vira zero):
- Identidade = GUID da população (escopo do dono). O `app_id` do relatório é o ID numérico da MESMA plataforma
  (`id` da Applications API = `legacy_id`); nunca nome. `app_id` fora do escopo = fora (contado na cobertura).
- SAST = `scan_type` "Static Analysis"; Policy/Sandbox por `policy_sandbox`. SCA: o relatório SCANS não tem tipo
  SCA (enum da especificação) ⇒ dimensão SCA INDISPONÍVEL (null), declarada no valor — nunca 0.
- Data efetiva = `published` (scan sem `published` = não publicado). A especificação diz "timestamps em EDT" sem
  regra de horário de verão ⇒ cada data vira um INTERVALO de instantes possíveis (UTC−4 e UTC−5; data sem hora =
  o dia inteiro); dentro da competência (fuso do cliente) só se o intervalo inteiro estiver dentro; cruzando um
  limite ⇒ indeterminado.
- Deduplicação: itens por `scan_id` (repetição entre páginas conta 1); aplicações por GUID (vários scans = 1).
- Completude: relatório completo, janela `last_updated_*` que cobre do início da competência até a geração
  (`last_updated_date` ≥ publicação), sem `most_recent_scan=true` (seria só o último scan), sem filtro por
  aplicação/contexto e sem divergência de visibilidade com o perfil das aplicações.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from app.metrics.competence import Competence, parse_timestamp

STATIC = 'Static Analysis'
SOURCE_OFFSETS = (timedelta(hours=-4), timedelta(hours=-5))  # "EDT" na especificação; EST possível no inverno
_DATE_ONLY = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_LOCAL_TS = re.compile(r'^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?$')
SCA_UNAVAILABLE = ('Relatório SCANS sem tipo SCA (enum da especificação: Static/Dynamic/MPT); SCA por upload sai no '
                   'mesmo scan estático e SCA Agent não aparece ⇒ sem fonte comprovada para a dimensão SCA')
IN, OUT, AMBIGUOUS = 'IN', 'OUT', 'AMBIGUOUS'


@dataclass(frozen=True)
class ScansEvidence:
    """Resultado de UM relatório SCANS já minimizado (`reporting.KEEP_FIELDS['SCANS']`)."""
    request: dict                      # ReportRequest.public()
    generated_on: date                 # data (UTC) em que o relatório foi gerado
    complete: bool                     # todas as páginas lidas e total = page_metadata.total_elements
    items: list[dict]
    data_refresh_date: str | None = None
    reasons: tuple[dict, ...] = field(default_factory=tuple)


def published_interval(value) -> tuple[datetime, datetime] | None:
    """Instantes UTC possíveis [mín, máx] da publicação. None = data ausente/ilegível."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    exact = parse_timestamp(text)
    if exact is not None:
        return exact.astimezone(timezone.utc), exact.astimezone(timezone.utc)
    if _DATE_ONLY.fullmatch(text):
        start = datetime.fromisoformat(text)
        span = (start, start + timedelta(days=1) - timedelta(microseconds=1))
    elif _LOCAL_TS.fullmatch(text):
        moment = datetime.fromisoformat(text.replace(' ', 'T'))
        span = (moment, moment)
    else:
        return None
    lo = min((span[0] - off).replace(tzinfo=timezone.utc) for off in SOURCE_OFFSETS)
    hi = max((span[1] - off).replace(tzinfo=timezone.utc) for off in SOURCE_OFFSETS)
    return lo, hi


def classify(interval: tuple[datetime, datetime], comp: Competence) -> str:
    lo, hi = interval
    if comp.utc_start <= lo and hi < comp.utc_end:
        return IN
    if hi < comp.utc_start or lo >= comp.utc_end:
        return OUT
    return AMBIGUOUS


def _window_blockers(ev: ScansEvidence, comp: Competence) -> list[tuple[str, str]]:
    req, out = ev.request, []
    if req.get('report_type') != 'SCANS':
        out.append(('report_type_mismatch', 'Relatório não é do tipo SCANS'))
    if req.get('most_recent_scan') is True:
        out.append(('most_recent_only', 'Relatório pedido com most_recent_scan=true traz só o ÚLTIMO scan: não '
                                        'sustenta a contagem do período'))
    if req.get('app_id') is not None or req.get('policy_sandbox') is not None:
        out.append(('report_filtered', 'Relatório filtrado por aplicação ou contexto: não cobre o escopo inteiro'))
    if req.get('scan_type') and STATIC not in req['scan_type']:
        out.append(('report_without_static', 'Relatório sem scans "Static Analysis"'))
    try:
        start = date.fromisoformat(req.get('last_updated_start_date') or '')
        end = date.fromisoformat(req.get('last_updated_end_date') or '')
    except ValueError:
        return out + [('report_window_unknown', 'Janela last_updated_* do relatório desconhecida')]
    if start > comp.utc_start.date():
        out.append(('report_window_starts_late', 'Janela do relatório começa depois do início da competência'))
    if end <= ev.generated_on:  # data sem hora = 00:00 (documentação): o dia da geração exige end = dia seguinte
        out.append(('report_window_ends_early', 'Janela do relatório termina antes da geração: scans do período '
                                                'atualizados depois (last_updated_date) ficariam de fora'))
    if comp.utc_end.date() > ev.generated_on + timedelta(days=1):
        out.append(('competence_not_closed', 'Relatório gerado antes do fim da competência'))
    refresh = parse_timestamp(ev.data_refresh_date) if ev.data_refresh_date else None
    if refresh is not None and refresh < comp.utc_end:
        out.append(('report_data_not_refreshed', 'data_refresh_date do relatório anterior ao fim da competência'))
    return out


def _visibility(apps: list[dict], seen_static: set[str], window_start: datetime | None) -> list[str]:
    """Aplicações cujo PERFIL mostra scan estático publicado dentro da janela, mas sem item no relatório: a conta do
    relatório não as enxerga (restrição de Team/papel) ⇒ ausência no relatório NÃO prova falta de scan."""
    if window_start is None:
        return []
    missing = []
    for a in apps:
        for s in a.get('scans') or []:
            d = parse_timestamp(s.get('modified_date'))
            if s.get('scan_type') == 'STATIC' and s.get('status') == 'PUBLISHED' and d and d >= window_start \
                    and a['guid'].lower() not in seen_static:
                missing.append(a['guid'].lower())
                break
    return missing


def evaluate(apps: list[dict], comp: Competence, ev: ScansEvidence) -> tuple[dict, list[tuple[str, str]], dict]:
    """(valor, bloqueios, cobertura). Bloqueio ⇒ o motor publica INCOMPLETE com o valor em `partial`."""
    blockers = _window_blockers(ev, comp)
    if not ev.complete:
        blockers.append(('report_incomplete', 'Relatório SCANS incompleto (páginas/total anunciado)'))
    by_legacy, no_legacy = {}, 0
    for a in apps:
        lid = a.get('legacy_id')
        if lid is None or isinstance(lid, bool):
            no_legacy += 1
        else:
            by_legacy[str(lid)] = a['guid'].lower()
    if no_legacy:
        blockers.append(('application_legacy_id_missing', f'{no_legacy} aplicação(ões) do escopo sem ID numérico: '
                                                          'scans não atribuíveis'))
    cov = {'applications': len(apps), 'report_items': len(ev.items), 'duplicate_items': 0, 'out_of_scope_items': 0,
           'other_scan_type_items': 0, 'unpublished_items': 0, 'ambiguous_items': 0}
    state: dict[tuple[str, str], str] = {}   # (guid, Policy|Sandbox) -> melhor estado
    seen_ids, seen_static = set(), set()
    rank = {OUT: 0, AMBIGUOUS: 1, IN: 2}
    for item in ev.items:
        sid = item.get('scan_id')
        if sid is not None:
            if sid in seen_ids:
                cov['duplicate_items'] += 1
                continue
            seen_ids.add(sid)
        app = item.get('app_id')
        if app is None:
            blockers.append(('scan_without_application', 'Item do relatório sem app_id'))
            continue
        guid = by_legacy.get(str(app))
        if guid is None:
            cov['out_of_scope_items'] += 1
            continue
        if item.get('scan_type') != STATIC:
            cov['other_scan_type_items'] += 1
            continue
        seen_static.add(guid)
        if not item.get('published'):
            cov['unpublished_items'] += 1
            continue
        interval = published_interval(item['published'])
        if interval is None:
            blockers.append(('published_date_invalid', 'Data de publicação ilegível em item do relatório'))
            continue
        where = classify(interval, comp)
        if where == AMBIGUOUS:
            cov['ambiguous_items'] += 1
        ctx = item.get('policy_sandbox')
        if ctx not in ('Policy', 'Sandbox'):
            if where != OUT:
                blockers.append(('scan_context_unknown', 'Scan do período sem policy_sandbox reconhecido'))
            continue
        key = (guid, ctx)
        if rank[where] > rank[state.get(key, OUT)]:
            state[key] = where

    def apps_in(ctx: str | None, wanted: str) -> set[str]:
        return {g for (g, c), s in state.items() if s == wanted and (ctx is None or c == ctx)}

    scanned = apps_in(None, IN)
    ambiguous = apps_in(None, AMBIGUOUS) - scanned
    if ambiguous:
        blockers.append(('publication_near_boundary', f'{len(ambiguous)} aplicação(ões) só com scan publicado perto '
                                                      'do limite da competência (fuso EDT/EST indeterminado)'))
    try:
        window_start = datetime.fromisoformat(ev.request['last_updated_start_date']).replace(tzinfo=timezone.utc)
    except (KeyError, TypeError, ValueError):
        window_start = None
    hidden = _visibility(apps, seen_static, window_start)
    if hidden:
        blockers.append(('report_missing_application', f'{len(hidden)} aplicação(ões) com scan publicado no perfil '
                                                       'e ausentes do relatório: visibilidade da conta da Reporting '
                                                       'API (Teams/papel) não cobre o escopo'))
    value = {'scanned': len(scanned), 'scanned_policy': len(apps_in('Policy', IN)),
             'scanned_sandbox': len(apps_in('Sandbox', IN)), 'not_scanned': len(apps) - len(scanned) - len(ambiguous),
             'indeterminate': len(ambiguous), 'applications_in_scope': len(apps),
             'sca_scanned': None, 'sca_status': 'UNAVAILABLE', 'sca_reason': SCA_UNAVAILABLE}
    seen, unique = set(), []
    for code, msg in blockers:
        if code not in seen:
            seen.add(code)
            unique.append((code, msg))
    return value, unique, cov


async def collect_evidence(client, comp: Competence, *, today: date, progress=None) -> ScansEvidence:
    """Gera UM relatório SCANS (POST autorizado na F05, só com `AFRIKA_VERACODE_REPORTING_ENABLED=true`) cobrindo do
    início da competência até o dia seguinte a `today` e devolve a evidência minimizada. Nunca chamado pela coleta
    GET-only; a janela é validada por `reporting_policy` (teto configurável e 6 meses documentados)."""
    from app.veracode.reporting_policy import build
    request = build({'report_type': 'SCANS', 'last_updated_start_date': comp.utc_start.date().isoformat(),
                     'last_updated_end_date': (today + timedelta(days=1)).isoformat()},
                    max_days=client.settings.reporting_max_window_days, today=today)
    items, meta = await client.fetch_items(request, progress or (lambda _update: None))
    return ScansEvidence(request.public(), today, meta['complete'], items, meta.get('data_refresh_date'),
                         tuple(meta['reasons']))
