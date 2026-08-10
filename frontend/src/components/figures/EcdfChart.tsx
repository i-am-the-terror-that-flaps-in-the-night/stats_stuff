// Cumulative share — what fraction of the column sits at or below a value.
//
// The histogram next door answers "where is the mass?". This answers "where do I
// stand?", which is the question a clinical cutoff actually asks: 150 mg/dL is
// meaningless until you know that 78% of the sample is under it. Reading that off
// a histogram means adding bar heights by eye; here it is one number, and the
// chart is built so you can get it for ANY value, not just the ones the engine
// happened to pick a threshold for.
//
// WHY THIS IS A CURVE YOU POINT AT
//   Every other figure on the page has a fixed set of marks, so hovering a mark
//   is enough. A cumulative curve is continuous -- the interesting value is
//   usually between two bin edges -- so the whole plot is the hit area. Moving
//   the pointer moves a crosshair and reads the curve at that x, which is the
//   interaction the shape is asking for.
//
// WHAT IT IS NOT
//   Not the exact empirical CDF. The server sends bins, not the 9,254 raw
//   values, so this rises linearly ACROSS each bin instead of stepping at each
//   observation. Inside a bin the reading is an interpolation, and the footnote
//   says so. Getting the exact curve would mean shipping every value to the
//   browser, which costs far more than the precision is worth at this width --
//   a bin is a couple of pixels wide.

import { useState } from "react";
import type { JSX } from "react";
import type { HistogramResponse } from "../../types/engine";
import { formatCount, formatTick, labelOf, linearScale, plotArea, ticks } from "../../lib/scales";
import { AxisLabel, GridLine, Tooltip, useNarrowChart, useTooltip } from "./ChartFrame";
import type { Layout } from "./ChartFrame";

// Two coordinate spaces, one per breakpoint — see useNarrowChart for why a
// single viewBox cannot serve both.
const WIDE: Layout = { W: 720, H: 340, margin: { top: 18, right: 20, bottom: 44, left: 54 } };
const NARROW: Layout = { W: 360, H: 260, margin: { top: 14, right: 12, bottom: 40, left: 40 } };

/** One vertex of the cumulative curve: the share of values at or below `value`. */
interface Step {
  value: number;
  share: number;
}

/**
 * Turn bin counts into a running total.
 *
 * Starts at (first bin's lower edge, 0) so the curve leaves the floor at the
 * column's minimum rather than appearing mid-air at the first bin's top edge.
 */
function cumulative(data: HistogramResponse): Step[] {
  const first = data.bins[0]?.lo ?? data.min;
  const steps: Step[] = [{ value: first, share: 0 }];
  let running = 0;
  for (const bin of data.bins) {
    running += bin.count;
    steps.push({ value: bin.hi, share: data.n > 0 ? running / data.n : 0 });
  }
  return steps;
}

/**
 * Read the curve at an arbitrary value, interpolating between vertices.
 *
 * Clamps outside the data range: below the minimum nothing is at or below you
 * (0), above the maximum everything is (1). Both are true statements about this
 * sample, and clamping keeps the readout from running past 100%.
 */
function shareAt(steps: Step[], value: number): number {
  const first = steps[0];
  const last = steps[steps.length - 1];
  if (!first || !last) return 0;
  if (value <= first.value) return 0;
  if (value >= last.value) return 1;

  for (let i = 1; i < steps.length; i++) {
    const a = steps[i - 1];
    const b = steps[i];
    if (!a || !b || value > b.value) continue;
    const span = b.value - a.value;
    // A zero-width bin cannot be interpolated across; take its top.
    if (span <= 0) return b.share;
    return a.share + ((value - a.value) / span) * (b.share - a.share);
  }
  return 1;
}

