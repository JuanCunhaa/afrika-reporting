import React, { useState } from 'react';
import { errorMessage, metrics } from '../api';
import { Compare, Series, SeriesPoint, VALUE_STATE_LABEL, snapshots } from '../snapshotsApi';
import { ErrorBox, useLoad } from '../ui';
import { Owner, OwnerPicker, shortValue } from './OwnerPicker';

// F05: séries históricas SOMENTE de snapshots aprovados. Competência sem aprovação = lacuna explícita
// (sem interpolação, sem zero no lugar de ausência). Preenchimento só por competência manual auditada.

function SeriesChart({ s }: { s: Series }) {
  const values = s.points.map((p) => p.headline).filter((v): v is number => typeof v === 'number');
  const max = Math.max(1, ...values);
  const H = 160;
  return (
    <figure className="chart" aria-label={`Série histórica — ${s.metric_name}`}>
      <figcaption>
        {s.metric_name} · {s.start} a {s.end} ({s.timezone}) · fonte: snapshots aprovados
      </figcaption>
      <div className="bars" style={{ height: H + 40 }}>
        {s.points.map((p) => (
          <Bar key={p.competence} p={p} max={max} h={H} />
        ))}
      </div>
    </figure>
  );
}

function Bar({ p, max, h }: { p: SeriesPoint; max: number; h: number }) {
  const gap = p.state === 'GAP';
  const noNumber = !gap && typeof p.headline !== 'number';
  const tip = gap
    ? `${p.competence}: lacuna — sem revisão aprovada`
    : `${p.competence}: ${noNumber ? 'sem valor numérico' : p.headline} · ${p.value_state ? VALUE_STATE_LABEL[p.value_state] : ''} · revisão ${p.approval?.revision}`;
  return (
    <div className="bar-slot" title={tip} data-testid={`point-${p.competence}`} tabIndex={0} aria-label={tip}>
      <span className="bar-value">{gap ? 'lacuna' : noNumber ? '—' : p.headline}</span>
      {gap || noNumber ? (
        <div className="bar-gap" style={{ height: h * 0.5 }} />
      ) : (
        <div className="bar" style={{ height: Math.max(2, (h * (p.headline as number)) / max) }} />
      )}
      <span className="bar-label">{p.competence.slice(2)}</span>
    </div>
  );
}

export function HistoryPage() {
  const catalog = useLoad(() => metrics.catalog(), []);
  const [owner, setOwner] = useState<Owner | null>(null);
  const [metric, setMetric] = useState('apps.total');
  const [months, setMonths] = useState<'6' | '12' | 'custom'>('6');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [series, setSeries] = useState<Series | null>(null);
  const [cmpLabel, setCmpLabel] = useState('');
  const [cmp, setCmp] = useState<Compare | null>(null);
  const [error, setError] = useState('');

  const load = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!owner) return;
    setError('');
    try {
      const range = months === 'custom' ? { start, end } : { months: Number(months), end: end || undefined };
      setSeries(await snapshots.series(owner.kind, owner.id, metric, range));
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <section>
      <h2>Histórico</h2>
      <p className="muted">
        Só revisões <strong>aprovadas</strong>. Lacunas aparecem como lacunas: para preenchê-las, crie a competência, informe o valor
        manual justificado e aprove.
      </p>
      <form className="form panel" onSubmit={load} aria-label="Série histórica">
        <OwnerPicker prefix="h" onChange={setOwner} />
        <div className="field">
          <label htmlFor="h-metric">Indicador</label>
          <select id="h-metric" value={metric} onChange={(e) => setMetric(e.target.value)}>
            {(catalog.data?.metrics ?? []).map((m) => (
              <option key={m.metric_id} value={m.metric_id}>
                {m.metric_id} — {m.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="h-range">Intervalo</label>
          <select id="h-range" value={months} onChange={(e) => setMonths(e.target.value as '6' | '12' | 'custom')}>
            <option value="6">6 meses</option>
            <option value="12">12 meses</option>
            <option value="custom">Personalizado</option>
          </select>
        </div>
        {months === 'custom' && (
          <div className="field">
            <label htmlFor="h-start">Início</label>
            <input id="h-start" type="month" value={start} onChange={(e) => setStart(e.target.value)} required />
          </div>
        )}
        <div className="field">
          <label htmlFor="h-end">Fim (vazio = último mês fechado no fuso do cliente)</label>
          <input id="h-end" type="month" value={end} onChange={(e) => setEnd(e.target.value)} required={months === 'custom'} />
        </div>
        <div className="actions">
          <button className="btn primary" type="submit" disabled={!owner}>
            Carregar série
          </button>
        </div>
      </form>
      {error && <ErrorBox message={error} />}
      {series && (
        <div className="panel">
          <SeriesChart s={series} />
          {series.warnings.map((w) => (
            <p key={w.code} className="warnings">
              {w.message}
            </p>
          ))}
          <p data-testid="gaps">Lacunas: {series.gaps.length ? series.gaps.join(', ') : 'nenhuma'}</p>
          <table className="preview-table" aria-label="Tabela da série">
            <thead>
              <tr>
                <th>Competência</th>
                <th>Situação</th>
                <th>Valor</th>
                <th>Estado</th>
                <th>Aprovação</th>
              </tr>
            </thead>
            <tbody>
              {series.points.map((p) => (
                <tr key={p.competence}>
                  <td>{p.competence}</td>
                  <td>{p.state === 'GAP' ? 'Lacuna' : 'Aprovada'}</td>
                  <td>{shortValue(p.value)}</td>
                  <td>{p.value_state ? VALUE_STATE_LABEL[p.value_state] : '—'}</td>
                  <td>{p.approval ? `rev. ${p.approval.revision} · ${p.approval.approver} (declarado)` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {owner && (
        <form
          className="form panel"
          aria-label="Comparar com mês anterior"
          onSubmit={(e) => {
            e.preventDefault();
            snapshots.compareMonth(owner.kind, owner.id, cmpLabel).then(setCmp).catch((err) => setError(errorMessage(err)));
          }}
        >
          <div className="field">
            <label htmlFor="h-cmp">Competência para comparar com a anterior</label>
            <input id="h-cmp" type="month" value={cmpLabel} onChange={(e) => setCmpLabel(e.target.value)} required />
          </div>
          <div className="actions">
            <button className="btn" type="submit">
              Comparar com mês anterior
            </button>
          </div>
        </form>
      )}
      {cmp && (
        <table className="preview-table" aria-label="Comparação mês a mês" data-testid="compare">
          <thead>
            <tr>
              <th>Indicador</th>
              <th>{cmp.previous_competence}</th>
              <th>{cmp.competence}</th>
              <th>Variação</th>
            </tr>
          </thead>
          <tbody>
            {cmp.items.map((i) => (
              <tr key={i.metric_id}>
                <td>{i.name}</td>
                <td>{i.previous.state === 'GAP' ? 'lacuna' : shortValue(i.previous.value)}</td>
                <td>{i.current.state === 'GAP' ? 'lacuna' : shortValue(i.current.value)}</td>
                <td>{i.delta ?? `— (${i.delta_unavailable_reason})`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
