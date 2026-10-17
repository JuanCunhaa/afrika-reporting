// F07 — extração do LAYOUT RENDERIZADO para a exportação PPTX/PDF. Roda no Chromium headless controlado pelo backend
// (rota #/render, mesma visualização da pré-visualização). O backend NÃO recria o layout: lê daqui caixas, estilos
// computados (a partir dos tokens do tema) e quebras de linha reais, e monta os objetos NATIVOS do PowerPoint.
// Nenhum número é calculado aqui: textos são os rótulos já formatados pelo backend (IR); gráficos são referenciados
// pelo caminho da IR (`data-ir`) e reconstruídos no backend com os valores aprovados.
//
// Também expõe o detector de overflow/cortes (antes só no motor visual) para a mesma regra valer na pré-visualização,
// na regressão visual e no bloqueio da exportação.

export const EXPORT_LAYOUT_VERSION = 1;

export type XBox = { x: number; y: number; w: number; h: number };
export type XColor = { rgb: string; a: number }; // rgb = 'RRGGBB' (maiúsculas), a = 0..1
export type XBorder = { w: number; color: XColor; style: 'solid' | 'dashed' | 'dotted' };
export type XRun = { t: string; font: string; weight: number; italic: boolean; size: number; color: XColor; spacing: number; underline: boolean };
export type XPara = {
  runs: XRun[];
  align: 'l' | 'ctr' | 'r' | 'just';
  lh: number; // entrelinha em px (altura da caixa de linha CSS)
  after: number; // espaço depois do parágrafo (px)
  bullet: { char: string; color: XColor; size: number; font: string; weight: number; scale: number } | null;
  marL: number; // recuo esquerdo do texto (px) — listas: recuo do marcador
  indent: number; // recuo da 1ª linha (px; negativo = marcador pendurado)
};
// `base` = distância do topo da 1ª caixa de linha CSS até a linha de base (meia-entrelinha + ascendente REAL da fonte,
// medido no navegador). O PowerPoint, com entrelinha exata L, põe a 1ª linha de base a 0,75·L do topo da caixa
// (calibrado na F07 para as fontes do tema); o exportador desloca a caixa em `base − 0,75·L`.
export type XText = { box: XBox; paras: XPara[]; wrap: boolean; vertical: boolean; lines: number; lineWidths: number[]; maxWidth: number; base: number };
export type XCell = XText & { cell: XBox; fill: XColor | null; pad: [number, number, number, number]; borders: (XBorder | null)[]; valign: 't' | 'ctr' | 'b'; xid: number | null };
export type XOp =
  | { op: 'background'; key: string; fill: XColor | null; image: string | null }
  | { op: 'rect'; key: string; box: XBox; fill: XColor | null; radius: [number, number, number, number]; border: XBorder | null; texture: boolean; prov?: string }
  | { op: 'line'; key: string; x1: number; y1: number; x2: number; y2: number; w: number; color: XColor; style: XBorder['style'] }
  | { op: 'path'; key: string; box: XBox; d: string; vw: number; vh: number; fill: XColor }
  | { op: 'image'; key: string; box: XBox; fit: string; natural: [number, number] }
  | ({ op: 'text'; key: string; xid: number; prov?: string } & XText)
  | { op: 'table'; key: string; box: XBox; kind: 'table' | 'matrix'; cols: number[]; rows: { y: number; h: number; header: boolean; cells: XCell[] }[]; gap: number; gapColor: XColor | null; ir: string | null }
  | { op: 'chart'; key: string; box: XBox; plot: XBox | null; ir: string; variant: 'plot' | 'donut' | 'severity'; rows: number; overlays: XOp[]; vb: [number, number]; categories: string[]; zone: string | null }
  | { op: 'arrow'; key: string; box: XBox; color: XColor; w: number };
export type SlideLayout = { version: number; index: number; slide_id: string; canvas: { width: number; height: number }; ops: XOp[]; text_nodes: number };
// `cut` (F07) = px de conteúdo efetivamente ESCONDIDOS: nos cortes, o excesso além da área de padding (conteúdo que só
// invade o padding continua visível); nos demais tipos, igual a `amount`.
export type OverflowFinding = { slide: string; key: string; kind: 'clipped-x' | 'clipped-y' | 'spill-x' | 'ellipsis' | 'outside-zone' | 'outside-slide'; amount: number; cut: number };

const r2 = (n: number) => Math.round(n * 100) / 100;

// ---------------------------------------------------------------- cores (sempre normalizadas para RRGGBB + alfa)

let colorCtx: CanvasRenderingContext2D | null | undefined;
export function parseColor(css: string | null | undefined): XColor | null {
  if (!css || css === 'transparent' || css === 'none') return null;
  let m = css.match(/^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)$/);
  let rgb: number[] | null = null;
  let a = 1;
  if (m) {
    rgb = [Number(m[1]), Number(m[2]), Number(m[3])];
    if (m[4] !== undefined) a = m[4].endsWith('%') ? Number(m[4].slice(0, -1)) / 100 : Number(m[4]);
  } else if ((m = css.match(/^color\(srgb\s+([\d.e-]+)\s+([\d.e-]+)\s+([\d.e-]+)(?:\s*\/\s*([\d.]+%?))?\s*\)$/))) {
    rgb = [Number(m[1]) * 255, Number(m[2]) * 255, Number(m[3]) * 255];
    if (m[4] !== undefined) a = m[4].endsWith('%') ? Number(m[4].slice(0, -1)) / 100 : Number(m[4]);
  } else {
    // outros formatos (hex, nomes, espaços de cor): o canvas do próprio navegador normaliza
    if (colorCtx === undefined) colorCtx = document.createElement('canvas').getContext('2d');
    if (!colorCtx) return null;
    colorCtx.fillStyle = '#000';
    colorCtx.fillStyle = css;
    const v = String(colorCtx.fillStyle);
    if (v.startsWith('#')) return { rgb: v.slice(1).toUpperCase(), a: 1 };
    return v === css ? null : parseColor(v);
  }
  if (a <= 0) return null;
  const hex = rgb.map((c) => Math.max(0, Math.min(255, Math.round(c))).toString(16).padStart(2, '0')).join('').toUpperCase();
  return { rgb: hex, a: r2(Math.min(1, a)) };
}

