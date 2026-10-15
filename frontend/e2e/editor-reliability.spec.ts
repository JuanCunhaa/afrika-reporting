import { APIRequestContext, Page, Request, Route, expect, test } from '@playwright/test';

// F06B.1 — confiabilidade do editor de apresentações: edições rápidas, duplo clique, salvamento concorrente, resposta
// atrasada, falha na releitura após HTTP 200, resposta antiga chegando depois de edição mais recente e persistência.
// A rede é manipulada só por interceptação no navegador (atraso/falha determinísticos), sem retries. Dados sintéticos.
const run = Date.now().toString(36);
const OP = 'Operadora Confiabilidade';

async function call(request: APIRequestContext, method: string, url: string, data?: unknown) {
  const r = await request.fetch(url, { method, data });
  expect(r.status(), `${method} ${url}: ${await r.text()}`).toBeLessThan(300);
  return r.json();
}

/** Cliente + competência aprovada + apresentação (template mínimo) — retorna o id da apresentação. */
async function presentation(request: APIRequestContext, tag: string): Promise<string> {
  const client = await call(request, 'POST', '/api/clients', { name: `Confiabilidade ${tag} ${run}` });
  const comp = await call(request, 'POST', '/api/competences', { owner_kind: 'client', owner_id: client.id, competence: '2026-09', operator: OP });
  const base = `/api/competences/${comp.id}/revisions/1`;
  const lock = async () => (await call(request, 'GET', base)).lock_version;
  await call(request, 'PUT', `${base}/metrics/apps.total`, { value: 7, justification: 'Valor sintético (confiabilidade F06B.1)', operator: OP, expected_lock_version: await lock() });
  await call(request, 'PUT', `${base}/required`, { metric_ids: ['apps.total'], operator: OP, expected_lock_version: await lock() });
  await call(request, 'POST', `${base}/submit`, { operator: OP, expected_lock_version: await lock() });
  await call(request, 'POST', `${base}/approve`, { approver: 'Aprovador Sintético', expected_lock_version: await lock() });
  return (await call(request, 'POST', '/api/presentations', { competence_id: comp.id, template_key: 'demo-minimo', operator: OP })).id;
}

async function openEditor(page: Page, pid: string) {
  await page.goto(`/#/presentations/${pid}`);
  await expect(page.getByTestId('presentation-revision')).toHaveText('Revisão 1');
  await page.getByLabel('Operador (declarado)').fill(OP);
}

const title = (page: Page) => page.getByLabel('Título (obrigatório)');
const badge = (page: Page) => page.getByTestId('presentation-revision');
const canvas = (page: Page) => page.getByTestId('slide-canvas');
const saveBtn = (page: Page) => page.getByRole('button', { name: 'Salvar revisão' });
const isPut = (r: Request) => r.method() === 'PUT' && /\/api\/presentations\/[^/]+\/document$/.test(r.url());

async function savedDocument(request: APIRequestContext, pid: string, n: number) {
  return (await call(request, 'GET', `/api/presentations/${pid}/revisions/${n}`)).document;
}

test('duas edições em sequência rápida e duplo clique em Salvar geram UMA revisão com as duas edições', async ({ page, request }) => {
  const pid = await presentation(request, 'rapidas');
  await openEditor(page, pid);
  const puts: string[] = [];
  page.on('request', (r) => isPut(r) && puts.push(r.url()));
  await page.getByLabel('Subtítulo').fill('Subtítulo rápido');
  await title(page).fill('Título rápido'); // segunda edição imediatamente, sem esperar a pré-visualização
  await saveBtn(page).dblclick();
  await expect(badge(page)).toHaveText('Revisão 2');
  await expect(page.getByTestId('editor-message')).toContainText('Revisão 2 salva');
  expect(puts).toHaveLength(1);
  const doc = await savedDocument(request, pid, 2);
  expect(doc.slides[0].fields).toMatchObject({ title: 'Título rápido', subtitle: 'Subtítulo rápido' });
  expect((await call(request, 'GET', `/api/presentations/${pid}`)).current_revision).toBe(2);
});

test('resposta de salvamento atrasada: edição feita durante o salvamento não é perdida', async ({ page, request }) => {
  const pid = await presentation(request, 'atrasada');
  await openEditor(page, pid);
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  await page.route(/\/api\/presentations\/[^/]+\/document$/, async (route) => {
    await gate; // segura a resposta do PUT até a edição seguinte acontecer
    await route.continue();
  });
  await title(page).fill('Versão salva');
  await saveBtn(page).click();
  await expect(saveBtn(page)).toBeDisabled(); // salvando
  await title(page).fill('Editado durante o salvamento');
  release();
  await expect(badge(page)).toHaveText('Revisão 2 · alterações não salvas');
  await expect(title(page)).toHaveValue('Editado durante o salvamento');
  await expect(canvas(page)).toContainText('Editado durante o salvamento');
  expect((await savedDocument(request, pid, 2)).slides[0].fields.title).toBe('Versão salva');
  await page.unroute(/\/api\/presentations\/[^/]+\/document$/);
  await saveBtn(page).click();
  await expect(badge(page)).toHaveText('Revisão 3');
  expect((await savedDocument(request, pid, 3)).slides[0].fields.title).toBe('Editado durante o salvamento');
});

