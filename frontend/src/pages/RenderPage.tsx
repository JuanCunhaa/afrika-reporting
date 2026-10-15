import React, { useEffect, useState } from 'react';
import { errorMessage } from '../api';
import { SlideSurface } from '../presentation/SlideView';
import { PresentationView, presentations } from '../presentationsApi';

// F06B.1 — renderização DETERMINÍSTICA para captura/regressão visual: todos os slides empilhados em tamanho nativo
// (escala 1, sem a interface do editor). Somente leitura. `data-render-ready` só é marcado depois que as fontes e as
// imagens do tema terminaram de carregar, para a captura não pegar estado intermediário.
export function RenderPage({ pid, revision }: { pid: string; revision?: number }) {
  const [view, setView] = useState<PresentationView | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    presentations
      .view(pid, revision)
      .then(setView)
      .catch((e) => setError(errorMessage(e)));
  }, [pid, revision]);

  useEffect(() => {
    if (!view) return;
    let alive = true;
    const images = Array.from(document.querySelectorAll<HTMLImageElement>('.render-stack img'));
    Promise.all([document.fonts.ready, ...images.map((img) => (img.complete ? Promise.resolve() : img.decode().catch(() => undefined)))])
      // dois quadros: o re-render pós-fontes (medição de rótulos) precisa estar pintado antes do sinal de pronto
      .then(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))))
      .then(() => {
        if (alive) document.documentElement.dataset.renderReady = '1';
      });
    return () => {
      alive = false;
      delete document.documentElement.dataset.renderReady;
    };
  }, [view]);

  if (error)
    return (
      <p role="alert" data-testid="render-error">
        {error}
      </p>
    );
  if (!view) return <p role="status">Carregando…</p>;
  const { width, height } = view.theme.canvas;
  return (
    <div className="render-stack" data-theme={`${view.theme.id}@${view.theme.version}`}>
      {view.slides.map((s) => (
        <div key={s.slide_id} className="render-slot" style={{ width, height }} data-render-slide={s.index} data-slide-id={s.slide_id}>
          <SlideSurface view={view} slide={s} />
        </div>
      ))}
    </div>
  );
}
