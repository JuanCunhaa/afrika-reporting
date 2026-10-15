import React, { createContext, useContext, useEffect, useRef, useState } from 'react';
import {
  CoverData,
  IRChart,
  IRComparison,
  IRKpi,
  IRPoint,
  IRRanking,
  IRTable,
  IRUnavailable,
  PresentationView,
  SlideData,
  Theme,
  ViewSlide,
} from '../presentationsApi';
import { ResolvedLayout, assetUrl, backgroundStyle, boxStyle, colorVar, fontFaceCss, fontStack, layoutFor, slideKind, themeVars } from './theme';

// F06A/F06B.1 — renderizador HTML da IR. Só DESENHA o que veio do backend (valores aprovados + rótulos já formatados);
// não calcula, soma nem interpola números. Escalas/grades são geometria do desenho, não dados.
// Todo valor visual (cor, fonte, tamanho, espaçamento, posição, formato de gráfico, dimensões) vem do TEMA versionado
// (variáveis CSS geradas em theme.ts + contexto abaixo); trocar a marca = trocar o tema.

const ThemeCtx = createContext<Theme | null>(null);
const useTheme = () => useContext(ThemeCtx) as Theme;

export function themeStyle(theme: Theme): React.CSSProperties {
  return themeVars(theme) as React.CSSProperties;
}