test('falha na releitura após HTTP 200: o salvamento é reconhecido, sem retry e sem "alterações não salvas"', async ({ page, request }) => {
  const pid = await presentation(request, 'releitura');
  await openEditor(page, pid);
  let saved = false;
  const gets: string[] = [];
  const pattern = /\/api\/presentations\/[^/?]+(\/[^?]*)?(\?.*)?$/;
  await page.route(pattern, async (route: Route) => {
    const req = route.request();
    if (isPut(req)) {
      const res = await route.fetch(); // PUT chega ao servidor e grava (HTTP 200)
      saved = res.ok();
      return route.fulfill({ response: res });
    }
    if (saved && req.method() === 'GET') {
      gets.push(req.url());
      return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'unavailable', message: 'Indisponível (simulado)', details: [] } }) });
    }
    return route.continue();
  });
  await title(page).fill('Gravado apesar da releitura');
  await saveBtn(page).click();
  await expect(page.getByTestId('editor-message')).toContainText('Revisão 2 salva');
  await expect(page.getByTestId('editor-error')).toContainText('A revisão 2 foi gravada, mas a releitura falhou');
  await expect(badge(page)).toHaveText('Revisão 2');
  await expect(saveBtn(page)).toBeDisabled(); // nada pendente: não convida a salvar de novo
  const attempts = gets.length;
  await page.waitForTimeout(800);
  expect(gets.length, 'nenhuma nova tentativa automática').toBe(attempts);
  await page.unroute(pattern);
  await page.reload(); // reinicialização da tela: o que foi gravado persiste
  await expect(badge(page)).toHaveText('Revisão 2');
  await expect(title(page)).toHaveValue('Gravado apesar da releitura');
  await expect(canvas(page)).toContainText('Gravado apesar da releitura');
});

test('resposta antiga da pré-visualização chegando depois da edição mais recente é descartada', async ({ page, request }) => {
  const pid = await presentation(request, 'antiga');
  await openEditor(page, pid);
  const held: (() => void)[] = [];
  let holdNext = true;
  await page.route(/\/api\/presentations\/[^/]+\/preview$/, async (route) => {
    if (holdNext) {
      holdNext = false;
      await new Promise<void>((r) => held.push(r)); // primeira pré-visualização fica presa
    }
    await route.continue();
  });
  await title(page).fill('Edição antiga');
  await expect.poll(() => held.length).toBe(1);
  await title(page).fill('Edição mais recente');
  await expect(canvas(page)).toContainText('Edição mais recente');
  held[0](); // a resposta antiga chega por último
  await page.waitForTimeout(600);
  await expect(canvas(page)).toContainText('Edição mais recente');
  await expect(canvas(page)).not.toContainText('Edição antiga');

  // Descartar com pré-visualização em voo: a resposta tardia não ressuscita o conteúdo descartado
  holdNext = true;
  await title(page).fill('Conteúdo descartado');
  await expect.poll(() => held.length).toBe(2);
  await page.getByRole('button', { name: 'Descartar alterações' }).click();
  await expect(badge(page)).toHaveText('Revisão 1');
  held[1]();
  await page.waitForTimeout(600);
  await expect(canvas(page)).not.toContainText('Conteúdo descartado');
  await expect(title(page)).not.toHaveValue('Conteúdo descartado');

  // Rascunho inválido mostra erro; voltar ao texto salvo limpa o erro e restaura a visualização salva
  const original = await title(page).inputValue();
  await title(page).fill('');
  await expect(page.getByTestId('preview-error')).toContainText('Campo obrigatório');
  await title(page).fill(original);
  await expect(page.getByTestId('preview-error')).toHaveCount(0);
  await title(page).fill('Temporário');
  await expect(canvas(page)).toContainText('Temporário');
  await title(page).fill(original);
  await expect(badge(page)).toHaveText('Revisão 1');
  await expect(canvas(page)).not.toContainText('Temporário');
});

test('salvamento concorrente em duas abas: uma vence, a outra recebe conflito sem perder a edição', async ({ browser, request }) => {
  const pid = await presentation(request, 'concorrente');
  const [a, b] = await Promise.all([browser.newContext(), browser.newContext()]);
  const pa = await a.newPage();
  const pb = await b.newPage();
  await openEditor(pa, pid);
  await openEditor(pb, pid);
  await title(pa).fill('Aba A');
  await title(pb).fill('Aba B');
  await saveBtn(pa).click();
  await expect(badge(pa)).toHaveText('Revisão 2');
  await saveBtn(pb).click();
  await expect(pb.getByTestId('editor-error')).toContainText('revisão 2');
  await expect(badge(pb)).toHaveText('Revisão 1 · alterações não salvas');
  await expect(title(pb)).toHaveValue('Aba B'); // edição preservada para o operador decidir
  expect((await call(request, 'GET', `/api/presentations/${pid}`)).current_revision).toBe(2);
  expect((await savedDocument(request, pid, 2)).slides[0].fields.title).toBe('Aba A');
  await pb.getByRole('button', { name: 'Descartar alterações' }).click();
  await expect(badge(pb)).toHaveText('Revisão 2');
  await expect(title(pb)).toHaveValue('Aba A');
  await a.close();
  await b.close();
});
