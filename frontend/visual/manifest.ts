// F06B.1 — manifesto de layout por slide e diagnóstico semântico das diferenças.
// O manifesto é coletado do DOM renderizado (elementos com `data-el`): caixa no slide, hash do texto (o texto em si
// não é gravado por padrão), fonte declarada/computada, fontes REAIS de plataforma usadas (CDP) e cores.
// Permite separar diferenças de CONTEÚDO (texto/elemento), FONTE (família/tamanho/peso ou fonte de plataforma),
// LAYOUT (posição/tamanho) e ESTILO (cor), e listar elementos desalinhados — além da contagem de pixels.
import type { Box, Region } from './diff.ts';

export type ElementInfo = {
  key: string; // valor de data-el (único no slide; repetições recebem sufixo #n)
  role: string; // parte antes de ':' (title, kpi, chart, footer…)
  box: Box; // px CSS relativos ao canto do slide
  text_hash: string | null;
  text_length: number;
  font: { family: string; size: number; weight: string; style: string } | null;
  platform_fonts: string[] | null; // fontes efetivamente usadas pelo Chromium (CSS.getPlatformFontsForNode)
  color: string | null;
  background: string | null;
};

export type SlideManifest = {
  manifest_version: 1;
  case: string;
  slide: { index: number; slide_id: string; type: string; layout: string };
  canvas: { width: number; height: number };
  theme: { id: string; version: number } | null;
  elements: ElementInfo[];
};

export type Category = 'content' | 'font' | 'layout' | 'style';
export type ElementDiff = {
  key: string;
  kind: 'missing' | 'added' | 'moved' | 'resized' | 'text' | 'font' | 'platform_font' | 'color';
  category: Category;
  detail: Record<string, unknown>;
};
export type GeometryTolerance = { position: number; size: number };
export const PRIORITY: Category[] = ['content', 'font', 'layout', 'style'];

const round = (n: number) => Math.round(n * 100) / 100;

export function compareManifests(ref: SlideManifest, cand: SlideManifest, tol: GeometryTolerance): ElementDiff[] {
  const out: ElementDiff[] = [];
  const r = new Map(ref.elements.map((e) => [e.key, e]));
  const c = new Map(cand.elements.map((e) => [e.key, e]));
  for (const [key, a] of r) {
    const b = c.get(key);
    if (!b) {
      out.push({ key, kind: 'missing', category: 'content', detail: { box: a.box } });
      continue;
    }
    if (a.text_hash !== b.text_hash)
      out.push({ key, kind: 'text', category: 'content', detail: { reference_length: a.text_length, candidate_length: b.text_length } });
    if (a.font && b.font && (a.font.family !== b.font.family || a.font.size !== b.font.size || a.font.weight !== b.font.weight || a.font.style !== b.font.style))
      out.push({ key, kind: 'font', category: 'font', detail: { reference: a.font, candidate: b.font } });
    const pa = (a.platform_fonts ?? []).join(', ');
    const pb = (b.platform_fonts ?? []).join(', ');
    if (a.platform_fonts && b.platform_fonts && pa !== pb)
      out.push({ key, kind: 'platform_font', category: 'font', detail: { reference: a.platform_fonts, candidate: b.platform_fonts } });
    const dx = round(b.box.x - a.box.x), dy = round(b.box.y - a.box.y);
    const dw = round(b.box.w - a.box.w), dh = round(b.box.h - a.box.h);
    if (Math.abs(dx) > tol.position || Math.abs(dy) > tol.position) out.push({ key, kind: 'moved', category: 'layout', detail: { dx, dy } });
    if (Math.abs(dw) > tol.size || Math.abs(dh) > tol.size) out.push({ key, kind: 'resized', category: 'layout', detail: { dw, dh } });
    if (a.color !== b.color || a.background !== b.background)
      out.push({ key, kind: 'color', category: 'style', detail: { reference: [a.color, a.background], candidate: [b.color, b.background] } });
  }
  for (const [key, b] of c) if (!r.has(key)) out.push({ key, kind: 'added', category: 'content', detail: { box: b.box } });
  return out;
}

/** Elementos desalinhados: deslocamento individual + quebra de alinhamento entre elementos que compartilhavam borda. */
export function misalignments(ref: SlideManifest, cand: SlideManifest, tol: GeometryTolerance) {
  const c = new Map(cand.elements.map((e) => [e.key, e]));
  const shared = ref.elements.filter((e) => c.has(e.key));
  const moved = shared
    .map((a) => {
      const b = c.get(a.key)!;
      return { key: a.key, dx: round(b.box.x - a.box.x), dy: round(b.box.y - a.box.y), dw: round(b.box.w - a.box.w), dh: round(b.box.h - a.box.h) };
    })
    .filter((m) => Math.abs(m.dx) > tol.position || Math.abs(m.dy) > tol.position || Math.abs(m.dw) > tol.size || Math.abs(m.dh) > tol.size)
    .sort((m, n) => Math.max(Math.abs(n.dx), Math.abs(n.dy)) - Math.max(Math.abs(m.dx), Math.abs(m.dy)));
  const edges: Record<string, (b: Box) => number> = {
    left: (b) => b.x,
    top: (b) => b.y,
    right: (b) => b.x + b.w,
    bottom: (b) => b.y + b.h,
  };
  const broken: { edge: string; elements: [string, string]; reference_gap: number; candidate_gap: number }[] = [];
  for (const [edge, f] of Object.entries(edges))
    for (let i = 0; i < shared.length; i++)
      for (let j = i + 1; j < shared.length; j++) {
        const a = shared[i], b = shared[j];
        const refGap = Math.abs(f(a.box) - f(b.box));
        if (refGap > 0.5) continue; // não estavam alinhados na referência
        const candGap = Math.abs(f(c.get(a.key)!.box) - f(c.get(b.key)!.box));
        if (Math.abs(candGap - refGap) > tol.position) broken.push({ edge, elements: [a.key, b.key], reference_gap: round(refGap), candidate_gap: round(candGap) });
      }
  return { moved, broken_alignments: broken.slice(0, 50) };
}

const intersects = (a: Box, b: Box) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
const area = (b: Box) => b.w * b.h;

export type RegionCategory = Category | 'rendering' | 'unattributed';
export type AttributedRegion = Region & { category: RegionCategory; elements: string[] };

/**
 * Atribui cada região de pixels diferentes aos elementos que a intersectam (referência ∪ candidato). Categoria da
 * região = a de maior prioridade entre as diferenças desses elementos (conteúdo > fonte > layout > estilo); elementos
 * sem diferença no manifesto => `rendering` (rasterização/antisserrilhado/subpixel); fora de qualquer elemento =>
 * `unattributed`.
 */
export function attributeRegions(regions: Region[], ref: SlideManifest | null, cand: SlideManifest | null, diffs: ElementDiff[]): AttributedRegion[] {
  const elements = [...(ref?.elements ?? []), ...(cand?.elements ?? [])];
  const byKey = new Map<string, ElementDiff[]>();
  for (const d of diffs) byKey.set(d.key, [...(byKey.get(d.key) ?? []), d]);
  return regions.map((reg) => {
    const hit = elements.filter((e) => intersects(e.box, reg));
    const keys = [...new Set(hit.sort((a, b) => area(a.box) - area(b.box)).map((e) => e.key))];
    let category: RegionCategory = keys.length ? 'rendering' : 'unattributed';
    for (const cat of PRIORITY) {
      if (keys.some((k) => (byKey.get(k) ?? []).some((d) => d.category === cat))) {
        category = cat;
        break;
      }
    }
    return { ...reg, category, elements: keys.slice(0, 8) };
  });
}
