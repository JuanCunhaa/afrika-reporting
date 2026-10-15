// F06A: templates, apresentações e modelo de visualização (API local). Nenhum endpoint daqui altera snapshots.
import { request } from './api';
import { OwnerKind, Snapshot } from './snapshotsApi';

export type SlideType =
  | 'cover'
  | 'executive_summary'
  | 'kpis'
  | 'month_comparison'
  | 'bar_chart'
  | 'line_chart'
  | 'severity_distribution'
  | 'top10_ranking'
  | 'metric_table'
  | 'recommendations'
  | 'closing';

export type SlideFields = {
  title: string | null;
  subtitle: string | null;
  body: string | null;
  items: string[];
  chart_title: string | null;
  legend_title: string | null;
  caption: string | null;
  notes: string | null;
};
export type SlideOptions = {
  months: 6 | 12 | null;
  data_mode: 'breakdown' | 'history' | null;
  show_legend: boolean | null;
  show_values: boolean | null;
  show_presenters: boolean | null;
  top_n: number | null;
};
export type DocSlide = {
  slide_id: string;
  template_slot: string | null;
  type: SlideType;
  layout: string;
  fields: Partial<SlideFields>;
  metrics: string[];
  options: Partial<SlideOptions>;
};
export type Presenter = { name: string; role?: string | null };
export type PresentationDocument = { schema_version: 1; title: string; presenters: Presenter[]; slides: DocSlide[] };

export type SlideTypeSpec = {
  type: SlideType;
  name: string;
  description: string;
  layouts: string[];
  default_layout: string;
  editable_fields: (keyof SlideFields)[];
  required_fields: (keyof SlideFields)[];
  min_metrics: number;
  max_metrics: number;
  value_types: string[];
  options: (keyof SlideOptions)[];
  chart: string | null;
};
export type CatalogMetric = { metric_id: string; name: string; contract_version: number; value_type: string; unit: string; support: string; slide_types: SlideType[] };
export type Theme = {
  id: string;
  version: number;
  name: string;
  provisional: boolean;
  notice: string;
  canvas: { width: number; height: number; aspect_ratio: string };
  fonts: { heading: string; body: string };
  colors: Record<string, string>;
};
export type Catalog = { slide_types: SlideTypeSpec[]; metrics: CatalogMetric[]; themes: Theme[] };

export type TemplateSummary = {
  id: string;
  key: string;
  version: number;
  name: string;
  description: string;
  theme: { id: string; version: number };
  origin: 'BUILTIN' | 'CUSTOM';
  definition_hash: string;
  versions?: number[];
};
export type Selection = { owner_key: string; template: TemplateSummary | null; inherited: boolean; selected_by?: string };

export type RevisionSummary = {
  number: number;
  created_by: string;
  created_at: string;
  change_summary: string;
  document_hash: string;
  revision_hash: string;
  source_revision: number;
  source_approval_sequence: number;
  source_content_hash: string;
};
export type PresentationMeta = {
  id: string;
  title: string;
  owner: { kind: OwnerKind; id: string; key: string };
  competence: { id: string; competence: string };
  template: TemplateSummary;
  current_revision: number;
  created_by: string;
  updated_at: string;
  revisions: RevisionSummary[];
};

// ---------------------------------------------------------------- IR de gráficos (backend/app/presentations/charts.py)
export type PointState = 'VALUE' | 'GAP' | 'MISSING' | 'NOT_NUMERIC' | 'INCOMPATIBLE' | 'NOT_APPLICABLE';
export type IRPoint = {
  x: string;
  y: number | null;
  state: PointState;
  label: string;
  value_state: string | null;
  origin: string | null;
  competence: string | null;
  metric_id: string;
  color?: string | null;
  extra?: Record<string, unknown>;
  aggregate?: boolean;
};
export type IRSeries = { key: string; label: string; metric_id: string; color: string; points: IRPoint[] };
type IRBase = { ir_version: number; kind: string; available: boolean; title: string | null; reason?: string; message?: string; warnings?: { code: string; message: string }[] };
export type IRUnavailable = IRBase & { available: false; reason: string; message: string };
export type IRKpi = IRBase & { kind: 'kpi'; items: (IRPoint & { name: string; unit_label: string })[] };
export type IRComparison = IRBase & {
  kind: 'comparison';
  current_competence: string;
  previous_competence: string;
  rows: { metric_id: string; name: string; unit_label: string; current: IRPoint; previous: IRPoint; delta: number | null; delta_label: string | null; delta_unavailable_reason: string | null }[];
};
export type IRChart = IRBase & {
  kind: 'bar' | 'line' | 'severity';
  x_axis: { type: 'month' | 'category'; label: string };
  y_axis: { label: string; min: number; integer: boolean };
  categories: string[];
  series: IRSeries[];
  legend: { show: boolean; title: string | null };
  gaps: string[];
  show_values?: boolean;
  total?: { y: number; label: string } | null;
  empty?: boolean;
};
export type IRRanking = IRBase & {
  kind: 'ranking';
  columns: string[];
  rows: { rank: number; label: string; y: number; value: string; extra: Record<string, unknown> }[];
  aggregate_rows: { label: string; y: number; value: string }[];
  max_y: number;
  show_values: boolean;
  empty: boolean;
};
export type IRTable = IRBase & {
  kind: 'table';
  rows: { metric_id: string; name: string; state: PointState; value: string; y: number | null; unit_label: string; value_state: string | null; origin: string | null; source: string | null }[];
};
export type CoverData = { kind: 'cover' | 'closing'; owner: string; owner_kind: OwnerKind; competence: string; period: { period_start: string; period_end_inclusive: string }; presenters: Presenter[] };
export type SlideData = IRUnavailable | IRKpi | IRComparison | IRChart | IRRanking | IRTable | CoverData | null;

