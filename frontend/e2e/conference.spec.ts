import { APIRequestContext, expect, test } from '@playwright/test';
import { SYNTHETIC_SECRET_NAMES, SYNTHETIC_SECRET_VALUES } from './fixture-creds';

// F10: conferência humana com a plataforma Veracode, contra o backend em modo FIXTURE (tenant sintético `alpha`).
// O operador informa só o valor oficial; Δ e status vêm do servidor. Universo BU1+BU2 = 60 aplicações.
const run = Date.now().toString(36);
const OP = 'Conferente E2E';
const bodies: string[] = [];

test.beforeEach(({ page }) => {
  page.on('request', (req) => {
    expect(['127.0.0.1', 'localhost'], `requisição externa: ${req.url()}`).toContain(new URL(req.url()).hostname);
  });
  page.on('response', async (res) => {
    if (/\/conference/.test(res.url())) bodies.push(await res.text().catch(() => ''));
  });
});

test.afterEach(() => {
  const all = bodies.join('\n');
  for (const secret of [...SYNTHETIC_SECRET_VALUES, ...SYNTHETIC_SECRET_NAMES, 'credential_ref']) expect(all).not.toContain(secret);
  bodies.length = 0;
});

async function draftFromRun(request: APIRequestContext, name: string) {
  const conns = await (await request.get('/api/connections?limit=200')).json();
  let conn = conns.items.find((c: { credential_ref: string }) => c.credential_ref === 'env:AFRIKA_DEMO_VERACODE');
  if (!conn)
    conn = await (
      await request.post('/api/connections', { data: { name: `Conexão ${name}`, region: 'commercial', credential_ref: 'env:AFRIKA_DEMO_VERACODE' } })
    ).json();
  const client = await (await request.post('/api/clients', { data: { name, connection_id: conn.id } })).json();
  const bus = await (await request.get(`/api/veracode/clients/${client.id}/business-units?limit=200`)).json();
  const ids = bus.items.filter((b: { name: string }) => b.name === 'Alfa BU 1' || b.name === 'Alfa BU 2').map((b: { bu_id: string }) => b.bu_id);
  const saved = await request.put(`/api/scopes/clients/${client.id}/applications`, {
    data: { rule: { field: 'business_unit.id', cmp: 'in', values: ids }, expected_version: 0 },
  });
  expect(saved.status()).toBe(201);
  const started = await request.post('/api/metrics/runs', { data: { owner_kind: 'client', owner_id: client.id, competence: '2026-08' } });
  expect(started.status(), await started.text()).toBe(202);
  const runId = (await started.json()).run_id;
  await expect
    .poll(async () => (await (await request.get(`/api/metrics/runs/${runId}`)).json()).status, { timeout: 30_000 })
    .toBe('done');
  const draft = await request.post('/api/competences/from-run', { data: { run_id: runId, operator: OP } });
  expect(draft.status(), await draft.text()).toBe(201);
  return (await draft.json()) as { competence_id: string; revision: number };
}

test('conferência: valor oficial → diferença e status do servidor, categorias separadas, CSV local', async ({ page, request }) => {
  const { competence_id: cid, revision } = await draftFromRun(request, `Conferência E2E ${run}`);
  await page.goto(`/#/snapshots/${cid}/${revision}`);
  await page.getByTestId('open-conference').click();
  await expect(page.getByRole('heading', { level: 2 })).toContainText('Conferência com a Veracode — 2026-08');
  await expect(page.getByTestId('summary-NOT_APPLICABLE')).toHaveText('12');
  await expect(page.getByTestId('summary-BLOCKED_EXTERNAL')).toHaveText('2');
  await expect(page.getByTestId('other-sast.open.distinct')).toContainText('identidade NÃO comprovada');
  await expect(page.getByTestId('other-scans.count')).toContainText('HTTP 403');

  // Estado atual: conferência no MESMO dia da coleta (data no fuso do cliente; o CI roda em UTC).
  const sheet = await (await request.get(`/api/competences/${cid}/revisions/${revision}/conference`)).json();
  const collectedOn = sheet.metrics.find((m: { metric_id: string }) => m.metric_id === 'apps.total').snapshot.collected_on;
  await page.getByLabel('Data da conferência').fill(collectedOn);
  await page.getByLabel('Conferente (declarado)').fill(OP);
  const total = page.getByTestId('conference-apps.total');
  await expect(total.getByTestId('comparison')).toHaveText('Não conferido');
  await total.getByLabel('Oficial Valor').fill('60');
  await expect(total.getByTestId('diff-value')).toHaveText('0'); // prévia
  await total.getByLabel(/mesmos do indicador/).check();
  await total.getByRole('button', { name: 'Registrar conferência' }).click();
  await expect(total.getByTestId('comparison')).toHaveText('Confere (MATCH)');
  await expect(total).toContainText('Homologado');

  const without = page.getByTestId('conference-apps.without_team');
  await without.getByLabel('Oficial Valor').fill('999');
  await without.getByLabel(/mesmos do indicador/).check();
  await without.getByRole('button', { name: 'Registrar conferência' }).click();
  await expect(without.getByTestId('comparison')).toHaveText('Diverge (MISMATCH)');

  const multi = page.getByTestId('conference-apps.multiple_teams');
  await multi.getByLabel('Oficial Valor').fill('0');
  await multi.getByRole('button', { name: 'Registrar conferência' }).click(); // filtros não confirmados
  await expect(multi.getByTestId('comparison')).toHaveText('Não comparável');
  await expect(multi.getByTestId('conference-last')).toContainText('filtros/escopo não confirmados');

  await page.reload();
  await expect(page.getByTestId('conference-apps.total').getByTestId('comparison')).toHaveText('Confere (MATCH)');

  const csv = await request.get(`/api/competences/${cid}/revisions/${revision}/conference.csv`);
  expect(csv.status()).toBe(200);
  expect(csv.headers()['cache-control']).toBe('no-store');
  const text = await csv.text();
  expect(text).toContain(';apps.total;');
  expect(text).toContain('BLOCKED_EXTERNAL');
});
