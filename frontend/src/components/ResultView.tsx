// Renders an engine result.
//
// The engine's output shape varies by tier, column and data, so nothing here is
// hard-coded to a tier: the tree is walked structurally. Scalars collect into a
// stat grid, same-shaped sibling records collapse into one comparison matrix,
// and anything else recurses as a titled sub-group. This is the React port of
// renderInto/renderStat/renderBarChart/renderMatrix from the old script.js, with
// one addition -- the engine's explanatory prose gets its own note treatment
// instead of being crammed into a value cell.

import type { JSX } from "react";
import type { EngineObject, EngineValue } from "../types/engine";
import { BarChart } from "./BarChart";
import {
  isFiniteNumber,
  isPlainObject,
  isRecord,
  isWideValue,
  layerOf,
  partitionEntries,
  prettify,
  PLOTTABLE_KEYS,
} from "../lib/format";

/** A leaf value: booleans become a coloured verdict, nulls a faint dash. */
function Value({ value }: { value: EngineValue }): JSX.Element {
  if (value === null || value === undefined) {
    return <span className="value-null">—</span>;
  }
  if (typeof value === "boolean") {
    return (
      <span className={`value-flag ${value ? "is-true" : "is-false"}`}>
        {value ? "YES" : "NO"}
      </span>
    );
  }
  if (Array.isArray(value)) {
    return <>{value.length ? value.map((v) => String(v)).join(", ") : "—"}</>;
  }
  return <>{String(value)}</>;
}

/** One statistic as a compact label-value cell. */
function Stat({ statKey, value }: { statKey: string; value: EngineValue }): JSX.Element {
  return (
    <div className={isWideValue(value) ? "stat is-wide" : "stat"}>
      <span className="stat-k">{prettify(statKey)}</span>
      <span className="stat-v">
        <Value value={value} />
      </span>
    </div>
  );
}

/**
 * The engine's explanatory prose. These sentences are the difference between a
 * number and a claim you can trust, so they are rendered as readable notes
 * rather than hidden or truncated.
 */
function Note({ noteKey, text }: { noteKey: string; text: string }): JSX.Element {
  return (
    <p className="result-note">
      <span className="result-note-k">{prettify(noteKey)}</span>
      <span className="result-note-v">{text}</span>
    </p>
  );
}

/**
 * Same-shaped record groups as one matrix: a row per group, a column per metric.
 * Columns are the union of the records' keys in first-seen order, so ragged
 * records still line up and gaps show as a dash. Each column shades against its
 * own range -- a duration_ms column and a p_value column live on wildly
 * different scales and must not share a gradient.
 */
function Matrix({ entries }: { entries: [string, EngineObject][] }): JSX.Element {
  const cols: string[] = [];
  const seen = new Set<string>();
  for (const [, rec] of entries) {
    for (const key of Object.keys(rec)) {
      if (!seen.has(key)) {
        seen.add(key);
        cols.push(key);
      }
    }
  }

  const ranges = new Map<string, [number, number]>();
  for (const col of cols) {
    const nums = entries
      .map(([, rec]) => rec[col])
      .filter((v): v is number => v !== undefined && isFiniteNumber(v));
    if (nums.length >= 2) ranges.set(col, [Math.min(...nums), Math.max(...nums)]);
  }

  return (
    <div className="results-scroll">
      <table className="matrix">
        <thead>
          <tr>
            <th className="matrix-corner" />
            {cols.map((col) => (
              <th key={col}>{prettify(col)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {entries.map(([name, rec]) => (
            <tr key={name}>
              <th className="matrix-row-label" scope="row">
                {prettify(name)}
              </th>
              {cols.map((col) => {
                const raw = col in rec ? (rec[col] ?? null) : null;
                const range = ranges.get(col);
                const heat =
                  range && isFiniteNumber(raw)
                    ? range[1] > range[0]
                      ? (raw - range[0]) / (range[1] - range[0])
                      : 0.5
                    : null;
                return (
                  <td
                    key={col}
                    className={heat === null ? "value" : "value is-heat"}
                    {...(heat === null
                      ? {}
                      : { style: { ["--heat" as string]: heat.toFixed(3) } })}
                  >
                    <Value value={raw} />
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Recursively render one object's contents into the current container. */
function Nodes({ obj }: { obj: EngineObject }): JSX.Element {
  const { rows, groups, notes } = partitionEntries(obj);

  const chartable = rows.filter(
    (entry): entry is [string, number] =>
      PLOTTABLE_KEYS.has(entry[0]) && isFiniteNumber(entry[1]),
  );

  // Two or more sibling groups that are all flat, same-kind records collapse
  // into a single comparison matrix.
  const asMatrix =
    groups.length >= 2 && groups.every(([, v]) => isRecord(v))
      ? (groups as [string, EngineObject][])
      : null;

  return (
    <>
      {rows.length > 0 && (
        <div className="stat-list">
          {rows.map(([key, value]) => (
            <Stat statKey={key} value={value} key={key} />
          ))}
        </div>
      )}

      {chartable.length >= 2 && <BarChart entries={chartable} />}

      {notes.map(([key, text]) => (
        <Note noteKey={key} text={text} key={key} />
      ))}

      {asMatrix ? (
        <Matrix entries={asMatrix} />
      ) : (
        groups.map(([key, value]) => (
          <div className="result-group" key={key}>
            <p className="result-group-title">{prettify(key)}</p>
            {Array.isArray(value)
              ? value.map((item, i) =>
                  isPlainObject(item) ? <Nodes obj={item} key={i} /> : null,
                )
              : isPlainObject(value) && <Nodes obj={value} />}
          </div>
        ))
      )}
    </>
  );
}

export interface ResultViewProps {
  result: EngineObject;
  tier: string;
  elapsedMs: number;
}

export function ResultView({ result, tier, elapsedMs }: ResultViewProps): JSX.Element {
  const layer = layerOf(result);
  return (
    <div className={`results${tier === "expert" ? " is-expert" : ""}`} id="results">
      <div className="results-head">
        <span className="results-head-k">Result</span>
        <span className="results-head-tier">{tier}</span>
        {layer && <span className="results-head-layer">{layer}</span>}
        <span className="results-head-ms">{elapsedMs} ms</span>
      </div>
      <Nodes obj={result} />
    </div>
  );
}