export type Issue = { level: 'blocker' | 'warning' | 'info'; code: string; metric_id: string | null; message: string };
export type ViewSlide = {
  index: number;
  slide_id: string;
  template_slot: string | null;
  type: SlideType;
  type_name: string;
  layout: string;
  required: boolean;
  fields: SlideFields;
  options: SlideOptions;
  metrics: string[];
  data: SlideData;
  issues: Issue[];
};
export type SourceRef = { competence_id: string; competence: string; revision_id: string; revision: number; approval_id: string; approval_sequence: number; content_hash: string };
export type PresentationView = {
  presentation: { id: string; title: string; current_revision: number };
  draft: boolean;
  revision: { number: number; created_by: string; created_at: string; change_summary: string; document_hash: string; revision_hash: string };
  owner: { kind: OwnerKind; id: string; name: string; key: string };
  competence: { id: string; competence: string; timezone: string };
  template: TemplateSummary;
  theme: Theme;
  presenters: Presenter[];
  sources: { policy: string; primary: SourceRef; history: Record<string, SourceRef>; history_window: { start: string; end: string }; metrics: Snapshot[] };
  slides: ViewSlide[];
  checks: Issue[];
  ready: boolean;
  blockers: number;
};
export type PresentationIntegrity = { ok: boolean; problems: string[]; revisions_checked: number; sources_checked: { competence: string; revision: number; content_ok: boolean }[] };

const p = (pid: string) => `/api/presentations/${pid}`;

export const presentations = {
  catalog: () => request<Catalog>('GET', '/api/presentation-catalog'),
  templates: () => request<{ items: TemplateSummary[] }>('GET', '/api/presentation-templates'),
  installBuiltin: (operator: string) =>
    request<{ created: string[]; existing: string[] }>('POST', '/api/presentation-templates/builtin', { operator }),
  selection: (kind: OwnerKind, id: string) => request<Selection>('GET', `/api/template-selection/${kind}/${id}`),
  select: (kind: OwnerKind, id: string, template_key: string, template_version: number, operator: string) =>
    request<Selection>('PUT', `/api/template-selection/${kind}/${id}`, { template_key, template_version, operator }),
  list: (kind: OwnerKind, id: string) => request<{ items: PresentationMeta[] }>('GET', `/api/presentations?owner_kind=${kind}&owner_id=${id}`),
  create: (body: { competence_id: string; operator: string; template_key?: string; template_version?: number; title?: string }) =>
    request<PresentationMeta>('POST', '/api/presentations', body),
  get: (pid: string) => request<PresentationMeta>('GET', p(pid)),
  revision: (pid: string, n: number) => request<{ document: PresentationDocument; number: number; is_current: boolean }>('GET', `${p(pid)}/revisions/${n}`),
  view: (pid: string, revision?: number) => request<PresentationView>('GET', `${p(pid)}/view${revision ? `?revision=${revision}` : ''}`),
  preview: (pid: string, document: PresentationDocument) => request<PresentationView>('POST', `${p(pid)}/preview`, { document }),
  save: (pid: string, document: PresentationDocument, expected_revision: number, operator: string, summary: string) =>
    request<PresentationMeta>('PUT', `${p(pid)}/document`, { document, expected_revision, operator, summary }),
  rebind: (pid: string, expected_revision: number, operator: string) =>
    request<PresentationMeta & { changes: { primary_changed: boolean; history_changed: string[] } }>('POST', `${p(pid)}/rebind`, { expected_revision, operator }),
  integrity: (pid: string) => request<PresentationIntegrity>('GET', `${p(pid)}/integrity`),
};
