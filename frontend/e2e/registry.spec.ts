import { Page, expect, test } from '@playwright/test';

// F01: fluxo funcional de cadastro pela interface, contra a API real (banco E2E descartável).
// Somente dados sintéticos. Nenhuma chamada Veracode.
const run = Date.now().toString(36);
const n = (label: string) => `${label} ${run}`;

async function createConnection(page: Page, name: string, ref: string) {
  await page.goto('/#/connections');
  await page.getByRole('button', { name: 'Nova conexão' }).click();
  const form = page.getByRole('form', { name: 'Nova conexão' });
  await form.getByLabel('Nome *').fill(name);
  await form.getByLabel('Referência da credencial *').fill(ref);
  await form.getByRole('button', { name: 'Cadastrar conexão' }).click();
  await expect(page.getByRole('table', { name: 'Lista de conexões' }).getByRole('row', { name: new RegExp(name) }))
    .toBeVisible();
}

test.beforeEach(({ page }) => {
  page.on('request', (req) => {
    const host = new URL(req.url()).hostname;
    expect(['127.0.0.1', 'localhost'], `requisição externa: ${req.url()}`).toContain(host);
  });
});

test('conexões: validação da referência, cadastro, edição e bloqueio de exclusão em uso', async ({ page }) => {
  await page.goto('/#/connections');
  await page.getByRole('button', { name: 'Nova conexão' }).click();
  const form = page.getByRole('form', { name: 'Nova conexão' });
  await expect(form.getByText('Nunca cole API ID ou API Key aqui')).toBeVisible();
  await form.getByLabel('Nome *').fill(n('Conexão inválida'));
  await form.getByLabel('Referência da credencial *').fill('a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4');
  await form.getByRole('button', { name: 'Cadastrar conexão' }).click();
  await expect(form.getByText('Use env:NOME_DA_VARIAVEL')).toBeVisible();
  await expect(form.getByLabel('Referência da credencial *')).toHaveAttribute('aria-invalid', 'true');
  // Validação do servidor (formato válido no cliente, mas parece chave hexadecimal) => erro do campo.
  await form.getByLabel('Referência da credencial *').fill('env:ABCDEF0123456789ABCDEF0123456789');
  await form.getByRole('button', { name: 'Cadastrar conexão' }).click();
  await expect(form.getByText(/parece conter um segredo/)).toBeVisible();
  await form.getByRole('button', { name: 'Cancelar' }).click();

  const name = n('Conexão editável');
  await createConnection(page, name, 'env:AFRIKA_E2E_EDIT');
  const row = page.getByRole('row', { name: new RegExp(name) });
  await row.getByRole('button', { name: 'Editar' }).click();
  const edit = page.getByRole('form', { name: 'Editar conexão' });
  await edit.getByLabel('Região').selectOption('european');
  await edit.getByRole('button', { name: 'Salvar conexão' }).click();
  await expect(row).toContainText('European (EU)');

  // Conexão da demo está em uso => exclusão desabilitada.
  const demo = page.getByRole('row', { name: /Conexão sintética \(demo\)/ });
  await expect(demo.getByRole('button', { name: 'Excluir' })).toBeDisabled();

  page.once('dialog', (d) => d.accept());
  await row.getByRole('button', { name: 'Excluir' }).click();
  await expect(row).toHaveCount(0);
});

