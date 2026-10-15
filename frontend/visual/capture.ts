// F06B.1 — captura determinística dos slides HTML (Playwright/Chromium) + manifesto de layout.
// Determinismo: rota `#/render/{id}` (sem interface do editor), escala 1, viewport = tamanho do canvas do tema,
// deviceScaleFactor 1 (padrão do contexto), animações desativadas, cursor oculto, espera de fontes e imagens
// (`data-render-ready`). Fontes de plataforma reais via CDP (CSS.getPlatformFontsForNode) para separar diferença de
// fonte de diferença de layout. O texto dos elementos NÃO é gravado: só hash e tamanho.
import { createHash } from 'node:crypto';
import type { Page } from '@playwright/test';
import { type Image, decodePng } from './png.ts';
import type { ElementInfo, SlideManifest } from './manifest.ts';

export type CapturedSlide = { name: string; png: Buffer; image: Image; manifest: SlideManifest };

type RawElement = Omit<ElementInfo, 'text_hash' | 'platform_fonts'> & { text: string };

const hash = (s: string) => createHash('sha256').update(s, 'utf8').digest('hex').slice(0, 16);

export async function captureSlides(page: Page, pid: string, caseName: string, opts: { fonts?: boolean } = {}): Promise<CapturedSlide[]> {
  await page.goto(`/#/render/${pid}`);
  await page.locator('html[data-render-ready="1"]').waitFor({ state: 'attached', timeout: 15_000 });
  const theme = await page.locator('.render-stack').getAttribute('data-theme');
  const [themeId, themeVersion] = (theme ?? '@').split('@');
  const slots = page.locator('[data-render-slide]');
  const count = await slots.count();
  const cdp = opts.fonts === false ? null : await page.context().newCDPSession(page);
  if (cdp) {
    await cdp.send('DOM.enable');
    await cdp.send('CSS.enable');
  }
  const out: CapturedSlide[] = [];
  for (let i = 0; i < count; i++) {
    const slot = slots.nth(i);
    const index = Number(await slot.getAttribute('data-render-slide'));
    const slideId = (await slot.getAttribute('data-slide-id')) ?? String(index);
    const png = await slot.screenshot({ animations: 'disabled', caret: 'hide', scale: 'css' });
    const raw = await slot.evaluate((root) => {
      const base = root.getBoundingClientRect();
      const seen = new Map<string, number>();
      const slide = root.querySelector('.slide') as HTMLElement;
      return {
        type: [...slide.classList].find((c) => c.startsWith('slide-') && c !== 'slide')?.slice(6) ?? '',
        layout: [...slide.classList].find((c) => c.startsWith('layout-'))?.slice(7) ?? '',
        canvas: { width: slide.offsetWidth, height: slide.offsetHeight },
        elements: [...root.querySelectorAll<HTMLElement>('[data-el]')].map((el) => {
          const k = el.dataset.el as string;
          const n = (seen.get(k) ?? 0) + 1;
          seen.set(k, n);
          const r = el.getBoundingClientRect();
          const cs = getComputedStyle(el);
          const text = (el.textContent ?? '').replace(/\s+/g, ' ').trim();
          const round = (v: number) => Math.round(v * 100) / 100;
          return {
            key: n > 1 ? `${k}#${n}` : k,
            role: k.split(':')[0],
            box: { x: round(r.left - base.left), y: round(r.top - base.top), w: round(r.width), h: round(r.height) },
            text,
            text_length: text.length,
            font: text ? { family: cs.fontFamily, size: parseFloat(cs.fontSize), weight: cs.fontWeight, style: cs.fontStyle } : null,
            color: cs.color,
            background: cs.backgroundColor === 'rgba(0, 0, 0, 0)' ? null : cs.backgroundColor,
          };
        }),
      };
    });
    let platform: (string[] | null)[] = raw.elements.map(() => null);
    if (cdp) {
      const { root } = await cdp.send('DOM.getDocument', { depth: 0 });
      const { nodeIds } = await cdp.send('DOM.querySelectorAll', { nodeId: root.nodeId, selector: `[data-render-slide="${index}"] [data-el]` });
      platform = await Promise.all(
        nodeIds.map(async (nodeId) => {
          const { fonts } = await cdp.send('CSS.getPlatformFontsForNode', { nodeId });
          return fonts.map((f) => f.familyName).sort();
        }),
      );
    }
    const elements: ElementInfo[] = (raw.elements as RawElement[]).map(({ text, ...e }, k) => ({ ...e, text_hash: text ? hash(text) : null, platform_fonts: platform[k] ?? null }));
    const name = `${String(index).padStart(2, '0')}-${slideId}`;
    out.push({
      name,
      png,
      image: decodePng(png),
      manifest: {
        manifest_version: 1,
        case: caseName,
        slide: { index, slide_id: slideId, type: raw.type, layout: raw.layout },
        canvas: raw.canvas,
        theme: themeId ? { id: themeId, version: Number(themeVersion) } : null,
        elements,
      },
    });
  }
  if (cdp) await cdp.detach();
  return out;
}
