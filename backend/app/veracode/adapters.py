"""Adaptadores dos endpoints OFICIAIS da Veracode usados na descoberta (F02) e normalização dos campos.

Especificações oficiais (SwaggerHub, organização Veracode):
- Applications API 1.0: https://app.swaggerhub.com/apis/Veracode/veracode-applications-api-specification/1.0
- Identity API 1.5:     https://app.swaggerhub.com/apis/Veracode/veracode-identity_api/1.5
- Findings API 2.1 (F04): https://app.swaggerhub.com/apis/Veracode/veracode-findings_api_specification/2.1

Só campos necessários para descoberta/filtros futuros são mantidos (minimização de dados pessoais:
e-mail, telefone, IP, login etc. de usuários são descartados na normalização).
Ausência de um campo na resposta vira `None` ("desconhecido"), nunca lista vazia/zero presumidos.
"""
from __future__ import annotations

import asyncio
from urllib.parse import quote

from app.veracode.errors import VeracodeError
from app.veracode.http import Collection, CollectionRun

APPLICATIONS = '/appsec/v1/applications'
SANDBOXES = '/appsec/v1/applications/{guid}/sandboxes'
BUSINESS_UNITS = '/api/authn/v2/business_units'
TEAMS = '/api/authn/v2/teams'
TEAM_DETAIL = '/api/authn/v2/teams/{team_id}'
USERS = '/api/authn/v2/users'
FINDINGS = '/appsec/v2/applications/{guid}/findings'
FINDING_SCAN_TYPES = ('STATIC', 'SCA')  # SCA não pode ser combinado com outros tipos (documentação oficial)


def _str(v) -> str | None:
    return v if isinstance(v, str) else None


