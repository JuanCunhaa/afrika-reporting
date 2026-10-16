import { expect, test } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { captureSlides } from '../visual/capture';
import { type Box, compareImages } from '../visual/diff';
import type { ElementInfo } from '../visual/manifest';
import { collectOverflow } from '../visual/overflow';
import { type Image, decodePng, encodePng } from '../visual/png';
import { afrikaPresentation } from './visual-fixture';

// F06C — comparação INTEGRAL (sem máscara) do template afrika-modelo@2 com a renderização LOCAL do PowerPoint de
// referência, com CONTEÚDO SINTÉTICO EQUIVALENTE e métricas SEPARADAS por categoria: geometria, tipografia, cores,
// gráficos, distribuição de conteúdo e overflow/cortes — e atribuição da diferença por classe de área (ativos de marca,
// gráficos, texto, estrutura). Só roda na máquina que tem o arquivo (no CI é pulada):
//   AFRIKA_REFERENCE_RENDER = pasta com slideNN.png (scripts/render_reference.ps1, em private/)
//   AFRIKA_REFERENCE_REPORT = report.json da inspeção local em modo strict
// "Equivalente" = comprimentos de texto, nº de tópicos/grupos e de células tirados SÓ das contagens estruturais do
// relatório strict (caracteres e parágrafos por forma) — nenhum texto, número ou nome da referência é lido ou gravado.
// Saída só numérica em output/reference-compare/integral.{json,md}; PNGs de diferença ficam locais (contêm a
// referência: não publicar).
const RENDER = process.env.AFRIKA_REFERENCE_RENDER;
const REPORT = process.env.AFRIKA_REFERENCE_REPORT;
const here = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(here, '../../output/reference-compare');
const MAP = JSON.parse(fs.readFileSync(path.resolve(here, '../visual/reference-map.json'), 'utf8')) as {
  slides: { slide: number; kind: string; pairs: { what: string; ref: number[]; html: string; text?: boolean }[] }[];
};
const THRESHOLD = 0.08;

type TextInfo = { characters: number; paragraphs: number; autofit?: string | null; style?: { sizes_pt: number[]; fonts: string[]; colors: string[]; bold_share: number } };
type RefShape = { n: number; kind: string; depth?: number; box_px?: Box | null; text?: TextInfo | null; fill_color?: string; table?: { rows: number; columns: number } };
type RefChart = { kinds: { type: string; series: number; points_per_series: number[]; hole_size?: number | null }[] };
type RefSlide = { shapes: RefShape[]; charts: RefChart[] };

const r1 = (n: number) => Math.round(n * 10) / 10;
const pct = (a: number, b: number) => r1((a / Math.max(1, b)) * 100);
const center = (b: Box) => [b.x + b.w / 2, b.y + b.h / 2];
const inside = (p: number[], b: Box) => p[0] >= b.x && p[0] <= b.x + b.w && p[1] >= b.y && p[1] <= b.y + b.h;
const union = (boxes: Box[]): Box => {
  const x0 = Math.min(...boxes.map((b) => b.x)), y0 = Math.min(...boxes.map((b) => b.y));
  const x1 = Math.max(...boxes.map((b) => b.x + b.w)), y1 = Math.max(...boxes.map((b) => b.y + b.h));
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
};

// ---------------------------------------------------------------- conteúdo sintético equivalente

const WORDS = ['conteúdo', 'sintético', 'equivalente', 'modelo', 'análise', 'painel', 'indicador', 'resumo', 'plano', 'ação', 'mensal', 'dados', 'exemplo', 'nível', 'tema'];
function synth(n: number, seed = 0): string {
  const target = Math.max(1, Math.round(n));
  let out = '';
  for (let i = seed; out.length < target; i++) out += (out ? ' ' : '') + WORDS[i % WORDS.length];
  out = out.slice(0, target).trimEnd();
  while (out.length < target) out += 'o';
  return out[0].toUpperCase() + out.slice(1);
}

type Doc = { slides: { template_slot: string | null; fields: { title?: string | null; subtitle?: string | null; body?: string | null; caption?: string | null; items: string[] } }[] };

