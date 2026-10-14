import { expect, test } from '@playwright/test';

// Regressão F00: a demo sintética continua navegável, agora vinda do banco via seed EXPLÍCITO
// (`python -m app.cli seed-demo`, executado pelo webServer do E2E). Nenhuma chamada externa.
test('F00: abre, lista clientes sintéticos e mostra detalhes com/sem subclientes', async ({ page }) => {
  const external: string[] = [];
  page.on('request', (req) => {
    const host = new URL(req.url()).hostname;
    if (!['127.0.0.1', 'localhost'].includes(host)) external.push(req.url());
  });

  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1, name: 'Central de relatórios AppSec' })).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);

  const table = page.getByRole('table', { name: 'Lista de clientes' });
  const semSub = table.getByRole('row', { name: /Cliente Demonstração/ });
  const comSub = table.getByRole('row', { name: /Cliente com BUs \(Sintético\)/ });
  await expect(semSub).toContainText('Sem subclientes');
  await expect(comSub).toContainText('2');
  await expect(comSub).toContainText('Consolidado + individual');

  await comSub.getByRole('link').click();
  await expect(page.getByRole('heading', { level: 2 })).toHaveText('Cliente com BUs (Sintético)');
  const subs = page.getByRole('table', { name: 'Lista de subclientes' });
  await expect(subs.getByRole('row')).toHaveCount(3); // cabeçalho + TI + Marketing
  await expect(page.getByTestId('subclient-TI')).toContainText('Herdada do cliente');
  await expect(page.getByTestId('subclient-Marketing')).toContainText('Conexão sintética (demo)');
  await page.screenshot({ path: 'test-results/evidence/f01-demo-cliente-com-subclientes.png', fullPage: true });

  await page.getByRole('link', { name: '← Clientes' }).click();
  await table.getByRole('row', { name: /Cliente Demonstração/ }).getByRole('link').click();
  await expect(page.getByRole('heading', { level: 2 })).toHaveText('Cliente Demonstração');
  await expect(page.getByText('Cliente sem subclientes.')).toBeVisible();
  await page.screenshot({ path: 'test-results/evidence/f01-demo-cliente-sem-subclientes.png', fullPage: true });

  expect(external, 'requisições externas inesperadas').toEqual([]);
});
