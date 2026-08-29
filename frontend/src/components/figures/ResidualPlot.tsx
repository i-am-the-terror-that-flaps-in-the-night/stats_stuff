// Residuals against fitted values — is the model equally wrong everywhere?
//
// The second assumption under every interval the study reports: that the spread
// of the errors does not depend on the prediction. If the cloud fans out to the
// right, the model is more uncertain about high-ALT adolescents than about low
// ones, and a single standard error that averages the two is describing neither.
//
// The binned mean line is a reading aid, not a fit. Eyes are bad at judging the
// centre of a cloud and good at following a line, so the points are averaged in
// vertical slices and joined; a real curve there means the model is missing
// something systematic, not merely noisy.

import type { JSX } from "react";
import type { DiagnosticsResponse } from "../../types/engine";
import { formatCount, formatTick, linearScale, niceDomain, plotArea, ticks } from "../../lib/scales";
import { AxisLabel, GridLine, Tooltip, useNarrowChart, useTooltip } from "./ChartFrame";
import type { Layout } from "./ChartFrame";

const WIDE: Layout = { W: 720, H: 340, margin: { top: 18, right: 20, bottom: 48, left: 58 } };
const NARROW: Layout = { W: 360, H: 280, margin: { top: 14, right: 12, bottom: 44, left: 44 } };

/** Vertical slices for the trend line. Eight keeps roughly 70 points a bin at
 *  n = 586, which is enough for a mean that is not itself mostly noise. */
const BINS = 8;

interface Bin {
  center: number;
  mean: number;
  n: number;
}

/** Average the residuals inside equal-width slices of the fitted range. */
function binResiduals(fitted: number[], residuals: number[], lo: number, hi: number): Bin[] {
  const width = (hi - lo) / BINS;
  if (!(width > 0)) return [];
  const sums = new Array<number>(BINS).fill(0);
  const counts = new Array<number>(BINS).fill(0);
  fitted.forEach((value, index) => {
    const residual = residuals[index];
    if (residual === undefined) return;
    const slot = Math.min(BINS - 1, Math.max(0, Math.floor((value - lo) / width)));
    sums[slot] = (sums[slot] ?? 0) + residual;
    counts[slot] = (counts[slot] ?? 0) + 1;
  });
  const out: Bin[] = [];
  for (let i = 0; i < BINS; i++) {
    const count = counts[i] ?? 0;
    if (count === 0) continue;
    out.push({ center: lo + width * (i + 0.5), mean: (sums[i] ?? 0) / count, n: count });
  }
  return out;
}

export function ResidualPlot({ data }: { data: DiagnosticsResponse }): JSX.Element {
  const { tip, show, hide } = useTooltip();
  const { W, H, margin: MARGIN } = useNarrowChart() ? NARROW : WIDE;
  const plot = plotArea(W, H, MARGIN);

  const [xLo, xHi] = niceDomain(data.fitted_min, data.fitted_max, 5);
  // A symmetric y-domain, so the zero line sits in the middle of the frame and
  // a lopsided cloud reads as lopsided instead of as a badly-placed axis.
  const reach = Math.max(Math.abs(data.residual_min), Math.abs(data.residual_max));
  const [, yHi] = niceDomain(0, reach, 4);
  const x = linearScale([xLo, xHi], [plot.left, plot.right]);
  const y = linearScale([-yHi, yHi], [plot.bottom, plot.top]);

  const bins = binResiduals(data.fitted, data.residuals, xLo, xHi);
  const trend = bins.map((b, i) => `${i === 0 ? "M" : "L"}${x(b.center)} ${y(b.mean)}`).join(" ");

  return (
    <>
      <svg className="fig-svg" viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label={`Residuals against fitted values for ${data.label}`}>
        {ticks(-yHi, yHi, 4).map((t) => (
          <g key={t}>
            <GridLine x1={plot.left} x2={plot.right} y1={y(t)} y2={y(t)} />
            <AxisLabel x={plot.left - 8} y={y(t) + 4} anchor="end">
              {formatTick(t)}
            </AxisLabel>
          </g>
        ))}

        {data.fitted.map((value, index) => {
          const residual = data.residuals[index];
          if (residual === undefined) return null;
          return (
            <circle
              key={index}
              className="fig-dot"
              cx={x(value)}
              cy={y(residual)}
              r={2.4}
              onMouseMove={(event) =>
                show(event, {
                  title: `Adolescent ${formatCount(index + 1)}`,
                  rows: [
                    ["Predicted log ALT", formatTick(value)],
                    ["Residual", formatTick(residual)],
                    ["Missed by", `${((Math.exp(residual) - 1) * 100).toFixed(1)}% of ALT`],
                  ],
                })
              }
              onMouseLeave={hide}
            />
          );
        })}

        {/* Zero, then the binned trend. Distance between them is the bias. */}
        <line className="fig-zero" x1={plot.left} x2={plot.right} y1={y(0)} y2={y(0)} />
        {trend && <path className="fig-trend" d={trend} fill="none" />}
        {bins.map((bin) => (
          <circle key={bin.center} className="fig-trend-dot" cx={x(bin.center)} cy={y(bin.mean)} r={3.5}
                  onMouseMove={(event) =>
                    show(event, {
                      title: `Fitted ≈ ${formatTick(bin.center)}`,
                      rows: [
                        ["Mean residual", formatTick(bin.mean)],
                        ["Points in slice", formatCount(bin.n)],
                      ],
                      note: "A flat line at zero is what a well-specified model looks like.",
                    })
                  }
                  onMouseLeave={hide} />
        ))}

        <line className="fig-axis" x1={plot.left} x2={plot.right} y1={plot.bottom} y2={plot.bottom} />
        {ticks(xLo, xHi, W > 500 ? 6 : 4).map((t) => (
          <AxisLabel key={t} x={x(t)} y={plot.bottom + 16}>
            {formatTick(t)}
          </AxisLabel>
        ))}

        <AxisLabel x={(plot.left + plot.right) / 2} y={H - 6} className="is-title">
          Fitted value (log ALT)
        </AxisLabel>
        <AxisLabel x={plot.left} y={plot.top - 4} anchor="start" className="is-title">
          Residual
        </AxisLabel>
      </svg>
      <Tooltip tip={tip} />
    </>
  );
}

export function ResidualLegend({ data }: { data: DiagnosticsResponse }): JSX.Element {
  return (
    <>
      <span className="fig-key">
        <i className="fig-key-mark is-dot" /> {formatCount(data.n)} residuals
      </span>
      <span className="fig-key">
        <i className="fig-key-mark is-trend" /> Mean residual in {BINS} slices
      </span>
      <span className="fig-key">
        <i className="fig-key-mark is-zero" /> Zero — where a perfect prediction lands
      </span>
      <span className="fig-key">
        Residual SD <b>{formatTick(data.residual_sd ?? 0)}</b>
      </span>
    </>
  );
}