function textShapesIn(shapes: RefShape[], box: Box): RefShape[] {
  return shapes.filter((s) => s.kind !== 'group' && s.box_px && (s.text?.characters ?? 0) > 0 && inside(center(s.box_px), box));
}

/** Iguala os campos editoriais às CONTAGENS da referência (slide i ↔ slot i): título, subtítulo, legenda, seção,
 * tópicos (nº de parágrafos e caracteres), corpo, grupos do encerramento e matriz. Números continuam sintéticos. */
function equalize(doc: Doc, report: { slides: RefSlide[] }): { slide: number; field: string; ref_chars: number; paragraphs?: number; limited_to?: number }[] {
  const log: { slide: number; field: string; ref_chars: number; paragraphs?: number; limited_to?: number }[] = [];
  for (const spec of MAP.slides) {
    const slide = doc.slides[spec.slide - 1];
    const shapes = report.slides[spec.slide - 1].shapes;
    const byN = new Map(shapes.map((s) => [s.n, s]));
    const chars = (refs: number[]) => refs.reduce((a, n) => a + (byN.get(n)?.text?.characters ?? 0), 0);
    const box = (refs: number[]) => union(refs.map((n) => byN.get(n)?.box_px).filter(Boolean) as Box[]);
    const matrix: Record<string, number> = {};
    for (const p of spec.pairs) {
      const c = chars(p.ref);
      if (['title', 'section'].includes(p.html) && c) {
        slide.fields.title = synth(c, spec.slide);
        log.push({ slide: spec.slide, field: 'title', ref_chars: c });
      } else if (p.html === 'subtitle' && c) {
        slide.fields.subtitle = synth(c, spec.slide + 3);
        log.push({ slide: spec.slide, field: 'subtitle', ref_chars: c });
      } else if (p.html === 'caption' && c) {
        slide.fields.caption = synth(c, spec.slide + 5);
        log.push({ slide: spec.slide, field: 'caption', ref_chars: c });
      } else if (['zone:list', 'zone:notes'].includes(p.html)) {
        const ts = textShapesIn(shapes, box(p.ref));
        const paras = ts.reduce((a, s) => a + (s.text?.paragraphs ?? 1), 0);
        const total = ts.reduce((a, s) => a + (s.text?.characters ?? 0), 0);
        // na referência os tópicos podem ser TABELAS (o modo strict expõe linhas, não caracteres): nº de linhas e
        // comprimento ESTIMADO (60) — registrado como estimativa
        const rows = shapes.filter((s) => s.table && s.box_px && inside(center(s.box_px), box(p.ref))).reduce((a, s) => a + (s.table?.rows ?? 0), 0);
        if (paras && total) {
          slide.fields.items = Array.from({ length: Math.min(12, paras) }, (_, k) => synth(total / paras, k));
          log.push({ slide: spec.slide, field: 'items', ref_chars: total, paragraphs: paras });
        } else if (rows) {
          slide.fields.items = Array.from({ length: Math.min(12, rows) }, (_, k) => synth(60, k));
          log.push({ slide: spec.slide, field: 'items (tabela; comprimento estimado)', ref_chars: 0, paragraphs: rows });
        }
      } else if (p.html === 'zone:text') {
        const total = textShapesIn(shapes, box(p.ref)).reduce((a, s) => a + (s.text?.characters ?? 0), 0);
        if (total) {
          slide.fields.body = synth(total, 7);
          log.push({ slide: spec.slide, field: 'body', ref_chars: total });
        }
      } else if (p.html === 'closing-groups') {
        slide.fields.items = p.ref.map((n, k) => {
          const total = textShapesIn(shapes, byN.get(n)?.box_px as Box).reduce((a, s) => a + (s.text?.characters ?? 0), 0) || 20;
          return `${synth(total * 0.35, k)} | ${synth(total * 0.65, k + 4)}`;
        });
        log.push({ slide: spec.slide, field: 'closing-groups', ref_chars: p.ref.length });
      } else if (p.html.startsWith('matrix') && c) matrix[p.html] = c;
    }
    if (Object.keys(matrix).length && slide.fields.items.length) {
      const cols = slide.fields.items[0].split(' | ').length;
      const label = matrix['matrix:1:1'] ?? 10;
      // contrato: cada linha da matriz é um item de até 400 caracteres ("a | b | c | d"); célula maior é LIMITADA
      const cellMax = Math.floor((400 - label - 3 * (cols - 1)) / (cols - 1));
      const cell = Math.min(matrix['matrix:1:2'] ?? 40, cellMax);
      const head = ['Tema', ...Array.from({ length: cols - 1 }, (_, k) => synth(matrix[`matrix-head:${k + 2}`] ?? 12, k))];
      const rows = slide.fields.items.slice(1).map((_, r) => [synth(label, r), ...Array.from({ length: cols - 1 }, (_, k) => synth(cell, r + k))].join(' | '));
      slide.fields.items = [head.join(' | '), ...rows];
      log.push({ slide: spec.slide, field: 'matrix', ref_chars: matrix['matrix:1:2'] ?? 0, ...(cell < (matrix['matrix:1:2'] ?? 0) ? { limited_to: cell } : {}) });
    }
  }
  return log;
}