def _int(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def _list_or_none(v) -> list | None:
    return v if isinstance(v, list) else None


# ---------------------------------------------------------------- normalização

def normalize_application(raw: dict) -> dict:
    profile = raw.get('profile') if isinstance(raw.get('profile'), dict) else {}
    bu = profile.get('business_unit') if isinstance(profile.get('business_unit'), dict) else None
    teams = _list_or_none(profile.get('teams'))
    custom = _list_or_none(profile.get('custom_fields'))
    policies = _list_or_none(profile.get('policies'))
    return {
        'guid': raw.get('guid'),
        'legacy_id': raw.get('id'),
        'name': _str(profile.get('name')),
        'business_unit': None if bu is None else {'guid': _str(bu.get('guid')), 'legacy_id': bu.get('id'),
                                                  'name': _str(bu.get('name'))},
        'teams': None if teams is None else [
            {'guid': _str(t.get('guid')), 'legacy_id': t.get('team_id'), 'name': _str(t.get('team_name'))}
            for t in teams if isinstance(t, dict)],
        'tags': _str(profile.get('tags')),
        'business_criticality': _str(profile.get('business_criticality')),
        'custom_fields': None if custom is None else [
            {'name': _str(c.get('name')), 'value': _str(c.get('value'))} for c in custom if isinstance(c, dict)],
        'policies': None if policies is None else [
            {'guid': _str(p.get('guid')), 'name': _str(p.get('name')),
             'compliance_status': _str(p.get('policy_compliance_status')), 'is_default': p.get('is_default')}
            for p in policies if isinstance(p, dict)],
        'created': _str(raw.get('created')),
        'modified': _str(raw.get('modified')),
        'last_completed_scan_date': _str(raw.get('last_completed_scan_date')),
    }


def normalize_sandbox(raw: dict) -> dict:
    return {'guid': raw.get('guid'), 'legacy_id': raw.get('id'), 'name': _str(raw.get('name')),
            'application_guid': _str(raw.get('application_guid')), 'created': _str(raw.get('created')),
            'modified': _str(raw.get('modified'))}


def _team_bu(raw: dict) -> dict | None:
    bu = raw.get('business_unit')
    if not isinstance(bu, dict):
        return None
    return {'bu_id': _str(bu.get('bu_id')), 'name': _str(bu.get('bu_name'))}


def normalize_business_unit(raw: dict) -> dict:
    teams = _list_or_none(raw.get('teams'))
    return {
        'bu_id': raw.get('bu_id'),
        'legacy_id': raw.get('bu_legacy_id'),
        'name': _str(raw.get('bu_name')),
        'is_default': raw.get('is_default') if isinstance(raw.get('is_default'), bool) else None,
        'team_ids': None if teams is None else [t.get('team_id') for t in teams if isinstance(t, dict)],
    }


def normalize_team(raw: dict) -> dict:
    return {
        'team_id': raw.get('team_id'),
        'legacy_id': raw.get('team_legacy_id'),
        'name': _str(raw.get('team_name')),
        'business_unit': _team_bu(raw),
        'user_count': raw.get('user_count') if isinstance(raw.get('user_count'), int) else None,
    }


def normalize_user(raw: dict) -> dict:
    # Minimização: e-mail, telefone, IP, último login etc. não saem deste módulo.
    return {
        'user_id': raw.get('user_id'),
        'legacy_id': raw.get('user_legacy_id'),
        'user_name': _str(raw.get('user_name')),
        'first_name': _str(raw.get('first_name')),
        'last_name': _str(raw.get('last_name')),
        'active': raw.get('active') if isinstance(raw.get('active'), bool) else None,
        'login_enabled': raw.get('login_enabled') if isinstance(raw.get('login_enabled'), bool) else None,
        'account_type': _str(raw.get('account_type')),
        'team_count': _int(raw.get('team_count')),
    }


def _relationship(v) -> str | None:
    # API real (homologação F02.1): objeto `{name, display_name}`; especificação Identity 1.5: string.
    return _str(v.get('name')) if isinstance(v, dict) else _str(v)


def normalize_membership(raw: dict) -> dict:
    # `team_count` (API real, F02.1): quantidade de Teams do usuário segundo a Veracode — base da reconciliação.
    return {'user_id': raw.get('user_id'), 'user_name': _str(raw.get('user_name')),
            'relationship': _relationship(raw.get('relationship')), 'team_count': _int(raw.get('team_count'))}


def _upper(v) -> str | None:
    return v.strip().upper() if isinstance(v, str) and v.strip() else None


def _severity(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 5 else None


def _sca_metadata(v) -> dict:
    # Especificação: `metadata` é string ("Displays metadata values, such as the SCA scan mode and dependency
    # mode"); observado em integrações: objeto. Aceita os dois; formato desconhecido => campos ausentes.
    if isinstance(v, dict):
        return {'sca_dep_mode': _upper(v.get('sca_dep_mode')), 'sca_scan_mode': _upper(v.get('sca_scan_mode'))}
    out = {'sca_dep_mode': None, 'sca_scan_mode': None}
    if isinstance(v, str):
        for part in v.replace(';', ',').split(','):
            key, sep, value = part.partition(':')
            if not sep:
                key, sep, value = part.partition('=')
            key = key.strip().strip('"').lower()
            if sep and key in out:
                out[key] = _upper(value.strip().strip('"'))
    return out


def normalize_finding(raw: dict) -> dict:
    """Minimização: descrição, arquivo/linha, módulo, procedimento e anotações NÃO saem deste módulo.

    `issue_id` é único "dentro do contexto da aplicação" (especificação): não prova identidade entre contextos.
    """
    status = raw.get('finding_status') if isinstance(raw.get('finding_status'), dict) else {}
    details = raw.get('finding_details') if isinstance(raw.get('finding_details'), dict) else {}
    cwe = details.get('cwe') if isinstance(details.get('cwe'), dict) else None
    cve = details.get('cve') if isinstance(details.get('cve'), dict) else None
    issue_id = raw.get('issue_id')
    out = {
        'issue_id': issue_id if isinstance(issue_id, int) and not isinstance(issue_id, bool) else None,
        'scan_type': _upper(raw.get('scan_type')),
        'context_type': _upper(raw.get('context_type')),
        'context_guid': _str(raw.get('context_guid')),
        'violates_policy': raw.get('violates_policy') if isinstance(raw.get('violates_policy'), bool) else None,
        'status': _upper(status.get('status')),
        'resolution': _upper(status.get('resolution')),
        'resolution_status': _upper(status.get('resolution_status')),
        'first_found_date': _str(status.get('first_found_date')),
        'last_seen_date': _str(status.get('last_seen_date')),
        'severity': _severity(details.get('severity')),
        'cwe_id': cwe.get('id') if cwe and isinstance(cwe.get('id'), int) else None,
        'cwe_name': _str(cwe.get('name')) if cwe else None,
    }
    if out['scan_type'] == 'SCA':
        out.update({'component_id': _str(details.get('component_id')),
                    'component_filename': _str(details.get('component_filename')),
                    'component_version': _str(details.get('version')),
                    'vulnerability_id': _str(cve.get('name')) if cve else None,
                    **_sca_metadata(details.get('metadata'))})
    return out


def _normalized(col: Collection, fn) -> Collection:
    col.items = [fn(i) for i in col.items]
    return col


# ---------------------------------------------------------------- coletas

async def fetch_applications(run: CollectionRun) -> Collection:
    col = await run.paginate(APPLICATIONS, 'applications', label='applications', id_field='guid')
    return _normalized(col, normalize_application)


async def fetch_sandboxes(run: CollectionRun, application_guid: str) -> Collection:
    col = await run.paginate(SANDBOXES.format(guid=quote(application_guid, safe='')), 'sandboxes',
                             label='sandboxes', id_field='guid')
    return _normalized(col, normalize_sandbox)


async def fetch_findings(run: CollectionRun, application_guid: str, scan_type: str,
                         sandbox_guid: str | None = None) -> Collection:
    """Findings de UM contexto: Policy (sem `context`) ou um sandbox (`context`=GUID do sandbox)."""
    if scan_type not in FINDING_SCAN_TYPES:
        raise ValueError('scan_type não suportado')
    params = {'scan_type': scan_type, **({'context': sandbox_guid} if sandbox_guid else {})}
    col = await run.paginate(FINDINGS.format(guid=quote(application_guid, safe='')), 'findings',
                             label=f'findings:{scan_type.lower()}', id_field='issue_id', params=params,
                             page_size=run.settings.findings_page_size)
    return _normalized(col, normalize_finding)


async def fetch_business_units(run: CollectionRun) -> Collection:
    col = await run.paginate(BUSINESS_UNITS, 'business_units', label='business_units', id_field='bu_id')
    return _normalized(col, normalize_business_unit)


async def fetch_teams(run: CollectionRun) -> Collection:
    # Sem `all_for_org=true` a Veracode devolve só os Teams dos quais a conta é membro (resposta do suporte
    # Veracode). Contas restritas a Teams recebem 403 com o parâmetro: reportado como `forbidden`, sem
    # recair silenciosamente para a lista parcial.
    col = await run.paginate(TEAMS, 'teams', label='teams', id_field='team_id', params={'all_for_org': 'true'})
    return _normalized(col, normalize_team)


async def fetch_users(run: CollectionRun) -> Collection:
    col = await run.paginate(USERS, 'users', label='users', id_field='user_id')
    return _normalized(col, normalize_user)


async def fetch_team_memberships(run: CollectionRun, teams: list[dict]) -> Collection:
    """Relação usuário<->Team a partir do detalhe de cada Team (`users[]`), com concorrência limitada.

    Coleta incompleta se qualquer detalhe falhar, se `users` estiver ausente ou se a quantidade
    divergir de `user_count` informado pela própria Veracode.
    """
    col = Collection(resource='team_memberships')
    start_requests, start_retries = run.requests, run.retries

    async def one(team: dict) -> tuple[dict, list[dict] | None, VeracodeError | None]:
        try:
            data = await run.get_json(TEAM_DETAIL.format(team_id=quote(str(team['team_id']), safe='')),
                                      label='team_detail')
        except VeracodeError as exc:
            return team, None, exc
        users = data.get('users')
        if not isinstance(users, list) or not all(isinstance(u, dict) for u in users):
            return team, None, VeracodeError('invalid_response')
        count = data.get('user_count', team.get('user_count'))
        if isinstance(count, int) and count != len(users):
            return team, [normalize_membership(u) for u in users], VeracodeError('membership_count_mismatch')
        return team, [normalize_membership(u) for u in users], None

    results = await asyncio.gather(*(one(t) for t in teams))
    col.meta['teams_fetched'] = [str(team['team_id']) for team, members, error in results
                                 if members is not None and error is None]
    for team, members, error in results:
        if members is not None:
            col.pages_fetched += 1
            for m in members:
                col.items.append({**m, 'team_id': team['team_id'], 'team_name': team.get('name')})
        if error is not None and col.error is None:
            col.complete, col.error = False, error
    col.requests = run.requests - start_requests
    col.retries = run.retries - start_retries
    return col
