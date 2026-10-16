// F06C — detecção de OVERFLOW e CORTES nos slides renderizados (rota #/render). Roda no DOM real da plataforma
// (Windows/DirectWrite × Linux/FreeType têm larguras de texto diferentes), então o mesmo teste no CI Linux e no
// Windows local prova que nada estoura em nenhuma das duas. Achados:
//   clipped-x / clipped-y  conteúdo maior que a caixa de um elemento que corta (overflow hidden/clip)
//   spill-x                texto mais longo que a própria caixa na direção INLINE (sem corte): vaza sobre o vizinho.
//                          (Direção de bloco não: entrelinhas apertadas fazem o glifo passar da caixa de linha.)
//   ellipsis               texto truncado com reticências (text-overflow: ellipsis) — registrado à parte
//   outside-zone           elemento com texto ultrapassa a moldura da zona do painel
//   outside-slide          elemento com texto ultrapassa o canvas do slide
// Só caixas (px) e chaves `data-el` saem daqui — nenhum texto.
import type { Page } from '@playwright/test';

export type OverflowFinding = { slide: string; key: string; kind: 'clipped-x' | 'clipped-y' | 'spill-x' | 'ellipsis' | 'outside-zone' | 'outside-slide'; amount: number };

export async function collectOverflow(page: Page): Promise<OverflowFinding[]> {
  return page.evaluate(() => {
    const out: { slide: string; key: string; kind: 'clipped-x' | 'clipped-y' | 'spill-x' | 'ellipsis' | 'outside-zone' | 'outside-slide'; amount: number }[] = [];
    const TOL = 1; // px: arredondamento de subpixel
    for (const slot of Array.from(document.querySelectorAll<HTMLElement>('[data-render-slide]'))) {
      const slideName = `${String(slot.dataset.renderSlide).padStart(2, '0')}-${slot.dataset.slideId}`;
      const slide = slot.querySelector('.slide') as HTMLElement;
      const sb = slide.getBoundingClientRect();
      const all = Array.from(slide.querySelectorAll<HTMLElement>('*'));
      for (const el of all) {
        if (!(el instanceof HTMLElement)) continue; // SVG: geometria do gráfico, avaliada pelo motor de pixels
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden') continue;
        const key = el.closest<HTMLElement>('[data-el]')?.dataset.el ?? el.className.toString().split(' ')[0] ?? el.tagName;
        const clips = (v: string) => v === 'hidden' || v === 'clip';
        const hasText = Array.from(el.childNodes).some((n) => n.nodeType === Node.TEXT_NODE && (n.textContent ?? '').trim());
        if (clips(cs.overflowX) && el.scrollWidth - el.clientWidth > TOL) {
          if (cs.textOverflow === 'ellipsis') out.push({ slide: slideName, key, kind: 'ellipsis', amount: el.scrollWidth - el.clientWidth });
          else if (hasText || el.querySelector('*')) out.push({ slide: slideName, key, kind: 'clipped-x', amount: el.scrollWidth - el.clientWidth });
        }
        if (clips(cs.overflowY) && el.scrollHeight - el.clientHeight > TOL && (hasText || el.querySelector('*')))
          out.push({ slide: slideName, key, kind: 'clipped-y', amount: el.scrollHeight - el.clientHeight });
        if (!hasText) continue;
        // direção INLINE do texto (em escrita vertical, a largura é a direção de bloco: entrelinha, não estouro)
        const vertical = /^(vertical|sideways)/.test(cs.writingMode);
        const spill = vertical ? el.scrollHeight - el.clientHeight : el.scrollWidth - el.clientWidth;
        if (!clips(vertical ? cs.overflowY : cs.overflowX) && spill > TOL && (vertical ? el.clientHeight : el.clientWidth) > 0)
          out.push({ slide: slideName, key, kind: 'spill-x', amount: spill });
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        const beyond = Math.max(sb.left - r.left, r.right - sb.right, sb.top - r.top, r.bottom - sb.bottom);
        if (beyond > TOL) out.push({ slide: slideName, key, kind: 'outside-slide', amount: Math.round(beyond * 10) / 10 });
        const zone = el.closest<HTMLElement>('.dash-zone');
        if (zone) {
          const z = zone.getBoundingClientRect();
          const past = Math.max(z.left - r.left, r.right - z.right, z.top - r.top, r.bottom - z.bottom);
          if (past > TOL) out.push({ slide: slideName, key, kind: 'outside-zone', amount: Math.round(past * 10) / 10 });
        }
      }
    }
    // um achado por (slide, chave, tipo): o maior
    const best = new Map<string, (typeof out)[number]>();
    for (const f of out) {
      const k = `${f.slide}|${f.key}|${f.kind}`;
      if (!best.has(k) || best.get(k)!.amount < f.amount) best.set(k, f);
    }
    return [...best.values()];
  });
}
