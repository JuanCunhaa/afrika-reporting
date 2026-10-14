"""Adaptadores dos endpoints OFICIAIS da Veracode usados na descoberta (F02) e normalização dos campos.

Especificações oficiais (SwaggerHub, organização Veracode):
- Applications API 1.0: https://app.swaggerhub.com/apis/Veracode/veracode-applications-api-specification/1.0
- Identity API 1.5:     https://app.swaggerhub.com/apis/Veracode/veracode-identity_api/1.5

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


def _str(v) -> str | None:
    return v if isinstance(v, str) else None


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
    }


def normalize_membership(raw: dict) -> dict:
    return {'user_id': raw.get('user_id'), 'user_name': _str(raw.get('user_name')),
            'relationship': _str(raw.get('relationship'))}


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
