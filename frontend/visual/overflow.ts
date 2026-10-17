// F06C — detecção de OVERFLOW e CORTES nos slides renderizados (rota #/render). Roda no DOM real da plataforma
// (Windows/DirectWrite × Linux/FreeType têm larguras de texto diferentes), então o mesmo teste no CI Linux e no
// Windows local prova que nada estoura em nenhuma das duas.
// F07: a regra mora no próprio app (`src/presentation/exportLayout.ts`, `window.__afrikaExport.overflow()`), para a
// pré-visualização, a regressão visual e o bloqueio da exportação usarem EXATAMENTE o mesmo detector. Achados:
//   clipped-x / clipped-y  conteúdo maior que a caixa de um elemento que corta (overflow hidden/clip)
//   spill-x                texto mais longo que a própria caixa na direção INLINE (sem corte): vaza sobre o vizinho.
//   ellipsis               texto truncado com reticências (text-overflow: ellipsis) — registrado à parte
//   outside-zone           elemento com texto ultrapassa a moldura da zona do painel
//   outside-slide          elemento com texto ultrapassa o canvas do slide
// Só caixas (px) e chaves `data-el` saem daqui — nenhum texto.
import type { Page } from '@playwright/test';

export type OverflowFinding = { slide: string; key: string; kind: 'clipped-x' | 'clipped-y' | 'spill-x' | 'ellipsis' | 'outside-zone' | 'outside-slide'; amount: number; cut: number };

export async function collectOverflow(page: Page): Promise<OverflowFinding[]> {
  return page.evaluate(() => {
    const hook = (window as unknown as { __afrikaExport?: { overflow: () => OverflowFinding[] } }).__afrikaExport;
    if (!hook) throw new Error('ganchos de exportação ausentes: a página não é a rota #/render');
    return hook.overflow();
  });
}
