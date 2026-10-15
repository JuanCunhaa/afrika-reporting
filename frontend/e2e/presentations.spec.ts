import { APIRequestContext, Page, expect, test } from '@playwright/test';
import { SYNTHETIC_SECRET_NAMES, SYNTHETIC_SECRET_VALUES } from './fixture-creds';

// F06A: templates, apresentação a partir de revisões APROVADAS, pré-visualização navegável, edição editorial,
// persistência, dados de origem e integridade. Dados 100% sintéticos (valores manuais justificados); sem Veracode.
const run = Date.now().toString(36);
const bodies: string[] = [];
const OP = 'Operadora E2E';

test.beforeEach(({ page }) => {
  page.on('request', (req) => {
    expect(['127.0.0.1', 'localhost'], `requisição externa: ${req.url()}`).toContain(new URL(req.url()).hostname);
  });
  page.on('response', async (res) => {
    if (/\/api\/(presentation|template)/.test(res.url())) bodies.push(await res.text().catch(() => ''));
  });
});

test.afterEach(() => {
  const all = bodies.join('\n');
  for (const secret of [...SYNTHETIC_SECRET_VALUES, ...SYNTHETIC_SECRET_NAMES, 'credential_ref']) expect(all).not.toContain(secret);
  bodies.length = 0;
});

const sev = (...n: number[]) => {
  const keys = ['VERY_HIGH', 'HIGH', 'MEDIUM', 'LOW', 'VERY_LOW', 'INFORMATIONAL', 'UNKNOWN'];
  return { ...Object.fromEntries(keys.map((k, i) => [k, n[i]])), total: n.reduce((a, b) => a + b, 0) };
};
const TOP = { top: Array.from({ length: 12 }, (_, i) => ({ application_guid: `g${i}`, name: `App Sintética ${String(i).padStart(2, '0')}`, findings: 30 - i })), total: 294 };
const BUS = { items: [{ business_unit_id: 'b1', name: 'BU Sintética 1', applications: 7 }, { business_unit_id: 'b2', name: 'BU Sintética 2', applications: 3 }], unknown: 0, distinct_applications: 10 };

async function call(request: APIRequestContext, method: string, url: string, data?: unknown) {
  const r = await request.fetch(url, { method, data });
  expect(r.status(), `${method} ${url}: ${await r.text()}`).toBeLessThan(300);
  return r.json();
}

async function competence(request: APIRequestContext, clientId: string, label: string, values: Record<string, unknown>, approve = true) {
  const comp = await call(request, 'POST', '/api/competences', { owner_kind: 'client', owner_id: clientId, competence: label, operator: OP });
  const base = `/api/competences/${comp.id}/revisions/1`;
  const lock = async () => (await call(request, 'GET', base)).lock_version;
  for (const [metric, value] of Object.entries(values))
    await call(request, 'PUT', `${base}/metrics/${metric}`, { value, justification: 'Valor sintético justificado (E2E F06A)', operator: OP, expected_lock_version: await lock() });
  if (!approve) return comp.id as string;
  await call(request, 'PUT', `${base}/required`, { metric_ids: ['apps.total'], operator: OP, expected_lock_version: await lock() });
  await call(request, 'POST', `${base}/submit`, { operator: OP, expected_lock_version: await lock() });
  await call(request, 'POST', `${base}/approve`, { approver: 'Aprovador E2E', expected_lock_version: await lock() });
  return comp.id as string;
}

const canvas = (page: Page) => page.getByTestId('slide-canvas');
async function goToSlide(page: Page, slideId: string) {
  await page.getByTestId(`slide-item-${slideId}`).getByRole('button').first().click();
}

