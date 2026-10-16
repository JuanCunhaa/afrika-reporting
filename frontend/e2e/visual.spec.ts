import { Page, expect, test } from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { type CapturedSlide, captureSlides } from '../visual/capture';
import { compareImages } from '../visual/diff';
import { compareManifests } from '../visual/manifest';
import { decodePng, encodePng } from '../visual/png';
import { type SlideComparison, type Tolerances, type VisualReport, compareSlide, renderMarkdown, summarize } from '../visual/report';
import { collectOverflow, type OverflowFinding } from '../visual/overflow';
import { afrikaPresentation, afrikaV2Presentation, visualPresentation } from './visual-fixture';
import { ensureAltTheme } from './visual-theme';

// F06B.1 — regressão visual dos slides HTML (fixture SINTÉTICA). Referências por plataforma em
// visual/baselines/<plataforma>/<caso>/ (renderização de fontes difere entre SOs); tolerâncias MEDIDAS em
// visual/tolerances.json. Relatório: test-results/visual/report.{json,md} + PNGs de diferença.
//   VISUAL_UPDATE=1     regrava as referências da plataforma atual (revisar o diff antes de versionar)
//   VISUAL_MEASURE=1    mede o ruído (3 capturas por slide) e grava em tolerances.json para a plataforma atual
//   VISUAL_BOOTSTRAP=1  plataforma sem referência: guarda as capturas como candidatas (sem falhar) — só para criar
//                       a primeira referência de uma plataforma nova (ex.: CI Linux), nunca como modo permanente
const here = path.dirname(fileURLToPath(import.meta.url));
const VISUAL = path.resolve(here, '../visual');
const OUT = path.resolve(here, '../test-results/visual');
const PLATFORM = process.platform;
const TOL_FILE = path.join(VISUAL, 'tolerances.json');

type Case = { name: string; setup: (page: Page) => Promise<string> };
const CASES: Case[] = [
  {
    // Tema demonstrativo neutro da F06A (compatibilidade: a renderização deve permanecer idêntica).
    name: 'neutral-demo',
    setup: (page) => visualPresentation(page.request, 'visual-neutral', { id: 'neutral-demo', version: 1 }, 'Visual — tema neutro (sintético)'),
  },
  {
    // Tema próprio sintético (4:3, regiões fixas, logotipo local, outras fontes): temas diferentes por cliente.
    name: 'alt-fixed-4x3',
    setup: async (page) => visualPresentation(page.request, 'visual-alt', await ensureAltTheme(page.request), 'Visual — tema alternativo (sintético)'),
  },
  {
    // F06B: template embutido afrika-modelo@1 (tema Afrika 1920×1080, 16 slots na sequência da referência), dados sintéticos.
    name: 'afrika',
    setup: (page) => afrikaPresentation(page.request),
  },
  {
    // F06C: afrika-modelo@2 (tema afrika@2: severidade por nível, variação comprovada) com seleção de 8 slots e
    // ativos SINTÉTICOS de marca (foto da capa e logotipo); demais encaixes vazios = fallback neutro.
    name: 'afrika-v2',
    setup: (page) => afrikaV2Presentation(page.request),
  },
];
// F06C: temas cujas fontes vêm empacotadas (OFL): nenhuma fonte de reserva/sistema pode aparecer na renderização
const BUNDLED_FONTS: Record<string, string[]> = { afrika: ['Montserrat', 'Poppins', 'Be Vietnam Pro'], 'afrika-v2': ['Montserrat', 'Poppins', 'Be Vietnam Pro'] };

const readTol = (): Tolerances => JSON.parse(fs.readFileSync(TOL_FILE, 'utf8'));
const baselineDir = (c: string) => path.join(VISUAL, 'baselines', PLATFORM, c);

function loadBaseline(c: string, name: string) {
  const png = path.join(baselineDir(c), `${name}.png`);
  if (!fs.existsSync(png)) return null;
  const json = path.join(baselineDir(c), `${name}.json`);
  return { image: decodePng(fs.readFileSync(png)), manifest: fs.existsSync(json) ? JSON.parse(fs.readFileSync(json, 'utf8')) : null };
}

