// Flattening an engine result into a ledger.
//
// The Studio shows one analysis as a flat table of (label, value) rows plus a
// bar chart, rather than the nested tree the Overview renders. That flattening
// used to happen in Python (studio.py built the rows and the bar widths); it
// lives here now so the backend serves one JSON shape and both views are just
// different readings of it.

import type { EngineObject, EngineValue } from "../types/engine";
import { isFiniteNumber, isPlainObject, PLOTTABLE_KEYS } from "./format";

/**
 * One statistic as ledger text -- readable, never a raw repr.
 * Numbers are trimmed to four significant figures: the engine already rounds,
 * but a ratio like 2.4509999999 would otherwise blow out the column.
 */
export function scalar(value: EngineValue): string {
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (value === null || value === undefined) return "n/a";
  if (typeof value === "number") {
    return Number.isFinite(value) ? String(Number(value.toPrecision(4))) : "n/a";
  }
  if (Array.isArray(value)) return value.map(scalar).join(", ") || "n/a";
  if (isPlainObject(value)) {
    return (
      Object.entries(value)
        .map(([k, v]) => `${k}: ${scalar(v)}`)
        .join(", ") || "n/a"
    );
  }
  return String(value);
}

/**
 * Flatten a result into (label, value) rows, expanding nested objects one level
 * as "parent.child" so the table stays flat and scannable.
 */
export function resultRows(result: EngineObject): [string, string][] {
  const rows: [string, string][] = [];
  for (const [key, value] of Object.entries(result)) {
    if (key === "error") continue;
    if (isPlainObject(value)) {
      for (const [sub, subValue] of Object.entries(value)) {
        rows.push([`${key}.${sub}`, scalar(subValue)]);
      }
    } else {
      rows.push([key, scalar(value)]);
    }
  }
  return rows;
}

/**
 * Plottable numbers, found at the top level or at any depth of nesting.
 * Only same-scale descriptive figures qualify (see PLOTTABLE_KEYS) -- putting a
 * p-value and a variance on one axis would be meaningless.
 */
export function chartRows(result: EngineObject): [string, number][] {
  const rows: [string, number][] = [];
  const collect = (obj: EngineObject): void => {
    for (const [key, value] of Object.entries(obj)) {
      if (PLOTTABLE_KEYS.has(key) && isFiniteNumber(value)) rows.push([key, value]);
      else if (isPlainObject(value)) collect(value);
    }
  };
  collect(result);
  return rows;
}

/** Bar widths as percentages of the largest magnitude in the set. */
export function chartBars(
  rows: [string, number][],
): { label: string; value: number; pct: number }[] {
  const maxAbs = Math.max(1e-9, ...rows.map(([, v]) => Math.abs(v)));
  return rows.map(([label, value]) => ({
    label,
    value,
    pct: (Math.abs(value) / maxAbs) * 100,
  }));
}