test('template → apresentação de revisão aprovada → navegação → edição → persistência → integridade', async ({ page, request }) => {
  const name = `Apresentações E2E ${run}`;
  const client = await call(request, 'POST', '/api/clients', { name });
  await competence(request, client.id, '2026-07', { 'apps.total': 44, 'sast.policy.open.by_severity': sev(1, 1, 1, 1, 0, 0, 0) });
  const sep = await competence(request, client.id, '2026-09', {
    'apps.total': 50,
    'sast.policy.open.by_severity': sev(1, 2, 3, 4, 0, 0, 0),
    'sca.policy.open.by_severity': sev(0, 1, 1, 2, 0, 1, 0),
    'sast.policy.open.top_applications': TOP,
    'apps.by_business_unit': BUS,
  });
  await competence(request, client.id, '2026-06', { 'apps.total': 1 }, false); // rascunho: indisponível
  const before = await call(request, 'GET', `/api/competences/${sep}/official`);

  // Escolha do template pelo dono e criação a partir da competência aprovada
  await page.goto('/#/presentations');
  await expect(page.getByTestId('theme-notice')).toContainText('provisório');
  await page.getByLabel('Cliente', { exact: true }).selectOption({ label: name });
  await page.getByLabel('Operador (declarado)').fill(OP);
  await expect(page.getByTestId('template-selection')).toHaveText('Nenhum template escolhido.');
  await page.getByLabel('Escolher template').selectOption('demo-executivo@1');
  await page.getByRole('button', { name: 'Salvar escolha' }).click();
  await expect(page.getByTestId('template-selection')).toContainText('demo-executivo v1');
  await expect(page.getByTestId('pending-competences')).toContainText('2026-06');
  await expect(page.getByLabel('Competência aprovada').locator('option', { hasText: '2026-06' })).toHaveCount(0);
  await page.getByLabel('Competência aprovada').selectOption({ label: '2026-09 — revisão oficial 1' });
  await page.getByRole('button', { name: 'Criar apresentação' }).click();

  // Pré-visualização navegável (16:9) com valores aprovados
  await expect(page.getByTestId('presentation-revision')).toHaveText('Revisão 1');
  await expect(canvas(page)).toBeVisible();
  const box = await page.locator('.slide-frame').boundingBox();
  expect(Math.abs(box!.width / box!.height - 16 / 9)).toBeLessThan(0.02);
  await expect(page.getByTestId('cover-competence')).toContainText('Competência 2026-09');
  await expect(page.getByTestId('slide-source')).toContainText('revisão aprovada 1');
  await expect(page.getByTestId('slide-counter')).toHaveText('1 / 9');
  await page.getByRole('button', { name: 'Próximo slide →' }).click();
  await expect(page.getByTestId('slide-counter')).toHaveText('2 / 9');
  await page.getByLabel('Pré-visualização (setas navegam)').press('ArrowRight');
  await expect(page.getByTestId('slide-counter')).toHaveText('3 / 9');
  await expect(page.getByTestId('kpi-apps.total')).toContainText('50');
  await expect(page.getByTestId('kpi-apps.total')).toContainText('Manual'); // valor manual identificado
  await expect(page.getByTestId('kpi-sast.policy.open.by_severity')).toContainText('10');
  await page.getByLabel('Pré-visualização (setas navegam)').press('ArrowRight');
  await expect(page.getByTestId('cmp-apps.total')).toContainText('lacuna'); // agosto sem aprovação
  await expect(page.getByTestId('cmp-apps.total')).toContainText('— (lacuna)');
  await goToSlide(page, 'severidade-sast');
  await expect(page.getByTestId('sev-Média')).toContainText('3');
  await expect(page.getByTestId('sev-total')).toContainText('Total: 10');
  await goToSlide(page, 'serie-sast');
  await expect(page.getByTestId('gap-2026-08')).toBeAttached(); // lacuna explícita, sem interpolação
  await expect(page.getByTestId('chart-gaps')).toContainText('2026-04, 2026-05, 2026-06, 2026-08');
  await expect(page.getByTestId('pt-sast.policy.open.by_severity-2026-07')).toContainText('4');
  await expect(page.getByTestId('pt-sast.policy.open.by_severity-2026-09')).toContainText('10');
  await page.screenshot({ path: 'test-results/evidence/f06a-serie-com-lacunas.png', fullPage: true });
  await goToSlide(page, 'top-apps');
  await expect(page.getByTestId('rank-1')).toContainText('App Sintética 00');
  await expect(page.getByTestId('rank-10')).toContainText('21');
  await expect(page.getByTestId('rank-11')).toHaveCount(0);

  // Edição editorial: título, reordenação, remoção, inclusão, apresentadores
  await goToSlide(page, 'capa');
  await page.getByLabel('Título (obrigatório)').fill('Relatório E2E editado');
  await expect(canvas(page)).toContainText('Relatório E2E editado'); // pré-visualização ao vivo
  await expect(page.getByTestId('presentation-revision')).toContainText('alterações não salvas');
  await expect(page.getByRole('button', { name: 'Remover slide: capa' })).toBeDisabled(); // obrigatório
  await page.getByRole('button', { name: 'Remover slide: comparacao' }).click();
  await page.getByRole('button', { name: 'Mover para cima: recomendacoes' }).click();
  await goToSlide(page, 'recomendacoes');
  await page.getByLabel('Tópicos (um por linha)').fill('Priorizar findings Muito alta\nRevisar SCA');
  await page.getByLabel('Tipo do novo slide').selectOption('bar_chart');
  await page.getByRole('button', { name: 'Adicionar slide' }).click();
  await page.getByLabel('Título (obrigatório)').fill('Aplicações por BU');
  await page.getByLabel('Título do gráfico').fill('Distribuição aprovada por BU');
  await page.getByLabel('apps.by_business_unit', { exact: true }).check();
  await expect(page.getByTestId('bar-BU Sintética 1')).toContainText('7');
  // a edição foi para o slide NOVO (não para o vizinho), mesmo com a pré-visualização ainda pendente
  await expect(page.locator('[data-testid^="slide-item-bar-chart-"]')).toContainText('Aplicações por BU');
  await expect(page.getByTestId('slide-item-top-apps')).toContainText('Top 10 aplicações (SAST Policy)');
  await page.getByRole('button', { name: 'Adicionar apresentador' }).click();
  await page.getByLabel('Nome do apresentador 1').fill('Pessoa Apresentadora');
  await page.getByLabel('Resumo da alteração').fill('Edição E2E');
  await page.getByRole('button', { name: 'Salvar revisão' }).click();
  await expect(page.getByTestId('presentation-revision')).toHaveText('Revisão 2');
  await expect(page.getByTestId('slide-counter')).toContainText('/ 9');

  // Persistência após recarregar
  await page.reload();
  await expect(page.getByTestId('presentation-revision')).toHaveText('Revisão 2');
  await expect(canvas(page)).toContainText('Relatório E2E editado');
  await expect(canvas(page)).toContainText('Pessoa Apresentadora');
  await expect(page.getByTestId('slide-item-comparacao')).toHaveCount(0);
  const order = await page.locator('[data-testid^="slide-item-"]').evaluateAll((els) => els.map((e) => e.getAttribute('data-testid')));
  expect(order.indexOf('slide-item-recomendacoes')).toBeLessThan(order.indexOf('slide-item-top-apps'));

  // Dados de origem e integridade
  await page.getByRole('button', { name: 'Ver dados de origem' }).click();
  await expect(page.getByTestId('source-apps.total')).toContainText('50');
  await expect(page.getByTestId('source-apps.total')).toContainText('Valor sintético justificado (E2E F06A)');
  await expect(page.getByTestId('source-apps.total')).toContainText('NOT_VERIFIED');
  await page.getByRole('button', { name: 'Verificar integridade' }).click();
  await expect(page.getByTestId('presentation-integrity')).toContainText('Integridade: OK · 2 revisão(ões)');

  // Revisão anterior preservada (somente leitura)
  await page.getByRole('button', { name: 'Visualizar revisão 1' }).click();
  await expect(page.getByTestId('presentation-revision')).toHaveText('Revisão 1 (somente leitura)');
  await expect(page.getByTestId('slide-item-comparacao')).toHaveCount(1);
  await page.getByRole('button', { name: 'Voltar à revisão atual' }).click();
  await expect(page.getByTestId('presentation-revision')).toHaveText('Revisão 2');

  // Modo apresentação
  await page.getByRole('button', { name: 'Apresentar' }).click();
  const overlay = page.getByRole('dialog', { name: 'Modo apresentação' });
  await expect(overlay).toBeVisible();
  await overlay.press('ArrowRight');
  await overlay.press('Escape');
  await expect(overlay).toHaveCount(0);
  await goToSlide(page, 'kpis');
  await page.screenshot({ path: 'test-results/evidence/f06a-editor-kpis.png', fullPage: true });

  // O editor não alterou o snapshot aprovado
  const after = await call(request, 'GET', `/api/competences/${sep}/official`);
  expect(after.snapshots.map((s: { row_hash: string }) => s.row_hash)).toEqual(before.snapshots.map((s: { row_hash: string }) => s.row_hash));
  expect(after.approval).toEqual(before.approval);
  expect((await call(request, 'GET', `/api/competences/${sep}/integrity`)).ok).toBe(true);
});

