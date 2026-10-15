import React, { useEffect, useRef, useState } from 'react';
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

// F06A — renderizador HTML da IR. Só DESENHA o que veio do backend (valores aprovados + rótulos já formatados);
// não calcula, soma nem interpola números. Escalas/grades são geometria do desenho, não dados.
// Cores = tokens do tema (CSS custom properties no canvas); trocar a marca = trocar o tema.

const W = 1280;
const H = 720;

const cssVar = (token: string) => `var(--c-${token.replace(/\./g, '-')})`;

export function themeStyle(theme: Theme): React.CSSProperties {
  const vars: Record<string, string> = {};
  for (const [k, v] of Object.entries(theme.colors)) vars[`--c-${k.replace(/\./g, '-')}`] = v;
  return { ...vars, fontFamily: theme.fonts.body } as React.CSSProperties;
}

// Escala o canvas fixo 1280×720 para a largura disponível, mantendo 16:9.
export function SlideCanvas({ view, slide, label }: { view: PresentationView; slide: ViewSlide; label?: string }) {
  const outer = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.5);
  useEffect(() => {
    const el = outer.current;
    if (!el) return;
    const update = () => setScale(el.clientWidth / W || 0.5);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return (
    <div ref={outer} className="slide-frame" style={{ height: H * scale }}>
      <div
        className={`slide slide-${slide.type} layout-${slide.layout}`}
        style={{ ...themeStyle(view.theme), transform: `scale(${scale})`, width: W, height: H }}
        role="group"
        aria-roledescription="slide"
        aria-label={label ?? `Slide ${slide.index} de ${view.slides.length}: ${slide.fields.title ?? slide.type_name}`}
        data-testid="slide-canvas"
      >
        <SlideBody view={view} slide={slide} />
        <footer className="slide-footer">
          <span>
            {view.owner.name} · {view.competence.competence}
          </span>
          <span data-testid="slide-source">
            Fonte: revisão aprovada {view.sources.primary.revision} (aprovação {view.sources.primary.approval_sequence})
          </span>
          <span className="slide-provisional">Tema provisório</span>
          <span>
            {slide.index}/{view.slides.length}
          </span>
        </footer>
      </div>
    </div>
  );
}

function Header({ slide }: { slide: ViewSlide }) {
  return (
    <div className="slide-header">
      <h2 className="slide-title">{slide.fields.title}</h2>
      {slide.fields.subtitle && <p className="slide-subtitle">{slide.fields.subtitle}</p>}
    </div>
  );
}

function Caption({ slide }: { slide: ViewSlide }) {
  return slide.fields.caption ? <p className="slide-caption">{slide.fields.caption}</p> : null;
}

function SlideBody({ view, slide }: { view: PresentationView; slide: ViewSlide }) {
  const d = slide.data;
  switch (slide.type) {
    case 'cover':
      return <Cover slide={slide} data={d as CoverData} />;
    case 'closing':
      return <Closing slide={slide} data={d as CoverData} />;
    case 'recommendations':
      return <Recommendations slide={slide} />;
    case 'executive_summary':
      return (
        <div className="slide-content">
          <Header slide={slide} />
          <div className={`summary-layout ${slide.layout}`}>
            <div className="summary-text">
              {slide.fields.body && <Paragraphs text={slide.fields.body} />}
              {slide.fields.items.length > 0 && (
                <ul className="slide-bullets">
                  {slide.fields.items.map((it, i) => (
                    <li key={i}>{it}</li>
                  ))}
                </ul>
              )}
            </div>
            {d && slide.layout !== 'text-only' && <Kpis data={d as IRKpi} compact />}
          </div>
          <Caption slide={slide} />
        </div>
      );
    default:
      return (
        <div className="slide-content">
          <Header slide={slide} />
          <div className={`slide-main ${slide.layout === 'chart-with-text' ? 'with-text' : ''}`}>
            <div className="slide-visual">{renderData(d, slide)}</div>
            {slide.layout === 'chart-with-text' && slide.fields.body && (
              <div className="slide-side">
                <Paragraphs text={slide.fields.body} />
              </div>
            )}
          </div>
          <Caption slide={slide} />
        </div>
      );
  }
}

function renderData(d: SlideData, slide: ViewSlide) {
  if (!d) return <Unavailable message="Sem dados vinculados" />;
  if ('available' in d && d.available === false) return <Unavailable message={(d as IRUnavailable).message} />;
  switch ((d as { kind: string }).kind) {
    case 'kpi':
      return <Kpis data={d as IRKpi} />;
    case 'comparison':
      return <Comparison data={d as IRComparison} layout={slide.layout} />;
    case 'bar':
      return <BarChart data={d as IRChart} />;
    case 'line':
      return <LineChart data={d as IRChart} />;
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
      <p key={i} className="slide-text">
        {p}
      </p>
    ))}
  </>
);

