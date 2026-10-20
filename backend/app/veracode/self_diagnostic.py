"""Diagnóstico de permissões da PRÓPRIA conta autenticada (F12). Uma única requisição: GET /api/authn/v2/users/self.

Fontes oficiais (consultadas em 2026-10-19):
- Identity API — https://docs.veracode.com/r/c_identity_intro: sem os papéis Admin API/Administrator, as contas
  ainda acessam `/users/self` e `/users/api_credentials`. `/principal` NÃO consta dessa exceção e devolve mais dados
  pessoais (e-mail, nomes, organização) sem acrescentar papéis/permissões ⇒ não usado.
- Esquema (SwaggerHub Veracode/veracode-identity_api 1.5): usuário com `account_type` (USER|API), `api_user`,
  `roles[]` (`role_name`, `role_description`, `is_api`, `role_disabled`, `ignore_team_restrictions`,
  `permissions[]`), `permissions[]` (`permission_name`), `teams[]`, `api_credentials.expiration_ts`.
- Papéis da Reporting API — https://docs.veracode.com/r/Reporting_REST_API e
  https://docs.veracode.com/r/c_API_roles_details: conta de API com o papel "Reporting API" OU usuário de interface
  com Executive, Security Lead ou Security Insights; além disso, a organização precisa ser HABILITADA pelo suporte
  Veracode (pedido por e-mail). O `role_name` exato do papel Reporting API não é documentado ⇒ a identificação é por
  nome OU descrição (heurística declarada no resultado, nunca apresentada como prova).

Minimização na leitura: guarda SÓ tipo de conta, flags booleanas, quantidade de Teams, nomes/descrições de papéis e
nomes de permissões (catálogo da plataforma, não dados pessoais) e o estado de validade da credencial. Descartados
na hora: identificadores (user_id, legacy ids, api_id, org_id), nome de usuário, e-mail, nomes, IPs, nomes de Teams,
datas de login e qualquer outro campo.

A habilitação da Reporting API para a organização NÃO é observável por esta API: com papel presente, o estado é
"habilitação não confirmada" — nunca "habilitada".
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import StrEnum

from app.veracode.errors import VeracodeError
from app.veracode.http import CollectionRun

USERS_SELF = '/api/authn/v2/users/self'
DOCS = {'identity': 'https://docs.veracode.com/r/c_identity_intro',
        'reporting': 'https://docs.veracode.com/r/Reporting_REST_API',
        'api_roles': 'https://docs.veracode.com/r/c_API_roles_details'}

_REPORTING_ROLE = re.compile(r'reporting', re.I)                       # "Reporting API (User)"
_REPORTING_UI_ROLE = re.compile(r'executive|security\s*lead|security\s*insights', re.I)
_REPORTING_PERMISSION = re.compile(r'analytics|generate\s*reports?', re.I)
# Papéis que permitem escrita/administração (o Afrika só lê): heurística por nome/descrição, só para alerta.
_WRITE_ROLE = re.compile(r'admin|delete|submit|creator|approver|upload|mitigation', re.I)
_TEXT_MAX = 120


class ReportingRoleState(StrEnum):
    # papel compatível presente; a habilitação da organização pelo suporte Veracode não é observável
    ROLE_PRESENT_ENABLEMENT_NOT_CONFIRMED = 'ROLE_PRESENT_ENABLEMENT_NOT_CONFIRMED'
    # lista de papéis recebida e nenhum compatível ⇒ permissão ausente (falta conceder o papel)
    ROLE_NOT_FOUND = 'ROLE_NOT_FOUND'
    # resposta sem lista de papéis utilizável (ou tipo de conta desconhecido)
    UNKNOWN = 'UNKNOWN'


def _bool(v) -> bool | None:
    return v if isinstance(v, bool) else None


def _text(v) -> str | None:
    return v.strip()[:_TEXT_MAX] if isinstance(v, str) and v.strip() else None


def _permission_names(raw) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [n for n in (_text(p.get('permission_name')) for p in raw if isinstance(p, dict)) if n]


def _role(raw: dict) -> dict:
    return {'role_name': _text(raw.get('role_name')), 'role_description': _text(raw.get('role_description')),
            'is_api': _bool(raw.get('is_api')), 'role_disabled': _bool(raw.get('role_disabled')),
            'ignore_team_restrictions': _bool(raw.get('ignore_team_restrictions')),
            'permissions': sorted(set(_permission_names(raw.get('permissions'))))}


def _credential(raw, now: datetime) -> dict:
    """Só a validade (nunca api_id/api_secret/datas de uso)."""
    exp = raw.get('expiration_ts') if isinstance(raw, dict) else None
    if not isinstance(exp, str):
        return {'expiration': 'UNKNOWN', 'days_to_expiration': None}
    try:
        moment = datetime.fromisoformat(exp.replace('Z', '+00:00'))
    except ValueError:
        return {'expiration': 'UNKNOWN', 'days_to_expiration': None}
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    days = (moment - now).days
    return {'expiration': 'EXPIRED' if moment <= now else 'VALID', 'days_to_expiration': max(days, 0)}


def _matches(role: dict, pattern: re.Pattern) -> bool:
    return any(pattern.search(role[k] or '') for k in ('role_name', 'role_description'))


def diagnose(raw: dict, *, now: datetime | None = None) -> dict:
    """Resultado minimizado e classificado. `raw` = corpo de GET /users/self (nunca guardado)."""
    if not isinstance(raw, dict):
        raise VeracodeError('invalid_response')
    now = now or datetime.now(timezone.utc)
    account_type = raw.get('account_type') if raw.get('account_type') in ('USER', 'API') else None
    roles_raw = raw.get('roles')
    roles = [_role(r) for r in roles_raw if isinstance(r, dict)] if isinstance(roles_raw, list) else None
    active_roles = [r for r in roles or [] if r['role_disabled'] is not True]
    user_permissions = sorted(set(_permission_names(raw.get('permissions'))))
    all_permissions = sorted(set(user_permissions).union(*(r['permissions'] for r in active_roles)))
    teams = raw.get('teams')
    teams_count = len(teams) if isinstance(teams, list) else None
    ignore_teams = any(r['ignore_team_restrictions'] is True for r in active_roles)

    limitations: list[str] = []
    api_flag = _bool(raw.get('api_user'))
    kind = account_type or ({True: 'API', False: 'USER'}.get(api_flag) if api_flag is not None else None)
    # Tipo ausente (observado na API real, F12): avaliam-se os DOIS critérios documentados — papel "Reporting API"
    # (conta de API) ou Executive/Security Lead/Security Insights (usuário de interface).
    patterns = {'API': (_REPORTING_ROLE,), 'USER': (_REPORTING_UI_ROLE,)}.get(kind, (_REPORTING_ROLE,
                                                                                     _REPORTING_UI_ROLE))
    candidates = [r['role_name'] or r['role_description'] for r in active_roles
                  if any(_matches(r, p) for p in patterns)]
    perm_hits = [p for p in all_permissions if _REPORTING_PERMISSION.search(p)]
    if kind is None:
        limitations.append('Resposta sem account_type/api_user: tipo da conta não informado pela API; avaliados os '
                           'dois critérios documentados (papel Reporting API ou Executive/Security Lead/Security '
                           'Insights)')
    if roles is None:
        state = ReportingRoleState.UNKNOWN
        limitations.append('Resposta sem lista de papéis: papel da Reporting API não avaliado')
    elif candidates:
        state = ReportingRoleState.ROLE_PRESENT_ENABLEMENT_NOT_CONFIRMED
        limitations.append('Papel compatível presente: a HABILITAÇÃO da Reporting API para a organização (pedido ao '
                           'suporte Veracode) não é exposta pela Identity API — um 403 continua possível')
    else:
        state = ReportingRoleState.ROLE_NOT_FOUND
        limitations.append('Nenhum papel compatível entre os papéis ativos retornados: permissão AUSENTE (concessão '
                           'pelo administrador da conta Veracode, decisão do cliente)')
    limitations.append('role_name exato do papel Reporting API não é documentado: identificação por nome/descrição '
                       f'({" | ".join(p.pattern for p in patterns)}); conferir no portal em Admin → Users')
    write_roles = sorted(r['role_name'] or r['role_description'] or '?' for r in active_roles
                         if _matches(r, _WRITE_ROLE))
    if write_roles:
        limitations.append(f'{len(write_roles)} papel(éis) com escrita/administração na credencial usada: o Afrika só '
                           'lê (trava GET-only), mas a credencial não é de privilégio mínimo')
    if teams_count and not ignore_teams:
        limitations.append(f'Conta vinculada a {teams_count} Team(s) sem papel que ignore restrições de Team: dados '
                           'visíveis (inclusive na Reporting API) podem se limitar às aplicações desses Teams')

    return {
        'endpoint': f'GET {USERS_SELF}',
        'account': {'account_type': account_type, 'api_user': _bool(raw.get('api_user')),
                    'active': _bool(raw.get('active')), 'login_enabled': _bool(raw.get('login_enabled')),
                    'saml_user': _bool(raw.get('saml_user')), 'ip_restricted': _bool(raw.get('ip_restricted')),
                    'teams_count': teams_count, 'team_restricted': None if teams_count is None
                    else bool(teams_count) and not ignore_teams},
        'credential': _credential(raw.get('api_credentials'), now),
        'roles': None if roles is None else sorted(roles, key=lambda r: (r['role_name'] or '', r['role_description']
                                                                         or '')),
        'permissions': all_permissions,
        'reporting_api': {
            'required': {'API': 'Conta de API com o papel "Reporting API"',
                         'USER': 'Usuário com Executive, Security Lead ou Security Insights'}.get(
                kind, 'Conta de API com o papel "Reporting API" OU usuário com Executive, Security Lead ou Security '
                      'Insights') + ' + habilitação da organização pelo suporte Veracode',
            'account_kind_evaluated': kind or 'UNKNOWN',
            'role_state': state.value, 'matching_roles': sorted(c for c in candidates if c),
            'matching_permissions': perm_hits, 'enablement': 'NOT_OBSERVABLE',
        },
        'least_privilege': {'write_or_admin_roles': write_roles, 'read_only_enforced_locally': True,
                            'heuristic': _WRITE_ROLE.pattern},
        'limitations': limitations, 'docs': DOCS,
    }


def interpret_reporting_403(diag: dict | None) -> dict:
    """Leitura objetiva do 403 da Reporting API à luz do diagnóstico (nunca presume licença)."""
    state = (diag or {}).get('reporting_api', {}).get('role_state', ReportingRoleState.UNKNOWN.value)
    if state == ReportingRoleState.ROLE_NOT_FOUND.value:
        cause = 'MISSING_ROLE'
        text = ('A conta autenticada não tem papel compatível com a Reporting API: conceder o papel (administrador '
                'da conta Veracode) e, se ainda não feito, pedir a habilitação ao suporte')
    elif state == ReportingRoleState.ROLE_PRESENT_ENABLEMENT_NOT_CONFIRMED.value:
        cause = 'ENABLEMENT_NOT_CONFIRMED'
        text = ('Papel compatível presente; o 403 é compatível com organização NÃO habilitada para a Reporting API '
                '(confirmar com o suporte Veracode) ou com restrição não exposta pela Identity API')
    else:
        cause = 'UNDETERMINED'
        text = 'Papéis da conta não avaliados: causa do 403 indeterminada'
    return {'cause': cause, 'explanation': text, 'license_assumed': False}


async def run_self_diagnostic(run: CollectionRun) -> dict:
    """UMA requisição GET (sem query). Erros viram código seguro; o corpo bruto nunca sai desta função."""
    try:
        raw = await run.get_json(USERS_SELF, label='identity:users_self')
    except VeracodeError as exc:
        return {'status': 'error', 'endpoint': f'GET {USERS_SELF}', 'error': exc.as_dict(),
                'requests': run.requests, 'retries': run.retries}
    out = diagnose(raw)
    return {'status': 'ok', **out, 'reporting_403_reading': interpret_reporting_403(out),
            'requests': run.requests, 'retries': run.retries}
