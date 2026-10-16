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
  | 'closing'
  | 'section'
  | 'dashboard';

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
  zones?: Record<string, Zone>;
};
// F06B: zona do painel composto (indicadores só por metric_id; título editável)
export type Zone = { title?: string | null; metrics: string[]; chart?: 'bar' | 'line' | 'combo' | null; data_mode?: 'breakdown' | 'history' | null; months?: 6 | 12 | null; top_n?: number | null };
export type ZoneKind = 'kpi_band' | 'kpi_cards' | 'severity_cards' | 'donut' | 'chart' | 'comparison' | 'ranking' | 'table' | 'text';
export type ZoneSpec = { zone: string; kind: ZoneKind; name: string; min_metrics: number; max_metrics: number; value_types: string[]; frac: [number, number, number, number]; text_field: 'body' | 'items' | null; charts: string[] };
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
  zones?: Record<string, ZoneSpec[]>;
};
export type CatalogMetric = { metric_id: string; name: string; contract_version: number; value_type: string; unit: string; support: string; slide_types: SlideType[] };
// F06B.1: tema versionado com tokens completos (backend/app/presentations/themes.py). Os componentes só leem tokens.
export type Box = { x: number; y: number; w: number; h: number };
export type Insets = { top: number; right: number; bottom: number; left: number };
export type AssetRef = { asset_id: string; media_type: string };
export type FontSpec = { stack: string[]; export_family: string; asset: AssetRef | null };
export type Background = { color: string | null; image: AssetRef | null; fit: 'cover' | 'contain' };
export type LayoutOverride = { mode: 'flow' | 'fixed' | null; body: Box | null; header: Box | null; content: Box | null; background: Background | null; hide_footer: boolean };
export type Theme = {
  id: string;
  version: number;
  origin: 'BUILTIN' | 'CUSTOM';
  definition_hash: string;
  name: string;
  description: string;
  provisional: boolean;
  notice: string;
  canvas: { width: number; height: number };
  colors: Record<string, string>;
  fonts: { heading: FontSpec; body: FontSpec; numeric: FontSpec };
  weights: Record<string, number>;
  sizes: Record<string, number>;
  line_heights: Record<string, number>;
  spacing: Record<string, number>;
  radii: Record<string, number>;
  borders: Record<string, number>;
  layout: {
    mode: 'flow' | 'fixed';
    body: Box;
    header: Box | null;
    content: Box | null;
    footer: { x: number; w: number; bottom: number; reserve: number };
    visual_side_ratio: [number, number];
    summary_ratio: [number, number];
  };
  layouts: Record<string, LayoutOverride>;
  header: { accent_bar: boolean; accent_width: number; accent_color: string; padding_left: number; align: 'left' | 'center' };
  footer: { show: boolean; items: ('owner_competence' | 'source' | 'provisional' | 'page' | 'custom_text')[]; separator: boolean; custom_text: string | null };
  cover: { band: 'left' | 'top' | 'none'; band_size: number; band_color: string; padding: Insets; gap: number; meta_top: number; align: 'left' | 'center'; kicker_uppercase: boolean };
  closing: { padding: Insets; gap: number; align: 'left' | 'center' };
  backgrounds: { default: Background; cover: Background | null; closing: Background | null };
  images: { name: string; asset: AssetRef; box: Box; slides: ('all' | 'cover' | 'closing' | 'content' | 'section')[]; fit: 'contain' | 'cover'; alt: string }[];
  components: ThemeComponents;
  semantics: ThemeSemantics;
  asset_slots: AssetSlot[];
  charts: {
    plot_width: number;
    plot_height: number;
    plot_width_with_text: number;
    plot_padding: Insets;
    plot_max_height: number;
    y_ticks: number;
    bar_max_width: number;
    bar_width_ratio: number;
    bar_radius: number;
    gap_dash: string;
    gap_bar_ratio: number;
    line_width: number;
    point_radius: number;
    point_stroke: number;
    axis_label_offset: number;
    axis_label_min_gap: number;
    category_label_offset: number;
    value_label_offset: number;
    point_label_offset: number;
    severity_label_width: number;
    severity_value_width: number;
    severity_bar_height: number;
    rank_bar_height: number;
    rank_bar_max: number;
    swatch_size: number;
    swatch_gap: number;
    swatch_baseline_offset: number;
    rank_bar_gap: number;
    min_bar: number;
    grid_width: number;
    gap_line_dash: string;
    axis_label_baseline: number;
    unit_label_y: number;
    gap_label_y_offset: number;
    texture_stripe: number;
    texture_period: number;
    texture_opacity: number;
    legend_position: 'top' | 'bottom';
  };
};
export type ThemeComponents = {
  title_color: string;
  title_underline: { w: number; h: number; color: string; radius: number; offset: number } | null;
  badge: { box: Box; fill: string; border: string; border_width: number; radius: number; month_size: number; year_size: number; color: string; year_color: string } | null;
  card: { fill: string; border: string; border_width: number; radius: number; padding_y: number; padding_x: number; title_size: number; title_color: string };
  band: { fill: string; radius: number; padding: number; label_color: string };
  pill: { fill: string; color: string; radius: number; size: number; padding_x: number; padding_y: number };
  table: { header_fill: string | null; header_color: string; header_rule: string; row_rule: string; zebra_fill: string | null };
  section: { background: string; title_color: string; subtitle_color: string; title_size: number; subtitle_size: number; orientation: 'horizontal' | 'vertical'; title_box: Box | null };
  closing: { title: string; text: string; accent: string; title_font: 'heading' | 'body' | 'numeric'; title_weight: number | null; title_size: number | null; valign: 'top' | 'center' };
  header_valign: 'top' | 'center' | 'bottom';
  zone_comparison: 'table' | 'columns';
  comparison_fill: string;
  header_valign_by_layout: Record<string, 'top' | 'center' | 'bottom'>;
  zone_frames: Record<string, Record<string, 'band' | 'card' | 'plain'>>;
  cover_title_color: string;
  cover_kicker_color: string;
  cover_valign: 'top' | 'bottom';
  cover_title_font: 'heading' | 'body' | 'numeric';
  cover_kicker_font: 'heading' | 'body' | 'numeric';
  cover_kicker_weight: number;
  shapes: { name: string; box: Box; fill: string; opacity: number; path: string | null; radius: number; slides: ('all' | 'cover' | 'closing' | 'content' | 'section')[] }[];
  severity_bar_width: number;
  donut_hole: number;
  dashboards: Record<string, Record<string, Box>>;
  donut_separator: number; // F06C
  subtitle_color: string | null; // F06C: null = visual F06B
  subtitle_font: 'heading' | 'body' | 'numeric' | null;
  subtitle_weight: number | null;
  subtitle_line_height: number | null;
  matrix_label_size: number | null;
};
// F06C: semântica de cores (severidade por nível; variação comprovada). null = comportamento F06B (neutro).
export type ThemeSemantics = {
  severity: { levels: Record<string, string>; mapping: Record<string, string>; unknown: string } | null;
  variation: { improvement: string; worsening: string; neutral: string; tint_opacity: number } | null;
};
export type AssetSlot = { name: string; box: Box; slides: ('all' | 'cover' | 'closing' | 'content' | 'section')[]; fit: 'contain' | 'cover'; alt: string };
export type BrandAsset = { slot: string; status: 'available' | 'missing' | 'invalid'; media_type?: string; sha256?: string; url?: string; message?: string };
export type ThemeSummary = { id: string; version: number; name: string; provisional: boolean; origin: 'BUILTIN' | 'CUSTOM'; versions: number[]; definition_hash: string };
export type Catalog = { slide_types: SlideTypeSpec[]; metrics: CatalogMetric[]; themes: ThemeSummary[] };

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
// F06C: tendência COMPROVADA (só com variação entre aprovados comparáveis e direção declarada no indicador).
export type Trend = 'improvement' | 'worsening' | 'unchanged' | 'unknown';
export type ComparisonRow = {
  metric_id: string;
  name: string;
  unit_label: string;
  current: IRPoint;
  previous: IRPoint;
  delta: number | null;
  delta_label: string | null;
  delta_unavailable_reason: string | null;
  direction?: 'LOWER_IS_BETTER' | 'HIGHER_IS_BETTER' | 'NEUTRAL';
  trend?: Trend;
  trend_reason?: string | null;
  trend_color?: string;
};
export type IRComparison = IRBase & {
  kind: 'comparison';
  current_competence: string;
  previous_competence: string;
  rows: ComparisonRow[];
};
export type IRChart = IRBase & {
  kind: 'bar' | 'line' | 'severity' | 'combo';
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
export type CoverData = { kind: 'cover' | 'closing'; owner: string; owner_kind: OwnerKind; competence: string; period: { period_start: string; period_end_inclusive: string }; period_label?: string; presenters: Presenter[] };
export type SectionData = { kind: 'section'; owner: string; competence: string };
export type DashboardZone = { zone: string; kind: ZoneKind; name: string; title: string | null; text_field: 'body' | 'items' | null; chart: string | null; metrics: string[]; data: SlideData };
export type DashboardData = { kind: 'dashboard'; layout: string; zones: Record<string, DashboardZone> };
export type SlideData = IRUnavailable | IRKpi | IRComparison | IRChart | IRRanking | IRTable | CoverData | SectionData | DashboardData | null;

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
  zones?: Record<string, Zone>;
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
  brand_assets?: Record<string, BrandAsset>;
  presenters: Presenter[];
  sources: { policy: string; primary: SourceRef; history: Record<string, SourceRef>; history_window: { start: string; end: string }; metrics: Snapshot[] };
  slides: ViewSlide[];
  checks: Issue[];
  ready: boolean;
  blockers: number;
};
export type PresentationIntegrity = { ok: boolean; problems: string[]; revisions_checked: number; sources_checked: { competence: string; revision: number; content_ok: boolean }[] };

export type SlotAvailability = {
  template: { key: string; version: number };
  competence: { id: string; competence: string; revision: number; approval_sequence: number };
  slots: { slot_id: string; type: string; layout: string | null; title: string | null; required: boolean; required_metrics: boolean; status: 'complete' | 'partial' | 'none' | 'editorial'; metrics: { metric_id: string; state: string }[]; suggested: boolean }[];
  policy: string;
};

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
  create: (body: { competence_id: string; operator: string; template_key?: string; template_version?: number; title?: string; slots?: string[] }) =>
    request<PresentationMeta>('POST', '/api/presentations', body),
  // F06C: situação de cada slot do template na revisão aprovada (para escolher os slides; nada é gravado)
  availability: (key: string, version: number, competenceId: string) =>
    request<SlotAvailability>('GET', `/api/presentation-templates/${key}/versions/${version}/availability?competence_id=${competenceId}`),
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
