import { APIRequestContext, Page, expect, test } from '@playwright/test';

// F08 — análise assistida no editor: gerar (executiva/técnica) com o provedor LOCAL determinístico, ver indicadores de
// origem e validação, revisar/aprovar, aplicar ao slide (nova revisão), editar (valor inventado bloqueia), regenerar,
// comparar, rejeitar, desabilitar por slide e aviso de desatualização. Dados 100% sintéticos; nenhuma requisição sai
// do loopback (nenhum provedor externo, nenhuma Veracode).
const run = Date.now().toString(36);
const OP = 'Operadora Análise E2E';

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

async function approveRevision(request: APIRequestContext, cid: string, n: number, values: Record<string, unknown>) {
  const base = `/api/competences/${cid}/revisions/${n}`;
  const lock = async () => (await call(request, 'GET', base)).lock_version;
  for (const [metric, value] of Object.entries(values))
    await call(request, 'PUT', `${base}/metrics/${metric}`, { value, justification: 'Valor sintético justificado (E2E F08)', operator: OP, expected_lock_version: await lock() });
  await call(request, 'PUT', `${base}/required`, { metric_ids: ['apps.total'], operator: OP, expected_lock_version: await lock() });
  await call(request, 'POST', `${base}/submit`, { operator: OP, expected_lock_version: await lock() });
  await call(request, 'POST', `${base}/approve`, { approver: 'Aprovador E2E', expected_lock_version: await lock() });
}

async function setup(request: APIRequestContext, name: string) {
  const client = await call(request, 'POST', '/api/clients', { name });
  for (const [label, i] of [['2026-08', 0], ['2026-09', 1]] as const) {
    const comp = await call(request, 'POST', '/api/competences', { owner_kind: 'client', owner_id: client.id, competence: label, operator: OP });
    await approveRevision(request, comp.id, 1, { 'apps.total': 60 + i, 'sast.policy.open.by_severity': sev(1, 2 + i, 4, 3, 0, 0, 0), 'sca.policy.open.by_severity': sev(0, 1, 2, 1, 0, 0, 0) });
    if (label === '2026-09') {
      const p = await call(request, 'POST', '/api/presentations', { competence_id: comp.id, template_key: 'demo-executivo', template_version: 1, operator: OP });
      return { pid: p.id as string, cid: comp.id as string };
    }
  }
  throw new Error('setup');
}

async function openSlide(page: Page, pid: string, slide: string) {
  await page.goto(`/#/presentations/${pid}`);
  await page.locator('#e-operator').fill(OP);
  await page.getByTestId(`slide-item-${slide}`).locator('button.slide-pick').click();
  await expect(page.getByTestId('interpretation-panel')).toBeVisible();
}

const panel = (page: Page) => page.getByTestId('interpretation-panel');
const detail = (page: Page) => page.getByTestId('interpretation-detail');

