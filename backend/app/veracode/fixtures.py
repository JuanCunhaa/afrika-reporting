"""Tenant Veracode SINTÉTICO em processo (modo `fixture`): usado por testes, E2E e demonstração local.

- Nenhum dado real: nomes, IDs e credenciais são gerados deterministicamente a partir de rótulos fixos.
- Valida a assinatura HMAC como a Veracode faria (credencial errada => 401).
- Formatos seguem o observado na API REAL (homologação F02.1): HAL `_embedded` + `page` em snake_case nas duas
  APIs; Team sem `user_count`; usuário sem `account_type`; `relationship` do membro como objeto `{name, display_name}`;
  membro do Team com `team_count` (quantidade de Teams do usuário).
  (camelCase, aceito por precaução porque a especificação Identity 1.5 o declara, é coberto em test_veracode_http.)
Findings (F04, Findings API v2): `/appsec/v2/applications/{guid}/findings` com `scan_type` (SCA nunca combinado
com outros tipos => 400) e `context`=GUID do sandbox (sem `context` => Policy). Findings sintéticos repetem o mesmo
`issue_id` entre Policy e sandboxes e o mesmo componente/vulnerabilidade SCA com `issue_id` diferentes — para testar
deduplicação sem supor identidade. Datas de identificação ficam na virada de agosto/setembro/outubro de 2026.
F04.1: perfil com `scans[]` (só STATIC, como no real), Summary Report derivado dos findings da Policy (chave
`flaw-status` com hífen e campos pessoais que a normalização descarta, como no real) e SCA Agent por aplicação.
`sca_500_without_components` imita o real (só Policy observada): Findings SCA => 500 sem componentes.
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
    # (application_guid, sandbox_guid|None, scan_type) -> findings no formato da Findings API
    findings: dict[tuple[str, str | None, str], list[dict]] = field(default_factory=dict)
    sca_sandbox_unsupported: bool = False  # simula 400 para SCA em sandbox (suporte NÃO homologado)
    sca_500_without_components: bool = False  # F04.1: Findings SCA => 500 se a aplicação não tem componentes
    sca_projects: dict[str, list[dict]] = field(default_factory=dict)  # app guid -> projetos do agente vinculados


def make_finding(issue_id: int, scan_type: str, *, severity: int | None, status: str | None = 'OPEN',
                 resolution: str = 'UNRESOLVED', resolution_status: str = 'NONE',
                 first_found: str | None = '2026-09-15T12:00:00.000Z', last_seen: str = '2026-09-20T10:00:00.000Z',
                 cwe: tuple[int, str] | None = None, sandbox_guid: str | None = None, component: str | None = None,
                 filename: str | None = None, version: str | None = None, vulnerability: str | None = None,
                 dep_mode: str | None = None) -> dict:
    """Finding SINTÉTICO no formato da Findings API v2 (inclui campos que a normalização descarta)."""
    details: dict = {'severity': severity, 'file_path': 'src/sintetico/Arquivo.java', 'file_line_number': 42,
                     'module': 'sintetico.jar', 'procedure': 'metodoSintetico'}
    if scan_type == 'SCA':
        details = {'severity': severity, 'component_id': component, 'component_filename': filename,
                   'version': version, 'licenses': [{'license_id': 'MIT', 'risk_rating': '2'}],
                   'metadata': {'sca_scan_mode': 'UPLOAD', 'sca_dep_mode': dep_mode},
                   'cve': None if vulnerability is None else {'name': vulnerability, 'cvss': 7.5,
                                                              'severity': 'High'}}
    if cwe:
        details['cwe'] = {'id': cwe[0], 'name': cwe[1]}
    finding_status = {'first_found_date': first_found, 'status': status, 'resolution': resolution,
                      'resolution_status': resolution_status, 'last_seen_date': last_seen, 'new': False,
                      'mitigation_review_status': 'NONE'}
    return {'issue_id': issue_id, 'scan_type': scan_type, 'description': 'Descrição sintética (descartada)',
            'count': 1, 'context_type': 'SANDBOX' if sandbox_guid else 'APPLICATION',
            'context_guid': sandbox_guid, 'violates_policy': (severity or 0) >= 3, 'build_id': 1,
            'finding_status': finding_status, 'finding_details': details,
            'annotations': [{'comment': 'anotação sintética (descartada)'}]}


_CWES = [(79, 'Cross-site Scripting'), (89, 'SQL Injection'), (117, 'Improper Output Neutralization for Logs'),
         (327, 'Use of a Broken or Risky Cryptographic Algorithm'), (601, 'URL Redirection to Untrusted Site'),
         (209, 'Generation of Error Message Containing Sensitive Information')]
_FOUND = ['2026-07-10T08:00:00.000Z', '2026-08-31T23:30:00.000Z', '2026-09-01T00:00:00.000Z',
          '2026-09-15T12:00:00.000Z', '2026-09-30T23:59:59.999Z', '2026-10-01T00:00:00.000Z']


def _synthetic_findings(t: Tenant, name: str, i: int, guid: str) -> None:
    n = i % 6
    policy = []
    for k in range(n):
        status = 'CLOSED' if k == 4 else 'OPEN'
        approved = status == 'OPEN' and (i + k) % 9 == 0
        policy.append(make_finding(1000 + k, 'STATIC', severity=(i + k) % 6, status=status,
                                   resolution='MITIGATED' if approved else ('FIXED' if status == 'CLOSED'
                                                                            else 'UNRESOLVED'),
                                   resolution_status='APPROVED' if approved else 'NONE',
                                   first_found=_FOUND[(i + 2 * k) % 6], cwe=_CWES[(i + k) % 6]))
    t.findings[(guid, None, 'STATIC')] = policy
    comp_a = _uid(name, 'component', i % 3)
    t.findings[(guid, None, 'SCA')] = [
        make_finding(9000, 'SCA', severity=4, component=comp_a, filename=f'biblioteca-{i % 3}.jar',
                     version='1.0.0', vulnerability=f'SYNTH-VULN-000{1 + i % 3}', dep_mode='DIRECT',
                     cwe=(502, 'Deserialization of Untrusted Data')),
        make_finding(9001, 'SCA', severity=2, component=_uid(name, 'component', 'shared'),
                     filename='biblioteca-compartilhada.jar', version='2.3.1', vulnerability='SYNTH-VULN-0100',
                     dep_mode='TRANSITIVE')] if i % 4 == 0 else []
    for s, sandbox in enumerate(t.sandboxes[guid]):
        sb = sandbox['guid']
        repeated = [make_finding(1000, 'STATIC', severity=policy[0]['finding_details']['severity'],
                                 first_found='2026-09-02T09:00:00.000Z', cwe=_CWES[i % 6], sandbox_guid=sb)] \
            if n else []
        t.findings[(guid, sb, 'STATIC')] = repeated + [
            make_finding(2000 + s, 'STATIC', severity=(i + s) % 5 + 1, first_found='2026-09-10T09:00:00.000Z',
                         cwe=_CWES[s % 6], sandbox_guid=sb),
            make_finding(2100, 'STATIC', severity=3, first_found='2026-09-11T09:00:00.000Z', cwe=_CWES[1],
                         sandbox_guid=sb)]  # mesmo issue_id em todos os sandboxes da aplicação
        t.findings[(guid, sb, 'SCA')] = [
            make_finding(9500 + s, 'SCA', severity=4, component=comp_a, filename=f'biblioteca-{i % 3}.jar',
                         version='1.0.0', vulnerability=f'SYNTH-VULN-000{1 + i % 3}', dep_mode='DIRECT',
                         sandbox_guid=sb)] if i % 4 == 0 else []


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
                'login_enabled': True, 'saml_user': False, 'scim_user': False,
                # Campos pessoais presentes na API real: a normalização deve descartá-los.
                'email_address': f'{label.lower()}.usuario{n + 1:02d}@example.invalid', 'phone': '000'}
        t.users.append(user)
        if n % 15 == 14:
            continue  # usuário sem Team
        team_idx = [n % teams] + ([(n + 1) % teams] if n % 4 == 0 and teams > 1 else [])
        for k in team_idx:
            members[team_rows[k]['team_id']].append(
                {'user_id': uid, 'user_name': user['user_name'], 'team_count': len(team_idx),
                 'relationship': {'name': 'ADMIN', 'display_name': 'Administrador'} if n % 10 == 0 else
                 {'name': 'MEMBER', 'display_name': 'Membro'}})
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
            'scans': [] if i % 7 == 6 else [{'scan_type': 'STATIC', 'status': 'PUBLISHED',
                                             'modified_date': '2026-09-28T09:30:00.000Z', 'internal_status': 'x',
                                             'scan_url': f'Cid:{9000 + i}'}],
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
        _synthetic_findings(t, name, i, guid)
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
            return self._page(tenant.applications, 'applications', page, size)
        m = re.fullmatch(r'/appsec/v1/applications/([^/]+)/sandboxes', path)
        if m:
            if m.group(1) not in tenant.sandboxes:
                return _error(404, 'Not Found')
            return self._page(tenant.sandboxes[m.group(1)], 'sandboxes', page, size)
        m = re.fullmatch(r'/appsec/v2/applications/([^/]+)/findings', path)
        if m:
            return self._findings(tenant, m.group(1), q, page, size)
        m = re.fullmatch(r'/appsec/v2/applications/([^/]+)/summary_report', path)
        if m:
            return self._summary(tenant, m.group(1), q.get('context'))
        m = re.fullmatch(r'/srcclr/v3/applications/([^/]+)/projects', path)
        if m:
            if m.group(1) not in tenant.sandboxes:
                return _error(404, 'Not Found')
            return _json(200, {'application': {'guid': m.group(1), 'name': 'sintético'},
                               'linked_projects': tenant.sca_projects.get(m.group(1), [])})
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
    def _findings(tenant: Tenant, app_guid: str, q: dict, page: int, size: int) -> httpx.Response:
        if app_guid not in tenant.sandboxes:
            return _error(404, 'Not Found')
        types = [t.strip().upper() for t in (q.get('scan_type') or '').split(',') if t.strip()] \
            or ['STATIC', 'DYNAMIC', 'MANUAL']  # sem scan_type: SCA fica de fora (documentação oficial)
        if 'SCA' in types and len(types) > 1:
            return _error(400, 'SCA cannot be combined with other scan types')
        context = q.get('context')
        if context and context not in {sb['guid'] for sb in tenant.sandboxes[app_guid]}:
            return _error(404, 'Not Found')
        if context and 'SCA' in types and tenant.sca_sandbox_unsupported:
            return _error(400, 'Bad Request')
        if 'SCA' in types and not context and tenant.sca_500_without_components                 and not tenant.findings.get((app_guid, None, 'SCA')):
            return httpx.Response(500, headers={'Content-Type': 'application/json'})  # corpo vazio, como no real
        items = [f for t in types for f in tenant.findings.get((app_guid, context, t), [])]
        return FixtureVeracode._page(sorted(items, key=lambda f: f['issue_id']), 'findings', page, size)

    @staticmethod
    def _summary(tenant: Tenant, app_guid: str, context: str | None) -> httpx.Response:
        idx = next((i for i, a in enumerate(tenant.applications) if a['guid'] == app_guid), None)
        if idx is None:
            return _error(404, 'Not Found')
        static = tenant.findings.get((app_guid, context, 'STATIC'), [])
        open_ = [f for f in static if f['finding_status']['status'] == 'OPEN']
        sev = {s: sum(f['finding_details']['severity'] == s for f in open_) for s in range(6)}
        sca = tenant.findings.get((app_guid, context, 'SCA'), [])
        components = {f['finding_details']['component_id'] for f in sca}
        scanned = bool(tenant.applications[idx].get('last_completed_scan_date'))
        body = {
            'app_name': 'nome sintético (descartado)', 'submitter': 'Pessoa Sintética', 'business_owner': 'Dono',
            'build_id': 100 + idx, 'analysis_id': 200 + idx, 'is_latest_build': True,
            'generation_date': '2026-10-10 10:00:00 UTC', 'last_update_time': '2026-09-28 09:30:00 UTC',
            'policy_compliance_status': 'Did Not Pass', 'total_flaws': len(open_),
            'flaws_not_mitigated': sum(f['finding_status']['resolution_status'] != 'APPROVED' for f in open_),
            'severity': [{'level': s, 'category': ([{'category_name': 'Sintética', 'severity': 'X', 'count': n}]
                                                   if n else [])} for s, n in sev.items()],
            'flaw-status': {'new': 0, 'reopen': 0, 'open': len(open_), 'fixed': 0, 'total': len(open_),
                            'not_mitigated': len(open_)},
            'software_composition_analysis': {'third_party_components': len(components),
                                              'components_violated_policy': sum(1 for f in sca if
                                                                                f['finding_details']['severity'] >= 4),
                                              'sca_service_available': 'true', 'vulnerable_components': {}},
        }
        if scanned:
            body['static_analysis'] = {
                'published_date': '2026-09-28 09:30:00 UTC', 'submitted_date': '2026-09-28 09:00:00 UTC',
                'modules': {'module': [{'name': 'sintetico.jar', 'loc': 1000 + 100 * idx,
                                        **{f'numflawssev{s}': n for s, n in sev.items()}}]}}
        return _json(200, body)

    @staticmethod
    def _page(items: list[dict], key: str, page: int, size: int) -> httpx.Response:
        total = len(items)
        total_pages = (total + size - 1) // size
        chunk = items[page * size:(page + 1) * size]
        meta = {'size': size, 'total_elements': total, 'total_pages': total_pages, 'number': page}
        body: dict = {'_links': {}, 'page': meta}
        if chunk:
            body['_embedded'] = {key: chunk}
        return _json(200, body)
