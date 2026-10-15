import React, { useEffect, useRef, useState } from 'react';
import { Client, MetricRow, MetricRun, MetricStatus, Subclient, api, errorMessage, metrics } from '../api';
import { Empty, ErrorBox, Loading, fmtDate, useLoad } from '../ui';

// F04: painel inicial de indicadores. A coleta só começa por ação explícita do usuário; os números vêm do
// backend com status, fonte, filtros e proveniência. Valor só aparece como definitivo quando VALIDATED.

export const STATUS_LABEL: Record<MetricStatus, string> = {
  VALIDATED: 'Validado',
  INCOMPLETE: 'Incompleto',
  UNAVAILABLE: 'Indisponível',
  UNSUPPORTED: 'Não suportado',
  FAILED: 'Falhou',
};
const STATUS_CLASS: Record<MetricStatus, string> = {
  VALIDATED: 'ok',
  INCOMPLETE: 'warn',
  UNAVAILABLE: 'off',
  UNSUPPORTED: 'off',
  FAILED: 'bad',
};
const RUN_LABEL: Record<MetricRun['status'], string> = {
  pending: 'Na fila',
  running: 'Em execução',
  done: 'Concluída',
  cancelled: 'Cancelada',
  failed: 'Falhou',
};
const SEVERITIES = [
  ['VERY_HIGH', 'Muito alta'],
  ['HIGH', 'Alta'],
  ['MEDIUM', 'Média'],
  ['LOW', 'Baixa'],
  ['VERY_LOW', 'Muito baixa'],
  ['INFORMATIONAL', 'Informativa'],
  ['UNKNOWN', 'Sem severidade'],
] as const;
const TEMPORAL_LABEL = {
  CURRENT_STATE: 'Estado atual (data da coleta)',
  EVENT_IN_PERIOD: 'Eventos na competência',
  STATE_AT_PERIOD_END: 'Estado no fechamento da competência',
};
const DOMAINS = [
  ['applications', 'Aplicações'],
  ['sast', 'SAST'],
  ['sca', 'SCA'],
  ['gaps', 'Scans e licenças'],
] as const;
type DomainTab = (typeof DOMAINS)[number][0];

function previousMonth(): string {
  const d = new Date();
  d.setUTCDate(1);
  d.setUTCMonth(d.getUTCMonth() - 1);
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
}

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);

