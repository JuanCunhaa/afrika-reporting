// F05: competências, revisões, snapshots, aprovação, histórico e Reporting API (API local; nunca segredos).
import { request } from './api';

export type OwnerKind = 'client' | 'subclient';
export type RevisionStatus = 'DRAFT' | 'READY_FOR_REVIEW' | 'APPROVED';
export type ValueState = 'VALIDATED' | 'MANUAL' | 'INCOMPLETE' | 'SOURCE_UNAVAILABLE' | 'UNSUPPORTED' | 'MISSING';

export type Approval = {
  sequence: number;
  approver: string;
  identity_mode: 'DECLARED_UNAUTHENTICATED';
  note: string | null;
  approved_at: string;
  content_hash: string;
  previous_chain_hash: string | null;
  chain_hash: string;
};
export type RevisionSummary = {
  number: number;
  status: RevisionStatus;
  lock_version: number;
  created_by: string;
  created_at: string;
  submitted_by: string | null;
  submitted_at: string | null;
  approval: Approval | null;
  is_official: boolean;
};
export type Period = { period_start: string; period_end_inclusive: string; utc_start: string; utc_end_exclusive: string; timezone: string };
export type CompetenceOwner = { kind: OwnerKind; id: string; client_id: string; subclient_id: string | null };
export type Competence = {
  id: string;
  owner: CompetenceOwner;
  competence: string;
  timezone: string;
  period: Period;
  created_at: string;
  revisions: RevisionSummary[];
  open_revision: number | null;
  official_revision: number | null;
};
export type Snapshot = {
  metric_id: string;
  name: string;
  contract_version: number;
  value_type: 'count' | 'decimal' | 'percentage' | 'by_severity' | 'breakdown' | 'ranking';
  shape: string;
  unit: string;
  origin: 'VERACODE' | 'MANUAL';
  value: unknown;
  value_state: ValueState;
  headline: number | null;
  required: boolean;
  source: {
    status: string | null;
    value: unknown;
    partial: unknown;
    reasons: { code: string; message: string }[];
    name: string | null;
    endpoint: string | null;
    context: string | null;
    collected_at: string | null;
  };
  dashboard_homologation: string;
  temporal: Record<string, unknown>;
  scope_refs: { owner_name: string; domain: string; status: string; version: number | null; rule_hash: string | null }[];
  provenance: { run_id?: string; engine?: string; input_hash?: string };
  collection_run_id: string | null;
  manual: { justification: string; operator: string; at: string } | null;
  row_hash: string;
};
export type Check = { code: string; metric_id: string | null; message: string };
export type ManualChangeRow = {
  metric_id: string;
  previous_value: unknown;
  new_value: unknown;
  previous_origin: string | null;
  new_origin: string;
  justification: string;
  operator: string;
  changed_at: string;
};
export type Revision = {
  competence: { id: string; competence: string; timezone: string; owner: CompetenceOwner; period: Period };
  number: number;
  status: RevisionStatus;
  lock_version: number;
  editable: boolean;
  is_official: boolean;
  base_revision: number | null;
  required_metrics: string[];
  required_set_version: number;
  created_by: string;
  created_at: string;
  submitted_by: string | null;
  submitted_at: string | null;
  approval: Approval | null;
  snapshots: Snapshot[];
  metrics_without_snapshot: string[];
  checks: Check[];
  manual_changes: ManualChangeRow[];
};
export type AuditEventRow = { id: number; occurred_at: string; event_type: string; actor: string | null; details: Record<string, unknown>; event_hash: string };
export type Integrity = { ok: boolean; problems: string[]; approvals: number; audit_chain: { ok: boolean; events_checked: number } };
export type RevisionDiff = {
  a: number;
  b: number;
  changed: number;
  required_changed: boolean;
  items: { metric_id: string; changed: boolean; value_changed: boolean; a: { value: unknown; origin: string } | null; b: { value: unknown; origin: string } | null }[];
};
export type SeriesPoint = {
  competence: string;
  state: 'APPROVED' | 'GAP';
  value: unknown;
  headline: number | null;
  value_state: ValueState | null;
  origin: string | null;
  approval: { sequence: number; revision: number; approver: string; approved_at: string } | null;
};
export type Series = {
  metric_id: string;
  metric_name: string;
  timezone: string;
  start: string;
  end: string;
  points: SeriesPoint[];
  gaps: string[];
  without_value: string[];
  warnings: { code: string; message: string }[];
};
export type CompareItem = { metric_id: string; name: string; current: SeriesPoint; previous: SeriesPoint; delta: number | null; delta_unavailable_reason: string | null };
export type Compare = { competence: string; previous_competence: string; current_state: string; previous_state: string; items: CompareItem[] };

const rev = (cid: string, n: number) => `/api/competences/${cid}/revisions/${n}`;
type Lock = { operator: string; expected_lock_version: number };

