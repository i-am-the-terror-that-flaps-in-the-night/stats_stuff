// Contribution chart — how one prediction was actually assembled.
//
// The marks are exact SHAP contributions from LightGBM's own TreeSHAP, and they
// are additive: the model's starting point plus every bar equals the prediction.
// So this is a DECOMPOSITION drawn to scale, not a ranking of importances, and
// the form follows from that — a diverging bar chart around a fixed zero, where
// bar length is the size of the push and the side of the axis is its direction.
//
// Three decisions worth the words:
//
//   * ZERO IS THE ANCHOR, and it stays put across renders. A reader moves one
//     slider and watches one bar grow; if the axis re-centred on each answer,
//     every other bar would move too and the comparison would be lost. The
//     domain is symmetric around zero for the same reason — an asymmetric one
//     makes a -8% bar look longer than a +8% one.
//   * THE UNIT IS PERCENT OF ALT, not the log contribution the model works in.
//     Log units are the additive ones, but "-0.038" means nothing to a visitor
//     at a poster; "lowered it by 3.8%" does. The exact log figure is one hover
//     away, and the panel beside the chart prints both.
//   * EVERY FEATURE IS DRAWN, including the ones that did nothing. Dropping the
//     near-zero bars would make the chart tidier and would quietly hide the
//     project's actual finding — that dietary sugar barely moves this model. A
//     bar of length zero next to a long one is the point.
//
// One self-contained <svg>, so lib/svgExport.ts can save it: the labels and the
// values are <text> inside the drawing rather than HTML beside it.

import type { JSX } from "react";
import type { PredictionResponse } from "../../types/engine";
import { formatTick } from "../../lib/scales";
import { AxisLabel, Tooltip, useNarrowChart, useTooltip } from "./ChartFrame";

// Row geometry rather than a viewBox height: the chart has one row per feature,
// so its height is derived and the rows stay a legible size instead of being
// squeezed into a fixed box.
const WIDE = { W: 720, rowH: 30, labelW: 168, valueW: 74, top: 30, bottom: 40 };
const NARROW = { W: 360, rowH: 26, labelW: 96, valueW: 52, top: 26, bottom: 36 };

/** Percent change in ALT for one driver, as a number the axis can scale. */
function percentOf(driver: { percent_of_alt: number | null }): number {
  return driver.percent_of_alt ?? 0;
}

export function ContributionChart({ data }: { data: PredictionResponse }): JSX.Element {
  const { tip, show, hide } = useTooltip();
  const { W, rowH, labelW, valueW, top, bottom } = useNarrowChart() ? NARROW : WIDE;

  const drivers = data.drivers;
  const H = top + drivers.length * rowH + bottom;
  const left = labelW;
  const right = W - valueW;
  const mid = (left + right) / 2;

  // A symmetric domain, rounded up to something a tick can land on, with a
  // floor so a prediction where nothing moved much does not get magnified into
  // a chart of dramatic-looking noise.
  const largest = Math.max(2, ...drivers.map((d) => Math.abs(percentOf(d))));
  const span = Math.ceil(largest / 5) * 5;
  const half = (right - left) / 2;
  const x = (percent: number): number => mid + (percent / span) * half;

  const axisTicks = [-span, -span / 2, 0, span / 2, span];

  return (
    <>
      <svg
        className="fig-svg"
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={
          `How each input moved the predicted ALT of ${data.predicted_alt} U/L, ` +
          `starting from the model's baseline of ${data.baseline_alt} U/L`
        }
      >
        {axisTicks.map((t) => (
          <line
            key={t}
            className={t === 0 ? "fig-axis" : "fig-grid"}
            x1={x(t)}
            x2={x(t)}
            y1={top - 8}
            y2={top + drivers.length * rowH}
          />
        ))}

        {/* The two directions, named in words above the axis. Colour alone
            would carry this, and colour alone is never enough. */}
        <AxisLabel x={x(-span / 2)} y={top - 14} className="is-faint">
          lowers the prediction
        </AxisLabel>
        <AxisLabel x={x(span / 2)} y={top - 14} className="is-faint">
          raises the prediction
        </AxisLabel>

        {drivers.map((driver, row) => {
          const percent = percentOf(driver);
          const y = top + row * rowH;
          const barY = y + rowH * 0.2;
          const barH = rowH * 0.6;
          const zero = x(0);
          const end = x(percent);
          // Math.max, not the raw width: a contribution of exactly zero would
          // otherwise vanish, and "this input did nothing" is a reading the
          // chart has to be able to show.
          const width = Math.max(1, Math.abs(end - zero));

          return (
            <g key={driver.feature}>
              <AxisLabel x={left - 10} y={y + rowH / 2 + 4} anchor="end">
                {driver.label}
              </AxisLabel>

              <rect
                className={percent < 0 ? "fig-contrib is-down" : "fig-contrib is-up"}
                x={Math.min(zero, end)}
                y={barY}
                width={width}
                height={barH}
                onMouseMove={(event) =>
                  show(event, {
                    title: driver.label,
                    rows: [
                      ["Entered", driver.display],
                      ["Cohort median", driver.cohort_median_display ?? "—"],
                      ["Moved ALT by", `${percent > 0 ? "+" : ""}${percent.toFixed(2)}%`],
                      ["Contribution to ln(ALT)", driver.contribution_log.toFixed(5)],
                    ],
                    note: "SHAP contribution — these sum exactly to the prediction.",
                  })
                }
                onMouseLeave={hide}
              />

              <AxisLabel x={right + 8} y={y + rowH / 2 + 4} anchor="start">
                {`${percent > 0 ? "+" : ""}${percent.toFixed(1)}%`}
              </AxisLabel>
            </g>
          );
        })}

        {axisTicks.map((t) => (
          <AxisLabel key={t} x={x(t)} y={top + drivers.length * rowH + 16}>
            {`${t > 0 ? "+" : ""}${formatTick(t)}%`}
          </AxisLabel>
        ))}

        <AxisLabel
          x={mid}
          y={H - 6}
          className="is-title"
        >
          {`Change in predicted ALT, from a baseline of ${data.baseline_alt} U/L`}
        </AxisLabel>
      </svg>
      <Tooltip tip={tip} />
    </>
  );
}

/** The key. Two colours, both named, plus the arithmetic that ties them together. */
export function ContributionLegend({ data }: { data: PredictionResponse }): JSX.Element {
  return (
    <>
      <span className="fig-key">
        <i className="fig-key-mark is-contrib-up" /> Raised the prediction
      </span>
      <span className="fig-key">
        <i className="fig-key-mark is-contrib-down" /> Lowered it
      </span>
      <span className="fig-key">
        {data.baseline_alt} U/L baseline + every bar = {data.predicted_alt} U/L
      </span>
    </>
  );
}
