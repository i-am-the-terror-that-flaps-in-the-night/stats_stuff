// Dose-response — does ALT climb as sugar intake climbs?
//
// WHY THIS FIGURE CARRIES WEIGHT
//   A dose-response curve is one of the stronger observational arguments that
//   an association is real: noise has no reason to arrange itself in order, so
//   a mean that rises step by step across quartiles is harder to explain away
//   than a single significant coefficient. That cuts both ways, which is why
//   the figure is here — the absence of a gradient is evidence about the null
//   result, not merely a missing finding, and it is far easier to see as four
//   points with error bars than to read out of a table.
//
// WHAT THE ERROR BARS ARE
//   ± one standard error of the weighted mean, computed on the ROW count rather
//   than the summed survey weight. The weight says how many U.S. adolescents
//   each participant stands for, and dividing by millions would draw an error
//   bar of essentially zero around an estimate that came from a few hundred
//   people. See step_dose_response() in engine.py, which computes it that way
//   for exactly this reason.
//
// The percentage above the clinical ALT threshold is drawn on the same frame as
// a second, fainter series, because "the average went up a bit" and "more
// adolescents crossed the line" are different claims and the protocol makes
// both (steps 3 and 7).

import type { JSX } from "react";
import type { SugarQuartile } from "../../types/engine";
import { formatCount, formatTick, linearScale, niceDomain, plotArea, ticks } from "../../lib/scales";
import { AxisLabel, GridLine, Tooltip, useNarrowChart, useTooltip } from "./ChartFrame";
import type { Layout } from "./ChartFrame";

const WIDE: Layout = { W: 720, H: 350, margin: { top: 20, right: 56, bottom: 56, left: 58 } };
const NARROW: Layout = { W: 360, H: 290, margin: { top: 16, right: 40, bottom: 52, left: 44 } };

