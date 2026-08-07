// Scatter — two columns against each other, with the least-squares line.
//
// This is the figure that keeps the advanced tier honest. r = 0.77 sounds like a
// law; the cloud shows it is a wide band with real people at both edges. The
// engine reports the number, this shows the spread the number is a summary of --
// and it is the reason the caption says "association", not "effect".
//
// Marks are semi-transparent so density reads through overplotting: 1,500 dots
// at full opacity is a silhouette, at 45% it is a distribution.

import type { JSX } from "react";
import type { ScatterResponse } from "../../types/engine";
import { formatCount, formatTick, labelOf, linearScale, niceDomain, plotArea, ticks } from "../../lib/scales";
import { AxisLabel, GridLine, Tooltip, useNarrowChart, useTooltip } from "./ChartFrame";
import type { Layout } from "./ChartFrame";

const WIDE: Layout = { W: 720, H: 400, margin: { top: 18, right: 20, bottom: 52, left: 62 } };
const NARROW: Layout = { W: 360, H: 300, margin: { top: 14, right: 10, bottom: 46, left: 40 } };

export function ScatterPlot({ data }: { data: ScatterResponse }): JSX.Element {
  const { tip, show, hide } = useTooltip();
  const narrow = useNarrowChart();
  const { W, H, margin: MARGIN } = narrow ? NARROW : WIDE;
  const plot = plotArea(W, H, MARGIN);

  const [xLo, xHi] = niceDomain(data.x_min, data.x_max, 6);
  const [yLo, yHi] = niceDomain(data.y_min, data.y_max, 5);
  const x = linearScale([xLo, xHi], [plot.left, plot.right]);
  const y = linearScale([yLo, yHi], [plot.bottom, plot.top]);

  // Clip the fit line twice over.
  //
  // In x, to the measured range: extending it to the axis ends would draw
  // predictions over values nobody was observed at.
  //
  // In y, to the plot box: Weight-against-Height has a negative intercept, so
  // the fitted line leaves the bottom of the frame before the data does, and
  // an unclipped segment drew itself across the x-axis labels. Solving for the
  // x where the line crosses the y-bound keeps the same line and just stops it
  // at the edge -- unlike an SVG clip path, which would need its own <defs> and
  // still leave the geometry lying about where the line goes.
  const fitY = (at: number): number => data.slope * at + data.intercept;
  const xAtY = (target: number): number =>
    data.slope === 0 ? Number.POSITIVE_INFINITY : (target - data.intercept) / data.slope;

  let fitX0 = Math.max(xLo, data.x_min);
  let fitX1 = Math.min(xHi, data.x_max);
  for (const bound of [yLo, yHi]) {
    const crossing = xAtY(bound);
    if (!Number.isFinite(crossing) || crossing <= fitX0 || crossing >= fitX1) continue;
    // The crossing splits the segment; keep whichever side stays in the box.
    if (fitY(fitX0) < yLo || fitY(fitX0) > yHi) fitX0 = crossing;
    else fitX1 = crossing;
  }

  return (
    <>
      <svg className="fig-svg" viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label={`${labelOf(data.y)} against ${labelOf(data.x)}, r = ${data.r}`}>
        {ticks(yLo, yHi, narrow ? 4 : 5).map((t) => (
          <g key={`y${t}`}>
            <GridLine x1={plot.left} x2={plot.right} y1={y(t)} y2={y(t)} />
            <AxisLabel x={plot.left - 8} y={y(t) + 4} anchor="end">
              {formatTick(t)}
            </AxisLabel>
          </g>
        ))}
        {ticks(xLo, xHi, narrow ? 4 : 6).map((t) => (
          <g key={`x${t}`}>
            <GridLine x1={x(t)} x2={x(t)} y1={plot.top} y2={plot.bottom} />
            <AxisLabel x={x(t)} y={plot.bottom + 16}>
              {formatTick(t)}
            </AxisLabel>
          </g>
        ))}

        <g className="fig-dots">
          {/* xs and ys are parallel arrays off the wire; pair them up front so
              the mark code never indexes one by the other's position. */}
          {data.xs.map((xv, i) => {
            const yv = data.ys[i];
            if (yv === undefined) return null;
            return (
              <circle
                key={i}
                className="fig-dot"
                cx={x(xv)}
                cy={y(yv)}
                // Marks are in the same user units as the layout, so the narrow
                // space needs its own radius or 1,500 dots merge into a slab.
                r={narrow ? 1.7 : 2.6}
                onMouseMove={(event) =>
                  show(event, {
                    title: "One person",
                    rows: [
                      [labelOf(data.x), formatTick(xv)],
                      [labelOf(data.y), formatTick(yv)],
                    ],
                  })
                }
                onMouseLeave={hide}
              />
            );
          })}
        </g>

        <line className="fig-fit" x1={x(fitX0)} y1={y(fitY(fitX0))} x2={x(fitX1)} y2={y(fitY(fitX1))} />

        <line className="fig-axis" x1={plot.left} x2={plot.right} y1={plot.bottom} y2={plot.bottom} />
        <line className="fig-axis" x1={plot.left} x2={plot.left} y1={plot.top} y2={plot.bottom} />

        <AxisLabel x={(plot.left + plot.right) / 2} y={H - 6} className="is-title">
          {labelOf(data.x)}
        </AxisLabel>
        <AxisLabel x={plot.left} y={plot.top - 5} anchor="start" className="is-title">
          {labelOf(data.y)}
        </AxisLabel>
      </svg>
      <Tooltip tip={tip} />
    </>
  );
}

export function ScatterLegend({ data }: { data: ScatterResponse }): JSX.Element {
  return (
    <>
      <span className="fig-key">
        <i className="fig-key-mark is-dot" />{" "}
        {data.sampled
          ? `${formatCount(data.drawn)} of ${formatCount(data.n)} pairs drawn`
          : `${formatCount(data.n)} pairs`}
      </span>
      <span className="fig-key">
        <i className="fig-key-mark is-fit" /> Least-squares fit
      </span>
      <span className="fig-key">
        r = <b>{data.r.toFixed(3)}</b> · r² = <b>{data.r_squared.toFixed(3)}</b>
      </span>
    </>
  );
}