const Unavailable = ({ message }: { message: string }) => (
  <div className="slide-unavailable" role="note" data-testid="slide-unavailable">
    <strong>Dado indisponível</strong>
    <span>{message}</span>
    <small>Nenhum número é presumido. Correções de indicadores: nova revisão em Competências (F05).</small>
  </div>
);

function Presenters({ list }: { list: { name: string; role?: string | null }[] }) {
  if (!list.length) return null;
  return (
    <ul className="slide-presenters" aria-label="Apresentadores">
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
  return (
    <div className="slide-cover">
      <div className="cover-band" />
      <div className="cover-body">
        <p className="cover-kicker">{data.owner}</p>
        <h1 className="cover-title">{slide.fields.title}</h1>
        {slide.fields.subtitle && <p className="cover-subtitle">{slide.fields.subtitle}</p>}
        <p className="cover-competence" data-testid="cover-competence">
          Competência {data.competence} · {data.period.period_start} a {data.period.period_end_inclusive}
        </p>
        <Presenters list={data.presenters} />
      </div>
    </div>
  );
}

function Closing({ slide, data }: { slide: ViewSlide; data: CoverData }) {
  return (
    <div className="slide-closing">
      <h1 className="cover-title">{slide.fields.title}</h1>
      {slide.fields.subtitle && <p className="cover-subtitle">{slide.fields.subtitle}</p>}
      {slide.fields.body && <Paragraphs text={slide.fields.body} />}
      <Presenters list={data.presenters} />
    </div>
  );
}

function Recommendations({ slide }: { slide: ViewSlide }) {
  const items = slide.fields.items;
  const half = Math.ceil(items.length / 2);
  const cols = slide.layout === 'two-columns' ? [items.slice(0, half), items.slice(half)] : [items];
  return (
    <div className="slide-content">
      <Header slide={slide} />
      {slide.fields.body && <Paragraphs text={slide.fields.body} />}
      <div className="reco-columns">
        {cols.map((col, i) => (
          <ul key={i} className="slide-bullets">
            {col.map((it, j) => (
              <li key={j}>{it}</li>
            ))}
          </ul>
        ))}
      </div>
      {!items.length && !slide.fields.body && <p className="slide-text muted-ink">Sem recomendações registradas.</p>}
    </div>
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
        <div key={k.metric_id} className={`kpi state-${k.state}`} data-testid={`kpi-${k.metric_id}`}>
          <span className="kpi-name">{k.name}</span>
          <span className="kpi-value">{k.label}</span>
          <span className="kpi-unit">
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
          <div key={r.metric_id} className="kpi" data-testid={`cmp-${r.metric_id}`}>
            <span className="kpi-name">{r.name}</span>
            <span className="kpi-value">{r.current.label}</span>
            <span className="kpi-unit">
              {data.previous_competence}: {r.previous.label} · variação {r.delta_label ?? `— (${reason[r.delta_unavailable_reason ?? ''] ?? '—'})`}
            </span>
          </div>
        ))}
      </div>
    );
  return (
    <table className="slide-table" aria-label="Comparação com o mês anterior">
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
          <tr key={r.metric_id} data-testid={`cmp-${r.metric_id}`}>
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

// ---------------------------------------------------------------- SVG

function niceMax(values: number[]): number {
  const max = Math.max(0, ...values);
  if (max === 0) return 1;
  const exp = Math.pow(10, Math.floor(Math.log10(max)));
  const f = max / exp;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * exp;
}

const PLOT = { w: 1100, h: 400, left: 64, right: 24, top: 24, bottom: 56 };

function Axes({ max, label, integer }: { max: number; label: string; integer: boolean }) {
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => t * max);
  const ih = PLOT.h - PLOT.top - PLOT.bottom;
  return (
    <g className="axes">
      {ticks.map((t) => {
        const y = PLOT.top + ih - (t / max) * ih;
        const text = integer && !Number.isInteger(t) ? '' : t.toLocaleString('pt-BR', { maximumFractionDigits: 2 });
        return (
          <g key={t}>
            <line x1={PLOT.left} x2={PLOT.w - PLOT.right} y1={y} y2={y} stroke={cssVar('grid')} strokeWidth={1} />
            <text x={PLOT.left - 10} y={y + 5} textAnchor="end" className="axis-text">
              {text}
            </text>
          </g>
        );
      })}
      <line x1={PLOT.left} x2={PLOT.w - PLOT.right} y1={PLOT.top + ih} y2={PLOT.top + ih} stroke={cssVar('axis')} strokeWidth={1} />
      <text x={PLOT.left} y={14} className="axis-text">
        {label}
      </text>
    </g>
  );
}

