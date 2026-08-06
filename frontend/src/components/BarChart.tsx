// A compact horizontal bar chart: inline SVG, no charting library.
//
// Shared by the Overview's result tree and the Studio's ledger so both draw the
// same bars from the same code. Bars scale to the largest magnitude in the set;
// a negative value gets a distinct fill and its exact signed figure in a tooltip.

import type { JSX } from "react";
import { prettify } from "../lib/format";
import { chartBars } from "../lib/ledger";

export function BarChart({
  entries,
  format = String,
}: {
  entries: [string, number][];
  /** How to render the value label; the ledger trims to 4 significant figures. */
  format?: (value: number) => string;
}): JSX.Element {
  return (
    <div className="stat-chart">
      {chartBars(entries).map(({ label, value, pct }) => (
        <div className="stat-chart-row" key={label}>
          <span className="stat-chart-label">{prettify(label)}</span>
          <svg
            className="stat-chart-track"
            viewBox="0 0 100 10"
            preserveAspectRatio="none"
            role="img"
            aria-label={`${prettify(label)}: ${value}`}
          >
            <rect
              x="0"
              y="0"
              width={pct}
              height="10"
              className={`stat-chart-bar${value < 0 ? " is-neg" : ""}`}
            >
              <title>{`${prettify(label)}: ${value}`}</title>
            </rect>
          </svg>
          <span className="stat-chart-value">{format(value)}</span>
        </div>
      ))}
    </div>
  );
}
