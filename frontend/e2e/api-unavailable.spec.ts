import { Page, expect, test } from '@playwright/test';

// F01.1: interface com a API indisponível. Os dois modos reproduzem falhas reais observadas:
// - proxy: o Vite responde 500 com corpo vazio (text/plain) quando o backend está parado;
// - rede: a requisição nem chega (conexão recusada).
const proxyDown = (page: Page, pattern = '**/api/**') =>
  page.route(pattern, (route) => route.fulfill({ status: 500, contentType: 'text/plain', body: '' }));
const networkDown = (page: Page, pattern = '**/api/**') =>
  page.route(pattern, (route) => route.abort('connectionrefused'));

test('lista: backend parado (proxy 500 vazio) => alerta claro e recuperação por "Tentar novamente"', async ({ page }) => {
  await proxyDown(page);
  await page.goto('/');
  const alert = page.getByRole('alert');
  await expect(alert).toContainText('API indisponível (HTTP 500). Verifique se o backend está em execução.');
  await expect(page.getByRole('table')).toHaveCount(0);

  await page.unroute('**/api/**');
  await alert.getByRole('button', { name: 'Tentar novamente' }).click();
  await expect(page.getByRole('link', { name: 'Cliente Demonstração' })).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
});

test('falha de rede (conexão recusada) em lista, detalhe e conexões', async ({ page }) => {
  await page.goto('/');
  const href = await page.getByRole('link', { name: 'Cliente Demonstração' }).getAttribute('href');

  await networkDown(page);
  await page.reload();
  await expect(page.getByRole('alert')).toContainText('Não foi possível contatar a API');

  await page.goto(`/${href}`);
  await expect(page.getByRole('alert')).toContainText('Falha ao carregar cliente: Não foi possível contatar a API');

  await page.goto('/#/connections');
  await expect(page.getByRole('alert')).toContainText('Falha ao carregar conexões: Não foi possível contatar a API');
});

test('formulário: API cai durante o envio => erro no formulário, dados preservados, reenvio funciona', async ({
  page,
}) => {
  const name = `Cliente queda ${Date.now().toString(36)}`;
  await page.goto('/');
  await page.getByRole('button', { name: 'Novo cliente' }).click();
  const form = page.getByRole('form', { name: 'Novo cliente' });
  await form.getByLabel('Nome *').fill(name);

  await proxyDown(page, '**/api/clients');
  await form.getByRole('button', { name: 'Cadastrar cliente' }).click();
  await expect(form.getByRole('alert')).toContainText('API indisponível');
  await expect(form.getByLabel('Nome *')).toHaveValue(name);
  await expect(form.getByRole('button', { name: 'Cadastrar cliente' })).toBeEnabled();
  await page.screenshot({ path: 'test-results/evidence/f01-1-api-indisponivel-formulario.png', fullPage: true });

  await page.unroute('**/api/clients');
  await form.getByRole('button', { name: 'Cadastrar cliente' }).click();
  await expect(page.getByRole('heading', { level: 2 })).toHaveText(name);
});

test('ação na tela de detalhe com API fora => mensagem e estado inalterado', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('link', { name: 'Cliente Demonstração' }).click();
  await expect(page.getByRole('heading', { level: 2 })).toHaveText('Cliente Demonstração');

  await networkDown(page, '**/api/clients/*');
  await page.getByRole('button', { name: 'Desativar' }).click();
  await expect(page.getByRole('alert')).toContainText('Não foi possível contatar a API');
  await page.unroute('**/api/clients/*');
  await page.reload();
  await expect(page.locator('.toolbar .badge')).toHaveText('Ativo'); // nada foi alterado
});