export const snapshots = {
  list: (kind: OwnerKind, id: string) =>
    request<{ items: Competence[] }>('GET', `/api/competences?owner_kind=${kind}&owner_id=${id}`),
  create: (kind: OwnerKind, id: string, competence: string, operator: string) =>
    request<Competence>('POST', '/api/competences', { owner_kind: kind, owner_id: id, competence, operator }),
  fromRun: (run_id: string, operator: string) =>
    request<{ competence_id: string; revision: number; import: Record<string, number>; detail: Revision }>(
      'POST',
      '/api/competences/from-run',
      { run_id, operator },
    ),
  get: (cid: string) => request<Competence>('GET', `/api/competences/${cid}`),
  newRevision: (cid: string, operator: string) => request<Revision>('POST', `/api/competences/${cid}/revisions`, { operator }),
  revision: (cid: string, n: number) => request<Revision>('GET', rev(cid, n)),
  importRun: (cid: string, n: number, body: Lock & { run_id: string }) =>
    request<{ detail: Revision }>('POST', `${rev(cid, n)}/import-run`, body),
  setManual: (cid: string, n: number, metric: string, body: Lock & { value: unknown; justification: string }) =>
    request<Revision>('PUT', `${rev(cid, n)}/metrics/${metric}`, body),
  revert: (cid: string, n: number, metric: string, body: Lock & { justification: string }) =>
    request<Revision>('POST', `${rev(cid, n)}/metrics/${metric}/revert`, body),
  setRequired: (cid: string, n: number, body: Lock & { metric_ids: string[] }) =>
    request<Revision>('PUT', `${rev(cid, n)}/required`, body),
  submit: (cid: string, n: number, body: Lock) => request<Revision>('POST', `${rev(cid, n)}/submit`, body),
  returnToDraft: (cid: string, n: number, body: Lock & { reason: string }) =>
    request<Revision>('POST', `${rev(cid, n)}/return`, body),
  approve: (cid: string, n: number, body: { approver: string; note: string | null; expected_lock_version: number }) =>
    request<Revision>('POST', `${rev(cid, n)}/approve`, body),
  compare: (cid: string, a: number, b: number) => request<RevisionDiff>('GET', `/api/competences/${cid}/compare?a=${a}&b=${b}`),
  audit: (cid: string) => request<{ items: AuditEventRow[] }>('GET', `/api/competences/${cid}/audit`),
  integrity: (cid: string) => request<Integrity>('GET', `/api/competences/${cid}/integrity`),
  series: (kind: OwnerKind, id: string, metric: string, range: { months?: number; start?: string; end?: string }) => {
    const p = new URLSearchParams({ metric_id: metric });
    for (const [k, v] of Object.entries(range)) if (v !== undefined && v !== '') p.set(k, String(v));
    return request<Series>('GET', `/api/history/${kind}/${id}/series?${p}`);
  },
  compareMonth: (kind: OwnerKind, id: string, competence: string) =>
    request<Compare>('GET', `/api/history/${kind}/${id}/compare?competence=${competence}`),
};

// ---------------------------------------------------------------- Reporting API

export type ReportingStatus = {
  enabled: boolean;
  mode: string;
  enabled_types: string[];
  not_enabled_types: Record<string, string>;
  allowed_operations: string[];
  limits: Record<string, number>;
  active: number;
  quota_left_this_hour: number;
  scan_types: Record<string, string[]>;
};
export type ReportJob = {
  job_id: string;
  status: 'pending' | 'processing' | 'fetching' | 'done' | 'failed' | 'cancelled';
  owner: { kind: OwnerKind; id: string; name: string };
  report_type: string;
  request: Record<string, unknown>;
  mode: string;
  created_at: string;
  finished_at: string | null;
  veracode: { report_id?: string; veracode_status?: string; report_expiration_date?: string | null };
  progress: { stage: string; polls: number; pages_fetched: number; total_pages?: number };
  usage: { requests?: number; retries?: number };
  result: {
    complete: boolean;
    truncated: boolean;
    items_processed: number;
    total_elements_reported: number | null;
    aggregates: Record<string, unknown>;
    aggregates_status: string;
    caveats: string[];
  } | null;
  error: { code: string; message: string; upstream_status?: number | null; hint?: string } | null;
  remote_note?: string;
};

export const reporting = {
  status: () => request<ReportingStatus>('GET', '/api/reporting/status'),
  list: () => request<{ items: ReportJob[] }>('GET', '/api/reporting/jobs'),
  get: (id: string) => request<ReportJob>('GET', `/api/reporting/jobs/${id}`),
  start: (kind: OwnerKind, id: string, req: Record<string, unknown>) =>
    request<ReportJob>('POST', '/api/reporting/jobs', { owner_kind: kind, owner_id: id, request: req }),
  cancel: (id: string) => request<ReportJob>('POST', `/api/reporting/jobs/${id}/cancel`),
};

// Operador DECLARADO (sem autenticação): lembrado só neste navegador, por conveniência.
const OPERATOR_KEY = 'afrika.operator';
export function loadOperator(): string {
  try {
    return window.localStorage.getItem(OPERATOR_KEY) ?? '';
  } catch {
    return '';
  }
}
export function saveOperator(name: string) {
  try {
    window.localStorage.setItem(OPERATOR_KEY, name);
  } catch {
    /* armazenamento indisponível: segue sem lembrar */
  }
}

export const VALUE_STATE_LABEL: Record<ValueState, string> = {
  VALIDATED: 'Validado (técnico)',
  MANUAL: 'Manual',
  INCOMPLETE: 'Coleta incompleta',
  SOURCE_UNAVAILABLE: 'Fonte indisponível',
  UNSUPPORTED: 'Sem fonte',
  MISSING: 'Ausente',
};
export const VALUE_STATE_CLASS: Record<ValueState, string> = {
  VALIDATED: 'ok',
  MANUAL: 'warn',
  INCOMPLETE: 'warn',
  SOURCE_UNAVAILABLE: 'bad',
  UNSUPPORTED: 'off',
  MISSING: 'off',
};
export const REVISION_LABEL: Record<RevisionStatus, string> = {
  DRAFT: 'Rascunho',
  READY_FOR_REVIEW: 'Em revisão',
  APPROVED: 'Aprovada',
};
