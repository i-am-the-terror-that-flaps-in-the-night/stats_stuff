// Box plot — the same column, split by a label column.
//
// This is the picture that belongs next to the medium tier's ANOVA. The test
// answers "are these groups distinguishable?"; a p-value of 0.0 says yes and
// says nothing about whether the difference is a whole BMI point or a rounding
// error. Five boxes side by side answer the question the p-value cannot: how
// much, in which direction, and with how much overlap.
//
// Every box is directly labelled on the axis, so colour is NOT carrying
// identity here -- all the boxes are one hue on purpose. Colouring them by group
// would mean colour-by-rank (change the grouping column and every box repaints),
// which is exactly the encoding that stops meaning anything.

import type { JSX } from "react";
import type { BoxResponse, BoxSummary } from "../../types/engine";
import { formatCount, formatTick, labelOf, linearScale, niceDomain, plotArea, ticks } from "../../lib/scales";
import { AxisLabel, GridLine, Tooltip, useNarrowChart, useTooltip } from "./ChartFrame";
import type { Layout } from "./ChartFrame";

const WIDE: Layout = { W: 720, H: 360, margin: { top: 18, right: 18, bottom: 68, left: 60 } };
// Taller in proportion, not just smaller: the group labels below the axis are
// the same words either way, and on a narrow space they need three lines.
const NARROW: Layout = { W: 360, H: 300, margin: { top: 14, right: 8, bottom: 74, left: 34 } };

/** Cap the drawn box width so two groups don't render as two slabs. */
const MAX_BOX = 68;

/** Wrap a long group label onto at most two lines of `width` characters. */
function wrapLabel(label: string, width: number): string[] {
  if (label.length <= width) return [label];
  const words = label.split(/[\s/]+/);
  const lines: string[] = [];
  let line = "";
  for (const word of words) {
    if ((line + " " + word).trim().length > width && line) {
      lines.push(line);
      line = word;
    } else {
      line = (line + " " + word).trim();
    }
  }
  if (line) lines.push(line);
  return lines.slice(0, 3);
}

export function BoxPlot({ data }: { data: BoxResponse }): JSX.Element {
  const { tip, show, hide } = useTooltip();
  const narrow = useNarrowChart();
  const { W, H, margin: MARGIN } = narrow ? NARROW : WIDE;
  const wrapAt = narrow ? 9 : 14;
  const lineHeight = 12;
  const plot = plotArea(W, H, MARGIN);
  const boxes = data.boxes;

  const lo = Math.min(...boxes.map((b) => b.low));
  const hi = Math.max(...boxes.map((b) => b.high));
  const [yLo, yHi] = niceDomain(lo, hi, 5);
  const y = linearScale([yLo, yHi], [plot.bottom, plot.top]);

  const slot = plot.innerWidth / boxes.length;
  const boxWidth = Math.min(MAX_BOX, slot * 0.55);
  const centerOf = (index: number): number => plot.left + slot * (index + 0.5);

  const tipFor = (box: BoxSummary): Parameters<typeof show>[1] => ({
    title: box.label,
    rows: [
      ["Median", formatTick(box.median)],
      ["IQR", `${formatTick(box.q1)} – ${formatTick(box.q3)}`],
      ["Whiskers", `${formatTick(box.low)} – ${formatTick(box.high)}`],
      ["Mean", formatTick(box.mean)],
      ["n", formatCount(box.n)],
    ],
    note: box.outliers > 0 ? `${formatCount(box.outliers)} beyond 1.5 × IQR, not drawn` : undefined,
  });

  return (
    <>
      <svg className="fig-svg" viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label={`${labelOf(data.column)} by ${data.group ? labelOf(data.group) : "all rows"}`}>
        {ticks(yLo, yHi, 5).map((t) => (
          <g key={t}>
            <GridLine x1={plot.left} x2={plot.right} y1={y(t)} y2={y(t)} />
            <AxisLabel x={plot.left - 8} y={y(t) + 4} anchor="end">
              {formatTick(t)}
            </AxisLabel>
          </g>
        ))}

        {boxes.map((box, index) => {
          const cx = centerOf(index);
          const left = cx - boxWidth / 2;
          const top = y(box.q3);
          const height = Math.max(1, y(box.q1) - y(box.q3));
          return (
            <g className="fig-box" key={box.label}>
              {/* Whisker stem and caps. */}
              <line className="fig-whisker" x1={cx} x2={cx} y1={y(box.high)} y2={y(box.q3)} />
              <line className="fig-whisker" x1={cx} x2={cx} y1={y(box.q1)} y2={y(box.low)} />
              <line className="fig-whisker-cap" x1={cx - boxWidth / 4} x2={cx + boxWidth / 4}
                    y1={y(box.high)} y2={y(box.high)} />
              <line className="fig-whisker-cap" x1={cx - boxWidth / 4} x2={cx + boxWidth / 4}
                    y1={y(box.low)} y2={y(box.low)} />

              <rect className="fig-box-body" x={left} y={top} width={boxWidth} height={height} />
              <line className="fig-box-median" x1={left} x2={left + boxWidth}
                    y1={y(box.median)} y2={y(box.median)} />
              {/* The mean, as a hollow dot — a second statistic, so a second mark
                  shape. Its distance from the median line is the skew. */}
              <circle className="fig-box-mean" cx={cx} cy={y(box.mean)} r={3.5} />

              {/* One transparent hit target per box, spanning the whole slot: the
                  drawn marks are thin lines, and a 2px hover target is a target
                  nobody hits. */}
              <rect
                className="fig-hit"
                x={cx - slot / 2}
                y={plot.top}
                width={slot}
                height={plot.innerHeight}
                onMouseMove={(event) => show(event, tipFor(box))}
                onMouseLeave={hide}
              />

              {wrapLabel(box.label, wrapAt).map((line, lineIndex) => (
                <AxisLabel key={line} x={cx} y={plot.bottom + 16 + lineIndex * lineHeight}>
                  {line}
                </AxisLabel>
              ))}
              <AxisLabel
                x={cx}
                y={plot.bottom + 18 + wrapLabel(box.label, wrapAt).length * lineHeight}
                className="is-faint"
              >
                n = {formatCount(box.n)}
              </AxisLabel>
            </g>
          );
        })}

        <line className="fig-axis" x1={plot.left} x2={plot.right} y1={plot.bottom} y2={plot.bottom} />
        <AxisLabel x={plot.left} y={plot.top - 5} anchor="start" className="is-title">
          {labelOf(data.column)}
        </AxisLabel>
      </svg>
      <Tooltip tip={tip} />
    </>
  );
}

export function BoxLegend(): JSX.Element {
  return (
    <>
      <span className="fig-key">
        <i className="fig-key-mark is-box" /> Middle 50% (Q1–Q3)
      </span>
      <span className="fig-key">
        <i className="fig-key-mark is-medianline" /> Median
      </span>
      <span className="fig-key">
        <i className="fig-key-mark is-meandot" /> Mean
      </span>
      <span className="fig-key">
        <i className="fig-key-mark is-whisker" /> Range within 1.5 × IQR
      </span>
    </>
  );
}
