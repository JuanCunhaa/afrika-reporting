import { APIRequestContext, expect, test } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { captureSlides } from '../visual/capture';
import { type Box, compareImages } from '../visual/diff';
import type { ElementInfo } from '../visual/manifest';
import { type Image, decodePng } from '../visual/png';
import { visualPresentation } from './visual-fixture';

// F07 — MEDIÇÃO LOCAL de fidelidade HTML × PPTX × PDF (Windows + PowerPoint instalado). Reaproveita o motor visual
// (captura #/render, manifesto, compareImages). Conteúdo SINTÉTICO equivalente nas três modalidades: o mesmo documento
// e as mesmas revisões aprovadas. PDF rasterizado pela API do Windows (scripts/render_pdf.ps1); PPTX pelo PowerPoint
// via COM (scripts/render_pptx.ps1) com as fontes OFL do tema registradas SÓ durante a renderização. Saídas em
// output/export-fidelity/ (ignorado pelo Git). Nada é enviado a serviços externos. No CI (Linux) é pulado.
const ENABLED = process.platform === 'win32' && process.env.AFRIKA_EXPORT_FIDELITY === '1';
const here = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(here, '..', '..');
const OUT = path.join(ROOT, 'output', 'export-fidelity');
const PY = /[\\/]/.test(process.env.PYTHON ?? '') ? path.resolve(process.env.PYTHON as string) : process.env.PYTHON || 'python';
const OP = 'Operadora Fidelidade F07';
const run = Date.now().toString(36);
const THRESHOLD = 0.08; // mesmo limiar YIQ das comparações com a referência (docs/VISUAL_FIDELITY.md)

const sev = (...n: number[]) => {
  const keys = ['VERY_HIGH', 'HIGH', 'MEDIUM', 'LOW', 'VERY_LOW', 'INFORMATIONAL', 'UNKNOWN'];
  return { ...Object.fromEntries(keys.map((k, i) => [k, n[i]])), total: n.reduce((a, b) => a + b, 0) };
};

/** Igual a backend/tests/export_fixtures.full_values: todos os indicadores do afrika-modelo@2 (apresentação pronta). */
function fullValues(i: number, primary: boolean): Record<string, unknown> {
  const v: Record<string, unknown> = {
    'apps.total': 140 + i, 'apps.without_team': 7, 'apps.multiple_teams': 3, 'apps.unclassified': 2, 'apps.loc.total': 2_400_000 + i * 35_000,
    'sast.policy.open.by_severity': sev(2, 7, 23 + i, 9, 3, 1, 1), 'sca.policy.open.by_severity': sev(1, 4, 11 + i, 5, 2, 1, 0),
    'sast.sandbox.open.by_severity': sev(1, 3, 8, 6, 2, 0, 1), 'sast.open.distinct': sev(2, 7, 18 + i, 11, 3, 1, 0),
    'sca.open.distinct': sev(1, 5, 9, 6, 2, 1, 0), 'sast.policy.new_in_period.by_severity': sev(0, 1, 4 + i, 2, 1, 0, 0),
  };
  if (primary) {
    v['apps.by_business_unit'] = { items: ['Norte', 'Sul', 'Leste', 'Oeste', 'Centro'].map((n, k) => ({ business_unit_id: `ab${k}`, name: `Unidade ${n}`, applications: 41 - k * 7 })), unknown: 0, distinct_applications: 135 };
    v['sast.policy.open.top_applications'] = { top: Array.from({ length: 12 }, (_, k) => ({ application_guid: `ag${k}`, name: `Aplicação Sintética ${String(k + 1).padStart(2, '0')}`, findings: 64 - k * 5 })), total: 512 };
    v['sast.policy.open.by_cwe'] = { top: [79, 89, 117, 327, 73, 601].map((cwe, k) => ({ cwe_id: cwe, findings: 38 - k * 5 })), others: 12 };
    v['sca.policy.open.top_components'] = { top: Array.from({ length: 10 }, (_, k) => ({ component_id: `ac${k}`, filename: `biblioteca-sintetica-${k + 1}.jar`, version: `2.${k}.1`, findings: 27 - k * 2, applications: 9 - (k % 5) })) };
    v['sca.policy.open.top_vulnerabilities'] = { top: Array.from({ length: 10 }, (_, k) => ({ vulnerability_id: `VULN-SINT-${String(k + 1).padStart(3, '0')}`, applications: 12 - k, findings: 30 - k * 2, max_severity: ['VERY_HIGH', 'HIGH', 'MEDIUM'][k % 3] })) };
  }
  return v;
}

