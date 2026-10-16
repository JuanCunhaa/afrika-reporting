import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, errorMessage } from '../api';
import { SlideCanvas } from '../presentation/SlideView';
import {
  Catalog,
  DocSlide,
  PresentationDocument,
  PresentationIntegrity,
  PresentationMeta,
  PresentationView,
  SlideFields,
  SlideOptions,
  SlideType,
  SlideTypeSpec,
  Zone,
  ZoneSpec,
  presentations,
} from '../presentationsApi';
import { VALUE_STATE_LABEL, ValueState, loadOperator, saveOperator } from '../snapshotsApi';
import { ErrorBox, Loading, fmtDate } from '../ui';
import { OperatorField, shortValue } from './OwnerPicker';

// F06A: editor de apresentação. Edita SÓ conteúdo editorial (textos, ordem, slides, indicadores compatíveis, opções).
// Valores vêm das revisões aprovadas fixadas e não são editáveis aqui: correção = nova revisão em Competências (F05).

const FIELD_LABEL: Record<keyof SlideFields, string> = {
  title: 'Título',
  subtitle: 'Subtítulo',
  body: 'Texto',
  items: 'Tópicos (um por linha)',
  chart_title: 'Título do gráfico',
  legend_title: 'Título da legenda',
  caption: 'Legenda / observação',
  notes: 'Notas do apresentador',
};
const LONG_FIELDS = new Set(['body', 'notes', 'items']);
const HEADLINE = ['count', 'decimal', 'percentage', 'by_severity'];
const CATEGORY = ['breakdown', 'ranking', 'by_severity'];

function compatibleTypes(spec: SlideTypeSpec, dataMode: string | null | undefined): string[] {
  if (spec.type !== 'bar_chart') return spec.value_types;
  return dataMode === 'history' ? HEADLINE : CATEGORY;
}

function newSlide(spec: SlideTypeSpec, catalog: Catalog): DocSlide {
  const options: Partial<SlideOptions> = spec.type === 'bar_chart' ? { data_mode: 'breakdown' } : {};
  const types = compatibleTypes(spec, options.data_mode);
  const first = catalog.metrics.find((m) => types.includes(m.value_type));
  return {
    slide_id: `${spec.type.replace(/_/g, '-')}-${Date.now().toString(36)}`,
    template_slot: null,
    type: spec.type,
    layout: spec.default_layout,
    fields: { title: spec.name, items: [] },
    metrics: spec.min_metrics > 0 && first ? [first.metric_id] : [],
    options,
  };
}

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));

