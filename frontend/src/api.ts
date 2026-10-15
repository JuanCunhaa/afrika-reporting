// Cliente HTTP da API local (proxy Vite em /api). Nunca envia nem recebe segredos.
export type ReportMode = 'consolidated' | 'per_subclient' | 'both';
export type Region = 'commercial' | 'european' | 'federal';
export type StatusFilter = 'all' | 'active' | 'inactive';

export type Page<T> = { items: T[]; total: number; limit: number; offset: number };

export type ConnectionSummary = { id: string; name: string; region: Region; credential_ref: string };
export type Connection = ConnectionSummary & {
  description: string | null;
  client_count: number;
  subclient_count: number;
  created_at: string;
  updated_at: string;
};

export type Client = {
  id: string;
  name: string;
  display_name: string;
  description: string | null;
  is_active: boolean;
  report_mode: ReportMode;
  connection_id: string | null;
  connection: ConnectionSummary | null;
  subclient_count: number;
  active_subclient_count: number;
  created_at: string;
  updated_at: string;
};

export type Subclient = {
  id: string;
  client_id: string;
  name: string;
  display_name: string;
  is_active: boolean;
  effective_active: boolean;
  connection_id: string | null;
  effective_connection: ConnectionSummary | null;
  connection_source: 'subclient' | 'client' | 'none';
  created_at: string;
  updated_at: string;
};

export type ClientInput = {
  name: string;
  display_name: string;
  description: string | null;
  is_active: boolean;
  report_mode: ReportMode;
  connection_id: string | null;
};
export type SubclientInput = { name: string; display_name: string; is_active: boolean; connection_id: string | null };
export type ConnectionInput = { name: string; description: string | null; region: Region; credential_ref: string };

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: { field: string; message: string }[] = [],
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, 'network_error', 'Não foi possível contatar a API. Verifique se o backend está em execução.');
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = data?.error;
    // Sem corpo de erro da API: resposta veio do proxy/gateway (backend parado ou inacessível).
    if (!err && res.status >= 500)
      throw new ApiError(
        res.status,
        'api_unavailable',
        `API indisponível (HTTP ${res.status}). Verifique se o backend está em execução.`,
      );
    throw new ApiError(res.status, err?.code ?? 'http_error', err?.message ?? `HTTP ${res.status}`, err?.details ?? []);
  }
  return data as T;
}

const qs = (params: Record<string, string | number | undefined>) =>
  new URLSearchParams(
    Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== '')
      .map(([k, v]) => [k, String(v)]),
  ).toString();

export const api = {
  listClients: (p: { limit: number; offset: number; status: StatusFilter; q?: string }) =>
    request<Page<Client>>('GET', `/api/clients?${qs(p)}`),
  getClient: (id: string) => request<Client>('GET', `/api/clients/${id}`),
  createClient: (body: ClientInput) => request<Client>('POST', '/api/clients', body),
  updateClient: (id: string, body: Partial<ClientInput>) => request<Client>('PATCH', `/api/clients/${id}`, body),
  deleteClient: (id: string) => request<void>('DELETE', `/api/clients/${id}`),

  listSubclients: (clientId: string) =>
    request<Page<Subclient>>('GET', `/api/clients/${clientId}/subclients?limit=200`),
  createSubclient: (clientId: string, body: SubclientInput) =>
    request<Subclient>('POST', `/api/clients/${clientId}/subclients`, body),
  updateSubclient: (id: string, body: Partial<SubclientInput>) =>
    request<Subclient>('PATCH', `/api/subclients/${id}`, body),
  deleteSubclient: (id: string) => request<void>('DELETE', `/api/subclients/${id}`),

  listConnections: () => request<Page<Connection>>('GET', '/api/connections?limit=200'),
  createConnection: (body: ConnectionInput) => request<Connection>('POST', '/api/connections', body),
  updateConnection: (id: string, body: Partial<ConnectionInput>) =>
    request<Connection>('PATCH', `/api/connections/${id}`, body),
  deleteConnection: (id: string) => request<void>('DELETE', `/api/connections/${id}`),
};

export const REPORT_MODE_LABEL: Record<ReportMode, string> = {
  consolidated: 'Consolidado',
  per_subclient: 'Individual por subcliente',
  both: 'Consolidado + individual',
};

export const REGION_LABEL: Record<Region, string> = {
  commercial: 'Commercial (US)',
  european: 'European (EU)',
  federal: 'Federal (US)',
};

export const errorMessage = (e: unknown) => (e instanceof Error ? e.message : String(e));

// ---------------------------------------------------------------- F02: descoberta Veracode (somente leitura)

