import React, { useEffect, useMemo, useState } from 'react';
import {
  ConnectionMode,
  Draft,
  FieldSpec,
  FieldsCatalog,
  OwnerKind,
  OwnerResolution,
  Resolution,
  RuleIssue,
  RuleLeaf,
  RuleNode,
  ScopeDomain,
  ScopeOptions,
  ScopeOverview,
  ScopeState,
  ValidationResult,
  VcApplication,
  VcBusinessUnit,
  VcMetadata,
  VcTeam,
  api,
  errorMessage,
  scopes,
  veracode,
} from '../api';
import { ErrorBox, Loading, fmtDate, useLoad } from '../ui';

// F03: construtor de escopos por domínio (cliente e subclientes). Regras guardam só IDs/valores de filtro;
// recursos Veracode vêm da descoberta somente leitura e nunca são gravados.

const DOMAINS: [ScopeDomain, string][] = [
  ['applications', 'Aplicações'],
  ['users', 'Usuários'],
  ['scans', 'Scans'],
  ['sca', 'SCA'],
];
const MODE_LABEL: Record<ConnectionMode, string> = {
  client: 'Conexão do cliente',
  shared: 'Mesma conexão do cliente',
  separate: 'Conexão própria (outro tenant)',
  none: 'Sem conexão',
};
const STATUS_LABEL: Record<string, string> = {
  active: 'Ativo',
  disabled: 'Desativado',
  not_defined: 'Não definido',
  shared: 'Avaliado (interseção com o universo)',
  separate_tenant: 'Avaliado no próprio tenant',
  coverage_unconfirmed: 'Abrangência não confirmada',
  connection_changed: 'Conexão mudou — salve nova versão',
  inactive: 'Subcliente inativo',
  no_connection: 'Sem conexão',
};
const CMP_LABEL: Record<string, string> = {
  eq: 'é igual a',
  neq: 'é diferente de',
  in: 'está em',
  not_in: 'não está em',
  contains: 'contém',
  not_contains: 'não contém',
  is_missing: 'está ausente',
  is_present: 'está presente',
  is_empty: 'está vazio',
};
const LIST_CMPS = ['in', 'not_in'];
const VALUE_CMPS = ['eq', 'neq', 'contains', 'not_contains'];
const NA = 'Indisponível';

// ---------------------------------------------------------------- modelo do modo simples

type Simple = {
  all: boolean;
  bus: string[];
  teams: string[];
  criticality: string[];
  tags: string[];
  apps: string[];
  contexts: string[];
  deps: string[];
  inScope: boolean;
};
const EMPTY_SIMPLE: Simple = { all: false, bus: [], teams: [], criticality: [], tags: [], apps: [], contexts: [], deps: [], inScope: false };

const inLeaf = (field: string, values: string[]): RuleLeaf => ({ field, cmp: 'in', values });
const and = (args: RuleNode[]): RuleNode | null => (args.length === 0 ? null : args.length === 1 ? args[0] : { op: 'and', args });

function simpleToRule(domain: ScopeDomain, s: Simple): RuleNode | null {
  if (s.all) return { op: 'all' };
  if (domain === 'users') return s.teams.length ? inLeaf('team.id', s.teams) : null;
  if (domain === 'scans' || domain === 'sca') {
    const conds: RuleNode[] = [];
    if (domain === 'scans' && s.contexts.length) conds.push(inLeaf('scan.context', s.contexts));
    if (domain === 'sca' && s.deps.length) conds.push(inLeaf('sca.dependency', s.deps));
    if (s.inScope) conds.push({ field: 'application.in_scope', cmp: 'eq', value: true });
    return and(conds);
  }
  const criteria = and(
    [
      s.bus.length ? inLeaf('business_unit.id', s.bus) : null,
      s.teams.length ? inLeaf('team.id', s.teams) : null,
      s.criticality.length ? inLeaf('business_criticality', s.criticality) : null,
      s.tags.length ? inLeaf('tag', s.tags) : null,
    ].filter(Boolean) as RuleNode[],
  );
  const apps = s.apps.length ? inLeaf('application.id', s.apps) : null;
  if (criteria && apps) return { op: 'or', args: [criteria, apps] };
  return criteria ?? apps;
}

const SIMPLE_KEYS: Record<string, keyof Simple> = {
  'business_unit.id': 'bus',
  'team.id': 'teams',
  business_criticality: 'criticality',
  tag: 'tags',
  'application.id': 'apps',
  'scan.context': 'contexts',
  'sca.dependency': 'deps',
};

