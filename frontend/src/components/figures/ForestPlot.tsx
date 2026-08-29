// Forest — every coefficient in the study's two models, with its interval.
//
// This is the picture of the primary test. The protocol pre-specified one
// number as the thing the hypothesis rises or falls on — sugar's coefficient in
// Model B WITH BMI — and pre-specified that the same model without BMI would be
// reported beside it. Two rows per predictor is therefore not a design flourish;
// it is the comparison the protocol committed to before the data were seen.
//
// WHY INTERVALS AND NOT STARS
//   A coefficient with a star next to it says "this cleared 0.05" and nothing
//   about how big it is or how well pinned down. The interval says both at once,
//   and it makes the null result legible in the way a p-value cannot: an
//   interval that straddles zero AND is narrow means "we looked, and there is no
//   room for a large effect here", which is a much stronger statement than
//   "p > 0.05". The zero line is the whole reading — an interval crossing it is
//   a predictor the model cannot tell apart from nothing.
//
// The x-axis is the standardized beta, not the raw coefficient. Sugar is in
// 10 g/day, BMI in kg/m², HbA1c in percent; drawn on one raw axis they would be
// incomparable, and comparing sugar against the Trig/HDL ratio is precisely the
// protocol's secondary question.

import type { JSX } from "react";
import type { Coefficient, StudyModel } from "../../types/engine";
import { formatTick, labelOf, linearScale, niceDomain, plotArea, ticks } from "../../lib/scales";
import { AxisLabel, GridLine, Tooltip, useNarrowChart, useTooltip } from "./ChartFrame";
import type { Layout } from "./ChartFrame";

const WIDE: Layout = { W: 720, H: 360, margin: { top: 20, right: 24, bottom: 46, left: 150 } };
const NARROW: Layout = { W: 360, H: 330, margin: { top: 16, right: 12, bottom: 42, left: 104 } };

/** One drawn row: a predictor as one model estimated it. */
interface Row {
  predictor: string;
  model: string;
  series: number;
  beta: number;
  low: number;
  high: number;
  estimate: number | null;
  p: number | null;
  significant: boolean;
}

/**
 * Turn a coefficient into the row the chart draws, on the standardized scale.
 *
 * The interval is standardized by the same factor as the estimate. That is
 * exact rather than an approximation: standardizing multiplies by the ratio of
 * two standard deviations, which is a constant, and a constant scales an
 * interval's endpoints as readily as its centre.
 */
function toRow(predictor: string, model: string, series: number, c: Coefficient): Row | null {
  const beta = c.standardized_beta;
  const estimate = c.estimate;
  if (beta === null || estimate === null || estimate === 0) return null;
  if (c.ci_low === null || c.ci_high === null) return null;
  const factor = beta / estimate;
  return {
    predictor,
    model,
    series,
    beta,
    low: c.ci_low * factor,
    high: c.ci_high * factor,
    estimate,
    p: c.significance.p_value,
    significant: c.significance.statistically_significant,
  };
}

/** Every predictor either model fits, in the order the specification lists them. */
export function forestRows(models: { label: string; model: StudyModel }[]): Row[] {
  const order: string[] = [];
  for (const { model } of models) {
    for (const name of model.predictors) if (!order.includes(name)) order.push(name);
  }
  const rows: Row[] = [];
  for (const predictor of order) {
    models.forEach(({ label, model }, series) => {
      const coefficient = model.coefficients[predictor];
      // A predictor absent from one specification is the point of the
      // comparison (BMI is in one model and not the other), so it is skipped
      // rather than drawn at zero — which would claim an estimate of nothing.
      if (!coefficient) return;
      const row = toRow(predictor, label, series, coefficient);
      if (row) rows.push(row);
    });
  }
  return rows;
}