export type ScopeKind = 'clients' | 'subclients';
export type ScopeInfo = {
  kind: 'client' | 'subclient';
  id: string;
  name: string;
  client_id: string;
  connection_source: 'subclient' | 'client' | 'none';
  connection: { id: string; name: string; region: Region; credential_ref: string } | null;
};
export type CredentialStatus = 'configured' | 'missing' | 'invalid_format' | 'unsupported_ref' | 'not_configured';
export type VeracodeScope = {
  scope: ScopeInfo;
  credential_status: CredentialStatus;
  mode: 'live' | 'fixture';
  cache_ttl_seconds: number;
  page_size: number;
  max_concurrency: number;
};
export type VeracodeErrorInfo = { code: string; message: string; upstream_status: number | null };
export type CollectionStatus = {
  resource: string;
  complete: boolean;
  status: 'complete' | 'incomplete';
  reason: VeracodeErrorInfo | null;
  pages_fetched: number;
  total_pages_reported: number | null;
  total_elements_reported: number | null;
  items_collected: number;
  requests: number;
  retries: number;
  fetched_at: string;
  cached: boolean;
  cache_ttl_remaining: number | null;
};
export type DiscoveryPage<T> = Page<T> & {
  scope: ScopeInfo;
  complete: boolean;
  collections: CollectionStatus[];
  summary?: Record<string, unknown>;
};
export type ConnectionCheck = { check: string; status: 'ok' | 'error'; error: VeracodeErrorInfo | null };
export type ConnectionTest = { scope: ScopeInfo; status: 'ok' | 'partial' | 'error'; checks: ConnectionCheck[] };

type Ref = { guid: string | null; legacy_id: number | null; name: string | null };
export type VcApplication = {
  guid: string;
  legacy_id: number | null;
  name: string | null;
  business_unit: Ref | null;
  teams: Ref[] | null;
  tags: string | null;
  business_criticality: string | null;
  custom_fields: { name: string | null; value: string | null }[] | null;
  policies: { guid: string | null; name: string | null; compliance_status: string | null }[] | null;
  last_completed_scan_date: string | null;
};
export type VcSandbox = { guid: string; legacy_id: number | null; name: string | null; modified: string | null };
export type VcBusinessUnit = {
  bu_id: string;
  name: string | null;
  is_default: boolean | null;
  team_ids: string[] | null;
};
export type VcTeam = {
  team_id: string;
  name: string | null;
  business_unit: { bu_id: string | null; name: string | null } | null;
  user_count: number | null;
};
export type VcUser = {
  user_id: string;
  user_name: string | null;
  first_name: string | null;
  last_name: string | null;
  active: boolean | null;
  login_enabled: boolean | null;
  account_type: string | null;
};
type Matched = { identity_match: boolean | null };
export type VcAppRelationship = {
  application: { guid: string; name: string | null };
  business_unit: (Ref & Matched) | null;
  teams: (Ref & Matched)[] | null;
};
export type VcUserRelationship = {
  user: VcUser;
  teams: { team_id: string; team_name: string | null; relationship: string | null }[] | null;
  teams_complete: boolean;
  reconciliation: string;
  team_count_reported: number | null;
};
export type VcMetadata = {
  scope: ScopeInfo;
  complete: boolean;
  collections: CollectionStatus[];
  metadata: {
    applications: number;
    custom_fields: {
      name: string;
      applications: number;
      distinct_values: number;
      values: { value: string; applications: number }[];
      values_truncated: boolean;
    }[];
    tags: { value: string; applications: number }[];
    business_criticality: { value: string; applications: number }[];
    policies: { value: string; applications: number }[];
    domains: Record<string, { available: string[]; source: string }>;
  };
};
export type ListParams = { q?: string; limit: number; offset: number };

const vcBase = (kind: ScopeKind, id: string) => `/api/veracode/${kind}/${id}`;

export const veracode = {
  scope: (kind: ScopeKind, id: string) => request<VeracodeScope>('GET', vcBase(kind, id)),
  test: (kind: ScopeKind, id: string) => request<ConnectionTest>('POST', `${vcBase(kind, id)}/test`),
  invalidate: (kind: ScopeKind, id: string) =>
    request<{ removed_entries: number }>('DELETE', `${vcBase(kind, id)}/cache`),
  list: <T,>(kind: ScopeKind, id: string, resource: string, p: ListParams) =>
    request<DiscoveryPage<T>>('GET', `${vcBase(kind, id)}/${resource}?${qs(p)}`),
  sandboxes: (kind: ScopeKind, id: string, appGuid: string) =>
    request<DiscoveryPage<VcSandbox>>('GET', `${vcBase(kind, id)}/applications/${appGuid}/sandboxes?limit=200`),
  metadata: (kind: ScopeKind, id: string) => request<VcMetadata>('GET', `${vcBase(kind, id)}/metadata`),
};

