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
  summary?: Record<string, number | null | VeracodeErrorInfo>;
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
