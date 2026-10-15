// F06B.1 — testes do motor de comparação visual (node:test, imagens e manifestos SINTÉTICOS gerados aqui).
// Executar: npm run test:visual-unit
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { compareImages } from './diff.ts';
import { type ElementInfo, type SlideManifest, attributeRegions, compareManifests, misalignments } from './manifest.ts';
import { PngError, blankImage, buildPng, decodePng, encodePng, type Image } from './png.ts';
import { type Tolerances, compareSlide, renderMarkdown, summarize } from './report.ts';

function rect(img: Image, x: number, y: number, w: number, h: number, rgba: [number, number, number, number]) {
  for (let j = y; j < y + h; j++) for (let i = x; i < x + w; i++) img.data.set(rgba, (j * img.width + i) * 4);
}
const BLACK: [number, number, number, number] = [0, 0, 0, 255];

test('PNG: codificar e decodificar preserva cada pixel (RGBA)', () => {
  const img = blankImage(37, 19);
  for (let i = 0; i < img.data.length; i++) img.data[i] = (i * 37 + (i >> 5)) & 0xff;
  const back = decodePng(encodePng(img));
  assert.equal(back.width, 37);
  assert.equal(back.height, 19);
  assert.deepEqual(back.data, img.data);
});

test('PNG: decodifica paleta, cinza, RGB com filtro Up e recusa entrelaçado/não PNG', () => {
  const pal = decodePng(buildPng({ width: 2, height: 1, colorType: 3, depth: 8, lines: new Uint8Array([0, 1]), palette: new Uint8Array([255, 0, 0, 0, 0, 255]), trns: new Uint8Array([128]) }));
  assert.deepEqual([...pal.data], [255, 0, 0, 128, 0, 0, 255, 255]);
  const pal4 = decodePng(buildPng({ width: 3, height: 1, colorType: 3, depth: 4, lines: new Uint8Array([0x10, 0x10]), palette: new Uint8Array([9, 9, 9, 200, 100, 50]) }));
  assert.deepEqual([...pal4.data.subarray(0, 8)], [200, 100, 50, 255, 9, 9, 9, 255]);
  const gray = decodePng(buildPng({ width: 2, height: 2, colorType: 0, depth: 8, lines: new Uint8Array([0, 255, 128, 64]), filter: 2 }));
  assert.deepEqual([...gray.data.subarray(8, 12)], [128, 128, 128, 255]);
  const rgb = decodePng(buildPng({ width: 1, height: 2, colorType: 2, depth: 8, lines: new Uint8Array([10, 20, 30, 40, 50, 60]), filter: 2 }));
  assert.deepEqual([...rgb.data], [10, 20, 30, 255, 40, 50, 60, 255]);
  const interlaced = buildPng({ width: 1, height: 1, colorType: 0, depth: 8, lines: new Uint8Array([1]) });
  interlaced[8 + 8 + 12] = 1; // byte de entrelaçamento do IHDR (CRC passa a divergir; o decodificador não depende dele)
  assert.throws(() => decodePng(interlaced), PngError);
  assert.throws(() => decodePng(new Uint8Array([1, 2, 3])), /não é PNG/);
});

test('imagens idênticas: zero diferença e nenhuma região', () => {
  const a = blankImage(64, 32);
  rect(a, 4, 4, 10, 10, BLACK);
  const r = compareImages(a, decodePng(encodePng(a)));
  assert.equal(r.diff_pixels, 0);
  assert.equal(r.aa_pixels, 0);
  assert.equal(r.identical_pixels, 64 * 32);
  assert.equal(r.regions.length, 0);
});

test('forma deslocada: contagem exata de pixels e região delimitada', () => {
  const a = blankImage(100, 60), b = blankImage(100, 60);
  rect(a, 10, 10, 20, 20, BLACK);
  rect(b, 14, 10, 20, 20, BLACK); // deslocada 4px à direita: 4 colunas somem + 4 aparecem
  const r = compareImages(a, b, { detectAntialiasing: false });
  assert.equal(r.diff_pixels, 2 * 4 * 20);
  assert.equal(r.regions.length, 1);
  const g = r.regions[0];
  assert.ok(g.x <= 10 && g.x + g.w >= 34 && g.y <= 10 && g.y + g.h >= 30, JSON.stringify(g));
  assert.ok(r.diff_image);
});

