import { expect, test } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { captureSlides } from '../visual/capture';
import { type Box, compareImages } from '../visual/diff';
import type { ElementInfo } from '../visual/manifest';
import { type Image, decodePng, encodePng } from '../visual/png';
import { afrikaPresentation } from './visual-fixture';

// F06B — comparação POR SLIDE do template HTML afrika-modelo@1 (dados SINTÉTICOS) com a renderização LOCAL do
// PowerPoint de referência. Só roda na máquina que tem o arquivo (no CI é pulada):
//   AFRIKA_REFERENCE_RENDER = pasta com slideNN.png (scripts/render_reference.ps1, em private/)
//   AFRIKA_REFERENCE_REPORT = report.json da inspeção local em modo strict (app.cli inspect-pptx)
// O conteúdo (textos, números, tabelas, gráficos, imagens) é DIFERENTE por definição (real × sintético) e é
// MASCARADO dos dois lados: mede-se a estrutura visual (fundos, faixas, cartões, formas, posições). A saída é só
// numérica, em output/reference-compare/ (ignorado pelo Git); os PNGs de diferença contêm a referência e ficam locais.
const RENDER = process.env.AFRIKA_REFERENCE_RENDER;
const REPORT = process.env.AFRIKA_REFERENCE_REPORT;
const here = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(here, '../../output/reference-compare');
const MAP = JSON.parse(fs.readFileSync(path.resolve(here, '../visual/reference-map.json'), 'utf8')) as {
  slides: { slide: number; kind: string; pairs: { what: string; ref: number[]; html: string; text?: boolean }[] }[];
};
const THRESHOLDS = [0.03, 0.08, 0.15];

type RefShape = { n: number; kind: string; depth?: number; box_px?: Box | null; text?: { characters: number } | null; table?: unknown; chart?: unknown };

const union = (boxes: Box[]): Box => {
  const x0 = Math.min(...boxes.map((b) => b.x)), y0 = Math.min(...boxes.map((b) => b.y));
  const x1 = Math.max(...boxes.map((b) => b.x + b.w)), y1 = Math.max(...boxes.map((b) => b.y + b.h));
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
};
const inside = (a: Box, b: Box) => a.x >= b.x - 0.5 && a.y >= b.y - 0.5 && a.x + a.w <= b.x + b.w + 0.5 && a.y + a.h <= b.y + b.h + 0.5;
const r1 = (n: number) => Math.round(n * 10) / 10;

/** Máscara da referência: toda forma com texto, tabela/gráfico e imagem (conteúdo real). */
function refMask(shapes: RefShape[]): Box[] {
  return shapes.filter((s) => s.box_px && s.kind !== 'group' && ((s.text?.characters ?? 0) > 0 || s.kind === 'frame' || s.kind === 'picture')).map((s) => s.box_px as Box);
}

/** Máscara do HTML: elementos de texto "folha" (sem outro elemento de texto dentro) + desenhos de gráfico. */
function htmlMask(elements: ElementInfo[]): Box[] {
  const texty = elements.filter((e) => e.text_length > 0 || ['plot', 'donut', 'slice'].includes(e.role));
  return texty.filter((e) => ['plot', 'donut'].includes(e.role) || !texty.some((o) => o !== e && o.text_length > 0 && inside(o.box, e.box) && (o.box.w < e.box.w || o.box.h < e.box.h))).map((e) => e.box);
}

function dominant(img: Image, mask: Box[], top = 3): { color: string; share: number }[] {
  const masked = new Uint8Array(img.width * img.height);
  for (const b of mask) for (let y = Math.max(0, Math.floor(b.y)); y < Math.min(img.height, Math.ceil(b.y + b.h)); y++) masked.fill(1, y * img.width + Math.max(0, Math.floor(b.x)), y * img.width + Math.min(img.width, Math.ceil(b.x + b.w)));
  const bins = new Map<number, number>();
  let n = 0;
  for (let i = 0; i < img.width * img.height; i += 3) {
    if (masked[i]) continue;
    const o = i * 4;
    const key = ((img.data[o] >> 4) << 8) | ((img.data[o + 1] >> 4) << 4) | (img.data[o + 2] >> 4);
    bins.set(key, (bins.get(key) ?? 0) + 1);
    n++;
  }
  return [...bins.entries()].sort((a, b) => b[1] - a[1]).slice(0, top).map(([k, c]) => ({
    color: '#' + [k >> 8, (k >> 4) & 15, k & 15].map((v) => (v * 16 + 8).toString(16).padStart(2, '0')).join('').toUpperCase(),
    share: Math.round((c / Math.max(1, n)) * 1000) / 10,
  }));
}