export function DoseResponseChart({ quartiles }: { quartiles: SugarQuartile[] }): JSX.Element {
  const { tip, show, hide } = useTooltip();
  const { W, H, margin: MARGIN } = useNarrowChart() ? NARROW : WIDE;
  const plot = plotArea(W, H, MARGIN);

  const means = quartiles.map((q) => q.weighted_mean_alt ?? 0);
  const errors = quartiles.map((q) => q.standard_error_alt ?? 0);
  // The domain covers the error bars, not just the points: a bar clipped by the
  // frame would understate the uncertainty, which is the one thing this figure
  // must not do.
  const lo = Math.min(...means.map((m, i) => m - (errors[i] ?? 0)));
  const hi = Math.max(...means.map((m, i) => m + (errors[i] ?? 0)));
  const [yLo, yHi] = niceDomain(lo, hi, 4);
  const y = linearScale([yLo, yHi], [plot.bottom, plot.top]);

  // The right-hand axis: share above the clinical threshold, on its own scale.
  const percents = quartiles.map((q) => q.percent_elevated_alt ?? 0);
  const [, pHi] = niceDomain(0, Math.max(...percents, 1), 4);
  const yPercent = linearScale([0, pHi], [plot.bottom, plot.top]);

  const slot = plot.innerWidth / Math.max(1, quartiles.length);
  const centerOf = (index: number): number => plot.left + slot * (index + 0.5);

  const elevatedPath = quartiles
    .map((q, i) => `${i === 0 ? "M" : "L"}${centerOf(i)} ${yPercent(q.percent_elevated_alt ?? 0)}`)
    .join(" ");

  return (
    <>
      <svg className="fig-svg" viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label="Weighted mean ALT and share above the clinical threshold, across sugar quartiles">
        {ticks(yLo, yHi, 4).map((t) => (
          <g key={t}>
            <GridLine x1={plot.left} x2={plot.right} y1={y(t)} y2={y(t)} />
            <AxisLabel x={plot.left - 8} y={y(t) + 4} anchor="end">
              {formatTick(t)}
            </AxisLabel>
          </g>
        ))}

        {/* The secondary series first, so it reads as background to the means. */}
        <path className="fig-elevated" d={elevatedPath} fill="none" />
        {quartiles.map((q, index) => (
          <circle key={`e-${q.quartile}`} className="fig-elevated-dot"
                  cx={centerOf(index)} cy={yPercent(q.percent_elevated_alt ?? 0)} r={3} />
        ))}
        {ticks(0, pHi, 4).map((t) => (
          <AxisLabel key={`p-${t}`} x={plot.right + 8} y={yPercent(t) + 4} anchor="start"
                     className="is-faint">
            {`${formatTick(t)}%`}
          </AxisLabel>
        ))}

        {quartiles.map((quartile, index) => {
          const cx = centerOf(index);
          const mean = quartile.weighted_mean_alt ?? 0;
          const error = quartile.standard_error_alt ?? 0;
          const range = quartile.sugar_range_g;
          return (
            <g className="fig-dose" key={quartile.quartile}>
              <line className="fig-dose-bar" x1={cx} x2={cx} y1={y(mean - error)} y2={y(mean + error)} />
              <line className="fig-dose-cap" x1={cx - 8} x2={cx + 8} y1={y(mean + error)} y2={y(mean + error)} />
              <line className="fig-dose-cap" x1={cx - 8} x2={cx + 8} y1={y(mean - error)} y2={y(mean - error)} />
              <circle className="fig-dose-dot" cx={cx} cy={y(mean)} r={5} />
              <rect
                className="fig-hit"
                x={cx - slot / 2}
                y={plot.top}
                width={slot}
                height={plot.innerHeight}
                onMouseMove={(event) =>
                  show(event, {
                    title: `Quartile ${quartile.quartile}`,
                    rows: [
                      ["Sugar", `${formatTick(range[0])} – ${formatTick(range[1])} g/day`],
                      ["Mean sugar", `${formatTick(quartile.weighted_mean_sugar_g ?? 0)} g/day`],
                      ["Mean ALT", `${formatTick(mean)} ± ${formatTick(error)} U/L`],
                      ["Median ALT", `${formatTick(quartile.weighted_median_alt ?? 0)} U/L`],
                      ["Above threshold", `${formatTick(quartile.percent_elevated_alt ?? 0)}%`],
                      ["n", formatCount(quartile.n)],
                    ],
                    note: "ALT is weighted to U.S. adolescents; ± is one standard error.",
                  })
                }
                onMouseLeave={hide}
              />
            </g>
          );
        })}

        {/* The line joining the means, drawn last so it sits over the bars. It
            is a reading aid between four ordered groups, not a fitted trend —
            the fitted trend is the coefficient quoted in the footnote. */}
        <path className="fig-dose-link"
              d={quartiles.map((q, i) => `${i === 0 ? "M" : "L"}${centerOf(i)} ${y(q.weighted_mean_alt ?? 0)}`).join(" ")}
              fill="none" />

        <line className="fig-axis" x1={plot.left} x2={plot.right} y1={plot.bottom} y2={plot.bottom} />
        {quartiles.map((quartile, index) => (
          <g key={`x-${quartile.quartile}`}>
            <AxisLabel x={centerOf(index)} y={plot.bottom + 16}>
              {`Q${quartile.quartile}`}
            </AxisLabel>
            <AxisLabel x={centerOf(index)} y={plot.bottom + 30} className="is-faint">
              {`${formatTick(quartile.sugar_range_g[0])}–${formatTick(quartile.sugar_range_g[1])} g`}
            </AxisLabel>
          </g>
        ))}

        <AxisLabel x={(plot.left + plot.right) / 2} y={H - 6} className="is-title">
          Daily sugar quartile
        </AxisLabel>
        <AxisLabel x={plot.left} y={plot.top - 6} anchor="start" className="is-title">
          Mean ALT (U/L)
        </AxisLabel>
      </svg>
      <Tooltip tip={tip} />
    </>
  );
}

export function DoseResponseLegend({ quartiles }: { quartiles: SugarQuartile[] }): JSX.Element {
  const total = quartiles.reduce((sum, q) => sum + q.n, 0);
  return (
    <>
      <span className="fig-key">
        <i className="fig-key-mark is-dosedot" /> Weighted mean ALT, ± 1 SE
      </span>
      <span className="fig-key">
        <i className="fig-key-mark is-elevated" /> Share above the clinical threshold (right axis)
      </span>
      <span className="fig-key">
        <b>{formatCount(total)}</b> adolescents across {quartiles.length} quartiles
      </span>
    </>
  );
}
