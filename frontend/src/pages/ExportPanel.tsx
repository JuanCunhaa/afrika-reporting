import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, errorMessage } from '../api';
import { ExportEngine, ExportFormat, ExportJob, exportsApi } from '../presentationsApi';

// F07 — exportação PPTX (editável) e PDF da revisão PERSISTIDA. Com alterações não salvas a exportação fica bloqueada
// (salve antes): o pedido sempre informa explicitamente o número da revisão salva, sem ambiguidade. O servidor recusa
// fonte não aprovada, referências não íntegras e conteúdo que não cabe (diagnóstico por slide).

const STATUS: Record<ExportJob['status'], string> = { queued: 'Na fila', running: 'Gerando…', done: 'Concluída', failed: 'Falhou' };
const NAME: Record<ExportFormat, string> = { pptx: 'PowerPoint (.pptx)', pdf: 'PDF' };

function summary(job: ExportJob): string {
  const r = job.report as { content?: { slides: number; editable_objects: number; objects: Record<string, number>; images: number }; pdf?: { pages: number; fonts: string[] } };
  if (job.format === 'pptx' && r.content)
    return `PPTX validado: ${r.content.slides} slides · ${r.content.editable_objects} objetos editáveis (${r.content.objects.chart} gráficos nativos, ${r.content.objects.table} tabelas) · ${r.content.images} imagem(ns)`;
  if (job.format === 'pdf' && r.pdf) return `PDF validado: ${r.pdf.pages} páginas · fontes incorporadas (${r.pdf.fonts.join(', ')})`;
  return '';
}

export function ExportPanel({ pid, revision, dirty, ready, blockers, operator }: { pid: string; revision: number; dirty: boolean; ready: boolean; blockers: number; operator: string }) {
  const [engine, setEngine] = useState<ExportEngine | null>(null);
  const [jobs, setJobs] = useState<ExportJob[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const r = await exportsApi.list(pid);
      if (alive.current) setJobs(r.items);
    } catch {
      /* lista é informativa: falha transitória não interrompe o editor */
    }
  }, [pid]);

  useEffect(() => {
    alive.current = true;
    exportsApi
      .engine()
      .then((e) => alive.current && setEngine(e))
      .catch(() => alive.current && setEngine({ available: false, formats: [], renderer: { ok: false, message: 'Motor de exportação inacessível' }, browser: { ok: false } }));
    void refresh();
    return () => {
      alive.current = false;
    };
  }, [refresh]);

  const active = jobs.some((j) => j.status === 'queued' || j.status === 'running');
  useEffect(() => {
    if (!active) return;
    const t = window.setInterval(() => void refresh(), 700);
    return () => window.clearInterval(t);
  }, [active, refresh]);

  const start = async (format: ExportFormat) => {
    setBusy(true);
    setError(null);
    try {
      const job = await exportsApi.create(pid, format, revision, operator);
      setJobs((cur) => [job, ...cur.filter((j) => j.id !== job.id)]);
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, 'error', errorMessage(e)));
    } finally {
      setBusy(false);
    }
  };

  const opValid = operator.trim().length >= 2;
  const reason = dirty
    ? 'Há alterações não salvas: salve a revisão para exportá-la (a exportação usa sempre uma revisão salva).'
    : !ready
      ? `Exportação indisponível: ${blockers} bloqueio(s) na apresentação (indicadores obrigatórios sem valor aprovado).`
      : engine && !engine.available
        ? `Motor de exportação indisponível: ${[engine.renderer.ok ? '' : engine.renderer.message, engine.browser.ok ? '' : engine.browser.message].filter(Boolean).join(' ')}`
        : !opValid
          ? 'Informe o operador (campo do documento) para registrar a exportação.'
          : '';
  const disabled = busy || !!reason || !engine;

  return (
    <div className="panel" aria-label="Exportação" data-testid="export-panel">
      <h3>Exportar</h3>
      <p className="muted">
        Exporta a <strong>revisão salva {revision}</strong>: PowerPoint editável (textos, formas, tabelas e gráficos nativos com dados incorporados) ou PDF com as fontes incorporadas. Os valores são os das revisões aprovadas fixadas; nada é recalculado.
      </p>
      {reason && (
        <p className="notice" role="status" data-testid={dirty ? 'export-dirty' : 'export-unavailable'}>
          {reason}
        </p>
      )}
      <div className="actions">
        <button type="button" className="btn primary" disabled={disabled} onClick={() => void start('pptx')} data-testid="export-pptx">
          Exportar PowerPoint
        </button>
        <button type="button" className="btn" disabled={disabled} onClick={() => void start('pdf')} data-testid="export-pdf">
          Exportar PDF
        </button>
      </div>
      {error && (
        <div role="alert" className="error-box" data-testid="export-error">
          <span>
            {error.message}
            {error.details.length > 0 && (
              <ul>
                {error.details.map((d, i) => (
                  <li key={i}>{d.field ? `${d.field}: ${d.message}` : d.message}</li>
                ))}
              </ul>
            )}
          </span>
        </div>
      )}
      {jobs.length > 0 && (
        <table aria-label="Exportações" data-testid="export-jobs">
          <thead>
            <tr>
              <th>Formato</th>
              <th>Revisão</th>
              <th>Situação</th>
              <th>Arquivo / detalhes</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.id} data-testid={`export-job-${j.format}`} data-status={j.status}>
                <td>{NAME[j.format]}</td>
                <td>{j.revision}</td>
                <td data-testid="export-status">{STATUS[j.status]}</td>
                <td>
                  {j.status === 'done' && j.download_url && (
                    <>
                      <a href={j.download_url} download={j.filename ?? undefined} data-testid={`export-download-${j.format}`}>
                        Baixar {j.filename}
                      </a>{' '}
                      <small className="muted">
                        {Math.round((j.size ?? 0) / 1024)} KB · SHA-256 {j.sha256?.slice(0, 12)}… · {j.timings.total_s?.toFixed(1)} s
                      </small>
                      <div className="muted">{summary(j)}</div>
                    </>
                  )}
                  {j.status === 'failed' && j.error && (
                    <div className="error-box" data-testid="export-job-error">
                      <span>
                        {j.error.message}
                        {j.error.details.length > 0 && (
                          <ul>
                            {j.error.details.slice(0, 20).map((d, i) => (
                              <li key={i}>{d.field ? `${d.field}: ${d.message}` : d.message}</li>
                            ))}
                          </ul>
                        )}
                      </span>
                    </div>
                  )}
                  {j.warnings.length > 0 && (
                    <ul className="warnings">
                      {j.warnings.map((w, i) => (
                        <li key={i}>[aviso] {w.message}</li>
                      ))}
                    </ul>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
