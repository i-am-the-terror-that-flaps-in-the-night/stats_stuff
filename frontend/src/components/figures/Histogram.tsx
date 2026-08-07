// Histogram — the shape of one column's distribution.
//
// The job is SHAPE, which is why this is bars and not the five numbers the
// engine already prints: mean 26.6 / median 25.8 tells you the middle, and
// nothing at all about the long right tail that pulled them apart. The mean and
// median are drawn ON the chart as reference lines precisely so the gap between
// them is visible as a distance rather than as arithmetic the reader has to do.

import type { JSX } from "react";
import type { HistogramResponse } from "../../types/engine";
import { formatCount, formatTick, labelOf, linearScale, niceDomain, plotArea, ticks } from "../../lib/scales";
import { AxisLabel, GridLine, Tooltip, useNarrowChart, useTooltip } from "./ChartFrame";
import type { Layout } from "./ChartFrame";

// Two coordinate spaces, one per breakpoint — see useNarrowChart for why a
// single viewBox cannot serve both.
const WIDE: Layout = { W: 720, H: 340, margin: { top: 16, right: 18, bottom: 44, left: 56 } };
const NARROW: Layout = { W: 360, H: 260, margin: { top: 14, right: 8, bottom: 40, left: 38 } };

export function Histogram({ data }: { data: HistogramResponse }): JSX.Element {
  const { tip, show, hide } = useTooltip();
  const { W, H, margin: MARGIN } = useNarrowChart() ? NARROW : WIDE;
  const plot = plotArea(W, H, MARGIN);

  const maxCount = Math.max(...data.bins.map((b) => b.count));
  const [yLo, yHi] = niceDomain(0, maxCount, 4);
  // The server always sends at least MIN_BINS bins, but the compiler cannot know
  // that, so the x-domain falls back to the column's own min/max rather than
  // reaching into a possibly-empty array.
  const first = data.bins[0]?.lo ?? data.min;
  const last = data.bins[data.bins.length - 1]?.hi ?? data.max;
  const x = linearScale([first, last], [plot.left, plot.right]);
  const y = linearScale([yLo, yHi], [plot.bottom, plot.top]);

  // A 1px gap between bars, taken off the right edge. Adjacent fills need a
  // surface-coloured separator or the bars read as one continuous mass and the
  // bin boundaries -- the entire point of a histogram -- disappear.
  const gap = 1;

  return (
    <>
      <svg className="fig-svg" viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label={`Distribution of ${labelOf(data.column)} across ${formatCount(data.n)} values`}>
        {ticks(yLo, yHi, 4).map((t) => (
          <g key={t}>
            <GridLine x1={plot.left} x2={plot.right} y1={y(t)} y2={y(t)} />
            <AxisLabel x={plot.left - 8} y={y(t) + 4} anchor="end">
              {formatTick(t)}
            </AxisLabel>
          </g>
        ))}

        {data.bins.map((bin) => {
          const left = x(bin.lo);
          const width = Math.max(0.5, x(bin.hi) - left - gap);
          const top = y(bin.count);
          return (
            <rect
              key={bin.lo}
              className="fig-bar"
              x={left}
              y={top}
              width={width}
              height={Math.max(0, plot.bottom - top)}
              onMouseMove={(event) =>
                show(event, {
                  title: `${formatTick(bin.lo)} – ${formatTick(bin.hi)}`,
                  rows: [
                    ["Count", formatCount(bin.count)],
                    ["Share", `${((bin.count / data.n) * 100).toFixed(1)}%`],
                  ],
                })
              }
              onMouseLeave={hide}
            />
          );
        })}

        {/* Reference lines last, so they sit over the bars they annotate. */}
        <line className="fig-ref is-median" x1={x(data.median)} x2={x(data.median)}
              y1={plot.top} y2={plot.bottom} />
        <line className="fig-ref is-mean" x1={x(data.mean)} x2={x(data.mean)}
              y1={plot.top} y2={plot.bottom} />

        <line className="fig-axis" x1={plot.left} x2={plot.right} y1={plot.bottom} y2={plot.bottom} />
        {ticks(x.domain[0], x.domain[1], W > 500 ? 6 : 4).map((t) => (
          <AxisLabel key={t} x={x(t)} y={plot.bottom + 16}>
            {formatTick(t)}
          </AxisLabel>
        ))}

        <AxisLabel x={(plot.left + plot.right) / 2} y={H - 6} className="is-title">
          {labelOf(data.column)}
        </AxisLabel>
        <AxisLabel x={plot.left} y={plot.top - 4} anchor="start" className="is-title">
          Values per bin
        </AxisLabel>
      </svg>
      <Tooltip tip={tip} />
    </>
  );
}

/**
 * The key for the two reference lines. Present because the lines are told apart
 * by dash pattern and colour alone — without this, they are two mystery rules.
 */
export function HistogramLegend({ data }: { data: HistogramResponse }): JSX.Element {
  return (
    <>
      <span className="fig-key">
        <i className="fig-key-mark is-median" /> Median {formatTick(data.median)}
      </span>
      <span className="fig-key">
        <i className="fig-key-mark is-mean" /> Mean {formatTick(data.mean)}
      </span>
      <span className="fig-key">
        <i className="fig-key-mark is-bar" /> {formatCount(data.n)} values in {data.bins.length} bins
      </span>
    </>
  );
}