test('clientes e subclientes: CRUD, modo de relatório, herança/sobrescrita, ativação e exclusão', async ({ page }) => {
  const connClient = n('Conn cliente');
  const connSub = n('Conn BU');
  await createConnection(page, connClient, 'env:AFRIKA_E2E_CLIENT');
  await createConnection(page, connSub, 'env:AFRIKA_E2E_BU');

  // --- cadastro com validação
  await page.goto('/');
  await page.getByRole('button', { name: 'Novo cliente' }).click();
  let form = page.getByRole('form', { name: 'Novo cliente' });
  await form.getByRole('button', { name: 'Cadastrar cliente' }).click();
  await expect(form.getByText('Informe o nome.')).toBeVisible();
  await expect(form.getByLabel('Nome *')).toHaveAttribute('aria-invalid', 'true');

  const clientName = n('Cliente E2E');
  await form.getByLabel('Nome *').fill(clientName);
  await form.getByLabel('Consolidado + individual').check();
  await form.getByLabel('Conexão Veracode').selectOption({ label: connClient });
  await form.getByRole('button', { name: 'Cadastrar cliente' }).click();

  await expect(page.getByRole('heading', { level: 2 })).toHaveText(clientName);
  await expect(page.getByTestId('client-report-mode')).toHaveText('Consolidado + individual');
  await expect(page.getByTestId('client-connection')).toContainText(connClient);
  await expect(page.getByText('Cliente sem subclientes.')).toBeVisible();
  await expect(page.getByText(/ainda não possui subclientes/)).toBeVisible();

  // --- edição
  await page.getByRole('button', { name: 'Editar' }).first().click();
  form = page.getByRole('form', { name: 'Editar cliente' });
  await form.getByLabel('Nome de exibição').fill(`${clientName} S.A.`);
  await form.getByLabel('Individual por subcliente').check();
  await form.getByRole('button', { name: 'Salvar alterações' }).click();
  await expect(page.getByTestId('client-report-mode')).toHaveText('Individual por subcliente');
  await expect(page.getByText(`${clientName} S.A.`)).toBeVisible();

  // --- subcliente herdando conexão
  await page.getByRole('button', { name: 'Novo subcliente' }).click();
  let subForm = page.getByRole('form', { name: 'Novo subcliente' });
  await expect(subForm.getByLabel('Conexão Veracode')).toContainText(`Herdar do cliente (${connClient})`);
  await subForm.getByLabel('Nome *').fill('Financeiro');
  await subForm.getByRole('button', { name: 'Cadastrar subcliente' }).click();
  await expect(page.getByTestId('subclient-Financeiro')).toContainText('Herdada do cliente');
  await expect(page.getByTestId('subclient-Financeiro')).toContainText(connClient);

  // --- subcliente com sobrescrita
  await page.getByRole('button', { name: 'Novo subcliente' }).click();
  subForm = page.getByRole('form', { name: 'Novo subcliente' });
  await subForm.getByLabel('Nome *').fill('Varejo');
  await subForm.getByLabel('Conexão Veracode').selectOption({ label: connSub });
  await subForm.getByRole('button', { name: 'Cadastrar subcliente' }).click();
  await expect(page.getByTestId('subclient-Varejo')).toContainText('Sobrescrita');
  await expect(page.getByTestId('subclient-Varejo')).toContainText(connSub);

  // --- nome duplicado no mesmo cliente => erro 409 no campo
  await page.getByRole('button', { name: 'Novo subcliente' }).click();
  subForm = page.getByRole('form', { name: 'Novo subcliente' });
  await subForm.getByLabel('Nome *').fill('FINANCEIRO');
  await subForm.getByRole('button', { name: 'Cadastrar subcliente' }).click();
  await expect(subForm.getByText('Já existe um subcliente com este nome neste cliente')).toBeVisible();
  await subForm.getByRole('button', { name: 'Cancelar' }).click();

  // --- edição de subcliente: remover sobrescrita volta a herdar
  await page.getByTestId('subclient-Varejo').getByRole('button', { name: 'Editar' }).click();
  subForm = page.getByRole('form', { name: 'Editar subcliente' });
  await subForm.getByLabel('Conexão Veracode').selectOption({ index: 0 });
  await subForm.getByRole('button', { name: 'Salvar subcliente' }).click();
  await expect(page.getByTestId('subclient-Varejo')).toContainText('Herdada do cliente');
  await page.screenshot({ path: 'test-results/evidence/f01-detalhe-cliente.png', fullPage: true });

  // --- desativar cliente: subclientes ficam efetivamente inativos, status próprio preservado
  const remove = page.getByRole('button', { name: 'Excluir', exact: true }).first();
  await expect(remove).toBeDisabled();
  await page.getByRole('button', { name: 'Desativar' }).first().click();
  await expect(page.getByTestId('subclient-Financeiro')).toContainText('Inativo (cliente inativo)');
  await expect(page.getByText(/Cliente possui subclientes/)).toBeVisible();
  await page.getByRole('button', { name: 'Ativar' }).first().click();
  await expect(page.getByTestId('subclient-Financeiro')).toContainText('Ativo');

  // --- exclusão segura: subclientes desativados e excluídos, depois o cliente
  for (const sub of ['Financeiro', 'Varejo']) {
    const row = page.getByTestId(`subclient-${sub}`);
    await expect(row.getByRole('button', { name: 'Excluir' })).toBeDisabled();
    await row.getByRole('button', { name: 'Desativar' }).click();
    page.once('dialog', (d) => d.accept());
    await row.getByRole('button', { name: 'Excluir' }).click();
    await expect(row).toHaveCount(0);
  }
  await page.getByRole('button', { name: 'Desativar' }).first().click();
  page.once('dialog', (d) => d.accept());
  await page.getByRole('button', { name: 'Excluir', exact: true }).first().click();
  await expect(page.getByRole('heading', { level: 2, name: 'Clientes' })).toBeVisible();
  await expect(page.getByRole('link', { name: clientName })).toHaveCount(0);
});

