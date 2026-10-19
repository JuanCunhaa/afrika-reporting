"""F10 — piloto operacional SINTÉTICO integral (um ciclo mensal completo; nenhuma Veracode real).

Cliente + subcliente → escopos → coleta → competência → snapshots → conferência com a "plataforma" (oráculo
independente calculado direto do tenant sintético, não do nosso motor) → aprovação → histórico (mês anterior aprovado)
→ apresentação no modelo reutilizável `afrika-modelo@2` → interpretação local revisada → PPTX/PDF → backup e
restauração do SQLite. Em cada passagem o MESMO número é conferido (coleta = snapshot = conferência = visualização =
PPTX/PDF). Exportação segue a política F07 (`AFRIKA_EXPORT_TESTS=required` => falha sem motor).
Os testes dependem da ordem (estado compartilhado no módulo); rodar o arquivo inteiro.
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
import zipfile
from pathlib import Path

import pytest

from app import backup, db
from app.metrics.registry import REGISTRY
from app.presentations.charts import EXECUTIVE_LABEL, SEVERITY_LABEL
from app.veracode.fixtures import FixtureVeracode, build_tenant
from conftest import sqlite_url
from test_export_engine import ENGINE_OK, ENGINE_REASON, REQUIRED
from test_f09_acceptance import World
from test_interpretation_export import pdf_text, pptx_text
from test_metrics import gamma_tenant, ids

OP = 'Operadora Piloto Sintético'
APPROVER = 'Aprovadora Piloto Sintético'
REVIEWER = 'Revisora Piloto Sintético'
CHECKER = 'Conferente Piloto Sintético'
PREV, LABEL = '2026-08', '2026-09'
SEVS = {5: 'VERY_HIGH', 4: 'HIGH', 3: 'MEDIUM', 2: 'LOW', 1: 'VERY_LOW', 0: 'INFORMATIONAL'}
NON_DATA_FIELDS = {'competence', 'name', 'unit'}

needs_engine = pytest.mark.skipif(not ENGINE_OK and not REQUIRED,
                                  reason=f'motor de exportação indisponível ({ENGINE_REASON})')


def oracle_open(tenant, app_guids: list[str], scan_type: str, *, sandbox: bool = False) -> dict:
    """'Valor oficial' do piloto: lido DIRETO dos findings do tenant (aberto = OPEN e mitigação não aprovada)."""
    out = {k: 0 for k in SEVS.values()}
    for (guid, sb, stype), findings in tenant.findings.items():
        if guid not in app_guids or stype != scan_type or (sb is not None) != sandbox:
            continue
        for f in findings:
            st = f['finding_status']
            if st['status'] == 'OPEN' and st['resolution_status'] != 'APPROVED':
                out[SEVS[f['finding_details']['severity']]] += 1
    return {**out, 'total': sum(out.values())}


def value_points(obj, label: str):
    """Todos os pontos com valor da competência `label` na visualização (recursivo)."""
    if isinstance(obj, dict):
        if obj.get('state') == 'VALUE' and obj.get('competence') == label and 'metric_id' in obj:
            yield obj
        for v in obj.values():
            yield from value_points(v, label)
    elif isinstance(obj, list):
        for v in obj:
            yield from value_points(v, label)


def same(point: dict, snapshot: dict) -> None:
    """Ponto da visualização = snapshot aprovado (número principal e, quando exposto, o valor inteiro)."""
    value = snapshot['value']
    if 'headline' in point:  # ponto resolvido
        assert point['headline'] == snapshot['headline'], point['metric_id']
    elif point.get('x') in (point['metric_id'], point['competence']):  # KPI/barra do indicador ou ponto da série
        assert point['y'] == snapshot['headline'], point['metric_id']
    else:  # parte do indicador (ex.: uma severidade): tem de existir no valor aprovado com o mesmo número
        parts = value if isinstance(value, dict) else {}
        parts = {**parts, **{label: parts[k] for labels in (SEVERITY_LABEL, EXECUTIVE_LABEL)
                             for k, label in labels.items() if k in parts}}
        assert point['x'] in parts and point['y'] == parts[point['x']], (point['metric_id'], point['x'], point['y'])
    if 'value' in point:
        assert point['value'] == snapshot['value'], point['metric_id']


def chart_numbers(pptx: bytes) -> list[float]:
    with zipfile.ZipFile(io.BytesIO(pptx)) as z:
        xml = ''.join(z.read(n).decode('utf-8') for n in z.namelist() if n.startswith('ppt/charts/chart'))
    return [float(v) for v in re.findall(r'<c:v>([0-9.]+)</c:v>', xml)]


class Pilot(World):
    def run_for(self, kind: str, owner_id: str, label: str) -> dict:
        import time
        r = self.call('POST', '/api/metrics/runs', 202, owner_kind=kind, owner_id=owner_id, competence=label)
        end = time.monotonic() + 30
        while time.monotonic() < end:
            body = self.call('GET', f'/api/metrics/runs/{r["run_id"]}')
            if body['status'] in ('done', 'cancelled', 'failed'):
                return body
            time.sleep(0.02)
        raise AssertionError('coleta não terminou')

    def detail(self, cid: str, n: int) -> dict:
        return self.call('GET', f'/api/competences/{cid}/revisions/{n}')

    def approve(self, cid: str, n: int, required: list[str]) -> dict:
        base = f'/api/competences/{cid}/revisions/{n}'
        self.call('PUT', f'{base}/required', metric_ids=required, operator=OP, expected_lock_version=self.lock(cid, n))
        self.call('POST', f'{base}/submit', operator=OP, expected_lock_version=self.lock(cid, n))
        out = self.call('POST', f'{base}/approve', approver=APPROVER, note='piloto F10 (sintético)',
                        expected_lock_version=self.lock(cid, n))
        # F11: toda aprovação passa antes por um backup automático verificado (falha bloquearia a aprovação)
        made = out['approval_backup']
        assert made['integrity'] == 'ok' and made['alembic_revision'] == db.head_revision()
        self.approval_backups.append(made)
        return self.detail(cid, n)


@pytest.fixture(scope='module')
def p(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('f10')
    url = sqlite_url(tmp / 'piloto.sqlite3')
    db.upgrade(url)
    tenant = gamma_tenant()
    fake = FixtureVeracode({'gamma': tenant, 'beta': build_tenant('beta', apps=2, bus=1, teams=1, users=1,
                                                                  label='Beta')})
    mp = pytest.MonkeyPatch()
    mp.setenv('AFRIKA_EXPORT_DIR', str(tmp / 'exports'))
    pilot = Pilot(url, tmp, tenant, fake, {}, mp)
    pilot.approval_backups = []  # F11: backups automáticos feitos antes de cada aprovação
    pilot.s['logs'] = logs = []
    handler = logging.Handler(logging.DEBUG)
    handler.emit = lambda record: logs.append(record.getMessage())
    root = logging.getLogger()
    previous = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    pilot.start()
    try:
        yield pilot
    finally:
        pilot.stop()
        root.removeHandler(handler)
        root.setLevel(previous)
        mp.undo()


def snap(detail: dict, metric_id: str) -> dict:
    return next(s for s in detail['snapshots'] if s['metric_id'] == metric_id)


def M(run: dict, metric_id: str) -> dict:
    return next(m for m in run['result']['metrics'] if m['metric_id'] == metric_id)


# ---------------------------------------------------------------- 1. cadastro e escopos

def test_01_client_subclient_and_scopes(p):
    conn = p.call('POST', '/api/connections', 201, name='Conexão Piloto Sintética', region='commercial',
                  credential_ref='env:VC_GAMMA')
    c = p.call('POST', '/api/clients', 201, name='Cliente Piloto Sintético', connection_id=conn['id'])
    assert c['timezone'] == 'America/Sao_Paulo'  # padrão: competências no fuso de São Paulo
    sub = p.call('POST', f'/api/clients/{c["id"]}/subclients', 201, name='Unidade Piloto Sintética')
    I = ids(p.tenant)
    p.call('PUT', f'/api/scopes/clients/{c["id"]}/applications', 201,
           rule={'field': 'business_unit.id', 'cmp': 'in', 'values': I['bu']}, expected_version=0)
    p.call('PUT', f'/api/scopes/subclients/{sub["id"]}/applications', 201,
           rule={'field': 'business_unit.id', 'cmp': 'eq', 'value': I['bu'][0]}, expected_version=0)
    prev = p.call('POST', f'/api/scope-preview/clients/{c["id"]}', domain='applications', sample_limit=200)
    sub_apps = sorted(r['id'] for r in next(s for s in prev['subclients'] if s['id'] == sub['id'])['sample'])
    assert prev['universe']['included'] == 4 and sub_apps == sorted([I['apps'][0], I['apps'][2]])
    p.s.update(client=c, sub=sub, apps=I['apps'], sub_apps=sub_apps)


# ---------------------------------------------------------------- 2. mês anterior (histórico aprovado)

def test_02_previous_month_collected_and_approved(p):
    run = p.run_for('client', p.s['client']['id'], PREV)
    assert run['status'] == 'done'
    out = p.call('POST', '/api/competences/from-run', 201, run_id=run['run_id'], operator=OP)
    d = p.approve(out['competence_id'], out['revision'], ['apps.total', 'sast.policy.open.by_severity'])
    assert d['status'] == 'APPROVED'
    p.s.update(prev_cid=out['competence_id'], prev_detail=d)


# ---------------------------------------------------------------- 3. coleta e snapshots da competência

def test_03_collection_equals_snapshots(p):
    run_c = p.run_for('client', p.s['client']['id'], LABEL)
    run_s = p.run_for('subclient', p.s['sub']['id'], LABEL)
    assert run_c['status'] == run_s['status'] == 'done'
    out = p.call('POST', '/api/competences/from-run', 201, run_id=run_c['run_id'], operator=OP)
    cid, n = out['competence_id'], out['revision']
    d = p.detail(cid, n)
    assert d['competence']['competence'] == LABEL and d['competence']['timezone'] == 'America/Sao_Paulo'
    assert len(d['snapshots']) == len(REGISTRY)
    for m in run_c['result']['metrics']:  # coleta → snapshot: mesmo valor; sem valor ⇒ sem valor (nunca 0)
        s = snap(d, m['metric_id'])
        assert s['value'] == (m['value'] if m['status'] == 'VALIDATED' else None), m['metric_id']
        assert s['source']['status'] == m['status']
    sub_out = p.call('POST', '/api/competences/from-run', 201, run_id=run_s['run_id'], operator=OP)
    sub_d = p.detail(sub_out['competence_id'], sub_out['revision'])
    assert snap(sub_d, 'apps.total')['value'] == 2  # subcliente isolado: só a BU 0
    p.s.update(cid=cid, n=n, run_c=run_c, sub_cid=sub_out['competence_id'], sub_n=sub_out['revision'])


# ---------------------------------------------------------------- 4. conferência com a "plataforma"

def test_04_conference_against_independent_oracle(p):
    cid, n = p.s['cid'], p.s['n']
    sheet = p.call('GET', f'/api/competences/{cid}/revisions/{n}/conference')
    rows = {m['metric_id']: m for m in sheet['metrics']}
    day = rows['apps.total']['snapshot']['collected_on']
    oracle = {'apps.total': {'value': len(p.s['apps'])},
              'sast.policy.open.by_severity': oracle_open(p.tenant, p.s['apps'], 'STATIC'),
              'sca.policy.open.by_severity': oracle_open(p.tenant, p.s['apps'], 'SCA'),
              'sast.sandbox.open.by_severity': oracle_open(p.tenant, p.s['apps'], 'STATIC', sandbox=True),
              'sca.sandbox.open.by_severity': oracle_open(p.tenant, p.s['apps'], 'SCA', sandbox=True)}
    for mid, official in oracle.items():
        out = p.call('POST', f'/api/competences/{cid}/revisions/{n}/conference/{mid}', 201, operator=CHECKER,
                     checked_on=day, filters_confirmed=True, official=official,
                     evidence='Piloto sintético: oráculo calculado do tenant fixture')
        assert out['comparison'] == 'MATCH', (mid, out['conference']['entries'])
        assert out['homologated'] is True
    s = p.call('GET', f'/api/competences/{cid}/revisions/{n}/conference')['summary']
    assert s['HOMOLOGATED'] == len(oracle) and s['NOT_APPLICABLE'] == 12 and s['BLOCKED_EXTERNAL'] == 2
    p.s['oracle'] = oracle


# ---------------------------------------------------------------- 5. aprovação e histórico

def test_05_approval_and_history(p):
    cid, n = p.s['cid'], p.s['n']
    required = ['apps.total', 'sast.policy.open.by_severity', 'sca.policy.open.by_severity']
    d = p.approve(cid, n, required)
    assert d['status'] == 'APPROVED' and p.call('GET', f'/api/competences/{cid}/integrity')['ok'] is True
    made = p.approval_backups[-1]  # F11: cópia do estado imediatamente ANTERIOR à aprovação, fora do repositório
    file = p.tmp / 'backups' / made['file']
    assert backup.inspect(file).sha256 == made['sha256']
    # a conferência continua válida sobre a revisão aprovada (snapshot imutável ⇒ não fica desatualizada)
    rows = {m['metric_id']: m for m in p.call('GET', f'/api/competences/{cid}/revisions/{n}/conference')['metrics']}
    assert all(rows[m]['comparison'] == 'MATCH' for m in p.s['oracle'])
    cl = p.s['client']['id']
    series = p.call('GET', f'/api/history/client/{cl}/series?metric_id=apps.total&months=2')
    pts = {x['competence']: (x['state'], x['value']) for x in series['points']}
    assert pts == {PREV: ('APPROVED', 4), LABEL: ('APPROVED', 4)}
    cmp_ = p.call('GET', f'/api/history/client/{cl}/compare?competence={LABEL}&metric_id=sast.policy.open.by_severity')
    item = next(i for i in cmp_['items'] if i['metric_id'] == 'sast.policy.open.by_severity')
    assert cmp_['previous_competence'] == PREV and item['delta'] == 0  # mesmo tenant ⇒ sem variação
    p.s['approved'] = d


# ---------------------------------------------------------------- 6. apresentação no modelo reutilizável

def test_06_presentation_from_reusable_template(p):
    cl, cid = p.s['client']['id'], p.s['cid']
    p.call('POST', '/api/presentation-templates/builtin', operator=OP)
    p.call('PUT', f'/api/template-selection/client/{cl}', template_key='afrika-modelo', template_version=2,
           operator=OP)
    tpl = p.call('GET', '/api/presentation-templates/afrika-modelo/versions/2?with_definition=true')
    assert 'Cliente Piloto' not in str(tpl)  # modelo genérico: nenhum dado do dono
    av = p.call('GET', f'/api/presentation-templates/afrika-modelo/versions/2/availability?competence_id={cid}')
    slots = [s['slot_id'] for s in av['slots'] if s['required'] or s['status'] in ('complete', 'editorial')
             or (s['status'] == 'partial' and not s['required_metrics'])]
    pr = p.call('POST', '/api/presentations', 201, competence_id=cid, operator=OP, slots=slots)
    view = p.call('GET', f'/api/presentations/{pr["id"]}/view')
    assert view['ready'] is True and view['blockers'] == 0
    approved = p.s['approved']
    prev = p.s['prev_detail']
    points = list(value_points(view, LABEL))
    assert points
    for pt in points:  # snapshot aprovado → visualização: mesmo valor
        same(pt, snap(approved, pt['metric_id']))
    for pt in value_points(view, PREV):  # mês anterior vem do snapshot APROVADO do mês anterior
        same(pt, snap(prev, pt['metric_id']))
    p.s.update(pid=pr['id'], slots=slots)


def test_06b_subclient_cycle_uses_inherited_reusable_template(p):
    cid, n = p.s['sub_cid'], p.s['sub_n']
    d = p.approve(cid, n, ['apps.total'])
    assert d['status'] == 'APPROVED' and snap(d, 'apps.total')['value'] == 2
    sel = p.call('GET', f'/api/template-selection/subclient/{p.s["sub"]["id"]}')
    assert sel['template']['key'] == 'afrika-modelo' and sel['inherited'] is True
    av = p.call('GET', f'/api/presentation-templates/afrika-modelo/versions/2/availability?competence_id={cid}')
    slots = [s['slot_id'] for s in av['slots'] if s['required'] or s['status'] in ('complete', 'editorial')
             or (s['status'] == 'partial' and not s['required_metrics'])]
    pr = p.call('POST', '/api/presentations', 201, competence_id=cid, operator=OP, slots=slots)
    view = p.call('GET', f'/api/presentations/{pr["id"]}/view')
    assert view['ready'] is True and view['blockers'] == 0
    for pt in value_points(view, LABEL):  # números do SUBCLIENTE, nunca do cliente
        same(pt, snap(d, pt['metric_id']))
    assert 'Unidade Piloto Sintética' in str(view)  # o nome vem do cadastro do dono, não do modelo


# ---------------------------------------------------------------- 7. interpretação revisada

def test_07_interpretation_reviewed_and_applied(p):
    pid = p.s['pid']
    cfg = p.call('GET', '/api/interpretation/config')
    assert cfg['settings']['external_enabled'] is False and cfg['settings']['provider'] == 'deterministic-demo'
    iv = p.call('POST', f'/api/presentations/{pid}/interpretations', 201, slide_id='painel-kpis', level='EXECUTIVE',
                kind='EXECUTIVE_SUMMARY', operator=OP)
    assert iv['validation']['valid'] is True
    p.interp(pid, iv['id'], 'review')
    ok = p.interp(pid, iv['id'], 'approve')
    rev = p.call('GET', f'/api/presentations/{pid}')['current_revision']
    p.interp(pid, ok['id'], 'apply', expected_revision=rev, overwrite_confirmed=True)
    view = p.call('GET', f'/api/presentations/{pid}/view')
    assert next(s for s in view['slides'] if s['slide_id'] == 'painel-kpis')['fields']['body'] == ok['text']
    p.s.update(iv=ok, final_revision=view['presentation']['current_revision'], final_view=view)


# ---------------------------------------------------------------- 8. exportação PPTX e PDF

@needs_engine
def test_08_export_pptx_and_pdf_carry_the_same_numbers(p):
    pid, rev, view = p.s['pid'], p.s['final_revision'], p.s['final_view']
    order = [s['slide_id'] for s in view['slides']]
    job, pptx = p.export(pid, 'pptx', rev)
    assert hashlib.sha256(pptx.content).hexdigest() == job['sha256']
    approved = p.s['approved']
    sev_values = snap(approved, 'sast.policy.open.by_severity')['value']
    numbers = chart_numbers(pptx.content)
    for k, v in sev_values.items():  # gráficos nativos com os números do snapshot aprovado
        if k not in ('total', 'UNKNOWN') and v:
            assert float(v) in numbers, (k, v)
    assert ''.join(p.s['iv']['text'].split()) in pptx_text(pptx.content, order.index('painel-kpis'))
    _, pdf = p.export(pid, 'pdf', rev)
    text = pdf_text(pdf.content)
    assert ''.join(p.s['iv']['text'].split()) in text
    assert len(re.findall(rb'/Type\s*/Page(?![a-zA-Z])', pdf.content)) == len(view['slides'])
    p.s.update(pptx_sha=job['sha256'])


# ---------------------------------------------------------------- 9. backup e restauração do SQLite

def test_09_backup_restore_roundtrip(p):
    cid = p.s['cid']
    before = p.call('GET', f'/api/competences/{cid}/integrity')
    conf_before = p.call('GET', f'/api/competences/{cid}/revisions/{p.s["n"]}/conference')['summary']
    bdir = p.tmp / 'backups'
    info = backup.backup(p.url, bdir)
    assert info.integrity == 'ok' and info.alembic_revision == db.head_revision()
    assert info.tables['metric_snapshots'] > 0 and info.tables['metric_conferences'] == 5
    assert Path(info.path).with_suffix('.json').exists()
    # recusas: diretório versionável, sem confirmação, arquivo corrompido
    with pytest.raises(backup.BackupError, match='versionável'):
        backup.safe_dir(db.REPO_ROOT / 'docs')
    with pytest.raises(backup.BackupError, match='confirmação'):
        backup.restore(info.path, p.url)
    bad = p.tmp / 'corrompido.sqlite3'
    bad.write_bytes(b'nao e sqlite' * 100)
    with pytest.raises(backup.BackupError):
        backup.restore(bad, p.url, confirm=True)
    # mudança depois do backup (nova competência) some com a restauração; backend parado durante a troca
    p.call('POST', '/api/competences', 201, owner_kind='client', owner_id=p.s['client']['id'], competence='2026-07',
           operator=OP)
    p.stop()
    out = backup.restore(info.path, p.url, confirm=True, safety_dir=bdir)
    assert out['safety_backup'] and Path(out['safety_backup']).exists()  # banco anterior preservado
    p.start()
    labels = [c['competence'] for c in p.call('GET', f'/api/competences?owner_kind=client&owner_id='
                                                       f'{p.s["client"]["id"]}')['items']]
    assert '2026-07' not in labels and {PREV, LABEL} <= set(labels)
    after = p.call('GET', f'/api/competences/{cid}/integrity')
    assert after == before and after['ok'] is True  # hashes de snapshots, aprovações e auditoria intactos
    assert p.call('GET', f'/api/competences/{cid}/revisions/{p.s["n"]}/conference')['summary'] == conf_before


@needs_engine
def test_10_reexport_after_restore_is_identical(p):
    job, _ = p.export(p.s['pid'], 'pptx', p.s['final_revision'])
    assert job['sha256'] == p.s['pptx_sha']


def test_11_no_secret_in_logs_and_sqlite(p):
    from app.veracode.fixtures import synthetic_credentials
    secrets = synthetic_credentials('gamma')
    logs = '\n'.join(p.s['logs'])
    assert not any(sec in logs for sec in secrets)
    raw = Path(p.url.removeprefix('sqlite:///')).read_bytes()
    assert not any(sec.encode() in raw for sec in secrets)