async function call(request: APIRequestContext, method: string, url: string, data?: unknown) {
  const r = await request.fetch(url, { method, data });
  expect(r.status(), `${method} ${url}: ${await r.text()}`).toBeLessThan(300);
  return r.json();
}

async function approved(request: APIRequestContext, clientId: string, label: string, values: Record<string, unknown>) {
  const comp = await call(request, 'POST', '/api/competences', { owner_kind: 'client', owner_id: clientId, competence: label, operator: OP });
  const base = `/api/competences/${comp.id}/revisions/1`;
  const lock = async () => (await call(request, 'GET', base)).lock_version;
  for (const [metric, value] of Object.entries(values))
    await call(request, 'PUT', `${base}/metrics/${metric}`, { value, justification: 'Valor sintético justificado (fidelidade F07)', operator: OP, expected_lock_version: await lock() });
  await call(request, 'PUT', `${base}/required`, { metric_ids: ['apps.total'], operator: OP, expected_lock_version: await lock() });
  await call(request, 'POST', `${base}/submit`, { operator: OP, expected_lock_version: await lock() });
  await call(request, 'POST', `${base}/approve`, { approver: 'Aprovador Fidelidade', expected_lock_version: await lock() });
  return comp.id as string;
}

async function afrikaReady(request: APIRequestContext): Promise<string> {
  const client = await call(request, 'POST', '/api/clients', { name: `Cliente Fidelidade ${run}` });
  await approved(request, client.id, '2026-08', fullValues(-1, false));
  const sep = await approved(request, client.id, '2026-09', fullValues(0, true));
  const p = await call(request, 'POST', '/api/presentations', { competence_id: sep, template_key: 'afrika-modelo', template_version: 2, operator: OP });
  return p.id;
}

async function exportFile(request: APIRequestContext, pid: string, format: 'pptx' | 'pdf', target: string) {
  let job = await call(request, 'POST', `/api/presentations/${pid}/exports`, { format, revision: (await call(request, 'GET', `/api/presentations/${pid}`)).current_revision, operator: OP });
  for (let i = 0; i < 300 && (job.status === 'queued' || job.status === 'running'); i++) {
    await new Promise((r) => setTimeout(r, 200));
    job = await call(request, 'GET', `/api/exports/${job.id}`);
  }
  expect(job.status, JSON.stringify(job.error)).toBe('done');
  const r = await request.get(job.download_url);
  fs.writeFileSync(target, await r.body());
  return job;
}

function ps(script: string, args: string[]) {
  execFileSync('powershell', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', path.join(ROOT, 'scripts', script), ...args], { stdio: 'pipe', timeout: 10 * 60_000 });
}

// ---------------------------------------------------------------- análise

const CHART = new Set(['plot', 'chart', 'donut', 'slice', 'legend', 'sev', 'bar', 'point', 'chart-gaps', 'sev-total']);
const TABLE = new Set(['table', 'comparison', 'ranking', 'rank', 'row', 'matrix', 'matrix-head']);
const SHAPE = new Set(['shape', 'zone', 'title-underline', 'cover-band', 'competence-badge', 'kpi-band', 'kpi-card', 'sev-card', 'image', 'brand']);
type Category = 'gráficos' | 'tabelas' | 'texto' | 'formas' | 'fundo';

function categoryOf(roles: string[]): Category {
  if (roles.some((r) => CHART.has(r))) return 'gráficos';
  if (roles.some((r) => TABLE.has(r))) return 'tabelas';
  if (roles.some((r) => !SHAPE.has(r))) return roles.length ? 'texto' : 'fundo';
  return roles.length ? 'formas' : 'fundo';
}

const inside = (a: Box, b: Box) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

function byCategory(regions: (Box & { pixels: number })[], elements: ElementInfo[]) {
  const out: Record<Category, number> = { gráficos: 0, tabelas: 0, texto: 0, formas: 0, fundo: 0 };
  for (const r of regions) out[categoryOf(elements.filter((e) => inside(e.box, r)).map((e) => e.role))] += r.pixels;
  return out;
}

/** Caixa da "tinta" (pixels distintos do fundo predominante) dentro de uma caixa. */
function ink(img: Image, b: Box, pad = 4): Box | null {
  const x0 = Math.max(0, Math.floor(b.x - pad)), y0 = Math.max(0, Math.floor(b.y - pad));
  const x1 = Math.min(img.width, Math.ceil(b.x + b.w + pad)), y1 = Math.min(img.height, Math.ceil(b.y + b.h + pad));
  if (x1 <= x0 || y1 <= y0) return null;
  const lum = (x: number, y: number) => { const i = (y * img.width + x) * 4; return 0.299 * img.data[i] + 0.587 * img.data[i + 1] + 0.114 * img.data[i + 2]; };
  const hist = new Map<number, number>();
  for (let y = y0; y < y1; y += 2) for (let x = x0; x < x1; x += 2) { const k = Math.round(lum(x, y) / 8); hist.set(k, (hist.get(k) ?? 0) + 1); }
  const bg = [...hist.entries()].sort((a, b) => b[1] - a[1])[0][0] * 8;
  let minX = Infinity, minY = Infinity, maxX = -1, maxY = -1;
  for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) if (Math.abs(lum(x, y) - bg) > 60) { minX = Math.min(minX, x); minY = Math.min(minY, y); maxX = Math.max(maxX, x); maxY = Math.max(maxY, y); }
  return maxX < 0 ? null : { x: minX, y: minY, w: maxX - minX + 1, h: maxY - minY + 1 };
}

