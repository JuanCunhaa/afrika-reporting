// F10: conferência humana dos indicadores com a plataforma Veracode (API local). O valor calculado vem do servidor.
import { request } from './api';

export type Category = 'APPLICABLE' | 'NOT_APPLICABLE' | 'BLOCKED_EXTERNAL';
export type Comparison = 'MATCH' | 'MISMATCH' | 'NOT_COMPARABLE' | 'NOT_VERIFIED' | 'NO_COMPUTED_VALUE' | Category;
export type Line = { key: string; label: string; computed: number };
export type Entry = Line & { official: number | null; difference: number | null; difference_pct: number | null };
export type Conference = {
  sequence: number;
  status: 'MATCH' | 'MISMATCH' | 'NOT_COMPARABLE';
  reasons: string[];
  entries: Entry[];
  filters_confirmed: boolean;
  checked_on: string;
  collected_on: string | null;
  evidence: string | null;
  note: string | null;
  operator: string;
  computed_origin: 'VERACODE' | 'MANUAL';
  created_at: string;
  stale: boolean;
};
export type ConferenceRow = {
  metric_id: string;
  name: string;
  domain: string;
  context: string;
  temporal_mode: string;
  same_day_required: boolean;
  guide: { category: Category; reason: string | null; path: string | null; filters: string[]; path_is_indicative: boolean };
  snapshot: { origin: string; value_state: string; source_status: string | null; collected_on: string | null; endpoint: string | null } | null;
  lines: Line[];
  comparison: Comparison;
  homologated: boolean;
  conference: Conference | null;
};
export type ConferenceSheet = {
  competence: { id: string; competence: string; timezone: string; owner_key: string };
  revision: { number: number; status: string };
  identity_mode: string;
  summary: Record<string, number>;
  metrics: ConferenceRow[];
};
export type ConferenceInput = {
  operator: string;
  checked_on: string;
  filters_confirmed: boolean;
  official: Record<string, number>;
  evidence?: string;
  not_comparable_note?: string;
};

const base = (cid: string, n: number) => `/api/competences/${cid}/revisions/${n}/conference`;

export const conference = {
  sheet: (cid: string, n: number) => request<ConferenceSheet>('GET', base(cid, n)),
  record: (cid: string, n: number, metricId: string, body: ConferenceInput) =>
    request<ConferenceRow>('POST', `${base(cid, n)}/${metricId}`, body),
  history: (cid: string, n: number, metricId: string) => request<Conference[]>('GET', `${base(cid, n)}/${metricId}/history`),
  csvUrl: (cid: string, n: number) => `${base(cid, n)}.csv`,
};

export const REASON_LABEL: Record<string, string> = {
  filters_not_confirmed: 'filtros/escopo não confirmados',
  current_state_date_mismatch: 'estado atual conferido em data diferente da coleta',
  entry_incomplete: 'linhas sem valor oficial',
  declared_not_comparable: 'declarado não comparável',
};

export const COMPARISON_LABEL: Record<Comparison, string> = {
  MATCH: 'Confere (MATCH)',
  MISMATCH: 'Diverge (MISMATCH)',
  NOT_COMPARABLE: 'Não comparável',
  NOT_VERIFIED: 'Não conferido',
  NO_COMPUTED_VALUE: 'Sem valor calculado',
  APPLICABLE: 'Aplicável',
  NOT_APPLICABLE: 'Não aplicável',
  BLOCKED_EXTERNAL: 'Bloqueado (externo)',
};
