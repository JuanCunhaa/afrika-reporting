import type React from 'react';
import type { AssetRef, Background, Box, FontSpec, Theme } from '../presentationsApi';

// F06B.1 — tradução dos tokens do tema em variáveis CSS e estilos de região. Os componentes do slide só usam estas
// variáveis/estilos: nenhum valor visual (cor, tamanho, espaçamento, posição) fica codificado neles.

const GENERIC = new Set(['system-ui', '-apple-system', 'sans-serif', 'serif', 'monospace', 'ui-sans-serif', 'ui-serif']);

/** Pilha de fontes CSS. Nomes já validados no backend (sem aspas/vírgulas); nomes com espaço vão entre aspas. */
export function fontStack(spec: FontSpec): string {
  return spec.stack.map((f) => (GENERIC.has(f) || /^-?[A-Za-z][A-Za-z0-9-]*$/.test(f) ? f : `"${f}"`)).join(', ');
}

export const assetUrl = (ref: AssetRef) => `/api/theme-assets/${ref.asset_id}`;
export const colorVar = (token: string) => `var(--c-${token.replace(/\./g, '-')})`;
const kebab = (s: string) => s.replace(/_/g, '-');
const px = (n: number) => `${n}px`;

export function themeVars(t: Theme): Record<string, string> {
  const v: Record<string, string> = {};
  for (const [k, c] of Object.entries(t.colors)) v[`--c-${k.replace(/\./g, '-')}`] = c;
  for (const role of ['heading', 'body', 'numeric'] as const) v[`--ff-${role}`] = fontStack(t.fonts[role]);
  for (const [k, n] of Object.entries(t.sizes)) v[`--fs-${kebab(k)}`] = px(n);
  for (const [k, n] of Object.entries(t.weights)) v[`--fw-${kebab(k)}`] = String(n);
  for (const [k, n] of Object.entries(t.line_heights)) v[`--lh-${kebab(k)}`] = String(n);
  for (const [k, n] of Object.entries(t.spacing)) v[`--sp-${kebab(k)}`] = k.endsWith('_em') ? `${n}em` : px(n);
  for (const [k, n] of Object.entries(t.radii)) v[`--r-${kebab(k)}`] = px(n);
  for (const [k, n] of Object.entries(t.borders)) v[`--b-${kebab(k)}`] = px(n);
  const h = t.header;
  v['--hdr-accent-width'] = px(h.accent_bar ? h.accent_width : 0);
  v['--hdr-accent-color'] = colorVar(h.accent_color);
  v['--hdr-padding-left'] = px(h.accent_bar ? h.padding_left : 0);
  v['--hdr-align'] = h.align;
  v['--ul-left'] = h.align === 'center' ? '50%' : '0px';
  v['--ul-shift'] = h.align === 'center' ? '-50%' : '0px';
  v['--ul-ml'] = h.align === 'center' ? 'auto' : '0px';
  v['--ul-mr'] = 'auto';
  v['--ftr-rule'] = px(t.footer.separator ? t.borders.footer_rule : 0);
  const c = t.cover;
  v['--cov-band-size'] = px(c.band_size);
  v['--cov-band-color'] = colorVar(c.band_color);
  v['--cov-direction'] = c.band === 'top' ? 'column' : 'row';
  v['--cov-padding'] = `${px(c.padding.top)} ${px(c.padding.right)} ${px(c.padding.bottom)} ${px(c.padding.left)}`;
  v['--cov-gap'] = px(c.gap);
  v['--cov-meta-top'] = px(c.meta_top);
  v['--cov-align'] = c.align;
  v['--cov-kicker-transform'] = c.kicker_uppercase ? 'uppercase' : 'none';
  const cl = t.closing;
  v['--clo-padding'] = `${px(cl.padding.top)} ${px(cl.padding.right)} ${px(cl.padding.bottom)} ${px(cl.padding.left)}`;
  v['--clo-gap'] = px(cl.gap);
  v['--clo-align'] = cl.align;
  v['--clo-items'] = cl.align === 'center' ? 'center' : 'flex-start';
  const ch = t.charts;
  v['--ch-plot-max-h'] = px(ch.plot_max_height);
  v['--ch-swatch'] = px(ch.swatch_size);
  v['--ch-swatch-gap'] = px(ch.swatch_gap);
  v['--ch-swatch-offset'] = px(ch.swatch_baseline_offset);
  v['--ch-sev-cols'] = `${px(ch.severity_label_width)} 1fr ${px(ch.severity_value_width)}`;
  v['--ch-sev-bar-h'] = px(ch.severity_bar_height);
  v['--ch-rank-bar-h'] = px(ch.rank_bar_height);
  v['--ch-rank-bar-gap'] = px(ch.rank_bar_gap);
  v['--ch-min-bar'] = px(ch.min_bar);
  v['--ch-texture'] = `repeating-linear-gradient(45deg,transparent 0 ${px(ch.texture_stripe)},rgba(255,255,255,${ch.texture_opacity}) ${px(ch.texture_stripe)} ${px(ch.texture_period)})`;
  v['--lay-visual'] = String(t.layout.visual_side_ratio[0]);
  v['--lay-side'] = String(t.layout.visual_side_ratio[1]);
  v['--lay-summary-cols'] = `${t.layout.summary_ratio[0]}fr ${t.layout.summary_ratio[1]}fr`;
  // F06B — componentes (padrões = visual F06A do tema neutro)
  const k = t.components;
  v['--title-color'] = colorVar(k.title_color);
  v['--cov-title-color'] = colorVar(k.cover_title_color);
  v['--cov-kicker-color'] = colorVar(k.cover_kicker_color);
  v['--card-fill'] = colorVar(k.card.fill);
  v['--card-border'] = colorVar(k.card.border);
  v['--card-bw'] = px(k.card.border_width);
  v['--card-radius'] = px(k.card.radius);
  v['--card-py'] = px(k.card.padding_y);
  v['--card-px'] = px(k.card.padding_x);
  v['--card-title-size'] = px(k.card.title_size);
  v['--card-title-color'] = colorVar(k.card.title_color);
  v['--band-fill'] = colorVar(k.band.fill);
  v['--band-radius'] = px(k.band.radius);
  v['--band-pad'] = px(k.band.padding);
  v['--band-label'] = colorVar(k.band.label_color);
  v['--pill-fill'] = colorVar(k.pill.fill);
  v['--cmp-fill'] = colorVar(k.comparison_fill);
  v['--pill-color'] = colorVar(k.pill.color);
  v['--pill-radius'] = px(k.pill.radius);
  v['--pill-size'] = px(k.pill.size);
  v['--pill-pad'] = `${px(k.pill.padding_y)} ${px(k.pill.padding_x)}`;
  v['--tbl-th-bg'] = k.table.header_fill ? colorVar(k.table.header_fill) : 'transparent';
  v['--tbl-th-color'] = colorVar(k.table.header_color);
  v['--tbl-th-rule'] = colorVar(k.table.header_rule);
  v['--tbl-td-rule'] = colorVar(k.table.row_rule);
  v['--tbl-zebra'] = k.table.zebra_fill ? colorVar(k.table.zebra_fill) : 'transparent';
  v['--sec-title'] = colorVar(k.section.title_color);
  v['--sec-sub'] = colorVar(k.section.subtitle_color);
  v['--sec-title-size'] = px(k.section.title_size);
  v['--sec-sub-size'] = px(k.section.subtitle_size);
  v['--clo-title'] = colorVar(k.closing.title);
  v['--clo-text'] = colorVar(k.closing.text);
  v['--clo-accent'] = colorVar(k.closing.accent);
  v['--sev-bar-w'] = px(k.severity_bar_width);
  v['--cov-justify'] = k.cover_valign === 'bottom' ? 'flex-end' : 'flex-start';
  v['--cov-title-ff'] = `var(--ff-${k.cover_title_font})`;
  v['--cov-kicker-ff'] = `var(--ff-${k.cover_kicker_font})`;
  v['--cov-kicker-fw'] = String(k.cover_kicker_weight);
  v['--clo-title-ff'] = `var(--ff-${k.closing.title_font})`;
  v['--clo-title-fw'] = k.closing.title_weight ? String(k.closing.title_weight) : 'var(--fw-cover-title)';
  v['--clo-title-size'] = k.closing.title_size ? px(k.closing.title_size) : 'var(--fs-cover-title)';
  v['--clo-justify'] = k.closing.valign === 'top' ? 'flex-start' : 'center';
  // F06C — semântica de variação (só quando o tema declara; sem ela a pílula continua neutra)
  if (t.semantics?.variation) v['--trend-tint'] = `${Math.round(t.semantics.variation.tint_opacity * 100)}%`;
  // F06C — subtítulo e rótulo da matriz (só quando o tema declara; sem eles o CSS cai no visual F06B)
  if (k.subtitle_color) v['--sub-color'] = colorVar(k.subtitle_color);
  if (k.subtitle_font) v['--sub-ff'] = `var(--ff-${k.subtitle_font})`;
  if (k.subtitle_weight) v['--sub-fw'] = String(k.subtitle_weight);
  if (k.subtitle_line_height) v['--sub-lh'] = String(k.subtitle_line_height);
  if (k.matrix_label_size) v['--mx-label-size'] = px(k.matrix_label_size);
  return v;
}

