import React, { useEffect, useState } from 'react';
import { errorMessage, metricRuns } from '../api';
import {
  AuditEventRow,
  Integrity,
  REVISION_LABEL,
  Revision,
  RevisionDiff,
  Snapshot,
  VALUE_STATE_CLASS,
  VALUE_STATE_LABEL,
  loadOperator,
  saveOperator,
  snapshots,
} from '../snapshotsApi';
import { Empty, ErrorBox, Loading, fmtDate, useLoad } from '../ui';
import { Badge, OperatorField, Owner, OwnerPicker, shortValue } from './OwnerPicker';

// F05: competências por cliente/subcliente, rascunhos a partir de coletas, edição manual auditada, revisão,
// aprovação (aprovador DECLARADO), histórico de revisões, comparação, auditoria e integridade.

function previousMonth(): string {
  const d = new Date();
  d.setUTCDate(1);
  d.setUTCMonth(d.getUTCMonth() - 1);
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
}

function useOperator(): [string, (v: string) => void] {
  const [op, setOp] = useState(loadOperator);
  return [op, (v: string) => (setOp(v), saveOperator(v))];
}

export function SnapshotsPage({ cid, n, navigate }: { cid?: string; n?: number; navigate: (p: string) => void }) {
  return cid ? <CompetenceView cid={cid} n={n} navigate={navigate} /> : <CompetenceList navigate={navigate} />;
}