// ---------------------------------------------------------------- utilidades de caixa/estilo

function rel(r: DOMRect | { left: number; top: number; width: number; height: number }, o: DOMRect): XBox {
  return { x: r2(r.left - o.left), y: r2(r.top - o.top), w: r2(r.width), h: r2(r.height) };
}
const px = (v: string) => (v.endsWith('px') ? parseFloat(v) : Number.isFinite(parseFloat(v)) ? parseFloat(v) : 0);
const visible = (cs: CSSStyleDeclaration) => cs.display !== 'none' && cs.visibility !== 'hidden' && cs.visibility !== 'collapse';

function border(cs: CSSStyleDeclaration, side: 'top' | 'right' | 'bottom' | 'left'): XBorder | null {
  const w = px(cs.getPropertyValue(`border-${side}-width`));
  const style = cs.getPropertyValue(`border-${side}-style`);
  const color = parseColor(cs.getPropertyValue(`border-${side}-color`));
  if (!w || style === 'none' || style === 'hidden' || !color) return null;
  return { w: r2(w), color, style: style === 'dashed' ? 'dashed' : style === 'dotted' ? 'dotted' : 'solid' };
}
const sameBorder = (a: XBorder | null, b: XBorder | null) =>
  !!a && !!b && a.w === b.w && a.style === b.style && a.color.rgb === b.color.rgb && a.color.a === b.color.a;

function radii(cs: CSSStyleDeclaration, box: XBox): [number, number, number, number] {
  const one = (v: string) => {
    const first = v.split(' ')[0];
    const n = first.endsWith('%') ? (parseFloat(first) / 100) * Math.min(box.w, box.h) * 2 : px(first);
    return r2(Math.min(n, box.w / 2, box.h / 2));
  };
  return [one(cs.borderTopLeftRadius), one(cs.borderTopRightRadius), one(cs.borderBottomRightRadius), one(cs.borderBottomLeftRadius)];
}

