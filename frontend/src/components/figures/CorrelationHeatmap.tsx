// Correlation matrix — every numeric pair at once, as a diverging heatmap.
//
// Fifteen numeric columns make 105 pairs. Nobody is going to open 105 scatter
// plots, and a table of 105 numbers is a wall. The heatmap's job is TRIAGE: see
// at a glance which pairs have something in them, then click one to open it in
// the scatter above. That click is why this figure earns its space -- it is a
// navigation control that happens to also be the data.
//
// Colour here encodes POLARITY, not magnitude, so the scale is diverging: two
// hues that read as opposites (the console's own blue for positive, red for
// negative) meeting at a neutral that reads as "nothing". A sequential ramp
// would make -0.9 and +0.9 look like the same finding, which is the exact
// mistake this chart exists to prevent.

import type { JSX } from "react";
import type { CorrelationResponse } from "../../types/engine";
import { labelOf } from "../../lib/scales";
import { Tooltip, useTooltip } from "./ChartFrame";

const CELL = 30;
const GUTTER_LEFT = 116;
const GUTTER_TOP = 104;
const PAD = 8;

/**
 * A cell's fill. |r| drives how far the colour travels from the neutral
 * midpoint; the sign picks which arm it travels along. Both arms use the same
 * step count, so a -0.4 and a +0.4 are equally far from the middle -- an
 * asymmetric ramp would make one sign look stronger than the other.
 *
 * color-mix does the interpolation in oklab, which keeps the ramp perceptually
 * even; mixing the same two colours in sRGB dips through a muddy middle.
 */
function fillFor(r: number | null): string {
  if (r === null) return "var(--fig-missing)";
  const strength = Math.min(1, Math.abs(r)) * 100;
  const pole = r >= 0 ? "var(--fig-pos)" : "var(--fig-neg)";
  return `color-mix(in oklab, ${pole} ${strength.toFixed(1)}%, var(--fig-neutral))`;
}

/**
 * The diagonal is a column against itself: r = 1 by definition, carrying no
 * information. Painting it the darkest blue on the chart -- as the colour rule
 * would -- puts the loudest marks on the only cells with nothing to say, and
 * the eye goes straight to them. It is drawn as neutral instead.
 */
const DIAGONAL_FILL = "var(--fig-neutral)";

export function CorrelationHeatmap({
  data,
  onPick,
  selected,
}: {
  data: CorrelationResponse;
  /** Clicking a cell loads that pair into the scatter plot. */
  onPick: (x: string, y: string) => void;
  /** The pair currently in the scatter, outlined here so the two figures agree. */
  selected?: { x: string; y: string } | undefined;
}): JSX.Element {
  const { tip, show, hide } = useTooltip();
  const columns = data.columns;
  const size = columns.length * CELL;
  const width = GUTTER_LEFT + size + PAD;
  const height = GUTTER_TOP + size + PAD;

  return (
    <>
      <svg className="fig-svg" viewBox={`0 0 ${width} ${height}`} role="img"
           aria-label={`Pearson correlation between ${columns.length} numeric columns`}>
        {columns.map((col, i) => (
          <text
            key={`top-${col}`}
            className="fig-axis-text"
            // Rotated about the label's own anchor point: 15 horizontal headers
            // at 30px pitch would overlap into an unreadable smear.
            transform={`translate(${GUTTER_LEFT + i * CELL + CELL / 2}, ${GUTTER_TOP - 8}) rotate(-52)`}
            textAnchor="start"
          >
            {labelOf(col)}
          </text>
        ))}

        {columns.map((rowCol, row) => (
          <g key={rowCol}>
            <text className="fig-axis-text" x={GUTTER_LEFT - 8}
                  y={GUTTER_TOP + row * CELL + CELL / 2 + 4} textAnchor="end">
              {labelOf(rowCol)}
            </text>
            {columns.map((colCol, col) => {
              // A ragged matrix would be a server bug, but an out-of-range read
              // is indistinguishable from a genuinely absent r, so treat both as
              // "not measured" rather than crashing the figure.
              const r = data.matrix[row]?.[col] ?? null;
              const isDiagonal = row === col;
              const isSelected =
                selected !== undefined &&
                ((selected.x === colCol && selected.y === rowCol) ||
                  (selected.x === rowCol && selected.y === colCol));
              return (
                <rect
                  key={colCol}
                  className={`fig-cell${isDiagonal ? " is-diagonal" : ""}${isSelected ? " is-selected" : ""}`}
                  x={GUTTER_LEFT + col * CELL}
                  y={GUTTER_TOP + row * CELL}
                  // 1px inset on each side: adjacent fills need a surface gap or
                  // a block of similar values reads as one shape.
                  width={CELL - 1}
                  height={CELL - 1}
                  fill={isDiagonal ? DIAGONAL_FILL : fillFor(r)}
                  onMouseMove={(event) =>
                    show(event, {
                      title: `${labelOf(rowCol)} × ${labelOf(colCol)}`,
                      rows: [["Pearson r", r === null ? "—" : r.toFixed(3)]],
                      note: isDiagonal
                        ? "A column against itself"
                        : r === null
                          ? `Fewer than ${data.min_overlap} overlapping values`
                          : "Click to plot this pair",
                    })
                  }
                  onMouseLeave={hide}
                  onClick={() => {
                    if (!isDiagonal && r !== null) onPick(colCol, rowCol);
                  }}
                />
              );
            })}
          </g>
        ))}
      </svg>
      <Tooltip tip={tip} />
    </>
  );
}

/**
 * The colour key. A diverging scale is unreadable without one — the reader has
 * no way to know which hue is which sign, or where the neutral sits.
 */
export function CorrelationLegend(): JSX.Element {
  const stops = [-1, -0.75, -0.5, -0.25, 0, 0.25, 0.5, 0.75, 1];
  return (
    <span className="fig-scale">
      <span className="fig-scale-end">−1 · inverse</span>
      {/* The swatches are one unit. Without this wrapper the key is 11 flex
          children and a narrow screen wraps it mid-ramp, which reads as two
          separate scales. */}
      <span className="fig-scale-ramp">
        {stops.map((stop) => (
          <i key={stop} className="fig-scale-step" style={{ background: fillFor(stop) }} />
        ))}
      </span>
      <span className="fig-scale-end">+1 · together</span>
    </span>
  );
}
