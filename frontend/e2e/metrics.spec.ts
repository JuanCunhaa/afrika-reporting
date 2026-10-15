import { APIRequestContext, Page, expect, test } from '@playwright/test';
import { SYNTHETIC_SECRET_NAMES, SYNTHETIC_SECRET_VALUES } from './fixture-creds';

// F04: painel de indicadores contra o backend em modo FIXTURE (tenant sintético `alpha`; nenhuma Veracode real).
// Valores esperados calculados diretamente dos dados brutos do fixture (backend/app/veracode/fixtures.py), sem o
// motor: universo BU1+BU2 = 60 apps; SAST Policy abertos = 126; ocorrências em sandboxes = 102; SCA Policy = 60.
const run = Date.now().toString(36);
const bodies: string[] = [];

test.beforeEach(({ page }) => {
  page.on('request', (req) => {
    expect(['127.0.0.1', 'localhost'], `requisição externa: ${req.url()}`).toContain(new URL(req.url()).hostname);
  });
  page.on('response', async (res) => {
    if (/\/api\/metrics/.test(res.url())) bodies.push(await res.text().catch(() => ''));
  });
});

test.afterEach(() => {
  const all = bodies.join('\n');
  for (const secret of [...SYNTHETIC_SECRET_VALUES, ...SYNTHETIC_SECRET_NAMES]) expect(all).not.toContain(secret);
  bodies.length = 0;
});

async function createClient(request: APIRequestContext, name: string) {
  const conns = await (await request.get('/api/connections?limit=200')).json();
  let conn = conns.items.find((c: { credential_ref: string }) => c.credential_ref === 'env:AFRIKA_DEMO_VERACODE');
  if (!conn)
    conn = await (
      await request.post('/api/connections', { data: { name: `Conexão ${name}`, region: 'commercial', credential_ref: 'env:AFRIKA_DEMO_VERACODE' } })
    ).json();
  return (await request.post('/api/clients', { data: { name, connection_id: conn.id } })).json();
}

async function collect(page: Page, clientId: string, competence = '2026-09') {
  await page.goto(`/#/metrics/clients/${clientId}`);
  await expect(page.getByRole('heading', { level: 2 })).toHaveText('Indicadores');
  await page.getByLabel('Competência (mês fechado)').fill(competence);
  await page.getByRole('button', { name: 'Iniciar coleta' }).click();
}

const card = (page: Page, id: string) => page.getByTestId(`metric-${id}`);

test('coleta explícita, status, severidades, fonte, filtros e motivos por domínio', async ({ page, request }) => {
  const name = `Indicadores E2E ${run}`;
  const client = await createClient(request, name);
  const bus = await (await request.get(`/api/veracode/clients/${client.id}/business-units?limit=200`)).json();
  const ids = bus.items
    .filter((b: { name: string }) => b.name === 'Alfa BU 1' || b.name === 'Alfa BU 2')
    .map((b: { bu_id: string }) => b.bu_id);
  expect(ids).toHaveLength(2);
  const saved = await request.put(`/api/scopes/clients/${client.id}/applications`, {
    data: { rule: { field: 'business_unit.id', cmp: 'in', values: ids }, expected_version: 0 },
  });
  expect(saved.status()).toBe(201);

  await collect(page, client.id);
  await expect(page.getByTestId('run-status')).toContainText('Concluída', { timeout: 20_000 });
  await expect(page.getByTestId('run-status')).toContainText(`${name} · competência 2026-09`);
  await expect(page.getByTestId('run-collected-at')).not.toBeEmpty();

  // Aplicações
  await expect(page.getByTestId('status-apps.total')).toHaveText('Validado');
  await expect(page.getByTestId('value-apps.total')).toHaveText('60');
  await expect(page.getByTestId('status-apps.total.at_period_end')).toHaveText('Indisponível');
  await expect(card(page, 'apps.total.at_period_end')).toContainText('historical_state_unavailable');

  // SAST: Policy × Sandbox, severidades, dedup não comprovada
  await page.getByRole('tab', { name: 'SAST', exact: true }).click();
  await expect(page.getByTestId('status-sast.policy.open.by_severity')).toHaveText('Validado');
  await expect(page.getByTestId('total-sast.policy.open.by_severity')).toHaveText('126');
  const policy = card(page, 'sast.policy.open.by_severity');
  await expect(policy.getByRole('row', { name: 'Muito alta 30' })).toBeVisible();
  await expect(policy.getByRole('row', { name: 'Informativa 14' })).toBeVisible();
  await expect(page.getByTestId('total-sast.sandbox.open.by_severity')).toHaveText('102');
  await expect(page.getByTestId('status-sast.sandbox.open.distinct')).toHaveText('Incompleto');
  await expect(card(page, 'sast.sandbox.open.distinct')).toContainText('dedup_identity_not_proven');
  await expect(card(page, 'sast.sandbox.open.distinct')).toContainText('Agregado PARCIAL observado');
  await policy.getByText('Fonte, período e filtros').click();
  await expect(policy).toContainText('Veracode Findings API 2.1');
  await expect(policy).toContainText('/appsec/v2/applications/{guid}/findings');
  await expect(policy).toContainText('Estado atual (data da coleta) — competência 2026-09');
  await expect(policy).toContainText('context=POLICY');
  await expect(policy).toContainText('status=OPEN_EXCLUDING_APPROVED_MITIGATIONS');
  await expect(page.getByTestId('status-sast.policy.resolved_in_period')).toHaveText('Não suportado');

  // SCA
  await page.getByRole('tab', { name: 'SCA', exact: true }).click();
  await expect(page.getByTestId('total-sca.policy.open.by_severity')).toHaveText('60');
  await expect(page.getByTestId('status-sca.agent.projects')).toHaveText('Não suportado');

  // Lacunas declaradas
  await page.getByRole('tab', { name: 'Scans e licenças' }).click();
  await expect(page.getByTestId('status-scans.count')).toHaveText('Não suportado');
  await expect(page.getByTestId('status-licenses.usage')).toHaveText('Não suportado');
});

test('cliente sem escopo: indisponível com motivo; competência aberta é recusada', async ({ page, request }) => {
  const client = await createClient(request, `Sem escopo E2E ${run}`);
  await collect(page, client.id);
  await expect(page.getByTestId('run-status')).toContainText('Concluída', { timeout: 20_000 });
  await expect(page.getByTestId('status-apps.total')).toHaveText('Indisponível');
  await expect(card(page, 'apps.total')).toContainText('universe_not_defined');
  await expect(page.getByTestId('value-apps.total')).toHaveCount(0);

  const now = new Date();
  const current = `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, '0')}`;
  await collect(page, client.id, current);
  await expect(page.getByRole('alert')).toContainText('mês já encerrado');
});
