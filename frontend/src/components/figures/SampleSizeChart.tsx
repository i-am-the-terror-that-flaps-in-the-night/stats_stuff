// Sample size — the band of conclusions a study of size n could have reached.
//
// The y-axis is the column's own units and the shaded band is the middle 95% of
// 200 simulated studies at each n. Read left to right, the band collapses toward
// the population mean: that collapse IS what a confidence interval is estimating,
// and seeing it happen makes the formula stop being arbitrary.
//
// The x-axis is LOGARITHMIC and that is not a stylistic choice. Precision
// improves with the square root of n, so on a linear axis the interesting part
// (25 → 400) is squeezed into the first eighth of the chart and the rest is a
// flat line. On a log axis, doubling n is a constant step, and the band's
// steady, even narrowing is legible as the rule it actually is.

import type { JSX } from "react";
import type { SampleSizeResponse } from "../../types/engine";
import { formatCount, formatTick, labelOf, linearScale, niceDomain, plotArea, ticks } from "../../lib/scales";
import { AxisLabel, GridLine, Tooltip, useNarrowChart, useTooltip } from "./ChartFrame";
import type { Layout } from "./ChartFrame";

const WIDE: Layout = { W: 720, H: 340, margin: { top: 18, right: 20, bottom: 48, left: 62 } };
const NARROW: Layout = { W: 360, H: 280, margin: { top: 14, right: 10, bottom: 44, left: 42 } };

export function SampleSizeChart({ data }: { data: SampleSizeResponse }): JSX.Element {
  const { tip, show, hide } = useTooltip();
  const narrow = useNarrowChart();
  const { W, H, margin: MARGIN } = narrow ? NARROW : WIDE;
  const plot = plotArea(W, H, MARGIN);
  const rungs = data.rungs;

  if (rungs.length === 0) return <p className="text">Not enough rows to run this.</p>;

  const lo = Math.min(...rungs.map((r) => r.lo));
  const hi = Math.max(...rungs.map((r) => r.hi));
  const [yLo, yHi] = niceDomain(lo, hi, 5);
  const y = linearScale([yLo, yHi], [plot.bottom, plot.top]);

  // Log scale by hand: map log10(n) linearly. One line, and it avoids pulling in
  // a scale library for the only non-linear axis in the project.
  const logs = rungs.map((r) => Math.log10(r.n));
  const x = linearScale(
    [Math.min(...logs), Math.max(...logs)],
    [plot.left, plot.right],
  );
  const at = (n: number): number => x(Math.log10(n));

  // The band, as one closed path: across the top edge, back along the bottom.
  const band = [
    ...rungs.map((r) => `${at(r.n)},${y(r.hi)}`),
    ...[...rungs].reverse().map((r) => `${at(r.n)},${y(r.lo)}`),
  ].join(" ");
  const centre = rungs.map((r) => `${at(r.n)},${y(r.mean_of_means)}`).join(" ");

  return (
    <>
      <svg className="fig-svg" viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label={`Spread of ${labelOf(data.column)} means by study size`}>
        {ticks(yLo, yHi, 5).map((t) => (
          <g key={t}>
            <GridLine x1={plot.left} x2={plot.right} y1={y(t)} y2={y(t)} />
            <AxisLabel x={plot.left - 8} y={y(t) + 4} anchor="end">
              {formatTick(t)}
            </AxisLabel>
          </g>
        ))}

        {/* The truth the band is converging on. Drawn under the band so it does
            not cut across it, and dashed so it reads as a reference, not data. */}
        <line className="fig-ref is-mean" x1={plot.left} x2={plot.right}
              y1={y(data.population_mean)} y2={y(data.population_mean)} />

        <polygon className="fig-band" points={band} />
        <polyline className="fig-line" points={centre} fill="none" />

        {rungs.map((rung) => (
          <g key={rung.n}>
            <circle className="fig-point" cx={at(rung.n)} cy={y(rung.mean_of_means)} r={3} />
            {/* One tall hit target per rung — the marks are 3px dots. */}
            <rect
              className="fig-hit"
              x={at(rung.n) - plot.innerWidth / (rungs.length * 2)}
              y={plot.top}
              width={plot.innerWidth / rungs.length}
              height={plot.innerHeight}
              onMouseMove={(event) =>
                show(event, {
                  title: `n = ${formatCount(rung.n)}`,
                  rows: [
                    ["95% of studies", `${formatTick(rung.lo)} – ${formatTick(rung.hi)}`],
                    ["Band width", formatTick(rung.width)],
                    ["Average result", formatTick(rung.mean_of_means)],
                    ["Off by >1%", `${(rung.miss_rate * 100).toFixed(0)}%`],
                  ],
                  note: `${formatCount(data.draws_per_rung)} simulated studies at this size`,
                })
              }
              onMouseLeave={hide}
            />
            <AxisLabel x={at(rung.n)} y={plot.bottom + 16}>
              {rung.n >= 1000 ? `${rung.n / 1000}k` : rung.n}
            </AxisLabel>
          </g>
        ))}

        <line className="fig-axis" x1={plot.left} x2={plot.right} y1={plot.bottom} y2={plot.bottom} />
        <AxisLabel x={(plot.left + plot.right) / 2} y={H - 6} className="is-title">
          People in the study (log scale)
        </AxisLabel>
        <AxisLabel x={plot.left} y={plot.top - 5} anchor="start" className="is-title">
          {labelOf(data.column)}
        </AxisLabel>
      </svg>
      <Tooltip tip={tip} />
    </>
  );
}

export function SampleSizeLegend({ data }: { data: SampleSizeResponse }): JSX.Element {
  return (
    <>
      <span className="fig-key">
        <i className="fig-key-mark is-band" /> Middle 95% of {formatCount(data.draws_per_rung)}{" "}
        studies
      </span>
      <span className="fig-key">
        <i className="fig-key-mark is-line" /> Their average
      </span>
      <span className="fig-key">
        <i className="fig-key-mark is-mean" /> Whole dataset: {formatTick(data.population_mean)}
      </span>
    </>
  );
}