export type ResolvedLayout = { mode: 'flow' | 'fixed'; body: Box; header: Box | null; content: Box | null; background: Background | null; hideFooter: boolean };

export function layoutFor(t: Theme, layout: string): ResolvedLayout {
  const o = t.layouts[layout];
  return {
    mode: o?.mode ?? t.layout.mode,
    body: o?.body ?? t.layout.body,
    header: o?.header ?? t.layout.header,
    content: o?.content ?? t.layout.content,
    background: o?.background ?? null,
    hideFooter: o?.hide_footer ?? false,
  };
}

export const boxStyle = (b: Box): React.CSSProperties => ({ left: b.x, top: b.y, width: b.w, height: b.h });

export type SlideKind = 'cover' | 'closing' | 'content' | 'section';
export const slideKind = (type: string): SlideKind => (type === 'cover' ? 'cover' : type === 'closing' ? 'closing' : type === 'section' ? 'section' : 'content');

export function backgroundStyle(t: Theme, kind: SlideKind, layout: ResolvedLayout): React.CSSProperties {
  const section: Background = { color: t.components.section.background, image: null, fit: 'cover' };
  const bg = layout.background ?? (kind === 'cover' ? t.backgrounds.cover : kind === 'closing' ? t.backgrounds.closing : kind === 'section' ? section : null) ?? t.backgrounds.default;
  const out: React.CSSProperties = {};
  if (bg.color) out.background = colorVar(bg.color);
  if (bg.image) {
    out.backgroundImage = `url("${assetUrl(bg.image)}")`;
    out.backgroundSize = bg.fit;
    out.backgroundPosition = 'center';
    out.backgroundRepeat = 'no-repeat';
  }
  return out;
}

/** Competência 'AAAA-MM' -> ['SET', '2026'] (formatação do rótulo; nenhum dado é calculado). */
export function competenceParts(label: string): [string, string] {
  const months = ['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN', 'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ'];
  const [y, m] = label.split('-');
  return [months[Number(m) - 1] ?? m, y];
}

/** @font-face das fontes do tema com arquivo local (uma vez por tema no documento). */
export function fontFaceCss(t: Theme): string {
  const formats: Record<string, string> = { 'font/woff2': 'woff2', 'font/woff': 'woff', 'font/ttf': 'truetype', 'font/otf': 'opentype' };
  const seen = new Set<string>();
  const rules: string[] = [];
  for (const role of ['heading', 'body', 'numeric'] as const) {
    const spec = t.fonts[role];
    if (!spec.asset || GENERIC.has(spec.stack[0]) || seen.has(spec.stack[0])) continue;
    seen.add(spec.stack[0]);
    rules.push(`@font-face{font-family:"${spec.stack[0]}";src:url("${assetUrl(spec.asset)}") format("${formats[spec.asset.media_type] ?? 'woff2'}");font-display:block}`);
  }
  return rules.join('\n');
}