// Converte a regra para o modo simples quando ela tem exatamente o formato que o modo simples gera.
function ruleToSimple(rule: RuleNode | null): Simple | null {
  const s: Simple = { ...EMPTY_SIMPLE };
  if (!rule) return s;
  if ('op' in rule && rule.op === 'all') return { ...s, all: true };
  const lists = s as unknown as Record<string, string[]>;
  const take = (n: RuleNode, allowApps: boolean): boolean => {
    if ('op' in n) return false;
    if (n.field === 'application.in_scope' && n.cmp === 'eq' && n.value === true) {
      if (s.inScope) return false;
      s.inScope = true;
      return true;
    }
    const key = SIMPLE_KEYS[n.field];
    if (!key || n.cmp !== 'in' || (key === 'apps' && !allowApps) || lists[key].length) return false;
    lists[key] = (n.values ?? []).map(String);
    return true;
  };
  const criteria = (n: RuleNode) =>
    'op' in n ? n.op === 'and' && n.args.every((a) => take(a, false)) : take(n, false);
  if ('op' in rule && rule.op === 'or') {
    const [c, a] = rule.args;
    return rule.args.length === 2 && !('op' in a) && a.field === 'application.id' && criteria(c) && take(a, true) ? s : null;
  }
  if (!('op' in rule) && rule.field === 'application.id') return take(rule, true) ? s : null;
  return criteria(rule) ? s : null;
}

// ---------------------------------------------------------------- modelo do modo avançado

type ENode =
  | { kind: 'all'; negate: boolean; uid: number }
  | { kind: 'group'; op: 'and' | 'or'; negate: boolean; children: ENode[]; uid: number }
  | { kind: 'leaf'; negate: boolean; field: string; cmp: string; key: string; value: string; values: string[]; uid: number };

let uidSeq = 0;
const nextUid = () => ++uidSeq;

function toEditor(rule: RuleNode | null, negate = false): ENode {
  if (!rule) return { kind: 'group', op: 'and', negate, children: [], uid: nextUid() };
  if ('op' in rule) {
    if (rule.op === 'not') {
      if (negate) return { kind: 'group', op: 'and', negate: true, children: [toEditor(rule.arg, true)], uid: nextUid() };
      return toEditor(rule.arg, true);
    }
    if (rule.op === 'all') return { kind: 'all', negate, uid: nextUid() };
    return { kind: 'group', op: rule.op, negate, children: rule.args.map((a) => toEditor(a)), uid: nextUid() };
  }
  return {
    kind: 'leaf',
    negate,
    field: rule.field,
    cmp: rule.cmp,
    key: rule.key ?? '',
    value: rule.value === undefined ? '' : String(rule.value),
    values: (rule.values ?? []).map(String),
    uid: nextUid(),
  };
}

function fromEditor(n: ENode, specs: Record<string, FieldSpec>): RuleNode {
  let out: RuleNode;
  if (n.kind === 'all') out = { op: 'all' };
  else if (n.kind === 'group') out = { op: n.op, args: n.children.map((c) => fromEditor(c, specs)) };
  else {
    const spec = specs[n.field];
    const leaf: RuleLeaf = { field: n.field, cmp: n.cmp };
    if (spec?.keyed) leaf.key = n.key;
    const conv = (v: string) => (spec?.type === 'bool' ? v === 'true' : v);
    if (VALUE_CMPS.includes(n.cmp)) leaf.value = conv(n.value);
    if (LIST_CMPS.includes(n.cmp)) leaf.values = n.values.map(conv);
    out = leaf;
  }
  return n.negate ? { op: 'not', arg: out } : out;
}

// ---------------------------------------------------------------- opções de descoberta (somente leitura)

type Options = {
  bus: { id: string; name: string }[];
  teams: { id: string; name: string }[];
  apps: { id: string; name: string }[];
  appsTotal: number;
  tags: string[];
  criticality: string[];
  complete: boolean;
};

async function loadOptions(kind: OwnerKind, id: string, domain: ScopeDomain): Promise<Options> {
  const path = kind === 'client' ? 'clients' : 'subclients';
  const page = { limit: 200, offset: 0 };
  const opts: Options = { bus: [], teams: [], apps: [], appsTotal: 0, tags: [], criticality: [], complete: true };
  const teams = await veracode.list<VcTeam>(path, id, 'teams', page);
  opts.teams = teams.items.map((t) => ({ id: t.team_id, name: t.name ?? t.team_id }));
  opts.complete &&= teams.complete;
  if (domain === 'applications') {
    const [bus, apps, meta] = await Promise.all([
      veracode.list<VcBusinessUnit>(path, id, 'business-units', page),
      veracode.list<VcApplication>(path, id, 'applications', page),
      veracode.metadata(path, id) as Promise<VcMetadata>,
    ]);
    opts.bus = bus.items.map((b) => ({ id: b.bu_id, name: b.name ?? b.bu_id }));
    opts.apps = apps.items.map((a) => ({ id: a.guid, name: a.name ?? a.guid }));
    opts.appsTotal = apps.total;
    opts.tags = meta.metadata.tags.map((t) => t.value);
    opts.criticality = meta.metadata.business_criticality.map((c) => c.value).filter((v) => v !== 'UNKNOWN');
    opts.complete &&= bus.complete && apps.complete && meta.complete;
  }
  return opts;
}

// ---------------------------------------------------------------- página

