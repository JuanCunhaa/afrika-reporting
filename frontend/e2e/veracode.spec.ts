import { APIRequestContext, Page, expect, test } from '@playwright/test';
import { SYNTHETIC_SECRET_NAMES, SYNTHETIC_SECRET_VALUES } from './fixture-creds';

// F02: área Veracode por cliente/subcliente contra o backend em modo FIXTURE (tenant sintético em processo).
// Nenhuma chamada à Veracode real; o navegador só fala com 127.0.0.1.
const run = Date.now().toString(36);
const SEED_CLIENT = 'Cliente com BUs (Sintético)';

const veracodeBodies: string[] = [];

test.beforeEach(({ page }) => {
  page.on('request', (req) => {
    const host = new URL(req.url()).hostname;
    expect(['127.0.0.1', 'localhost'], `requisição externa: ${req.url()}`).toContain(host);
  });
  page.on('response', async (res) => {
    if (res.url().includes('/api/veracode/')) veracodeBodies.push(await res.text().catch(() => ''));
  });
});

test.afterEach(() => {
  // Nenhuma resposta da API Veracode local expõe credenciais ou os nomes das variáveis derivadas.
  const all = veracodeBodies.join('\n');
  for (const secret of [...SYNTHETIC_SECRET_VALUES, ...SYNTHETIC_SECRET_NAMES]) expect(all).not.toContain(secret);
  veracodeBodies.length = 0;
});

async function seedClientId(request: APIRequestContext): Promise<string> {
  const r = await request.get(`/api/clients?q=${encodeURIComponent('Cliente com BUs')}`);
  return (await r.json()).items[0].id;
}

async function openClientVeracode(page: Page) {
  await page.goto('/');
  await page.getByRole('link', { name: SEED_CLIENT }).click();
  await page.getByRole('link', { name: 'Veracode', exact: true }).click();
  await expect(page.getByRole('heading', { level: 2 })).toHaveText(`Veracode — ${SEED_CLIENT}`);
}