function save(dir: string, s: CapturedSlide) {
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, `${s.name}.png`), s.png);
  fs.writeFileSync(path.join(dir, `${s.name}.json`), JSON.stringify(s.manifest, null, 2) + '\n');
}

function maxGeometryDelta(a: CapturedSlide, b: CapturedSlide): number {
  const other = new Map(b.manifest.elements.map((e) => [e.key, e]));
  let max = 0;
  for (const e of a.manifest.elements) {
    const o = other.get(e.key);
    if (!o) return Infinity;
    max = Math.max(max, Math.abs(o.box.x - e.box.x), Math.abs(o.box.y - e.box.y), Math.abs(o.box.w - e.box.w), Math.abs(o.box.h - e.box.h));
  }
  return max;
}

test.describe.configure({ mode: 'serial' });

test('regressão visual dos slides (fixture sintética, tolerâncias medidas)', async ({ page, browser, context }) => {
  test.setTimeout(240_000);
  await page.setViewportSize({ width: 1920, height: 1080 });
  const tol = readTol();
  const platformTol = tol.platforms[PLATFORM] ?? null;
  const runs = process.env.VISUAL_MEASURE === '1' ? 3 : 2;
  const slides: SlideComparison[] = [];
  const noise = { runs, max_diff_pixels: 0, max_aa_pixels: 0, max_geometry_delta: 0 };
  const overflow: (OverflowFinding & { case: string })[] = [];
  const fallbackFonts: string[] = [];
  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(OUT, { recursive: true });

  for (const c of CASES) {
    const pid = await c.setup(page);
    const captures: CapturedSlide[][] = [];
    for (let r = 0; r < runs; r++) {
      const p = r === 0 ? page : await context.newPage(); // capturas extras em página nova (sem estado residual)
      if (r) await p.setViewportSize({ width: 1920, height: 1080 });
      captures.push(await captureSlides(p, pid, c.name));
      if (r) await p.close();
    }
    const first = captures[0];
    expect(first.length, 'nenhum slide capturado').toBeGreaterThan(0);
    // F06C: overflow/cortes medidos no DOM da plataforma atual (a página ainda está na rota de render deste caso)
    overflow.push(...(await collectOverflow(page)).map((f) => ({ ...f, case: c.name })));
    const allowed = BUNDLED_FONTS[c.name];
    if (allowed)
      for (const s of first)
        for (const e of s.manifest.elements)
          for (const f of e.platform_fonts ?? []) if (!allowed.some((a) => f.startsWith(a))) fallbackFonts.push(`${c.name}/${s.name}/${e.key}: ${f}`);
    for (const again of captures.slice(1))
      first.forEach((s, k) => {
        const d = compareImages(s.image, again[k].image, { colorThreshold: tol.comparison.color_threshold, detectAntialiasing: tol.comparison.detect_antialiasing });
        noise.max_diff_pixels = Math.max(noise.max_diff_pixels, d.diff_pixels);
        noise.max_aa_pixels = Math.max(noise.max_aa_pixels, d.aa_pixels);
        noise.max_geometry_delta = Math.max(noise.max_geometry_delta, maxGeometryDelta(s, again[k]));
        expect(compareManifests(s.manifest, again[k].manifest, { position: Infinity, size: Infinity }), `${c.name}/${s.name}: manifesto instável entre capturas`).toEqual([]);
      });

    if (process.env.VISUAL_UPDATE === '1') {
      fs.rmSync(baselineDir(c.name), { recursive: true, force: true });
      for (const s of first) save(baselineDir(c.name), s);
      continue;
    }
    for (const s of first) {
      const ref = loadBaseline(c.name, s.name);
      const { result, diffImage } = compareSlide(c.name, s.name, ref, { image: s.image, manifest: s.manifest }, tol, platformTol ?? { max_diff_pixels: 0, max_aa_pixels: 0 });
      if (diffImage) {
        const rel = path.join('diffs', c.name, `${s.name}.diff.png`);
        fs.mkdirSync(path.dirname(path.join(OUT, rel)), { recursive: true });
        fs.writeFileSync(path.join(OUT, rel), encodePng(diffImage));
        result.diff_image = rel.replace(/\\/g, '/');
      }
      if (result.verdict !== 'PASS') save(path.join(OUT, 'candidates', PLATFORM, c.name), s);
      slides.push(result);
    }
  }

  const report: VisualReport = {
    report_version: 1,
    generated_at: new Date().toISOString(),
    environment: {
      platform: PLATFORM,
      os_release: os.release(),
      browser: `${browser.browserType().name()} ${browser.version()}`,
      viewport: '1920×1080 (cada slide capturado no tamanho do canvas do seu tema)',
      device_scale_factor: 1,
      rota: '#/render/{id} (escala 1)',
      node: process.version,
    },
    tolerances: { comparison: tol.comparison, geometry: tol.geometry, platform: PLATFORM, applied: platformTol },
    noise,
    summary: summarize(slides),
    slides,
  };
  // F06C: overflow e fontes de reserva no relatório (mesmo em modo de atualização de referência)
  (report as VisualReport & { overflow: unknown; fallback_fonts: unknown }).overflow = overflow;
  (report as VisualReport & { overflow: unknown; fallback_fonts: unknown }).fallback_fonts = [...new Set(fallbackFonts)];
  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 2) + '\n');
  fs.writeFileSync(path.join(OUT, 'report.md'), renderMarkdown(report));

  if (process.env.VISUAL_MEASURE === '1') {
    tol.platforms[PLATFORM] = {
      max_diff_pixels: noise.max_diff_pixels,
      max_aa_pixels: noise.max_aa_pixels,
      measured_noise: { runs, slides: slides.length || CASES.length, ...noise },
      measured_at: report.generated_at,
      chromium: browser.version(),
      basis: `ruído máximo observado em ${runs} capturas independentes por slide nesta plataforma`,
    };
    fs.writeFileSync(TOL_FILE, JSON.stringify(tol, null, 2) + '\n');
  }
  if (process.env.VISUAL_UPDATE === '1') {
    test.info().annotations.push({ type: 'visual', description: `referências regravadas para ${PLATFORM}` });
    return;
  }

  // Determinismo do ambiente: ruído entre capturas não pode exceder o medido/registrado para a plataforma.
  if (platformTol) {
    expect(noise.max_diff_pixels, 'ruído (pixels diferentes) acima do medido').toBeLessThanOrEqual(platformTol.max_diff_pixels);
    expect(noise.max_aa_pixels, 'ruído (antisserrilhado) acima do medido').toBeLessThanOrEqual(platformTol.max_aa_pixels);
  }
  expect(noise.max_geometry_delta, 'geometria instável entre capturas').toBeLessThanOrEqual(tol.geometry.position);

  const missing = slides.filter((s) => s.verdict === 'BASELINE_MISSING');
  if (missing.length && process.env.VISUAL_BOOTSTRAP === '1') {
    test.info().annotations.push({ type: 'visual', description: `BOOTSTRAP: ${missing.length} slide(s) sem referência para ${PLATFORM}; candidatas em test-results/visual/candidates` });
  } else {
    expect(missing.map((s) => `${s.case}/${s.name}`), `sem referência para ${PLATFORM} (gere com VISUAL_UPDATE=1 e revise)`).toEqual([]);
  }
  // F06C: nada estoura nem é cortado (Windows e Linux: o mesmo teste roda nas duas plataformas)
  expect(overflow.filter((f) => f.kind !== 'ellipsis').map((f) => `${f.case}/${f.slide} ${f.key} ${f.kind} ${f.amount}px`), 'overflow/corte de conteúdo').toEqual([]);
  expect([...new Set(fallbackFonts)], 'fonte de reserva/sistema num tema com fontes empacotadas').toEqual([]);
  const failing = slides.filter((s) => s.verdict === 'FAIL').map((s) => `${s.case}/${s.name}: ${s.reasons.join('; ')}`);
  expect(failing, 'regressão visual — ver test-results/visual/report.md').toEqual([]);
});
