import { APIRequestContext, Page, expect, test } from '@playwright/test';

// F06B: template de referência Afrika (afrika-modelo@1 + tema afrika@1) para um cliente QUALQUER, com painéis
// compostos editáveis (zonas), seções e quantidade de slides configurável. Dados 100% sintéticos; sem Veracode.
const run = Date.now().toString(36);
const OP = 'Operadora E2E Afrika';

test.beforeEach(({ page }) => {
  page.on('request', (req) => {
    expect(['127.0.0.1', 'localhost'], `requisição externa: ${req.url()}`).toContain(new URL(req.url()).hostname);
  });
});

const sev = (...n: number[]) => {
  const keys = ['VERY_HIGH', 'HIGH', 'MEDIUM', 'LOW', 'VERY_LOW', 'INFORMATIONAL', 'UNKNOWN'];
  return { ...Object.fromEntries(keys.map((k, i) => [k, n[i]])), total: n.reduce((a, b) => a + b, 0) };
};

async function call(request: APIRequestContext, method: string, url: string, data?: unknown) {
  const r = await request.fetch(url, { method, data });
  expect(r.status(), `${method} ${url}: ${await r.text()}`).toBeLessThan(300);
  return r.json();
}

async function approved(request: APIRequestContext, clientId: string, label: string, values: Record<string, unknown>) {
  const comp = await call(request, 'POST', '/api/competences', { owner_kind: 'client', owner_id: clientId, competence: label, operator: OP });
  const base = `/api/competences/${comp.id}/revisions/1`;
  const lock = async () => (await call(request, 'GET', base)).lock_version;
  for (const [metric, value] of Object.entries(values))
    await call(request, 'PUT', `${base}/metrics/${metric}`, { value, justification: 'Valor sintético justificado (E2E F06B)', operator: OP, expected_lock_version: await lock() });
  await call(request, 'PUT', `${base}/required`, { metric_ids: ['apps.total'], operator: OP, expected_lock_version: await lock() });
  await call(request, 'POST', `${base}/submit`, { operator: OP, expected_lock_version: await lock() });
  await call(request, 'POST', `${base}/approve`, { approver: 'Aprovador E2E', expected_lock_version: await lock() });
}

const canvas = (page: Page) => page.getByTestId('slide-canvas');
const el = (page: Page, key: string) => canvas(page).locator(`[data-el="${key}"]`);
async function goToSlide(page: Page, slideId: string) {
  await page.getByTestId(`slide-item-${slideId}`).getByRole('button').first().click();
}

test('Afrika: criar para cliente qualquer → painéis com valores aprovados → editar zona → remover slide → persistir', async ({ page, request }) => {
  const name = `Cliente Afrika E2E ${run}`;
  const client = await call(request, 'POST', '/api/clients', { name });
  await approved(request, client.id, '2026-08', { 'apps.total': 120, 'sast.policy.open.by_severity': sev(1, 5, 20, 8, 2, 1, 0) });
  await approved(request, client.id, '2026-09', {
    'apps.total': 128,
    'apps.without_team': 6,
    'sast.policy.open.by_severity': sev(2, 7, 23, 9, 3, 1, 1),
    'sca.policy.open.by_severity': sev(1, 4, 11, 5, 2, 1, 0),
  });

  await page.goto('/#/presentations');
  await page.getByLabel('Cliente', { exact: true }).selectOption({ label: name });
  await page.getByLabel('Operador (declarado)').fill(OP);
  await page.getByLabel('Escolher template').selectOption('afrika-modelo@1');
  await page.getByRole('button', { name: 'Salvar escolha' }).click();
  await expect(page.getByTestId('template-selection')).toContainText('afrika-modelo v1');
  await page.getByLabel('Competência aprovada').selectOption({ label: '2026-09 — revisão oficial 1' });
  await page.getByRole('button', { name: 'Criar apresentação' }).click();

  await expect(page.getByTestId('presentation-revision')).toHaveText('Revisão 1');
  await expect(page.getByTestId('slide-counter')).toHaveText('1 / 16');
  await expect(canvas(page)).toContainText(name); // capa genérica: nome do cliente vem do cadastro
  await goToSlide(page, 'secao-indicadores');
  await expect(el(page, 'section')).toContainText('Indicadores');

  // Painel de KPIs: só valores aprovados; ausente ≠ zero
  await goToSlide(page, 'painel-kpis');
  await expect(el(page, 'kpi-value:apps.total')).toHaveText('128');
  await expect(el(page, 'kpi-value:sast.policy.open.by_severity')).toHaveText('46');
  await expect(el(page, 'kpi-card:apps.unclassified')).toContainText('valor indisponível');
  await expect(el(page, 'kpi-card:apps.without_team')).toContainText('6');
  await expect(el(page, 'competence-badge')).toContainText('2026');

  // Painel de severidades: comparação em colunas (anterior → atual)
  await goToSlide(page, 'painel-severidades');
  await expect(el(page, 'cmp-value:sast.policy.open.by_severity')).toContainText('37');
  await expect(el(page, 'cmp-value:sast.policy.open.by_severity')).toContainText('46');
  await expect(el(page, 'cmp-delta:sast.policy.open.by_severity')).toContainText('+9');

  // Edição de zona: gráfico combinado → linhas de apps.total em 12 meses, com título próprio
  await goToSlide(page, 'painel-graficos');
  const zone = page.getByTestId('zone-editor-chart');
  await zone.getByLabel('Gráfico').selectOption('line');
  await zone.getByLabel('apps.total', { exact: true }).check();
  await zone.getByLabel('Meses').selectOption('12');
  await zone.getByLabel('Título da zona').fill('Aplicações — 12 meses (E2E)');
  await expect(el(page, 'zone-title:chart')).toHaveText('Aplicações — 12 meses (E2E)');
  await page.getByLabel('Título (obrigatório)').fill('Painel editado E2E');
  await expect(canvas(page)).toContainText('Painel editado E2E');

  // Quantidade de slides configurável: remove um divisor opcional
  await page.getByRole('button', { name: 'Remover slide: secao-detalhes' }).click();
  await expect(page.getByRole('button', { name: 'Remover slide: capa' })).toBeDisabled();
  await page.getByLabel('Resumo da alteração').fill('Edição de zona E2E');
  await page.getByRole('button', { name: 'Salvar revisão' }).click();
  await expect(page.getByTestId('presentation-revision')).toHaveText('Revisão 2');
  await expect(page.getByTestId('slide-counter')).toContainText('/ 15');

  await page.reload();
  await expect(page.getByTestId('presentation-revision')).toHaveText('Revisão 2');
  await expect(page.getByTestId('slide-item-secao-detalhes')).toHaveCount(0);
  await goToSlide(page, 'painel-graficos');
  await expect(el(page, 'zone-title:chart')).toHaveText('Aplicações — 12 meses (E2E)');
  await expect(canvas(page)).toContainText('Painel editado E2E');
  await expect(canvas(page).locator('[data-el="zone:chart"] [data-el="plot"]')).toBeVisible();
});