test('antisserrilhado é contado à parte (não some do relatório)', () => {
  const a = blankImage(40, 40), b = blankImage(40, 40);
  rect(a, 10, 10, 10, 10, BLACK);
  rect(b, 10, 10, 10, 10, BLACK);
  // borda suavizada só no candidato: coluna intermediária cinza entre o preto e o branco
  for (let y = 12; y < 18; y++) b.data.set([128, 128, 128, 255], (y * 40 + 20) * 4);
  const r = compareImages(a, b);
  assert.equal(r.aa_pixels, 6);
  assert.equal(r.diff_pixels, 0);
  const strict = compareImages(a, b, { detectAntialiasing: false });
  assert.equal(strict.diff_pixels, 6);
});

test('limiar de cor: variação abaixo do limiar não conta; acima conta', () => {
  const a = blankImage(10, 10, [100, 100, 100, 255]);
  const b = blankImage(10, 10, [101, 100, 100, 255]);
  assert.equal(compareImages(a, b, { colorThreshold: 0, detectAntialiasing: false }).diff_pixels, 100);
  assert.equal(compareImages(a, b, { colorThreshold: 0.05, detectAntialiasing: false }).diff_pixels, 0);
  const c = blankImage(10, 10, [200, 100, 100, 255]);
  assert.equal(compareImages(a, c, { colorThreshold: 0.05, detectAntialiasing: false }).diff_pixels, 100);
});

test('dimensões diferentes são reportadas sem comparação por pixel', () => {
  const r = compareImages(blankImage(10, 10), blankImage(12, 10));
  assert.deepEqual(r.dimension_mismatch, { reference: [10, 10], candidate: [12, 10] });
  assert.equal(r.diff_image, null);
});

const el = (key: string, box: ElementInfo['box'], over: Partial<ElementInfo> = {}): ElementInfo => ({
  key,
  role: key.split(':')[0],
  box,
  text_hash: `h-${key}`,
  text_length: 5,
  font: { family: 'Sintética', size: 20, weight: '400', style: 'normal' },
  platform_fonts: ['Sintética'],
  color: 'rgb(0, 0, 0)',
  background: null,
  ...over,
});
const manifest = (elements: ElementInfo[]): SlideManifest => ({
  manifest_version: 1,
  case: 'teste',
  slide: { index: 1, slide_id: 's', type: 'kpis', layout: 'kpi-grid' },
  canvas: { width: 100, height: 60 },
  theme: { id: 't', version: 1 },
  elements,
});

test('manifesto separa conteúdo, fonte, layout e estilo', () => {
  const ref = manifest([
    el('title', { x: 10, y: 10, w: 50, h: 10 }),
    el('kpi:a', { x: 10, y: 30, w: 20, h: 20 }),
    el('kpi:b', { x: 40, y: 30, w: 20, h: 20 }),
    el('footer', { x: 0, y: 55, w: 100, h: 5 }),
  ]);
  const cand = manifest([
    el('title', { x: 10, y: 10, w: 50, h: 10 }, { text_hash: 'outro' }),
    el('kpi:a', { x: 13, y: 30, w: 20, h: 20 }),
    el('kpi:b', { x: 40, y: 30, w: 20, h: 20 }, { platform_fonts: ['Fallback'] }),
    el('logo', { x: 90, y: 0, w: 10, h: 10 }),
  ]);
  const d = compareManifests(ref, cand, { position: 0.5, size: 0.5 });
  const kinds = Object.fromEntries(d.map((x) => [`${x.key}/${x.kind}`, x.category]));
  assert.deepEqual(kinds, {
    'title/text': 'content',
    'kpi:a/moved': 'layout',
    'kpi:b/platform_font': 'font',
    'footer/missing': 'content',
    'logo/added': 'content',
  });
  const style = compareManifests(ref, manifest([...cand.elements.slice(0, 3), el('footer', { x: 0, y: 55, w: 100, h: 5 }, { color: 'rgb(9, 9, 9)' })]), { position: 0.5, size: 0.5 });
  assert.ok(style.some((x) => x.key === 'footer' && x.category === 'style'));
});

