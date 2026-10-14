import React, { useEffect, useState } from 'react';
import {
  CollectionStatus,
  ConnectionTest,
  CredentialStatus,
  DiscoveryPage,
  REGION_LABEL,
  ScopeKind,
  VcAppRelationship,
  VcApplication,
  VcBusinessUnit,
  VcTeam,
  VcUser,
  VcUserRelationship,
  errorMessage,
  veracode,
} from '../api';
import { Empty, ErrorBox, Loading, fmtDate, useLoad } from '../ui';

// F02: descoberta Veracode SOMENTE LEITURA por cliente/subcliente. Segredos nunca chegam ao navegador:
// a página só conhece a referência (env:NOME) e o estado da credencial no backend.
const PAGE_SIZE = 25;

const CREDENTIAL_LABEL: Record<CredentialStatus, string> = {
  configured: 'Configurada no backend',
  missing: 'Ausente no ambiente do backend',
  invalid_format: 'Formato inválido no ambiente do backend',
  unsupported_ref: 'Referência não suportada',
  not_configured: 'Sem conexão',
};
const SOURCE_LABEL = { subclient: 'Sobrescrita no subcliente', client: 'Herdada do cliente', none: 'Sem conexão' };
const CHECK_LABEL: Record<string, string> = {
  credentials: 'Credencial',
  applications: 'Aplicações',
  users: 'Usuários',
  teams: 'Teams',
  business_units: 'Business Units',
};
const TABS = [
  ['applications', 'Aplicações'],
  ['business-units', 'Business Units'],
  ['teams', 'Teams'],
  ['users', 'Usuários'],
  ['rel-apps', 'Aplicação ↔ BU/Teams'],
  ['rel-users', 'Usuário ↔ Teams'],
  ['metadata', 'Metadados'],
] as const;
type Tab = (typeof TABS)[number][0];

