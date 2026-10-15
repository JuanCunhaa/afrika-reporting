// F06B.1 — comparação de um slide (imagem + manifesto) e relatório agregado (JSON + Markdown).
// Veredito por TOLERÂNCIAS MEDIDAS (tolerances.json): contagem absoluta de pixels diferentes/antisserrilhados e
// diferenças semânticas do manifesto. Nenhuma porcentagem é usada como prova de fidelidade.
import { type CompareResult, compareImages } from './diff.ts';
import {
  type AttributedRegion,
  type ElementDiff,
  type GeometryTolerance,
  type SlideManifest,
  attributeRegions,
  compareManifests,
  misalignments,
} from './manifest.ts';
import type { Image } from './png.ts';

export type PlatformTolerance = {
  max_diff_pixels: number;
  max_aa_pixels: number;
  measured_noise?: { runs: number; slides: number; max_diff_pixels: number; max_aa_pixels: number; max_geometry_delta: number };
  measured_at?: string;
  chromium?: string;
  basis?: string;
};
export type Tolerances = {
  tolerance_version: 1;
  comparison: { color_threshold: number; detect_antialiasing: boolean; cell_size: number };
  geometry: GeometryTolerance;
  platforms: Record<string, PlatformTolerance>;
};

export type SlideComparison = {
  case: string;
  name: string;
  verdict: 'PASS' | 'FAIL' | 'BASELINE_MISSING';
  reasons: string[];
  dimensions: { reference: [number, number] | null; candidate: [number, number] };
  pixels: Omit<CompareResult, 'diff_image' | 'regions'> | null;
  regions: AttributedRegion[];
  categories: Record<string, number>; // pixels (diferentes + antisserrilhados) por categoria de região
  element_diffs: ElementDiff[];
  misaligned: ReturnType<typeof misalignments> | null;
  diff_image?: string; // caminho relativo do PNG de diferença (quando há diferença)
};

export function compareSlide(
  caseName: string,
  name: string,
  ref: { image: Image; manifest: SlideManifest | null } | null,
  cand: { image: Image; manifest: SlideManifest | null },
  tol: Tolerances,
  platform: PlatformTolerance,
): { result: SlideComparison; diffImage: Image | null } {
  const dims = { reference: ref ? ([ref.image.width, ref.image.height] as [number, number]) : null, candidate: [cand.image.width, cand.image.height] as [number, number] };
  if (!ref)
    return {
      result: { case: caseName, name, verdict: 'BASELINE_MISSING', reasons: ['sem referência para esta plataforma'], dimensions: dims, pixels: null, regions: [], categories: {}, element_diffs: [], misaligned: null },
      diffImage: null,
    };
  const px = compareImages(ref.image, cand.image, {
    colorThreshold: tol.comparison.color_threshold,
    detectAntialiasing: tol.comparison.detect_antialiasing,
    cellSize: tol.comparison.cell_size,
  });
  const diffs = ref.manifest && cand.manifest ? compareManifests(ref.manifest, cand.manifest, tol.geometry) : [];
  const regions = attributeRegions(px.regions, ref.manifest, cand.manifest, diffs);
  const categories: Record<string, number> = {};
  for (const r of regions) categories[r.category] = (categories[r.category] ?? 0) + r.pixels + r.aa_pixels;
  const reasons: string[] = [];
  if (px.dimension_mismatch) reasons.push(`dimensões diferentes: referência ${dims.reference!.join('×')} × candidato ${dims.candidate.join('×')}`);
  if (px.diff_pixels > platform.max_diff_pixels) reasons.push(`${px.diff_pixels} pixel(s) diferentes > tolerância medida ${platform.max_diff_pixels}`);
  if (px.aa_pixels > platform.max_aa_pixels) reasons.push(`${px.aa_pixels} pixel(s) de antisserrilhado > tolerância medida ${platform.max_aa_pixels}`);
  for (const cat of ['content', 'font', 'layout', 'style'] as const) {
    const n = diffs.filter((d) => d.category === cat).length;
    if (n) reasons.push(`${n} diferença(s) de ${CATEGORY_LABEL[cat]} no manifesto`);
  }
  const { diff_image, regions: _r, ...pixels } = px;
  return {
    result: {
      case: caseName,
      name,
      verdict: reasons.length ? 'FAIL' : 'PASS',
      reasons,
      dimensions: dims,
      pixels,
      regions: regions.slice(0, 50),
      categories,
      element_diffs: diffs,
      misaligned: ref.manifest && cand.manifest ? misalignments(ref.manifest, cand.manifest, tol.geometry) : null,
    },
    diffImage: px.diff_pixels + px.aa_pixels > 0 || px.dimension_mismatch ? diff_image : null,
  };
}

export const CATEGORY_LABEL: Record<string, string> = {
  content: 'conteúdo',
  font: 'fonte',
  layout: 'layout',
  style: 'estilo/cor',
  rendering: 'rasterização (sem mudança semântica)',
  unattributed: 'fora de elementos mapeados',
};

