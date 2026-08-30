// A horizontal bar chart: one inline SVG, no charting library.
//
// Shared by the Overview's result tree, the Studio's ledger and the outlier
// experiment, so all three draw the same bars from the same code. Bars scale to
// the largest magnitude in the set; a negative value gets a distinct fill and
// its exact signed figure in a tooltip.
//
// ONE <svg>, NOT ONE PER ROW
//   This was an HTML flex row per bar with a tiny <svg> holding only the track.
//   It drew correctly and it could not be exported: lib/svgExport.ts walks a
//   single SVG, and the labels and the values — the half of the figure that says
//   what the bars mean — lived in HTML beside it, so a download would have
//   produced six anonymous rectangles. Drawing the whole thing in one coordinate
//   space is what lets it save as a PDF, a PNG or an SVG like every other chart
//   on the site.

import { useRef } from "react";
import type { JSX } from "react";
import { prettify } from "../lib/format";
import { chartBars } from "../lib/ledger";
import { SaveControl, useNarrowChart } from "./figures/ChartFrame";

/** The drawing space: a fixed width, and gutters wide enough for the text. */
interface Space {
  /** viewBox width. Height is derived from the row count. */
  W: number;
  /** Vertical pitch of one bar. */
  row: number;
  pad: number;
  /** Left gutter, holding the row name. */
  label: number;
  /** Right gutter, holding the figure. */
  value: number;
  /** Type size for the row name; the figure is set a little larger. */
  text: number;
}

// Two spaces for the same reason every other chart here has two: a viewBox
// scales its text along with everything else, so a 720-wide drawing painted
// into a phone column renders its labels at half legibility. See useNarrowChart.
//
// The type sizes look small written down because they are not pixels. The wide
// space is 720 units drawn across a 1200px column, so everything here lands on
// screen about 1.67x larger than the number says: `text: 7` is a 12px label.
const WIDE: Space = { W: 720, row: 17, pad: 6, label: 104, value: 74, text: 7 };
const NARROW: Space = { W: 360, row: 20, pad: 6, label: 88, value: 62, text: 10 };

/** Bar thickness, in the same units as the viewBox. */
const BAR = { wide: 9, narrow: 10 };

export function BarChart({
  entries,
  format = String,
  title,
}: {
  entries: [string, number][];
  /** How to render the value label; the ledger trims to 4 significant figures. */
  format?: (value: number) => string;
  /**
   * Names the figure and turns on the save control. Left out, the chart draws
   * without a head — which is what the recursive result tree wants for the
   * nested groups, where a title per bar chart would be more chrome than data.
   */
  title?: string;
}): JSX.Element {
  // The export reads the live <svg> back out of the DOM, so keep a handle on
  // the element that wraps it. A ref rather than a selector: a result tree can
  // hold several of these and a query would export whichever came first.
  const plotRef = useRef<HTMLDivElement | null>(null);
  const narrow = useNarrowChart();
  const space = narrow ? NARROW : WIDE;
  const bar = narrow ? BAR.narrow : BAR.wide;
  const bars = chartBars(entries);

  const height = space.pad * 2 + bars.length * space.row;
  const trackX = space.label;
  const trackWidth = space.W - space.label - space.value;

  return (
    <div className="stat-chart">
      {title && (
        <div className="stat-chart-head">
          <span className="stat-chart-title">{title}</span>
          <SaveControl plotRef={plotRef} title={title} />
        </div>
      )}
      <div className="stat-chart-plot" ref={plotRef}>
        <svg
          className="fig-svg"
          viewBox={`0 0 ${space.W} ${height}`}
          role="img"
          aria-label={
            title ?? `Bar chart of ${bars.map((bar) => prettify(bar.label)).join(", ")}`
          }
        >
          {bars.map(({ label, value, pct }, index) => {
            const top = space.pad + index * space.row + (space.row - bar) / 2;
            // Baseline offset: text is positioned from its baseline, so centring
            // it on the bar means dropping it by roughly a third of its size.
            const baseline = top + bar / 2 + space.text * 0.36;
            return (
              <g key={label}>
                <text
                  className="stat-chart-label"
                  x={0}
                  y={baseline}
                  fontSize={space.text}
                >
                  {prettify(label)}
                </text>
                <rect
                  className="stat-chart-track"
                  x={trackX}
                  y={top}
                  width={trackWidth}
                  height={bar}
                />
                <rect
                  className={`stat-chart-bar${value < 0 ? " is-neg" : ""}`}
                  x={trackX}
                  y={top}
                  width={Math.max(0, (pct / 100) * trackWidth)}
                  height={bar}
                >
                  <title>{`${prettify(label)}: ${value}`}</title>
                </rect>
                <text
                  className="stat-chart-value"
                  x={space.W}
                  y={baseline}
                  fontSize={space.text * 1.2}
                  textAnchor="end"
                >
                  {format(value)}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
