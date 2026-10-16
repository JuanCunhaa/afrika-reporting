import { APIRequestContext, Page, expect, test } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { collectOverflow } from '../visual/overflow';
import { encodePng } from '../visual/png';

// F06C: homologação visual — seleção flexível de slides pelos indicadores aprovados, variação comprovada (cor só com
// direção declarada), ativos locais com fallback neutro e prova de que o detector de overflow encontra estouros.
// Dados 100% sintéticos; sem Veracode; nenhuma requisição externa.
const run = Date.now().toString(36);
const OP = 'Operadora E2E F06C';

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

async function approved(request: APIRequestContext, clientId: string, label: string, values: Record<string, unknown>): Promise<string> {
  const comp = await call(request, 'POST', '/api/competences', { owner_kind: 'client', owner_id: clientId, competence: label, operator: OP });
  const base = `/api/competences/${comp.id}/revisions/1`;
  const lock = async () => (await call(request, 'GET', base)).lock_version;
  for (const [metric, value] of Object.entries(values))
    await call(request, 'PUT', `${base}/metrics/${metric}`, { value, justification: 'Valor sintético justificado (E2E F06C)', operator: OP, expected_lock_version: await lock() });
  await call(request, 'PUT', `${base}/required`, { metric_ids: ['apps.total'], operator: OP, expected_lock_version: await lock() });
  await call(request, 'POST', `${base}/submit`, { operator: OP, expected_lock_version: await lock() });
  await call(request, 'POST', `${base}/approve`, { approver: 'Aprovador E2E', expected_lock_version: await lock() });
  return comp.id;
}

async function seedClient(request: APIRequestContext, name: string): Promise<{ clientId: string; competenceId: string }> {
  const client = await call(request, 'POST', '/api/clients', { name });
  await approved(request, client.id, '2026-08', { 'apps.total': 120, 'sast.policy.open.by_severity': sev(1, 5, 20, 8, 2, 1, 0), 'sca.policy.open.by_severity': sev(1, 5, 12, 5, 2, 1, 0) });
  const competenceId = await approved(request, client.id, '2026-09', {
    'apps.total': 128,
    'apps.without_team': 6,
    'sast.policy.open.by_severity': sev(2, 7, 23, 9, 3, 1, 1), // sobe: piora comprovada
    'sca.policy.open.by_severity': sev(1, 4, 11, 5, 2, 1, 0), // cai: melhora comprovada
  });
  return { clientId: client.id, competenceId };
}

const canvas = (page: Page) => page.getByTestId('slide-canvas');
const el = (page: Page, key: string) => canvas(page).locator(`[data-el="${key}"]`);
async function goToSlide(page: Page, slideId: string) {
  await page.getByTestId(`slide-item-${slideId}`).getByRole('button').first().click();
}

test('F06C: escolher slides pelos indicadores aprovados → variação colorida só com direção declarada', async ({ page, request }) => {
  const name = `Cliente F06C E2E ${run}`;
  await seedClient(request, name);
  await page.goto('/#/presentations');
  await page.getByLabel('Cliente', { exact: true }).selectOption({ label: name });
  await page.getByLabel('Operador (declarado)').fill(OP);
  await page.getByLabel('Competência aprovada').selectOption({ label: '2026-09 — revisão oficial 1' });
  await page.getByLabel('Template (vazio = escolhido para o dono)').selectOption('afrika-modelo@2');
  const picker = page.getByTestId('slot-picker');
  await expect(picker).toContainText('16 de 16');
  await expect(page.getByTestId('slot-status-ranking-componentes')).toContainText('nenhum indicador com valor aprovado');
  await expect(page.getByTestId('slot-status-painel-severidades')).toContainText('todos os indicadores');
  await expect(page.getByTestId('slot-capa')).toBeDisabled(); // obrigatório
  await page.getByRole('button', { name: 'Usar sugestão (indicadores disponíveis)' }).click();
  await expect(page.getByTestId('slot-ranking-componentes')).not.toBeChecked();
  const legend = await picker.locator('legend').textContent();
  const chosen = Number(/\((\d+) de 16\)/.exec(legend ?? '')?.[1]);
  expect(chosen).toBeGreaterThan(2);
  expect(chosen).toBeLessThan(16);
  await page.getByRole('button', { name: 'Criar apresentação' }).click();

  await expect(page.getByTestId('presentation-revision')).toHaveText('Revisão 1');
  await expect(page.getByTestId('slide-counter')).toHaveText(`1 / ${chosen}`);
  await expect(page.getByTestId('slide-item-ranking-componentes')).toHaveCount(0);
  await expect(page.getByTestId('slide-item-encerramento')).toHaveCount(1);

  // painel de severidades: SAST sobe (backlog aberto: menos é melhor) => piora; SCA cai => melhora
  await goToSlide(page, 'painel-severidades');
  const sast = el(page, 'cmp-delta:sast.policy.open.by_severity');
  await expect(sast).toHaveAttribute('data-trend', 'worsening');
  await expect(sast).toContainText('+9 · piora');
  const sca = el(page, 'cmp-delta:sca.policy.open.by_severity');
  await expect(sca).toHaveAttribute('data-trend', 'improvement');
  await expect(sca).toContainText('melhora');
  // direção não declarada (apps.total): variação exibida, mas neutra (sem "melhora"/"piora")
  await goToSlide(page, 'painel-graficos');
  const apps = el(page, 'cmp-delta:apps.total');
  await expect(apps).toHaveAttribute('data-trend', 'unknown');
  await expect(apps).toHaveText('+8');
  // cores vêm dos tokens do tema (paleta efetiva): melhora/piora diferentes da neutra
  const dot = async (key: string) => el(page, key).locator('.pill-dot').evaluate((n) => getComputedStyle(n).backgroundColor);
  await goToSlide(page, 'painel-severidades');
  expect(await dot('cmp-delta:sast.policy.open.by_severity')).toBe('rgb(192, 0, 0)');
  expect(await dot('cmp-delta:sca.policy.open.by_severity')).toBe('rgb(46, 158, 91)');
});