// Escala o canvas do tema (ex.: 1280×720) para a largura disponível, mantendo a proporção.
export function SlideCanvas({ view, slide, label }: { view: PresentationView; slide: ViewSlide; label?: string }) {
  const outer = useRef<HTMLDivElement>(null);
  const { width, height } = view.theme.canvas;
  const [scale, setScale] = useState(0.5);
  useEffect(() => {
    const el = outer.current;
    if (!el) return;
    const update = () => setScale(el.clientWidth / width || 0.5);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [width]);
  return (
    <div ref={outer} className="slide-frame" style={{ height: height * scale }}>
      <SlideSurface view={view} slide={slide} label={label} scale={scale} testId="slide-canvas" />
    </div>
  );
}

/** Injeta (uma vez por tema) o @font-face das fontes do tema com arquivo local e re-renderiza quando as fontes
 * terminam de carregar (a medição de rótulos dos gráficos usa a fonte real). */
function useThemeFonts(theme: Theme) {
  const css = fontFaceCss(theme);
  const [, bump] = useState(0);
  useEffect(() => {
    let alive = true;
    document.fonts?.ready.then(() => alive && bump((n) => n + 1));
    return () => {
      alive = false;
    };
  }, [theme.id, theme.version]);
  useEffect(() => {
    if (!css) return;
    const id = `theme-fonts-${theme.id}-${theme.version}`;
    if (document.getElementById(id)) return;
    const style = document.createElement('style');
    style.id = id;
    style.textContent = css;
    document.head.appendChild(style);
  }, [css, theme.id, theme.version]);
}

// Superfície do slide em tamanho nativo (escala 1 na captura determinística `#/render/{id}`).
export function SlideSurface({ view, slide, label, scale = 1, testId }: { view: PresentationView; slide: ViewSlide; label?: string; scale?: number; testId?: string }) {
  const theme = view.theme;
  useThemeFonts(theme);
  const kind = slideKind(slide.type);
  const lay = layoutFor(theme, slide.layout);
  const images = theme.images.filter((img) => img.slides.includes('all') || img.slides.includes(kind));
  return (
    <ThemeCtx.Provider value={theme}>
      <div
        className={`slide slide-${slide.type} layout-${slide.layout}`}
        style={{ ...themeStyle(theme), ...backgroundStyle(theme, kind, lay), transform: scale === 1 ? undefined : `scale(${scale})`, width: theme.canvas.width, height: theme.canvas.height }}
        role="group"
        aria-roledescription="slide"
        aria-label={label ?? `Slide ${slide.index} de ${view.slides.length}: ${slide.fields.title ?? slide.type_name}`}
        data-testid={testId}
        data-slide-index={slide.index}
      >
        {images.map((img) => (
          <img key={img.name} className="slide-image" src={assetUrl(img.asset)} alt={img.alt} style={{ ...boxStyle(img.box), objectFit: img.fit }} data-el={`image:${img.name}`} />
        ))}
        <SlideBody view={view} slide={slide} lay={lay} />
        {theme.footer.show && !lay.hideFooter && <Footer view={view} slide={slide} />}
      </div>
    </ThemeCtx.Provider>
  );
}

function Footer({ view, slide }: { view: PresentationView; slide: ViewSlide }) {
  const t = useTheme();
  const f = t.layout.footer;
  return (
    <footer className="slide-footer" data-el="footer" style={{ left: f.x, width: f.w, bottom: f.bottom }}>
      {t.footer.items.map((item) => {
        if (item === 'owner_competence')
          return (
            <span key={item} data-el="footer-owner">
              {view.owner.name} · {view.competence.competence}
            </span>
          );
        if (item === 'source')
          return (
            <span key={item} data-testid="slide-source" data-el="footer-source">
              Fonte: revisão aprovada {view.sources.primary.revision} (aprovação {view.sources.primary.approval_sequence})
            </span>
          );
        if (item === 'provisional')
          return t.provisional ? (
            <span key={item} className="slide-provisional" data-el="footer-provisional">
              Tema provisório
            </span>
          ) : null;
        if (item === 'custom_text')
          return (
            <span key={item} data-el="footer-custom">
              {t.footer.custom_text}
            </span>
          );
        return (
          <span key={item} data-el="footer-page">
            {slide.index}/{view.slides.length}
          </span>
        );
      })}
    </footer>
  );
}

function Header({ slide }: { slide: ViewSlide }) {
  return (
    <div className="slide-header" data-el="header">
      <h2 className="slide-title" data-el="title">
        {slide.fields.title}
      </h2>
      {slide.fields.subtitle && (
        <p className="slide-subtitle" data-el="subtitle">
          {slide.fields.subtitle}
        </p>
      )}
    </div>
  );
}

/** Regiões do tema: `flow` = título+conteúdo empilhados em `body`; `fixed` = título em `header`, conteúdo em `content`. */
function ContentFrame({ slide, lay, children }: { slide: ViewSlide; lay: ResolvedLayout; children: React.ReactNode }) {
  if (lay.mode === 'fixed' && lay.header && lay.content)
    return (
      <>
        <div className="slide-header-box" style={boxStyle(lay.header)}>
          <Header slide={slide} />
        </div>
        <div className="slide-content" style={boxStyle(lay.content)}>
          {children}
        </div>
      </>
    );
  return (
    <div className="slide-content" style={boxStyle(lay.body)}>
      <Header slide={slide} />
      {children}
    </div>
  );
}

function Caption({ slide }: { slide: ViewSlide }) {
  return slide.fields.caption ? (
    <p className="slide-caption" data-el="caption">
      {slide.fields.caption}
    </p>
  ) : null;
}

function SlideBody({ view, slide, lay }: { view: PresentationView; slide: ViewSlide; lay: ResolvedLayout }) {
  const d = slide.data;
  switch (slide.type) {
    case 'cover':
      return <Cover slide={slide} data={d as CoverData} />;
    case 'closing':
      return <Closing slide={slide} data={d as CoverData} />;
    case 'recommendations':
      return <Recommendations slide={slide} lay={lay} />;
    case 'executive_summary':
      return (
        <ContentFrame slide={slide} lay={lay}>
          <div className={`summary-layout ${slide.layout}`}>
            <div className="summary-text">
              {slide.fields.body && <Paragraphs text={slide.fields.body} />}
              {slide.fields.items.length > 0 && (
                <ul className="slide-bullets" data-el="bullets">
                  {slide.fields.items.map((it, i) => (
                    <li key={i}>{it}</li>
                  ))}
                </ul>
              )}
            </div>
            {d && slide.layout !== 'text-only' && <Kpis data={d as IRKpi} compact />}
          </div>
          <Caption slide={slide} />
        </ContentFrame>
      );
    default:
      return (
        <ContentFrame slide={slide} lay={lay}>
          <div className={`slide-main ${slide.layout === 'chart-with-text' ? 'with-text' : ''}`}>
            <div className="slide-visual" data-el="visual">
              {renderData(d, slide)}
            </div>
            {slide.layout === 'chart-with-text' && slide.fields.body && (
              <div className="slide-side" data-el="side">
                <Paragraphs text={slide.fields.body} />
              </div>
            )}
          </div>
          <Caption slide={slide} />
        </ContentFrame>
      );
  }
}

function renderData(d: SlideData, slide: ViewSlide) {
  if (!d) return <Unavailable message="Sem dados vinculados" />;
  if ('available' in d && d.available === false) return <Unavailable message={(d as IRUnavailable).message} />;
  const withText = slide.layout === 'chart-with-text';
  switch ((d as { kind: string }).kind) {
    case 'kpi':
      return <Kpis data={d as IRKpi} />;
    case 'comparison':
      return <Comparison data={d as IRComparison} layout={slide.layout} />;
    case 'bar':
      return <BarChart data={d as IRChart} withText={withText} />;
    case 'line':
      return <LineChart data={d as IRChart} withText={withText} />;
    case 'severity':
      return <SeverityChart data={d as IRChart} />;
    case 'ranking':
      return <Ranking data={d as IRRanking} bars={slide.layout === 'ranking-bars'} />;
    case 'table':
      return <MetricTable data={d as IRTable} />;
    default:
      return <Unavailable message="Tipo de dado não suportado pelo renderizador" />;
  }
}

const Paragraphs = ({ text }: { text: string }) => (
  <>
    {text.split(/\n{2,}/).map((p, i) => (
      <p key={i} className="slide-text" data-el={`body:${i + 1}`}>
        {p}
      </p>
    ))}
  </>
);

const Unavailable = ({ message }: { message: string }) => (
  <div className="slide-unavailable" role="note" data-testid="slide-unavailable" data-el="unavailable">
    <strong>Dado indisponível</strong>
    <span>{message}</span>
    <small>Nenhum número é presumido. Correções de indicadores: nova revisão em Competências (F05).</small>
  </div>
);

// Proveniência por elemento (atributo invisível): indicador, competência, estado e origem do valor aprovado. Serve ao
// manifesto visual e, na F07, ao texto alternativo dos objetos nativos do PPTX.
function provenance(p: { metric_id: string; competence?: string | null; state?: string; origin?: string | null }): string {
  return [p.metric_id, p.competence ?? '', p.state ?? '', p.origin ?? ''].join('|');
}

function Presenters({ list }: { list: { name: string; role?: string | null }[] }) {
  if (!list.length) return null;
  return (
    <ul className="slide-presenters" aria-label="Apresentadores" data-el="presenters">
      {list.map((p, i) => (
        <li key={i}>
          <strong>{p.name}</strong>
          {p.role ? ` — ${p.role}` : ''}
        </li>
      ))}
    </ul>
  );
}

function Cover({ slide, data }: { slide: ViewSlide; data: CoverData }) {
  const t = useTheme();
  return (
    <div className="slide-cover">
      {t.cover.band !== 'none' && <div className="cover-band" data-el="cover-band" />}
      <div className="cover-body">
        <p className="cover-kicker" data-el="cover-kicker">
          {data.owner}
        </p>
        <h1 className="cover-title" data-el="title">
          {slide.fields.title}
        </h1>
        {slide.fields.subtitle && (
          <p className="cover-subtitle" data-el="subtitle">
            {slide.fields.subtitle}
          </p>
        )}
        <p className="cover-competence" data-testid="cover-competence" data-el="cover-competence">
          Competência {data.competence} · {data.period_label ?? `${data.period.period_start} a ${data.period.period_end_inclusive}`}
        </p>
        <Presenters list={data.presenters} />
      </div>
    </div>
  );
}

function Closing({ slide, data }: { slide: ViewSlide; data: CoverData }) {
  return (
    <div className="slide-closing">
      <h1 className="cover-title" data-el="title">
        {slide.fields.title}
      </h1>
      {slide.fields.subtitle && (
        <p className="cover-subtitle" data-el="subtitle">
          {slide.fields.subtitle}
        </p>
      )}
      {slide.fields.body && <Paragraphs text={slide.fields.body} />}
      <Presenters list={data.presenters} />
    </div>
  );
}

function Recommendations({ slide, lay }: { slide: ViewSlide; lay: ResolvedLayout }) {
  const items = slide.fields.items;
  const half = Math.ceil(items.length / 2);
  const cols = slide.layout === 'two-columns' ? [items.slice(0, half), items.slice(half)] : [items];
  return (
    <ContentFrame slide={slide} lay={lay}>
      {slide.fields.body && <Paragraphs text={slide.fields.body} />}
      <div className="reco-columns">
        {cols.map((col, i) => (
          <ul key={i} className="slide-bullets" data-el={`bullets:${i + 1}`}>
            {col.map((it, j) => (
              <li key={j}>{it}</li>
            ))}
          </ul>
        ))}
      </div>
      {!items.length && !slide.fields.body && (
        <p className="slide-text muted-ink" data-el="empty">
          Sem recomendações registradas.
        </p>
      )}
    </ContentFrame>
  );
}

const StateTag = ({ p }: { p: { state: string; origin: string | null } }) => (
  <>
    {p.origin === 'MANUAL' && (
      <span className="tag tag-manual" title="Valor manual justificado, aprovado na F05">
        Manual
      </span>
    )}
    {p.state !== 'VALUE' && p.state !== 'NOT_NUMERIC' && <span className="tag tag-gap">{p.state === 'GAP' ? 'Lacuna' : p.state === 'INCOMPATIBLE' ? 'Incompatível' : 'Ausente'}</span>}
  </>
);

function Kpis({ data, compact }: { data: IRKpi; compact?: boolean }) {
  return (
    <div className={`kpi-grid ${compact ? 'compact' : ''} n${data.items.length}`}>
      {data.items.map((k) => (
        <div key={k.metric_id} className={`kpi state-${k.state}`} data-testid={`kpi-${k.metric_id}`} data-el={`kpi:${k.metric_id}`} data-provenance={provenance(k)}>
          <span className="kpi-name" data-el={`kpi-name:${k.metric_id}`}>
            {k.name}
          </span>
          <span className="kpi-value" data-el={`kpi-value:${k.metric_id}`}>
            {k.label}
          </span>
          <span className="kpi-unit" data-el={`kpi-unit:${k.metric_id}`}>
            {k.state === 'VALUE' ? k.unit_label : 'valor indisponível na revisão aprovada'} <StateTag p={k} />
          </span>
        </div>
      ))}
    </div>
  );
}

function Comparison({ data, layout }: { data: IRComparison; layout: string }) {
  const reason: Record<string, string> = {
    gap: 'lacuna',
    no_numeric_value: 'sem número',
    value_type_changed: 'tipo mudou',
    contract_version_changed: 'contrato mudou',
  };
  if (layout === 'comparison-cards')
    return (
      <div className="kpi-grid">
        {data.rows.map((r) => (
          <div key={r.metric_id} className="kpi" data-testid={`cmp-${r.metric_id}`} data-el={`cmp:${r.metric_id}`} data-provenance={provenance(r.current)}>
            <span className="kpi-name" data-el={`cmp-name:${r.metric_id}`}>
              {r.name}
            </span>
            <span className="kpi-value" data-el={`cmp-value:${r.metric_id}`}>
              {r.current.label}
            </span>
            <span className="kpi-unit" data-el={`cmp-detail:${r.metric_id}`}>
              {data.previous_competence}: {r.previous.label} · variação {r.delta_label ?? `— (${reason[r.delta_unavailable_reason ?? ''] ?? '—'})`}
            </span>
          </div>
        ))}
      </div>
    );
  return (
    <table className="slide-table" aria-label="Comparação com o mês anterior" data-el="comparison">
      <thead>
        <tr>
          <th>Indicador</th>
          <th>{data.previous_competence}</th>
          <th>{data.current_competence}</th>
          <th>Variação</th>
        </tr>
      </thead>
      <tbody>
        {data.rows.map((r) => (
          <tr key={r.metric_id} data-testid={`cmp-${r.metric_id}`} data-el={`cmp:${r.metric_id}`} data-provenance={provenance(r.current)}>
            <td>{r.name}</td>
            <td>
              {r.previous.label} <StateTag p={r.previous} />
            </td>
            <td>
              {r.current.label} <StateTag p={r.current} />
            </td>
            <td>{r.delta_label ?? `— (${reason[r.delta_unavailable_reason ?? ''] ?? '—'})`}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ---------------------------------------------------------------- SVG (geometria = tokens `charts` do tema)

function niceMax(values: number[]): number {
  const max = Math.max(0, ...values);
  if (max === 0) return 1;
  const exp = Math.pow(10, Math.floor(Math.log10(max)));
  const f = max / exp;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * exp;
}

type Plot = { w: number; h: number; left: number; right: number; top: number; bottom: number };

function usePlot(withText: boolean): Plot {
  const c = useTheme().charts;
  const p = c.plot_padding;
  return { w: withText ? c.plot_width_with_text : c.plot_width, h: c.plot_height, left: p.left, right: p.right, top: p.top, bottom: p.bottom };
}

function Axes({ plot, max, label, integer }: { plot: Plot; max: number; label: string; integer: boolean }) {
  const c = useTheme().charts;
  const ticks = Array.from({ length: c.y_ticks + 1 }, (_, i) => (i / c.y_ticks) * max);
  const ih = plot.h - plot.top - plot.bottom;
  return (
    <g className="axes">
      {ticks.map((t) => {
        const y = plot.top + ih - (t / max) * ih;
        const text = integer && !Number.isInteger(t) ? '' : t.toLocaleString('pt-BR', { maximumFractionDigits: 2 });
        return (
          <g key={t}>
            <line x1={plot.left} x2={plot.w - plot.right} y1={y} y2={y} stroke={colorVar('grid')} strokeWidth={c.grid_width} />
            <text x={plot.left - c.axis_label_offset} y={y + c.axis_label_baseline} textAnchor="end" className="axis-text">
              {text}
            </text>
          </g>
        );
      })}
      <line x1={plot.left} x2={plot.w - plot.right} y1={plot.top + ih} y2={plot.top + ih} stroke={colorVar('axis')} strokeWidth={c.grid_width} />
      <text x={plot.left} y={c.unit_label_y} className="axis-text">
        {label}
      </text>
    </g>
  );
}

function Legend({ data }: { data: IRChart }) {
  if (!data.legend.show) return null;
  return (
    <ul className="chart-legend" aria-label={data.legend.title ?? 'Legenda'} data-el="legend">
      {data.legend.title && <li className="legend-title">{data.legend.title}</li>}
      {data.series.map((s) => (
        <li key={s.key}>
          <span className="swatch" style={{ background: colorVar(s.color) }} />
          {s.label}
        </li>
      ))}
    </ul>
  );
}

function ChartFrame({ data, children }: { data: IRChart; children: React.ReactNode }) {
  const bottom = useTheme().charts.legend_position === 'bottom';
  return (
    <figure className="slide-chart" data-el="chart">
      {data.title && (
        <figcaption className="chart-title" data-el="chart-title">
          {data.title}
        </figcaption>
      )}
      {!bottom && <Legend data={data} />}
      {children}
      {bottom && <Legend data={data} />}
      {data.gaps.length > 0 && (
        <p className="chart-note" data-testid="chart-gaps" data-el="chart-gaps">
          Lacunas (sem revisão aprovada): {data.gaps.join(', ')} — sem interpolação.
        </p>
      )}
      {(data.warnings ?? []).map((w) => (
        <p key={w.code} className="chart-note" data-el={`chart-note:${w.code}`}>
          {w.message}
        </p>
      ))}
    </figure>
  );
}

function BarChart({ data, withText }: { data: IRChart; withText: boolean }) {
  const t = useTheme();
  const c = t.charts;
  const plot = usePlot(withText);
  const s = data.series[0];
  if (!s || data.empty) return <Unavailable message="Distribuição aprovada sem itens" />;
  const max = niceMax(s.points.map((p) => p.y ?? 0));
  const ih = plot.h - plot.top - plot.bottom;
  const iw = plot.w - plot.left - plot.right;
  const step = iw / s.points.length;
  const bw = Math.min(c.bar_max_width, step * c.bar_width_ratio);
  const font = axisFont(t);
  const months = data.x_axis.type === 'month';
  const every = months ? monthLabelEvery(s.points.map((p) => p.x), step, font, c.axis_label_min_gap) : 1;
  return (
    <ChartFrame data={data}>
      <svg viewBox={`0 0 ${plot.w} ${plot.h}`} className="chart-svg" role="img" aria-label={data.title ?? s.label} data-el="plot">
        <Axes plot={plot} max={max} label={data.y_axis.label} integer={data.y_axis.integer} />
        {s.points.map((p, i) => {
          const cx = plot.left + step * i + step / 2;
          const has = p.y !== null;
          const h = has ? Math.max(c.min_bar, ((p.y as number) / max) * ih) : ih * c.gap_bar_ratio;
          const y = plot.top + ih - h;
          return (
            <g key={p.x} data-testid={`bar-${p.x}`} data-el={`bar:${p.x}`} data-provenance={provenance(p)}>
              <title>{`${p.x}: ${p.label}${p.origin === 'MANUAL' ? ' (manual)' : ''}`}</title>
              {has ? (
                <rect x={cx - bw / 2} y={y} width={bw} height={h} rx={c.bar_radius} fill={colorVar(p.color ?? s.color)} />
              ) : (
                <rect x={cx - bw / 2} y={y} width={bw} height={h} rx={c.bar_radius} fill="none" stroke={colorVar('gap')} strokeDasharray={c.gap_dash} />
              )}
              {(data.show_values !== false || !has) && (
                <text x={cx} y={y - c.value_label_offset} textAnchor="middle" className="value-text">
                  {p.label}
                </text>
              )}
              <text x={cx} y={plot.h - plot.bottom + c.category_label_offset} textAnchor="middle" className="axis-text">
                {months ? (showMonth(i, s.points.length, every) ? p.x : '') : fitLabel(p.x, step - c.axis_label_min_gap, font)}
              </text>
            </g>
          );
        })}
      </svg>
    </ChartFrame>
  );
}

// Largura REAL do texto na fonte do eixo (mesma pilha e tamanho do SVG), medida pelo navegador: a decisão de
// rarefazer/truncar rótulos acompanha a fonte efetiva de cada plataforma (ex.: Segoe UI × DejaVu Sans).
let measureCtx: CanvasRenderingContext2D | null | undefined;
function textWidth(text: string, font: string): number {
  if (measureCtx === undefined) measureCtx = document.createElement('canvas').getContext('2d');
  if (!measureCtx) return text.length * parseFloat(font) * 0.6; // sem canvas (não ocorre no Chromium)
  measureCtx.font = font;
  return measureCtx.measureText(text).width;
}
const axisFont = (t: Theme) => `${t.sizes.axis}px ${fontStack(t.fonts.body)}`;

/** Categoria longa: maior prefixo que cabe + "…" (o nome completo fica no <title> do elemento). */
function fitLabel(label: string, maxWidth: number, font: string): string {
  if (textWidth(label, font) <= maxWidth) return label;
  for (let n = label.length - 1; n > 3; n--) if (textWidth(`${label.slice(0, n)}…`, font) <= maxWidth) return `${label.slice(0, n)}…`;
  return `${label.slice(0, 3)}…`;
}

/** Eixo de MESES: em vez de truncar ("202…"), mostra um rótulo a cada N meses (sempre o último). */
function monthLabelEvery(labels: string[], slotWidth: number, font: string, gap: number): number {
  const widest = Math.max(1, ...labels.map((l) => textWidth(l, font)));
  return Math.max(1, Math.ceil((widest + gap) / slotWidth));
}
const showMonth = (i: number, n: number, every: number) => (n - 1 - i) % every === 0;

function LineChart({ data, withText }: { data: IRChart; withText: boolean }) {
  const t = useTheme();
  const c = t.charts;
  const plot = usePlot(withText);
  const all = data.series.flatMap((s) => s.points.map((p) => p.y ?? 0));
  const max = niceMax(all);
  const ih = plot.h - plot.top - plot.bottom;
  const iw = plot.w - plot.left - plot.right;
  const n = data.categories.length;
  const x = (i: number) => plot.left + (n === 1 ? iw / 2 : (iw * i) / (n - 1));
  const y = (v: number) => plot.top + ih - (v / max) * ih;
  const every = monthLabelEvery(data.categories, iw / Math.max(1, n), axisFont(t), c.axis_label_min_gap);
  // Segmentos só entre meses CONSECUTIVOS com valor: lacuna quebra a linha (sem interpolação).
  const segments = (pts: IRPoint[]) => {
    const out: string[] = [];
    let cur: string[] = [];
    pts.forEach((p, i) => {
      if (p.y === null) {
        if (cur.length > 1) out.push(cur.join(' '));
        cur = [];
      } else cur.push(`${x(i)},${y(p.y)}`);
    });
    if (cur.length > 1) out.push(cur.join(' '));
    return out;
  };
  return (
    <ChartFrame data={data}>
      <svg viewBox={`0 0 ${plot.w} ${plot.h}`} className="chart-svg" role="img" aria-label={data.title ?? 'Série histórica'} data-el="plot">
        <Axes plot={plot} max={max} label={data.y_axis.label} integer={data.y_axis.integer} />
        {data.categories.map((cat, i) => (
          <text key={cat} x={x(i)} y={plot.h - plot.bottom + c.category_label_offset} textAnchor="middle" className="axis-text">
            {showMonth(i, n, every) ? cat : ''}
          </text>
        ))}
        {data.categories.map((cat, i) =>
          data.series.every((s) => s.points[i].state === 'GAP') ? (
            <g key={`gap-${cat}`} data-testid={`gap-${cat}`}>
              <line x1={x(i)} x2={x(i)} y1={plot.top} y2={plot.top + ih} stroke={colorVar('gap')} strokeDasharray={c.gap_line_dash} />
              <text x={x(i)} y={plot.top + c.gap_label_y_offset} textAnchor="middle" className="gap-text">
                lacuna
              </text>
            </g>
          ) : null,
        )}
        {data.series.map((s) => (
          <g key={s.key} data-testid={`series-${s.key}`}>
            {segments(s.points).map((pts, i) => (
              <polyline key={i} points={pts} fill="none" stroke={colorVar(s.color)} strokeWidth={c.line_width} strokeLinejoin="round" />
            ))}
            {s.points.map((p, i) =>
              p.y === null ? null : (
                <g key={p.x} data-testid={`pt-${s.key}-${p.x}`} data-el={`point:${s.key}:${p.x}`} data-provenance={provenance(p)}>
                  <title>{`${s.label} · ${p.x}: ${p.label}${p.origin === 'MANUAL' ? ' (manual)' : ''}`}</title>
                  <circle cx={x(i)} cy={y(p.y)} r={c.point_radius} fill={colorVar(s.color)} stroke={colorVar('surface')} strokeWidth={c.point_stroke} />
                  {data.show_values !== false && (
                    <text x={x(i)} y={y(p.y) - c.point_label_offset} textAnchor="middle" className="value-text">
                      {p.label}
                    </text>
                  )}
                </g>
              ),
            )}
          </g>
        ))}
      </svg>
    </ChartFrame>
  );
}

function SeverityChart({ data }: { data: IRChart }) {
  const s = data.series[0];
  const max = Math.max(1, ...s.points.map((p) => p.y ?? 0));
  return (
    <figure className="slide-chart" data-el="chart">
      {data.title && (
        <figcaption className="chart-title" data-el="chart-title">
          {data.title}
        </figcaption>
      )}
      <div className="sev-rows" role="list" aria-label={data.title ?? 'Distribuição por severidade'}>
        {s.points.map((p) => (
          <div key={p.x} className="sev-row" role="listitem" data-testid={`sev-${p.x}`} data-el={`sev:${p.x}`} data-provenance={provenance(p)} title={`${p.x}: ${p.label}`}>
            <span className="sev-name">
              <span className="swatch" style={{ background: colorVar(p.color ?? 'series.1') }} />
              {p.x}
            </span>
            <span className="sev-track">
              <span
                className={`sev-bar ${p.x === 'Desconhecida' ? 'textured' : ''}`}
                style={{ width: `${((p.y ?? 0) / max) * 100}%`, background: colorVar(p.color ?? 'series.1') }}
              />
            </span>
            {data.show_values !== false && <span className="sev-value">{p.label}</span>}
          </div>
        ))}
      </div>
      {data.total && (
        <p className="chart-note" data-testid="sev-total" data-el="sev-total">
          Total: {data.total.label} {data.series[0].points[0]?.origin === 'MANUAL' ? '· valor manual aprovado' : ''}
        </p>
      )}
    </figure>
  );
}

function Ranking({ data, bars }: { data: IRRanking; bars: boolean }) {
  const c = useTheme().charts;
  if (data.empty) return <Unavailable message="Ranking aprovado sem itens" />;
  const extras = data.columns.slice(3);
  return (
    <figure className="slide-chart" data-el="chart">
      {data.title && (
        <figcaption className="chart-title" data-el="chart-title">
          {data.title}
        </figcaption>
      )}
      <table className="slide-table ranking" aria-label={data.title ?? 'Ranking'} data-el="ranking">
        <thead>
          <tr>
            {data.columns.map((col) => (
              <th key={col}>{col}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((r) => (
            <tr key={r.rank} data-testid={`rank-${r.rank}`} data-el={`rank:${r.rank}`}>
              <td>{r.rank}</td>
              <td>{r.label}</td>
              <td className="num">
                {bars && <span className="rank-bar" style={{ width: `${(r.y / Math.max(1, data.max_y)) * c.rank_bar_max}px`, background: colorVar('series.1') }} />}
                {data.show_values !== false ? r.value : ''}
              </td>
              {extras.map((k) => (
                <td key={k}>{String(r.extra[k] ?? '—')}</td>
              ))}
            </tr>
          ))}
          {data.aggregate_rows.map((r) => (
            <tr key={r.label} className="aggregate">
              <td />
              <td>{r.label}</td>
              <td className="num">{r.value}</td>
              {extras.map((k) => (
                <td key={k} />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}

function MetricTable({ data }: { data: IRTable }) {
  return (
    <table className="slide-table" aria-label="Tabela de indicadores" data-el="table">
      <thead>
        <tr>
          <th>Indicador</th>
          <th>Valor</th>
          <th>Estado</th>
          <th>Origem</th>
          <th>Fonte</th>
        </tr>
      </thead>
      <tbody>
        {data.rows.map((r) => (
          <tr key={r.metric_id} data-testid={`row-${r.metric_id}`} data-el={`row:${r.metric_id}`} data-provenance={provenance(r)}>
            <td>{r.name}</td>
            <td className="num">
              {r.value} {r.state === 'VALUE' ? r.unit_label : ''}
            </td>
            <td>{r.value_state ?? '—'}</td>
            <td>{r.origin === 'MANUAL' ? 'Manual' : r.origin === 'VERACODE' ? 'Veracode' : '—'}</td>
            <td>{r.source ?? '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