function ChartFrame({ data, children }: { data: IRChart; children: React.ReactNode }) {
  return (
    <figure className="slide-chart">
      {data.title && <figcaption className="chart-title">{data.title}</figcaption>}
      {data.legend.show && (
        <ul className="chart-legend" aria-label={data.legend.title ?? 'Legenda'}>
          {data.legend.title && <li className="legend-title">{data.legend.title}</li>}
          {data.series.map((s) => (
            <li key={s.key}>
              <span className="swatch" style={{ background: cssVar(s.color) }} />
              {s.label}
            </li>
          ))}
        </ul>
      )}
      {children}
      {data.gaps.length > 0 && (
        <p className="chart-note" data-testid="chart-gaps">
          Lacunas (sem revisão aprovada): {data.gaps.join(', ')} — sem interpolação.
        </p>
      )}
      {(data.warnings ?? []).map((w) => (
        <p key={w.code} className="chart-note">
          {w.message}
        </p>
      ))}
    </figure>
  );
}

function BarChart({ data }: { data: IRChart }) {
  const s = data.series[0];
  if (!s || data.empty) return <Unavailable message="Distribuição aprovada sem itens" />;
  const max = niceMax(s.points.map((p) => p.y ?? 0));
  const ih = PLOT.h - PLOT.top - PLOT.bottom;
  const iw = PLOT.w - PLOT.left - PLOT.right;
  const step = iw / s.points.length;
  const bw = Math.min(56, step * 0.6);
  return (
    <ChartFrame data={data}>
      <svg viewBox={`0 0 ${PLOT.w} ${PLOT.h}`} className="chart-svg" role="img" aria-label={data.title ?? s.label}>
        <Axes max={max} label={data.y_axis.label} integer={data.y_axis.integer} />
        {s.points.map((p, i) => {
          const cx = PLOT.left + step * i + step / 2;
          const has = p.y !== null;
          const h = has ? Math.max(2, ((p.y as number) / max) * ih) : ih * 0.4;
          const y = PLOT.top + ih - h;
          return (
            <g key={p.x} data-testid={`bar-${p.x}`}>
              <title>{`${p.x}: ${p.label}${p.origin === 'MANUAL' ? ' (manual)' : ''}`}</title>
              {has ? (
                <rect x={cx - bw / 2} y={y} width={bw} height={h} rx={4} fill={cssVar(p.color ?? s.color)} />
              ) : (
                <rect x={cx - bw / 2} y={y} width={bw} height={h} rx={4} fill="none" stroke={cssVar('gap')} strokeDasharray="6 4" />
              )}
              {(data.show_values !== false || !has) && (
                <text x={cx} y={y - 8} textAnchor="middle" className="value-text">
                  {p.label}
                </text>
              )}
              <text x={cx} y={PLOT.h - PLOT.bottom + 22} textAnchor="middle" className="axis-text">
                {truncate(p.x, step / 8)}
              </text>
            </g>
          );
        })}
      </svg>
    </ChartFrame>
  );
}

const truncate = (s: string, n: number) => (s.length > Math.max(4, n) ? `${s.slice(0, Math.max(3, n - 1))}…` : s);

