"""Tenant Veracode SINTÉTICO em processo (modo `fixture`): usado por testes, E2E e demonstração local.

- Nenhum dado real: nomes, IDs e credenciais são gerados deterministicamente a partir de rótulos fixos.
- Valida a assinatura HMAC como a Veracode faria (credencial errada => 401).
- Formatos seguem as especificações oficiais (HAL `_embedded` + `page`). A página da Applications API usa
  snake_case e a da Identity API camelCase (como declarado na especificação 1.5), exercitando os dois formatos.
Tenants: `alpha` (completo, multi-página), `beta` (outro tenant, para isolamento), `denied` (sem permissão
na Identity API => 403). Qualquer outra credencial => 401.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import uuid
from dataclasses import dataclass, field
from urllib.parse import parse_qs

import httpx

from app.veracode.hmac_auth import REQUEST_VERSION, SCHEME, signing_data

_NS = uuid.UUID('6f1c0a9e-0000-4000-8000-00000000af00')  # namespace dos IDs sintéticos (uuid5)


def synthetic_credentials(tenant: str) -> tuple[str, str]:
    """(api_id, api_key) SINTÉTICOS e determinísticos do tenant fixture. Não são credenciais Veracode."""
    api_id = hashlib.sha256(f'afrika-fixture:{tenant}:id'.encode()).hexdigest()[:32]
    api_key = hashlib.sha512(f'afrika-fixture:{tenant}:key'.encode()).hexdigest()
    return api_id, api_key


def _uid(*parts) -> str:
    return str(uuid.uuid5(_NS, ':'.join(str(p) for p in parts)))


@dataclass
class Tenant:
    name: str
    applications: list[dict] = field(default_factory=list)
    sandboxes: dict[str, list[dict]] = field(default_factory=dict)
    business_units: list[dict] = field(default_factory=list)
    teams: list[dict] = field(default_factory=list)
    team_users: dict[str, list[dict]] = field(default_factory=dict)
    users: list[dict] = field(default_factory=list)
    identity_forbidden: bool = False


def build_tenant(name: str, *, apps: int, bus: int, teams: int, users: int, label: str) -> Tenant:
    t = Tenant(name)
    bu_rows = [{'bu_id': _uid(name, 'bu', i), 'bu_legacy_id': 1000 + i, 'bu_name': f'{label} BU {i + 1}',
                'is_default': i == 0} for i in range(bus)]
    team_rows = []
    for i in range(teams):
        bu = bu_rows[i % bus]
        team_rows.append({'team_id': _uid(name, 'team', i), 'team_legacy_id': 2000 + i,
                          'team_name': f'{label} Team {i + 1:02d}',
                          'business_unit': {'bu_id': bu['bu_id'], 'bu_name': bu['bu_name']}})
    for bu in bu_rows:
        bu['teams'] = [{'team_id': tm['team_id'], 'team_name': tm['team_name']} for tm in team_rows
                       if tm['business_unit']['bu_id'] == bu['bu_id']]
    t.business_units = bu_rows

    members: dict[str, list[dict]] = {tm['team_id']: [] for tm in team_rows}
    for n in range(users):
        uid = _uid(name, 'user', n)
        user = {'user_id': uid, 'user_legacy_id': 3000 + n, 'user_name': f'{label.lower()}.usuario{n + 1:02d}',
                'first_name': 'Usuário', 'last_name': f'Sintético {n + 1:02d}', 'active': n % 11 != 10,
                'login_enabled': True, 'account_type': 'API' if n % 9 == 8 else 'USER',
                # Campos pessoais presentes na API real: a normalização deve descartá-los.
                'email_address': f'{label.lower()}.usuario{n + 1:02d}@example.invalid', 'phone': '000'}
        t.users.append(user)
        if n % 15 == 14:
            continue  # usuário sem Team
        team_idx = [n % teams] + ([(n + 1) % teams] if n % 4 == 0 and teams > 1 else [])
        for k in team_idx:
            members[team_rows[k]['team_id']].append(
                {'user_id': uid, 'user_name': user['user_name'], 'relationship': 'ADMIN' if n % 10 == 0 else 'MEMBER'})
    for tm in team_rows:
        tm['user_count'] = len(members[tm['team_id']])
    t.teams = team_rows
    t.team_users = members

    criticality = ['VERY_HIGH', 'HIGH', 'MEDIUM', 'LOW', 'VERY_LOW']
    for i in range(apps):
        guid = _uid(name, 'app', i)
        bu = bu_rows[i % bus]
        app_teams = [] if i % 17 == 16 else [team_rows[i % teams]] + (
            [team_rows[(i + 3) % teams]] if i % 5 == 0 and teams > 3 else [])
        t.applications.append({
            'guid': guid, 'id': 5000 + i, 'oid': 1, 'organization_id': 1,
            'created': '2026-01-05T12:00:00.000Z', 'modified': '2026-09-20T12:00:00.000Z',
            'last_completed_scan_date': None if i % 7 == 6 else '2026-09-28T09:30:00.000Z',
            'profile': {
                'name': f'{label} App {i + 1:03d}',
                'business_unit': {'guid': bu['bu_id'], 'id': bu['bu_legacy_id'], 'name': bu['bu_name']},
                'teams': [{'guid': tm['team_id'], 'team_id': tm['team_legacy_id'], 'team_name': tm['team_name']}
                          for tm in app_teams],
                'tags': 'sintetico,web' if i % 2 == 0 else 'sintetico,api',
                'business_criticality': criticality[i % 5],
                'custom_fields': [{'name': 'Ambiente', 'value': 'Produção' if i % 3 else 'Homologação'},
                                  {'name': 'Centro de custo', 'value': f'CC-{i % 6 + 1:02d}'}],
                'policies': [{'guid': _uid(name, 'policy'), 'name': f'{label} Política Padrão',
                              'is_default': True, 'policy_compliance_status': 'PASSED' if i % 4 else 'DID_NOT_PASS'}],
            },
        })
        n_sandboxes = 3 if i == 0 else (2 if i % 3 == 0 else 0)
        t.sandboxes[guid] = [{'guid': _uid(name, 'sandbox', i, s), 'id': 7000 + i * 10 + s,
                              'name': f'Sandbox {s + 1}', 'application_guid': guid, 'owner_username': 'sintetico',
                              'created': '2026-02-01T10:00:00.000Z', 'modified': '2026-09-01T10:00:00.000Z'}
                             for s in range(n_sandboxes)]
    return t


def default_tenants() -> dict[str, Tenant]:
    tenants = {
        'alpha': build_tenant('alpha', apps=120, bus=4, teams=8, users=45, label='Alfa'),
        'beta': build_tenant('beta', apps=7, bus=1, teams=2, users=5, label='Beta'),
        'denied': build_tenant('denied', apps=3, bus=1, teams=1, users=2, label='Restrito'),
    }
    tenants['denied'].identity_forbidden = True
    return tenants


_AUTH_RE = re.compile(r'^' + SCHEME + r' id=([0-9a-fA-F]+),ts=(\d+),nonce=([0-9a-fA-F]+),sig=([0-9a-f]{64})$')


def _json(status: int, body: dict) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})


def _error(status: int, message: str) -> httpx.Response:
    return _json(status, {'_embedded': {'errors': [{'status': str(status), 'title': message}]}})


class FixtureVeracode:
    """Handler para `httpx.MockTransport`. Registra as requisições recebidas (sem headers) para inspeção."""

    def __init__(self, tenants: dict[str, Tenant] | None = None):
        self.tenants = tenants or default_tenants()
        self._by_id = {}
        for name, tenant in self.tenants.items():
            api_id, api_key = synthetic_credentials(name)
            self._by_id[api_id.lower()] = (tenant, api_key)
        self.requests: list[tuple[str, str, str]] = []  # (tenant|?, method, path)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def _authenticate(self, request: httpx.Request) -> Tenant | None:
        m = _AUTH_RE.match(request.headers.get('Authorization', ''))
        if not m:
            return None
        api_id, ts, nonce, sig = m.groups()
        entry = self._by_id.get(api_id.lower())
        if entry is None:
            return None
        tenant, api_key = entry
        data = signing_data(api_id, request.url.host, request.url.raw_path.decode('ascii'), request.method)
        k = hmac.new(bytes.fromhex(api_key), bytes.fromhex(nonce), hashlib.sha256).digest()
        k = hmac.new(k, ts.encode(), hashlib.sha256).digest()
        k = hmac.new(k, REQUEST_VERSION, hashlib.sha256).digest()
        expected = hmac.new(k, data.encode(), hashlib.sha256).hexdigest()
        return tenant if hmac.compare_digest(expected, sig) else None

    def handle(self, request: httpx.Request) -> httpx.Response:
        tenant = self._authenticate(request)
        self.requests.append((tenant.name if tenant else '?', request.method, request.url.path))
        if tenant is None:
            return _error(401, 'Unauthorized')
        if request.method != 'GET':
            return _error(405, 'Method Not Allowed')
        q = {k: v[-1] for k, v in parse_qs(request.url.query.decode()).items()}
        page, size = int(q.get('page', 0)), min(int(q.get('size', 50)), 500)
        path = request.url.path

        if path == '/appsec/v1/applications':
            return self._page(tenant.applications, 'applications', page, size, snake=True)
        m = re.fullmatch(r'/appsec/v1/applications/([^/]+)/sandboxes', path)
        if m:
            if m.group(1) not in tenant.sandboxes:
                return _error(404, 'Not Found')
            return self._page(tenant.sandboxes[m.group(1)], 'sandboxes', page, size, snake=True)
        if path.startswith('/api/authn/') and tenant.identity_forbidden:
            return _error(403, 'Forbidden')
        if path == '/api/authn/v2/business_units':
            return self._page(tenant.business_units, 'business_units', page, size)
        if path == '/api/authn/v2/teams':
            teams = tenant.teams if q.get('all_for_org') == 'true' else tenant.teams[:1]
            return self._page(teams, 'teams', page, size)
        m = re.fullmatch(r'/api/authn/v2/teams/([^/]+)', path)
        if m:
            team = next((tm for tm in tenant.teams if tm['team_id'] == m.group(1)), None)
            if team is None:
                return _error(404, 'Not Found')
            return _json(200, {**team, 'users': tenant.team_users[team['team_id']]})
        if path == '/api/authn/v2/users':
            return self._page(tenant.users, 'users', page, size)
        return _error(404, 'Not Found')

    @staticmethod
    def _page(items: list[dict], key: str, page: int, size: int, snake: bool = False) -> httpx.Response:
        total = len(items)
        total_pages = (total + size - 1) // size
        chunk = items[page * size:(page + 1) * size]
        meta = ({'size': size, 'total_elements': total, 'total_pages': total_pages, 'number': page} if snake else
                {'size': size, 'totalElements': total, 'totalPages': total_pages, 'number': page})
        body: dict = {'_links': {}, 'page': meta}
        if chunk:
            body['_embedded'] = {key: chunk}
        return _json(200, body)