test('gera, revisa, aprova e aplica a análise; edição inventada bloqueia; regenera, compara e rejeita', async ({ page, request }) => {
  test.setTimeout(90_000);
  const { pid } = await setup(request, `Análise E2E ${run}`);
  await openSlide(page, pid, 'sumario');
  await expect(page.getByTestId('interpretation-provider')).toHaveText('deterministic-demo');
  await expect(panel(page)).toContainText('nada é enviado para fora');

  await panel(page).getByLabel('Técnica').check();
  await page.getByTestId('interpretation-generate').click();
  await expect(detail(page)).toHaveAttribute('data-status', 'GENERATED');
  await expect(page.getByTestId('interpretation-validation')).toHaveText('Validação automática: sem bloqueios');
  await expect(page.getByTestId('interpretation-text')).toContainText('61 aplicações em 2026-09');
  await expect(page.getByTestId('interpretation-text')).toContainText('[apps.total]');
  await expect(page.getByTestId('interpretation-indicators')).toContainText('Aplicações no escopo');
  await expect(page.getByTestId('interpretation-indicators')).toContainText('manual');

  await page.getByTestId('interpretation-review').click();
  await expect(detail(page)).toHaveAttribute('data-status', 'IN_REVIEW');
  await page.getByTestId('interpretation-approve').click();
  await expect(detail(page)).toHaveAttribute('data-status', 'APPROVED');
  const text = (await call(request, 'GET', `/api/presentations/${pid}/interpretations`)).items[0].text as string;

  await page.getByTestId('interpretation-apply').click();
  await expect(page.getByTestId('interpretation-applied')).toContainText('revisão 2');
  await expect(page.getByTestId('presentation-revision')).toHaveText('Revisão 2');
  await expect(page.getByTestId('slide-canvas')).toContainText(text.slice(0, 60));
  const doc = (await call(request, 'GET', `/api/presentations/${pid}/revisions/2`)).document;
  expect(doc.slides.find((s: { slide_id: string }) => s.slide_id === 'sumario').fields.body).toBe(text);

  // edição humana com número inventado: nova versão em revisão, bloqueada para aprovação
  await page.getByTestId('interpretation-edit').click();
  await page.getByLabel(/^Texto \(/).fill('SAST abertos: 999 findings em 2026-09.');
  await page.getByTestId('interpretation-save-edit').click();
  await expect(detail(page)).toHaveAttribute('data-status', 'IN_REVIEW');
  await expect(detail(page)).toHaveAttribute('data-valid', 'false');
  await expect(page.getByTestId('interpretation-issues')).toContainText('999');
  await expect(page.getByTestId('interpretation-approve')).toBeDisabled();

  // regenerar (executiva), comparar com a versão aprovada e rejeitar com motivo
  await panel(page).getByLabel('Executiva').check();
  await page.getByTestId('interpretation-regenerate').click();
  await expect(detail(page)).toHaveAttribute('data-status', 'GENERATED');
  await expect(page.getByTestId('interpretation-versions').locator('tbody tr')).toHaveCount(3);
  await page.locator('#interp-compare').selectOption({ label: 'v1 (Aprovada)' });
  await page.getByRole('button', { name: 'Comparar versões' }).click();
  await expect(page.getByTestId('interpretation-diff')).toContainText('v1 → v3');
  await page.getByLabel('Motivo da rejeição').fill('Prefiro a versão técnica');
  await page.getByTestId('interpretation-reject').click();
  await expect(detail(page)).toHaveAttribute('data-status', 'REJECTED');
  await expect(page.getByTestId('interpretation-events')).toContainText('Prefiro a versão técnica');
  // nada disso mudou a apresentação: continua na revisão 2 com o texto aprovado
  await expect(page.getByTestId('presentation-revision')).toHaveText('Revisão 2');
});

test('desabilita a análise por slide e sinaliza interpretação desatualizada após nova aprovação', async ({ page, request }) => {
  test.setTimeout(90_000);
  const { pid, cid } = await setup(request, `Análise Desatualizada E2E ${run}`);
  await openSlide(page, pid, 'kpis');
  await page.getByTestId('interpretation-disable').click();
  await expect(page.getByTestId('interpretation-disabled')).toBeVisible();
  await page.getByRole('button', { name: 'Reabilitar análise' }).click();
  await expect(page.getByTestId('interpretation-generate')).toBeVisible();
  await page.getByTestId('interpretation-generate').click();
  await expect(detail(page)).toHaveAttribute('data-status', 'GENERATED');
  await page.getByTestId('interpretation-review').click();
  await expect(detail(page)).toHaveAttribute('data-status', 'IN_REVIEW');

  // nova revisão aprovada da competência + troca explícita de fontes
  await call(request, 'POST', `/api/competences/${cid}/revisions`, { operator: OP });
  await approveRevision(request, cid, 2, { 'apps.total': 75 });
  await call(request, 'POST', `/api/presentations/${pid}/rebind`, { expected_revision: 1, operator: OP });

  await page.reload(); // mesma URL (hash): recarrega o editor para ler o estado novo
  await page.locator('#e-operator').fill(OP);
  await page.getByTestId('slide-item-kpis').locator('button.slide-pick').click();
  await expect(page.getByTestId('presentation-revision')).toHaveText('Revisão 2');
  await expect(page.getByTestId('interpretation-stale')).toContainText('desatualizada');
  await expect(page.getByTestId('interpretation-approve')).toBeDisabled();
  await page.getByTestId('interpretation-regenerate').click();
  await expect(detail(page)).toHaveAttribute('data-status', 'GENERATED');
  await expect(page.getByTestId('interpretation-stale')).toHaveCount(0);
  await expect(page.getByTestId('interpretation-text')).toContainText('75 aplicações');

  // capa não recebe análise
  await page.getByTestId('slide-item-capa').locator('button.slide-pick').click();
  await expect(page.getByTestId('interpretation-not-applicable')).toBeVisible();
});