test('competência sem aprovação não gera apresentação; indicador ausente aparece como indisponível', async ({ page, request }) => {
  const name = `Lacunas E2E ${run}`;
  const client = await call(request, 'POST', '/api/clients', { name });
  const draft = await competence(request, client.id, '2026-05', { 'apps.total': 3 }, false);
  const refused = await request.post('/api/presentations', { data: { competence_id: draft, operator: OP, template_key: 'demo-executivo' } });
  expect(refused.status()).toBe(409);
  expect((await refused.json()).error.code).toBe('no_approved_revision');
  const ok = await competence(request, client.id, '2026-04', { 'apps.total': 3 });
  const p = await call(request, 'POST', '/api/presentations', { competence_id: ok, operator: OP, template_key: 'demo-executivo' });
  await page.goto(`/#/presentations/${p.id}`);
  await goToSlide(page, 'kpis');
  await expect(page.getByTestId('kpi-sast.policy.open.by_severity')).toContainText('ausente');
  await expect(page.getByTestId('kpi-sast.policy.open.by_severity')).toContainText('valor indisponível na revisão aprovada');
  await expect(page.getByTestId('issues')).toContainText('[bloqueio] sast.policy.open.by_severity: sem valor na revisão aprovada');
  await expect(page.getByTestId('readiness')).toContainText('bloqueio(s)');
  await goToSlide(page, 'severidade-sast');
  await expect(page.getByTestId('slide-unavailable')).toContainText('Nenhum número é presumido');
  await page.screenshot({ path: 'test-results/evidence/f06a-indisponivel.png', fullPage: true });
});