function CompetenceList({ navigate }: { navigate: (p: string) => void }) {
  const [owner, setOwner] = useState<Owner | null>(null);
  const [operator, setOperator] = useOperator();
  const [label, setLabel] = useState(previousMonth());
  const [error, setError] = useState('');
  const list = useLoad(() => (owner ? snapshots.list(owner.kind, owner.id) : Promise.resolve({ items: [] })), [owner?.id]);
  const runs = useLoad(() => metricRuns.list(), [owner?.id]);
  const ownerRuns = (runs.data?.items ?? []).filter((r) => owner && r.owner.id === owner.id && r.status === 'done');

  const act = async (fn: () => Promise<string>) => {
    setError('');
    try {
      navigate(await fn());
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  return (
    <section>
      <h2>Competências</h2>
      <p className="muted">
        Snapshots por competência mensal. Só versões <strong>aprovadas</strong> alimentam o histórico oficial; uma aprovação nunca
        é sobrescrita — correções criam nova revisão.
      </p>
      <div className="form panel" aria-label="Dono e operador">
        <OwnerPicker prefix="s" onChange={setOwner} />
        <OperatorField id="s-operator" value={operator} onChange={setOperator} />
      </div>
      {error && <ErrorBox message={error} />}
      {owner && (
        <>
          <form
            className="form panel"
            aria-label="Nova competência"
            onSubmit={(e) => {
              e.preventDefault();
              act(async () => `/snapshots/${(await snapshots.create(owner.kind, owner.id, label, operator)).id}/1`);
            }}
          >
            <div className="field">
              <label htmlFor="s-competence">Competência (mês fechado)</label>
              <input id="s-competence" type="month" value={label} onChange={(e) => setLabel(e.target.value)} required />
            </div>
            <div className="actions">
              <button className="btn primary" type="submit" disabled={!operator.trim()}>
                Criar competência (rascunho vazio)
              </button>
            </div>
            <small className="muted">Fuso: {owner.timezone}. Sem coleta, os valores precisam ser informados manualmente e justificados.</small>
          </form>
          <div className="panel" aria-label="Execuções disponíveis">
            <h3>Importar execução de indicadores</h3>
            {ownerRuns.length === 0 ? (
              <Empty>Nenhuma execução concluída deste dono nesta sessão do backend (execuções vivem só em memória).</Empty>
            ) : (
              <ul className="plain">
                {ownerRuns.map((r) => (
                  <li key={r.run_id}>
                    {r.competence.competence} · {r.competence.timezone} · concluída {r.finished_at ? fmtDate(r.finished_at) : ''}{' '}
                    <button
                      type="button"
                      className="btn"
                      disabled={!operator.trim()}
                      onClick={() =>
                        act(async () => {
                          const out = await snapshots.fromRun(r.run_id, operator);
                          return `/snapshots/${out.competence_id}/${out.revision}`;
                        })
                      }
                    >
                      Criar rascunho de {r.competence.competence}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="panel" aria-label="Competências do dono">
            <h3>Competências de {owner.name}</h3>
            {list.error && <ErrorBox message={list.error} onRetry={list.reload} />}
            {list.data && list.data.items.length === 0 && <Empty>Nenhuma competência.</Empty>}
            {list.data && list.data.items.length > 0 && (
              <table className="preview-table">
                <thead>
                  <tr>
                    <th>Competência</th>
                    <th>Fuso</th>
                    <th>Revisões</th>
                    <th>Oficial</th>
                    <th>Aberta</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {list.data.items.map((c) => (
                    <tr key={c.id}>
                      <td>{c.competence}</td>
                      <td>{c.timezone}</td>
                      <td>{c.revisions.map((r) => `${r.number}:${REVISION_LABEL[r.status]}`).join(' · ')}</td>
                      <td>{c.official_revision ?? '— (lacuna)'}</td>
                      <td>{c.open_revision ?? '—'}</td>
                      <td>
                        <a href={`#/snapshots/${c.id}/${c.open_revision ?? c.official_revision ?? 1}`}>Abrir {c.competence}</a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </section>
  );
}

function CompetenceView({ cid, n, navigate }: { cid: string; n?: number; navigate: (p: string) => void }) {
  const comp = useLoad(() => snapshots.get(cid), [cid, n]);
  const [operator, setOperator] = useOperator();
  const [error, setError] = useState('');
  if (comp.error) return <ErrorBox message={comp.error} onRetry={comp.reload} />;
  if (!comp.data) return <Loading label="Carregando competência…" />;
  const c = comp.data;
  const number = n ?? c.open_revision ?? c.official_revision ?? 1;
  const newRevision = async () => {
    setError('');
    try {
      const r = await snapshots.newRevision(cid, operator);
      navigate(`/snapshots/${cid}/${r.number}`);
    } catch (e) {
      setError(errorMessage(e));
    }
  };
  return (
    <section>
      <p>
        <a href="#/snapshots">← Competências</a>
      </p>
      <h2>
        Competência {c.competence} <small className="muted">({c.timezone}; UTC {c.period.utc_start} → {c.period.utc_end_exclusive})</small>
      </h2>
      <div className="panel" aria-label="Revisões">
        <h3>Revisões</h3>
        <ul className="plain" data-testid="revision-list">
          {c.revisions.map((r) => (
            <li key={r.number}>
              <a href={`#/snapshots/${cid}/${r.number}`} aria-current={r.number === number ? 'page' : undefined}>
                Revisão {r.number}
              </a>{' '}
              <Badge cls={r.status === 'APPROVED' ? 'ok' : r.status === 'DRAFT' ? 'off' : 'warn'}>{REVISION_LABEL[r.status]}</Badge>
              {r.is_official && <Badge cls="ok">Oficial</Badge>}
              {r.approval && (
                <small className="muted">
                  {' '}
                  aprovada por {r.approval.approver} (declarado) em {fmtDate(r.approval.approved_at)}
                </small>
              )}
            </li>
          ))}
        </ul>
        <div className="form">
          <OperatorField id="c-operator" value={operator} onChange={setOperator} />
          <div className="actions">
            <button className="btn" type="button" onClick={newRevision} disabled={c.open_revision !== null || !operator.trim()}>
              Nova revisão a partir da aprovada
            </button>
          </div>
        </div>
        {error && <ErrorBox message={error} />}
      </div>
      <RevisionPanel key={`${cid}-${number}`} cid={cid} n={number} operator={operator} setOperator={setOperator} others={c.revisions.map((r) => r.number)} onChanged={comp.reload} />
    </section>
  );
}

function RevisionPanel(props: { cid: string; n: number; operator: string; setOperator: (v: string) => void; others: number[]; onChanged: () => void }) {
  const { cid, n, operator } = props;
  const loaded = useLoad(() => snapshots.revision(cid, n), [cid, n]);
  const [rev, setRev] = useState<Revision | null>(null);
  const [error, setError] = useState('');
  const [editing, setEditing] = useState<Snapshot | null>(null);
  const [required, setRequired] = useState<string[]>([]);
  const [approver, setApprover] = useState('');
  const [note, setNote] = useState('');
  const [reason, setReason] = useState('');
  const [diffWith, setDiffWith] = useState('');
  const [diff, setDiff] = useState<RevisionDiff | null>(null);
  const [audit, setAudit] = useState<AuditEventRow[] | null>(null);
  const [integrity, setIntegrity] = useState<Integrity | null>(null);

  useEffect(() => {
    if (loaded.data) {
      setRev(loaded.data);
      setRequired(loaded.data.required_metrics);
    }
  }, [loaded.data]);

  if (loaded.error) return <ErrorBox message={loaded.error} onRetry={loaded.reload} />;
  if (!rev) return <Loading label="Carregando revisão…" />;
  const lock = { operator, expected_lock_version: rev.lock_version };
  const run = async (fn: () => Promise<Revision>) => {
    setError('');
    try {
      const r = await fn();
      setRev(r);
      setRequired(r.required_metrics);
      setEditing(null);
      props.onChanged();
    } catch (e) {
      setError(errorMessage(e) + (e && typeof e === 'object' && 'details' in e ? detailsText(e as { details: { field: string; message: string }[] }) : ''));
    }
  };
  const allMetrics = [...rev.snapshots.map((s) => s.metric_id), ...rev.metrics_without_snapshot].sort();

  return (
    <div className="panel" aria-label={`Revisão ${rev.number}`}>
      <div className="toolbar">
        <h3>Revisão {rev.number}</h3>
        <Badge cls={rev.status === 'APPROVED' ? 'ok' : rev.status === 'DRAFT' ? 'off' : 'warn'} testId="revision-status">
          {REVISION_LABEL[rev.status]}
        </Badge>
        {rev.is_official && <Badge cls="ok">Oficial</Badge>}
        <a className="btn" href={`#/conference/${cid}/${rev.number}`} data-testid="open-conference">
          Conferir com a Veracode
        </a>
      </div>
      <small className="muted">
        versão de bloqueio {rev.lock_version} · criada por {rev.created_by} (declarado) {fmtDate(rev.created_at)}
        {rev.base_revision && ` · baseada na revisão ${rev.base_revision}`}
      </small>
      {rev.approval && (
        <p data-testid="approval-info">
          Aprovada por <strong>{rev.approval.approver}</strong> em {fmtDate(rev.approval.approved_at)} — identidade declarada, não autenticada ·
          hash <code>{rev.approval.content_hash.slice(0, 16)}…</code>
        </p>
      )}
      {error && <ErrorBox message={error} />}
      {rev.checks.length > 0 && rev.status !== 'APPROVED' && (
        <ul className="warnings" aria-label="Pendências para aprovação" data-testid="checks">
          {rev.checks.map((c, i) => (
            <li key={i}>
              {c.metric_id && <code>{c.metric_id}</code>} {c.message}
            </li>
          ))}
        </ul>
      )}

      <details className="panel" open={rev.editable && rev.required_metrics.length === 0}>
        <summary>Indicadores obrigatórios ({rev.required_metrics.length}) — conjunto explícito v{rev.required_set_version}</summary>
        <div className="checks-grid">
          {allMetrics.map((m) => (
            <label key={m}>
              <input
                type="checkbox"
                checked={required.includes(m)}
                disabled={!rev.editable}
                onChange={(e) => setRequired(e.target.checked ? [...required, m] : required.filter((x) => x !== m))}
              />{' '}
              {m}
            </label>
          ))}
        </div>
        {rev.editable && (
          <button className="btn" type="button" onClick={() => run(() => snapshots.setRequired(cid, n, { ...lock, metric_ids: required }))}>
            Salvar obrigatórios
          </button>
        )}
      </details>

      <table className="preview-table" aria-label="Snapshots">
        <thead>
          <tr>
            <th>Indicador</th>
            <th>Valor</th>
            <th>Estado</th>
            <th>Fonte (técnico)</th>
            <th>Homologação dashboard</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rev.snapshots.map((s) => (
            <tr key={s.metric_id} data-testid={`snap-${s.metric_id}`}>
              <td>
                {s.required && <strong title="obrigatório">* </strong>}
                {s.name}
                <br />
                <small className="muted">
                  <code>{s.metric_id}</code> v{s.contract_version} · {s.value_type}
                </small>
              </td>
              <td data-testid={`snapval-${s.metric_id}`}>{shortValue(s.value)}</td>
              <td>
                <Badge cls={VALUE_STATE_CLASS[s.value_state]} testId={`snapstate-${s.metric_id}`}>
                  {VALUE_STATE_LABEL[s.value_state]}
                </Badge>
                {s.manual && (
                  <small className="muted">
                    <br />
                    {s.manual.operator}: {s.manual.justification}
                  </small>
                )}
              </td>
              <td>
                {s.source.status ?? 'sem coleta'}
                {s.origin === 'MANUAL' && s.source.status && <small className="muted"> · fonte: {shortValue(s.source.value ?? s.source.partial)}</small>}
                {s.source.reasons.length > 0 && <small className="muted"><br />{s.source.reasons.map((r) => r.code).join(', ')}</small>}
              </td>
              <td>{s.dashboard_homologation}</td>
              <td>
                {rev.editable && (
                  <button className="btn" type="button" onClick={() => setEditing(s)}>
                    Editar {s.metric_id}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {rev.editable && rev.metrics_without_snapshot.length > 0 && (
        <p className="muted">
          Sem snapshot: {rev.metrics_without_snapshot.join(', ')}{' '}
          <button
            className="btn"
            type="button"
            onClick={() => setEditing({ metric_id: rev.metrics_without_snapshot[0], value_type: 'count', value: null, origin: 'VERACODE' } as Snapshot)}
          >
            Informar valor manual
          </button>
        </p>
      )}
      {editing && rev.editable && (
        <ManualForm
          key={editing.metric_id}
          snap={editing}
          choices={rev.metrics_without_snapshot}
          onCancel={() => setEditing(null)}
          onSave={(metric, value, justification) => run(() => snapshots.setManual(cid, n, metric, { ...lock, value, justification }))}
          onRevert={(justification) => run(() => snapshots.revert(cid, n, editing.metric_id, { ...lock, justification }))}
        />
      )}

      <div className="form panel" aria-label="Ciclo de vida">
        <OperatorField id="r-operator" value={operator} onChange={props.setOperator} />
        {rev.status === 'DRAFT' && (
          <div className="actions">
            <button className="btn primary" type="button" disabled={!operator.trim()} onClick={() => run(() => snapshots.submit(cid, n, lock))}>
              Enviar para revisão
            </button>
          </div>
        )}
        {rev.status === 'READY_FOR_REVIEW' && (
          <>
            <div className="field">
              <label htmlFor="r-approver">Aprovador (declarado)</label>
              <input id="r-approver" value={approver} onChange={(e) => setApprover(e.target.value)} maxLength={120} />
            </div>
            <div className="field">
              <label htmlFor="r-note">Observação da aprovação</label>
              <input id="r-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
            </div>
            <div className="actions">
              <button
                className="btn primary"
                type="button"
                disabled={!approver.trim()}
                onClick={() => run(() => snapshots.approve(cid, n, { approver, note: note || null, expected_lock_version: rev.lock_version }))}
              >
                Aprovar revisão
              </button>
            </div>
            <div className="field">
              <label htmlFor="r-reason">Motivo para devolver</label>
              <input id="r-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
            </div>
            <div className="actions">
              <button className="btn" type="button" onClick={() => run(() => snapshots.returnToDraft(cid, n, { ...lock, reason }))}>
                Devolver a rascunho
              </button>
            </div>
          </>
        )}
      </div>

      {rev.manual_changes.length > 0 && (
        <details className="panel">
          <summary>Alterações manuais ({rev.manual_changes.length})</summary>
          <table className="preview-table">
            <thead>
              <tr>
                <th>Quando (UTC)</th>
                <th>Indicador</th>
                <th>Anterior</th>
                <th>Novo</th>
                <th>Operador</th>
                <th>Justificativa</th>
              </tr>
            </thead>
            <tbody>
              {rev.manual_changes.map((m, i) => (
                <tr key={i}>
                  <td>{m.changed_at}</td>
                  <td>{m.metric_id}</td>
                  <td>
                    {shortValue(m.previous_value)} ({m.previous_origin ?? '—'})
                  </td>
                  <td>
                    {shortValue(m.new_value)} ({m.new_origin})
                  </td>
                  <td>{m.operator}</td>
                  <td>{m.justification}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      <div className="form panel" aria-label="Comparação e auditoria">
        <div className="field">
          <label htmlFor="r-diff">Comparar com a revisão</label>
          <select id="r-diff" value={diffWith} onChange={(e) => setDiffWith(e.target.value)}>
            <option value="">Selecione…</option>
            {props.others.filter((x) => x !== n).map((x) => (
              <option key={x} value={x}>
                {x}
              </option>
            ))}
          </select>
        </div>
        <div className="actions">
          <button className="btn" type="button" disabled={!diffWith} onClick={() => snapshots.compare(cid, Number(diffWith), n).then(setDiff).catch((e) => setError(errorMessage(e)))}>
            Comparar versões
          </button>
          <button className="btn" type="button" onClick={() => snapshots.audit(cid).then((a) => setAudit(a.items)).catch((e) => setError(errorMessage(e)))}>
            Ver auditoria
          </button>
          <button className="btn" type="button" onClick={() => snapshots.integrity(cid).then(setIntegrity).catch((e) => setError(errorMessage(e)))}>
            Verificar integridade
          </button>
        </div>
      </div>
      {diff && (
        <div className="panel" data-testid="diff">
          <p>
            Revisão {diff.a} → {diff.b}: {diff.changed} indicador(es) alterado(s){diff.required_changed && ' · obrigatórios mudaram'}
          </p>
          <ul className="plain">
            {diff.items.filter((i) => i.changed).map((i) => (
              <li key={i.metric_id}>
                <code>{i.metric_id}</code>: {shortValue(i.a?.value)} ({i.a?.origin ?? '—'}) → {shortValue(i.b?.value)} ({i.b?.origin ?? '—'})
              </li>
            ))}
          </ul>
        </div>
      )}
      {integrity && (
        <p role="status" data-testid="integrity">
          Integridade: {integrity.ok ? 'OK' : 'FALHA'} · {integrity.approvals} aprovação(ões) · cadeia de auditoria{' '}
          {integrity.audit_chain.ok ? 'íntegra' : 'divergente'} ({integrity.audit_chain.events_checked} eventos)
          {integrity.problems.length > 0 && ` · ${integrity.problems.join('; ')}`}
        </p>
      )}
      {audit && (
        <ol className="audit" data-testid="audit">
          {audit.map((e) => (
            <li key={e.id}>
              {e.occurred_at} · <strong>{e.event_type}</strong> · {e.actor ?? '—'} · <small className="muted">{JSON.stringify(e.details)}</small>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

const detailsText = (e: { details: { field: string; message: string }[] }) =>
  e.details?.length ? ' — ' + e.details.map((d) => `${d.field}: ${d.message}`).join('; ') : '';

function ManualForm(props: {
  snap: Snapshot;
  choices: string[];
  onCancel: () => void;
  onSave: (metric: string, value: unknown, justification: string) => void;
  onRevert: (justification: string) => void;
}) {
  const s = props.snap;
  const isNew = props.choices.includes(s.metric_id);
  const [metric, setMetric] = useState(s.metric_id);
  const [text, setText] = useState(s.value === null || s.value === undefined ? '' : JSON.stringify(s.value, null, 1));
  const [justification, setJustification] = useState('');
  const [parseError, setParseError] = useState('');
  const save = () => {
    try {
      setParseError('');
      props.onSave(metric, JSON.parse(text), justification);
    } catch {
      setParseError('Valor precisa ser JSON válido (ex.: 12, ou um objeto com as severidades).');
    }
  };
  return (
    <div className="form panel" aria-label="Valor manual">
      <h4>Valor manual {isNew ? '' : `— ${s.metric_id}`}</h4>
      {isNew && (
        <div className="field">
          <label htmlFor="mv-metric">Indicador</label>
          <select id="mv-metric" value={metric} onChange={(e) => setMetric(e.target.value)}>
            {props.choices.map((m) => (
              <option key={m}>{m}</option>
            ))}
          </select>
        </div>
      )}
      <div className="field">
        <label htmlFor="mv-value">Valor ({s.value_type}; JSON)</label>
        <textarea id="mv-value" value={text} onChange={(e) => setText(e.target.value)} rows={4} />
        {s.source?.status && (
          <small className="muted">
            Fonte: {s.source.status} · valor da Veracode preservado: {shortValue(s.source.value ?? s.source.partial)}
          </small>
        )}
      </div>
      <div className="field">
        <label htmlFor="mv-justification">Justificativa (obrigatória)</label>
        <textarea id="mv-justification" value={justification} onChange={(e) => setJustification(e.target.value)} rows={2} />
      </div>
      {parseError && <ErrorBox message={parseError} />}
      <div className="actions">
        <button className="btn primary" type="button" onClick={save} disabled={justification.trim().length < 10}>
          Salvar valor manual
        </button>
        {s.origin === 'MANUAL' && s.source?.status && (
          <button className="btn" type="button" onClick={() => props.onRevert(justification)} disabled={justification.trim().length < 10}>
            Voltar ao valor da fonte
          </button>
        )}
        <button className="btn" type="button" onClick={props.onCancel}>
          Cancelar
        </button>
      </div>
    </div>
  );
}