test('comparação por slide com a renderização local do PowerPoint de referência', async ({ page }) => {
  test.skip(!RENDER || !REPORT, 'comparação com a referência real só roda localmente (arquivo não existe no CI)');
  test.setTimeout(300_000);
  await page.setViewportSize({ width: 1920, height: 1080 });
  const report = JSON.parse(fs.readFileSync(REPORT as string, 'utf8'));
  expect(report.privacy, 'use o relatório em modo strict').toBe('strict');
  const pid = await afrikaPresentation(page.request);
  const slides = await captureSlides(page, pid, 'afrika-referencia');
  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(path.join(OUT, 'diffs'), { recursive: true });
  fs.mkdirSync(path.join(OUT, 'html'), { recursive: true });
  slides.forEach((s, i) => fs.writeFileSync(path.join(OUT, 'html', `slide${String(i + 1).padStart(2, '0')}.png`), encodePng(s.image)));
  const results = [];
  for (const spec of MAP.slides) {
    const html = slides[spec.slide - 1];
    const refPng = path.join(RENDER as string, `slide${String(spec.slide).padStart(2, '0')}.png`);
    const ref = decodePng(fs.readFileSync(refPng));
    const shapes: RefShape[] = report.slides[spec.slide - 1].shapes;
    const mask = [...refMask(shapes), ...htmlMask(html.manifest.elements)];
    const byThreshold = THRESHOLDS.map((t) => {
      const r = compareImages(ref, html.image, { colorThreshold: t, mask });
      const unmasked = r.total_pixels - r.masked_pixels;
      if (t === 0.08 && r.diff_image) fs.writeFileSync(path.join(OUT, 'diffs', `slide${String(spec.slide).padStart(2, '0')}.png`), encodePng(r.diff_image));
      return { threshold: t, unmasked_pixels: unmasked, masked_share: r1((r.masked_pixels / r.total_pixels) * 100), diff_share: r1(((r.diff_pixels + r.aa_pixels) / Math.max(1, unmasked)) * 100), regions: r.regions.slice(0, 5).map((g) => ({ ...g, html_elements: html.manifest.elements.filter((e) => e.box.x < g.x + g.w && g.x < e.box.x + e.box.w && e.box.y < g.y + g.h && g.y < e.box.y + e.box.h).sort((a, b) => a.box.w * a.box.h - b.box.w * b.box.h).slice(0, 3).map((e) => e.key) })) };
    });
    const elements = new Map(html.manifest.elements.map((e) => [e.key, e]));
    const pairs = spec.pairs.map((p) => {
      const refBoxes = p.ref.map((n) => shapes.find((s) => s.n === n)?.box_px).filter(Boolean) as Box[];
      const el = elements.get(p.html);
      if (!refBoxes.length || !el) return { what: p.what, html: p.html, status: !el ? 'html_ausente' : 'ref_ausente' };
      const rb = union(refBoxes), hb = el.box;
      return {
        what: p.what, html: p.html, text: !!p.text, status: 'ok',
        ref_box: { x: r1(rb.x), y: r1(rb.y), w: r1(rb.w), h: r1(rb.h) }, html_box: { x: r1(hb.x), y: r1(hb.y), w: r1(hb.w), h: r1(hb.h) },
        d_center: [r1(hb.x + hb.w / 2 - (rb.x + rb.w / 2)), r1(hb.y + hb.h / 2 - (rb.y + rb.h / 2))],
        d_size: [r1(hb.w - rb.w), r1(hb.h - rb.h)],
      };
    });
    results.push({ slide: spec.slide, kind: spec.kind, html_slide: html.name, dimensions: { reference: [ref.width, ref.height], html: [html.image.width, html.image.height] }, pixels: byThreshold, dominant_colors: { reference: dominant(ref, mask), html: dominant(html.image, mask) }, geometry: pairs });
  }
  const md = ['# Comparação por slide — HTML (afrika-modelo@1, dados sintéticos) × PowerPoint de referência (local)', '', 'Conteúdo mascarado dos dois lados; percentuais são MEDIÇÕES da estrutura visual, não prova de fidelidade.', '', '| Slide | Tipo | Mascarado | Dif. Δ>0,03 | Dif. Δ>0,08 | Dif. Δ>0,15 | Cores dominantes (ref → HTML) |', '|---|---|---|---|---|---|---|'];
  for (const r of results)
    md.push(`| ${r.slide} | ${r.kind} | ${r.pixels[0].masked_share}% | ${r.pixels[0].diff_share}% | ${r.pixels[1].diff_share}% | ${r.pixels[2].diff_share}% | ${r.dominant_colors.reference.map((c) => `${c.color} ${c.share}%`).join(', ')} → ${r.dominant_colors.html.map((c) => `${c.color} ${c.share}%`).join(', ')} |`);
  md.push('', '## Geometria dos pares mapeados (px; Δcentro e Δtamanho; em texto vale o centro)', '', '| Slide | Elemento | Ref (x,y,w,h) | HTML (x,y,w,h) | Δcentro | Δtamanho |', '|---|---|---|---|---|---|');
  for (const r of results)
    for (const g of r.geometry as { what: string; status: string; ref_box?: Box; html_box?: Box; d_center?: number[]; d_size?: number[]; text?: boolean }[])
      md.push(g.status !== 'ok' ? `| ${r.slide} | ${g.what} | — | — | ${g.status} | — |` : `| ${r.slide} | ${g.what}${g.text ? ' (texto)' : ''} | ${[g.ref_box!.x, g.ref_box!.y, g.ref_box!.w, g.ref_box!.h].join(', ')} | ${[g.html_box!.x, g.html_box!.y, g.html_box!.w, g.html_box!.h].join(', ')} | ${g.d_center!.join(', ')} | ${g.d_size!.join(', ')} |`);
  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify({ generated_at: new Date().toISOString(), thresholds: THRESHOLDS, slides: results }, null, 2) + '\n');
  fs.writeFileSync(path.join(OUT, 'report.md'), md.join('\n') + '\n');
  expect(results).toHaveLength(16);
});
