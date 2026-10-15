import { APIRequestContext, Page, expect, test } from '@playwright/test';
import { SYNTHETIC_SECRET_NAMES, SYNTHETIC_SECRET_VALUES } from './fixture-creds';

// F05: competências, snapshots, aprovação, histórico e Reporting API contra o backend em modo FIXTURE
// (tenant sintético `alpha`; nenhuma Veracode real). Universo BU1+BU2 = 60 aplicações (ver metrics.spec.ts).
const run = Date.now().toString(36);
const bodies: string[] = [];
const OP = 'Operadora E2E';

test.beforeEach(({ page }) => {
  page.on('request', (req) => {
    expect(['127.0.0.1', 'localhost'], `requisição externa: ${req.url()}`).toContain(new URL(req.url()).hostname);
  });
  page.on('response', async (res) => {
    if (/\/api\/(competences|history|reporting)/.test(res.url())) bodies.push(await res.text().catch(() => ''));
  });
});

test.afterEach(() => {
  const all = bodies.join('\n');
  for (const secret of [...SYNTHETIC_SECRET_VALUES, ...SYNTHETIC_SECRET_NAMES, 'credential_ref']) expect(all).not.toContain(secret);
  bodies.length = 0;
});

async function clientWithScope(request: APIRequestContext, name: string) {
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
  return client;
}

async function approveManual(request: APIRequestContext, clientId: string, label: string, value: number) {
  const comp = await (
    await request.post('/api/competences', { data: { owner_kind: 'client', owner_id: clientId, competence: label, operator: OP } })
  ).json();
  const base = `/api/competences/${comp.id}/revisions/1`;
  const steps: [string, string, Record<string, unknown>][] = [
    ['PUT', `${base}/required`, { metric_ids: ['licenses.usage'], operator: OP, expected_lock_version: 1 }],
    ['PUT', `${base}/metrics/licenses.usage`, { value, justification: 'Histórico informado manualmente (E2E)', operator: OP, expected_lock_version: 2 }],
    ['POST', `${base}/submit`, { operator: OP, expected_lock_version: 3 }],
    ['POST', `${base}/approve`, { approver: 'Aprovador E2E', expected_lock_version: 4 }],
  ];
  for (const [method, url, data] of steps) {
    const r = await request.fetch(url, { method, data });
    expect(r.status(), await r.text()).toBe(200);
  }
}

const state = (page: Page, id: string) => page.getByTestId(`snapstate-${id}`);
const val = (page: Page, id: string) => page.getByTestId(`snapval-${id}`);