test('cliente: conexão sem segredos, teste OK, aplicações paginadas, busca e sandboxes', async ({ page }) => {
  await openClientVeracode(page);
  await expect(page.getByTestId('fixture-mode')).toBeVisible();
  await expect(page.getByTestId('vc-connection')).toHaveText('Conexão sintética (demo)');
  await expect(page.getByTestId('vc-source')).toHaveText('Herdada do cliente');
  await expect(page.getByTestId('vc-credential')).toHaveText('Configurada no backend');
  await expect(page.getByText('env:AFRIKA_DEMO_VERACODE', { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Testar conexão' }).click();
  const result = page.getByTestId('vc-test-result');
  await expect(result).toContainText('Conexão OK');
  await expect(result.getByRole('row')).toHaveCount(6); // cabeçalho + 5 verificações

  const apps = page.getByRole('table', { name: 'Aplicações' });
  await expect(page.getByTestId('collection-complete')).toBeVisible();
  await expect(apps.getByRole('row')).toHaveCount(26); // cabeçalho + 25 por página
  await expect(page.getByText('1–25 de 120')).toBeVisible();
  await page.getByRole('button', { name: 'Próxima' }).click();
  await expect(page.getByText('26–50 de 120')).toBeVisible();
  await expect(page.getByTestId('collection-complete')).toContainText('do cache');

  await page.getByRole('searchbox').fill('App 001');
  await expect(apps.getByRole('row')).toHaveCount(2);
  const row = apps.getByRole('row', { name: /Alfa App 001/ });
  await expect(row).toContainText('Alfa Team 01, Alfa Team 04');
  await row.getByRole('button', { name: 'Sandboxes' }).click();
  const sandboxes = page.getByRole('group', { name: 'Sandboxes de Alfa App 001' });
  await expect(sandboxes.getByRole('listitem')).toHaveCount(3);
  await page.screenshot({ path: 'test-results/evidence/f02-veracode-aplicacoes.png', fullPage: true });
  expect(veracodeBodies.length).toBeGreaterThan(5); // verificação de segredos (afterEach) cobriu respostas reais

  await page.getByRole('searchbox').fill('inexistente-xyz');
  await expect(page.getByText('Nenhum resultado para a busca.')).toBeVisible();
});

test('BUs, Teams, usuários e relacionamentos (usuário em vários Teams, aplicação em vários Teams)', async ({ page }) => {
  await openClientVeracode(page);
  await page.getByRole('tab', { name: 'Business Units', exact: true }).click();
  await expect(page.getByRole('table', { name: 'Business Units' }).getByRole('row')).toHaveCount(5);
  await page.getByRole('tab', { name: 'Teams', exact: true }).click();
  await expect(page.getByRole('table', { name: 'Teams' }).getByRole('row')).toHaveCount(9);
  // F03: campo ausente na API real (user_count) aparece como "Indisponível", nunca "?"
  await expect(page.getByRole('table', { name: 'Teams' }).getByRole('cell', { name: 'Indisponível' })).toHaveCount(8);
  await expect(page.getByRole('table', { name: 'Teams' }).getByRole('cell', { name: '?', exact: true })).toHaveCount(0);
  await page.getByRole('tab', { name: 'Usuários', exact: true }).click();
  await expect(page.getByText('1–25 de 45')).toBeVisible();
  await expect(page.getByRole('tabpanel')).not.toContainText('example.invalid'); // e-mail nunca chega à UI

  await page.getByRole('tab', { name: 'Usuário ↔ Teams' }).click();
  const summary = page.locator('.summary');
  await expect(summary).toContainText('Em 2+ Teams11');
  await expect(summary).toContainText('Sem Team3');
  await page.getByRole('searchbox').fill('alfa.usuario01');
  const rel = page.getByRole('table', { name: 'Relação usuário ↔ Teams' });
  await expect(rel.getByRole('row')).toHaveCount(2);
  await expect(rel.getByRole('row', { name: /alfa\.usuario01/ })).toContainText('Alfa Team 01');
  await expect(rel.getByRole('row', { name: /alfa\.usuario01/ })).toContainText('Alfa Team 02');

  await page.getByRole('tab', { name: 'Aplicação ↔ BU/Teams' }).click();
  await expect(page.locator('.summary')).toContainText('Com 2+ Teams23');
  await page.getByRole('searchbox').fill('Alfa App 017');
  const relApps = page.getByRole('table', { name: 'Relação aplicação ↔ BU/Teams' });
  await expect(relApps.getByRole('row')).toHaveCount(2); // busca aplicada (debounce) antes de verificar
  await expect(relApps.getByRole('row', { name: /Alfa App 017/ })).toContainText('Nenhum');
  await page.screenshot({ path: 'test-results/evidence/f02-veracode-relacionamentos.png', fullPage: true });

  await page.getByRole('tab', { name: 'Metadados', exact: true }).click();
  await expect(page.getByText('Campo: Centro de custo')).toBeVisible();
  await expect(page.getByRole('table', { name: 'Filtros por domínio' })).toContainText('nenhum nesta fase');

  await page.getByRole('button', { name: 'Invalidar cache' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Cache invalidado' })).toBeVisible();
});

test('subclientes: herança, sobrescrita sem permissão (403) e credencial ausente', async ({ page, request }) => {
  const clientId = await seedClientId(request);
  const subs = (await (await request.get(`/api/clients/${clientId}/subclients`)).json()).items as { id: string; name: string }[];
  const ti = subs.find((s) => s.name === 'TI')!;

  // Herança: subcliente TI usa a conexão do cliente.
  await page.goto(`/#/clients/${clientId}`);
  await page.getByRole('link', { name: 'Veracode do subcliente TI' }).click();
  await expect(page.getByTestId('vc-source')).toHaveText('Herdada do cliente');
  await page.getByRole('tab', { name: 'Teams', exact: true }).click();
  await expect(page.getByRole('table', { name: 'Teams' }).getByRole('row')).toHaveCount(9);
  // F03: campo ausente na API real (user_count) aparece como "Indisponível", nunca "?"
  await expect(page.getByRole('table', { name: 'Teams' }).getByRole('cell', { name: 'Indisponível' })).toHaveCount(8);
  await expect(page.getByRole('table', { name: 'Teams' }).getByRole('cell', { name: '?', exact: true })).toHaveCount(0);

  // Sobrescrita: conexão própria cuja credencial não tem permissão na Identity API.
  const denied = await request.post('/api/connections', {
    data: { name: `Sem permissão ${run}`, region: 'commercial', credential_ref: 'env:AFRIKA_E2E_DENIED' },
  });
  const sub = await request.post(`/api/clients/${clientId}/subclients`, {
    data: { name: `Sub restrito ${run}`, connection_id: (await denied.json()).id },
  });
  const subId = (await sub.json()).id;
  await page.goto(`/#/veracode/subclients/${subId}`);
  await expect(page.getByTestId('vc-source')).toHaveText('Sobrescrita no subcliente');
  await page.getByRole('button', { name: 'Testar conexão' }).click();
  await expect(page.getByTestId('vc-test-result')).toContainText('Conexão parcial: permissões ausentes');
  await expect(page.getByTestId('vc-test-result')).toContainText('Permissão insuficiente na Veracode');
  await expect(page.getByRole('table', { name: 'Aplicações' }).getByRole('row')).toHaveCount(4); // apps OK
  await page.getByRole('tab', { name: 'Usuários', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Permissão insuficiente na Veracode para este recurso (HTTP 403)');
  await page.screenshot({ path: 'test-results/evidence/f02-veracode-sem-permissao.png', fullPage: true });

  // Credencial ausente no ambiente do backend.
  const missing = await request.post('/api/connections', {
    data: { name: `Ausente ${run}`, region: 'european', credential_ref: 'env:AFRIKA_E2E_AUSENTE' },
  });
  await request.patch(`/api/subclients/${ti.id}`, { data: { connection_id: (await missing.json()).id } });
  await page.goto(`/#/veracode/subclients/${ti.id}`);
  await expect(page.getByTestId('vc-credential')).toHaveText('Ausente no ambiente do backend');
  await expect(page.getByRole('alert')).toContainText('não estão configuradas no ambiente do backend');
  await page.getByRole('button', { name: 'Testar conexão' }).click();
  await expect(page.getByTestId('vc-test-result')).toContainText('Falha na conexão');
  await request.patch(`/api/subclients/${ti.id}`, { data: { connection_id: null } }); // restaura herança
});

test('cliente sem conexão: estado vazio sem abas e sem chamadas Veracode', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('link', { name: 'Cliente Demonstração' }).click();
  await page.getByRole('link', { name: 'Veracode', exact: true }).click();
  await expect(page.getByText('Escopo sem conexão Veracode.')).toBeVisible();
  await expect(page.getByRole('tablist')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Testar conexão' })).toBeDisabled();
});

test('erro de conectividade da API local na área Veracode e recuperação', async ({ page }) => {
  await openClientVeracode(page);
  await page.route('**/api/veracode/**/teams**', (route) => route.abort('connectionrefused'));
  await page.getByRole('tab', { name: 'Teams', exact: true }).click();
  const alert = page.getByRole('alert');
  await expect(alert).toContainText('Não foi possível contatar a API');
  await page.unroute('**/api/veracode/**/teams**');
  await alert.getByRole('button', { name: 'Tentar novamente' }).click();
  await expect(page.getByRole('table', { name: 'Teams' }).getByRole('row')).toHaveCount(9);
  // F03: campo ausente na API real (user_count) aparece como "Indisponível", nunca "?"
  await expect(page.getByRole('table', { name: 'Teams' }).getByRole('cell', { name: 'Indisponível' })).toHaveCount(8);
  await expect(page.getByRole('table', { name: 'Teams' }).getByRole('cell', { name: '?', exact: true })).toHaveCount(0);
});