function LineChart({ data }: { data: IRChart }) {
  const all = data.series.flatMap((s) => s.points.map((p) => p.y ?? 0));
  const max = niceMax(all);
  const ih = PLOT.h - PLOT.top - PLOT.bottom;
  const iw = PLOT.w - PLOT.left - PLOT.right;
  const n = data.categories.length;
  const x = (i: number) => PLOT.left + (n === 1 ? iw / 2 : (iw * i) / (n - 1));
  const y = (v: number) => PLOT.top + ih - (v / max) * ih;
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
      <svg viewBox={`0 0 ${PLOT.w} ${PLOT.h}`} className="chart-svg" role="img" aria-label={data.title ?? 'Série histórica'}>
        <Axes max={max} label={data.y_axis.label} integer={data.y_axis.integer} />
        {data.categories.map((c, i) => (
          <text key={c} x={x(i)} y={PLOT.h - PLOT.bottom + 22} textAnchor="middle" className="axis-text">
            {c}
          </text>
        ))}
        {data.categories.map((c, i) =>
          data.series.every((s) => s.points[i].state === 'GAP') ? (
            <g key={`gap-${c}`} data-testid={`gap-${c}`}>
              <line x1={x(i)} x2={x(i)} y1={PLOT.top} y2={PLOT.top + ih} stroke={cssVar('gap')} strokeDasharray="4 6" />
              <text x={x(i)} y={PLOT.top + 14} textAnchor="middle" className="gap-text">
                lacuna
              </text>
            </g>
          ) : null,
        )}
        {data.series.map((s) => (
          <g key={s.key} data-testid={`series-${s.key}`}>
            {segments(s.points).map((pts, i) => (
              <polyline key={i} points={pts} fill="none" stroke={cssVar(s.color)} strokeWidth={2.5} strokeLinejoin="round" />
            ))}
            {s.points.map((p, i) =>
              p.y === null ? null : (
                <g key={p.x} data-testid={`pt-${s.key}-${p.x}`}>
                  <title>{`${s.label} · ${p.x}: ${p.label}${p.origin === 'MANUAL' ? ' (manual)' : ''}`}</title>
                  <circle cx={x(i)} cy={y(p.y)} r={6} fill={cssVar(s.color)} stroke={cssVar('surface')} strokeWidth={2} />
                  {data.show_values !== false && (
                    <text x={x(i)} y={y(p.y) - 12} textAnchor="middle" className="value-text">
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
    <figure className="slide-chart">
      {data.title && <figcaption className="chart-title">{data.title}</figcaption>}
      <div className="sev-rows" role="list" aria-label={data.title ?? 'Distribuição por severidade'}>
        {s.points.map((p) => (
          <div key={p.x} className="sev-row" role="listitem" data-testid={`sev-${p.x}`} title={`${p.x}: ${p.label}`}>
            <span className="sev-name">
              <span className="swatch" style={{ background: cssVar(p.color ?? 'series.1') }} />
              {p.x}
            </span>
            <span className="sev-track">
              <span
                className={`sev-bar ${p.x === 'Desconhecida' ? 'textured' : ''}`}
                style={{ width: `${((p.y ?? 0) / max) * 100}%`, background: cssVar(p.color ?? 'series.1') }}
              />
            </span>
            {data.show_values !== false && <span className="sev-value">{p.label}</span>}
          </div>
        ))}
      </div>
      {data.total && (
        <p className="chart-note" data-testid="sev-total">
          Total: {data.total.label} {data.series[0].points[0]?.origin === 'MANUAL' ? '· valor manual aprovado' : ''}
        </p>
      )}
    </figure>
  );
}

function Ranking({ data, bars }: { data: IRRanking; bars: boolean }) {
  if (data.empty) return <Unavailable message="Ranking aprovado sem itens" />;
  const extras = data.columns.slice(3);
  return (
    <figure className="slide-chart">
      {data.title && <figcaption className="chart-title">{data.title}</figcaption>}
      <table className="slide-table ranking" aria-label={data.title ?? 'Ranking'}>
        <thead>
          <tr>
            {data.columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((r) => (
            <tr key={r.rank} data-testid={`rank-${r.rank}`}>
              <td>{r.rank}</td>
              <td>{r.label}</td>
              <td className="num">
                {bars && (
                  <span className="rank-bar" style={{ width: `${(r.y / Math.max(1, data.max_y)) * 160}px`, background: cssVar('series.1') }} />
                )}
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
    <table className="slide-table" aria-label="Tabela de indicadores">
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
          <tr key={r.metric_id} data-testid={`row-${r.metric_id}`}>
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