export function VeracodePage({ kind, id }: { kind: ScopeKind; id: string }) {
  const scope = useLoad(() => veracode.scope(kind, id), [kind, id]);
  const [tab, setTab] = useState<Tab>('applications');
  const [test, setTest] = useState<ConnectionTest | null>(null);
  const [busy, setBusy] = useState('');
  const [actionError, setActionError] = useState('');
  const [notice, setNotice] = useState('');
  const [generation, setGeneration] = useState(0); // força recarga das abas após invalidar o cache

  if (scope.error)
    return (
      <section>
        <a href="#/clients">← Clientes</a>
        <ErrorBox message={`Falha ao carregar escopo: ${scope.error}`} onRetry={scope.reload} />
      </section>
    );
  if (scope.loading && !scope.data) return <Loading label="Carregando escopo…" />;
  const s = scope.data!;
  const conn = s.scope.connection;

  const runTest = async () => {
    setBusy('test');
    setActionError('');
    setTest(null);
    try {
      setTest(await veracode.test(kind, id));
    } catch (e) {
      setActionError(errorMessage(e));
    } finally {
      setBusy('');
    }
  };
  const invalidate = async () => {
    setBusy('cache');
    setActionError('');
    try {
      const r = await veracode.invalidate(kind, id);
      setNotice(`Cache invalidado (${r.removed_entries} entrada(s)). Os dados serão coletados novamente.`);
      setGeneration((g) => g + 1);
    } catch (e) {
      setActionError(errorMessage(e));
    } finally {
      setBusy('');
    }
  };

  return (
    <section aria-labelledby="vc-title">
      <a href={`#/clients/${s.scope.client_id}`}>← Cliente</a>
      <div className="toolbar">
        <h2 id="vc-title">Veracode — {s.scope.name}</h2>
        <span className="badge">{s.scope.kind === 'client' ? 'Cliente' : 'Subcliente'}</span>
        {s.mode === 'fixture' && (
          <span className="badge source-subclient" data-testid="fixture-mode">
            Modo fixture: tenant sintético
          </span>
        )}
      </div>
      <p className="muted">
        Consulta somente leitura. Segredos ficam no backend; esta tela nunca recebe API ID/Key.
      </p>

      <article className="panel" aria-label="Conexão Veracode">
        <dl className="details">
          <dt>Conexão</dt>
          <dd data-testid="vc-connection">{conn ? conn.name : 'Nenhuma'}</dd>
          <dt>Origem</dt>
          <dd data-testid="vc-source">{SOURCE_LABEL[s.scope.connection_source]}</dd>
          {conn && (
            <>
              <dt>Região</dt>
              <dd>{REGION_LABEL[conn.region]}</dd>
              <dt>Referência da credencial</dt>
              <dd>
                <code>{conn.credential_ref}</code>
              </dd>
            </>
          )}
          <dt>Credencial</dt>
          <dd data-testid="vc-credential">
            <span className={`badge ${s.credential_status === 'configured' ? 'ok' : 'off'}`}>
              {CREDENTIAL_LABEL[s.credential_status]}
            </span>
          </dd>
          <dt>Cache de descoberta</dt>
          <dd>{s.cache_ttl_seconds > 0 ? `${s.cache_ttl_seconds}s por escopo` : 'Desativado'}</dd>
        </dl>
        <div className="actions">
          <button type="button" className="btn primary" onClick={runTest} disabled={!conn || busy !== ''}>
            {busy === 'test' ? 'Testando…' : 'Testar conexão'}
          </button>
          <button type="button" className="btn" onClick={invalidate} disabled={!conn || busy !== ''}>
            Invalidar cache
          </button>
        </div>
        {actionError && <ErrorBox message={actionError} />}
        {notice && (
          <p role="status" className="notice">
            {notice}
          </p>
        )}
        {busy === 'test' && <Loading label="Testando conexão…" />}
        {test && <TestResult test={test} />}
      </article>

      {!conn ? (
        <Empty>
          Escopo sem conexão Veracode. Configure uma conexão no cliente
          {s.scope.kind === 'subclient' ? ' ou uma sobrescrita no subcliente' : ''}.
        </Empty>
      ) : (
        <>
          <div role="tablist" aria-label="Recursos Veracode" className="tabs">
            {TABS.map(([key, label]) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={tab === key}
                className={`tab ${tab === key ? 'active' : ''}`}
                onClick={() => setTab(key)}
              >
                {label}
              </button>
            ))}
          </div>
          <div role="tabpanel" aria-label={TABS.find(([k]) => k === tab)![1]} key={`${tab}-${generation}`}>
            <TabContent tab={tab} kind={kind} id={id} />
          </div>
        </>
      )}
    </section>
  );
}

