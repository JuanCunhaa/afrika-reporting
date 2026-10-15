// F06B.1 — comparação por imagem (implementação própria, sem dependências).
// - Diferença de cor perceptual no espaço YIQ (coeficientes de Kotsarenko & Ramos, "Measuring perceived color
//   difference using YIQ NTSC transmission color space"), com composição sobre fundo branco quando há alfa.
// - Pixel de antisserrilhado (borda de texto/forma) detectado pela heurística de vizinhança descrita por Vysniauskas
//   ("Anti-aliased pixel and intensity slope detector"): é contado À PARTE, nunca escondido.
// - Regiões: células de 16 px com diferença, agrupadas por vizinhança (componentes conexos) => caixas delimitadoras.
// Nada aqui decide "fidelidade" por porcentagem: o relatório traz contagens absolutas, e a aprovação usa tolerâncias
// MEDIDAS (ver tolerances.json e docs/VISUAL_REGRESSION.md).
import { type Image, blankImage } from './png.ts';

export type Box = { x: number; y: number; w: number; h: number };
export type Region = Box & { pixels: number; aa_pixels: number };
export type CompareOptions = {
  /** 0 = qualquer diferença de cor conta; (0,1] = limiar perceptual YIQ normalizado. */
  colorThreshold?: number;
  /** separa pixels de antisserrilhado (contados em `aa_pixels`, não em `diff_pixels`). */
  detectAntialiasing?: boolean;
  cellSize?: number;
  maxRegions?: number;
};
export type CompareResult = {
  width: number;
  height: number;
  dimension_mismatch: null | { reference: [number, number]; candidate: [number, number] };
  total_pixels: number;
  identical_pixels: number;
  diff_pixels: number; // diferenças acima do limiar que NÃO são antisserrilhado
  aa_pixels: number; // diferenças classificadas como antisserrilhado
  max_delta: number; // maior delta YIQ normalizado [0,1] observado
  regions: Region[];
  regions_truncated: boolean;
  diff_image: Image | null;
};

const MAX_YIQ_DELTA = 35215; // delta máximo possível entre preto e branco com os coeficientes abaixo

function blend(c: number, a: number): number {
  return 255 + ((c - 255) * a) / 255;
}

function rgbAt(d: Uint8Array, i: number): [number, number, number] {
  const a = d[i + 3];
  return a === 255 ? [d[i], d[i + 1], d[i + 2]] : [blend(d[i], a), blend(d[i + 1], a), blend(d[i + 2], a)];
}

const Y = (r: number, g: number, b: number) => r * 0.29889531 + g * 0.58662247 + b * 0.11448223;
const I = (r: number, g: number, b: number) => r * 0.59597799 - g * 0.2741761 - b * 0.32180189;
const Q = (r: number, g: number, b: number) => r * 0.21147017 - g * 0.52261711 + b * 0.31114694;

/** Delta YIQ entre o pixel i de `a` e o pixel j de `b` (0..MAX_YIQ_DELTA). */
function yiqDelta(a: Uint8Array, i: number, b: Uint8Array, j: number): number {
  const [r1, g1, b1] = rgbAt(a, i);
  const [r2, g2, b2] = rgbAt(b, j);
  const dy = Y(r1, g1, b1) - Y(r2, g2, b2);
  const di = I(r1, g1, b1) - I(r2, g2, b2);
  const dq = Q(r1, g1, b1) - Q(r2, g2, b2);
  return 0.5053 * dy * dy + 0.299 * di * di + 0.1957 * dq * dq;
}

function brightness(d: Uint8Array, i: number): number {
  const [r, g, b] = rgbAt(d, i);
  return Y(r, g, b);
}

function samePixel(d: Uint8Array, i: number, j: number): boolean {
  return d[i] === d[j] && d[i + 1] === d[j + 1] && d[i + 2] === d[j + 2] && d[i + 3] === d[j + 3];
}

/** Quantos vizinhos (8-vizinhança) têm exatamente a mesma cor do pixel (x, y). */
function identicalNeighbours(img: Image, x: number, y: number): number {
  const { width, height, data } = img;
  const c = (y * width + x) * 4;
  let n = 0;
  for (let dy = -1; dy <= 1; dy++)
    for (let dx = -1; dx <= 1; dx++) {
      if (!dx && !dy) continue;
      const nx = x + dx, ny = y + dy;
      if (nx < 0 || ny < 0 || nx >= width || ny >= height) continue;
      if (samePixel(data, c, (ny * width + nx) * 4)) n++;
    }
  return n;
}

/**
 * O pixel (x, y) de `img` parece antisserrilhado? Critério: tem no máximo 2 vizinhos idênticos (não está numa área
 * chapada), possui vizinho mais escuro E mais claro (está "entre" duas cores) e esses dois vizinhos extremos estão em
 * áreas chapadas (≥ 3 vizinhos idênticos) em AMBAS as imagens — padrão típico da borda suavizada de texto/forma.
 */
function antialiased(img: Image, x: number, y: number, other: Image): boolean {
  const { width, height, data } = img;
  const c = (y * width + x) * 4;
  const center = brightness(data, c);
  let zeroes = 0;
  let min = 0, max = 0;
  let minX = -1, minY = -1, maxX = -1, maxY = -1;
  for (let dy = -1; dy <= 1; dy++)
    for (let dx = -1; dx <= 1; dx++) {
      if (!dx && !dy) continue;
      const nx = x + dx, ny = y + dy;
      if (nx < 0 || ny < 0 || nx >= width || ny >= height) {
        zeroes++; // borda da imagem conta como vizinho igual (evita falso positivo nas margens)
        continue;
      }
      const delta = brightness(data, (ny * width + nx) * 4) - center;
      if (delta === 0) {
        if (++zeroes > 2) return false;
      } else if (delta < min) {
        min = delta;
        minX = nx;
        minY = ny;
      } else if (delta > max) {
        max = delta;
        maxX = nx;
        maxY = ny;
      }
    }
  if (min === 0 || max === 0) return false;
  const flat = (im: Image, px: number, py: number) => identicalNeighbours(im, px, py) >= 3;
  return (flat(img, minX, minY) && flat(other, minX, minY)) || (flat(img, maxX, maxY) && flat(other, maxX, maxY));
}

