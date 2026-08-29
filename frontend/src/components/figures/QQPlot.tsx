// Q-Q — are the model's residuals normal?
//
// Every confidence interval and every p-value the study reports assumes the
// residuals are roughly normal. The expert tier already TESTS that and returns
// a number. What a number cannot tell you is the SHAPE of the departure, and
// the shape is what decides whether it matters: a plot that tracks the line
// through its whole range and lifts off only in the last two points is a couple
// of unusual adolescents, while one that bows through the middle is a model
// mis-specified for everybody. Both can return the same test statistic.
//
// The reference line runs through the first and third quartiles rather than
// being the 45° identity. The identity would flag a pure difference in spread
// as non-normality, which is not what is being asked.

import type { JSX } from "react";
import type { DiagnosticsResponse } from "../../types/engine";
import { formatCount, formatTick, linearScale, niceDomain, plotArea, ticks } from "../../lib/scales";
import { AxisLabel, GridLine, Tooltip, useNarrowChart, useTooltip } from "./ChartFrame";
import type { Layout } from "./ChartFrame";

const WIDE: Layout = { W: 720, H: 360, margin: { top: 18, right: 20, bottom: 48, left: 58 } };
const NARROW: Layout = { W: 360, H: 300, margin: { top: 14, right: 12, bottom: 44, left: 44 } };

export function QQPlot({ data }: { data: DiagnosticsResponse }): JSX.Element {
  const { tip, show, hide } = useTooltip();
  const { W, H, margin: MARGIN } = useNarrowChart() ? NARROW : WIDE;
  const plot = plotArea(W, H, MARGIN);

  const theory = data.qq_theoretical;
  const observed = data.qq_observed;
  const [xLo, xHi] = niceDomain(Math.min(...theory), Math.max(...theory), 5);
  const [yLo, yHi] = niceDomain(Math.min(...observed), Math.max(...observed), 5);
  const x = linearScale([xLo, xHi], [plot.left, plot.right]);
  const y = linearScale([yLo, yHi], [plot.bottom, plot.top]);

  const slope = data.qq_line.slope ?? 1;
  const intercept = data.qq_line.intercept ?? 0;
  const lineAt = (t: number): number => slope * t + intercept;

  return (
    <>
      <svg className="fig-svg" viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label={`Normal quantile-quantile plot of the residuals from ${data.label}`}>
        {ticks(yLo, yHi, 5).map((t) => (
          <g key={t}>
            <GridLine x1={plot.left} x2={plot.right} y1={y(t)} y2={y(t)} />
            <AxisLabel x={plot.left - 8} y={y(t) + 4} anchor="end">
              {formatTick(t)}
            </AxisLabel>
          </g>
        ))}

        {/* The line first, so the points sit on top of the thing they are being
            compared against rather than under it. */}
        <line className="fig-qq-line" x1={x(xLo)} x2={x(xHi)} y1={y(lineAt(xLo))} y2={y(lineAt(xHi))} />

        {theory.map((t, index) => {
          const value = observed[index];
          if (value === undefined) return null;
          return (
            <circle
              key={index}
              className="fig-dot"
              cx={x(t)}
              cy={y(value)}
              r={2.4}
              onMouseMove={(event) =>
                show(event, {
                  title: `Residual ${formatCount(index + 1)} of ${formatCount(data.n)}`,
                  rows: [
                    ["Observed", formatTick(value)],
                    ["Expected if normal", formatTick(lineAt(t))],
                    ["Departure", formatTick(value - lineAt(t))],
                  ],
                  note: "In standard deviations of the residual.",
                })
              }
              onMouseLeave={hide}
            />
          );
        })}

        <line className="fig-axis" x1={plot.left} x2={plot.right} y1={plot.bottom} y2={plot.bottom} />
        {ticks(xLo, xHi, W > 500 ? 6 : 4).map((t) => (
          <AxisLabel key={t} x={x(t)} y={plot.bottom + 16}>
            {formatTick(t)}
          </AxisLabel>
        ))}

        <AxisLabel x={(plot.left + plot.right) / 2} y={H - 6} className="is-title">
          Theoretical normal quantile
        </AxisLabel>
        <AxisLabel x={plot.left} y={plot.top - 4} anchor="start" className="is-title">
          Observed residual (SDs)
        </AxisLabel>
      </svg>
      <Tooltip tip={tip} />
    </>
  );
}

export function QQLegend({ data }: { data: DiagnosticsResponse }): JSX.Element {
  return (
    <>
      <span className="fig-key">
        <i className="fig-key-mark is-dot" /> {formatCount(data.n)} residuals
      </span>
      <span className="fig-key">
        <i className="fig-key-mark is-qq" /> Normal, matched to this sample's quartiles
      </span>
      <span className="fig-key">
        Skewness <b>{formatTick(data.residual_skewness ?? 0)}</b>
      </span>
      <span className="fig-key">
        Excess kurtosis <b>{formatTick(data.residual_kurtosis ?? 0)}</b>
      </span>
    </>
  );
}