// ---------------------------------------------------------------- F03: escopos e filtros

export type ScopeDomain = 'applications' | 'users' | 'scans' | 'sca';
export type OwnerKind = 'client' | 'subclient';
export type ConnectionMode = 'client' | 'shared' | 'separate' | 'none';
export type RuleLeaf = {
  field: string;
  cmp: string;
  key?: string;
  value?: string | boolean;
  values?: (string | boolean)[];
};
export type RuleNode =
  | { op: 'all' }
  | { op: 'and' | 'or'; args: RuleNode[] }
  | { op: 'not'; arg: RuleNode }
  | RuleLeaf;
export type FieldSpec = {
  name: string;
  label: string;
  type: 'id' | 'string' | 'enum' | 'bool';
  multi: boolean;
  cmps: string[];
  enum: string[] | null;
  keyed: boolean;
  note: string;
};
export type FieldsCatalog = {
  domains: Record<ScopeDomain, { fields: FieldSpec[]; evaluable: boolean }>;
  limits: Record<string, number>;
};
export type ScopeOptions = { inactive_users?: 'exclude' | 'include' };
export type ScopeVersion = {
  version: number;
  status: 'active' | 'superseded';
  rule: RuleNode;
  options: ScopeOptions;
  rule_hash: string;
  connection_mode: ConnectionMode;
  coverage_ack: boolean;
  note: string | null;
  created_at: string;
};
export type ScopeState = {
  owner: { kind: OwnerKind; id: string; name: string; client_id: string; effective_active: boolean };
  domain: ScopeDomain;
  evaluable: boolean;
  connection_mode: ConnectionMode;
  defined: boolean;
  status: 'active' | 'disabled' | 'not_defined';
  active_version: ScopeVersion | null;
  latest_version: number;
  versions?: ScopeVersion[];
};
export type ScopeOverview = {
  client_id: string;
  domains: ScopeDomain[];
  owners: {
    kind: OwnerKind;
    id: string;
    name: string;
    effective_active: boolean;
    connection_mode: ConnectionMode;
    scopes: Record<ScopeDomain, ScopeState>;
  }[];
};
export type RuleIssue = { field: string; type: string; message: string };
export type ValidationResult = {
  valid: boolean;
  issues: RuleIssue[];
  complexity: { nodes: number; depth: number; values: number; limits: Record<string, number> };
  rule: RuleNode | null;
  rule_hash: string | null;
};
export type SampleItem = { id: string; name: string | null };
export type UsersPerTeam = {
  complete: boolean;
  reason: string | null;
  teams: { team_id: string; name: string | null; unique_users: number | null }[];
  unique_users_total: number | null;
};
export type OwnerResolution = {
  kind: OwnerKind;
  id: string;
  name: string;
  effective_active: boolean;
  connection_mode: ConnectionMode;
  scope_status: string;
  version: number | null;
  draft: boolean;
  status?: string;
  defined?: boolean;
  total_available?: number;
  included?: number;
  excluded?: number;
  undetermined?: number;
  inactive_excluded?: number;
  missing_fields?: Record<string, number>;
  sample?: SampleItem[];
  users_per_team?: UsersPerTeam | null;
  intersected?: boolean;
  outside_universe?: number;
  tenant?: 'separate';
  complete?: boolean;
  error?: VeracodeErrorInfo;
};
export type ResolutionWarning = { code: string; message: string; blocking: boolean };
export type Resolution = {
  client: ScopeInfo;
  domain: ScopeDomain;
  evaluable: boolean;
  status: 'ok' | 'incomplete' | 'universe_not_defined' | 'deferred_f04';
  complete: boolean;
  message?: string;
  universe: OwnerResolution;
  subclients: OwnerResolution[];
  unclassified?: {
    available: boolean;
    count: number | null;
    complete: boolean;
    reasons: string[];
    no_subclients: boolean;
    sample: SampleItem[];
  };
  overlap?: {
    resources_in_multiple: number;
    pairs: { a: string; b: string; count: number }[];
    sample: (SampleItem & { subclients: string[] })[];
  } | null;
  warnings: ResolutionWarning[];
  collections: CollectionStatus[];
  reconciliation?: { status: string; reason: string | null } & Record<string, number | string | null>;
  members_not_in_user_list?: number;
};
export type Draft = { owner_kind: OwnerKind; owner_id: string; rule: RuleNode; options: ScopeOptions; coverage_ack: boolean };