const median = (v: number[]) => (v.length ? [...v].sort((a, b) => a - b)[Math.floor(v.length / 2)] : 0);
const pct = (n: number, total: number) => Math.round((10000 * n) / total) / 100;

test.skip(!ENABLED, 'medição LOCAL (Windows + PowerPoint): defina AFRIKA_EXPORT_FIDELITY=1');

test('fidelidade HTML × PPTX × PDF por slide (conteúdo sintético equivalente)', async ({ page, request }) => {
  test.setTimeout(20 * 60_000);
  fs.mkdirSync(OUT, { recursive: true });
  execFileSync(PY, [path.join(ROOT, 'scripts', 'export_fonts.py'), path.join(OUT, 'fonts')], { stdio: 'pipe' });
  const cases = [
    { name: 'afrika-v2', pid: await afrikaReady(request) },
    { name: 'neutral-demo', pid: await visualPresentation(request, `fid-neutral-${run}`, { id: 'neutral-demo', version: 1 }, 'Fidelidade F07 (neutro)') },
  ];
  const report: Record<string, unknown>[] = [];
  for (const c of cases) {
    const dir = path.join(OUT, c.name);
    fs.mkdirSync(dir, { recursive: true });
    const html = await captureSlides(page, c.pid, c.name);
    const lines: Record<string, number>[] = await page.evaluate(() => {
      const api = (window as unknown as { __afrikaExport: { slides: () => number; layout: (i: number) => { ops: { op: string; key: string; lines?: number }[] } } }).__afrikaExport;
      return Array.from({ length: api.slides() }, (_, i) => Object.fromEntries(api.layout(i + 1).ops.filter((o) => o.op === 'text').map((o) => [o.key, o.lines ?? 0])));
    });
    const pptxJob = await exportFile(request, c.pid, 'pptx', path.join(dir, 'deck.pptx'));
    const pdfJob = await exportFile(request, c.pid, 'pdf', path.join(dir, 'deck.pdf'));
    const [w, hgt] = [html[0].image.width, html[0].image.height]; // tamanho do canvas do tema (16:9 ou outro)
    ps('render_pdf.ps1', ['-Pdf', path.join(dir, 'deck.pdf'), '-OutDir', path.join(dir, 'pdf'), '-Width', String(w)]);
    ps('render_pptx.ps1', ['-Pptx', path.join(dir, 'deck.pptx'), '-OutDir', path.join(dir, 'pptx'), '-FontsDir', path.join(OUT, 'fonts'), '-Width', String(w), '-Height', String(hgt)]);
    const ppt = JSON.parse(fs.readFileSync(path.join(dir, 'pptx', 'powerpoint.json'), 'utf8').replace(/^﻿/, ''));
    html.forEach((h, i) => {
      const n = i + 1;
      const pdfImg = decodePng(fs.readFileSync(path.join(dir, 'pdf', `page${String(n).padStart(2, '0')}.png`)));
      const pptImg = decodePng(fs.readFileSync(path.join(dir, 'pptx', `slide${String(n).padStart(2, '0')}.png`)));
      const opts = { colorThreshold: THRESHOLD, detectAntialiasing: true, maxRegions: 400 };
      const vsPdf = compareImages(h.image, pdfImg, opts);
      const vsPpt = compareImages(h.image, pptImg, opts);
      const total = h.image.width * h.image.height;
      const texts = h.manifest.elements.filter((e) => e.text_length > 0 && e.box.w > 2 && e.box.h > 2);
      const offsets = texts.map((e) => { const a = ink(h.image, e.box), b = ink(pptImg, e.box); return a && b ? { key: e.key, dx: b.x - a.x, dy: b.y - a.y } : null; }).filter(Boolean) as { key: string; dx: number; dy: number }[];
      const pdfOffsets = texts.map((e) => { const a = ink(h.image, e.box), b = ink(pdfImg, e.box); return a && b ? Math.max(Math.abs(b.x - a.x), Math.abs(b.y - a.y)) : null; }).filter((v) => v !== null) as number[];
      const pptLines = Object.fromEntries((ppt.text as { slide: number; key: string; lines: number }[]).filter((t) => t.slide === n && !t.key.includes('[')).map((t) => [t.key, t.lines]));
      const mismatch = Object.entries(lines[i]).filter(([k, l]) => pptLines[k] !== undefined && pptLines[k] !== l).map(([k, l]) => ({ key: k, html: l, pptx: pptLines[k] }));
      report.push({
        case: c.name, slide: h.name,
        dims: { html: [h.image.width, h.image.height], pdf: [pdfImg.width, pdfImg.height], pptx: [pptImg.width, pptImg.height] },
        html_vs_pdf: { diff_pct: pct(vsPdf.diff_pixels, total), aa_pct: pct(vsPdf.aa_pixels, total), by_category: byCategory(vsPdf.regions, h.manifest.elements), text_offset_max: Math.max(0, ...pdfOffsets) },
        html_vs_pptx: { diff_pct: pct(vsPpt.diff_pixels, total), aa_pct: pct(vsPpt.aa_pixels, total), by_category: byCategory(vsPpt.regions, h.manifest.elements),
          text_dy_median: median(offsets.map((o) => o.dy)), text_dx_median: median(offsets.map((o) => o.dx)),
          text_offset_p95: [...offsets.map((o) => Math.max(Math.abs(o.dx), Math.abs(o.dy)))].sort((a, b) => a - b)[Math.floor(offsets.length * 0.95)] ?? 0,
          text_worst: offsets.sort((a, b) => Math.max(Math.abs(b.dx), Math.abs(b.dy)) - Math.max(Math.abs(a.dx), Math.abs(a.dy))).slice(0, 3),
          texts_measured: offsets.length, line_mismatches: mismatch },
      });
    });
    report.push({ case: c.name, summary: true, pptx: { sha256: pptxJob.sha256, size: pptxJob.size, timings: pptxJob.timings, objects: pptxJob.report.content.objects },
      pdf: { sha256: pdfJob.sha256, size: pdfJob.size, timings: pdfJob.timings, pages: pdfJob.report.pdf.pages }, powerpoint: { fonts: ppt.fonts, session_fonts: ppt.session_fonts, opened: ppt.opened } });
  }
  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 2));
  const rows = report.filter((r) => !r.summary) as { case: string; slide: string; html_vs_pdf: { diff_pct: number; text_offset_max: number }; html_vs_pptx: { diff_pct: number; by_category: Record<string, number>; text_dy_median: number; text_dx_median: number; text_offset_p95: number; line_mismatches: unknown[] } }[];
  const md = ['# Fidelidade HTML × PPTX × PDF (medição local)', '', `Gerado em ${new Date().toISOString()} — limiar YIQ ${THRESHOLD}, antisserrilhado separado.`, '',
    '| Caso / slide | HTML×PDF dif. % | HTML×PDF texto máx px | HTML×PPTX dif. % | PPTX: gráficos / tabelas / texto / formas (px) | texto Δy/Δx mediana | texto p95 px | linhas ≠ |', '|---|---|---|---|---|---|---|---|',
    ...rows.map((r) => `| ${r.case} / ${r.slide} | ${r.html_vs_pdf.diff_pct} | ${r.html_vs_pdf.text_offset_max} | ${r.html_vs_pptx.diff_pct} | ${['gráficos', 'tabelas', 'texto', 'formas'].map((k) => r.html_vs_pptx.by_category[k]).join(' / ')} | ${r.html_vs_pptx.text_dy_median}/${r.html_vs_pptx.text_dx_median} | ${r.html_vs_pptx.text_offset_p95} | ${r.html_vs_pptx.line_mismatches.length} |`)];
  fs.writeFileSync(path.join(OUT, 'report.md'), `${md.join('\n')}\n`);
  expect(rows.length).toBeGreaterThan(20);
  for (const r of rows) expect(r.html_vs_pptx.line_mismatches, `${r.case}/${r.slide}`).toBeDefined();
});
