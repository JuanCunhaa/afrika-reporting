import { APIRequestContext, expect, test } from '@playwright/test';
import fs from 'node:fs';

// F07 — exportação pela interface: PowerPoint e PDF da revisão SALVA, status/erros, alterações não salvas bloqueiam,
// apresentação com bloqueios não exporta, download pelo navegador com arquivo válido. Dados 100% sintéticos; o
// backend renderiza com o próprio Chromium headless (build do frontend), sem rede.
const run = Date.now().toString(36);
const OP = 'Operadora Exportação E2E';

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

async function approvedPresentation(request: APIRequestContext, name: string, values: Record<string, unknown>, template: { key: string; version: number }) {
  const client = await call(request, 'POST', '/api/clients', { name });
  const comp = await call(request, 'POST', '/api/competences', { owner_kind: 'client', owner_id: client.id, competence: '2026-09', operator: OP });
  const base = `/api/competences/${comp.id}/revisions/1`;
  const lock = async () => (await call(request, 'GET', base)).lock_version;
  for (const [metric, value] of Object.entries(values))
    await call(request, 'PUT', `${base}/metrics/${metric}`, { value, justification: 'Valor sintético justificado (E2E F07)', operator: OP, expected_lock_version: await lock() });
  await call(request, 'PUT', `${base}/required`, { metric_ids: ['apps.total'], operator: OP, expected_lock_version: await lock() });
  await call(request, 'POST', `${base}/submit`, { operator: OP, expected_lock_version: await lock() });
  await call(request, 'POST', `${base}/approve`, { approver: 'Aprovador E2E', expected_lock_version: await lock() });
  return call(request, 'POST', '/api/presentations', { competence_id: comp.id, template_key: template.key, template_version: template.version, operator: OP });
}

const READY = {
  'apps.total': 73,
  'sast.policy.open.by_severity': sev(1, 3, 6, 4, 1, 0, 1),
  'sca.policy.open.by_severity': sev(0, 2, 3, 1, 1, 1, 0),
  'sast.policy.open.top_applications': { top: Array.from({ length: 6 }, (_, i) => ({ application_guid: `x${i}`, name: `App Exportação ${i + 1}`, findings: 20 - i })), total: 120 },
};

async function exportAndDownload(page: import('@playwright/test').Page, format: 'pptx' | 'pdf', revision: number) {
  await page.getByTestId(`export-${format}`).click();
  const row = page.getByTestId(`export-job-${format}`).first();
  await expect(row).toHaveAttribute('data-status', 'done', { timeout: 90_000 });
  await expect(row).toContainText(format === 'pptx' ? 'PPTX validado' : 'PDF validado');
  await expect(row.locator('td').nth(1)).toHaveText(String(revision));
  const [download] = await Promise.all([page.waitForEvent('download'), page.getByTestId(`export-download-${format}`).first().click()]);
  expect(download.suggestedFilename()).toMatch(new RegExp(`_r${revision}\\.${format}$`));
  const bytes = fs.readFileSync((await download.path()) as string);
  return { name: download.suggestedFilename(), bytes };
}

test('exporta PowerPoint e PDF da revisão salva com status, validação e download', async ({ page, request }) => {
  test.setTimeout(240_000);
  const p = await approvedPresentation(request, `Exportação E2E ${run}`, READY, { key: 'demo-executivo', version: 1 });
  await page.goto(`/#/presentations/${p.id}`);
  await page.locator('#e-operator').fill(OP);
  await expect(page.getByTestId('export-panel')).toContainText('revisão salva 1');
  await expect(page.getByTestId('export-pptx')).toBeEnabled({ timeout: 15_000 });

  const pptx = await exportAndDownload(page, 'pptx', 1);
  expect(pptx.bytes.subarray(0, 2).toString()).toBe('PK');
  expect(pptx.bytes.includes(Buffer.from('ppt/presentation.xml'))).toBe(true);
  expect(pptx.bytes.includes(Buffer.from('ppt/charts/'))).toBe(true); // gráfico nativo, não imagem

  const pdf = await exportAndDownload(page, 'pdf', 1);
  expect(pdf.bytes.subarray(0, 5).toString()).toBe('%PDF-');
  expect(pdf.bytes.subarray(-8).toString()).toContain('%%EOF');

  // o mesmo conteúdo continua disponível pela lista de exportações (status consultável)
  const listed = await call(request, 'GET', `/api/presentations/${p.id}/exports`);
  expect(listed.items.map((j: { status: string }) => j.status)).toEqual(['done', 'done']);
});

test('alterações não salvas bloqueiam a exportação até salvar; depois exporta a nova revisão', async ({ page, request }) => {
  test.setTimeout(180_000);
  const p = await approvedPresentation(request, `Exportação não salva ${run}`, READY, { key: 'demo-executivo', version: 1 });
  await page.goto(`/#/presentations/${p.id}`);
  await page.locator('#e-operator').fill(OP);
  await expect(page.getByTestId('export-pptx')).toBeEnabled({ timeout: 15_000 });
  await page.locator('#doc-title').fill('Título editado e ainda não salvo');
  await expect(page.getByTestId('export-dirty')).toContainText('alterações não salvas');
  await expect(page.getByTestId('export-pptx')).toBeDisabled();
  await expect(page.getByTestId('export-pdf')).toBeDisabled();
  await page.getByRole('button', { name: 'Salvar revisão' }).click();
  await expect(page.getByTestId('editor-message')).toContainText('Revisão 2 salva');
  await expect(page.getByTestId('export-dirty')).toHaveCount(0);
  await expect(page.getByTestId('export-panel')).toContainText('revisão salva 2');
  const pptx = await exportAndDownload(page, 'pptx', 2);
  expect(pptx.bytes.includes(Buffer.from('Título editado e ainda não salvo'))).toBe(false); // texto vai comprimido no ZIP
  const job = (await call(request, 'GET', `/api/presentations/${p.id}/exports`)).items[0];
  expect(job.revision).toBe(2);
});

test('apresentação com bloqueios não exporta e o motivo é exibido', async ({ page, request }) => {
  const p = await approvedPresentation(request, `Exportação bloqueada ${run}`, { 'apps.total': 5 }, { key: 'afrika-modelo', version: 2 });
  await page.goto(`/#/presentations/${p.id}`);
  await page.locator('#e-operator').fill(OP);
  await expect(page.getByTestId('export-unavailable')).toContainText('bloqueio(s)');
  await expect(page.getByTestId('export-pptx')).toBeDisabled();
  // a API recusa mesmo se chamada diretamente (fonte aprovada + sem bloqueios é exigência do servidor)
  const r = await request.post(`/api/presentations/${p.id}/exports`, { data: { format: 'pdf', revision: 1, operator: OP } });
  expect(r.status()).toBe(409);
  expect((await r.json()).error.code).toBe('export_blocked');
});