const fontName = (cs: CSSStyleDeclaration) => cs.fontFamily.split(',')[0].trim().replace(/^["']|["']$/g, '');

function withAlpha(c: XColor | null, opacity: number): XColor | null {
  if (!c) return null;
  return opacity >= 0.999 ? c : { rgb: c.rgb, a: r2(c.a * opacity) };
}

function transform(text: string, cs: CSSStyleDeclaration): string {
  if (cs.textTransform === 'uppercase') return text.toLocaleUpperCase('pt-BR');
  if (cs.textTransform === 'lowercase') return text.toLocaleLowerCase('pt-BR');
  if (cs.textTransform === 'capitalize') return text.replace(/(^|\s)(\p{L})/gu, (_, s, c) => s + c.toLocaleUpperCase('pt-BR'));
  return text;
}

let metricsCtx: CanvasRenderingContext2D | null | undefined;
function fontCss(cs: CSSStyleDeclaration): string {
  return `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
}
function fontMetrics(cs: CSSStyleDeclaration): { asc: number; desc: number } {
  if (metricsCtx === undefined) metricsCtx = document.createElement('canvas').getContext('2d');
  const size = px(cs.fontSize);
  if (!metricsCtx) return { asc: size * 0.9, desc: size * 0.25 };
  metricsCtx.font = fontCss(cs);
  const m = metricsCtx.measureText('Hg');
  return { asc: m.fontBoundingBoxAscent, desc: m.fontBoundingBoxDescent };
}
/** Glifo "•" na fonte do item: largura da tinta e recuo esquerdo (px, a 100%). */
function bulletGlyph(cs: CSSStyleDeclaration): { ink: number; lsb: number } {
  if (metricsCtx === undefined) metricsCtx = document.createElement('canvas').getContext('2d');
  if (!metricsCtx) return { ink: px(cs.fontSize) * 0.3, lsb: 0 };
  metricsCtx.font = fontCss(cs);
  const m = metricsCtx.measureText('•');
  return { ink: Math.max(0.1, m.actualBoundingBoxLeft + m.actualBoundingBoxRight), lsb: -m.actualBoundingBoxLeft };
}

/** Linha de base da 1ª linha a partir do topo da caixa de linha CSS (meia-entrelinha + ascendente). */
function baseline(cs: CSSStyleDeclaration, lh: number): number {
  const { asc, desc } = fontMetrics(cs);
  return r2((lh - (asc + desc)) / 2 + asc);
}

const ALIGN: Record<string, XPara['align']> = { left: 'l', start: 'l', right: 'r', end: 'r', center: 'ctr', justify: 'just', '-webkit-center': 'ctr' };

// ---------------------------------------------------------------- texto

type Collected = { runs: XRun[]; nodes: Text[]; consumed: Set<Element> };

function decorated(cs: CSSStyleDeclaration): boolean {
  return !!parseColor(cs.backgroundColor) || cs.backgroundImage !== 'none' || ['top', 'right', 'bottom', 'left'].some((s) => !!border(cs, s as 'top'));
}

/** Runs de um bloco de texto: nós de texto diretos + elementos INLINE sem decoração (ex.: <strong>). Elementos com
 *  caixa própria (tags, pílulas, amostras de cor, svg) ficam fora: são exportados separadamente na própria posição. */
function collectRuns(el: Element, opacity: number, out: Collected, all = false): void {
  const cs = getComputedStyle(el);
  const pre = cs.whiteSpace === 'pre-line' || cs.whiteSpace === 'pre-wrap' || cs.whiteSpace === 'pre';
  for (const node of Array.from(el.childNodes)) {
    if (node.nodeType === Node.TEXT_NODE) {
      const raw = node.textContent ?? '';
      if (!raw) continue;
      let t = pre ? raw.replace(/[ \t\f\r]+/g, ' ').replace(/ ?\n ?/g, '\n') : raw.replace(/[\s]+/g, ' ');
      t = transform(t, cs);
      if (!t) continue;
      out.runs.push({
        t,
        font: fontName(cs),
        weight: Number(cs.fontWeight) || 400,
        italic: cs.fontStyle === 'italic' || cs.fontStyle.startsWith('oblique'),
        size: r2(px(cs.fontSize)),
        color: withAlpha(parseColor(cs.color), opacity) ?? { rgb: '000000', a: 1 },
        spacing: cs.letterSpacing === 'normal' ? 0 : r2(px(cs.letterSpacing)),
        underline: cs.textDecorationLine.includes('underline'),
      });
      out.nodes.push(node as Text);
    } else if (node instanceof HTMLBRElement) {
      out.runs.push({ ...(out.runs[out.runs.length - 1] ?? { font: fontName(cs), weight: 400, italic: false, size: px(cs.fontSize), color: { rgb: '000000', a: 1 }, spacing: 0, underline: false }), t: '\n' });
    } else if (node instanceof HTMLElement) {
      const ccs = getComputedStyle(node);
      if (!visible(ccs)) continue;
      // dentro de células de tabela tudo vira run (inclusive marcadores "Manual"/"Lacuna"): a célula fica completa
      if (all ? !node.matches('.rank-bar,.swatch,.pill-dot') : ccs.display === 'inline' && !decorated(ccs)) {
        out.consumed.add(node);
        collectRuns(node, opacity * (Number(ccs.opacity) || 1), out, all);
      }
    }
  }
}

/** Junta espaços entre runs (colapso CSS) e apara início/fim do parágrafo. */
function normalizeRuns(runs: XRun[]): XRun[] {
  const out: XRun[] = [];
  for (const r of runs) {
    let t = r.t;
    const prev = out[out.length - 1];
    if (!prev || prev.t.endsWith(' ') || prev.t.endsWith('\n')) t = t.replace(/^ +/, '');
    if (!t) continue;
    if (prev && prev.font === r.font && prev.weight === r.weight && prev.italic === r.italic && prev.size === r.size && prev.color.rgb === r.color.rgb && prev.color.a === r.color.a && prev.spacing === r.spacing && prev.underline === r.underline)
      prev.t += t;
    else out.push({ ...r, t });
  }
  if (out.length) out[out.length - 1].t = out[out.length - 1].t.replace(/[ \n]+$/, '');
  return out.filter((r) => r.t.length > 0);
}

// `glyph` = altura da área de conteúdo da fonte na 1ª linha (com entrelinha menor que a fonte as linhas se sobrepõem:
// a média top..bottom/linhas subestimaria a altura e deslocaria a caixa)
type LineInfo = { lines: number; top: number; bottom: number; left: number; right: number; widths: number[]; firstLeft: number; glyph: number };

/** Linhas REAIS (quebras do Chromium) a partir dos retângulos dos nós de texto. */
function lineInfo(nodes: Text[], origin: DOMRect, vertical: boolean): LineInfo | null {
  const rects: DOMRect[] = [];
  const range = document.createRange();
  for (const n of nodes) {
    range.selectNodeContents(n);
    for (const r of Array.from(range.getClientRects())) if (r.width > 0.5 && r.height > 0.5) rects.push(r);
  }
  range.detach();
  if (!rects.length) return null;
  // agrupa fragmentos por linha (sobreposição no eixo de bloco)
  const groups: { a: number; b: number; lo: number; hi: number }[] = [];
  for (const r of rects) {
    const [a, b, lo, hi] = vertical ? [r.left, r.right, r.top, r.bottom] : [r.top, r.bottom, r.left, r.right];
    const g = groups.find((x) => Math.min(x.b, b) - Math.max(x.a, a) > Math.min(b - a, x.b - x.a) * 0.5);
    if (g) {
      g.a = Math.min(g.a, a);
      g.b = Math.max(g.b, b);
      g.lo = Math.min(g.lo, lo);
      g.hi = Math.max(g.hi, hi);
    } else groups.push({ a, b, lo, hi });
  }
  groups.sort((x, y) => x.a - y.a);
  const top = Math.min(...rects.map((r) => r.top)) - origin.top;
  const bottom = Math.max(...rects.map((r) => r.bottom)) - origin.top;
  const left = Math.min(...rects.map((r) => r.left)) - origin.left;
  const right = Math.max(...rects.map((r) => r.right)) - origin.left;
  return { lines: groups.length, top, bottom, left, right, widths: groups.map((g) => r2(g.hi - g.lo)), firstLeft: (vertical ? groups[0].lo - origin.top : groups[0].lo - origin.left), glyph: groups[0].b - groups[0].a };
}

function contentBox(el: Element, cs: CSSStyleDeclaration, o: DOMRect): XBox {
  const r = el.getBoundingClientRect();
  const l = px(cs.borderLeftWidth) + px(cs.paddingLeft), t = px(cs.borderTopWidth) + px(cs.paddingTop);
  const w = r.width - l - px(cs.borderRightWidth) - px(cs.paddingRight);
  const h = r.height - t - px(cs.borderBottomWidth) - px(cs.paddingBottom);
  return { x: r2(r.left - o.left + l), y: r2(r.top - o.top + t), w: r2(Math.max(0, w)), h: r2(Math.max(0, h)) };
}

function lineHeight(cs: CSSStyleDeclaration, info: LineInfo | null, fallbackBox: XBox): number {
  if (cs.lineHeight !== 'normal') return r2(px(cs.lineHeight));
  if (info && info.lines > 1) return r2((info.bottom - info.top) / info.lines);
  return r2(Math.max(px(cs.fontSize) * 1.2, info ? info.bottom - info.top : fallbackBox.h));
}

/** Monta a caixa de texto: horizontal = caixa de conteúdo (largura de quebra); vertical = caixas de LINHA reais. */
function textGeometry(el: Element, cs: CSSStyleDeclaration, o: DOMRect, info: LineInfo, lh: number, vertical: boolean): Omit<XText, 'paras' | 'base'> & { indent: number } {
  const cb = contentBox(el, cs, o);
  if (vertical) {
    // escrita vertical (título de seção, lido de baixo para cima): colunas = linhas; a extensão do texto na vertical
    // vem dos retângulos reais. Uma coluna: caixa justa e sem quebra; várias: altura da caixa de conteúdo.
    const half = (lh * info.lines - (info.right - info.left)) / 2;
    const one = info.lines === 1;
    return { box: { x: r2(info.left - half), y: one ? r2(info.top) : cb.y, w: r2(lh * info.lines), h: one ? r2(info.bottom - info.top) : cb.h }, wrap: !one, vertical: true, lines: info.lines, lineWidths: info.widths, maxWidth: cb.h, indent: 0 };
  }
  // topo da 1ª caixa de linha CSS = topo do glifo - meia entrelinha (o retângulo do texto é a área de conteúdo da fonte)
  const top = info.top - (lh - info.glyph) / 2;
  const single = info.lines === 1 && !el.closest('td,th,[role=cell],[role=columnheader]');
  // recuo da 1ª linha só em texto alinhado à esquerda (prefixo inline-block, ex.: amostra de cor); em texto centralizado
  // ou à direita o deslocamento da 1ª linha vem do próprio alinhamento
  const left = ['left', 'start', 'justify', '-webkit-left'].includes(cs.textAlign);
  const indent = left ? r2(Math.max(0, info.firstLeft - cb.x)) : 0;
  if (single) {
    // uma linha: sem quebra no PowerPoint (wrap=none) => nunca ganha linha extra por diferença de métrica
    return { box: { x: r2(info.left), y: r2(top), w: r2(info.right - info.left), h: r2(lh) }, wrap: false, vertical: false, lines: 1, lineWidths: info.widths, maxWidth: cb.w, indent: 0 };
  }
  return { box: { x: cb.x, y: r2(top), w: cb.w, h: r2(lh * info.lines) }, wrap: true, vertical: false, lines: info.lines, lineWidths: info.widths, maxWidth: cb.w, indent };
}

// ---------------------------------------------------------------- extração por slide

class Extractor {
  ops: XOp[] = [];
  private counts = new Map<string, number>();
  private consumed = new Set<Element>();
  private xid = 0;
  constructor(private origin: DOMRect) {}

  key(kind: string, el: Element, suffix = ''): string {
    const base = (el.closest('[data-el]') as HTMLElement | null)?.dataset.el ?? (el.getAttribute('class') ?? el.tagName).split(' ')[0];
    const k = `${kind}:${base}${suffix ? `/${suffix}` : ''}`;
    const n = (this.counts.get(k) ?? 0) + 1;
    this.counts.set(k, n);
    return n > 1 ? `${k}#${n}` : k;
  }

  prov(el: Element): string | undefined {
    return (el.closest('[data-provenance]') as HTMLElement | null)?.dataset.provenance;
  }

  textOp(el: HTMLElement, cs: CSSStyleDeclaration, opacity: number, keyKind = 'text'): void {
    const col: Collected = { runs: [], nodes: [], consumed: this.consumed };
    collectRuns(el, opacity, col);
    const runs = normalizeRuns(col.runs);
    if (!runs.length) return;
    const vertical = /^(vertical|sideways)/.test(cs.writingMode);
    const info = lineInfo(col.nodes, this.origin, vertical);
    if (!info) return;
    const lh = lineHeight(cs, info, contentBox(el, cs, this.origin));
    const g = textGeometry(el, cs, this.origin, info, lh, vertical);
    const xid = ++this.xid;
    el.dataset.xid = String(xid);
    this.ops.push({
      op: 'text', key: this.key(keyKind, el), xid, prov: this.prov(el), box: g.box, wrap: g.wrap, vertical: g.vertical, lines: g.lines, lineWidths: g.lineWidths, maxWidth: g.maxWidth, base: baseline(cs, lh),
      paras: [{ runs, align: ALIGN[cs.textAlign] ?? 'l', lh, after: 0, bullet: null, marL: 0, indent: g.indent }],
    });
  }

  listOp(list: HTMLElement, cs: CSSStyleDeclaration, opacity: number): void {
    const items = Array.from(list.children).filter((c): c is HTMLLIElement => c instanceof HTMLLIElement && visible(getComputedStyle(c)));
    const paras: XPara[] = [];
    const nodes: Text[] = [];
    const lb = contentBox(list, cs, this.origin);
    const listBox = list.getBoundingClientRect();
    let last: LineInfo | null = null;
    let first: LineInfo | null = null;
    let lines = 0;
    let firstBase = 0;
    const widths: number[] = [];
    items.forEach((li, i) => {
      const lcs = getComputedStyle(li);
      const col: Collected = { runs: [], nodes: [], consumed: this.consumed };
      collectRuns(li, opacity, col);
      const runs = normalizeRuns(col.runs);
      const info = lineInfo(col.nodes, this.origin, false);
      if (!runs.length || !info) return;
      first ??= info;
      lines += info.lines;
      widths.push(...info.widths);
      const lh = lineHeight(lcs, info, lb);
      const next = items[i + 1]?.getBoundingClientRect();
      // espaço real até o próximo item (margem + gap do contêiner), medido — não presumido
      const after = next ? r2(next.top - li.getBoundingClientRect().bottom) : 0;
      const mcs = getComputedStyle(li, '::marker');
      const char = lcs.listStyleType === 'decimal' ? `${i + 1}.` : '•';
      const marL = r2(li.getBoundingClientRect().left - listBox.left);
      // marcador "disc" do Chromium é um DISCO desenhado (não o glifo): diâmetro (2/3·ascendente + 1)/2 e início a
      // ≈ 0,66·tamanho + 7 px antes do texto (calibrado na F07, Chromium 156, Poppins/Montserrat/Be Vietnam Pro 14–37 px).
      // No PowerPoint o marcador é o glifo "•" da mesma fonte, escalado para o mesmo diâmetro e recuado para a mesma tinta.
      const size = px(lcs.fontSize);
      const g = bulletGlyph(lcs);
      const disc = (fontMetrics(lcs).asc * 2 / 3 + 1) / 2;
      const scale = r2(Math.max(0.25, Math.min(4, disc / g.ink)));
      const hang = lcs.listStyleType === 'none' ? 0 : r2(Math.min(marL, 0.66 * size + 7 + g.lsb * scale));
      const marker = lcs.listStyleType === 'none' ? null : { char, color: parseColor(mcs.color) ?? parseColor(lcs.color) ?? { rgb: '000000', a: 1 }, size: r2(px(mcs.fontSize) || size), font: fontName(lcs), weight: Number(lcs.fontWeight) || 400, scale };
      paras.push({ runs, align: ALIGN[lcs.textAlign] ?? 'l', lh, after: Math.max(0, after), bullet: marker, marL, indent: -hang });
      if (paras.length === 1) firstBase = baseline(lcs, lh);
      nodes.push(...col.nodes);
      last = info;
    });
    if (!paras.length || !first || !last) return;
    const f = first as LineInfo, l = last as LineInfo;
    const top = f.top - (paras[0].lh - f.glyph) / 2;
    const bottom = l.bottom + (paras[paras.length - 1].lh - l.glyph) / 2;
    const xid = ++this.xid;
    list.dataset.xid = String(xid);
    this.ops.push({ op: 'text', key: this.key('list', list), xid, box: { x: r2(listBox.left - this.origin.left), y: r2(top), w: r2(listBox.width), h: r2(bottom - top) }, wrap: true, vertical: false, lines, lineWidths: widths, maxWidth: lb.w + px(cs.paddingLeft), paras, base: firstBase });
    for (const li of items) this.consumed.add(li);
  }

  decorate(el: HTMLElement, cs: CSSStyleDeclaration, opacity: number): void {
    const box = rel(el.getBoundingClientRect(), this.origin);
    if (box.w < 0.5 || box.h < 0.5) return;
    const fill = withAlpha(parseColor(cs.backgroundColor), opacity);
    const texture = cs.backgroundImage.includes('gradient');
    const sides = (['top', 'right', 'bottom', 'left'] as const).map((s) => border(cs, s));
    const uniform = sides.every((s) => sameBorder(s, sides[0]));
    if (fill || texture || (uniform && sides[0])) {
      const b = uniform ? sides[0] : null;
      this.ops.push({ op: 'rect', key: this.key('rect', el), box, fill, radius: radii(cs, box), border: b ? { ...b, color: withAlpha(b.color, opacity)! } : null, texture, prov: this.prov(el) });
    }
    if (!uniform)
      sides.forEach((s, i) => {
        if (!s) return;
        const h = s.w / 2;
        const [x1, y1, x2, y2] = [
          [box.x, box.y + h, box.x + box.w, box.y + h],
          [box.x + box.w - h, box.y, box.x + box.w - h, box.y + box.h],
          [box.x, box.y + box.h - h, box.x + box.w, box.y + box.h - h],
          [box.x + h, box.y, box.x + h, box.y + box.h],
        ][i];
        this.ops.push({ op: 'line', key: this.key('line', el, ['t', 'r', 'b', 'l'][i]), x1: r2(x1), y1: r2(y1), x2: r2(x2), y2: r2(y2), w: s.w, color: withAlpha(s.color, opacity)!, style: s.style });
      });
  }

  /** Células de tabela/matriz: runs de todo o conteúdo + linhas reais + preenchimento/bordas/recuos. */
  cell(el: HTMLElement, opacity: number): XCell {
    const cs = getComputedStyle(el);
    const col: Collected = { runs: [], nodes: [], consumed: this.consumed };
    collectRuns(el, opacity, col, true);
    const runs = normalizeRuns(col.runs);
    const cellBox = rel(el.getBoundingClientRect(), this.origin);
    const cb = contentBox(el, cs, this.origin);
    const info = lineInfo(col.nodes, this.origin, false);
    const lh = lineHeight(cs, info, cb);
    const valign = cs.display.includes('flex') ? (cs.alignItems === 'center' ? 'ctr' : cs.alignItems.endsWith('end') ? 'b' : 't') : cs.verticalAlign === 'top' ? 't' : cs.verticalAlign === 'bottom' ? 'b' : el.tagName === 'TD' || el.tagName === 'TH' ? 'ctr' : 't';
    const align = cs.display.includes('flex') && cs.justifyContent === 'center' ? 'ctr' : ALIGN[cs.textAlign] ?? 'l';
    const xid = info ? ++this.xid : null;
    if (xid) el.dataset.xid = String(xid);
    // amostras/barras dentro da célula (ranking com barras): formas sobrepostas, exportadas depois da tabela
    for (const deco of Array.from(el.querySelectorAll<HTMLElement>('.rank-bar,.swatch'))) this.pendingOverlays.push(deco);
    return {
      cell: cellBox,
      box: info ? { x: cb.x, y: r2(info.top), w: cb.w, h: r2(info.bottom - info.top) } : cb,
      paras: runs.length ? [{ runs, align, lh, after: 0, bullet: null, marL: 0, indent: 0 }] : [],
      wrap: true, vertical: false, lines: info?.lines ?? 0, lineWidths: info?.widths ?? [], maxWidth: cb.w, base: baseline(cs, lh),
      fill: withAlpha(parseColor(cs.backgroundColor), opacity),
      pad: [px(cs.paddingTop), px(cs.paddingRight), px(cs.paddingBottom), px(cs.paddingLeft)].map(r2) as [number, number, number, number],
      borders: (['top', 'right', 'bottom', 'left'] as const).map((s) => border(cs, s)),
      valign,
      xid,
    };
  }
  pendingOverlays: HTMLElement[] = [];

  tableOp(t: HTMLTableElement, opacity: number): void {
    const rows: { y: number; h: number; header: boolean; cells: XCell[] }[] = [];
    for (const tr of Array.from(t.rows)) {
      if (!visible(getComputedStyle(tr))) continue;
      const rb = rel(tr.getBoundingClientRect(), this.origin);
      rows.push({ y: rb.y, h: rb.h, header: tr.parentElement?.tagName === 'THEAD', cells: Array.from(tr.cells).map((c) => this.cell(c, opacity)) });
    }
    const cols = (rows[0]?.cells ?? []).map((c) => c.cell.w);
    this.ops.push({ op: 'table', key: this.key('table', t), box: rel(t.getBoundingClientRect(), this.origin), kind: 'table', cols, rows, gap: 0, gapColor: null, ir: t.closest<HTMLElement>('[data-ir]')?.dataset.ir ?? null });
    this.flushOverlays(opacity);
  }

  /** Matriz (grade CSS com células separadas por espaço): vira TABELA editável; o espaço entre células é emulado no
   *  exportador por bordas na cor do fundo. */
  matrixOp(grid: HTMLElement, opacity: number, slideBg: XColor | null): void {
    const cs = getComputedStyle(grid);
    const cells = Array.from(grid.children).filter((c): c is HTMLElement => c instanceof HTMLElement && visible(getComputedStyle(c)));
    const tops = [...new Set(cells.map((c) => Math.round(c.getBoundingClientRect().top)))].sort((a, b) => a - b);
    const rows = tops.map((top) => {
      const rc = cells.filter((c) => Math.round(c.getBoundingClientRect().top) === top).sort((a, b) => a.getBoundingClientRect().left - b.getBoundingClientRect().left);
      const b = rel(rc[0].getBoundingClientRect(), this.origin);
      return { y: b.y, h: Math.max(...rc.map((c) => c.getBoundingClientRect().height)), header: rc[0].getAttribute('role') === 'columnheader', cells: rc.map((c) => this.cell(c, opacity)) };
    });
    const cols = (rows[0]?.cells ?? []).map((c) => c.cell.w);
    this.ops.push({ op: 'table', key: this.key('table', grid), box: rel(grid.getBoundingClientRect(), this.origin), kind: 'matrix', cols, rows, gap: r2(px(cs.columnGap) || px(cs.rowGap)), gapColor: slideBg, ir: null });
  }

  flushOverlays(opacity: number): void {
    for (const el of this.pendingOverlays.splice(0)) this.decorate(el, getComputedStyle(el), opacity);
  }

  svgText(t: SVGTextElement, key: string, opacity: number): XOp | null {
    const text = (t.textContent ?? '').trim();
    if (!text) return null;
    const cs = getComputedStyle(t);
    const b = rel(t.getBoundingClientRect(), this.origin);
    const anchor = t.getAttribute('text-anchor') ?? cs.textAnchor;
    const xid = ++this.xid;
    t.dataset.xid = String(xid);
    const m = fontMetrics(cs);
    return {
      op: 'text', key: this.key('text', t, key), xid, box: b, wrap: false, vertical: false, lines: 1, lineWidths: [b.w], maxWidth: b.w, base: r2((b.h - (m.asc + m.desc)) / 2 + m.asc),
      paras: [{ runs: [{ t: text, font: fontName(cs), weight: Number(cs.fontWeight) || 400, italic: false, size: r2(px(cs.fontSize)), color: withAlpha(parseColor(cs.fill), opacity) ?? { rgb: '000000', a: 1 }, spacing: 0, underline: false }], align: anchor === 'middle' ? 'ctr' : anchor === 'end' ? 'r' : 'l', lh: b.h, after: 0, bullet: null, marL: 0, indent: 0 }],
    };
  }

  chartOp(svg: SVGSVGElement, variant: 'plot' | 'donut', opacity: number): void {
    const ir = svg.closest<HTMLElement>('[data-ir]')?.dataset.ir ?? 'data';
    const plotEl = svg.querySelector('[data-plot-area]');
    const overlays: XOp[] = [];
    // marcadores de lacuna (contorno tracejado, linha vertical e rótulo): anotação vetorial, nunca valor
    for (const m of Array.from(svg.querySelectorAll<SVGGraphicsElement>('[data-gap-marker]'))) {
      const b = rel(m.getBoundingClientRect(), this.origin);
      const cs = getComputedStyle(m);
      const stroke = withAlpha(parseColor(cs.stroke), opacity);
      if (m instanceof SVGTextElement) {
        const t = this.svgText(m, 'gap', opacity);
        if (t) overlays.push(t);
      } else if (m instanceof SVGLineElement && stroke) {
        overlays.push({ op: 'line', key: this.key('line', m, 'gap'), x1: r2(b.x + b.w / 2), y1: b.y, x2: r2(b.x + b.w / 2), y2: r2(b.y + b.h), w: r2(px(cs.strokeWidth) || 1), color: stroke, style: 'dashed' });
      } else if (m instanceof SVGRectElement && stroke) {
        overlays.push({ op: 'rect', key: this.key('rect', m, 'gap'), box: b, fill: null, radius: [0, 0, 0, 0], border: { w: r2(px(cs.strokeWidth) || 1), color: stroke, style: 'dashed' }, texture: false });
      }
    }
    if (variant === 'donut') {
      const total = svg.querySelector<SVGTextElement>('text.donut-total');
      const t = total ? this.svgText(total, 'total', opacity) : null;
      if (t) overlays.push(t);
      const ring = svg.querySelector('circle');
      if (ring) {
        const cs = getComputedStyle(ring);
        const b = rel(ring.getBoundingClientRect(), this.origin);
        const w = px(cs.strokeWidth) * (svg.getBoundingClientRect().width / 220);
        overlays.push({ op: 'rect', key: this.key('rect', ring, 'ring'), box: b, fill: null, radius: [b.w / 2, b.w / 2, b.w / 2, b.w / 2], border: { w: r2(w), color: withAlpha(parseColor(cs.stroke), opacity) ?? { rgb: 'CCCCCC', a: 1 }, style: 'solid' }, texture: false });
      }
    }
    // rótulo de unidade do eixo (texto editável sobreposto) e rótulos de categoria como DESENHADOS (rarefação de meses e
    // abreviação "…" de categorias longas — o PPTX recebe as categorias completas da IR)
    const unit = svg.querySelector<SVGTextElement>('text[data-axis-unit]');
    const unitOp = unit ? this.svgText(unit, 'unit', opacity) : null;
    if (unitOp) overlays.push(unitOp);
    const lineText = (t: SVGTextElement) => {
      const spans = Array.from(t.querySelectorAll('tspan'));
      return (spans.length ? spans.map((s) => s.textContent ?? '').join(' ') : (t.textContent ?? '')).trim();
    };
    const categories = Array.from(svg.querySelectorAll<SVGTextElement>('text[data-cat]')).map(lineText);
    const vb = svg.viewBox.baseVal;
    this.ops.push({ op: 'chart', key: this.key('chart', svg), box: rel(svg.getBoundingClientRect(), this.origin), plot: plotEl ? rel(plotEl.getBoundingClientRect(), this.origin) : null, ir, variant, rows: 0, overlays, vb: [vb.width, vb.height], categories, zone: zoneOf(svg) });
  }

  severityOp(rowsEl: HTMLElement): void {
    const tracks = Array.from(rowsEl.querySelectorAll<HTMLElement>('.sev-track')).map((t) => t.getBoundingClientRect());
    const ir = rowsEl.closest<HTMLElement>('[data-ir]')?.dataset.ir ?? 'data';
    let plot: XBox | null = null;
    if (tracks.length) {
      const pitch = tracks.length > 1 ? (tracks[tracks.length - 1].top - tracks[0].top) / (tracks.length - 1) : tracks[0].height * 1.5;
      const top = tracks[0].top - (pitch - tracks[0].height) / 2;
      plot = rel({ left: tracks[0].left, top, width: tracks[0].width, height: pitch * tracks.length }, this.origin);
    }
    this.ops.push({ op: 'chart', key: this.key('chart', rowsEl), box: rel(rowsEl.getBoundingClientRect(), this.origin), plot, ir, variant: 'severity', rows: tracks.length, overlays: [], vb: [0, 0], categories: [], zone: zoneOf(rowsEl) });
  }

  walk(el: Element, opacity: number, slideBg: XColor | null): void {
    if (this.consumed.has(el)) return;
    if (el instanceof SVGSVGElement) {
      const cs = getComputedStyle(el);
      if (!visible(cs)) return;
      const op = opacity * (Number(cs.opacity) || 1);
      if (el.matches('.chart-svg')) return this.chartOp(el, 'plot', op);
      if (el.matches('.donut-svg')) return this.chartOp(el, 'donut', op);
      const path = el.querySelector('path');
      if (el.matches('.slide-shape') && path) {
        const vb = el.viewBox.baseVal;
        const pcs = getComputedStyle(path);
        const fill = withAlpha(parseColor(pcs.fill), op * (Number(pcs.opacity) || 1));
        if (fill) this.ops.push({ op: 'path', key: this.key('path', el), box: rel(el.getBoundingClientRect(), this.origin), d: path.getAttribute('d') ?? '', vw: vb.width, vh: vb.height, fill });
        return;
      }
      if (el.matches('.cmp-col-arrow')) {
        const b = rel(el.getBoundingClientRect(), this.origin);
        const color = withAlpha(parseColor(cs.color), op) ?? { rgb: '888888', a: 1 };
        this.ops.push({ op: 'arrow', key: this.key('arrow', el), box: b, color, w: r2((2 * b.w) / 24) });
      }
      return;
    }
    if (!(el instanceof HTMLElement)) return;
    const cs = getComputedStyle(el);
    if (!visible(cs)) return;
    const op = opacity * (Number(cs.opacity) || 1);
    if (op <= 0.001) return;
    if (el instanceof HTMLImageElement) {
      if (el.complete && el.naturalWidth > 0)
        this.ops.push({ op: 'image', key: (el.dataset.el ?? this.key('image', el)), box: rel(el.getBoundingClientRect(), this.origin), fit: cs.objectFit, natural: [el.naturalWidth, el.naturalHeight] });
      return;
    }
    if (el instanceof HTMLTableElement && el.matches('.slide-table')) return this.tableOp(el, op);
    if (el.matches('.reco-matrix')) {
      this.decorate(el, cs, op);
      return this.matrixOp(el, op, slideBg);
    }
    if (el.matches('.sev-rows')) return this.severityOp(el);
    this.decorate(el, cs, op);
    if ((el instanceof HTMLUListElement || el instanceof HTMLOListElement) && cs.listStyleType !== 'none') return this.listOp(el, cs, op);
    if (hasOwnText(el)) this.textOp(el, cs, op);
    for (const child of Array.from(el.children)) this.walk(child, op, slideBg);
  }
}

const zoneOf = (el: Element) => (el.closest<HTMLElement>('.dash-zone')?.dataset.el ?? null);

/** Bloco de texto: nó de texto direto não vazio, ou filho INLINE sem decoração com texto (ex.: <li><strong>…</strong>). */
function hasOwnText(el: HTMLElement): boolean {
  for (const n of Array.from(el.childNodes)) {
    if (n.nodeType === Node.TEXT_NODE && (n.textContent ?? '').trim()) return true;
    if (n instanceof HTMLElement) {
      const cs = getComputedStyle(n);
      if (cs.display === 'inline' && !decorated(cs) && (n.textContent ?? '').trim() && visible(cs)) return true;
    }
  }
  return false;
}

export function collectLayout(slot: HTMLElement): SlideLayout {
  const slide = slot.querySelector('.slide') as HTMLElement;
  const origin = slide.getBoundingClientRect();
  const x = new Extractor(origin);
  const cs = getComputedStyle(slide);
  const bg = parseColor(cs.backgroundColor);
  const img = cs.backgroundImage.match(/\/api\/theme-assets\/([0-9a-f]{64})/);
  x.ops.push({ op: 'background', key: 'background', fill: bg, image: img ? img[1] : null });
  for (const child of Array.from(slide.children)) x.walk(child, Number(cs.opacity) || 1, bg);
  x.flushOverlays(1);
  return { version: EXPORT_LAYOUT_VERSION, index: Number(slot.dataset.renderSlide), slide_id: slot.dataset.slideId ?? '', canvas: { width: slide.offsetWidth, height: slide.offsetHeight }, ops: x.ops, text_nodes: x.ops.filter((o) => o.op === 'text').length };
}

// ---------------------------------------------------------------- overflow e cortes (F06C; regra única)
// clipped-x / clipped-y  conteúdo maior que a caixa de um elemento que corta (overflow hidden/clip)
// spill-x                texto mais longo que a própria caixa na direção INLINE (sem corte): vaza sobre o vizinho
// ellipsis               texto truncado com reticências — registrado à parte
// outside-zone           elemento com texto ultrapassa a moldura da zona do painel
// outside-slide          elemento com texto ultrapassa o canvas do slide
export function collectOverflow(root: ParentNode = document): OverflowFinding[] {
  const out: OverflowFinding[] = [];
  const TOL = 1; // px: arredondamento de subpixel
  for (const slot of Array.from(root.querySelectorAll<HTMLElement>('[data-render-slide]'))) {
    const slideName = `${String(slot.dataset.renderSlide).padStart(2, '0')}-${slot.dataset.slideId}`;
    const slide = slot.querySelector('.slide') as HTMLElement;
    const sb = slide.getBoundingClientRect();
    for (const el of Array.from(slide.querySelectorAll<HTMLElement>('*'))) {
      if (!(el instanceof HTMLElement)) continue; // SVG: geometria do gráfico, avaliada pelo motor de pixels
      const cs = getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden') continue;
      const key = el.closest<HTMLElement>('[data-el]')?.dataset.el ?? el.className.toString().split(' ')[0] ?? el.tagName;
      const clips = (v: string) => v === 'hidden' || v === 'clip';
      const hasText = Array.from(el.childNodes).some((n) => n.nodeType === Node.TEXT_NODE && (n.textContent ?? '').trim());
      if (clips(cs.overflowX) && el.scrollWidth - el.clientWidth > TOL) {
        const amount = el.scrollWidth - el.clientWidth;
        if (cs.textOverflow === 'ellipsis') out.push({ slide: slideName, key, kind: 'ellipsis', amount, cut: amount });
        else if (hasText || el.querySelector('*')) out.push({ slide: slideName, key, kind: 'clipped-x', amount, cut: Math.max(0, amount - parseFloat(cs.paddingRight)) });
      }
      if (clips(cs.overflowY) && el.scrollHeight - el.clientHeight > TOL && (hasText || el.querySelector('*'))) {
        const amount = el.scrollHeight - el.clientHeight;
        out.push({ slide: slideName, key, kind: 'clipped-y', amount, cut: Math.max(0, amount - parseFloat(cs.paddingBottom)) });
      }
      if (!hasText) continue;
      // direção INLINE do texto (em escrita vertical, a largura é a direção de bloco: entrelinha, não estouro)
      const vertical = /^(vertical|sideways)/.test(cs.writingMode);
      const spill = vertical ? el.scrollHeight - el.clientHeight : el.scrollWidth - el.clientWidth;
      if (!clips(vertical ? cs.overflowY : cs.overflowX) && spill > TOL && (vertical ? el.clientHeight : el.clientWidth) > 0)
        out.push({ slide: slideName, key, kind: 'spill-x', amount: spill, cut: spill });
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      const beyond = Math.max(sb.left - r.left, r.right - sb.right, sb.top - r.top, r.bottom - sb.bottom);
      if (beyond > TOL) out.push({ slide: slideName, key, kind: 'outside-slide', amount: Math.round(beyond * 10) / 10, cut: Math.round(beyond * 10) / 10 });
      const zone = el.closest<HTMLElement>('.dash-zone');
      if (zone) {
        const z = zone.getBoundingClientRect();
        const past = Math.max(z.left - r.left, r.right - z.right, z.top - r.top, r.bottom - z.bottom);
        if (past > TOL) out.push({ slide: slideName, key, kind: 'outside-zone', amount: Math.round(past * 10) / 10, cut: Math.round(past * 10) / 10 });
      }
    }
    // rótulo de categoria do gráfico (SVG) que não coube nem quebrado em linhas: abreviado ⇒ bloqueia (nunca em silêncio)
    for (const t of Array.from(slide.querySelectorAll<SVGTextElement>('text[data-abbrev]'))) {
      const full = t.dataset.abbrev ?? '';
      const amount = Math.max(1, Math.round(full.length - (t.textContent ?? '').replace('…', '').length));
      out.push({ slide: slideName, key: `axis-label:${full.slice(0, 80)}`, kind: 'ellipsis', amount, cut: amount });
    }
  }
  // um achado por (slide, chave, tipo): o maior
  const best = new Map<string, OverflowFinding>();
  for (const f of out) {
    const k = `${f.slide}|${f.key}|${f.kind}`;
    if (!best.has(k) || best.get(k)!.amount < f.amount) best.set(k, f);
  }
  return [...best.values()];
}

// ---------------------------------------------------------------- ganchos da rota #/render

declare global {
  interface Window {
    __afrikaExport?: { version: number; slides: () => number; layout: (index: number) => SlideLayout; overflow: () => OverflowFinding[] };
  }
}

export function installExportHooks(): void {
  window.__afrikaExport = {
    version: EXPORT_LAYOUT_VERSION,
    slides: () => document.querySelectorAll('[data-render-slide]').length,
    layout: (index: number) => {
      const slot = document.querySelector<HTMLElement>(`[data-render-slide="${index}"]`);
      if (!slot) throw new Error(`slide ${index} inexistente`);
      return collectLayout(slot);
    },
    overflow: () => collectOverflow(document),
  };
}