export type VisualReport = {
  report_version: 1;
  generated_at: string;
  environment: Record<string, unknown>;
  tolerances: { comparison: Tolerances['comparison']; geometry: GeometryTolerance; platform: string; applied: PlatformTolerance | null };
  noise: { runs: number; max_diff_pixels: number; max_aa_pixels: number; max_geometry_delta: number } | null;
  summary: { slides: number; pass: number; fail: number; baseline_missing: number };
  slides: SlideComparison[];
};

export function summarize(slides: SlideComparison[]): VisualReport['summary'] {
  return {
    slides: slides.length,
    pass: slides.filter((s) => s.verdict === 'PASS').length,
    fail: slides.filter((s) => s.verdict === 'FAIL').length,
    baseline_missing: slides.filter((s) => s.verdict === 'BASELINE_MISSING').length,
  };
}

export function renderMarkdown(r: VisualReport): string {
  const lines = [
    '# Relatório de regressão visual (sintético)',
    '',
    `Gerado em ${r.generated_at}. Plataforma: \`${r.tolerances.platform}\`.`,
    '',
    '## Ambiente',
    ...Object.entries(r.environment).map(([k, v]) => `- ${k}: \`${typeof v === 'string' ? v : JSON.stringify(v)}\``),
    '',
    '## Tolerâncias aplicadas (medidas — ver docs/VISUAL_REGRESSION.md)',
    `- comparação: limiar de cor ${r.tolerances.comparison.color_threshold}, antisserrilhado separado: ${r.tolerances.comparison.detect_antialiasing ? 'sim' : 'não'}, célula ${r.tolerances.comparison.cell_size}px`,
    `- geometria: posição ±${r.tolerances.geometry.position}px, tamanho ±${r.tolerances.geometry.size}px`,
    r.tolerances.applied
      ? `- pixels: diferentes ≤ ${r.tolerances.applied.max_diff_pixels}, antisserrilhado ≤ ${r.tolerances.applied.max_aa_pixels} (base: ${r.tolerances.applied.basis ?? '—'})`
      : '- pixels: sem tolerância registrada para esta plataforma',
    r.noise
      ? `- ruído medido nesta execução (${r.noise.runs} capturas por slide): diferentes ${r.noise.max_diff_pixels}, antisserrilhado ${r.noise.max_aa_pixels}, geometria ${r.noise.max_geometry_delta}px`
      : '- ruído: não medido',
    '',
    `## Resultado: ${r.summary.pass} PASS · ${r.summary.fail} FAIL · ${r.summary.baseline_missing} sem referência (de ${r.summary.slides})`,
    '',
    '| Caso / slide | Veredito | Dimensões | Pixels dif. | Antisserr. | Categorias | Motivos |',
    '|---|---|---|---|---|---|---|',
  ];
  for (const s of r.slides) {
    const cats = Object.entries(s.categories).map(([k, v]) => `${CATEGORY_LABEL[k] ?? k}: ${v}`).join('; ') || '—';
    lines.push(
      `| ${s.case} / ${s.name} | ${s.verdict} | ${s.dimensions.candidate.join('×')} | ${s.pixels?.diff_pixels ?? '—'} | ${s.pixels?.aa_pixels ?? '—'} | ${cats} | ${s.reasons.join('; ') || '—'} |`,
    );
  }
  const failing = r.slides.filter((s) => s.verdict === 'FAIL');
  if (failing.length) {
    lines.push('', '## Diagnóstico das falhas');
    for (const s of failing) {
      lines.push('', `### ${s.case} / ${s.name}`);
      if (s.diff_image) lines.push(`Imagem de diferença: \`${s.diff_image}\` (vermelho = diferença, amarelo = antisserrilhado).`);
      for (const d of s.element_diffs.slice(0, 20)) lines.push(`- [${CATEGORY_LABEL[d.category]}] \`${d.key}\` ${d.kind} ${JSON.stringify(d.detail)}`);
      for (const m of s.misaligned?.moved.slice(0, 10) ?? []) lines.push(`- desalinhado: \`${m.key}\` dx=${m.dx} dy=${m.dy} dw=${m.dw} dh=${m.dh}`);
      for (const b of s.misaligned?.broken_alignments.slice(0, 10) ?? [])
        lines.push(`- alinhamento rompido (${b.edge}): \`${b.elements[0]}\` × \`${b.elements[1]}\` (${b.reference_gap}px → ${b.candidate_gap}px)`);
      for (const g of s.regions.slice(0, 10))
        lines.push(`- região ${g.x},${g.y} ${g.w}×${g.h}: ${g.pixels} dif. + ${g.aa_pixels} antisserr. · ${CATEGORY_LABEL[g.category]} · ${g.elements.join(', ') || '—'}`);
    }
  }
  return lines.join('\n') + '\n';
}