test('coleta → rascunho → valor manual → revisão → aprovação → nova revisão → comparação', async ({ page, request }) => {
  const client = await clientWithScope(request, `Competências E2E ${run}`);
  await page.goto(`/#/metrics/clients/${client.id}`);
  await page.getByLabel('Competência (mês fechado)').fill('2026-08');
  await page.getByRole('button', { name: 'Iniciar coleta' }).click();
  await expect(page.getByTestId('run-status')).toContainText('Concluída', { timeout: 20_000 });
  await page.getByLabel('Operador (declarado)').fill(OP);
  await page.getByRole('button', { name: 'Criar rascunho da competência' }).click();

  await expect(page.getByRole('heading', { level: 2 })).toContainText('Competência 2026-08');
  await expect(page.getByTestId('revision-status')).toHaveText('Rascunho');
  await expect(val(page, 'apps.total')).toHaveText('60');
  await expect(state(page, 'apps.total')).toHaveText('Validado (técnico)');
  await expect(page.getByTestId('snap-apps.total')).toContainText('NOT_VERIFIED'); // técnico ≠ homologado
  await expect(state(page, 'licenses.usage')).toHaveText('Sem fonte');
  await expect(state(page, 'sast.open.distinct')).toHaveText('Coleta incompleta');

  // valor manual tipado e justificado
  await page.getByRole('button', { name: 'Editar licenses.usage' }).click();
  await page.getByLabel(/Valor \(count; JSON\)/).fill('42');
  await page.getByLabel('Justificativa (obrigatória)').fill('Contagem do contrato de licenças (E2E)');
  await page.getByRole('button', { name: 'Salvar valor manual' }).click();
  await expect(state(page, 'licenses.usage')).toHaveText('Manual');
  await expect(val(page, 'licenses.usage')).toHaveText('42');

  // aprovação bloqueada sem conjunto obrigatório explícito
  await page.getByRole('button', { name: 'Enviar para revisão' }).click();
  await expect(page.getByTestId('revision-status')).toHaveText('Em revisão');
  await page.getByLabel('Aprovador (declarado)').fill('Aprovador E2E');
  await page.getByRole('button', { name: 'Aprovar revisão' }).click();
  await expect(page.getByRole('alert')).toContainText('Aprovação bloqueada');
  await page.getByLabel('Motivo para devolver').fill('Selecionar indicadores obrigatórios');
  await page.getByRole('button', { name: 'Devolver a rascunho' }).click();
  await expect(page.getByTestId('revision-status')).toHaveText('Rascunho');
  // painel de obrigatórios abre sozinho enquanto o conjunto está vazio
  await page.getByLabel('apps.total', { exact: true }).check();
  await page.getByLabel('licenses.usage', { exact: true }).check();
  await page.getByRole('button', { name: 'Salvar obrigatórios' }).click();
  await expect(page.getByTestId('checks')).toHaveCount(0);
  await page.getByRole('button', { name: 'Enviar para revisão' }).click();
  await page.getByLabel('Aprovador (declarado)').fill('Aprovador E2E');
  await page.getByRole('button', { name: 'Aprovar revisão' }).click();
  await expect(page.getByTestId('revision-status')).toHaveText('Aprovada');
  await expect(page.getByTestId('approval-info')).toContainText('identidade declarada, não autenticada');
  await expect(page.getByRole('button', { name: 'Editar apps.total' })).toHaveCount(0);

  // revisão posterior: cópia exata, ajuste, nova aprovação; a anterior continua consultável
  await page.getByRole('button', { name: 'Nova revisão a partir da aprovada' }).click();
  await expect(page.getByRole('heading', { level: 3, name: 'Revisão 2' })).toBeVisible();
  await expect(val(page, 'licenses.usage')).toHaveText('42');
  await page.getByRole('button', { name: 'Editar licenses.usage' }).click();
  await page.getByLabel(/Valor \(count; JSON\)/).fill('43');
  await page.getByLabel('Justificativa (obrigatória)').fill('Correção posterior auditada (E2E)');
  await page.getByRole('button', { name: 'Salvar valor manual' }).click();
  await expect(val(page, 'licenses.usage')).toHaveText('43');
  await page.getByRole('button', { name: 'Enviar para revisão' }).click();
  await page.getByLabel('Aprovador (declarado)').fill('Aprovador E2E');
  await page.getByRole('button', { name: 'Aprovar revisão' }).click();
  await expect(page.getByTestId('revision-status')).toHaveText('Aprovada');
  await page.getByLabel('Comparar com a revisão').selectOption('1');
  await page.getByRole('button', { name: 'Comparar versões' }).click();
  await expect(page.getByTestId('diff')).toContainText('licenses.usage: 42 (MANUAL) → 43 (MANUAL)');
  await page.getByRole('button', { name: 'Verificar integridade' }).click();
  await expect(page.getByTestId('integrity')).toContainText('Integridade: OK · 2 aprovação(ões)');
  await page.getByRole('button', { name: 'Ver auditoria' }).click();
  await expect(page.getByTestId('audit')).toContainText('revision.approved');
  await page.getByRole('link', { name: 'Revisão 1' }).click();
  await expect(val(page, 'licenses.usage')).toHaveText('42');
});

test('histórico só de aprovados: lacuna explícita e comparação com mês anterior', async ({ page, request }) => {
  const name = `Histórico E2E ${run}`;
  const client = await clientWithScope(request, name);
  await approveManual(request, client.id, '2026-07', 5);
  await approveManual(request, client.id, '2026-09', 9);
  await page.goto('/#/history');
  await page.getByLabel('Cliente', { exact: true }).selectOption({ label: name });
  await page.getByLabel('Indicador').selectOption('licenses.usage');
  await page.getByLabel('Intervalo').selectOption('custom');
  await page.getByLabel('Início').fill('2026-07');
  await page.getByLabel(/^Fim/).fill('2026-09');
  await page.getByRole('button', { name: 'Carregar série' }).click();
  await expect(page.getByTestId('point-2026-07')).toContainText('5');
  await expect(page.getByTestId('point-2026-08')).toContainText('lacuna');
  await expect(page.getByTestId('point-2026-09')).toContainText('9');
  await expect(page.getByTestId('gaps')).toHaveText('Lacunas: 2026-08');
  await page.getByLabel('Competência para comparar com a anterior').fill('2026-09');
  await page.getByRole('button', { name: 'Comparar com mês anterior' }).click();
  await expect(page.getByTestId('compare')).toContainText('lacuna');
  await expect(page.getByTestId('compare')).toContainText('— (gap)');
});

test('Reporting API (fixture): geração FINDINGS com polling e agregados exploratórios', async ({ page, request }) => {
  const name = `Reporting E2E ${run}`;
  await clientWithScope(request, name);
  await page.goto('/#/reporting');
  await expect(page.getByTestId('reporting-status')).toContainText('habilitada');
  await expect(page.getByTestId('reporting-status')).toContainText('POST /appsec/v1/analytics/report');
  await page.getByLabel('Cliente', { exact: true }).selectOption({ label: name });
  await page.getByLabel('ID numérico da aplicação (opcional)').fill('5001'); // escopo limitado: uma aplicação
  await page.getByRole('button', { name: 'Gerar relatório' }).click();
  await expect(page.getByTestId('job-status').first()).toHaveText('Concluído', { timeout: 20_000 });
  await expect(page.getByTestId('job-result').first()).toContainText('Completo');
  await expect(page.getByTestId('job-result').first()).toContainText('EXPLORATORY_NOT_HOMOLOGATED');
});