function TestResult({ test }: { test: ConnectionTest }) {
  const label = { ok: 'Conexão OK', partial: 'Conexão parcial: permissões ausentes', error: 'Falha na conexão' };
  return (
    <div className="subsection" data-testid="vc-test-result">
      <p className={`badge ${test.status === 'ok' ? 'ok' : 'off'}`}>{label[test.status]}</p>
      <table aria-label="Resultado do teste de conexão">
        <thead>
          <tr>
            <th>Verificação</th>
            <th>Resultado</th>
            <th>Detalhe</th>
          </tr>
        </thead>
        <tbody>
          {test.checks.map((c) => (
            <tr key={c.check}>
              <td>{CHECK_LABEL[c.check] ?? c.check}</td>
              <td>
                <span className={`badge ${c.status === 'ok' ? 'ok' : 'off'}`}>{c.status === 'ok' ? 'OK' : 'Erro'}</span>
              </td>
              <td>{c.error ? c.error.message : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TabContent({ tab, kind, id }: { tab: Tab; kind: ScopeKind; id: string }) {
  switch (tab) {
    case 'applications':
      return <ApplicationsTab kind={kind} id={id} />;
    case 'business-units':
      return (
        <ResourceTable<VcBusinessUnit>
          kind={kind}
          id={id}
          resource="business-units"
          label="Business Units"
          placeholder="Nome da BU"
          columns={[
            ['Nome', (b) => b.name ?? '—'],
            ['Padrão', (b) => (b.is_default === null ? '?' : b.is_default ? 'Sim' : 'Não')],
            ['Teams', (b) => (b.team_ids === null ? 'não informado' : String(b.team_ids.length))],
          ]}
          rowKey={(b) => b.bu_id}
        />
      );
    case 'teams':
      return (
        <ResourceTable<VcTeam>
          kind={kind}
          id={id}
          resource="teams"
          label="Teams"
          placeholder="Nome do Team ou da BU"
          columns={[
            ['Nome', (t) => t.name ?? '—'],
            ['Business Unit', (t) => t.business_unit?.name ?? 'não informada'],
            ['Usuários', (t) => (t.user_count === null ? '?' : String(t.user_count))],
          ]}
          rowKey={(t) => t.team_id}
        />
      );
    case 'users':
      return (
        <ResourceTable<VcUser>
          kind={kind}
          id={id}
          resource="users"
          label="Usuários"
          placeholder="Usuário ou nome"
          columns={[
            ['Usuário', (u) => u.user_name ?? '—'],
            ['Nome', (u) => [u.first_name, u.last_name].filter(Boolean).join(' ') || '—'],
            ['Tipo', (u) => u.account_type ?? '?'],
            ['Ativo', (u) => (u.active === null ? '?' : u.active ? 'Sim' : 'Não')],
          ]}
          rowKey={(u) => u.user_id}
        />
      );
    case 'rel-apps':
      return (
        <ResourceTable<VcAppRelationship>
          kind={kind}
          id={id}
          resource="relationships/applications"
          label="Relação aplicação ↔ BU/Teams"
          placeholder="Aplicação, BU ou Team"
          columns={[
            ['Aplicação', (r) => r.application.name ?? '—'],
            ['Business Unit', (r) => (r.business_unit ? <RefName r={r.business_unit} /> : 'não informada')],
            [
              'Teams',
              (r) =>
                r.teams === null ? 'não informado' : r.teams.length === 0 ? 'Nenhum' : (
                  r.teams.map((t, i) => (
                    <div key={i}>
                      <RefName r={t} />
                    </div>
                  ))
                ),
            ],
          ]}
          rowKey={(r) => r.application.guid}
          summaryLabels={{
            applications: 'Aplicações',
            multiple_teams: 'Com 2+ Teams',
            without_teams: 'Sem Team',
            unmatched_team_refs: 'Refs. de Team sem correspondência por ID',
          }}
        />
      );
    case 'rel-users':
      return (
        <ResourceTable<VcUserRelationship>
          kind={kind}
          id={id}
          resource="relationships/users"
          label="Relação usuário ↔ Teams"
          placeholder="Usuário ou Team"
          columns={[
            ['Usuário', (r) => r.user.user_name ?? '—'],
            [
              'Teams',
              (r) =>
                r.teams === null
                  ? 'desconhecido (coleta incompleta)'
                  : r.teams.length === 0
                    ? 'Nenhum'
                    : r.teams.map((t) => (
                        <div key={t.team_id}>
                          {t.team_name ?? t.team_id}
                          {t.relationship === 'ADMIN' && <span className="muted"> (admin)</span>}
                        </div>
                      )),
            ],
          ]}
          rowKey={(r) => r.user.user_id}
          summaryLabels={{
            users: 'Usuários',
            memberships: 'Vínculos',
            multiple_teams: 'Em 2+ Teams',
            without_team: 'Sem Team',
            members_not_in_user_list: 'Membros fora da lista de usuários',
          }}
        />
      );
    case 'metadata':
      return <MetadataTab kind={kind} id={id} />;
  }
}

const RefName = ({ r }: { r: { name: string | null; guid: string | null; identity_match: boolean | null } }) => (
  <>
    {r.name ?? r.guid ?? '—'}
    {r.identity_match === false && (
      <span className="badge off" title="ID não encontrado na Identity API (correspondência nunca é feita por nome)">
        sem correspondência
      </span>
    )}
  </>
);

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

type Column<T> = [string, (row: T) => React.ReactNode];

function ResourceTable<T>(props: {
  kind: ScopeKind;
  id: string;
  resource: string;
  label: string;
  placeholder: string;
  columns: Column<T>[];
  rowKey: (row: T) => string;
  summaryLabels?: Record<string, string>;
  expand?: (row: T) => React.ReactNode;
}) {
  const { kind, id, resource, label, placeholder, columns, rowKey, summaryLabels, expand } = props;
  const [query, setQuery] = useState('');
  const [offset, setOffset] = useState(0);
  const q = useDebounced(query.trim());
  const data = useLoad(
    () => veracode.list<T>(kind, id, resource, { q: q || undefined, limit: PAGE_SIZE, offset }),
    [kind, id, resource, q, offset],
  );
  const page = data.data;

  return (
    <section aria-label={label}>
      <div className="filters">
        <label>
          Buscar
          <input
            type="search"
            value={query}
            placeholder={placeholder}
            onChange={(e) => {
              setQuery(e.target.value);
              setOffset(0);
            }}
          />
        </label>
      </div>
      {data.error ? (
        <ErrorBox message={`Falha ao consultar a Veracode: ${data.error}`} onRetry={data.reload} />
      ) : data.loading && !page ? (
        <Loading label={`Consultando ${label.toLowerCase()} na Veracode…`} />
      ) : !page ? null : (
        <>
          <CollectionBanner page={page} />
          {page.summary && summaryLabels && <Summary summary={page.summary} labels={summaryLabels} />}
          {!page.items.length ? (
            <Empty>{q ? 'Nenhum resultado para a busca.' : 'Nenhum registro retornado pela Veracode.'}</Empty>
          ) : (
            <table aria-label={label}>
              <thead>
                <tr>
                  {columns.map(([h]) => (
                    <th key={h}>{h}</th>
                  ))}
                  {expand && <th>Ações</th>}
                </tr>
              </thead>
              <tbody>
                {page.items.map((row) => (
                  <ExpandableRow key={rowKey(row)} row={row} columns={columns} expand={expand} />
                ))}
              </tbody>
            </table>
          )}
          <Pager total={page.total} offset={offset} onChange={setOffset} loading={data.loading} />
        </>
      )}
    </section>
  );
}

function ExpandableRow<T>({ row, columns, expand }: { row: T; columns: Column<T>[]; expand?: (r: T) => React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr>
        {columns.map(([h, render]) => (
          <td key={h}>{render(row)}</td>
        ))}
        {expand && (
          <td>
            <button type="button" className="btn small" aria-expanded={open} onClick={() => setOpen(!open)}>
              {open ? 'Ocultar sandboxes' : 'Sandboxes'}
            </button>
          </td>
        )}
      </tr>
      {open && expand && (
        <tr>
          <td colSpan={columns.length + 1}>{expand(row)}</td>
        </tr>
      )}
    </>
  );
}

function ApplicationsTab({ kind, id }: { kind: ScopeKind; id: string }) {
  return (
    <ResourceTable<VcApplication>
      kind={kind}
      id={id}
      resource="applications"
      label="Aplicações"
      placeholder="Nome da aplicação"
      columns={[
        ['Nome', (a) => a.name ?? '—'],
        ['Business Unit', (a) => a.business_unit?.name ?? 'não informada'],
        [
          'Teams',
          (a) => (a.teams === null ? 'não informado' : a.teams.map((t) => t.name).join(', ') || 'Nenhum'),
        ],
        ['Criticidade', (a) => a.business_criticality ?? '—'],
        ['Último scan concluído', (a) => (a.last_completed_scan_date ? fmtDate(a.last_completed_scan_date) : '—')],
      ]}
      rowKey={(a) => a.guid}
      expand={(a) => <Sandboxes kind={kind} id={id} app={a} />}
    />
  );
}

function Sandboxes({ kind, id, app }: { kind: ScopeKind; id: string; app: VcApplication }) {
  const data = useLoad(() => veracode.sandboxes(kind, id, app.guid), [kind, id, app.guid]);
  if (data.error) return <ErrorBox message={`Falha ao carregar sandboxes: ${data.error}`} onRetry={data.reload} />;
  if (data.loading && !data.data) return <Loading label="Carregando sandboxes…" />;
  const page = data.data!;
  return (
    <div aria-label={`Sandboxes de ${app.name}`} role="group">
      <CollectionBanner page={page} />
      {!page.items.length ? (
        <p className="muted">Aplicação sem sandboxes.</p>
      ) : (
        <ul>
          {page.items.map((s) => (
            <li key={s.guid}>
              {s.name ?? s.guid}
              {s.modified && <span className="muted"> — modificado em {fmtDate(s.modified)}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CollectionBanner({ page }: { page: Pick<DiscoveryPage<unknown>, 'complete' | 'collections'> }) {
  const incomplete = page.collections.filter((c) => !c.complete);
  const latest = page.collections.reduce<CollectionStatus | null>(
    (acc, c) => (!acc || c.fetched_at > acc.fetched_at ? c : acc),
    null,
  );
  if (incomplete.length)
    return (
      <div role="alert" className="error-box" data-testid="collection-incomplete">
        <span>
          Coleta INCOMPLETA — dados parciais, não usar como resultado confiável.{' '}
          {incomplete.map((c) => `${c.resource}: ${c.reason?.message ?? 'motivo desconhecido'}`).join(' · ')}
        </span>
      </div>
    );
  return (
    <p className="muted" data-testid="collection-complete">
      Coleta completa
      {latest && ` · consultado em ${fmtDate(latest.fetched_at)}`}
      {page.collections.every((c) => c.cached) ? ' · do cache' : ''}
    </p>
  );
}

function Summary({
  summary,
  labels,
}: {
  summary: Record<string, unknown>;
  labels: Record<string, string>;
}) {
  return (
    <dl className="summary">
      {Object.entries(labels).map(([key, label]) => (
        <div key={key}>
          <dt>{label}</dt>
          <dd>{summary[key] === null || summary[key] === undefined ? '?' : String(summary[key])}</dd>
        </div>
      ))}
    </dl>
  );
}

function Pager({
  total,
  offset,
  onChange,
  loading,
}: {
  total: number;
  offset: number;
  onChange: (o: number) => void;
  loading: boolean;
}) {
  if (total <= PAGE_SIZE) return <p className="muted">{total} registro(s)</p>;
  const end = Math.min(offset + PAGE_SIZE, total);
  return (
    <div className="pager">
      <span className="muted">
        {offset + 1}–{end} de {total}
      </span>
      <button type="button" className="btn small" disabled={offset === 0 || loading} onClick={() => onChange(Math.max(0, offset - PAGE_SIZE))}>
        Anterior
      </button>
      <button type="button" className="btn small" disabled={end >= total || loading} onClick={() => onChange(offset + PAGE_SIZE)}>
        Próxima
      </button>
    </div>
  );
}

function MetadataTab({ kind, id }: { kind: ScopeKind; id: string }) {
  const data = useLoad(() => veracode.metadata(kind, id), [kind, id]);
  if (data.error) return <ErrorBox message={`Falha ao consultar a Veracode: ${data.error}`} onRetry={data.reload} />;
  if (data.loading && !data.data) return <Loading label="Consultando metadados…" />;
  const m = data.data!;
  const list = (rows: { value: string; applications: number }[]) =>
    rows.length ? rows.map((r) => `${r.value} (${r.applications})`).join(', ') : 'nenhum';
  return (
    <section aria-label="Metadados para filtros">
      <CollectionBanner page={m} />
      <p className="muted">
        Valores presentes nos perfis das {m.metadata.applications} aplicações. Base para os filtros da F03 — nada é
        inferido.
      </p>
      <dl className="details">
        <dt>Tags</dt>
        <dd>{list(m.metadata.tags)}</dd>
        <dt>Criticidade</dt>
        <dd>{list(m.metadata.business_criticality)}</dd>
        <dt>Políticas</dt>
        <dd>{list(m.metadata.policies)}</dd>
        {m.metadata.custom_fields.map((f) => (
          <React.Fragment key={f.name}>
            <dt>Campo: {f.name}</dt>
            <dd>
              {list(f.values)}
              {f.values_truncated && <span className="muted"> (lista truncada)</span>}
            </dd>
          </React.Fragment>
        ))}
      </dl>
      <h3 className="subsection">Filtros por domínio (disponibilidade)</h3>
      <table aria-label="Filtros por domínio">
        <thead>
          <tr>
            <th>Domínio</th>
            <th>Atributos disponíveis</th>
            <th>Fonte</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(m.metadata.domains).map(([d, info]) => (
            <tr key={d}>
              <td>{d}</td>
              <td>{info.available.join(', ') || 'nenhum nesta fase'}</td>
              <td>{info.source}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