function Value({ m }: { m: MetricRow }) {
  const data = m.status === 'VALIDATED' ? m.value : m.status === 'INCOMPLETE' ? m.partial : null;
  if (data === null || data === undefined) return <p className="muted">Sem valor ({STATUS_LABEL[m.status].toLowerCase()}).</p>;
  const partial = m.status === 'INCOMPLETE';
  const caption = partial ? 'Agregado PARCIAL observado — não definitivo' : undefined;
  if (m.shape === 'BY_SEVERITY' && isObj(data))
    return (
      <table className="preview-table" aria-label={`Severidades — ${m.name}`}>
        {caption && <caption>{caption}</caption>}
        <tbody>
          {SEVERITIES.filter(([k]) => k !== 'UNKNOWN' || Number(data.UNKNOWN) > 0).map(([k, label]) => (
            <tr key={k}>
              <th scope="row">{label}</th>
              <td>{String(data[k])}</td>
            </tr>
          ))}
          <tr>
            <th scope="row">Total</th>
            <td data-testid={`total-${m.metric_id}`}>{String(data.total)}</td>
          </tr>
        </tbody>
      </table>
    );
  if (typeof data === 'number' || (isObj(data) && typeof data.count === 'number'))
    return (
      <p className="metric-value" data-testid={`value-${m.metric_id}`}>
        {String(typeof data === 'number' ? data : data.count)}
        {partial && <small className="muted"> (parcial, não definitivo)</small>}
      </p>
    );
  const rows = isObj(data) ? ((data.items ?? data.top) as Obj[] | undefined) : undefined;
  if (rows)
    return (
      <>
        {rows.length === 0 ? (
          <Empty>Nenhum item.</Empty>
        ) : (
          <table className="preview-table" aria-label={`Itens — ${m.name}`}>
            {caption && <caption>{caption}</caption>}
            <thead>
              <tr>
                {Object.keys(rows[0]).map((k) => (
                  <th key={k}>{k}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  {Object.values(r).map((v, j) => (
                    <td key={j}>{String(v ?? '—')}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <small className="muted">
          {Object.entries(data as Obj)
            .filter(([k]) => k !== 'items' && k !== 'top')
            .map(([k, v]) => `${k}: ${String(v)}`)
            .join(' · ')}
        </small>
      </>
    );
  return <pre className="rule-json">{JSON.stringify(data, null, 2)}</pre>;
}

function MetricCard({ m }: { m: MetricRow }) {
  return (
    <article className="panel metric" aria-label={m.name} data-testid={`metric-${m.metric_id}`}>
      <div className="toolbar">
        <h4>{m.name}</h4>
        <span className={`badge ${STATUS_CLASS[m.status]}`} data-testid={`status-${m.metric_id}`}>
          {STATUS_LABEL[m.status]}
        </span>
      </div>
      <small className="muted">
        <code>{m.metric_id}</code> v{m.contract_version} · {m.description}
      </small>
      <Value m={m} />
      {m.reasons.length > 0 && (
        <ul className="warnings" aria-label={`Motivos — ${m.name}`}>
          {m.reasons.map((r) => (
            <li key={r.code}>
              <strong>{r.code}</strong>: {r.message}
            </li>
          ))}
        </ul>
      )}
      <details>
        <summary>Fonte, período e filtros</summary>
        <dl className="details">
          <dt>Fonte</dt>
          <dd>
            {m.source} {m.endpoint && <code>{m.endpoint}</code>}
          </dd>
          <dt>Temporalidade</dt>
          <dd>
            {TEMPORAL_LABEL[m.temporal.mode]} — competência {m.temporal.competence}; coleta em {fmtDate(m.temporal.as_of)}. {m.temporal.note}
          </dd>
          <dt>Campo de data</dt>
          <dd>{m.temporal.date_field}</dd>
          <dt>Filtros</dt>
          <dd>
            {Object.entries(m.filters)
              .filter(([k]) => k !== 'scope_rules_applied')
              .map(([k, v]) => `${k}=${String(v)}`)
              .join(' · ')}
          </dd>
          <dt>Cobertura</dt>
          <dd>
            {Object.entries(m.coverage)
              .filter(([, v]) => typeof v !== 'object')
              .map(([k, v]) => `${k}=${String(v)}`)
              .join(' · ') || '—'}
          </dd>
          <dt>Homologação</dt>
          <dd>{m.homologation}</dd>
        </dl>
        {m.limitations.length > 0 && (
          <ul>
            {m.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        )}
      </details>
    </article>
  );
}

export function MetricsPage({ clientId }: { clientId?: string }) {
  const clients = useLoad(() => api.listClients({ limit: 200, offset: 0, status: 'all' }), []);
  const [client, setClient] = useState(clientId ?? '');
  const [subs, setSubs] = useState<Subclient[]>([]);
  const [owner, setOwner] = useState('');
  const [competence, setCompetence] = useState(previousMonth);
  const [tzOverride, setTzOverride] = useState('');
  const [run, setRun] = useState<MetricRun | null>(null);
  const [error, setError] = useState('');
  const [tab, setTab] = useState<DomainTab>('applications');
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    setSubs([]);
    setOwner('');
    if (!client) return;
    api
      .listSubclients(client)
      .then((p) => setSubs(p.items))
      .catch((e) => setError(errorMessage(e)));
  }, [client]);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const poll = (runId: string) => {
    timer.current = window.setTimeout(async () => {
      try {
        const r = await metrics.get(runId);
        setRun(r);
        if (r.status === 'pending' || r.status === 'running') poll(runId);
      } catch (e) {
        setError(errorMessage(e));
      }
    }, 400);
  };

  const start = async (ev: React.FormEvent) => {
    ev.preventDefault();
    setError('');
    setRun(null);
    window.clearTimeout(timer.current);
    try {
      const r = await metrics.start({
        owner_kind: owner ? 'subclient' : 'client',
        owner_id: owner || client,
        competence,
        timezone: tzOverride.trim() || undefined,
      });
      setRun(r);
      poll(r.run_id);
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  const cancel = async () => {
    if (!run) return;
    try {
      await metrics.cancel(run.run_id);
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  if (clients.error) return <ErrorBox message={`Falha ao carregar clientes: ${clients.error}`} onRetry={clients.reload} />;
  if (clients.loading && !clients.data) return <Loading label="Carregando clientes…" />;
  const running = run?.status === 'pending' || run?.status === 'running';
  const result = run?.result;
  const shown = result?.metrics.filter((m) => (tab === 'gaps' ? m.domain === 'scans' || m.domain === 'licenses' : m.domain === tab)) ?? [];

  return (
    <section>
      <h2>Indicadores</h2>
      <p className="muted">
        Coleta somente leitura na Veracode, sob demanda. Valores só são definitivos com status <strong>Validado</strong>; estado
        atual não representa o fechamento de competências anteriores.
      </p>
      <form className="form panel" onSubmit={start} aria-label="Nova coleta de indicadores">
        <div className="field">
          <label htmlFor="m-client">Cliente</label>
          <select id="m-client" value={client} onChange={(e) => setClient(e.target.value)} required>
            <option value="">Selecione…</option>
            {clients.data!.items.map((c: Client) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="m-owner">Escopo</label>
          <select id="m-owner" value={owner} onChange={(e) => setOwner(e.target.value)} disabled={!client}>
            <option value="">Cliente principal (universo)</option>
            {subs.map((s) => (
              <option key={s.id} value={s.id}>
                Subcliente: {s.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="m-competence">Competência (mês fechado)</label>
          <input id="m-competence" type="month" value={competence} onChange={(e) => setCompetence(e.target.value)} required />
        </div>
        <div className="field">
          <label htmlFor="m-timezone">Fuso (opcional)</label>
          <input
            id="m-timezone"
            value={tzOverride}
            onChange={(e) => setTzOverride(e.target.value)}
            placeholder={clients.data?.items.find((c) => c.id === client)?.timezone ?? 'fuso do cliente'}
            aria-describedby="m-timezone-hint"
          />
          <small id="m-timezone-hint" className="muted">
            Vazio = fuso do cliente (nome IANA, regras históricas).
          </small>
        </div>
        <div className="actions">
          <button className="btn primary" type="submit" disabled={!client || running}>
            Iniciar coleta
          </button>
          {running && (
            <button className="btn" type="button" onClick={cancel}>
              Cancelar coleta
            </button>
          )}
        </div>
      </form>
      {error && <ErrorBox message={error} />}
      {run && (
        <div className="panel" aria-label="Execução">
          <p role="status" data-testid="run-status">
            Execução {RUN_LABEL[run.status]} — {run.owner.name} · competência {run.competence.competence} ({run.competence.timezone}; UTC {run.competence.utc_start} → {run.competence.utc_end_exclusive})
            {running && ` · ${run.progress.stage} ${run.progress.applications_done}/${run.progress.applications_total ?? '?'} aplicações`}
          </p>
          {run.error && <ErrorBox message={run.error.message} />}
          {result && (
            <>
              <p data-testid="run-summary">
                {(Object.keys(STATUS_LABEL) as MetricStatus[]).map((s) => (
                  <span key={s} className={`badge ${STATUS_CLASS[s]}`}>
                    {STATUS_LABEL[s]}: {result.summary[s] ?? 0}
                  </span>
                ))}
              </p>
              <dl className="details">
                <dt>Coleta</dt>
                <dd data-testid="run-collected-at">{fmtDate(result.collected_at)}</dd>
                <dt>Conexão</dt>
                <dd>
                  {result.connection?.name ?? '—'} ({result.connection?.connection_source ?? 'sem conexão'})
                </dd>
                <dt>População</dt>
                <dd>
                  {result.population.applications} aplicação(ões) no escopo · status {result.population.status}
                  {result.population.undetermined > 0 && ` · ${result.population.undetermined} indeterminada(s)`}
                </dd>
                <dt>Requisições</dt>
                <dd>
                  {result.collection
                    ? `${result.collection.requests} GET · ${result.collection.retries} retries · ${result.collection.cache_hits}/${result.collection.contexts} contextos do cache`
                    : '—'}
                  {result.collection?.limit_reached && ` · limite atingido: ${result.collection.limit_reached}`}
                </dd>
                <dt>Escopos usados</dt>
                <dd>
                  {result.provenance.scope_refs
                    .map((r) => `${r.owner_name}/${r.domain}: ${r.status === 'active' ? `v${r.version}` : r.status}`)
                    .join(' · ')}
                </dd>
                <dt>Proveniência</dt>
                <dd>
                  <code>{result.provenance.engine}</code> · execução <code>{result.provenance.run_id}</code> · hash de entrada{' '}
                  <code>{result.provenance.input_hash.slice(0, 16)}…</code>
                </dd>
              </dl>
              {result.population.reasons.length > 0 && (
                <ul className="warnings" aria-label="Motivos da população">
                  {result.population.reasons.map((r) => (
                    <li key={r.code}>{r.message}</li>
                  ))}
                </ul>
              )}
              <div className="tabs" role="tablist" aria-label="Domínios">
                {DOMAINS.map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    role="tab"
                    className={`tab${tab === key ? ' active' : ''}`}
                    aria-selected={tab === key}
                    onClick={() => setTab(key)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div role="tabpanel" className="metrics-grid">
                {shown.map((m) => (
                  <MetricCard key={m.metric_id} m={m} />
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