export function PresentationEditorPage({ pid }: { pid: string }) {
  const [meta, setMeta] = useState<PresentationMeta | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [doc, setDoc] = useState<PresentationDocument | null>(null);
  const [saved, setSaved] = useState<PresentationDocument | null>(null);
  const [view, setView] = useState<PresentationView | null>(null);
  const [viewing, setViewing] = useState<number | null>(null); // revisão antiga (somente leitura)
  const [current, setCurrent] = useState(0);
  const [operator, setOperator] = useState(loadOperator);
  const [summary, setSummary] = useState('');
  const [error, setError] = useState('');
  const [previewError, setPreviewError] = useState<ApiError | null>(null);
  const [message, setMessage] = useState('');
  const [integrity, setIntegrity] = useState<PresentationIntegrity | null>(null);
  const [presenting, setPresenting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [savedView, setSavedView] = useState<PresentationView | null>(null); // visualização da revisão salva

  // F06B.1 — ordem das respostas: `seq` invalida pré-visualizações em voo (toda edição, recarga ou salvamento cria
  // uma nova geração; resposta de geração antiga é descartada); `loadSeq` faz valer só a recarga mais recente.
  const seq = useRef(0);
  const loadSeq = useRef(0);
  const saving = useRef(false); // guarda síncrona contra duplo clique (o estado `busy` só vale após re-render)

  const reload = useCallback(async () => {
    setError('');
    const n = ++loadSeq.current;
    seq.current++;
    try {
      const [m, c] = await Promise.all([presentations.get(pid), catalog ? Promise.resolve(catalog) : presentations.catalog()]);
      const [r, v] = await Promise.all([presentations.revision(pid, m.current_revision), presentations.view(pid)]);
      if (n !== loadSeq.current) return;
      seq.current++;
      setMeta(m);
      setCatalog(c);
      setDoc(r.document);
      setSaved(r.document);
      setView(v);
      setSavedView(v);
      setViewing(null);
      setPreviewError(null);
    } catch (e) {
      if (n === loadSeq.current) setError(errorMessage(e));
    }
  }, [pid, catalog]);

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pid]);

  const dirty = doc !== null && saved !== null && JSON.stringify(doc) !== JSON.stringify(saved);

  // Pré-visualização ao vivo do documento não salvo (servidor monta a IR; nada é gravado). Sem alterações pendentes,
  // nenhuma pré-visualização em voo pode mais substituir a tela: vale a visualização da revisão salva.
  useEffect(() => {
    if (!doc || viewing !== null) return;
    if (!dirty) {
      seq.current++;
      if (savedView) setView(savedView);
      setPreviewError(null); // erro de um rascunho que não existe mais
      return;
    }
    const n = ++seq.current;
    const t = window.setTimeout(() => {
      presentations
        .preview(pid, doc)
        .then((v) => n === seq.current && (setView(v), setPreviewError(null)))
        .catch((e) => n === seq.current && setPreviewError(e instanceof ApiError ? e : new ApiError(0, 'error', errorMessage(e))));
    }, 250);
    return () => window.clearTimeout(t);
  }, [doc, dirty, pid, viewing, savedView]);

  if (error && !meta) return <ErrorBox message={error} onRetry={reload} />;
  if (!meta || !doc || !view || !catalog) return <Loading label="Carregando apresentação…" />;

  const readOnly = viewing !== null;
  const specs = Object.fromEntries(catalog.slide_types.map((s) => [s.type, s])) as Record<SlideType, SlideTypeSpec>;
  // Edição: o DOCUMENTO define ordem e seleção; a visualização (IR do servidor) é casada por slide_id e pode estar
  // momentaneamente atrasada (pré-visualização pendente). Somente leitura: a revisão visualizada define tudo.
  const count = readOnly ? view.slides.length : doc.slides.length;
  const idx = Math.max(0, Math.min(current, count - 1));
  const docSlide = readOnly ? undefined : doc.slides[idx];
  const slide = readOnly ? view.slides[idx] : view.slides.find((s) => s.slide_id === docSlide?.slide_id);
  const requiredIds = new Set(view.slides.filter((s) => s.required).map((s) => s.slide_id));

  const update = (fn: (d: PresentationDocument) => void) => {
    const next = clone(doc);
    fn(next);
    setDoc(next);
  };
  const move = (i: number, delta: number) =>
    update((d) => {
      const [s] = d.slides.splice(i, 1);
      d.slides.splice(i + delta, 0, s);
      setCurrent(i + delta);
    });
  const remove = (i: number) =>
    update((d) => {
      d.slides.splice(i, 1);
      setCurrent(Math.max(0, i - 1));
    });
  const go = (delta: number) => setCurrent((c) => Math.max(0, Math.min(count - 1, c + delta)));
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowRight' || e.key === 'PageDown') go(1);
    if (e.key === 'ArrowLeft' || e.key === 'PageUp') go(-1);
    if (e.key === 'Escape') setPresenting(false);
  };

  const act = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      await fn();
      setMessage(done);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  // F06B.1 — salvar: o estado salvo vem da resposta do PUT (fonte da verdade). A releitura seguinte só atualiza
  // metadados/visualização: NUNCA sobrescreve edições feitas enquanto o PUT estava em andamento, e uma falha nela é
  // informada como tal (a revisão já foi gravada; sem nova tentativa automática).
  const save = async () => {
    if (saving.current || !doc) return;
    saving.current = true;
    const sent = doc;
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const m = await presentations.save(pid, sent, meta.current_revision, operator, summary);
      setMeta(m);
      setSaved(sent);
      setSummary('');
      setMessage(`Revisão ${m.current_revision} salva.`);
      const n = ++seq.current;
      try {
        const [r, v] = await Promise.all([presentations.revision(pid, m.current_revision), presentations.view(pid)]);
        setSaved(r.document);
        setDoc((cur) => (cur !== null && JSON.stringify(cur) === JSON.stringify(sent) ? r.document : cur));
        setSavedView(v);
        if (n === seq.current) setView(v); // senão, uma edição mais nova já pediu a própria pré-visualização
      } catch (e) {
        setError(`A revisão ${m.current_revision} foi gravada, mas a releitura falhou: ${errorMessage(e)}. Recarregue a página para atualizar a visualização.`);
      }
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      saving.current = false;
      setBusy(false);
    }
  };
  const rebind = () =>
    act(async () => {
      await presentations.rebind(pid, meta.current_revision, operator);
      await reload();
    }, 'Fontes aprovadas atualizadas (nova revisão).');
  const showRevision = (n: number) =>
    act(async () => {
      if (n === meta.current_revision) return reload();
      setView(await presentations.view(pid, n));
      setViewing(n);
    }, '');
  const checkIntegrity = () => act(async () => setIntegrity(await presentations.integrity(pid)), '');

  const opValid = operator.trim().length >= 2;
  const issues = [...view.checks, ...(slide?.issues ?? [])];

  return (
    <section className="editor">
      <div className="toolbar">
        <a href="#/presentations">← Apresentações</a>
        <h2 data-testid="presentation-title">{view.presentation.title}</h2>
        <span className="badge">
          {view.template.key} v{view.template.version}
        </span>
        <span className="badge" data-testid="presentation-revision">
          {readOnly ? `Revisão ${viewing} (somente leitura)` : `Revisão ${meta.current_revision}${dirty ? ' · alterações não salvas' : ''}`}
        </span>
      </div>
      <p className="notice">
        {view.theme.notice} Valores vêm da revisão <strong>aprovada</strong> {view.sources.primary.revision} da competência{' '}
        {view.competence.competence} (hash <code title={view.sources.primary.content_hash}>{view.sources.primary.content_hash.slice(0, 12)}…</code>) e{' '}
        <strong>não são editáveis aqui</strong>. Para corrigir um indicador, crie uma nova revisão em{' '}
        <a href={`#/snapshots/${view.competence.id}`}>Competências</a>, aprove-a e use “Atualizar fontes aprovadas”.
      </p>
      {error && (
        <div data-testid="editor-error">
          <ErrorBox message={error} />
        </div>
      )}
      {message && (
        <p role="status" data-testid="editor-message">
          {message}
        </p>
      )}
      {previewError && (
        <div role="alert" className="error-box" data-testid="preview-error">
          <span>
            {previewError.message}
            {previewError.details.length > 0 && `: ${previewError.details.map((d) => d.message).join('; ')}`}
          </span>
        </div>
      )}

      <div className="editor-layout">
        <aside className="slide-list" aria-label="Slides">
          <ol>
            {(readOnly ? view.slides.map((s) => ({ slide_id: s.slide_id, type: s.type, fields: s.fields })) : doc.slides).map((s, i) => (
              <li key={s.slide_id} className={i === idx ? 'active' : ''} data-testid={`slide-item-${s.slide_id}`}>
                <button type="button" className="slide-pick" onClick={() => setCurrent(i)} aria-current={i === idx ? 'true' : undefined}>
                  <span className="muted">{i + 1}.</span> {s.fields.title || specs[s.type].name}
                  <small className="muted">
                    {specs[s.type].name}
                    {requiredIds.has(s.slide_id) ? ' · obrigatório' : ''}
                  </small>
                </button>
                {!readOnly && (
                  <span className="row-actions">
                    <button type="button" className="btn small" aria-label={`Mover para cima: ${s.slide_id}`} disabled={i === 0} onClick={() => move(i, -1)}>
                      ↑
                    </button>
                    <button
                      type="button"
                      className="btn small"
                      aria-label={`Mover para baixo: ${s.slide_id}`}
                      disabled={i === doc.slides.length - 1}
                      onClick={() => move(i, 1)}
                    >
                      ↓
                    </button>
                    <button
                      type="button"
                      className="btn small danger"
                      aria-label={`Remover slide: ${s.slide_id}`}
                      disabled={requiredIds.has(s.slide_id) || doc.slides.length === 1}
                      title={requiredIds.has(s.slide_id) ? 'Slide obrigatório do template' : undefined}
                      onClick={() => remove(i)}
                    >
                      ✕
                    </button>
                  </span>
                )}
              </li>
            ))}
          </ol>
          {!readOnly && <AddSlide catalog={catalog} onAdd={(s) => update((d) => (d.slides.splice(idx + 1, 0, s), setCurrent(idx + 1)))} />}
        </aside>

        <div className="slide-stage">
          <div className="stage-nav">
            <button type="button" className="btn small" onClick={() => go(-1)} disabled={idx === 0}>
              ← Slide anterior
            </button>
            <span data-testid="slide-counter">
              {idx + 1} / {count}
            </span>
            <button type="button" className="btn small" onClick={() => go(1)} disabled={idx >= count - 1}>
              Próximo slide →
            </button>
            <button type="button" className="btn small" onClick={() => setPresenting(true)}>
              Apresentar
            </button>
          </div>
          <div tabIndex={0} onKeyDown={onKey} className="stage-focus" aria-label="Pré-visualização (setas navegam)">
            {slide ? (
              <SlideCanvas view={view} slide={slide} />
            ) : (
              <p className="empty" role="status">
                {previewError ? 'Pré-visualização indisponível: corrija o documento.' : 'Atualizando pré-visualização…'}
              </p>
            )}
          </div>
          {slide?.fields.notes && (
            <p className="muted" data-testid="speaker-notes">
              Notas do apresentador: {slide.fields.notes}
            </p>
          )}
          {issues.length > 0 && (
            <ul className="warnings" aria-label="Pendências" data-testid="issues">
              {issues.map((i, k) => (
                <li key={k} className={i.level === 'blocker' ? 'blocking' : ''}>
                  [{i.level === 'blocker' ? 'bloqueio' : i.level === 'warning' ? 'aviso' : 'info'}] {i.message}
                </li>
              ))}
            </ul>
          )}
          <p className="muted" data-testid="readiness">
            {view.ready ? 'Sem bloqueios para exportação futura (F07).' : `${view.blockers} bloqueio(s): indicadores obrigatórios sem valor aprovado.`}
          </p>
        </div>

        <aside className="slide-props" aria-label="Propriedades do slide">
          {readOnly ? (
            <div>
              <p>Visualizando a revisão {viewing} (somente leitura).</p>
              <button type="button" className="btn" onClick={reload}>
                Voltar à revisão atual
              </button>
            </div>
          ) : (
            docSlide && (
              <SlideProps
                key={docSlide.slide_id}
                spec={specs[docSlide.type]}
                slide={docSlide}
                catalog={catalog}
                onChange={(s) => update((d) => (d.slides[d.slides.findIndex((x) => x.slide_id === s.slide_id)] = s))}
              />
            )
          )}
        </aside>
      </div>

      {!readOnly && (
        <div className="panel" aria-label="Documento">
          <h3>Documento</h3>
          <div className="field">
            <label htmlFor="doc-title">Título da apresentação</label>
            <input id="doc-title" value={doc.title} maxLength={200} onChange={(e) => update((d) => (d.title = e.target.value))} />
          </div>
          <Presenters doc={doc} update={update} />
          <OperatorField
            id="e-operator"
            value={operator}
            onChange={(v) => {
              setOperator(v);
              saveOperator(v);
            }}
          />
          <div className="field">
            <label htmlFor="e-summary">Resumo da alteração</label>
            <input id="e-summary" value={summary} maxLength={500} onChange={(e) => setSummary(e.target.value)} />
          </div>
          <div className="actions">
            <button type="button" className="btn primary" disabled={!dirty || !opValid || busy || !!previewError} onClick={save}>
              Salvar revisão
            </button>
            <button type="button" className="btn" disabled={!dirty || busy} onClick={reload}>
              Descartar alterações
            </button>
            <button type="button" className="btn" disabled={dirty || !opValid || busy} onClick={rebind} title="Fixa as aprovações vigentes (nova revisão)">
              Atualizar fontes aprovadas
            </button>
            <button type="button" className="btn" disabled={busy} onClick={checkIntegrity}>
              Verificar integridade
            </button>
          </div>
          {integrity && (
            <p data-testid="presentation-integrity" className={integrity.ok ? 'notice valid' : 'notice'}>
              {integrity.ok
                ? `Integridade: OK · ${integrity.revisions_checked} revisão(ões) · ${integrity.sources_checked.length} fonte(s) aprovada(s) conferida(s)`
                : `Integridade: FALHA — ${integrity.problems.join('; ')}`}
            </p>
          )}
        </div>
      )}

      <SourcesPanel view={view} />

      <div className="panel">
        <h3>Revisões da apresentação</h3>
        <table aria-label="Revisões da apresentação">
          <thead>
            <tr>
              <th>Nº</th>
              <th>Autor (declarado)</th>
              <th>Quando</th>
              <th>Resumo</th>
              <th>Fonte</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {meta.revisions.map((r) => (
              <tr key={r.number}>
                <td>{r.number}</td>
                <td>{r.created_by}</td>
                <td>{fmtDate(r.created_at)}</td>
                <td>{r.change_summary || '—'}</td>
                <td>
                  rev. {r.source_revision} · aprov. {r.source_approval_sequence}
                </td>
                <td>
                  <button type="button" className="btn small" disabled={dirty} onClick={() => showRevision(r.number)}>
                    Visualizar revisão {r.number}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {presenting && slide && (
        <div className="presenter-overlay" role="dialog" aria-modal="true" aria-label="Modo apresentação" tabIndex={-1} onKeyDown={onKey} ref={(el) => el?.focus()}>
          <SlideCanvas view={view} slide={slide} />
          <div className="presenter-nav">
            <button type="button" className="btn small" onClick={() => go(-1)}>
              ←
            </button>
            <span>
              {idx + 1} / {count}
            </span>
            <button type="button" className="btn small" onClick={() => go(1)}>
              →
            </button>
            <button type="button" className="btn small" onClick={() => setPresenting(false)}>
              Sair (Esc)
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function AddSlide({ catalog, onAdd }: { catalog: Catalog; onAdd: (s: DocSlide) => void }) {
  const [type, setType] = useState<SlideType>('kpis');
  return (
    <div className="add-slide">
      <label htmlFor="add-type">Tipo do novo slide</label>
      <select id="add-type" value={type} onChange={(e) => setType(e.target.value as SlideType)}>
        {catalog.slide_types.map((s) => (
          <option key={s.type} value={s.type}>
            {s.name}
          </option>
        ))}
      </select>
      <button type="button" className="btn small" onClick={() => onAdd(newSlide(catalog.slide_types.find((s) => s.type === type)!, catalog))}>
        Adicionar slide
      </button>
    </div>
  );
}

function SlideProps({ spec, slide, catalog, onChange }: { spec: SlideTypeSpec; slide: DocSlide; catalog: Catalog; onChange: (s: DocSlide) => void }) {
  const set = (fn: (s: DocSlide) => void) => {
    const next = clone(slide);
    fn(next);
    onChange(next);
  };
  const types = compatibleTypes(spec, slide.options.data_mode);
  const metrics = catalog.metrics.filter((m) => types.includes(m.value_type));
  const full = slide.metrics.length >= spec.max_metrics;
  return (
    <div className="form">
      <h3>{spec.name}</h3>
      <p className="muted">{spec.description}</p>
      <div className="field">
        <label htmlFor="sp-layout">Layout</label>
        <select
          id="sp-layout"
          value={slide.layout}
          onChange={(e) =>
            set((s) => {
              s.layout = e.target.value;
              // painel composto: só ficam as zonas que existem no novo layout
              if (spec.zones) {
                const ids = new Set((spec.zones[s.layout] ?? []).map((z) => z.zone));
                s.zones = Object.fromEntries(Object.entries(s.zones ?? {}).filter(([k]) => ids.has(k)));
              }
            })
          }
        >
          {spec.layouts.map((l) => (
            <option key={l}>{l}</option>
          ))}
        </select>
      </div>
      {spec.editable_fields.map((f) => {
        const id = `sp-${f}`;
        const req = spec.required_fields.includes(f);
        const label = `${FIELD_LABEL[f]}${req ? ' (obrigatório)' : ''}`;
        if (f === 'items')
          return (
            <div className="field" key={f}>
              <label htmlFor={id}>{label}</label>
              <textarea
                id={id}
                rows={4}
                value={(slide.fields.items ?? []).join('\n')}
                onChange={(e) => set((s) => (s.fields.items = e.target.value.split('\n').filter((x) => x.trim())))}
              />
            </div>
          );
        const value = (slide.fields[f] as string | null | undefined) ?? '';
        return (
          <div className="field" key={f}>
            <label htmlFor={id}>{label}</label>
            {LONG_FIELDS.has(f) ? (
              <textarea id={id} rows={3} value={value} onChange={(e) => set((s) => ((s.fields as Record<string, unknown>)[f] = e.target.value || null))} />
            ) : (
              <input id={id} value={value} onChange={(e) => set((s) => ((s.fields as Record<string, unknown>)[f] = e.target.value || null))} />
            )}
          </div>
        );
      })}
      {spec.options.includes('data_mode') && (
        <div className="field">
          <label htmlFor="sp-mode">Dados do gráfico</label>
          <select
            id="sp-mode"
            value={slide.options.data_mode ?? 'breakdown'}
            onChange={(e) =>
              set((s) => {
                s.options.data_mode = e.target.value as 'breakdown' | 'history';
                const ok = compatibleTypes(spec, s.options.data_mode);
                s.metrics = s.metrics.filter((m) => ok.includes(catalog.metrics.find((x) => x.metric_id === m)?.value_type ?? ''));
              })
            }
          >
            <option value="breakdown">Categorias da competência</option>
            <option value="history">Série mensal aprovada</option>
          </select>
        </div>
      )}
      {spec.options.includes('months') && (spec.type !== 'bar_chart' || slide.options.data_mode === 'history') && (
        <div className="field">
          <label htmlFor="sp-months">Meses</label>
          <select id="sp-months" value={slide.options.months ?? 6} onChange={(e) => set((s) => (s.options.months = Number(e.target.value) as 6 | 12))}>
            <option value={6}>6 meses</option>
            <option value={12}>12 meses</option>
          </select>
        </div>
      )}
      {spec.options.includes('top_n') && (
        <div className="field">
          <label htmlFor="sp-top">Itens no ranking (máx. 10)</label>
          <input id="sp-top" type="number" min={1} max={10} value={slide.options.top_n ?? 10} onChange={(e) => set((s) => (s.options.top_n = Math.max(1, Math.min(10, Number(e.target.value) || 10))))} />
        </div>
      )}
      {(['show_values', 'show_legend', 'show_presenters'] as const)
        .filter((o) => spec.options.includes(o))
        .map((o) => (
          <label key={o} className="inline">
            <input type="checkbox" checked={slide.options[o] !== false && (o !== 'show_presenters' || slide.options[o] === true)} onChange={(e) => set((s) => (s.options[o] = e.target.checked))} />
            {{ show_values: 'Mostrar valores', show_legend: 'Mostrar legenda', show_presenters: 'Mostrar apresentadores' }[o]}
          </label>
        ))}
      {spec.zones && (
        <fieldset className="field">
          <legend>Zonas do painel</legend>
          {(spec.zones[slide.layout] ?? []).map((z) => (
            <ZoneEditor
              key={`${slide.layout}-${z.zone}`}
              spec={z}
              zone={slide.zones?.[z.zone]}
              catalog={catalog}
              onChange={(next) =>
                set((s) => {
                  const zones = { ...(s.zones ?? {}) };
                  if (next) zones[z.zone] = next;
                  else delete zones[z.zone];
                  s.zones = zones;
                })
              }
            />
          ))}
        </fieldset>
      )}
      {spec.max_metrics > 0 && (
        <fieldset className="field checklist">
          <legend>
            Indicadores compatíveis ({slide.metrics.length}/{spec.max_metrics})
          </legend>
          <div className="checklist-items">
            {metrics.map((m) => (
              <label key={m.metric_id} className="inline" title={m.name}>
                <input
                  type="checkbox"
                  checked={slide.metrics.includes(m.metric_id)}
                  disabled={!slide.metrics.includes(m.metric_id) && full}
                  onChange={(e) =>
                    set((s) => {
                      s.metrics = e.target.checked
                        ? spec.max_metrics === 1
                          ? [m.metric_id]
                          : [...s.metrics, m.metric_id]
                        : s.metrics.filter((x) => x !== m.metric_id);
                    })
                  }
                />
                {m.metric_id}
              </label>
            ))}
          </div>
        </fieldset>
      )}
    </div>
  );
}

const HEADLINE_TYPES = ['count', 'decimal', 'percentage', 'by_severity'];
const CATEGORY_TYPES = ['breakdown', 'ranking', 'by_severity'];

/** Tipos de valor aceitos pela zona (gráfico: série mensal exige número principal; categorias, distribuição). */
function zoneTypes(spec: ZoneSpec, zone: Zone | undefined): string[] {
  if (spec.kind !== 'chart') return spec.value_types;
  const history = zone?.chart === 'line' || zone?.chart === 'combo' || zone?.data_mode === 'history' || (!zone?.chart && spec.charts[0] !== 'bar');
  return spec.value_types.filter((t) => (history ? HEADLINE_TYPES : CATEGORY_TYPES).includes(t));
}

function ZoneEditor({ spec, zone, catalog, onChange }: { spec: ZoneSpec; zone: Zone | undefined; catalog: Catalog; onChange: (z: Zone | undefined) => void }) {
  const z: Zone = zone ?? { metrics: [] };
  const id = `zone-${spec.zone}`;
  const types = zoneTypes(spec, z);
  const options = catalog.metrics.filter((m) => types.includes(m.value_type));
  const full = z.metrics.length >= spec.max_metrics;
  const put = (patch: Partial<Zone>) => onChange({ ...z, ...patch });
  const history = z.chart === 'line' || z.chart === 'combo' || z.data_mode === 'history';
  return (
    <div className="zone-editor" data-testid={`zone-editor-${spec.zone}`}>
      <strong>
        {spec.name} <small className="muted">({spec.zone})</small>
      </strong>
      {spec.kind === 'text' ? (
        <p className="muted">Texto editorial: usa o campo “{spec.text_field === 'items' ? 'Tópicos' : 'Texto'}” do slide.</p>
      ) : (
        <>
          <label htmlFor={`${id}-title`}>Título da zona</label>
          <input id={`${id}-title`} value={z.title ?? ''} maxLength={120} onChange={(e) => put({ title: e.target.value || null })} />
          {spec.charts.length > 0 && (
            <>
              <label htmlFor={`${id}-chart`}>Gráfico</label>
              <select id={`${id}-chart`} value={z.chart ?? spec.charts[0]} onChange={(e) => put({ chart: e.target.value as Zone['chart'], metrics: [] })}>
                {spec.charts.map((c) => (
                  <option key={c} value={c}>
                    {{ bar: 'Barras', line: 'Linhas', combo: 'Barras + linha' }[c] ?? c}
                  </option>
                ))}
              </select>
              {(z.chart ?? spec.charts[0]) === 'bar' && (
                <>
                  <label htmlFor={`${id}-mode`}>Dados</label>
                  <select id={`${id}-mode`} value={z.data_mode ?? 'breakdown'} onChange={(e) => put({ data_mode: e.target.value as Zone['data_mode'], metrics: [] })}>
                    <option value="breakdown">Categorias da competência</option>
                    <option value="history">Série mensal aprovada</option>
                  </select>
                </>
              )}
              {(history || (z.chart ?? spec.charts[0]) !== 'bar') && (
                <>
                  <label htmlFor={`${id}-months`}>Meses</label>
                  <select id={`${id}-months`} value={z.months ?? 6} onChange={(e) => put({ months: Number(e.target.value) as 6 | 12 })}>
                    <option value={6}>6 meses</option>
                    <option value={12}>12 meses</option>
                  </select>
                </>
              )}
            </>
          )}
          {spec.kind === 'ranking' && (
            <>
              <label htmlFor={`${id}-top`}>Itens (máx. 10)</label>
              <input id={`${id}-top`} type="number" min={1} max={10} value={z.top_n ?? 10} onChange={(e) => put({ top_n: Math.max(1, Math.min(10, Number(e.target.value) || 10)) })} />
            </>
          )}
          <div className="checklist-items" aria-label={`Indicadores da zona ${spec.name}`}>
            {options.map((m) => (
              <label key={m.metric_id} className="inline" title={m.name}>
                <input
                  type="checkbox"
                  checked={z.metrics.includes(m.metric_id)}
                  disabled={!z.metrics.includes(m.metric_id) && full}
                  onChange={(e) => put({ metrics: e.target.checked ? (spec.max_metrics === 1 ? [m.metric_id] : [...z.metrics, m.metric_id]) : z.metrics.filter((x) => x !== m.metric_id) })}
                />
                {m.metric_id}
              </label>
            ))}
          </div>
          <small className="muted">
            {z.metrics.length}/{spec.max_metrics} indicador(es){spec.min_metrics > 0 ? ` · mínimo ${spec.min_metrics}` : ''}
          </small>
          {zone && (
            <button type="button" className="btn small" onClick={() => onChange(undefined)}>
              Esvaziar zona
            </button>
          )}
        </>
      )}
    </div>
  );
}

function Presenters({ doc, update }: { doc: PresentationDocument; update: (fn: (d: PresentationDocument) => void) => void }) {
  return (
    <fieldset className="field">
      <legend>Apresentadores</legend>
      {doc.presenters.map((p, i) => (
        <div key={i} className="toolbar">
          <input aria-label={`Nome do apresentador ${i + 1}`} value={p.name} maxLength={120} onChange={(e) => update((d) => (d.presenters[i].name = e.target.value))} />
          <input aria-label={`Papel do apresentador ${i + 1}`} value={p.role ?? ''} maxLength={120} onChange={(e) => update((d) => (d.presenters[i].role = e.target.value || null))} />
          <button type="button" className="btn small danger" onClick={() => update((d) => d.presenters.splice(i, 1))}>
            Remover apresentador
          </button>
        </div>
      ))}
      <div>
        <button type="button" className="btn small" disabled={doc.presenters.length >= 10} onClick={() => update((d) => d.presenters.push({ name: '', role: null }))}>
          Adicionar apresentador
        </button>
      </div>
    </fieldset>
  );
}

function SourcesPanel({ view }: { view: PresentationView }) {
  const [open, setOpen] = useState(false);
  const refs = [view.sources.primary, ...Object.values(view.sources.history)].sort((a, b) => b.competence.localeCompare(a.competence));
  return (
    <div className="panel">
      <div className="toolbar">
        <h3>Dados de origem</h3>
        <button type="button" className="btn small" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? 'Ocultar dados de origem' : 'Ver dados de origem'}
        </button>
      </div>
      {open && (
        <div data-testid="sources">
          <p className="muted">
            Política: {view.sources.policy} — somente revisões aprovadas fixadas; meses sem aprovação na janela {view.sources.history_window.start} a{' '}
            {view.sources.history_window.end} aparecem como lacuna.
          </p>
          <table aria-label="Indicadores da competência (revisão aprovada)">
            <thead>
              <tr>
                <th>Indicador</th>
                <th>Valor aprovado</th>
                <th>Estado</th>
                <th>Fonte técnica</th>
                <th>Homologação dashboard</th>
                <th>Manual</th>
              </tr>
            </thead>
            <tbody>
              {view.sources.metrics.map((m) => (
                <tr key={m.metric_id} data-testid={`source-${m.metric_id}`}>
                  <td>
                    <code>{m.metric_id}</code>
                    {m.contract_version ? ` · contrato v${m.contract_version}` : ''}
                  </td>
                  <td>{shortValue(m.value)}</td>
                  <td>{VALUE_STATE_LABEL[m.value_state as ValueState] ?? m.value_state}</td>
                  <td>
                    {m.source ? `${m.source.status ?? '—'} · ${m.source.name ?? '—'}${m.source.context ? ` · ${m.source.context}` : ''}` : '—'}
                    {m.source?.collected_at ? ` · ${fmtDate(m.source.collected_at)}` : ''}
                  </td>
                  <td>{m.dashboard_homologation ?? '—'}</td>
                  <td>{m.manual ? `${m.manual.justification} (${m.manual.operator}, declarado)` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h4>Revisões aprovadas fixadas</h4>
          <ul className="plain">
            {refs.map((r) => (
              <li key={r.approval_id}>
                {r.competence}: revisão {r.revision} · aprovação {r.approval_sequence} · <code>{r.content_hash.slice(0, 16)}…</code>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
