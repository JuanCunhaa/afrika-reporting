import { APIRequestContext, expect } from '@playwright/test';

// F06B.1 — fixture SINTÉTICA e DETERMINÍSTICA da regressão visual: cliente de nome fixo, 12 competências (duas
// lacunas: 2026-04 e 2026-07) com valores manuais justificados, template cobrindo os 11 tipos de slide × layouts.
// Idempotente (reaproveita cliente/competências/template num mesmo banco, ex.: --repeat-each). Sem Veracode.
const OP = 'Operadora Visual Sintética';
export const VISUAL_CLIENT = 'Cliente Visual Sintético';
const MONTHS = ['2025-10', '2025-11', '2025-12', '2026-01', '2026-02', '2026-03', '2026-05', '2026-06', '2026-08', '2026-09'];
export const PRIMARY = '2026-09';

const sev = (...n: number[]) => {
  const keys = ['VERY_HIGH', 'HIGH', 'MEDIUM', 'LOW', 'VERY_LOW', 'INFORMATIONAL', 'UNKNOWN'];
  return { ...Object.fromEntries(keys.map((k, i) => [k, n[i]])), total: n.reduce((a, b) => a + b, 0) };
};

function valuesFor(i: number, label: string): Record<string, unknown> {
  const v: Record<string, unknown> = {
    'apps.total': 40 + i * 2,
    'sast.policy.open.by_severity': sev(1, 2 + (i % 3), 3 + i, 4, 1, 0, i % 2),
    'sca.policy.open.by_severity': sev(0, 1, 1 + (i % 2), 2, 0, 1, 0),
    'licenses.usage': 30 + i,
  };
  if (label === PRIMARY) {
    v['apps.by_business_unit'] = {
      items: [
        { business_unit_id: 'b1', name: 'BU Sintética Norte', applications: 21 },
        { business_unit_id: 'b2', name: 'BU Sintética Sul', applications: 13 },
        { business_unit_id: 'b3', name: 'BU Sintética Leste', applications: 8 },
        { business_unit_id: 'b4', name: 'BU Sintética Oeste', applications: 4 },
      ],
      unknown: 0,
      distinct_applications: 46,
    };
    v['sast.policy.open.top_applications'] = {
      top: Array.from({ length: 12 }, (_, k) => ({ application_guid: `vg${k}`, name: `App Visual ${String(k + 1).padStart(2, '0')}`, findings: 48 - k * 3 })),
      total: 378,
    };
    v['sca.policy.open.top_components'] = {
      top: Array.from({ length: 6 }, (_, k) => ({ component_id: `c${k + 1}`, filename: `componente-sintetico-${k + 1}.jar`, version: `1.${k}.0`, findings: 19 - k * 2, applications: 6 - k })),
    };
  }
  return v;
}

async function call(request: APIRequestContext, method: string, url: string, data?: unknown) {
  const r = await request.fetch(url, { method, data });
  expect(r.status(), `${method} ${url}: ${await r.text()}`).toBeLessThan(300);
  return r.json();
}

async function ensureClient(request: APIRequestContext, name: string): Promise<string> {
  const found = await call(request, 'GET', `/api/clients?q=${encodeURIComponent(name)}&limit=50`);
  const hit = found.items.find((c: { name: string }) => c.name === name);
  return hit ? hit.id : (await call(request, 'POST', '/api/clients', { name })).id;
}

async function ensureApproved(request: APIRequestContext, clientId: string, label: string, values: Record<string, unknown>): Promise<string> {
  const list = await call(request, 'GET', `/api/competences?owner_kind=client&owner_id=${clientId}`);
  const existing = list.items.find((c: { competence: string }) => c.competence === label);
  if (existing?.official_revision) return existing.id;
  const comp = existing ?? (await call(request, 'POST', '/api/competences', { owner_kind: 'client', owner_id: clientId, competence: label, operator: OP }));
  const base = `/api/competences/${comp.id}/revisions/1`;
  const lock = async () => (await call(request, 'GET', base)).lock_version;
  for (const [metric, value] of Object.entries(values))
    await call(request, 'PUT', `${base}/metrics/${metric}`, { value, justification: 'Valor sintético justificado (regressão visual F06B.1)', operator: OP, expected_lock_version: await lock() });
  await call(request, 'PUT', `${base}/required`, { metric_ids: ['apps.total'], operator: OP, expected_lock_version: await lock() });
  await call(request, 'POST', `${base}/submit`, { operator: OP, expected_lock_version: await lock() });
  await call(request, 'POST', `${base}/approve`, { approver: 'Aprovador Visual Sintético', expected_lock_version: await lock() });
  return comp.id;
}

const SEV = ['sast.policy.open.by_severity', 'sca.policy.open.by_severity'];
const BODY = 'Texto sintético de apoio para a regressão visual.\n\nSegundo parágrafo sintético, sem dados reais.';

