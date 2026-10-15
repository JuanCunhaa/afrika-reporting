import { APIRequestContext, Page, expect, test } from '@playwright/test';
import { SYNTHETIC_SECRET_NAMES, SYNTHETIC_SECRET_VALUES } from './fixture-creds';

// F03: construtor de escopos contra o backend em modo FIXTURE (tenant sintético `alpha`; nenhuma Veracode real).
// Valores esperados calculados dos dados brutos do fixture (backend/app/veracode/fixtures.py):
// universo BU1+BU2 = 60 apps; Sub A (Team 01) ∩ universo = 17; Sub B (BU2) = 30; sobreposição A∩B = 3;
// não classificadas = 16; com Sub C ((BU1 E NÃO tag web) OU VERY_HIGH) = 12 → não classificadas 13, sobreposição 9.
const run = Date.now().toString(36);
const bodies: string[] = [];

test.beforeEach(({ page }) => {
  page.on('request', (req) => {
    expect(['127.0.0.1', 'localhost'], `requisição externa: ${req.url()}`).toContain(new URL(req.url()).hostname);
  });
  page.on('response', async (res) => {
    if (/\/api\/(scope|veracode)/.test(res.url())) bodies.push(await res.text().catch(() => ''));
  });
});

test.afterEach(() => {
  const all = bodies.join('\n');
  for (const secret of [...SYNTHETIC_SECRET_VALUES, ...SYNTHETIC_SECRET_NAMES]) expect(all).not.toContain(secret);
  bodies.length = 0;
});

async function createClient(request: APIRequestContext, name: string, credentialRef = 'env:AFRIKA_DEMO_VERACODE') {
  const conns = await (await request.get('/api/connections?limit=200')).json();
  let conn = conns.items.find((c: { credential_ref: string }) => c.credential_ref === credentialRef);
  if (!conn)
    conn = await (
      await request.post('/api/connections', { data: { name: `Conexão ${name}`, region: 'commercial', credential_ref: credentialRef } })
    ).json();
  const client = await (await request.post('/api/clients', { data: { name, connection_id: conn.id } })).json();
  return { client, conn };
}

async function openScopes(page: Page, clientId: string, name: string) {
  await page.goto(`/#/clients/${clientId}`);
  await page.getByRole('link', { name: 'Escopos', exact: true }).click();
  await expect(page.getByRole('heading', { level: 2 })).toHaveText(`Escopos — ${name}`);
}

const owner = (page: Page, name: string) => page.getByRole('navigation', { name: 'Donos do escopo' }).getByRole('button', { name: new RegExp(`^${name}`) });
const check = (page: Page, group: string, label: string) =>
  page.getByRole('group', { name: group }).getByLabel(label, { exact: true }).check();
const preview = (page: Page) => page.getByRole('article', { name: 'Pré-visualização' });

async function saveVersion(page: Page, version: number) {
  await page.getByRole('button', { name: 'Salvar nova versão' }).click();
  await expect(page.getByTestId('scope-status')).toHaveText(`Versão ${version} · Ativo`);
}

