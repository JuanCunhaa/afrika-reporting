import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, errorMessage } from '../api';
import {
  Comparison,
  Interpretation,
  InterpretationConfig,
  InterpretationKind,
  InterpretationLevel,
  InterpretationList,
  interpretationsApi,
} from '../interpretationsApi';
import { fmtDate } from '../ui';

// F08 — painel de análise do slide atual: gerar (executiva/técnica), ver indicadores de origem e validação, revisar
// (iniciar revisão, aprovar, rejeitar), editar, regenerar, comparar versões, aplicar ao slide e desabilitar por slide.
// A geração usa a revisão SALVA da apresentação; aplicar grava uma nova revisão (nunca automático, nunca silencioso).

const STATUS: Record<string, string> = { GENERATED: 'Gerada', IN_REVIEW: 'Em revisão', APPROVED: 'Aprovada', REJECTED: 'Rejeitada' };
const LEVEL: Record<InterpretationLevel, string> = { EXECUTIVE: 'Executiva', TECHNICAL: 'Técnica' };
const FIELD: Record<string, string> = { body: 'corpo do slide', items: 'tópicos do slide', caption: 'legenda do slide', notes: 'notas do apresentador' };

type Props = { pid: string; slideId: string; slideType: string; revision: number; dirty: boolean; operator: string; onApplied: () => Promise<void> | void };