export function EcdfChart({ data }: { data: HistogramResponse }): JSX.Element {
  const { tip, show, hide } = useTooltip();
  // Where the crosshair sits, in DATA space. Null means the pointer is away and
  // the chart shows only its fixed quartile marks.
  const [cursor, setCursor] = useState<number | null>(null);
  const { W, H, margin: MARGIN } = useNarrowChart() ? NARROW : WIDE;
  const plot = plotArea(W, H, MARGIN);

  const steps = cumulative(data);
  const lo = steps[0]?.value ?? data.min;
  const hi = steps[steps.length - 1]?.value ?? data.max;
  const x = linearScale([lo, hi], [plot.left, plot.right]);
  const y = linearScale([0, 1], [plot.bottom, plot.top]);

  const path = steps.map((s, i) => `${i === 0 ? "M" : "L"}${x(s.value)} ${y(s.share)}`).join(" ");
  // The area under the curve. Not decoration: it is what makes "share BELOW this
  // point" readable as a quantity rather than a line that happens to rise.
  const area = `${path} L${x(hi)} ${plot.bottom} L${x(lo)} ${plot.bottom} Z`;

  const quartiles: [string, number, number][] = [
    ["25th percentile", data.q1, 0.25],
    ["Median", data.median, 0.5],
    ["75th percentile", data.q3, 0.75],
  ];

  /** Pointer → a value on the x axis, from the hit rect's own box. */
  function readCursor(event: { clientX: number; currentTarget: Element }): number {
    const box = event.currentTarget.getBoundingClientRect();
    const withinPlot = box.width > 0 ? (event.clientX - box.left) / box.width : 0;
    return x.invert(plot.left + withinPlot * plot.innerWidth);
  }

  const cursorShare = cursor === null ? null : shareAt(steps, cursor);

  return (
    <>
      <svg
        className="fig-svg"
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`Cumulative share of ${labelOf(data.column)} across ${formatCount(data.n)} values`}
      >
        {/* Horizontal guides every 25%: the quartile lines you read across to. */}
        {[0, 0.25, 0.5, 0.75, 1].map((share) => (
          <g key={share}>
            <GridLine x1={plot.left} x2={plot.right} y1={y(share)} y2={y(share)} />
            <AxisLabel x={plot.left - 8} y={y(share) + 4} anchor="end">
              {`${Math.round(share * 100)}%`}
            </AxisLabel>
          </g>
        ))}

        <path className="fig-band" d={area} />
        {/* fill="none" as an attribute, not CSS: .fig-line is a stroke class
            shared with SampleSizeChart's polyline, which does the same. */}
        <path className="fig-line" d={path} fill="none" />

        {/* Quartile drops. Fixed marks, so the chart still says something with no
            pointer on it. The median gets the solid ink rule every figure here
            uses for it; Q1 and Q3 get their own recessive class -- bare
            `.fig-ref` sets a stroke WIDTH and no stroke, which in SVG paints
            nothing at all. */}
        {quartiles.map(([label, value, share]) => (
          <line
            key={label}
            className={share === 0.5 ? "fig-ref is-median" : "fig-ref is-quartile"}
            x1={x(value)}
            x2={x(value)}
            y1={y(share)}
            y2={plot.bottom}
          />
        ))}

        {cursor !== null && cursorShare !== null && (
          <g>
            <line
              className="fig-crosshair"
              x1={x(cursor)}
              x2={x(cursor)}
              y1={plot.top}
              y2={plot.bottom}
            />
            <line
              className="fig-crosshair"
              x1={plot.left}
              x2={x(cursor)}
              y1={y(cursorShare)}
              y2={y(cursorShare)}
            />
            <circle className="fig-dot is-cursor" cx={x(cursor)} cy={y(cursorShare)} r={5} />
          </g>
        )}

        <line className="fig-axis" x1={plot.left} x2={plot.right} y1={plot.bottom} y2={plot.bottom} />
        {ticks(lo, hi, W > 500 ? 6 : 4).map((t) => (
          <AxisLabel key={t} x={x(t)} y={plot.bottom + 16}>
            {formatTick(t)}
          </AxisLabel>
        ))}

        {/* The hit area is the whole plot, not the curve: see the header note. */}
        <rect
          className="fig-hit"
          x={plot.left}
          y={plot.top}
          width={plot.innerWidth}
          height={plot.innerHeight}
          onMouseMove={(event) => {
            const value = readCursor(event);
            setCursor(value);
            const share = shareAt(steps, value);
            show(event, {
              title: `${labelOf(data.column)} ${formatTick(value)}`,
              rows: [
                ["At or below", `${(share * 100).toFixed(1)}%`],
                ["Above", `${((1 - share) * 100).toFixed(1)}%`],
                ["People below", formatCount(Math.round(share * data.n))],
              ],
              note: "Interpolated inside a bin — see the note under the chart.",
            });
          }}
          onMouseLeave={() => {
            setCursor(null);
            hide();
          }}
        />

        <AxisLabel x={(plot.left + plot.right) / 2} y={H - 6} className="is-title">
          {labelOf(data.column)}
        </AxisLabel>
        <AxisLabel x={plot.left} y={plot.top - 5} anchor="start" className="is-title">
          Share at or below
        </AxisLabel>
      </svg>
      <Tooltip tip={tip} />
    </>
  );
}

/** The key. The curve and the quartile drops are the only encoded marks. */
export function EcdfLegend({ data }: { data: HistogramResponse }): JSX.Element {
  return (
    <>
      <span className="fig-key">
        <i className="fig-key-mark is-line" /> Cumulative share
      </span>
      <span className="fig-key">
        <i className="fig-key-mark is-medianline" /> Median {formatTick(data.median)}
      </span>
      <span className="fig-key">
        <i className="fig-key-mark is-quartile" /> Q1 {formatTick(data.q1)} · Q3{" "}
        {formatTick(data.q3)}
      </span>
      <span className="fig-key">Point anywhere to read a percentile</span>
    </>
  );
}
