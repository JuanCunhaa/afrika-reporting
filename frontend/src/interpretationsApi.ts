// F08: interpretação dos indicadores (texto editorial assistido) com validação determinística e revisão humana.
// Nada daqui altera snapshots; o texto só entra no slide por "Aplicar" (nova revisão da apresentação).
import { request } from './api';

export type InterpretationKind =
  | 'EXECUTIVE_SUMMARY'
  | 'IMPROVEMENTS'
  | 'ATTENTION_POINTS'
  | 'SAST_TRENDS'
  | 'SCA_TRENDS'
  | 'PERIOD_COMPARISON'
  | 'COMPLIANCE_EVOLUTION'
  | 'SCAN_COVERAGE_EVOLUTION'
  | 'CHART_EXPLANATION'
  | 'RANKING_HIGHLIGHTS'
  | 'TECHNICAL_RECOMMENDATIONS';
export type InterpretationLevel = 'EXECUTIVE' | 'TECHNICAL';
export type InterpretationStatus = 'GENERATED' | 'IN_REVIEW' | 'APPROVED' | 'REJECTED';

export type InterpretationConfig = {
  settings: { provider: string; external_enabled: boolean; credential_configured: boolean; model: string | null; max_requests_per_day: number; max_input_chars: number };
  providers: { name: string; external: boolean; model: string | null }[];
  prompt_version: string;
  validator_version: string;
  kinds: { kind: InterpretationKind; name: string }[];
  kinds_by_slide_type: Record<string, InterpretationKind[]>;
  policy: string;
};

export type ValidationIssue = { level: 'blocker' | 'warning'; code: string; message: string; statement: number | null; token?: string };
export type Notice = { level: string; code: string; message: string };
export type SideValue = { competence: string; state: string; value_state: string | null; origin: string | null; value: number | null; label: string | null };
export type Indicator = {
  fact_id: string;
  metric_id: string;
  name: string;
  state: string;
  value_state: string | null;
  origin: string | null;
  definitive: boolean;
  current: SideValue;
  previous: SideValue;
  delta: number | null;
  delta_label: string | null;
  delta_pct: number | null;
  delta_unavailable_reason: string | null;
  trend: string;
  provenance: { current: { competence: string; revision: number | null; approval_sequence: number | null; content_hash: string | null; contract_version: number | null } };
  labels_redacted: boolean;
};

export type Interpretation = {
  id: string;
  presentation_id: string;
  owner: { kind: string; id: string; client_id: string; subclient_id: string | null };
  competence: { id: string; competence: string };
  presentation_revision: number;
  slide_id: string;
  target_field: 'body' | 'items' | 'caption' | 'notes';
  kind: InterpretationKind;
  kind_name: string;
  level: InterpretationLevel;
  version: number;
  parent_id: string | null;
  origin: 'GENERATED' | 'EDITED';
  text: string;
  statements: { text: string; fact_ids: string[] }[];
  provider: string;
  model: string | null;
  prompt_version: string;
  context_hash: string;
  sources_hash: string;
  content_hash: string;
  validation: { valid: boolean; blockers: number; warnings: number; issues: ValidationIssue[]; checked: Record<string, number> };
  valid: boolean;
  justification: string | null;
  created_by: string;
  created_at: string;
  status: InterpretationStatus;
  is_latest: boolean;
  stale: Notice[];
  notices: Notice[];
  applied: { presentation_revision: number; actor: string; at: string }[];
  events: { sequence: number; event: string; actor: string; reason: string | null; presentation_revision: number | null; at: string }[];
  indicators?: Indicator[];
  editorial_notes?: string[];
  history?: { id: string; version: number; origin: string; level: string; status: InterpretationStatus; valid: boolean; created_by: string; created_at: string }[];
};

export type InterpretationList = { items: Interpretation[]; disabled_slides: Record<string, { disabled: boolean; actor: string; reason: string | null; at: string }> };
export type Comparison = { from: { id: string; version: number; text: string }; to: { id: string; version: number; text: string }; diff: { op: string; from: string; to: string }[]; same_facts: boolean };

const base = (pid: string) => `/api/presentations/${pid}/interpretations`;

export const interpretationsApi = {
  config: () => request<InterpretationConfig>('GET', '/api/interpretation/config'),
  list: (pid: string) => request<InterpretationList>('GET', base(pid)),
  get: (pid: string, id: string) => request<Interpretation>('GET', `${base(pid)}/${id}`),
  generate: (pid: string, body: { slide_id: string; kind?: InterpretationKind; level: InterpretationLevel; notes: string[]; operator: string }) =>
    request<Interpretation>('POST', base(pid), body),
  review: (pid: string, id: string, operator: string) => request<Interpretation>('POST', `${base(pid)}/${id}/review`, { operator }),
  approve: (pid: string, id: string, operator: string) => request<Interpretation>('POST', `${base(pid)}/${id}/approve`, { operator }),
  reject: (pid: string, id: string, operator: string, reason: string) => request<Interpretation>('POST', `${base(pid)}/${id}/reject`, { operator, reason }),
  edit: (pid: string, id: string, text: string, operator: string, justification: string | null) =>
    request<Interpretation>('POST', `${base(pid)}/${id}/edit`, { text, operator, ...(justification ? { justification } : {}) }),
  regenerate: (pid: string, id: string, operator: string, level: InterpretationLevel) => request<Interpretation>('POST', `${base(pid)}/${id}/regenerate`, { operator, level }),
  apply: (pid: string, id: string, operator: string, expected_revision: number, overwrite_confirmed: boolean) =>
    request<{ presentation_revision: number; interpretation: Interpretation }>('POST', `${base(pid)}/${id}/apply`, { operator, expected_revision, overwrite_confirmed }),
  compare: (pid: string, id: string, other: string) => request<Comparison>('GET', `${base(pid)}/${id}/compare/${other}`),
  setDisabled: (pid: string, slideId: string, disabled: boolean, operator: string) =>
    request<{ disabled_slides: InterpretationList['disabled_slides'] }>('PUT', `/api/presentations/${pid}/interpretation-settings/${slideId}`, { disabled, operator }),
};