export function ForestPlot({
  models,
}: {
  models: { label: string; model: StudyModel }[];
}): JSX.Element {
  const { tip, show, hide } = useTooltip();
  const { W, H, margin: MARGIN } = useNarrowChart() ? NARROW : WIDE;
  const plot = plotArea(W, H, MARGIN);

  const rows = forestRows(models);
  const reach = Math.max(0.05, ...rows.map((r) => Math.max(Math.abs(r.low), Math.abs(r.high))));
  const [, xHi] = niceDomain(0, reach, 4);
  const x = linearScale([-xHi, xHi], [plot.left, plot.right]);

  // Rows are grouped by predictor, so the two models for one predictor sit
  // adjacent and the eye compares them without hunting.
  const predictors = [...new Set(rows.map((r) => r.predictor))];
  const band = plot.innerHeight / Math.max(1, predictors.length);
  const yOf = (row: Row): number => {
    const group = predictors.indexOf(row.predictor);
    const within = models.length > 1 ? (row.series + 0.5) / models.length : 0.5;
    return plot.top + band * (group + within);
  };

  return (
    <>
      <svg className="fig-svg" viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label={`Standardized coefficients with 95% confidence intervals for ${models.map((m) => m.label).join(" and ")}`}>
        {ticks(-xHi, xHi, 4).map((t) => (
          <GridLine key={t} x1={x(t)} x2={x(t)} y1={plot.top} y2={plot.bottom} />
        ))}

        {predictors.map((predictor, index) => (
          <AxisLabel key={predictor} x={plot.left - 10} y={plot.top + band * (index + 0.5) + 4}
                     anchor="end">
            {labelOf(predictor)}
          </AxisLabel>
        ))}

        {/* Zero. Drawn heavier than the grid because crossing it is the finding. */}
        <line className="fig-zero" x1={x(0)} x2={x(0)} y1={plot.top} y2={plot.bottom} />

        {rows.map((row) => {
          const cy = yOf(row);
          const state = row.significant ? "is-sig" : "is-null";
          return (
            <g key={`${row.predictor}-${row.model}`} className={`fig-forest ${state} is-s${row.series}`}>
              <line className="fig-forest-ci" x1={x(row.low)} x2={x(row.high)} y1={cy} y2={cy} />
              <line className="fig-forest-cap" x1={x(row.low)} x2={x(row.low)} y1={cy - 4} y2={cy + 4} />
              <line className="fig-forest-cap" x1={x(row.high)} x2={x(row.high)} y1={cy - 4} y2={cy + 4} />
              <circle className="fig-forest-dot" cx={x(row.beta)} cy={cy} r={4} />
              <rect
                className="fig-hit"
                x={plot.left}
                y={cy - band / (2 * models.length)}
                width={plot.innerWidth}
                height={band / models.length}
                onMouseMove={(event) =>
                  show(event, {
                    title: `${labelOf(row.predictor)} — ${row.model}`,
                    rows: [
                      ["Standardized β", formatTick(row.beta)],
                      ["95% CI", `${formatTick(row.low)} to ${formatTick(row.high)}`],
                      ["Raw coefficient", formatTick(row.estimate ?? 0)],
                      ["p", row.p === null ? "—" : row.p < 0.0001 ? "< 0.0001" : row.p.toFixed(4)],
                    ],
                    note: row.significant
                      ? "Interval clears zero at α = 0.05."
                      : "Interval includes zero — indistinguishable from no association.",
                  })
                }
                onMouseLeave={hide}
              />
            </g>
          );
        })}

        <line className="fig-axis" x1={plot.left} x2={plot.right} y1={plot.bottom} y2={plot.bottom} />
        {ticks(-xHi, xHi, 4).map((t) => (
          <AxisLabel key={t} x={x(t)} y={plot.bottom + 16}>
            {formatTick(t)}
          </AxisLabel>
        ))}
        <AxisLabel x={(plot.left + plot.right) / 2} y={H - 6} className="is-title">
          Standardized β (SDs of log ALT per SD of predictor)
        </AxisLabel>
      </svg>
      <Tooltip tip={tip} />
    </>
  );
}

export function ForestLegend({
  models,
}: {
  models: { label: string; model: StudyModel }[];
}): JSX.Element {
  return (
    <>
      {models.map((entry, index) => (
        <span className="fig-key" key={entry.label}>
          <i className={`fig-key-mark is-series is-s${index}`} /> {entry.label}{" "}
          <b>n = {entry.model.n}</b>
        </span>
      ))}
      <span className="fig-key">
        <i className="fig-key-mark is-zero" /> Zero — an interval crossing it is no association
      </span>
    </>
  );
}