export function InterpretationPanel({ pid, slideId, slideType, revision, dirty, operator, onApplied }: Props) {
  const [config, setConfig] = useState<InterpretationConfig | null>(null);
  const [list, setList] = useState<InterpretationList | null>(null);
  const [selected, setSelected] = useState<Interpretation | null>(null);
  const [kind, setKind] = useState<InterpretationKind | ''>('');
  const [level, setLevel] = useState<InterpretationLevel>('EXECUTIVE');
  const [notes, setNotes] = useState('');
  const [editing, setEditing] = useState<string | null>(null);
  const [justification, setJustification] = useState('');
  const [rejectReason, setRejectReason] = useState('');
  const [compareWith, setCompareWith] = useState('');
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [overwrite, setOverwrite] = useState<string | null>(null); // texto atual do campo, quando a aplicação pede confirmação
  const [error, setError] = useState<ApiError | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);

  const refresh = useCallback(
    async (keep?: string) => {
      const l = await interpretationsApi.list(pid);
      if (!alive.current) return;
      setList(l);
      const mine = l.items.filter((i) => i.slide_id === slideId);
      const target = keep ?? mine.filter((i) => i.is_latest).at(-1)?.id;
      setSelected(target ? await interpretationsApi.get(pid, target) : null);
    },
    [pid, slideId],
  );

  useEffect(() => {
    alive.current = true;
    interpretationsApi.config().then((c) => alive.current && setConfig(c)).catch((e) => alive.current && setError(asApi(e)));
    return () => {
      alive.current = false;
    };
  }, []);

  useEffect(() => {
    setSelected(null);
    setEditing(null);
    setComparison(null);
    setOverwrite(null);
    setMessage('');
    setError(null);
    setKind('');
    refresh().catch((e) => alive.current && setError(asApi(e)));
  }, [refresh]);

  if (!config) return null;
  const kinds = config.kinds_by_slide_type[slideType] ?? [];
  const names = Object.fromEntries(config.kinds.map((k) => [k.kind, k.name]));
  const disabled = list?.disabled_slides[slideId];
  const mine = (list?.items ?? []).filter((i) => i.slide_id === slideId);
  const opValid = operator.trim().length >= 2;

  const run = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setError(null);
    setMessage('');
    try {
      await fn();
      setMessage(done);
    } catch (e) {
      setError(asApi(e));
    } finally {
      setBusy(false);
    }
  };

  const generate = () =>
    run(async () => {
      const iv = await interpretationsApi.generate(pid, {
        slide_id: slideId,
        ...(kind ? { kind } : {}),
        level,
        notes: notes.split('\n').map((n) => n.trim()).filter(Boolean),
        operator,
      });
      await refresh(iv.id);
    }, 'Análise gerada: revise antes de aprovar.');

  const step = (fn: () => Promise<Interpretation>, done: string) =>
    run(async () => {
      const iv = await fn();
      setEditing(null);
      setComparison(null);
      await refresh(iv.id);
    }, done);

  const apply = (confirm: boolean) =>
    run(async () => {
      if (!selected) return;
      try {
        await interpretationsApi.apply(pid, selected.id, operator, revision, confirm);
      } catch (e) {
        const err = asApi(e);
        if (err.code === 'interpretation_overwrite_requires_confirmation') {
          setOverwrite(err.details[0]?.message ?? '');
          throw err;
        }
        throw err;
      }
      setOverwrite(null);
      await onApplied();
      await refresh(selected.id);
    }, 'Texto aprovado aplicado ao slide (nova revisão da apresentação).');

  const toggleDisabled = (value: boolean) =>
    run(async () => {
      await interpretationsApi.setDisabled(pid, slideId, value, operator);
      await refresh();
    }, value ? 'Análise desabilitada neste slide.' : 'Análise reabilitada neste slide.');

  const compare = () =>
    run(async () => {
      if (selected && compareWith) setComparison(await interpretationsApi.compare(pid, compareWith, selected.id));
    }, '');

  const s = selected;
  const blocked = s ? s.validation.blockers > 0 || s.stale.length > 0 : true;

  return (
    <div className="panel" aria-label="Análise do slide" data-testid="interpretation-panel">
      <h3>Análise do slide (assistida)</h3>
      <p className="muted">
        Texto gerado a partir dos valores <strong>aprovados</strong> da revisão salva {revision}, com validação automática dos números, períodos e afirmações. Nada entra no slide sem
        aprovação humana e “Aplicar ao slide”. Provedor: <strong data-testid="interpretation-provider">{config.settings.provider}</strong>
        {config.settings.external_enabled ? '' : ' (local — nada é enviado para fora)'}.
      </p>
      {kinds.length === 0 ? (
        <p className="muted" data-testid="interpretation-not-applicable">
          Este tipo de slide não recebe análise.
        </p>
      ) : disabled ? (
        <div className="notice" data-testid="interpretation-disabled">
          Análise desabilitada neste slide por {disabled.actor}.{' '}
          <button type="button" className="btn small" disabled={busy || !opValid} onClick={() => toggleDisabled(false)}>
            Reabilitar análise
          </button>
        </div>
      ) : (
        <>
          <div className="interp-controls">
            <div className="field">
              <label htmlFor="interp-kind">Tipo de análise</label>
              <select id="interp-kind" value={kind} onChange={(e) => setKind(e.target.value as InterpretationKind)}>
                <option value="">Padrão do slide ({names[kinds[0]]})</option>
                {kinds.map((k) => (
                  <option key={k} value={k}>
                    {names[k]}
                  </option>
                ))}
              </select>
            </div>
            <fieldset className="field">
              <legend>Linguagem</legend>
              {(['EXECUTIVE', 'TECHNICAL'] as InterpretationLevel[]).map((lv) => (
                <label key={lv} className="inline">
                  <input type="radio" name="interp-level" value={lv} checked={level === lv} onChange={() => setLevel(lv)} /> {LEVEL[lv]}
                </label>
              ))}
            </fieldset>
            <div className="field">
              <label htmlFor="interp-notes">Informações editoriais do operador (opcional, uma por linha)</label>
              <textarea id="interp-notes" rows={2} maxLength={2500} value={notes} onChange={(e) => setNotes(e.target.value)} />
              <small className="muted">Contexto que só o operador conhece (ex.: mudança de escopo). Sem e-mails, links ou identificadores.</small>
            </div>
          </div>
          <div className="actions">
            <button type="button" className="btn primary" disabled={busy || !opValid} onClick={generate} data-testid="interpretation-generate">
              Gerar análise
            </button>
            <button type="button" className="btn" disabled={busy || !opValid} onClick={() => toggleDisabled(true)} data-testid="interpretation-disable">
              Desabilitar análise neste slide
            </button>
          </div>
          {dirty && <p className="muted">Há alterações não salvas: a análise usa a revisão salva {revision}.</p>}
        </>
      )}
      {!opValid && <p className="muted">Informe o operador (campo do documento) para gerar ou revisar.</p>}
      {message && (
        <p role="status" data-testid="interpretation-message">
          {message}
        </p>
      )}
      {error && (
        <div role="alert" className="error-box" data-testid="interpretation-error">
          <span>
            {error.message}
            {error.details.length > 0 && error.code !== 'interpretation_overwrite_requires_confirmation' && (
              <ul>
                {error.details.map((d, i) => (
                  <li key={i}>{d.field ? `${d.field}: ${d.message}` : d.message}</li>
                ))}
              </ul>
            )}
          </span>
        </div>
      )}

      {mine.length > 0 && (
        <table aria-label="Versões da análise" data-testid="interpretation-versions">
          <thead>
            <tr>
              <th>Versão</th>
              <th>Tipo</th>
              <th>Linguagem</th>
              <th>Origem</th>
              <th>Situação</th>
              <th>Validação</th>
              <th>Autor</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {mine.map((i) => (
              <tr key={i.id} className={s?.id === i.id ? 'active' : ''}>
                <td>v{i.version}</td>
                <td>{i.kind_name}</td>
                <td>{LEVEL[i.level]}</td>
                <td>{i.origin === 'EDITED' ? 'Edição humana' : i.provider}</td>
                <td>{STATUS[i.status]}</td>
                <td>{i.valid ? 'válida' : `${i.validation.blockers} bloqueio(s)`}</td>
                <td>{i.created_by}</td>
                <td>
                  <button type="button" className="btn small" onClick={() => run(() => refresh(i.id), '')}>
                    Abrir v{i.version}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {s && (
        <div className="interp-detail" data-testid="interpretation-detail" data-status={s.status} data-valid={String(s.valid)}>
          <p>
            <span className="badge" data-testid="interpretation-status">
              {STATUS[s.status]}
            </span>{' '}
            <span className={s.valid ? 'badge ok' : 'badge off'} data-testid="interpretation-validation">
              {s.valid ? 'Validação automática: sem bloqueios' : `Validação automática: ${s.validation.blockers} bloqueio(s)`}
            </span>{' '}
            <small className="muted">
              v{s.version} · {s.kind_name} · {LEVEL[s.level]} · destino: {FIELD[s.target_field]} · {s.created_by}, {fmtDate(s.created_at)} · {s.model ?? s.provider} · prompt {s.prompt_version}
            </small>
          </p>
          {s.stale.length > 0 && (
            <div className="notice" data-testid="interpretation-stale">
              <strong>Interpretação potencialmente desatualizada.</strong>
              <ul>
                {s.stale.map((n, i) => (
                  <li key={i}>{n.message}</li>
                ))}
              </ul>
              Regenere para usar os valores aprovados atuais.
            </div>
          )}
          {s.notices.map((n, i) => (
            <p key={i} className="muted" data-testid="interpretation-notice">
              {n.message}
            </p>
          ))}
          {s.validation.issues.length > 0 && (
            <ul className="warnings" aria-label="Validação" data-testid="interpretation-issues">
              {s.validation.issues.map((i, k) => (
                <li key={k} className={i.level === 'blocker' ? 'blocking' : ''}>
                  [{i.level === 'blocker' ? 'bloqueio' : 'aviso'}] {i.message}
                </li>
              ))}
            </ul>
          )}
          {editing === null ? (
            <div className="interp-text" data-testid="interpretation-text">
              {s.target_field === 'items' ? (
                <ul>
                  {s.statements.map((st, i) => (
                    <li key={i}>{st.text}</li>
                  ))}
                </ul>
              ) : (
                s.text.split('\n').map((line, i) => <p key={i}>{line}</p>)
              )}
            </div>
          ) : (
            <div>
              <div className="field">
                <label htmlFor="interp-edit">Texto ({s.target_field === 'items' ? 'um tópico por linha' : 'parágrafos separados por linha em branco'})</label>
                <textarea id="interp-edit" rows={6} maxLength={4000} value={editing} onChange={(e) => setEditing(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="interp-justification">Justificativa da edição (obrigatória para manter afirmação de causa/remediação)</label>
                <input id="interp-justification" maxLength={1000} value={justification} onChange={(e) => setJustification(e.target.value)} />
              </div>
              <div className="actions">
                <button
                  type="button"
                  className="btn primary"
                  disabled={busy || !opValid || !editing.trim()}
                  onClick={() => step(() => interpretationsApi.edit(pid, s.id, editing, operator, justification.trim() || null), 'Edição salva como nova versão (em revisão).')}
                  data-testid="interpretation-save-edit"
                >
                  Salvar edição
                </button>
                <button type="button" className="btn" onClick={() => setEditing(null)}>
                  Cancelar edição
                </button>
              </div>
            </div>
          )}

          {s.indicators && (
            <details open data-testid="interpretation-indicators">
              <summary>Indicadores de origem usados ({s.indicators.length})</summary>
              <table aria-label="Indicadores de origem">
                <thead>
                  <tr>
                    <th>Indicador</th>
                    <th>Atual</th>
                    <th>Anterior</th>
                    <th>Variação</th>
                    <th>Estado</th>
                    <th>Fonte aprovada</th>
                  </tr>
                </thead>
                <tbody>
                  {s.indicators.map((ind) => (
                    <tr key={ind.fact_id}>
                      <td title={ind.metric_id}>
                        {ind.name}
                        {ind.labels_redacted ? ' (sem nomes)' : ''}
                      </td>
                      <td>{ind.current.label ?? '—'}</td>
                      <td>{ind.previous.label ?? '—'}</td>
                      <td>{ind.delta_label ? `${ind.delta_label}${ind.delta_pct !== null ? ` (${String(ind.delta_pct).replace('.', ',')}%)` : ''}` : ind.delta_unavailable_reason ?? '—'}</td>
                      <td>
                        {ind.definitive ? ind.value_state : `sem valor aprovado (${ind.value_state ?? ind.state})`}
                        {ind.origin === 'MANUAL' ? ' · manual' : ''}
                      </td>
                      <td>
                        rev. {ind.provenance.current.revision ?? '—'} · aprov. {ind.provenance.current.approval_sequence ?? '—'}
                        {ind.provenance.current.content_hash ? ` · ${ind.provenance.current.content_hash.slice(0, 10)}…` : ''}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {s.editorial_notes && s.editorial_notes.length > 0 && <p className="muted">Notas editoriais usadas: {s.editorial_notes.join(' · ')}</p>}
            </details>
          )}

          {s.is_latest && editing === null && (
            <div className="actions">
              {s.status === 'GENERATED' && (
                <button type="button" className="btn" disabled={busy || !opValid} onClick={() => step(() => interpretationsApi.review(pid, s.id, operator), 'Revisão iniciada.')} data-testid="interpretation-review">
                  Iniciar revisão
                </button>
              )}
              {s.status === 'IN_REVIEW' && (
                <button
                  type="button"
                  className="btn primary"
                  disabled={busy || !opValid || blocked}
                  title={blocked ? 'Corrija os bloqueios da validação ou regenere (desatualizada)' : undefined}
                  onClick={() => step(() => interpretationsApi.approve(pid, s.id, operator), 'Análise aprovada.')}
                  data-testid="interpretation-approve"
                >
                  Aprovar
                </button>
              )}
              {s.status === 'APPROVED' && (
                <button
                  type="button"
                  className="btn primary"
                  disabled={busy || !opValid || dirty || s.stale.length > 0}
                  title={dirty ? 'Salve ou descarte as alterações do documento antes de aplicar' : undefined}
                  onClick={() => apply(false)}
                  data-testid="interpretation-apply"
                >
                  Aplicar ao slide
                </button>
              )}
              <button type="button" className="btn" disabled={busy} onClick={() => (setEditing(s.target_field === 'items' ? s.statements.map((x) => x.text).join('\n') : s.text), setJustification(''))} data-testid="interpretation-edit">
                Editar texto
              </button>
              <button type="button" className="btn" disabled={busy || !opValid} onClick={() => step(() => interpretationsApi.regenerate(pid, s.id, operator, level), 'Nova versão gerada.')} data-testid="interpretation-regenerate">
                Regenerar ({LEVEL[level]})
              </button>
              {(s.status === 'GENERATED' || s.status === 'IN_REVIEW') && (
                <span className="inline">
                  <input aria-label="Motivo da rejeição" placeholder="Motivo da rejeição" maxLength={1000} value={rejectReason} onChange={(e) => setRejectReason(e.target.value)} />
                  <button
                    type="button"
                    className="btn danger"
                    disabled={busy || !opValid || !rejectReason.trim()}
                    onClick={() => step(() => interpretationsApi.reject(pid, s.id, operator, rejectReason.trim()), 'Análise rejeitada.').then(() => setRejectReason(''))}
                    data-testid="interpretation-reject"
                  >
                    Rejeitar
                  </button>
                </span>
              )}
            </div>
          )}
          {overwrite !== null && (
            <div className="notice" data-testid="interpretation-overwrite">
              O campo do slide já tem texto (possivelmente revisado):
              <blockquote>{overwrite || '—'}</blockquote>
              <button type="button" className="btn danger" disabled={busy} onClick={() => apply(true)} data-testid="interpretation-overwrite-confirm">
                Substituir pelo texto aprovado
              </button>{' '}
              <button type="button" className="btn" onClick={() => (setOverwrite(null), setError(null))}>
                Manter o texto atual
              </button>
            </div>
          )}
          {s.applied.length > 0 && (
            <p className="muted" data-testid="interpretation-applied">
              Aplicada na revisão {s.applied.map((a) => a.presentation_revision).join(', ')} da apresentação.
            </p>
          )}

          {s.history && s.history.length > 1 && (
            <div className="inline" data-testid="interpretation-compare">
              <label htmlFor="interp-compare">Comparar com</label>{' '}
              <select id="interp-compare" value={compareWith} onChange={(e) => setCompareWith(e.target.value)}>
                <option value="">—</option>
                {s.history
                  .filter((h) => h.id !== s.id)
                  .map((h) => (
                    <option key={h.id} value={h.id}>
                      v{h.version} ({STATUS[h.status]})
                    </option>
                  ))}
              </select>{' '}
              <button type="button" className="btn small" disabled={!compareWith || busy} onClick={compare}>
                Comparar versões
              </button>
            </div>
          )}
          {comparison && (
            <p className="interp-diff" data-testid="interpretation-diff">
              v{comparison.from.version} → v{comparison.to.version}
              {comparison.same_facts ? ' (mesmos fatos)' : ' (fatos diferentes)'}:{' '}
              {comparison.diff.map((d, i) =>
                d.op === 'equal' ? (
                  <span key={i}>{d.from} </span>
                ) : (
                  <span key={i}>
                    {d.from && <del>{d.from}</del>} {d.to && <ins>{d.to}</ins>}{' '}
                  </span>
                ),
              )}
            </p>
          )}
          <details>
            <summary>Histórico de revisão</summary>
            <ul data-testid="interpretation-events">
              {s.events.map((e) => (
                <li key={e.sequence}>
                  {fmtDate(e.at)} — {STATUS[e.event] ?? (e.event === 'APPLIED' ? `Aplicada (revisão ${e.presentation_revision})` : e.event)} por {e.actor}
                  {e.reason ? `: ${e.reason}` : ''}
                </li>
              ))}
            </ul>
          </details>
        </div>
      )}
    </div>
  );
}

function asApi(e: unknown): ApiError {
  return e instanceof ApiError ? e : new ApiError(0, 'error', errorMessage(e));
}
