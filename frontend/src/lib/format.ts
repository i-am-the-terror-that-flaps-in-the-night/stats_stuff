// Shape inspection and formatting for engine results.
//
// The engine returns an open-ended nested tree (see types/engine.ts), so the
// renderer decides what to draw by interrogating structure rather than by
// matching tier names. These guards are that interrogation, lifted out of the
// components so the rules live in one testable place. They are the typed
// equivalents of the old script.js helpers of the same names.

import type { EngineObject, EngineValue } from "../types/engine";

/** A non-null, non-array object. */
export function isPlainObject(value: EngineValue): value is EngineObject {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/**
 * A "leaf" is anything renderable in a single cell: a scalar, null, or an array
 * of scalars -- never a nested object.
 */
export function isLeaf(value: EngineValue): boolean {
  if (value === null || value === undefined) return true;
  const t = typeof value;
  if (t === "number" || t === "string" || t === "boolean") return true;
  if (Array.isArray(value)) return !value.some(isPlainObject);
  return false;
}

/**
 * A "record" is a flat object whose every value is a leaf -- one row's worth of
 * data. Two or more same-shaped sibling records render as a comparison matrix
 * instead of a stack of identical little tables.
 */
export function isRecord(value: EngineValue): value is EngineObject {
  if (!isPlainObject(value)) return false;
  const values = Object.values(value);
  return values.length > 0 && values.every(isLeaf);
}

/** "ci_lower" -> "ci lower" (the CSS uppercases the label). */
export function prettify(key: string): string {
  return String(key).replace(/_/g, " ");
}

/**
 * Prose, not a statistic. The engine now ships explanatory strings next to its
 * numbers -- what a p-value does and doesn't mean, why a threshold was refused,
 * the caveat on a standardized beta. Those are the point of the output, but they
 * are sentences: they get their own full-width note block rather than being
 * squeezed into a label-value cell built for "median 87".
 */
export function isProse(key: string, value: EngineValue): boolean {
  return typeof value === "string" && (value.length > 60 || PROSE_KEYS.has(key));
}

const PROSE_KEYS = new Set([
  "p_value_means",
  "caveat",
  "means",
  "note",
  "not_causal",
  "reason",
  "why",
  "why_it_is_not_automatic",
  "why_this_matters",
  "how_to_run",
  "information_loss",
  "assumes",
  "accuracy_warning",
  "assumption_warning",
  "threshold_means",
  "reading_the_change",
  "coefficients_mean",
  "iqr_rule_note",
  "covers",
]);

/**
 * A value too wide for the narrow right half of a label-value cell: a list
 * (predictors, confounders, group order) or a longish string. These span the
 * full row so they read left-to-right instead of stacking one word per line.
 */
export function isWideValue(value: EngineValue): boolean {
  if (Array.isArray(value)) return value.length > 2;
  return typeof value === "string" && value.length > 28;
}

/**
 * Keys worth plotting side by side -- same-scale descriptive figures that read
 * better as relative bar lengths than as a column of numbers. Anything else
 * (n, flags, lists, p-values) stays table-only.
 */
export const PLOTTABLE_KEYS = new Set([
  "mean", "median", "min", "max", "std", "variance",
  "q1", "q3", "iqr", "skewness", "kurtosis",
]);

/** A finite number, safe to plot or shade. */
export function isFiniteNumber(value: EngineValue): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** Split an object's entries into scalar rows and nested groups. */
export function partitionEntries(obj: EngineObject): {
  rows: [string, EngineValue][];
  groups: [string, EngineValue][];
  notes: [string, string][];
} {
  const rows: [string, EngineValue][] = [];
  const groups: [string, EngineValue][] = [];
  const notes: [string, string][] = [];

  for (const [key, value] of Object.entries(obj)) {
    if (isPlainObject(value) || (Array.isArray(value) && value.some(isPlainObject))) {
      groups.push([key, value]);
    } else if (isProse(key, value) && typeof value === "string") {
      notes.push([key, value]);
    } else {
      rows.push([key, value]);
    }
  }
  return { rows, groups, notes };
}

/**
 * The layer tag the engine stamps on each block (descriptive / inferential /
 * predictive). Surfaced in the UI because it is the whole point of the engine's
 * output contract: it says how strong a claim the numbers below it support.
 */
export function layerOf(obj: EngineObject): string | null {
  const layer = obj["layer"];
  return typeof layer === "string" ? layer : null;
}