test('aplicações: modo simples, subclientes, avançado AND/OR/NOT, sobreposição, não classificadas e versões', async ({ page, request }) => {
  const name = `Escopos E2E ${run}`;
  const { client } = await createClient(request, name);
  for (const sub of ['Sub A', 'Sub B', 'Sub C'])
    await request.post(`/api/clients/${client.id}/subclients`, { data: { name: sub } });
  await openScopes(page, client.id, name);
  await expect(preview(page).getByText(/^Universo não definido: salve/)).toBeVisible();

  // Universo do cliente: BU 1 + BU 2 (modo simples), rascunho primeiro, depois salvo
  await expect(page.getByTestId('connection-mode')).toHaveText('Conexão do cliente');
  await check(page, 'Business Units', 'Alfa BU 1');
  await check(page, 'Business Units', 'Alfa BU 2');
  await page.getByRole('button', { name: 'Pré-visualizar rascunho' }).click();
  await expect(page.getByTestId('validation-ok')).toBeVisible();
  await expect(preview(page).getByText('com rascunho não salvo')).toBeVisible();
  await expect(page.getByTestId('universe-included')).toHaveText('60');
  await expect(page.getByTestId('universe-excluded')).toHaveText('60');
  await saveVersion(page, 1);
  await expect(page.getByTestId('preview-complete')).toBeVisible();
  await expect(page.getByTestId('unclassified-count')).toHaveText('60');
  await expect(preview(page).getByText('não validado')).toBeVisible(); // subclientes ainda sem escopo

  // Sub A: Team 01; Sub B: BU 2
  await owner(page, 'Sub A').click();
  await expect(page.getByTestId('connection-mode')).toHaveText('Mesma conexão do cliente');
  await check(page, 'Teams', 'Alfa Team 01');
  await saveVersion(page, 1);
  await owner(page, 'Sub B').click();
  await check(page, 'Business Units', 'Alfa BU 2');
  await saveVersion(page, 1);

  // Sub C: modo avançado — (BU 1 E NÃO tag web) OU criticidade VERY_HIGH
  await owner(page, 'Sub C').click();
  await page.getByLabel('Avançado').check();
  const root = page.getByTestId('node-root');
  await root.getByRole('button', { name: '+ Grupo' }).click();
  const sub = page.getByTestId('node-root-0');
  await sub.getByLabel('Operador do grupo').selectOption('and');
  await sub.getByRole('button', { name: '+ Condição' }).click();
  await sub.getByRole('button', { name: '+ Condição' }).click();
  const bu = page.getByTestId('node-root-0-0');
  await bu.getByLabel('Campo').selectOption('business_unit.id');
  await bu.getByLabel('Comparação').selectOption('eq');
  await bu.getByLabel('Valor').selectOption({ label: 'Alfa BU 1' });
  const tag = page.getByTestId('node-root-0-1');
  await tag.getByLabel('NÃO').check();
  await tag.getByLabel('Campo').selectOption('tag');
  await tag.getByLabel('Comparação').selectOption('in');
  await tag.getByLabel('Valores').fill('web');
  await root.getByLabel('Operador do grupo').first().selectOption('or');
  await root.getByRole('button', { name: '+ Condição' }).last().click();
  const crit = page.getByTestId('node-root-1');
  await crit.getByLabel('Campo').selectOption('business_criticality');
  await crit.getByLabel('Comparação').selectOption('in');
  await crit.getByLabel('Valores').selectOption(['VERY_HIGH']);
  await expect(page.getByLabel('Simples')).toBeDisabled(); // regra não representável no modo simples
  await page.getByRole('button', { name: 'Validar regra' }).click();
  await expect(page.getByTestId('validation-ok')).toContainText('Regra válida');
  await saveVersion(page, 1);

  const subs = preview(page).getByRole('table', { name: 'Subclientes' });
  await expect(subs.getByRole('row', { name: /Sub A/ })).toContainText('17');
  await expect(subs.getByRole('row', { name: /Sub B/ })).toContainText('30');
  await expect(subs.getByRole('row', { name: /Sub C/ })).toContainText('12');
  await expect(page.getByTestId('unclassified-count')).toHaveText('13');
  await expect(page.getByTestId('overlap-count')).toHaveText('9');
  await expect(preview(page).getByText('não validado')).toHaveCount(0);
  await page.screenshot({ path: 'test-results/evidence/f03-escopos-aplicacoes.png', fullPage: true });

  // Regra inválida: erro com caminho, botão salvar desabilitado
  await root.getByRole('button', { name: '+ Condição' }).last().click();
  const bad = page.getByTestId('node-root-2');
  await bad.getByLabel('Campo').selectOption('name');
  await bad.getByLabel('Comparação').selectOption('eq');
  await page.getByRole('button', { name: 'Validar regra' }).click();
  await expect(page.getByTestId('validation-errors')).toContainText('rule.args[2].value');
  await expect(page.getByRole('button', { name: 'Salvar nova versão' })).toBeDisabled();

  // Versionamento: Sub B v2 (BU 3) e restauração da v1 como v3 (v1 preservada)
  await owner(page, 'Sub B').click();
  await page.getByRole('group', { name: 'Business Units' }).getByLabel('Alfa BU 2', { exact: true }).uncheck();
  await check(page, 'Business Units', 'Alfa BU 3');
  await saveVersion(page, 2);
  await expect(subs.getByRole('row', { name: /Sub B/ })).toContainText('Avaliado');
  const history = page.getByRole('table', { name: 'Histórico de versões' });
  await expect(history.getByRole('row', { name: /v1/ })).toContainText('Substituída (preservada)');
  await history.getByRole('row', { name: /v1/ }).getByRole('button', { name: 'Restaurar como nova versão' }).click();
  await expect(page.getByTestId('scope-status')).toHaveText('Versão 3 · Ativo');
  await expect(page.getByRole('group', { name: 'Business Units' }).getByLabel('Alfa BU 2', { exact: true })).toBeChecked();
  await expect(history.getByRole('row')).toHaveCount(4);
});