export function ScopesPage({ clientId }: { clientId: string }) {
  const client = useLoad(() => api.getClient(clientId), [clientId]);
  const catalog = useLoad(() => scopes.fields(), []);
  const [domain, setDomain] = useState<ScopeDomain>('applications');
  const [ownerKey, setOwnerKey] = useState(`client:${clientId}`);
  const [generation, setGeneration] = useState(0);
  const overview = useLoad(() => scopes.overview(clientId), [clientId, generation]);
  const [draft, setDraft] = useState<Draft | null>(null);

  if (client.error || overview.error || catalog.error)
    return (
      <section>
        <a href="#/clients">← Clientes</a>
        <ErrorBox message={`Falha ao carregar escopos: ${client.error || overview.error || catalog.error}`} onRetry={overview.reload} />
      </section>
    );
  if (!client.data || !overview.data || !catalog.data) return <Loading label="Carregando escopos…" />;
  const owners = overview.data.owners;
  const owner = owners.find((o) => `${o.kind}:${o.id}` === ownerKey) ?? owners[0];

  return (
    <section aria-labelledby="scopes-title">
      <a href={`#/clients/${clientId}`}>← Cliente</a>
      <div className="toolbar">
        <h2 id="scopes-title">Escopos — {client.data.name}</h2>
      </div>
      <p className="muted">
        O cliente principal define o universo; cada subcliente tem critérios próprios (interseção com o universo quando
        usa a mesma conexão). Domínios não compartilham filtros. Relacionamentos sempre por ID.
      </p>
      <div role="tablist" aria-label="Domínio" className="tabs">
        {DOMAINS.map(([d, label]) => (
          <button
            key={d}
            role="tab"
            type="button"
            aria-selected={domain === d}
            className={`tab ${domain === d ? 'active' : ''}`}
            onClick={() => {
              setDomain(d);
              setDraft(null);
            }}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="scopes-layout">
        <nav aria-label="Donos do escopo" className="owner-list">
          {owners.map((o) => {
            const st = o.scopes[domain];
            const key = `${o.kind}:${o.id}`;
            return (
              <button
                key={key}
                type="button"
                className={`owner ${key === `${owner.kind}:${owner.id}` ? 'active' : ''}`}
                aria-pressed={key === `${owner.kind}:${owner.id}`}
                onClick={() => {
                  setOwnerKey(key);
                  setDraft(null);
                }}
              >
                <strong>{o.kind === 'client' ? `${o.name} (cliente principal)` : o.name}</strong>
                <span className="muted">
                  {st.active_version ? `v${st.active_version.version} · ` : ''}
                  {STATUS_LABEL[st.status]}
                  {!o.effective_active && ' · inativo'}
                </span>
              </button>
            );
          })}
        </nav>
        <div>
          <ScopeEditor
            key={`${owner.kind}:${owner.id}:${domain}:${generation}`}
            clientId={clientId}
            kind={owner.kind}
            ownerId={owner.id}
            domain={domain}
            catalog={catalog.data}
            onSaved={() => setGeneration((g) => g + 1)}
            onDraft={setDraft}
          />
          <PreviewPanel clientId={clientId} domain={domain} draft={draft} generation={generation} overview={overview.data} />
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- editor

function ScopeEditor(props: {
  clientId: string;
  kind: OwnerKind;
  ownerId: string;
  domain: ScopeDomain;
  catalog: FieldsCatalog;
  onSaved: () => void;
  onDraft: (d: Draft | null) => void;
}) {
  const { kind, ownerId, domain, catalog, onSaved, onDraft } = props;
  const state = useLoad(() => scopes.get(kind, ownerId, domain), [kind, ownerId, domain]);
  const options = useLoad(() => loadOptions(kind, ownerId, domain), [kind, ownerId, domain]);
  const specs = useMemo(
    () => Object.fromEntries(catalog.domains[domain].fields.map((f) => [f.name, f])) as Record<string, FieldSpec>,
    [catalog, domain],
  );
  const [mode, setMode] = useState<'simple' | 'advanced'>('simple');
  const [simple, setSimple] = useState<Simple>(EMPTY_SIMPLE);
  const [tree, setTree] = useState<ENode>(() => toEditor(null));
  const [opts, setOpts] = useState<ScopeOptions>({});
  const [note, setNote] = useState('');
  const [ack, setAck] = useState(false);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    const st = state.data;
    if (!st) return;
    const rule = st.active_version?.rule ?? null;
    const s = ruleToSimple(rule);
    setSimple(s ?? EMPTY_SIMPLE);
    setTree(toEditor(rule));
    setMode(s ? 'simple' : 'advanced');
    setOpts(st.active_version?.options ?? (domain === 'users' ? { inactive_users: 'exclude' } : {}));
    setAck(st.active_version?.coverage_ack ?? false);
  }, [state.data, domain]);

  const rule: RuleNode | null = mode === 'simple' ? simpleToRule(domain, simple) : fromEditor(tree, specs);
  const ruleKey = JSON.stringify([rule, opts, ack]);
  useEffect(() => setValidation(null), [ruleKey]);

  if (state.error) return <ErrorBox message={`Falha ao carregar o escopo: ${state.error}`} onRetry={state.reload} />;
  if (!state.data) return <Loading label="Carregando escopo…" />;
  const st = state.data;
  const separate = st.connection_mode === 'separate';
  const simpleFromTree = mode === 'advanced' ? ruleToSimple(fromEditor(tree, specs)) : null;

  const validate = async (): Promise<ValidationResult | null> => {
    setError('');
    setMessage('');
    if (!rule) {
      setError('Selecione ao menos um critério (ou "todo o universo").');
      return null;
    }
    setBusy('validate');
    try {
      const v = await scopes.validate(domain, rule, opts);
      setValidation(v);
      return v;
    } catch (e) {
      setError(errorMessage(e));
      return null;
    } finally {
      setBusy('');
    }
  };
  const previewDraft = async () => {
    const v = await validate();
    if (v?.valid && v.rule) onDraft({ owner_kind: kind, owner_id: ownerId, rule: v.rule, options: opts, coverage_ack: ack });
  };
  const save = async () => {
    const v = await validate();
    if (!v?.valid || !v.rule) return;
    setBusy('save');
    try {
      const r = await scopes.save(kind, ownerId, domain, {
        rule: v.rule,
        options: opts,
        note: note.trim() || null,
        coverage_ack: ack,
        expected_version: st.active_version?.version ?? 0,
      });
      setMessage(r.created ? `Versão ${r.active_version?.version} salva.` : 'Nenhuma mudança: a versão ativa já tem esta regra.');
      onDraft(null);
      onSaved();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy('');
    }
  };
  const restore = async (version: number) => {
    setBusy('restore');
    setError('');
    try {
      await scopes.restore(kind, ownerId, domain, version, st.active_version?.version ?? 0, ack);
      onDraft(null);
      onSaved();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy('');
    }
  };
  const toggleStatus = async () => {
    setBusy('status');
    try {
      await scopes.setStatus(kind, ownerId, domain, st.status === 'active' ? 'disabled' : 'active');
      onSaved();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy('');
    }
  };

  return (
    <article className="panel" aria-label="Editor de escopo">
      <div className="toolbar">
        <h3>
          {st.owner.kind === 'client' ? 'Universo do cliente' : `Subcliente ${st.owner.name}`} —{' '}
          {DOMAINS.find(([d]) => d === domain)![1]}
        </h3>
        <span className={`badge ${separate ? 'source-subclient' : 'source-client'}`} data-testid="connection-mode">
          {MODE_LABEL[st.connection_mode]}
        </span>
        <span className="badge" data-testid="scope-status">
          {st.active_version ? `Versão ${st.active_version.version} · ` : ''}
          {STATUS_LABEL[st.status]}
        </span>
      </div>
      {!st.evaluable && (
        <p className="notice">Scans/SCA: regras são validadas e versionadas; a consulta real fica para a F04.</p>
      )}
      <div role="radiogroup" aria-label="Modo do construtor" className="mode-switch">
        <label className="inline">
          <input type="radio" name="mode" checked={mode === 'simple'} disabled={mode === 'advanced' && !simpleFromTree}
            onChange={() => {
              if (simpleFromTree) setSimple(simpleFromTree);
              setMode('simple');
            }}
          />
          Simples
        </label>
        <label className="inline">
          <input type="radio" name="mode" checked={mode === 'advanced'}
            onChange={() => {
              setTree(toEditor(simpleToRule(domain, simple)));
              setMode('advanced');
            }}
          />
          Avançado
        </label>
        {mode === 'advanced' && !simpleFromTree && <span className="muted">Regra avançada: não representável no modo simples.</span>}
      </div>

      {options.loading && <Loading label="Carregando BUs, Teams e aplicações (somente leitura)…" />}
      {options.error && <ErrorBox message={`Descoberta indisponível: ${options.error}`} onRetry={options.reload} />}
      {options.data && !options.data.complete && (
        <div role="alert" className="error-box" data-testid="options-incomplete">
          Coleta INCOMPLETA — listas de seleção parciais, não validadas.
        </div>
      )}

      {mode === 'simple' ? (
        <SimpleForm domain={domain} kind={kind} value={simple} onChange={setSimple} options={options.data} />
      ) : (
        <NodeEditor path="root" node={tree} onChange={setTree} specs={specs} options={options.data} onRemove={null} />
      )}

      {domain === 'users' && (
        <label className="field">
          Usuários inativos
          <select
            value={opts.inactive_users ?? 'exclude'}
            onChange={(e) => setOpts({ ...opts, inactive_users: e.target.value as 'exclude' | 'include' })}
          >
            <option value="exclude">Excluir da contagem e reportar à parte (padrão)</option>
            <option value="include">Incluir na contagem</option>
          </select>
        </label>
      )}
      {separate && (
        <label className="inline notice">
          <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
          Confirmo a abrangência: este subcliente usa outra conexão e será avaliado só no próprio tenant, sem interseção com o
          universo do cliente.
        </label>
      )}
      <label className="field">
        Nota da versão (opcional)
        <input value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
      </label>

      <details className="rule-json">
        <summary>Regra (JSON)</summary>
        <pre data-testid="rule-json">{rule ? JSON.stringify(rule, null, 2) : '—'}</pre>
      </details>
      <ValidationBox validation={validation} />
      {error && <ErrorBox message={error} />}
      {message && (
        <p role="status" className="notice">
          {message}
        </p>
      )}
      <div className="actions">
        <button type="button" className="btn" disabled={!!busy} onClick={validate}>
          {busy === 'validate' ? 'Validando…' : 'Validar regra'}
        </button>
        <button type="button" className="btn" disabled={!!busy || !rule} onClick={previewDraft}>
          Pré-visualizar rascunho
        </button>
        <button
          type="button"
          className="btn primary"
          disabled={!!busy || !rule || validation?.valid === false || (separate && !ack)}
          onClick={save}
        >
          {busy === 'save' ? 'Salvando…' : 'Salvar nova versão'}
        </button>
        {st.defined && (
          <button type="button" className="btn" disabled={!!busy} onClick={toggleStatus}>
            {st.status === 'active' ? 'Desativar escopo' : 'Reativar escopo'}
          </button>
        )}
      </div>

      {(st.versions?.length ?? 0) > 0 && (
        <table aria-label="Histórico de versões" className="versions">
          <thead>
            <tr>
              <th>Versão</th>
              <th>Status</th>
              <th>Criada em</th>
              <th>Nota</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {st.versions!.map((v) => (
              <tr key={v.version}>
                <td>v{v.version}</td>
                <td>{v.status === 'active' ? 'Ativa' : 'Substituída (preservada)'}</td>
                <td>{fmtDate(v.created_at)}</td>
                <td>{v.note ?? '—'}</td>
                <td>
                  {v.status !== 'active' && (
                    <button type="button" className="btn small" disabled={!!busy} onClick={() => restore(v.version)}>
                      Restaurar como nova versão
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </article>
  );
}

function ValidationBox({ validation }: { validation: ValidationResult | null }) {
  if (!validation) return null;
  if (validation.valid)
    return (
      <p className="notice valid" data-testid="validation-ok">
        Regra válida · {validation.complexity.nodes} nó(s), profundidade {validation.complexity.depth} (limites:{' '}
        {validation.complexity.limits.max_nodes} nós, profundidade {validation.complexity.limits.max_depth})
      </p>
    );
  return (
    <div role="alert" className="error-box" data-testid="validation-errors">
      <ul>
        {validation.issues.map((i: RuleIssue, n) => (
          <li key={n}>
            <code>{i.field}</code>: {i.message}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------- modo simples

function CheckList({
  label,
  items,
  selected,
  onChange,
  searchable,
}: {
  label: string;
  items: { id: string; name: string }[];
  selected: string[];
  onChange: (v: string[]) => void;
  searchable?: boolean;
}) {
  const [q, setQ] = useState('');
  const visible = items.filter((i) => !q || i.name.toLowerCase().includes(q.toLowerCase()));
  const toggle = (id: string) => onChange(selected.includes(id) ? selected.filter((s) => s !== id) : [...selected, id]);
  const unknown = selected.filter((s) => !items.some((i) => i.id === s));
  return (
    <fieldset className="field checklist" aria-label={label}>
      <legend>
        {label} {selected.length > 0 && <span className="badge">{selected.length} selecionado(s)</span>}
      </legend>
      {searchable && <input type="search" placeholder={`Buscar ${label.toLowerCase()}`} value={q} onChange={(e) => setQ(e.target.value)} />}
      <div className="checklist-items">
        {visible.slice(0, 60).map((i) => (
          <label key={i.id} className="inline">
            <input type="checkbox" checked={selected.includes(i.id)} onChange={() => toggle(i.id)} />
            {i.name}
          </label>
        ))}
        {unknown.map((id) => (
          <label key={id} className="inline" title="ID não encontrado na descoberta atual">
            <input type="checkbox" checked onChange={() => toggle(id)} />
            <code>{id}</code> (não encontrado)
          </label>
        ))}
        {visible.length > 60 && <span className="muted">Refine a busca ({visible.length} itens).</span>}
      </div>
    </fieldset>
  );
}

const plain = (values: string[]) => values.map((v) => ({ id: v, name: v }));

function SimpleForm(props: {
  domain: ScopeDomain;
  kind: OwnerKind;
  value: Simple;
  onChange: (s: Simple) => void;
  options: Options | null;
}) {
  const { domain, kind, value: s, onChange, options: o } = props;
  const set = (patch: Partial<Simple>) => onChange({ ...s, ...patch });
  const allLabel =
    kind === 'client'
      ? domain === 'users'
        ? 'Todos os usuários da conexão'
        : 'Todo o tenant da conexão'
      : 'Todo o universo do cliente principal';
  return (
    <div className="simple-form">
      <label className="inline">
        <input type="checkbox" checked={s.all} onChange={(e) => set({ all: e.target.checked })} />
        {allLabel}
      </label>
      {!s.all && domain === 'applications' && o && (
        <>
          <p className="muted">Inclui: (BU E Teams E criticidade E tags) OU aplicações selecionadas.</p>
          <CheckList label="Business Units" items={o.bus} selected={s.bus} onChange={(bus) => set({ bus })} />
          <CheckList label="Teams" items={o.teams} selected={s.teams} onChange={(teams) => set({ teams })} searchable />
          <CheckList label="Criticidade" items={plain(o.criticality)} selected={s.criticality} onChange={(criticality) => set({ criticality })} />
          <CheckList label="Tags" items={plain(o.tags)} selected={s.tags} onChange={(tags) => set({ tags })} searchable />
          <CheckList label="Aplicações" items={o.apps} selected={s.apps} onChange={(apps) => set({ apps })} searchable />
          {o.appsTotal > o.apps.length && (
            <p className="muted">Lista de aplicações limitada a {o.apps.length} de {o.appsTotal}; use o modo avançado para GUIDs.</p>
          )}
        </>
      )}
      {!s.all && domain === 'users' && o && (
        <>
          <p className="muted">Teams de usuários não selecionam aplicações (domínios independentes).</p>
          <CheckList label="Teams" items={o.teams} selected={s.teams} onChange={(teams) => set({ teams })} searchable />
        </>
      )}
      {!s.all && (domain === 'scans' || domain === 'sca') && (
        <>
          {domain === 'scans' ? (
            <CheckList label="Contexto do scan" items={[{ id: 'policy', name: 'Policy (produção)' }, { id: 'sandbox', name: 'Sandbox (desenvolvimento)' }]}
              selected={s.contexts} onChange={(contexts) => set({ contexts })} />
          ) : (
            <CheckList label="Dependência" items={[{ id: 'direct', name: 'Direta' }, { id: 'transitive', name: 'Transitiva' }]}
              selected={s.deps} onChange={(deps) => set({ deps })} />
          )}
          <label className="inline">
            <input type="checkbox" checked={s.inScope} onChange={(e) => set({ inScope: e.target.checked })} />
            Somente aplicações do escopo de aplicações deste dono (vínculo explícito)
          </label>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- modo avançado

function idChoices(field: string, o: Options | null) {
  if (!o) return null;
  if (field === 'business_unit.id') return o.bus;
  if (field === 'team.id') return o.teams;
  if (field === 'application.id') return o.apps;
  return null;
}

function NodeEditor(props: {
  path: string;
  node: ENode;
  onChange: (n: ENode) => void;
  onRemove: (() => void) | null;
  specs: Record<string, FieldSpec>;
  options: Options | null;
}) {
  const { path, node, onChange, onRemove, specs, options } = props;
  const fields = Object.values(specs);
  const negate = (
    <label className="inline">
      <input type="checkbox" checked={node.negate} onChange={(e) => onChange({ ...node, negate: e.target.checked })} />
      NÃO
    </label>
  );
  const remove = onRemove && (
    <button type="button" className="btn small danger" onClick={onRemove}>
      Remover
    </button>
  );
  if (node.kind === 'all')
    return (
      <div className="rule-leaf" data-testid={`node-${path}`}>
        {negate} <strong>Todo o universo</strong> {remove}
      </div>
    );
  if (node.kind === 'group') {
    const newLeaf = (): ENode => {
      const f = fields[0];
      return { kind: 'leaf', negate: false, field: f.name, cmp: f.cmps[0], key: '', value: '', values: [], uid: nextUid() };
    };
    return (
      <fieldset className="rule-group" aria-label={`Grupo ${node.op === 'and' ? 'E' : 'OU'}`} data-testid={`node-${path}`}>
        <legend>
          {negate}
          <select aria-label="Operador do grupo" value={node.op} onChange={(e) => onChange({ ...node, op: e.target.value as 'and' | 'or' })}>
            <option value="and">E (todas)</option>
            <option value="or">OU (qualquer)</option>
          </select>
          {remove}
        </legend>
        {node.children.length === 0 && <p className="muted">Grupo vazio: adicione condições.</p>}
        {node.children.map((c, i) => (
          <NodeEditor
            key={c.uid}
            path={`${path}-${i}`}
            node={c}
            specs={specs}
            options={options}
            onChange={(n) => onChange({ ...node, children: node.children.map((x, j) => (j === i ? n : x)) })}
            onRemove={() => onChange({ ...node, children: node.children.filter((_, j) => j !== i) })}
          />
        ))}
        <div className="actions">
          <button type="button" className="btn small" onClick={() => onChange({ ...node, children: [...node.children, newLeaf()] })}>
            + Condição
          </button>
          <button
            type="button"
            className="btn small"
            onClick={() =>
              onChange({ ...node, children: [...node.children, { kind: 'group', op: 'or', negate: false, children: [], uid: nextUid() }] })
            }
          >
            + Grupo
          </button>
          <button
            type="button"
            className="btn small"
            onClick={() => onChange({ ...node, children: [...node.children, { kind: 'all', negate: false, uid: nextUid() }] })}
          >
            + Todo o universo
          </button>
        </div>
      </fieldset>
    );
  }
  const spec = specs[node.field];
  const choices = spec?.type === 'id' ? idChoices(node.field, options) : spec?.enum ? plain(spec.enum) : null;
  const setField = (name: string) => {
    const f = specs[name];
    onChange({ ...node, field: name, cmp: f.cmps.includes(node.cmp) ? node.cmp : f.cmps[0], value: '', values: [] });
  };
  return (
    <div className="rule-leaf" role="group" aria-label="Condição" data-testid={`node-${path}`}>
      {negate}
      <select aria-label="Campo" value={node.field} onChange={(e) => setField(e.target.value)}>
        {fields.map((f) => (
          <option key={f.name} value={f.name}>
            {f.label}
          </option>
        ))}
      </select>
      {spec?.keyed && <input aria-label="Nome do campo personalizado" placeholder="Nome do campo" value={node.key} onChange={(e) => onChange({ ...node, key: e.target.value })} />}
      <select aria-label="Comparação" value={node.cmp} onChange={(e) => onChange({ ...node, cmp: e.target.value })}>
        {(spec?.cmps ?? []).map((c) => (
          <option key={c} value={c}>
            {CMP_LABEL[c] ?? c}
          </option>
        ))}
      </select>
      {VALUE_CMPS.includes(node.cmp) &&
        (spec?.type === 'bool' ? (
          <select aria-label="Valor" value={node.value} onChange={(e) => onChange({ ...node, value: e.target.value })}>
            <option value="">—</option>
            <option value="true">Sim</option>
            <option value="false">Não</option>
          </select>
        ) : choices ? (
          <select aria-label="Valor" value={node.value} onChange={(e) => onChange({ ...node, value: e.target.value })}>
            <option value="">—</option>
            {choices.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        ) : (
          <input aria-label="Valor" value={node.value} onChange={(e) => onChange({ ...node, value: e.target.value })} />
        ))}
      {LIST_CMPS.includes(node.cmp) &&
        (choices ? (
          <select
            aria-label="Valores"
            multiple
            value={node.values}
            onChange={(e) => onChange({ ...node, values: Array.from(e.target.selectedOptions).map((o) => o.value) })}
          >
            {choices.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        ) : (
          <input
            aria-label="Valores"
            placeholder="valores separados por vírgula"
            value={node.values.join(', ')}
            onChange={(e) => onChange({ ...node, values: e.target.value.split(',').map((v) => v.trim()).filter(Boolean) })}
          />
        ))}
      {spec?.note && <span className="muted">{spec.note}</span>}
      {remove}
    </div>
  );
}

// ---------------------------------------------------------------- pré-visualização

const num = (v: number | null | undefined) => (v === null || v === undefined ? NA : String(v));

function PreviewPanel(props: {
  clientId: string;
  domain: ScopeDomain;
  draft: Draft | null;
  generation: number;
  overview: ScopeOverview;
}) {
  const { clientId, domain, draft, generation, overview } = props;
  const res = useLoad(() => scopes.preview(clientId, domain, draft), [clientId, domain, JSON.stringify(draft), generation]);
  const names = Object.fromEntries(overview.owners.map((o) => [o.id, o.name]));
  return (
    <article className="panel" aria-label="Pré-visualização" aria-busy={res.loading}>
      <div className="toolbar">
        <h3>Pré-visualização {draft && <span className="badge source-subclient">com rascunho não salvo</span>}</h3>
        <button type="button" className="btn small" onClick={res.reload} disabled={res.loading}>
          Recalcular
        </button>
      </div>
      {res.loading && <Loading label="Calculando pré-visualização (descoberta somente leitura)…" />}
      {res.error && <ErrorBox message={`Pré-visualização indisponível: ${res.error}`} onRetry={res.reload} />}
      {!res.loading && res.data && <PreviewBody r={res.data} names={names} />}
    </article>
  );
}

function PreviewBody({ r, names }: { r: Resolution; names: Record<string, string> }) {
  if (r.status === 'deferred_f04') return <p className="notice">{r.message}</p>;
  const u = r.universe;
  return (
    <div data-testid="preview">
      {r.complete ? (
        <p className="muted" data-testid="preview-complete">
          Coleta completa · resultado baseado em dados completos da descoberta
        </p>
      ) : (
        <div role="alert" className="error-box" data-testid="preview-incomplete">
          Coleta INCOMPLETA — contagens parciais, NÃO validadas.
        </div>
      )}
      {r.warnings.length > 0 && (
        <ul className="warnings" aria-label="Avisos">
          {r.warnings.map((w) => (
            <li key={w.code} className={w.blocking ? 'blocking' : ''}>
              {w.message}
            </li>
          ))}
        </ul>
      )}
      <h4>Universo do cliente principal</h4>
      {u.defined ? (
        <OwnerCounts o={u} testId="universe" />
      ) : (
        <p className="notice">Universo não definido: salve o escopo do cliente principal neste domínio.</p>
      )}
      {r.subclients.length > 0 && (
        <table aria-label="Subclientes" className="preview-table">
          <thead>
            <tr>
              <th>Subcliente</th>
              <th>Situação</th>
              <th>Incluídos</th>
              <th>Excluídos</th>
              <th>Indeterminados</th>
              {r.domain === 'users' && <th>Inativos (fora)</th>}
            </tr>
          </thead>
          <tbody>
            {r.subclients.map((s) => (
              <tr key={s.id}>
                <td>
                  {s.name}
                  {s.draft && <span className="badge source-subclient">rascunho</span>}
                </td>
                <td>
                  {STATUS_LABEL[s.status ?? ''] ?? s.status}
                  {s.error && <span className="field-error"> · {s.error.message}</span>}
                  {s.outside_universe ? <span className="muted"> · {s.outside_universe} fora do universo</span> : null}
                </td>
                <td>{num(s.included)}</td>
                <td>{num(s.excluded)}</td>
                <td>{num(s.undetermined)}</td>
                {r.domain === 'users' && <td>{num(s.inactive_excluded)}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {r.unclassified && (
        <section aria-label="Não classificados" className="subsection">
          <h4>Não classificados (universo − subclientes)</h4>
          {r.unclassified.available ? (
            <>
              <p>
                <strong data-testid="unclassified-count">{r.unclassified.count}</strong>{' '}
                {r.unclassified.complete ? '' : <span className="badge off">não validado</span>}
                {r.unclassified.no_subclients && <span className="muted"> · cliente sem subclientes ativos</span>}
              </p>
              <SampleList items={r.unclassified.sample} total={r.unclassified.count ?? 0} />
            </>
          ) : (
            <p className="muted">{NA}: universo não definido.</p>
          )}
        </section>
      )}
      {r.overlap && (
        <section aria-label="Sobreposição" className="subsection">
          <h4>Sobreposição entre subclientes</h4>
          <p>
            <strong data-testid="overlap-count">{r.overlap.resources_in_multiple}</strong> recurso(s) em 2+ subclientes
          </p>
          {r.overlap.pairs.length > 0 && (
            <ul>
              {r.overlap.pairs.map((p) => (
                <li key={`${p.a}-${p.b}`}>
                  {names[p.a] ?? p.a} ∩ {names[p.b] ?? p.b}: {p.count}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
      {r.domain === 'users' && r.reconciliation && (
        <p className="muted" data-testid="reconciliation">
          Reconciliação usuário–Team: {r.reconciliation.status}
          {r.reconciliation.reason ? ` — ${r.reconciliation.reason}` : ''}
        </p>
      )}
    </div>
  );
}

function OwnerCounts({ o, testId }: { o: OwnerResolution; testId: string }) {
  const missing = Object.entries(o.missing_fields ?? {});
  return (
    <>
      <dl className="summary" data-testid={testId}>
        <div>
          <dt>Disponíveis</dt>
          <dd>{num(o.total_available)}</dd>
        </div>
        <div>
          <dt>Incluídos</dt>
          <dd data-testid={`${testId}-included`}>{num(o.included)}</dd>
        </div>
        <div>
          <dt>Excluídos</dt>
          <dd data-testid={`${testId}-excluded`}>{num(o.excluded)}</dd>
        </div>
        <div>
          <dt>Indeterminados</dt>
          <dd>{num(o.undetermined)}</dd>
        </div>
        {o.inactive_excluded !== undefined && (
          <div>
            <dt>Inativos (fora da contagem)</dt>
            <dd data-testid={`${testId}-inactive`}>{num(o.inactive_excluded)}</dd>
          </div>
        )}
      </dl>
      {missing.length > 0 && (
        <p className="muted">Campos ausentes: {missing.map(([f, c]) => `${f} (${c})`).join(', ')}</p>
      )}
      {o.users_per_team && (
        <table aria-label="Usuários únicos por Team" className="preview-table">
          <thead>
            <tr>
              <th>Team</th>
              <th>Usuários únicos</th>
            </tr>
          </thead>
          <tbody>
            {o.users_per_team.teams.map((t) => (
              <tr key={t.team_id}>
                <td>{t.name ?? t.team_id}</td>
                <td>{num(t.unique_users)}</td>
              </tr>
            ))}
            <tr>
              <td>
                <strong>Total de usuários únicos</strong>
              </td>
              <td data-testid="unique-users-total">{num(o.users_per_team.unique_users_total)}</td>
            </tr>
          </tbody>
        </table>
      )}
    </>
  );
}

function SampleList({ items, total }: { items: { id: string; name: string | null }[]; total: number }) {
  if (!items.length) return null;
  return (
    <details>
      <summary>
        Ver {items.length}
        {total > items.length ? ` de ${total}` : ''}
      </summary>
      <ul className="sample">
        {items.map((i) => (
          <li key={i.id}>{i.name ?? i.id}</li>
        ))}
      </ul>
    </details>
  );
}
