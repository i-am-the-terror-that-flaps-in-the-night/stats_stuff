// Outlier rules, side by side — how much the answer moves when you change what
// counts as data.
//
// The experiments page already prints these four rules as a table, and the table
// is honest but easy to skim past: four means that differ in the second decimal
// look like rounding noise in a column of digits. Drawn on a shared axis, the
// same numbers show their spread as a DISTANCE, against the mean±SD interval
// each rule is claiming. That is the whole point of the experiment — the
// judgement call is not free, and here you can see its size.
//
// Two things you can do with the pointer:
//   hover  read one rule's numbers without losing the others
//   click  pin a rule, so it stays highlighted while you compare against it
//
// Pinning is the interaction the table cannot offer. With four overlapping
// intervals the eye loses which one it was tracking the moment it moves; a
// pinned rule keeps its reference line on the plot.

import { useState } from "react";
import type { JSX } from "react";
import type { OutliersResponse, OutlierVariant } from "../../types/engine";
import { formatCount, formatTick, labelOf, linearScale, niceDomain, plotArea, ticks } from "../../lib/scales";
import { AxisLabel, GridLine, Tooltip, useNarrowChart, useTooltip } from "./ChartFrame";

/**
 * Display names for the rules the server sends.
 *
 * The wire values are terse keys ("z3"), and a chart axis is the wrong place to
 * make someone decode one. Unknown keys fall through to the raw name rather than
 * rendering blank, so a rule added server-side still draws.
 */
const RULE_LABEL: Record<string, string> = {
  keep: "Keep all",
  // Spelled out rather than "|z| ≤ 3": the row labels and the tooltip title are
  // both uppercased by the stylesheet, which turns the conventional lowercase
  // z-score notation into "|Z|" — wrong notation, and unreadable as maths anyway
  // at this size.
  z3: "Within 3 SD",
  iqr: "Inside IQR fence",
  winsorize: "Winsorized",
};

const ROW_WIDE = 54;
const ROW_NARROW = 44;

/** Rows that carry no usable centre cannot be placed on a value axis. */
function isPlottable(v: OutlierVariant): v is OutlierVariant & { mean: number } {
  return typeof v.mean === "number" && Number.isFinite(v.mean);
}

