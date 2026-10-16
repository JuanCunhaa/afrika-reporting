import React, { useEffect, useState } from 'react';
import { errorMessage } from '../api';
import { PresentationMeta, SlotAvailability, TemplateSummary, presentations } from '../presentationsApi';
import { Competence, loadOperator, saveOperator, snapshots } from '../snapshotsApi';
import { Empty, ErrorBox, fmtDate, useLoad } from '../ui';
import { Owner, OperatorField, OwnerPicker } from './OwnerPicker';

// F06A: escolha de template por cliente/subcliente e criação de apresentação a partir de competência APROVADA.

export function PresentationsPage({ navigate }: { navigate: (p: string) => void }) {
  const [owner, setOwner] = useState<Owner | null>(null);
  const [operator, setOperator] = useState(loadOperator);
  const [tick, setTick] = useState(0);
  const tpls = useLoad(() => presentations.templates(), [tick]);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const install = async () => {
    setError('');
    try {
      const r = await presentations.installBuiltin(operator);
      setMessage(`Templates demonstrativos: ${r.created.length} instalado(s), ${r.existing.length} já existente(s).`);
      setTick((t) => t + 1);
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  return (
    <section>
      <h2>Apresentações</h2>
      <p className="notice" data-testid="theme-notice">
        Tema demonstrativo neutro — <strong>provisório</strong>. A identidade visual oficial ainda não foi escolhida; os templates
        embutidos são sintéticos. Apresentações usam somente revisões <strong>aprovadas</strong> (F05).
      </p>
      <form className="form panel" aria-label="Dono da apresentação" onSubmit={(e) => e.preventDefault()}>
        <OwnerPicker prefix="p" onChange={setOwner} />
        <OperatorField
          id="p-operator"
          value={operator}
          onChange={(v) => {
            setOperator(v);
            saveOperator(v);
          }}
        />
      </form>
      {error && <ErrorBox message={error} />}
      {message && <p role="status">{message}</p>}
      {tpls.data && tpls.data.items.length === 0 && (
        <div className="panel">
          <p>Nenhum template cadastrado.</p>
          <button type="button" className="btn" onClick={install} disabled={operator.trim().length < 2}>
            Instalar templates demonstrativos
          </button>
        </div>
      )}
      {owner && tpls.data && (
        <OwnerPanel key={`${owner.kind}:${owner.id}`} owner={owner} templates={tpls.data.items} operator={operator} navigate={navigate} />
      )}
    </section>
  );
}

function OwnerPanel(props: { owner: Owner; templates: TemplateSummary[]; operator: string; navigate: (p: string) => void }) {
  const { owner, templates, operator, navigate } = props;
  const [tick, setTick] = useState(0);
  const sel = useLoad(() => presentations.selection(owner.kind, owner.id), [tick]);
  const comps = useLoad(() => snapshots.list(owner.kind, owner.id), []);
  const list = useLoad(() => presentations.list(owner.kind, owner.id), [tick]);
  const [choice, setChoice] = useState('');
  const [competence, setCompetence] = useState('');
  const [override, setOverride] = useState('');
  const [error, setError] = useState('');
  // F06C: seleção flexível de slides conforme os indicadores aprovados da competência (obrigatórios travados)
  const [avail, setAvail] = useState<SlotAvailability | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const opValid = operator.trim().length >= 2;
  const target = override || (sel.data?.template ? `${sel.data.template.key}@${sel.data.template.version}` : '');

  useEffect(() => {
    let alive = true;
    setAvail(null);
    if (!competence || !target) return;
    const [key, v] = target.split('@');
    presentations
      .availability(key, Number(v), competence)
      .then((a) => {
        if (!alive) return;
        setAvail(a);
        setChosen(new Set(a.slots.map((s) => s.slot_id)));
      })
      .catch(() => alive && setAvail(null));
    return () => {
      alive = false;
    };
  }, [competence, target]);

  useEffect(() => {
    const t = sel.data?.template;
    if (t) setChoice(`${t.key}@${t.version}`);
  }, [sel.data]);

  const allVersions = templates.flatMap((t) => (t.versions ?? [t.version]).map((v) => ({ key: t.key, version: v, name: t.name })));
  const approved = (comps.data?.items ?? []).filter((c: Competence) => c.official_revision !== null);
  const pending = (comps.data?.items ?? []).filter((c: Competence) => c.official_revision === null);

  const saveSelection = async () => {
    setError('');
    const [key, v] = choice.split('@');
    try {
      await presentations.select(owner.kind, owner.id, key, Number(v), operator);
      setTick((t) => t + 1);
    } catch (e) {
      setError(errorMessage(e));
    }
  };
  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      const [key, v] = override ? override.split('@') : [undefined, undefined];
      const p = await presentations.create({
        competence_id: competence,
        operator,
        ...(key ? { template_key: key, template_version: Number(v) } : {}),
        // só envia a seleção se ela difere de "todos" (sem seleção = todos os slots do template)
        ...(avail && chosen.size < avail.slots.length ? { slots: avail.slots.filter((s) => chosen.has(s.slot_id)).map((s) => s.slot_id) } : {}),
      });
      navigate(`/presentations/${p.id}`);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <>
      {error && <ErrorBox message={error} />}
      <div className="panel" aria-label="Template do dono">
        <h3>Template de {owner.name}</h3>
        <p data-testid="template-selection">
          {sel.data?.template
            ? `${sel.data.template.name} (${sel.data.template.key} v${sel.data.template.version})${sel.data.inherited ? ' — herdado do cliente' : ''}`
            : 'Nenhum template escolhido.'}
        </p>
        <div className="toolbar">
          <label htmlFor="p-template">Escolher template</label>
          <select id="p-template" value={choice} onChange={(e) => setChoice(e.target.value)}>
            <option value="">Selecione…</option>
            {allVersions.map((t) => (
              <option key={`${t.key}@${t.version}`} value={`${t.key}@${t.version}`}>
                {t.name} — {t.key} v{t.version}
              </option>
            ))}
          </select>
          <button type="button" className="btn" onClick={saveSelection} disabled={!choice || !opValid}>
            Salvar escolha
          </button>
        </div>
      </div>
      <form className="form panel" aria-label="Nova apresentação" onSubmit={create}>
        <h3>Nova apresentação</h3>
        <div className="field">
          <label htmlFor="p-competence">Competência aprovada</label>
          <select id="p-competence" value={competence} onChange={(e) => setCompetence(e.target.value)} required>
            <option value="">Selecione…</option>
            {approved.map((c) => (
              <option key={c.id} value={c.id}>
                {c.competence} — revisão oficial {c.official_revision}
              </option>
            ))}
          </select>
          {pending.length > 0 && (
            <small className="muted" data-testid="pending-competences">
              Sem aprovação (não disponíveis): {pending.map((c) => c.competence).join(', ')}. Aprove-as em Competências.
            </small>
          )}
        </div>
        <div className="field">
          <label htmlFor="p-override">Template (vazio = escolhido para o dono)</label>
          <select id="p-override" value={override} onChange={(e) => setOverride(e.target.value)}>
            <option value="">Template do dono</option>
            {allVersions.map((t) => (
              <option key={`${t.key}@${t.version}`} value={`${t.key}@${t.version}`}>
                {t.name} — {t.key} v{t.version}
              </option>
            ))}
          </select>
        </div>
        {avail && <SlotPicker avail={avail} chosen={chosen} setChosen={setChosen} />}
        <div className="actions">
          <button type="submit" className="btn primary" disabled={!competence || !opValid}>
            Criar apresentação
          </button>
        </div>
      </form>
      <h3>Apresentações de {owner.name}</h3>
      {list.error && <ErrorBox message={list.error} onRetry={list.reload} />}
      {list.data && list.data.items.length === 0 && <Empty>Nenhuma apresentação ainda.</Empty>}
      {list.data && list.data.items.length > 0 && (
        <table aria-label="Lista de apresentações">
          <thead>
            <tr>
              <th>Título</th>
              <th>Competência</th>
              <th>Template</th>
              <th>Revisão</th>
              <th>Atualizada</th>
            </tr>
          </thead>
          <tbody>
            {list.data.items.map((p: PresentationMeta) => (
              <tr key={p.id}>
                <td>
                  <a href={`#/presentations/${p.id}`}>{p.title}</a>
                </td>
                <td>{p.competence.competence}</td>
                <td>
                  {p.template.key} v{p.template.version}
                </td>
                <td>{p.current_revision}</td>
                <td>{fmtDate(p.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}


const STATUS_LABEL: Record<SlotAvailability['slots'][number]['status'], string> = {
  complete: 'todos os indicadores com valor aprovado',
  partial: 'parte dos indicadores sem valor aprovado',
  none: 'nenhum indicador com valor aprovado (mostraria “ausente”)',
  editorial: 'editorial (sem indicadores)',
};

function SlotPicker({ avail, chosen, setChosen }: { avail: SlotAvailability; chosen: Set<string>; setChosen: (s: Set<string>) => void }) {
  const toggle = (id: string) => {
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setChosen(next);
  };
  return (
    <fieldset className="field slot-picker" aria-label="Slides da apresentação" data-testid="slot-picker">
      <legend>
        Slides ({chosen.size} de {avail.slots.length}) — competência {avail.competence.competence}, revisão aprovada {avail.competence.revision}
      </legend>
      <div className="toolbar">
        <button type="button" className="btn" onClick={() => setChosen(new Set(avail.slots.filter((s) => s.suggested).map((s) => s.slot_id)))}>
          Usar sugestão (indicadores disponíveis)
        </button>
        <button type="button" className="btn" onClick={() => setChosen(new Set(avail.slots.map((s) => s.slot_id)))}>
          Todos
        </button>
      </div>
      <ul className="slot-list">
        {avail.slots.map((s) => (
          <li key={s.slot_id}>
            <label>
              <input type="checkbox" checked={s.required || chosen.has(s.slot_id)} disabled={s.required} onChange={() => toggle(s.slot_id)} data-testid={`slot-${s.slot_id}`} />
              {s.title ?? s.slot_id} {s.required && <strong>(obrigatório)</strong>}{' '}
              <small className={`muted slot-status-${s.status}`} data-testid={`slot-status-${s.slot_id}`}>
                {STATUS_LABEL[s.status]}
              </small>
            </label>
          </li>
        ))}
      </ul>
      <small className="muted">{avail.policy}</small>
    </fieldset>
  );
}
