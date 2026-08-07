// Bootstrap — the sampling distribution of one statistic, drawn.
//
// Take the dataset, draw a new one the same size by sampling WITH replacement,
// compute the statistic, repeat 2,000 times. The histogram of those 2,000
// answers is where a confidence interval comes from: the shaded middle 95% of
// this chart IS the interval, and the reader can see it rather than take the
// formula's word for it.
//
// Bars outside the interval are drawn in the same hue at lower opacity rather
// than in a second colour. They are the same measurements, not a different
// category — colour would claim a distinction that isn't there.

import type { JSX } from "react";
import type { BootstrapResponse } from "../../types/engine";
import { formatCount, formatTick, labelOf, linearScale, niceDomain, plotArea, ticks } from "../../lib/scales";
import { AxisLabel, GridLine, Tooltip, useNarrowChart, useTooltip } from "./ChartFrame";
import type { Layout } from "./ChartFrame";

const WIDE: Layout = { W: 720, H: 300, margin: { top: 16, right: 18, bottom: 46, left: 56 } };
const NARROW: Layout = { W: 360, H: 250, margin: { top: 14, right: 8, bottom: 42, left: 38 } };

export function BootstrapChart({ data }: { data: BootstrapResponse }): JSX.Element {
  const { tip, show, hide } = useTooltip();
  const narrow = useNarrowChart();
  const { W, H, margin: MARGIN } = narrow ? NARROW : WIDE;
  const plot = plotArea(W, H, MARGIN);

  const bins = data.bins;
  if (bins.length === 0) return <p className="text">Nothing to draw.</p>;

  const maxCount = Math.max(...bins.map((b) => b.count));
  const [yLo, yHi] = niceDomain(0, maxCount, 4);
  const firstBin = bins[0];
  const lastBin = bins[bins.length - 1];
  const x = linearScale(
    [firstBin?.lo ?? data.ci_lower, lastBin?.hi ?? data.ci_upper],
    [plot.left, plot.right],
  );
  const y = linearScale([yLo, yHi], [plot.bottom, plot.top]);

  // A bin counts as inside the interval if its midpoint is — the interval falls
  // between bin edges, and shading a bin half-in would suggest a precision the
  // 32-bin resolution does not have.
  const inside = (binLo: number, binHi: number): boolean => {
    const mid = (binLo + binHi) / 2;
    return mid >= data.ci_lower && mid <= data.ci_upper;
  };

  return (
    <>
      <svg className="fig-svg" viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label={`Bootstrap distribution of the ${data.statistic} of ${labelOf(data.column)}`}>
        {ticks(yLo, yHi, 4).map((t) => (
          <g key={t}>
            <GridLine x1={plot.left} x2={plot.right} y1={y(t)} y2={y(t)} />
            <AxisLabel x={plot.left - 8} y={y(t) + 4} anchor="end">
              {formatTick(t)}
            </AxisLabel>
          </g>
        ))}

        {bins.map((bin) => {
          const left = x(bin.lo);
          const width = Math.max(0.5, x(bin.hi) - left - 1);
          const top = y(bin.count);
          return (
            <rect
              key={bin.lo}
              className={`fig-bar${inside(bin.lo, bin.hi) ? "" : " is-outside"}`}
              x={left}
              y={top}
              width={width}
              height={Math.max(0, plot.bottom - top)}
              onMouseMove={(event) =>
                show(event, {
                  title: `${formatTick(bin.lo)} – ${formatTick(bin.hi)}`,
                  rows: [
                    ["Resamples", formatCount(bin.count)],
                    ["Share", `${((bin.count / data.draws) * 100).toFixed(1)}%`],
                  ],
                  note: inside(bin.lo, bin.hi) ? "Inside the 95% interval" : "Outside it",
                })
              }
              onMouseLeave={hide}
            />
          );
        })}

        {/* The statistic actually measured on the real dataset. It sits near the
            middle by construction, and saying so is the point: the spread around
            it is the uncertainty, not a disagreement with it. */}
        <line className="fig-ref is-median" x1={x(data.observed)} x2={x(data.observed)}
              y1={plot.top} y2={plot.bottom} />

        <line className="fig-axis" x1={plot.left} x2={plot.right} y1={plot.bottom} y2={plot.bottom} />
        {ticks(x.domain[0], x.domain[1], narrow ? 4 : 6).map((t) => (
          <AxisLabel key={t} x={x(t)} y={plot.bottom + 16}>
            {formatTick(t)}
          </AxisLabel>
        ))}

        <AxisLabel x={(plot.left + plot.right) / 2} y={H - 6} className="is-title">
          {data.statistic} of {labelOf(data.column)} in a resampled dataset
        </AxisLabel>
        <AxisLabel x={plot.left} y={plot.top - 4} anchor="start" className="is-title">
          Resamples per bin
        </AxisLabel>
      </svg>
      <Tooltip tip={tip} />
    </>
  );
}

export function BootstrapLegend({ data }: { data: BootstrapResponse }): JSX.Element {
  return (
    <>
      <span className="fig-key">
        <i className="fig-key-mark is-bar" /> Inside the 95% interval
      </span>
      <span className="fig-key">
        <i className="fig-key-mark is-bar-faint" /> Outside it
      </span>
      <span className="fig-key">
        <i className="fig-key-mark is-median" /> Measured: <b>{formatTick(data.observed)}</b>
      </span>
      <span className="fig-key">
        95% interval{" "}
        <b>
          {formatTick(data.ci_lower)} – {formatTick(data.ci_upper)}
        </b>
      </span>
    </>
  );
}