// ---------------------------------------------------------------- medições

const RGB = (s: string | null): number[] | null => {
  const m = s && /rgba?\((\d+), (\d+), (\d+)/.exec(s);
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null;
};
const HEX = (s?: string | null): number[] | null => (s && /^#[0-9a-f]{6}$/i.test(s) ? [1, 3, 5].map((i) => parseInt(s.slice(i, i + 2), 16)) : null);
const dist = (a: number[], b: number[]) => Math.max(...a.map((v, i) => Math.abs(v - b[i])));

/** Cor predominante (quantizada a 16 níveis) dentro da caixa, ignorando as caixas de texto. */
function modeColor(img: Image, b: Box, skip: Box[]): number[] | null {
  const bins = new Map<number, number>();
  for (let y = Math.max(0, Math.floor(b.y)); y < Math.min(img.height, b.y + b.h); y += 2)
    for (let x = Math.max(0, Math.floor(b.x)); x < Math.min(img.width, b.x + b.w); x += 2) {
      if (skip.some((s) => inside([x, y], s))) continue;
      const o = (y * img.width + x) * 4;
      const k = ((img.data[o] >> 4) << 8) | ((img.data[o + 1] >> 4) << 4) | (img.data[o + 2] >> 4);
      bins.set(k, (bins.get(k) ?? 0) + 1);
    }
  const top = [...bins.entries()].sort((p, q) => q[1] - p[1])[0];
  return top ? [top[0] >> 8, (top[0] >> 4) & 15, top[0] & 15].map((v) => v * 16 + 8) : null;
}

/** "Tinta": fração de pixels da caixa que diferem da cor predominante (quanto conteúdo visível há na área). */
function ink(img: Image, b: Box): number {
  const base = modeColor(img, b, []);
  if (!base) return 0;
  let n = 0, hit = 0;
  for (let y = Math.max(0, Math.floor(b.y)); y < Math.min(img.height, b.y + b.h); y += 2)
    for (let x = Math.max(0, Math.floor(b.x)); x < Math.min(img.width, b.x + b.w); x += 2) {
      const o = (y * img.width + x) * 4;
      n++;
      if (dist([img.data[o], img.data[o + 1], img.data[o + 2]], base) > 40) hit++;
    }
  return pct(hit, n);
}

function htmlTextBoxes(elements: ElementInfo[]): Box[] {
  return elements.filter((e) => e.text_length > 0 && !['plot', 'donut'].includes(e.role)).map((e) => e.box);
}

type ViewZone = { kind: string; data?: { kind?: string; series?: unknown[]; categories?: unknown[] } | null };
type ViewSlide = { data?: { kind?: string; zones?: Record<string, ViewZone> } | null };

function htmlCharts(slide: ViewSlide): { type: string; series: number; points: number }[] {
  const out: { type: string; series: number; points: number }[] = [];
  for (const z of Object.values(slide.data?.zones ?? {})) {
    const d = z.data;
    if (!d || !('kind' in d)) continue;
    const n = (d.series ?? []).length, pts = (d.categories ?? []).length;
    if (z.kind === 'donut') out.push({ type: 'doughnutChart', series: 1, points: pts });
    else if (d.kind === 'combo') out.push({ type: 'barChart', series: 1, points: pts }, { type: 'lineChart', series: n - 1, points: pts });
    else if (d.kind === 'line') out.push({ type: 'lineChart', series: n, points: pts });
    else if (z.kind === 'chart') out.push({ type: 'barChart', series: n, points: pts });
  }
  return out;
}

test('comparação INTEGRAL por categoria com conteúdo sintético equivalente (local)', async ({ page, request }) => {
  test.skip(!RENDER || !REPORT, 'comparação com a referência real só roda localmente (arquivo não existe no CI)');
  test.setTimeout(600_000);
  await page.setViewportSize({ width: 1920, height: 1080 });
  const report = JSON.parse(fs.readFileSync(REPORT as string, 'utf8'));
  expect(report.privacy, 'use o relatório em modo strict').toBe('strict');
  // estado SEM ativos de marca (é o que a comparação quer atribuir): limpa a pasta descartável do E2E
  if (process.env.AFRIKA_E2E_BRAND_DIR) fs.rmSync(path.join(process.env.AFRIKA_E2E_BRAND_DIR, 'afrika'), { recursive: true, force: true });

  const pid = await afrikaPresentation(request, 2);
  const cur = await (await request.get(`/api/presentations/${pid}`)).json();
  const doc = (await (await request.get(`/api/presentations/${pid}/revisions/${cur.current_revision}`)).json()).document as Doc;
  const equalized = equalize(doc, report);
  const saved = await request.put(`/api/presentations/${pid}/document`, { data: { document: doc, expected_revision: cur.current_revision, operator: 'Operadora Visual Sintética', summary: 'Conteúdo sintético equivalente (comparação integral F06C)' } });
  expect(saved.status(), await saved.text()).toBe(200);
  const view = await (await request.get(`/api/presentations/${pid}/view`)).json();
  const slides = await captureSlides(page, pid, 'afrika-integral');
  const overflow = await collectOverflow(page);
  const master = (report.masters?.[0]?.static_shapes ?? []).map((s: RefShape) => s.box_px).filter(Boolean) as Box[];

  fs.mkdirSync(path.join(OUT, 'integral-diffs'), { recursive: true });
  fs.mkdirSync(path.join(OUT, 'integral-html'), { recursive: true });
  const results = [];
  for (const spec of MAP.slides) {
    const html = slides[spec.slide - 1];
    fs.writeFileSync(path.join(OUT, 'integral-html', `slide${String(spec.slide).padStart(2, '0')}.png`), encodePng(html.image));
    const ref = decodePng(fs.readFileSync(path.join(RENDER as string, `slide${String(spec.slide).padStart(2, '0')}.png`)));
    const rs: RefSlide = report.slides[spec.slide - 1];
    const content = !['capa', 'seção', 'encerramento'].includes(spec.kind);
    const theme = view.theme;
    const kind = spec.kind === 'capa' ? 'cover' : spec.kind === 'encerramento' ? 'closing' : spec.kind === 'seção' ? 'section' : 'content';
    // classes de área (prioridade: ativos > gráficos > texto > estrutura)
    const assets = [
      ...rs.shapes.filter((s) => s.kind === 'picture' && s.box_px && s.box_px.w > 60).map((s) => s.box_px as Box),
      ...(content ? master : []),
      ...theme.asset_slots.filter((a: { slides: string[] }) => a.slides.includes(kind) || a.slides.includes('all')).map((a: { box: Box }) => a.box),
    ];
    const chartsArea = [
      ...rs.shapes.filter((s) => s.kind === 'frame' && !s.table && s.box_px).map((s) => s.box_px as Box),
      ...html.manifest.elements.filter((e) => ['plot', 'donut'].includes(e.role)).map((e) => e.box),
    ];
    const textArea = [...rs.shapes.filter((s) => s.box_px && s.kind !== 'group' && (s.text?.characters ?? 0) > 0).map((s) => s.box_px as Box), ...htmlTextBoxes(html.manifest.elements)];
    const cmp = (mask: Box[]) => compareImages(ref, html.image, { colorThreshold: THRESHOLD, mask });
    const all = cmp([]), noA = cmp(assets), noAC = cmp([...assets, ...chartsArea]), noACT = cmp([...assets, ...chartsArea, ...textArea]);
    const d = (r: ReturnType<typeof cmp>) => r.diff_pixels + r.aa_pixels;
    const px = (r: ReturnType<typeof cmp>) => r.total_pixels - r.masked_pixels;
    const area = {
      assets: { pixels: px(all) - px(noA), diff: d(all) - d(noA) },
      charts: { pixels: px(noA) - px(noAC), diff: d(noA) - d(noAC) },
      text: { pixels: px(noAC) - px(noACT), diff: d(noAC) - d(noACT) },
      structure: { pixels: px(noACT), diff: d(noACT) },
    };
    if (all.diff_image) fs.writeFileSync(path.join(OUT, 'integral-diffs', `slide${String(spec.slide).padStart(2, '0')}.png`), encodePng(all.diff_image));

    const els = new Map(html.manifest.elements.map((e) => [e.key, e]));
    const byN = new Map(rs.shapes.map((s) => [s.n, s]));
    const geometry = [], typography = [], colors = [], distribution = [];
    for (const p of spec.pairs) {
      const refBoxes = p.ref.map((n) => byN.get(n)?.box_px).filter(Boolean) as Box[];
      const el = els.get(p.html);
      if (!refBoxes.length || !el) {
        geometry.push({ what: p.what, status: !el ? 'html_ausente' : 'ref_ausente' });
        continue;
      }
      const rb = union(refBoxes), hb = el.box;
      const dc = Math.max(Math.abs(center(hb)[0] - center(rb)[0]), Math.abs(center(hb)[1] - center(rb)[1]));
      const ds = Math.max(Math.abs(hb.w - rb.w), Math.abs(hb.h - rb.h));
      geometry.push({ what: p.what, text: !!p.text, d_center: r1(dc), d_size: r1(ds), class: (p.text ? dc : Math.max(dc, ds)) <= 5 ? 'ok' : (p.text ? dc : Math.max(dc, ds)) <= 15 ? 'aprox' : 'divergente' });
      const t = byN.get(p.ref[0])?.text;
      if (p.text && t?.style?.sizes_pt?.length) {
        const refPx = r1(Math.max(...t.style.sizes_pt) * (4 / 3));
        const htmlEl = html.manifest.elements.filter((e) => e.font && inside(center(e.box), hb)).sort((a, b) => (b.font?.size ?? 0) - (a.font?.size ?? 0))[0];
        const fam = (htmlEl?.font?.family ?? '').split(',')[0].replace(/"/g, '').trim();
        const refFam = t.style.fonts[0] ?? null;
        typography.push({ what: p.what, ref_size_px: refPx, html_size_px: htmlEl?.font?.size ?? null, d_size_px: htmlEl?.font ? r1(htmlEl.font.size - refPx) : null, ref_font: refFam, html_font: fam, family_match: !!refFam && fam.length > 0 && refFam.toLowerCase().startsWith(fam.toLowerCase()), ref_bold: t.style.bold_share >= 0.5, html_weight: htmlEl?.font?.weight ?? null });
        const refC = HEX(t.style.colors[0]), htmlC = RGB(htmlEl?.color ?? null);
        if (refC && htmlC) colors.push({ what: `${p.what} (texto)`, ref: t.style.colors[0], html: htmlEl?.color, d_max_channel: dist(refC, htmlC), match: dist(refC, htmlC) <= 24 });
        distribution.push({ what: p.what, ref_chars: p.ref.reduce((a, n) => a + (byN.get(n)?.text?.characters ?? 0), 0), html_chars: el.text_length, ref_ink: ink(ref, rb), html_ink: ink(html.image, hb) });
      } else if (!p.text) {
        const skip = [...textArea];
        const a = modeColor(ref, rb, skip), b = modeColor(html.image, hb, skip);
        if (a && b) colors.push({ what: p.what, ref_mode: a, html_mode: b, d_max_channel: dist(a, b), match: dist(a, b) <= 24 });
        distribution.push({ what: p.what, ref_ink: ink(ref, rb), html_ink: ink(html.image, hb) });
      }
    }
    const refCharts = rs.charts.flatMap((c) => c.kinds.map((k) => ({ type: k.type, series: k.series, points: Math.max(0, ...(k.points_per_series ?? [0])) })));
    const hCharts = htmlCharts(view.slides[spec.slide - 1]);
    const count = (xs: { type: string }[]) => Object.fromEntries(Object.entries(xs.reduce<Record<string, number>>((m, x) => ({ ...m, [x.type]: (m[x.type] ?? 0) + 1 }), {})).sort(([a], [b]) => a.localeCompare(b)));
    const autofit = rs.shapes.filter((s) => s.text?.autofit).reduce<Record<string, number>>((m, s) => ({ ...m, [String(s.text?.autofit)]: (m[String(s.text?.autofit)] ?? 0) + 1 }), {});
    const slideOverflow = overflow.filter((f) => f.slide.startsWith(String(spec.slide).padStart(2, '0'))).map((f) => ({ key: f.key, kind: f.kind, amount: f.amount }));
    results.push({
      slide: spec.slide, kind: spec.kind,
      integral: { diff_share: pct(d(all), all.total_pixels), by_area: Object.fromEntries(Object.entries(area).map(([k, v]) => [k, { area_share: pct(v.pixels, all.total_pixels), diff_share_of_area: pct(v.diff, v.pixels), share_of_all_diff: pct(v.diff, d(all)) }])) },
      geometry, typography, colors,
      charts: { reference: count(refCharts), html: count(hCharts), reference_detail: refCharts, html_detail: hCharts, types_match: JSON.stringify(count(refCharts)) === JSON.stringify(count(hCharts)) },
      distribution, overflow: { html: slideOverflow, reference_autofit: autofit },
    });
  }
  fs.writeFileSync(path.join(OUT, 'integral.json'), JSON.stringify({ generated_at: new Date().toISOString(), threshold: THRESHOLD, template: 'afrika-modelo@2', equalized, slides: results }, null, 2) + '\n');
  const md = ['# Comparação INTEGRAL por categoria — HTML (afrika-modelo@2, conteúdo sintético equivalente) × PowerPoint de referência (local)', '', `Limiar de cor Δ>${THRESHOLD}. Percentuais são MEDIÇÕES; não são prova de fidelidade.`, '',
    '| Slide | Tipo | Dif. total | Ativos (área / dif. / % do total) | Gráficos | Texto | Estrutura | Geometria ok/aprox/div | Tipografia Δpx (máx) | Cores ok | Gráficos (tipos iguais) | Overflow HTML |',
    '|---|---|---|---|---|---|---|---|---|---|---|---|'];
  for (const r of results) {
    const a = r.integral.by_area;
    const g = r.geometry as { class?: string }[];
    const ty = r.typography as { d_size_px: number | null }[];
    const co = r.colors as { match: boolean }[];
    const cell = (k: string) => `${a[k].area_share}% / ${a[k].diff_share_of_area}% / ${a[k].share_of_all_diff}%`;
    md.push(`| ${r.slide} | ${r.kind} | ${r.integral.diff_share}% | ${cell('assets')} | ${cell('charts')} | ${cell('text')} | ${cell('structure')} | ${['ok', 'aprox', 'divergente'].map((c) => g.filter((x) => x.class === c).length).join('/')} | ${ty.length ? Math.max(...ty.map((x) => Math.abs(x.d_size_px ?? 0))) : '—'} | ${co.filter((x) => x.match).length}/${co.length} | ${r.charts.types_match ? 'sim' : 'não'} | ${r.overflow.html.length} |`);
  }
  fs.writeFileSync(path.join(OUT, 'integral.md'), md.join('\n') + '\n');
  expect(results).toHaveLength(16);
});
