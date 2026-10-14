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