export function compareImages(ref: Image, cand: Image, opts: CompareOptions = {}): CompareResult {
  const threshold = opts.colorThreshold ?? 0;
  const detectAA = opts.detectAntialiasing ?? true;
  const cell = opts.cellSize ?? 16;
  const maxRegions = opts.maxRegions ?? 200;
  if (ref.width !== cand.width || ref.height !== cand.height)
    return {
      width: cand.width,
      height: cand.height,
      dimension_mismatch: { reference: [ref.width, ref.height], candidate: [cand.width, cand.height] },
      total_pixels: cand.width * cand.height,
      identical_pixels: 0,
      diff_pixels: 0,
      aa_pixels: 0,
      max_delta: 0,
      regions: [],
      regions_truncated: false,
      diff_image: null,
    };
  const { width, height } = ref;
  const limit = MAX_YIQ_DELTA * threshold * threshold;
  const out = blankImage(width, height);
  const cols = Math.ceil(width / cell), rows = Math.ceil(height / cell);
  const cellDiff = new Uint32Array(cols * rows);
  const cellAA = new Uint32Array(cols * rows);
  let identical = 0, diff = 0, aa = 0, maxDelta = 0;
  for (let y = 0; y < height; y++)
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4;
      const same =
        ref.data[i] === cand.data[i] && ref.data[i + 1] === cand.data[i + 1] && ref.data[i + 2] === cand.data[i + 2] && ref.data[i + 3] === cand.data[i + 3];
      if (same) {
        identical++;
        // fundo do diff: referência esmaecida (contexto visual)
        const g = 255 - (255 - brightness(ref.data, i)) * 0.1;
        out.data[i] = out.data[i + 1] = out.data[i + 2] = g;
        out.data[i + 3] = 255;
        continue;
      }
      const delta = yiqDelta(ref.data, i, cand.data, i);
      maxDelta = Math.max(maxDelta, Math.sqrt(delta / MAX_YIQ_DELTA));
      const k = Math.floor(y / cell) * cols + Math.floor(x / cell);
      if (delta <= limit) {
        identical++; // abaixo do limiar perceptual configurado
        out.data.set([235, 235, 235, 255], i);
        continue;
      }
      if (detectAA && (antialiased(ref, x, y, cand) || antialiased(cand, x, y, ref))) {
        aa++;
        cellAA[k]++;
        out.data.set([242, 177, 0, 255], i); // amarelo: antisserrilhado
      } else {
        diff++;
        cellDiff[k]++;
        out.data.set([214, 39, 40, 255], i); // vermelho: diferença
      }
    }
  const { regions, truncated } = clusterCells(cellDiff, cellAA, cols, rows, cell, width, height, maxRegions);
  return {
    width,
    height,
    dimension_mismatch: null,
    total_pixels: width * height,
    identical_pixels: identical,
    diff_pixels: diff,
    aa_pixels: aa,
    max_delta: Math.round(maxDelta * 10000) / 10000,
    regions,
    regions_truncated: truncated,
    diff_image: out,
  };
}

/** Agrupa células com diferença (inclusive antisserrilhado) em regiões por 8-vizinhança de células. */
function clusterCells(
  cellDiff: Uint32Array,
  cellAA: Uint32Array,
  cols: number,
  rows: number,
  cell: number,
  width: number,
  height: number,
  maxRegions: number,
): { regions: Region[]; truncated: boolean } {
  const seen = new Uint8Array(cols * rows);
  const regions: Region[] = [];
  for (let start = 0; start < cols * rows; start++) {
    if (seen[start] || (cellDiff[start] === 0 && cellAA[start] === 0)) continue;
    let x0 = Infinity, y0 = Infinity, x1 = -1, y1 = -1, px = 0, pa = 0;
    const stack = [start];
    seen[start] = 1;
    while (stack.length) {
      const k = stack.pop()!;
      const cx = k % cols, cy = Math.floor(k / cols);
      x0 = Math.min(x0, cx);
      y0 = Math.min(y0, cy);
      x1 = Math.max(x1, cx);
      y1 = Math.max(y1, cy);
      px += cellDiff[k];
      pa += cellAA[k];
      for (let dy = -1; dy <= 1; dy++)
        for (let dx = -1; dx <= 1; dx++) {
          const nx = cx + dx, ny = cy + dy;
          if (nx < 0 || ny < 0 || nx >= cols || ny >= rows) continue;
          const n = ny * cols + nx;
          if (!seen[n] && (cellDiff[n] > 0 || cellAA[n] > 0)) {
            seen[n] = 1;
            stack.push(n);
          }
        }
    }
    const x = x0 * cell, y = y0 * cell;
    regions.push({ x, y, w: Math.min(width, (x1 + 1) * cell) - x, h: Math.min(height, (y1 + 1) * cell) - y, pixels: px, aa_pixels: pa });
  }
  regions.sort((a, b) => b.pixels + b.aa_pixels - (a.pixels + a.aa_pixels));
  return { regions: regions.slice(0, maxRegions), truncated: regions.length > maxRegions };
}
