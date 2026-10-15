import React, { useEffect, useRef, useState } from 'react';
import { errorMessage } from '../api';
import { ReportJob, reporting } from '../snapshotsApi';
import { Empty, ErrorBox, Loading, fmtDate, useLoad } from '../ui';
import { Badge, Owner, OwnerPicker } from './OwnerPicker';

// F05: Reporting API. A geração de relatório é a ÚNICA escrita autorizada na Veracode e fica desligada por padrão.
// Agregados são exploratórios (não são indicadores do catálogo nem números de dashboard).

const JOB_LABEL: Record<ReportJob['status'], string> = {
  pending: 'Na fila',
  processing: 'Processando na Veracode',
  fetching: 'Lendo páginas',
  done: 'Concluído',
  failed: 'Falhou',
  cancelled: 'Cancelado',
};
const JOB_CLASS: Record<ReportJob['status'], string> = {
  pending: 'off',
  processing: 'warn',
  fetching: 'warn',
  done: 'ok',
  failed: 'bad',
  cancelled: 'off',
};

const isoDay = (d: Date) => d.toISOString().slice(0, 10);

export function ReportingPage() {
  const status = useLoad(() => reporting.status(), []);
  const jobs = useLoad(() => reporting.list(), []);
  const [owner, setOwner] = useState<Owner | null>(null);
  const [type, setType] = useState('FINDINGS');
  const today = new Date();
  const [start, setStart] = useState(isoDay(new Date(today.getTime() - 7 * 86400_000)));
  const [end, setEnd] = useState(isoDay(today));
  const [appId, setAppId] = useState('');
  const [context, setContext] = useState('');
  const [error, setError] = useState('');
  const timer = useRef<number | undefined>(undefined);

  const running = (jobs.data?.items ?? []).some((j) => !['done', 'failed', 'cancelled'].includes(j.status));
  useEffect(() => {
    if (!running) return;
    timer.current = window.setTimeout(jobs.reload, 1000);
    return () => window.clearTimeout(timer.current);
  }, [running, jobs.data, jobs.reload]);

  if (status.error) return <ErrorBox message={status.error} onRetry={status.reload} />;
  if (!status.data) return <Loading label="Carregando política da Reporting API…" />;
  const st = status.data;

  const start_ = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!owner) return;
    setError('');
    const req: Record<string, unknown> = { report_type: type, last_updated_start_date: start, last_updated_end_date: end };
    if (appId) req.app_id = Number(appId);
    if (context) req.policy_sandbox = context;
    if (type === 'SCANS') req.most_recent_scan = true;
    try {
      await reporting.start(owner.kind, owner.id, req);
      jobs.reload();
      status.reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <section>
      <h2>Reporting API</h2>
      <div className="panel" data-testid="reporting-status">
        <p>
          Geração de relatórios: <Badge cls={st.enabled ? 'ok' : 'off'}>{st.enabled ? 'habilitada' : 'desabilitada'}</Badge> · modo {st.mode} ·
          cota restante nesta hora: {st.quota_left_this_hour}
        </p>
        <ul className="plain">
          {st.allowed_operations.map((o) => (
            <li key={o}>
              <code>{o}</code>
            </li>
          ))}
        </ul>
        <small className="muted">
          Tipos habilitados: {st.enabled_types.join(', ')} · não habilitados: {Object.keys(st.not_enabled_types).join(', ')} · janela máxima{' '}
          {st.limits.max_window_days} dias · até {st.limits.max_pages} páginas. Nenhuma outra escrita é permitida.
        </small>
      </div>
      {st.enabled ? (
        <form className="form panel" onSubmit={start_} aria-label="Gerar relatório">
          <OwnerPicker prefix="rp" onChange={setOwner} />
          <div className="field">
            <label htmlFor="rp-type">Tipo</label>
            <select id="rp-type" value={type} onChange={(e) => setType(e.target.value)}>
              {st.enabled_types.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="rp-start">Atualizados a partir de (UTC)</label>
            <input id="rp-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="rp-end">Até (UTC)</label>
            <input id="rp-end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="rp-app">ID numérico da aplicação (opcional)</label>
            <input id="rp-app" inputMode="numeric" value={appId} onChange={(e) => setAppId(e.target.value.replace(/\D/g, ''))} />
          </div>
          <div className="field">
            <label htmlFor="rp-context">Contexto</label>
            <select id="rp-context" value={context} onChange={(e) => setContext(e.target.value)}>
              <option value="">Policy e Sandbox</option>
              <option value="Policy">Policy (produção)</option>
              <option value="Sandbox">Sandbox (desenvolvimento)</option>
            </select>
          </div>
          <div className="actions">
            <button className="btn primary" type="submit" disabled={!owner || running}>
              Gerar relatório
            </button>
          </div>
        </form>
      ) : (
        <p className="muted">Para habilitar (somente com autorização): AFRIKA_VERACODE_REPORTING_ENABLED=true no ambiente do backend.</p>
      )}
      {error && <ErrorBox message={error} />}
      <div className="panel" aria-label="Execuções de relatório">
        <h3>Execuções</h3>
        {(jobs.data?.items ?? []).length === 0 && <Empty>Nenhuma execução nesta sessão do backend.</Empty>}
        {(jobs.data?.items ?? []).map((j) => (
          <article key={j.job_id} className="panel" data-testid={`job-${j.job_id}`}>
            <div className="toolbar">
              <h4>
                {j.report_type} · {j.owner.name}
              </h4>
              <Badge cls={JOB_CLASS[j.status]} testId="job-status">
                {JOB_LABEL[j.status]}
              </Badge>
              {!['done', 'failed', 'cancelled'].includes(j.status) && (
                <button className="btn" type="button" onClick={() => reporting.cancel(j.job_id).then(jobs.reload).catch((e) => setError(errorMessage(e)))}>
                  Cancelar
                </button>
              )}
            </div>
            <small className="muted">
              {fmtDate(j.created_at)} · {String(j.request.last_updated_start_date)} → {String(j.request.last_updated_end_date)} · Veracode:{' '}
              {j.veracode.veracode_status ?? '—'} · consultas {j.progress.polls} · páginas {j.progress.pages_fetched}
              {j.progress.total_pages !== undefined && `/${j.progress.total_pages}`} · requisições {j.usage.requests ?? '—'}
            </small>
            {j.error && <ErrorBox message={`${j.error.message}${j.error.hint ? ` — ${j.error.hint}` : ''}`} />}
            {j.remote_note && <p className="muted">{j.remote_note}</p>}
            {j.result && (
              <>
                <p data-testid="job-result">
                  {j.result.complete ? 'Completo' : 'INCOMPLETO'} · {j.result.items_processed} item(ns) contados · {j.result.aggregates_status}
                </p>
                <pre className="rule-json">{JSON.stringify(j.result.aggregates, null, 1)}</pre>
                <ul className="warnings">
                  {j.result.caveats.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              </>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}
