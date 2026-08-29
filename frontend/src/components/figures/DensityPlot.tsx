// Density — the shape the box plot summarizes.
//
// A five-number summary cannot show a second hump. Two groups with identical
// quartiles, one unimodal and one splitting into a low and a high cluster, draw
// the same box; the difference between them is usually the interesting thing.
// So this is the box plot's companion rather than its replacement, and the page
// puts them next to each other deliberately.
//
// The curve is a smoothing CHOICE as much as a measurement, which is why the
// bandwidth is in the legend. A bump narrower than the bandwidth is the
// smoother talking, not the data, and a reader who cannot see the bandwidth has
// no way to tell the two apart.

import type { JSX, MouseEvent } from "react";
import type { DensityCurve, DensityResponse } from "../../types/engine";
import { formatCount, formatTick, labelOf, linearScale, niceDomain, plotArea, ticks } from "../../lib/scales";
import { AxisLabel, GridLine, Tooltip, useNarrowChart, useTooltip } from "./ChartFrame";
import type { Layout } from "./ChartFrame";

const WIDE: Layout = { W: 720, H: 340, margin: { top: 16, right: 18, bottom: 46, left: 58 } };
const NARROW: Layout = { W: 360, H: 260, margin: { top: 14, right: 10, bottom: 42, left: 44 } };

/** Four series colours, cycled. Past four groups a legend stops being readable
 *  anyway, and the server has already dropped the groups too small to draw. */
export const SERIES = ["is-s0", "is-s1", "is-s2", "is-s3"] as const;

export function seriesClass(index: number): string {
  return SERIES[index % SERIES.length] ?? "is-s0";
}

export function DensityPlot({ data }: { data: DensityResponse }): JSX.Element {
  const { tip, show, hide } = useTooltip();
  const { W, H, margin: MARGIN } = useNarrowChart() ? NARROW : WIDE;
  const plot = plotArea(W, H, MARGIN);

  const first = data.grid[0] ?? 0;
  const last = data.grid[data.grid.length - 1] ?? 1;
  const x = linearScale([first, last], [plot.left, plot.right]);
  const [yLo, yHi] = niceDomain(0, data.peak, 4);
  const y = linearScale([yLo, yHi], [plot.bottom, plot.top]);

  /** The curve itself, and the same curve closed down to the axis for its fill. */
  const lineOf = (curve: DensityCurve): string =>
    curve.density
      .map((height, i) => `${i === 0 ? "M" : "L"}${x(data.grid[i] ?? 0)} ${y(height)}`)
      .join(" ");
  const areaOf = (curve: DensityCurve): string =>
    `${lineOf(curve)} L${x(last)} ${plot.bottom} L${x(first)} ${plot.bottom} Z`;

  // One shared vertical cursor rather than a hit target per curve: the curves
  // overlap by design, so "which one is the pointer on" has no good answer, and
  // the useful reading is every curve's height at one x.
  const readAt = (event: MouseEvent<SVGRectElement>): void => {
    const box = event.currentTarget.getBoundingClientRect();
    const value = x.invert(plot.left + ((event.clientX - box.left) / box.width) * plot.innerWidth);
    let index = 0;
    let best = Infinity;
    data.grid.forEach((g, i) => {
      const distance = Math.abs(g - value);
      if (distance < best) {
        best = distance;
        index = i;
      }
    });
    show(event, {
      title: `${labelOf(data.column)} ≈ ${formatTick(data.grid[index] ?? value)}`,
      rows: data.curves.map((curve): [string, string] => [
        curve.label,
        (curve.density[index] ?? 0).toPrecision(3),
      ]),
      note: "Density, not a count — the area under each curve is 1.",
    });
  };

  return (
    <>
      <svg className="fig-svg" viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label={`Distribution shape of ${labelOf(data.column)}${data.group ? ` by ${labelOf(data.group)}` : ""}`}>
        {ticks(yLo, yHi, 4).map((t) => (
          <g key={t}>
            <GridLine x1={plot.left} x2={plot.right} y1={y(t)} y2={y(t)} />
            <AxisLabel x={plot.left - 8} y={y(t) + 4} anchor="end">
              {t === 0 ? "0" : t.toPrecision(2)}
            </AxisLabel>
          </g>
        ))}

        {/* Fills first, then every outline, so no curve's fill hides another's
            line — the overlap is the comparison the figure exists to show. */}
        {data.curves.map((curve, index) => (
          <path key={`fill-${curve.label}`} className={`fig-density-area ${seriesClass(index)}`}
                d={areaOf(curve)} />
        ))}
        {data.curves.map((curve, index) => (
          <path key={`line-${curve.label}`} className={`fig-density-line ${seriesClass(index)}`}
                d={lineOf(curve)} fill="none" />
        ))}

        {/* Each group's mean, as a tick on the baseline. The gap between two
            ticks is the difference in centre; the curves above say whether that
            difference means anything. */}
        {data.curves.map((curve, index) => (
          <line key={`mean-${curve.label}`} className={`fig-density-mean ${seriesClass(index)}`}
                x1={x(curve.mean)} x2={x(curve.mean)} y1={plot.bottom} y2={plot.bottom - 10} />
        ))}

        <line className="fig-axis" x1={plot.left} x2={plot.right} y1={plot.bottom} y2={plot.bottom} />
        {ticks(first, last, W > 500 ? 6 : 4).map((t) => (
          <AxisLabel key={t} x={x(t)} y={plot.bottom + 16}>
            {formatTick(t)}
          </AxisLabel>
        ))}

        <AxisLabel x={(plot.left + plot.right) / 2} y={H - 6} className="is-title">
          {labelOf(data.column)}
        </AxisLabel>
        <AxisLabel x={plot.left} y={plot.top - 4} anchor="start" className="is-title">
          Density
        </AxisLabel>

        <rect className="fig-hit" x={plot.left} y={plot.top}
              width={plot.innerWidth} height={plot.innerHeight}
              onMouseMove={readAt} onMouseLeave={hide} />
      </svg>
      <Tooltip tip={tip} />
    </>
  );
}

export function DensityLegend({ data }: { data: DensityResponse }): JSX.Element {
  return (
    <>
      {data.curves.map((curve, index) => (
        <span className="fig-key" key={curve.label}>
          <i className={`fig-key-mark is-series ${seriesClass(index)}`} /> {curve.label}{" "}
          <b>n = {formatCount(curve.n)}</b>
        </span>
      ))}
      <span className="fig-key">
        {data.method}, bandwidth{" "}
        {data.curves.map((c) => formatTick(c.bandwidth)).join(" / ")}
      </span>
    </>
  );
}