export function OutlierRuleChart({ data }: { data: OutliersResponse }): JSX.Element {
  const { tip, show, hide } = useTooltip();
  const [pinned, setPinned] = useState<string | null>(null);
  const narrow = useNarrowChart();

  const rows = data.results.filter(isPlottable);
  const rowHeight = narrow ? ROW_NARROW : ROW_WIDE;
  const margin = narrow
    ? { top: 14, right: 14, bottom: 40, left: 92 }
    : { top: 18, right: 26, bottom: 42, left: 132 };
  const W = narrow ? 360 : 720;
  const H = margin.top + rows.length * rowHeight + margin.bottom;
  const plot = plotArea(W, H, margin);

  // The axis has to hold every interval AND both fences, or a rule would sit off
  // the edge of the picture that exists to compare it.
  const edges = rows.flatMap((r) => {
    const spread = typeof r.std === "number" && Number.isFinite(r.std) ? r.std : 0;
    return [r.mean - spread, r.mean + spread];
  });
  const [lo, hi] = niceDomain(
    Math.min(...edges, ...data.fences),
    Math.max(...edges, ...data.fences),
    5,
  );
  const x = linearScale([lo, hi], [plot.left, plot.right]);

  // "Keep all" is the reference every other rule is a departure from.
  const baseline = rows.find((r) => r.rule === "keep") ?? rows[0];

  return (
    <>
      <svg
        className="fig-svg"
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`Mean and standard deviation of ${labelOf(data.column)} under ${rows.length} outlier rules`}
      >
        {ticks(lo, hi, narrow ? 4 : 6).map((t) => (
          <g key={t}>
            <GridLine x1={x(t)} x2={x(t)} y1={plot.top} y2={plot.bottom} />
            <AxisLabel x={x(t)} y={plot.bottom + 16}>
              {formatTick(t)}
            </AxisLabel>
          </g>
        ))}

        {/* The IQR fences, as the band they actually are. Two of the four rules
            are defined by these lines, so drawing them explains the chart. */}
        <rect
          className="fig-band"
          x={x(data.fences[0])}
          y={plot.top}
          width={Math.max(0, x(data.fences[1]) - x(data.fences[0]))}
          height={plot.innerHeight}
        />

        {baseline && (
          <line
            className="fig-ref is-mean"
            x1={x(baseline.mean)}
            x2={x(baseline.mean)}
            y1={plot.top}
            y2={plot.bottom}
          />
        )}

        {rows.map((row, i) => {
          const cy = plot.top + i * rowHeight + rowHeight / 2;
          const spread = typeof row.std === "number" && Number.isFinite(row.std) ? row.std : 0;
          const active = pinned === row.rule;
          const label = RULE_LABEL[row.rule] ?? row.rule;
          return (
            <g key={row.rule} className={active ? "fig-rule is-active" : "fig-rule"}>
              <line
                className="fig-whisker"
                x1={x(row.mean - spread)}
                x2={x(row.mean + spread)}
                y1={cy}
                y2={cy}
              />
              <line className="fig-whisker-cap" x1={x(row.mean - spread)} x2={x(row.mean - spread)}
                    y1={cy - 6} y2={cy + 6} />
              <line className="fig-whisker-cap" x1={x(row.mean + spread)} x2={x(row.mean + spread)}
                    y1={cy - 6} y2={cy + 6} />
              <circle className="fig-dot is-meandot" cx={x(row.mean)} cy={cy} r={narrow ? 5 : 6} />

              <AxisLabel x={plot.left - 10} y={cy + 4} anchor="end" className="is-rowkey">
                {label}
              </AxisLabel>
              {/* How many rows the rule threw away, right where the trade is
                  being made. Winsorizing removes none — it moves them instead. */}
              <AxisLabel x={plot.left - 10} y={cy + (narrow ? 16 : 18)} anchor="end">
                {row.removed === 0 ? "kept every row" : `−${formatCount(row.removed)} rows`}
              </AxisLabel>

              {/* The row's hit target, LAST so it wins the pointer everywhere in
                  the band — including over the whisker and the dot, which carry
                  no handlers of their own. It is transparent, so the marks it
                  covers are still fully visible; the same trick, and the same
                  ordering requirement, as BoxPlot's per-box target. */}
              <rect
                className="fig-hit"
                x={plot.left}
                y={plot.top + i * rowHeight}
                width={plot.innerWidth}
                height={rowHeight}
                onMouseMove={(event) =>
                  show(event, {
                    title: label,
                    rows: [
                      ["Rows kept", formatCount(row.n)],
                      ["Mean", formatTick(row.mean)],
                      ["Std dev", spread ? formatTick(spread) : "—"],
                      ["Rows removed", `${formatCount(row.removed)} (${(row.removed_share * 100).toFixed(1)}%)`],
                      ["Mean shift", formatTick(row.mean_shift)],
                    ],
                    note: row.blurb,
                  })
                }
                onMouseLeave={hide}
                onClick={() => setPinned(active ? null : row.rule)}
              />
            </g>
          );
        })}

        <line className="fig-axis" x1={plot.left} x2={plot.right} y1={plot.bottom} y2={plot.bottom} />
        <AxisLabel x={(plot.left + plot.right) / 2} y={H - 5} className="is-title">
          {labelOf(data.column)} — mean, with ±1 SD
        </AxisLabel>
      </svg>
      <Tooltip tip={tip} />
    </>
  );
}

export function OutlierRuleLegend({ data }: { data: OutliersResponse }): JSX.Element {
  return (
    <>
      <span className="fig-key">
        <i className="fig-key-mark is-meandot" /> Mean under the rule
      </span>
      <span className="fig-key">
        <i className="fig-key-mark is-whisker" /> ±1 standard deviation
      </span>
      <span className="fig-key">
        <i className="fig-key-mark is-mean" /> Keep-all mean
      </span>
      <span className="fig-key">
        <i className="fig-key-mark is-band" /> IQR fence {formatTick(data.fences[0])} –{" "}
        {formatTick(data.fences[1])}
      </span>
      <span className="fig-key">Click a row to pin it</span>
    </>
  );
}
