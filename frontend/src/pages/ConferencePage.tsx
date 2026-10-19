// F10: conferência humana com a plataforma Veracode. O operador informa SÓ o valor oficial; a diferença mostrada ao
// digitar é prévia — o status oficial (MATCH/MISMATCH/NOT_COMPARABLE) é calculado e registrado pelo servidor.
import React, { useState } from 'react';
import { errorMessage } from '../api';
import { COMPARISON_LABEL, Comparison, ConferenceRow, REASON_LABEL, conference } from '../conferenceApi';
import { ErrorBox, Loading, useLoad } from '../ui';
import { Badge, OperatorField } from './OwnerPicker';

const CLS: Partial<Record<Comparison, string>> = { MATCH: 'ok', MISMATCH: 'bad', NOT_COMPARABLE: 'warn', NOT_VERIFIED: 'off' };

function localToday(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

const pct = (diff: number, official: number) => (official === 0 ? (diff === 0 ? '0%' : '—') : `${((diff / official) * 100).toFixed(2)}%`);

function MetricCard(props: { cid: string; n: number; row: ConferenceRow; operator: string; checkedOn: string; onSaved: (r: ConferenceRow) => void }) {
  const { row } = props;
  const current = row.conference && !row.conference.stale ? row.conference : null;
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries((current?.entries ?? []).filter((e) => e.official !== null).map((e) => [e.key, String(e.official)])),
  );
  const [filters, setFilters] = useState(current?.filters_confirmed ?? false);
  const [evidence, setEvidence] = useState(current?.evidence ?? '');
  const [note, setNote] = useState(current?.note ?? '');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const id = row.metric_id.replace(/\./g, '-');
  const dateWarning = row.same_day_required && row.snapshot?.collected_on && row.snapshot.collected_on !== props.checkedOn;

  const save = async () => {
    setError('');
    const official: Record<string, number> = {};
    for (const [k, v] of Object.entries(values)) {
      if (v.trim() === '') continue;
      if (!/^\d+$/.test(v.trim())) return setError('Valores oficiais devem ser inteiros não negativos');
      official[k] = Number(v.trim());
    }
    setSaving(true);
    try {
      props.onSaved(
        await conference.record(props.cid, props.n, row.metric_id, {
          operator: props.operator,
          checked_on: props.checkedOn,
          filters_confirmed: filters,
          official,
          evidence: evidence.trim() || undefined,
          not_comparable_note: note.trim() || undefined,
        }),
      );
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <article className="panel" data-testid={`conference-${row.metric_id}`} aria-label={row.name}>
      <div className="toolbar">
        <h3>
          {row.name} <code>{row.metric_id}</code>
        </h3>
        <Badge cls={CLS[row.comparison] ?? 'off'} testId="comparison">
          {COMPARISON_LABEL[row.comparison]}
        </Badge>
        {row.homologated && <Badge cls="ok">Homologado</Badge>}
        {row.snapshot?.origin === 'MANUAL' && <Badge cls="warn">Valor manual (não homologa o cálculo)</Badge>}
      </div>
      <p className="muted">
        Onde conferir (indicativo): {row.guide.path} · coleta em {row.snapshot?.collected_on ?? '—'}
        {row.same_day_required ? ' · estado ATUAL: conferir no mesmo dia da coleta' : ''}
      </p>
      <ul className="warnings" aria-label="Filtros necessários">
        {row.guide.filters.map((f) => (
          <li key={f}>{f}</li>
        ))}
      </ul>
      {dateWarning && <p className="notice">A data da conferência difere da data da coleta: o resultado será “não comparável”.</p>}
      {row.lines.length === 0 ? (
        <p className="empty">Sem valor calculado nesta revisão: nada a conferir.</p>
      ) : (
        <table className="preview-table" aria-label={`Linhas de ${row.metric_id}`}>
          <thead>
            <tr>
              <th>Linha</th>
              <th>Calculado</th>
              <th>Oficial (Veracode)</th>
              <th>Diferença</th>
              <th>%</th>
            </tr>
          </thead>
          <tbody>
            {row.lines.map((line) => {
              const raw = values[line.key] ?? '';
              const official = /^\d+$/.test(raw.trim()) ? Number(raw.trim()) : null;
              const diff = official === null ? null : line.computed - official;
              return (
                <tr key={line.key}>
                  <td>{line.label}</td>
                  <td>{line.computed}</td>
                  <td>
                    <input
                      aria-label={`Oficial ${line.label}`}
                      inputMode="numeric"
                      value={raw}
                      onChange={(e) => setValues({ ...values, [line.key]: e.target.value })}
                      size={8}
                    />
                  </td>
                  <td data-testid={`diff-${line.key}`}>{diff === null ? '—' : diff}</td>
                  <td>{diff === null || official === null ? '—' : pct(diff, official)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {row.lines.length > 0 && (
        <div className="form">
          <label>
            <input type="checkbox" checked={filters} onChange={(e) => setFilters(e.target.checked)} /> Conferi que escopo e filtros na
            Veracode são os mesmos do indicador
          </label>
          <div className="field">
            <label htmlFor={`${id}-evidence`}>Evidência local (ex.: onde salvou a captura — fora do repositório)</label>
            <textarea id={`${id}-evidence`} value={evidence} onChange={(e) => setEvidence(e.target.value)} maxLength={2000} rows={2} />
          </div>
          <div className="field">
            <label htmlFor={`${id}-note`}>Não comparável? Explique (opcional)</label>
            <textarea id={`${id}-note`} value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} rows={2} />
          </div>
          {error && <ErrorBox message={error} />}
          <button className="btn primary" type="button" onClick={save} disabled={saving || props.operator.trim().length < 2}>
            Registrar conferência
          </button>
        </div>
      )}
      {row.conference && (
        <p className="muted" data-testid="conference-last">
          Último registro nº {row.conference.sequence}: {COMPARISON_LABEL[row.conference.status]} em {row.conference.checked_on} por{' '}
          {row.conference.operator} (declarado)
          {row.conference.reasons.length > 0 && ` — ${row.conference.reasons.map((r) => REASON_LABEL[r] ?? r).join('; ')}`}
          {row.conference.stale && ' — DESATUALIZADO: o snapshot mudou depois da conferência'}
        </p>
      )}
    </article>
  );
}

export function ConferencePage({ cid, n }: { cid: string; n: number }) {
  const loaded = useLoad(() => conference.sheet(cid, n), [cid, n]);
  const [operator, setOperator] = useState('');
  const [checkedOn, setCheckedOn] = useState(localToday);
  const [rows, setRows] = useState<Record<string, ConferenceRow>>({});

  if (loaded.error) return <ErrorBox message={loaded.error} onRetry={loaded.reload} />;
  if (!loaded.data) return <Loading label="Carregando conferência…" />;
  const sheet = loaded.data;
  const all = sheet.metrics.map((m) => rows[m.metric_id] ?? m);
  const count = (c: Comparison) => all.filter((m) => m.comparison === c).length;
  const applicable = all.filter((m) => m.guide.category === 'APPLICABLE');
  const others = all.filter((m) => m.guide.category !== 'APPLICABLE');

  return (
    <section aria-labelledby="conference-title">
      <div className="toolbar">
        <a href={`#/snapshots/${cid}/${n}`}>← Revisão {n}</a>
        <h2 id="conference-title">
          Conferência com a Veracode — {sheet.competence.competence} · revisão {sheet.revision.number} ({sheet.revision.status})
        </h2>
        <a className="btn" href={conference.csvUrl(cid, n)} download data-testid="conference-csv">
          Exportar CSV (evidência local)
        </a>
      </div>
      <p className="notice">
        Informe o número que a plataforma Veracode mostra com os MESMOS filtros e na data indicada. Divergência significa investigar a
        nossa consulta — nunca altera o snapshot. Os caminhos são indicativos.
      </p>
      <dl className="summary" data-testid="conference-summary">
        <div>
          <dt>Homologados</dt>
          <dd>{all.filter((m) => m.homologated).length}</dd>
        </div>
        {(['MATCH', 'MISMATCH', 'NOT_COMPARABLE', 'NOT_VERIFIED', 'NO_COMPUTED_VALUE', 'NOT_APPLICABLE', 'BLOCKED_EXTERNAL'] as Comparison[]).map(
          (c) => (
            <div key={c}>
              <dt>{COMPARISON_LABEL[c]}</dt>
              <dd data-testid={`summary-${c}`}>{count(c)}</dd>
            </div>
          ),
        )}
      </dl>
      <div className="form">
        <OperatorField id="conference-operator" value={operator} onChange={setOperator} label="Conferente (declarado)" />
        <div className="field">
          <label htmlFor="conference-date">Data da conferência</label>
          <input id="conference-date" type="date" value={checkedOn} max={localToday()} onChange={(e) => setCheckedOn(e.target.value)} />
        </div>
      </div>
      <h3>Aplicáveis ({applicable.length})</h3>
      {applicable.map((row) => (
        <MetricCard
          key={`${row.metric_id}-${row.conference?.sequence ?? 0}`}
          cid={cid}
          n={n}
          row={row}
          operator={operator}
          checkedOn={checkedOn}
          onSaved={(r) => setRows({ ...rows, [r.metric_id]: r })}
        />
      ))}
      <h3>Sem valor oficial equivalente ({others.length})</h3>
      <table className="preview-table" aria-label="Indicadores não aplicáveis e bloqueados">
        <thead>
          <tr>
            <th>Indicador</th>
            <th>Situação</th>
            <th>Motivo</th>
          </tr>
        </thead>
        <tbody>
          {others.map((m) => (
            <tr key={m.metric_id} data-testid={`other-${m.metric_id}`}>
              <td>
                {m.name} <code>{m.metric_id}</code>
              </td>
              <td>{COMPARISON_LABEL[m.comparison]}</td>
              <td>{m.guide.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
