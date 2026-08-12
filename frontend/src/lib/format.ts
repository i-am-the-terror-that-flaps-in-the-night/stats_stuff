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
 * The longest label that can sit beside its value in one grid cell.
 *
 * A label-value cell is ~184px wide and the label does not wrap (wrapping it
 * would leave a ragged two-line key next to a single-line number, which reads
 * worse than either fix). So a long label simply takes the whole cell, and
 * whatever is left for the value can be a couple of characters -- at which
 * point `overflow-wrap: anywhere` on the value does exactly what it was asked
 * to and breaks "0.5011" into one digit per line.
 *
 * That was a real rendering bug: "Proportion At Or Above" and "Standardized
 * Beta" both blew past the space and printed their numbers vertically. The fix
 * is to decide by LABEL length as well as value type -- past this many
 * characters the pair gets its own full-width row, label above value, the same
 * treatment isWideValue() already gives a long string.
 *
 * The number is arithmetic, not taste. A cell is 208px wide with 14px padding
 * each side and a 14px gap, leaving 166px to split. The label renders at
 * 0.72rem (11.5px), 700 weight, uppercase, with 0.05em tracking -- about 7.7px
 * per letter. A value renders at 1rem, 800 weight, tabular figures: roughly
 * 9.5px per digit, so a typical "0.5011" or "16.04" needs ~50px.
 *
 * 166 - 50 = 116px of label, which is 15 characters. Past that the value is
 * squeezed. "Standardized Beta" (17) is the case that proves it matters -- it
 * sat just under an earlier, guessed limit of 18 and rendered its number
 * vertically anyway.
 */
export const MAX_INLINE_LABEL = 15;

/**
 * The longest single unbreakable token that still fits the value half of a cell.
 *
 * The other half of the same bug. A column name like "TrigHDLRatio" is one
 * 12-character word with no space or hyphen to break at, so it cannot be
 * wrapped politely -- it either fits or it is chopped mid-word ("TrigHDLRati /
 * o", which is what the page was doing). Values made of several short words are
 * fine, because they wrap at the spaces; only the longest token matters.
 *
 * 11 comes from the same budget as MAX_INLINE_LABEL, run the other way: a
 * value has ~90px once a short label has taken its share, and at ~8px per
 * character in the value's weight that is 11 characters.
 */
export const MAX_INLINE_TOKEN = 11;

function longestToken(text: string): number {
  return text.split(/[\s_-]+/).reduce((max, part) => Math.max(max, part.length), 0);
}

/**
 * True when a label-value pair needs its own full-width row rather than sharing
 * one grid cell.
 *
 * Three ways to earn it: a value that is already wide by type (a list or a long
 * string), a label too long to leave room beside it, or a value containing a
 * token too long to wrap. Any of the three produces the same unreadable cell,
 * so they get the same fix.
 */
export function isWidePair(key: string, value: EngineValue): boolean {
  if (isWideValue(value)) return true;
  if (prettify(key).length > MAX_INLINE_LABEL) return true;
  return typeof value === "string" && longestToken(value) > MAX_INLINE_TOKEN;
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