test('F06C: ativo local autorizado aparece no encaixe; sem o arquivo, fallback neutro (sem bloquear)', async ({ page, request }) => {
  const dir = process.env.AFRIKA_E2E_BRAND_DIR as string;
  expect(dir, 'pasta descartável de ativos do E2E').toBeTruthy();
  const file = path.join(dir, 'afrika', 'logo-capa.png');
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const img = { width: 64, height: 32, data: new Uint8Array(64 * 32 * 4).fill(0x5d) };
  fs.writeFileSync(file, encodePng(img));
  try {
    const { competenceId } = await seedClient(request, `Cliente Ativos F06C ${run}`);
    const p = await call(request, 'POST', '/api/presentations', { competence_id: competenceId, template_key: 'afrika-modelo', template_version: 2, slots: [], operator: OP });
    await page.goto(`/#/presentations/${p.id}`);
    const logo = el(page, 'brand:logo-capa');
    await expect(logo).toBeVisible();
    expect(await logo.evaluate((n) => (n as HTMLImageElement).naturalWidth)).toBe(64);
    fs.rmSync(file);
    await page.reload();
    await expect(page.getByTestId('slide-counter')).toHaveText('1 / 2');
    await expect(el(page, 'brand:logo-capa')).toHaveCount(0);
    await expect(el(page, 'shape:area-foto')).toBeVisible(); // fallback neutro: a forma do tema
    const view = await call(request, 'GET', `/api/presentations/${p.id}/view`);
    expect(view.brand_assets['logo-capa'].status).toBe('missing');
    expect(view.checks.filter((c: { code: string; level: string }) => c.code === 'brand_asset_missing').map((c: { level: string }) => c.level)).toEqual(['info']);
  } finally {
    fs.rmSync(file, { force: true });
  }
});

test('F06C: detector de overflow encontra estouro real (zona e slide) e nada no slide íntegro', async ({ page, request }) => {
  const { competenceId } = await seedClient(request, `Cliente Overflow F06C ${run}`);
  const p = await call(request, 'POST', '/api/presentations', { competence_id: competenceId, template_key: 'afrika-modelo', template_version: 2, slots: ['painel-kpis'], operator: OP });
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto(`/#/render/${p.id}`);
  await page.locator('html[data-render-ready="1"]').waitFor({ state: 'attached' });
  expect((await collectOverflow(page)).filter((f) => f.kind !== 'ellipsis')).toEqual([]);
  // 1) texto longo sem quebra: vazamento no título e corte na moldura da zona
  await page.evaluate(() => {
    const t = document.querySelector('[data-el="zone-title:table"]') as HTMLElement;
    t.style.whiteSpace = 'nowrap';
    t.textContent = 'Título sintético propositalmente longo para estourar a moldura da zona '.repeat(4);
  });
  const cut = (await collectOverflow(page)).map((f) => `${f.key} ${f.kind}`);
  expect(cut).toEqual(expect.arrayContaining(['zone-title:table spill-x', 'zone:table clipped-x'])); // vaza do título e a zona corta
  // 2) elemento de texto além da moldura da zona e do canvas: detectado pela geometria
  await page.evaluate(() => {
    const zone = document.querySelector('[data-el="zone:text"]') as HTMLElement;
    const span = document.createElement('span');
    span.dataset.el = 'injetado';
    span.style.cssText = 'position:absolute;left:600px;top:0;white-space:nowrap';
    span.textContent = 'Texto sintético fora da zona e do slide';
    zone.appendChild(span);
  });
  const outside = (await collectOverflow(page)).filter((f) => f.key === 'injetado').map((f) => f.kind);
  expect(outside).toEqual(expect.arrayContaining(['outside-zone', 'outside-slide']));
});

test('F06C: resposta atrasada da disponibilidade não sobrescreve a competência escolhida depois', async ({ page, request }) => {
  const name = `Cliente Atraso F06C ${run}`;
  const { clientId } = await seedClient(request, name);
  await approved(request, clientId, '2026-07', { 'apps.total': 110 });
  let delayed = 0;
  await page.route('**/availability?competence_id=*', async (route) => {
    if (delayed++ === 0) await new Promise((r) => setTimeout(r, 1500)); // 1ª resposta chega DEPOIS da 2ª
    await route.continue();
  });
  await page.goto('/#/presentations');
  await page.getByLabel('Cliente', { exact: true }).selectOption({ label: name });
  await page.getByLabel('Template (vazio = escolhido para o dono)').selectOption('afrika-modelo@2');
  await page.getByLabel('Competência aprovada').selectOption({ label: '2026-07 — revisão oficial 1' });
  await page.getByLabel('Competência aprovada').selectOption({ label: '2026-09 — revisão oficial 1' });
  const legend = page.getByTestId('slot-picker').locator('legend');
  await expect(legend).toContainText('competência 2026-09');
  await page.waitForTimeout(2000); // a resposta atrasada (2026-07) chega aqui e deve ser descartada
  await expect(legend).toContainText('competência 2026-09');
  expect(delayed).toBeGreaterThanOrEqual(2);
});