/** Template que exercita todos os tipos de slide e todos os layouts do catálogo F06A. */
export function visualTemplate(theme: { id: string; version: number }, name: string) {
  return {
    name,
    description: 'Fixture sintética da regressão visual (F06B.1): todos os tipos de slide e layouts.',
    theme,
    metric_contracts: Object.fromEntries(
      ['apps.total', 'apps.without_team', 'licenses.usage', 'apps.by_business_unit', 'apps.by_team', ...SEV, 'sast.policy.open.top_applications', 'sca.policy.open.top_components'].map((m) => [m, [1]]),
    ),
    slides: [
      { slot_id: 'capa', type: 'cover', required: true, fields: { title: 'Relatório visual sintético', subtitle: 'Fixture de regressão' }, options: { show_presenters: true } },
      { slot_id: 'sumario', type: 'executive_summary', layout: 'text-with-highlights', fields: { title: 'Sumário executivo', subtitle: 'Destaques do mês', body: BODY, items: ['Primeiro tópico sintético', 'Segundo tópico sintético'], caption: 'Legenda sintética.' }, metrics: ['apps.total', SEV[0]] },
      { slot_id: 'sumario-texto', type: 'executive_summary', layout: 'text-only', fields: { title: 'Sumário (só texto)', body: BODY, items: ['Tópico A', 'Tópico B', 'Tópico C'] } },
      { slot_id: 'kpis', type: 'kpis', fields: { title: 'Indicadores principais', caption: 'Um indicador sem valor aparece como ausente.' }, metrics: ['apps.total', ...SEV, 'apps.without_team'] },
      { slot_id: 'comparacao', type: 'month_comparison', layout: 'comparison-table', fields: { title: 'Mês atual × anterior' }, metrics: ['apps.total', ...SEV] },
      { slot_id: 'comparacao-cards', type: 'month_comparison', layout: 'comparison-cards', fields: { title: 'Comparação em cartões' }, metrics: ['apps.total', 'licenses.usage'] },
      { slot_id: 'barras-bu', type: 'bar_chart', layout: 'chart-full', fields: { title: 'Aplicações por BU', chart_title: 'Distribuição aprovada' }, metrics: ['apps.by_business_unit'], options: { data_mode: 'breakdown' } },
      { slot_id: 'barras-historico', type: 'bar_chart', layout: 'chart-with-text', fields: { title: 'Aplicações — 12 meses', chart_title: 'Total mensal', body: BODY }, metrics: ['apps.total'], options: { data_mode: 'history', months: 12 } },
      { slot_id: 'linhas', type: 'line_chart', layout: 'chart-full', fields: { title: 'SAST × SCA — 12 meses', chart_title: 'Findings abertos', legend_title: 'Origem' }, metrics: SEV, options: { months: 12 } },
      { slot_id: 'linhas-texto', type: 'line_chart', layout: 'chart-with-text', fields: { title: 'Aplicações — 6 meses', body: BODY }, metrics: ['apps.total'], options: { months: 6, show_legend: false } },
      { slot_id: 'severidade', type: 'severity_distribution', layout: 'chart-full', fields: { title: 'SAST por severidade', chart_title: 'Findings abertos por severidade' }, metrics: [SEV[0]] },
      { slot_id: 'severidade-texto', type: 'severity_distribution', layout: 'chart-with-text', fields: { title: 'SCA por severidade', body: BODY }, metrics: [SEV[1]] },
      { slot_id: 'ranking', type: 'top10_ranking', layout: 'ranking-table', fields: { title: 'Top 10 aplicações' }, metrics: ['sast.policy.open.top_applications'], options: { top_n: 10 } },
      { slot_id: 'ranking-barras', type: 'top10_ranking', layout: 'ranking-bars', fields: { title: 'Top 5 componentes', chart_title: 'Componentes com mais findings' }, metrics: ['sca.policy.open.top_components'], options: { top_n: 5 } },
      { slot_id: 'tabela', type: 'metric_table', fields: { title: 'Tabela de indicadores' }, metrics: ['apps.total', ...SEV, 'licenses.usage', 'apps.without_team'] },
      { slot_id: 'indisponivel', type: 'bar_chart', fields: { title: 'Distribuição sem valor aprovado' }, metrics: ['apps.by_team'], options: { data_mode: 'breakdown' } },
      { slot_id: 'recomendacoes', type: 'recommendations', layout: 'bullets', fields: { title: 'Recomendações', items: ['Recomendação sintética um', 'Recomendação sintética dois', 'Recomendação sintética três'] } },
      { slot_id: 'recomendacoes-2col', type: 'recommendations', layout: 'two-columns', fields: { title: 'Observações', body: 'Observações sintéticas em duas colunas.', items: ['Item 1', 'Item 2', 'Item 3', 'Item 4', 'Item 5'] } },
      { slot_id: 'encerramento', type: 'closing', required: true, fields: { title: 'Obrigado', subtitle: 'Encerramento sintético', body: 'Contato: equipe sintética.' }, options: { show_presenters: true } },
    ],
  };
}

/** Cria (ou reaproveita) dados e uma apresentação NOVA do template `key`; retorna o id da apresentação. */
export async function visualPresentation(request: APIRequestContext, key: string, theme: { id: string; version: number }, templateName: string): Promise<string> {
  const clientId = await ensureClient(request, VISUAL_CLIENT);
  let primary = '';
  for (const [i, label] of MONTHS.entries()) {
    const id = await ensureApproved(request, clientId, label, valuesFor(i, label));
    if (label === PRIMARY) primary = id;
  }
  const t = await request.post('/api/presentation-templates', { data: { key, definition: visualTemplate(theme, templateName), operator: OP } });
  expect([201, 409], await t.text()).toContain(t.status()); // 409 = já existe neste banco (mesma definição)
  const p = await call(request, 'POST', '/api/presentations', { competence_id: primary, template_key: key, template_version: 1, title: 'Apresentação visual sintética', operator: OP });
  const r1 = await call(request, 'GET', `/api/presentations/${p.id}/revisions/1`);
  const document = { ...r1.document, presenters: [{ name: 'Pessoa Sintética Um', role: 'Apresentadora' }, { name: 'Pessoa Sintética Dois', role: null }] };
  await call(request, 'PUT', `/api/presentations/${p.id}/document`, { document, expected_revision: 1, operator: OP, summary: 'Apresentadores sintéticos' });
  return p.id;
}