const scopeBase = (kind: OwnerKind, id: string, domain: ScopeDomain) =>
  `/api/scopes/${kind === 'client' ? 'clients' : 'subclients'}/${id}/${domain}`;

export const scopes = {
  fields: () => request<FieldsCatalog>('GET', '/api/scopes/fields'),
  overview: (clientId: string) => request<ScopeOverview>('GET', `/api/scopes/clients/${clientId}`),
  get: (kind: OwnerKind, id: string, domain: ScopeDomain) => request<ScopeState>('GET', scopeBase(kind, id, domain)),
  validate: (domain: ScopeDomain, rule: RuleNode, options: ScopeOptions) =>
    request<ValidationResult>('POST', '/api/scopes/validate', { domain, rule, options }),
  save: (
    kind: OwnerKind,
    id: string,
    domain: ScopeDomain,
    body: { rule: RuleNode; options: ScopeOptions; note: string | null; coverage_ack: boolean; expected_version: number },
  ) => request<ScopeState & { created: boolean }>('PUT', scopeBase(kind, id, domain), body),
  restore: (kind: OwnerKind, id: string, domain: ScopeDomain, version: number, expected_version: number, coverage_ack: boolean) =>
    request<ScopeState & { created: boolean }>('POST', `${scopeBase(kind, id, domain)}/versions/${version}/restore`, {
      expected_version,
      coverage_ack,
    }),
  setStatus: (kind: OwnerKind, id: string, domain: ScopeDomain, status: 'active' | 'disabled') =>
    request<ScopeState>('PATCH', scopeBase(kind, id, domain), { status }),
  preview: (clientId: string, domain: ScopeDomain, draft: Draft | null) =>
    request<Resolution>('POST', `/api/scope-preview/clients/${clientId}`, { domain, draft, sample_limit: 50 }),
};

// ---------------------------------------------------------------- F04: indicadores (somente leitura na Veracode)

export type MetricStatus = 'VALIDATED' | 'INCOMPLETE' | 'UNAVAILABLE' | 'UNSUPPORTED' | 'FAILED';
export type MetricReason = { code: string; message: string };
export type MetricRow = {
  metric_id: string;
  contract_version: number;
  status: MetricStatus;
  publishable: boolean;
  value: unknown;
  partial: unknown;
  reasons: MetricReason[];
  coverage: Record<string, unknown>;
  filters: Record<string, unknown>;
  temporal: {
    mode: 'CURRENT_STATE' | 'EVENT_IN_PERIOD' | 'STATE_AT_PERIOD_END';
    competence: string;
    date_field: string;
    as_of: string;
    historical_state: boolean;
    note: string;
    period: { period_start: string; period_end_inclusive: string; utc_offset: string };
  };
  name: string;
  description: string;
  domain: 'applications' | 'sast' | 'sca' | 'scans' | 'licenses';
  source: string;
  endpoint: string | null;
  context: string;
  scan_type: string;
  shape: 'SCALAR' | 'BY_SEVERITY' | 'BREAKDOWN' | 'RANKING';
  unit: string;
  support: string;
  homologation: string;
  limitations: string[];
};
export type MetricRunResult = {
  collected_at: string;
  applications_collected_at: string | null;
  connection: { connection_source: string; id?: string; name?: string; region?: Region } | null;
  population: { status: string; reasons: MetricReason[]; applications: number; total_available: number | null; undetermined: number };
  collection: { contexts: number; requests: number; retries: number; cache_hits: number; limit_reached: string | null } | null;
  provenance: { run_id: string; engine: string; input_hash: string; scope_refs: { owner_name: string; domain: string; status: string; version: number | null; rule_hash: string | null }[] };
  summary: Partial<Record<MetricStatus, number>>;
  metrics: MetricRow[];
};
export type MetricRun = {
  run_id: string;
  status: 'pending' | 'running' | 'done' | 'cancelled' | 'failed';
  owner: { kind: 'client' | 'subclient'; id: string; name: string; client_id: string };
  competence: { competence: string; utc_offset: string; period_start: string; period_end_inclusive: string };
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  progress: { stage: string; applications_done: number; applications_total: number | null };
  error: MetricReason | null;
  result?: MetricRunResult | null;
};
export type MetricRunInput = { owner_kind: 'client' | 'subclient'; owner_id: string; competence: string; utc_offset: string };

export const metrics = {
  start: (body: MetricRunInput) => request<MetricRun>('POST', '/api/metrics/runs', body),
  get: (runId: string) => request<MetricRun>('GET', `/api/metrics/runs/${runId}`),
  cancel: (runId: string) => request<MetricRun>('POST', `/api/metrics/runs/${runId}/cancel`),
};