test('usuários: filtros independentes, únicos por Team e inativos fora da contagem', async ({ page, request }) => {
  const name = `Usuários E2E ${run}`;
  const { client } = await createClient(request, name);
  await request.post(`/api/clients/${client.id}/subclients`, { data: { name: 'Sub Usuários' } });
  await openScopes(page, client.id, name);
  await page.getByRole('tab', { name: 'Usuários' }).click();
  await page.getByLabel('Todos os usuários da conexão').check();
  await expect(page.getByLabel('Usuários inativos')).toHaveValue('exclude');
  await saveVersion(page, 1);
  await expect(page.getByTestId('universe-included')).toHaveText('41');
  await expect(page.getByTestId('universe-inactive')).toHaveText('4');
  await expect(page.getByTestId('unique-users-total')).toHaveText('41');
  await expect(page.getByTestId('reconciliation')).toContainText('partial');

  await owner(page, 'Sub Usuários').click();
  await expect(page.getByText('Teams de usuários não selecionam aplicações')).toBeVisible();
  await check(page, 'Teams', 'Alfa Team 01');
  await saveVersion(page, 1);
  await expect(preview(page).getByRole('table', { name: 'Subclientes' }).getByRole('row', { name: /Sub Usuários/ })).toContainText('5');

  // O escopo de usuários não criou escopo de aplicações
  await page.getByRole('tab', { name: 'Aplicações' }).click();
  await expect(owner(page, 'Sub Usuários')).toContainText('Não definido');
  await page.screenshot({ path: 'test-results/evidence/f03-escopos-usuarios.png', fullPage: true });
});

test('outro tenant exige confirmação; erro da descoberta é exibido sem dados falsos', async ({ page, request }) => {
  const name = `Tenants E2E ${run}`;
  const { client } = await createClient(request, name);
  const denied = await (
    await request.post('/api/connections', { data: { name: `Negada escopos ${run}`, region: 'commercial', credential_ref: 'env:AFRIKA_E2E_DENIED' } })
  ).json();
  await request.post(`/api/clients/${client.id}/subclients`, { data: { name: 'Sub Outro Tenant', connection_id: denied.id } });
  await openScopes(page, client.id, name);
  await owner(page, 'Sub Outro Tenant').click();
  await expect(page.getByTestId('connection-mode')).toHaveText('Conexão própria (outro tenant)');
  await page.getByLabel('Todo o universo do cliente principal').check();
  await expect(page.getByRole('button', { name: 'Salvar nova versão' })).toBeDisabled();
  await page.getByLabel(/Confirmo a abrangência/).check();
  await saveVersion(page, 1);

  // Tenant sem permissão na Identity API: aba Usuários mostra erro (sem contagens inventadas)
  const deniedClient = await createClient(request, `Negado E2E ${run}`, 'env:AFRIKA_E2E_DENIED');
  await openScopes(page, deniedClient.client.id, `Negado E2E ${run}`);
  await page.getByRole('tab', { name: 'Usuários' }).click();
  await expect(page.getByText(/Descoberta indisponível/)).toBeVisible();
  await page.getByLabel('Todos os usuários da conexão').check();
  await saveVersion(page, 1);
  await expect(preview(page).getByText(/Pré-visualização indisponível/)).toBeVisible();
  await expect(page.getByTestId('universe-included')).toHaveCount(0);
});
