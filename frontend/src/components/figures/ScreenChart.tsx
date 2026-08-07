// Multiple comparisons — every p-value against the thresholds it must clear.
//
// One dot per column, sorted by p-value, plotted on a LOG y-axis because
// p-values span thirty orders of magnitude here and a linear axis would pile
// every real result onto the floor.
//
// Three reference lines, and the gaps between them are the entire lesson:
//
//   α            what a single test has to beat — the line people quote
//   α/m          Bonferroni: what a test has to beat when you ran m of them
//   α·rank/m     Benjamini-Hochberg: a SLOPED line, stricter for the weakest
//                results and nearly as forgiving as α for the strongest
//
// A dot between the α line and the sloped line is a result that would be
// reported as "significant" by anyone who ran fifteen tests and mentioned one.

import type { JSX } from "react";
import type { ScreenResponse } from "../../types/engine";
import { labelOf, linearScale, plotArea } from "../../lib/scales";
import { AxisLabel, GridLine, Tooltip, useNarrowChart, useTooltip } from "./ChartFrame";
import type { Layout } from "./ChartFrame";

const WIDE: Layout = { W: 720, H: 360, margin: { top: 18, right: 22, bottom: 78, left: 58 } };
const NARROW: Layout = { W: 360, H: 300, margin: { top: 14, right: 12, bottom: 84, left: 40 } };

/**
 * The smallest p-value the axis will show; anything below pins to the floor.
 *
 * Set by what the chart is FOR. p-values here reach 1e-263, and an axis that
 * honoured that would compress the three threshold lines — which all sit within
 * one decade of each other near p = 1 — into a couple of pixels at the top,
 * making the one comparison this figure exists to show impossible to read. Eight
 * decades puts the decision region across the upper third with the lines clearly
 * apart, and a dot on the floor is not misreported: it is already past every
 * threshold, and its tooltip still carries the real number.
 */
const FLOOR_EXPONENT = -8;

export function ScreenChart({ data }: { data: ScreenResponse }): JSX.Element {
  const { tip, show, hide } = useTooltip();
  const narrow = useNarrowChart();
  const { W, H, margin: MARGIN } = narrow ? NARROW : WIDE;
  const plot = plotArea(W, H, MARGIN);

  const tests = data.tests;
  if (tests.length === 0) return <p className="text">No column could be tested against this group.</p>;

  // log10(p), clamped. A p-value of 0 after underflow, or 1e-263, would stretch
  // the axis until everything else was a single line — the floor keeps the
  // region people actually argue about (1e-6 to 1) readable, and a pinned dot
  // is honest because its tooltip still carries the real number.
  const logP = (p: number): number => Math.max(FLOOR_EXPONENT, Math.log10(Math.max(p, 1e-300)));
  const lowest = Math.min(...tests.map((t) => logP(t.p_value)));
  const y = linearScale([Math.floor(lowest), 0], [plot.bottom, plot.top]);
  const x = linearScale([1, tests.length], [plot.left, plot.right]);

  const decades: number[] = [];
  for (let e = 0; e >= Math.floor(lowest); e -= narrow ? 2 : 1) decades.push(e);

  const bhLine = tests
    .map((t) => `${x(t.rank)},${y(logP(data.alpha * (t.rank / data.tests_run)))}`)
    .join(" ");

  return (
    <>
      <svg className="fig-svg" viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label={`p-values for ${data.tests_run} columns against ${labelOf(data.group)}`}>
        {decades.map((e) => (
          <g key={e}>
            <GridLine x1={plot.left} x2={plot.right} y1={y(e)} y2={y(e)} />
            <AxisLabel x={plot.left - 8} y={y(e) + 4} anchor="end">
              {e === 0 ? "1" : `1e${e}`}
            </AxisLabel>
          </g>
        ))}

        <line className="fig-thresh is-alpha" x1={plot.left} x2={plot.right}
              y1={y(logP(data.alpha))} y2={y(logP(data.alpha))} />
        <line className="fig-thresh is-bonferroni" x1={plot.left} x2={plot.right}
              y1={y(logP(data.bonferroni_alpha))} y2={y(logP(data.bonferroni_alpha))} />
        <polyline className="fig-thresh is-bh" points={bhLine} fill="none" />

        {tests.map((test) => {
          const cx = x(test.rank);
          const cy = y(logP(test.p_value));
          // Survives everything / survives only the lenient correction / fails.
          // Shape as well as fill, so the three states are not colour-only.
          const state = test.bonferroni ? "is-strong" : test.benjamini_hochberg ? "is-weak" : "is-none";
          return (
            <g key={test.column}>
              <circle className={`fig-screen-dot ${state}`} cx={cx} cy={cy} r={5} />
              <rect
                className="fig-hit"
                x={cx - plot.innerWidth / (tests.length * 2)}
                y={plot.top}
                width={plot.innerWidth / tests.length}
                height={plot.innerHeight}
                onMouseMove={(event) =>
                  show(event, {
                    title: labelOf(test.column),
                    rows: [
                      ["p-value", test.p_value.toExponential(2)],
                      ["Effect (η²)", test.eta_squared.toFixed(4)],
                      ["Survives α", test.raw ? "yes" : "no"],
                      ["Survives Bonferroni", test.bonferroni ? "yes" : "no"],
                      ["Survives B–H", test.benjamini_hochberg ? "yes" : "no"],
                    ],
                    note:
                      test.eta_squared < 0.01
                        ? "η² under 0.01 — under 1% of the variation, whatever the p-value says"
                        : undefined,
                  })
                }
                onMouseLeave={hide}
              />
              {/* Angled DOWN-LEFT from the tick (anchor end, negative rotation),
                  not down-right. Down-right runs the rightmost label off the
                  edge of the plot; this way every label stays inside the box its
                  tick is in. */}
              <text
                className="fig-axis-text"
                transform={`translate(${cx - 2}, ${plot.bottom + 12}) rotate(-42)`}
                textAnchor="end"
              >
                {labelOf(test.column)}
              </text>
            </g>
          );
        })}

        <line className="fig-axis" x1={plot.left} x2={plot.right} y1={plot.bottom} y2={plot.bottom} />
        <AxisLabel x={plot.left} y={plot.top - 5} anchor="start" className="is-title">
          p-value (log scale)
        </AxisLabel>
      </svg>
      <Tooltip tip={tip} />
    </>
  );
}

export function ScreenLegend({ data }: { data: ScreenResponse }): JSX.Element {
  const pinned = data.tests.filter(
    (t) => Math.log10(Math.max(t.p_value, 1e-300)) < FLOOR_EXPONENT,
  ).length;
  return (
    <>
      <span className="fig-key">
        <i className="fig-key-mark is-strong-dot" /> Survives Bonferroni
      </span>
      {pinned > 0 && (
        <span className="fig-key">
          {pinned} {pinned === 1 ? "dot sits" : "dots sit"} on the floor — smaller than 1e
          {FLOOR_EXPONENT}
        </span>
      )}
      <span className="fig-key">
        <i className="fig-key-mark is-weak-dot" /> Survives B–H only
      </span>
      <span className="fig-key">
        <i className="fig-key-mark is-none-dot" /> Survives neither
      </span>
      <span className="fig-key">
        <i className="fig-key-mark is-alpha-line" /> α = {data.alpha}
      </span>
      <span className="fig-key">
        <i className="fig-key-mark is-bh-line" /> B–H threshold
      </span>
    </>
  );
}