test('lista: nome duplicado, filtros e paginação', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Novo cliente' }).click();
  const form = page.getByRole('form', { name: 'Novo cliente' });
  await form.getByLabel('Nome *').fill('cliente demonstração'); // já existe (seed), caixa diferente
  await form.getByRole('button', { name: 'Cadastrar cliente' }).click();
  await expect(form.getByText('Já existe um cliente com este nome')).toBeVisible();
  await form.getByRole('button', { name: 'Cancelar' }).click();

  await page.getByLabel('Buscar').fill(`inexistente-${run}`);
  await expect(page.getByText('Nenhum cliente encontrado para os filtros aplicados.')).toBeVisible();
  await page.getByLabel('Buscar').fill('');
  await page.getByLabel('Status').selectOption('inactive');
  await expect(page.getByRole('link', { name: 'Cliente Demonstração' })).toHaveCount(0);
  await page.getByLabel('Status').selectOption('all');
  await expect(page.getByRole('link', { name: 'Cliente Demonstração' })).toBeVisible();
  await expect(page.getByText(/^1–\d+ de \d+$/)).toBeVisible();
});

test('estados de carregamento, vazio e erro', async ({ page }) => {
  // vazio
  await page.route('**/api/clients?*', (route) =>
    route.fulfill({ json: { items: [], total: 0, limit: 20, offset: 0 } }),
  );
  await page.goto('/');
  await expect(page.getByText('Nenhum cliente cadastrado.')).toBeVisible();
  await page.unroute('**/api/clients?*');

  // carregamento + erro (API indisponível) + recuperação
  let fail = true;
  await page.route('**/api/clients?*', async (route) => {
    await new Promise((r) => setTimeout(r, 400));
    if (fail) await route.fulfill({ status: 503, json: { error: { code: 'x', message: 'Serviço indisponível' } } });
    else await route.continue();
  });
  await page.reload();
  await expect(page.getByRole('status')).toHaveText('Carregando clientes…');
  await expect(page.getByRole('alert')).toContainText('Falha ao carregar clientes: Serviço indisponível');
  fail = false;
  await page.getByRole('button', { name: 'Tentar novamente' }).click();
  await expect(page.getByRole('link', { name: 'Cliente Demonstração' })).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);

  // cliente inexistente
  await page.goto('/#/clients/00000000-0000-4000-8000-000000000000');
  await expect(page.getByRole('alert')).toContainText('Cliente não encontrado');
});