test('desalinhamento: deslocamento individual e alinhamento rompido', () => {
  const ref = manifest([el('kpi:a', { x: 10, y: 30, w: 20, h: 20 }), el('kpi:b', { x: 40, y: 30, w: 20, h: 20 })]);
  const cand = manifest([el('kpi:a', { x: 10, y: 30, w: 20, h: 20 }), el('kpi:b', { x: 40, y: 33, w: 20, h: 20 })]);
  const m = misalignments(ref, cand, { position: 0.5, size: 0.5 });
  assert.deepEqual(m.moved, [{ key: 'kpi:b', dx: 0, dy: 3, dw: 0, dh: 0 }]);
  assert.ok(m.broken_alignments.some((b) => b.edge === 'top' && b.candidate_gap === 3));
  // folga de subpixel que não mudou não é alinhamento rompido
  const half = manifest([el('kpi:a', { x: 10, y: 30, w: 20, h: 20 }), el('kpi:b', { x: 40, y: 30.5, w: 20, h: 20 })]);
  assert.deepEqual(misalignments(half, half, { position: 0, size: 0 }).broken_alignments, []);
});

test('regiões herdam a categoria do elemento; sem diferença semântica = rasterização; fora = não atribuída', () => {
  const ref = manifest([el('kpi:a', { x: 0, y: 0, w: 30, h: 30 }), el('kpi:b', { x: 50, y: 0, w: 30, h: 30 })]);
  const cand = manifest([el('kpi:a', { x: 0, y: 0, w: 30, h: 30 }, { font: { family: 'X', size: 21, weight: '400', style: 'normal' } }), el('kpi:b', { x: 50, y: 0, w: 30, h: 30 })]);
  const diffs = compareManifests(ref, cand, { position: 0.5, size: 0.5 });
  const regs = attributeRegions(
    [
      { x: 5, y: 5, w: 10, h: 10, pixels: 9, aa_pixels: 1 },
      { x: 55, y: 5, w: 10, h: 10, pixels: 0, aa_pixels: 4 },
      { x: 90, y: 40, w: 5, h: 5, pixels: 2, aa_pixels: 0 },
    ],
    ref,
    cand,
    diffs,
  );
  assert.deepEqual(regs.map((r) => r.category), ['font', 'rendering', 'unattributed']);
});

const TOL: Tolerances = {
  tolerance_version: 1,
  comparison: { color_threshold: 0, detect_antialiasing: true, cell_size: 16 },
  geometry: { position: 0, size: 0 },
  platforms: { test: { max_diff_pixels: 0, max_aa_pixels: 0 } },
};

test('veredito por tolerância medida: PASS, FAIL com motivos e sem referência', () => {
  const a = blankImage(50, 50);
  const b = blankImage(50, 50);
  rect(b, 0, 0, 2, 2, BLACK);
  const m = manifest([el('title', { x: 0, y: 0, w: 10, h: 10 })]);
  const ok = compareSlide('c', 's1', { image: a, manifest: m }, { image: a, manifest: m }, TOL, TOL.platforms.test);
  assert.equal(ok.result.verdict, 'PASS');
  assert.equal(ok.diffImage, null);
  const bad = compareSlide('c', 's2', { image: a, manifest: m }, { image: b, manifest: m }, TOL, TOL.platforms.test);
  assert.equal(bad.result.verdict, 'FAIL');
  assert.match(bad.result.reasons.join(' '), /pixel\(s\) diferentes > tolerância medida 0/);
  assert.ok(bad.diffImage);
  const loose = compareSlide('c', 's3', { image: a, manifest: m }, { image: b, manifest: m }, TOL, { max_diff_pixels: 4, max_aa_pixels: 0 });
  assert.equal(loose.result.verdict, 'PASS');
  const missing = compareSlide('c', 's4', null, { image: a, manifest: m }, TOL, TOL.platforms.test);
  assert.equal(missing.result.verdict, 'BASELINE_MISSING');
  const md = renderMarkdown({
    report_version: 1,
    generated_at: 'agora',
    environment: { os: 'teste' },
    tolerances: { comparison: TOL.comparison, geometry: TOL.geometry, platform: 'test', applied: TOL.platforms.test },
    noise: { runs: 2, max_diff_pixels: 0, max_aa_pixels: 0, max_geometry_delta: 0 },
    summary: summarize([ok.result, bad.result, missing.result]),
    slides: [ok.result, bad.result, missing.result],
  });
  assert.match(md, /1 PASS · 1 FAIL · 1 sem referência/);
  assert.match(md, /Diagnóstico das falhas/);
});
