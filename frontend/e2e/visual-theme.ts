import { APIRequestContext, expect } from '@playwright/test';
import { blankImage, encodePng } from '../visual/png';

// F06B.1 — tema PRÓPRIO SINTÉTICO para a regressão visual: prova que o motor aceita temas diferentes por cliente
// (outra proporção 4:3, regiões fixas como placeholders de master PPTX, outras fontes/paleta, logotipo como ativo local,
// rodapé com texto próprio, legenda embaixo, encerramento centralizado). Não representa nenhuma marca real.

/** Logotipo sintético (PNG 144×96 gerado aqui): dois blocos geométricos. Nenhum recurso proprietário. */
export function syntheticLogo(): Buffer {
  const img = blankImage(144, 96, [0, 0, 0, 0]);
  const fill = (x0: number, y0: number, w: number, h: number, rgba: [number, number, number, number]) => {
    for (let y = y0; y < y0 + h; y++) for (let x = x0; x < x0 + w; x++) img.data.set(rgba, (y * 144 + x) * 4);
  };
  fill(8, 16, 56, 64, [18, 94, 104, 255]);
  fill(72, 32, 64, 48, [134, 68, 160, 255]);
  return Buffer.from(encodePng(img));
}

export function altTheme(logo: { asset_id: string; media_type: string }) {
  const sev = ['#3b0f4f', '#5c1f78', '#7d3a9c', '#9c5bb8', '#b981cf', '#d3aae2', '#8a8a8a'];
  return {
    name: 'Tema alternativo sintético (teste)',
    description: 'Tema sintético da regressão visual F06B.1 (4:3, regiões fixas).',
    provisional: true,
    notice: 'Tema sintético de teste — não representa identidade visual real.',
    canvas: { width: 960, height: 720 },
    colors: {
      surface: '#ffffff', page: '#f4f6f6', band: '#e6f0f1',
      'text.primary': '#132226', 'text.secondary': '#3d5257', 'text.muted': '#5f7176',
      grid: '#dde5e6', axis: '#b6c4c6', border: '#cfdadb', accent: '#125e68',
      'series.1': '#125e68', 'series.2': '#86449f', 'series.3': '#c27c0e', 'series.4': '#3f7d3a',
      'severity.VERY_HIGH': sev[0], 'severity.HIGH': sev[1], 'severity.MEDIUM': sev[2], 'severity.LOW': sev[3],
      'severity.VERY_LOW': sev[4], 'severity.INFORMATIONAL': sev[5], 'severity.UNKNOWN': sev[6],
      gap: '#8a8a8a', manual: '#8a5a00', warning: '#8a5a00', 'delta.up': '#3d5257', 'delta.down': '#3d5257',
    },
    fonts: {
      heading: { stack: ['Georgia', 'serif'], export_family: 'Georgia' },
      body: { stack: ['Verdana', 'sans-serif'], export_family: 'Verdana' },
      numeric: { stack: ['Consolas', 'monospace'], export_family: 'Consolas' },
    },
    weights: { title: 700, kpi_value: 700 },
    sizes: { title: 30, subtitle: 17, body: 16, bullet: 17, caption: 13, kpi_value: 40, kpi_value_compact: 28, table: 15, table_header: 13, ranking: 14, axis: 12, value_label: 12, legend: 13, severity: 15, cover_title: 44 },
    spacing: { block_gap: 12, card_gap: 14, column_gap: 20 },
    radii: { card: 2, bar: 0, track: 0, swatch: 0 },
    layout: {
      mode: 'fixed',
      body: { x: 48, y: 96, w: 864, h: 528 },
      header: { x: 48, y: 96, w: 864, h: 80 },
      content: { x: 48, y: 184, w: 864, h: 440 },
      footer: { x: 48, w: 864, bottom: 16, reserve: 30 },
      visual_side_ratio: [3, 2],
    },
    header: { accent_bar: false, align: 'left' },
    footer: { items: ['custom_text', 'owner_competence', 'provisional', 'page'], separator: false, custom_text: 'Rodapé sintético de teste' },
    cover: { band: 'top', band_size: 12, band_color: 'series.2', padding: { top: 200, right: 64, bottom: 64, left: 64 }, align: 'left', kicker_uppercase: false },
    closing: { align: 'center' },
    backgrounds: { default: { color: 'surface' }, cover: { color: 'band' }, closing: { color: 'page' } },
    images: [
      { name: 'logo', asset: logo, box: { x: 840, y: 24, w: 72, h: 48 }, slides: ['content', 'closing'], alt: 'Logotipo sintético' },
      { name: 'logo-capa', asset: logo, box: { x: 64, y: 64, w: 144, h: 96 }, slides: ['cover'], alt: 'Logotipo sintético' },
    ],
    charts: { plot_width: 864, plot_width_with_text: 500, plot_padding: { top: 24, right: 40, bottom: 56, left: 56 }, plot_height: 340, plot_max_height: 360, bar_max_width: 40, bar_radius: 0, line_width: 2, point_radius: 4, legend_position: 'bottom', severity_label_width: 150, severity_value_width: 70, severity_bar_height: 20, rank_bar_max: 120 },
  };
}

export async function ensureAltTheme(request: APIRequestContext): Promise<{ id: string; version: number }> {
  const up = await request.post('/api/theme-assets', { data: syntheticLogo(), headers: { 'Content-Type': 'application/octet-stream' } });
  expect(up.status(), await up.text()).toBe(201);
  const { asset_id, media_type } = await up.json();
  expect(media_type).toBe('image/png');
  const logo = { asset_id, media_type };
  const r = await request.post('/api/presentation-themes', { data: { key: 'visual-alt', definition: altTheme(logo), operator: 'Operadora Visual Sintética' } });
  expect([201, 409], await r.text()).toContain(r.status()); // 409 = já existe neste banco
  return { id: 'visual-alt', version: 1 };
}
