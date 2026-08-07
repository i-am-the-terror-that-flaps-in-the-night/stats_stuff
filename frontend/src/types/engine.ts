// Types for what Backend/app.py returns.
//
// A deliberate design note on the analysis results: the engine's tier output is
// an open-ended, recursively nested object whose exact shape depends on the tier,
// the column and the data (a group block appears only when you pass a group; a
// clinical_threshold block can be "ran" or "not_run" with entirely different
// keys). Modelling every tier as an exact interface would be a large, brittle lie
// -- the moment engine.py adds a field, the type would be wrong rather than
// merely incomplete.
//
// So results are typed as a recursive JSON tree (`EngineValue`), and the renderer
// walks it structurally. Narrowing happens through the type guards in lib/format.ts,
// which is where the shape is actually interrogated. Everything with a FIXED,
// engine-guaranteed contract -- the column lists, the dataset overview, the run
// log -- gets a precise interface below.

/** Any value the engine can put in a JSON result. */
export type EngineValue =
  | string
  | number
  | boolean
  | null
  | EngineValue[]
  | { [key: string]: EngineValue };

/** A nested object inside a tier result. */
export type EngineObject = { [key: string]: EngineValue };

/** The analysis tiers, in depth order. Mirrors engine.py's public methods. */
export const TIERS = ["basic", "medium", "advanced", "expert", "categorical"] as const;
export type Tier = (typeof TIERS)[number];

/** Only these tiers run group comparisons, so only they show the group picker. */
export const GROUPING_TIERS = new Set<Tier>(["medium", "advanced", "expert"]);

export function isTier(value: string): value is Tier {
  return (TIERS as readonly string[]).includes(value);
}

/** GET /api/columns */
export interface ColumnsResponse {
  dataset: string;
  /** Numeric columns: the basic/medium/advanced/expert tiers run on these. */
  columns: string[];
  /** Label columns: the categorical tier and the group-by picker use these. */
  categorical: string[];
}

/** GET /api/overview -- dataset telemetry for the ribbon and Studio. */
export interface OverviewResponse {
  dataset: string;
  rows: number;
  columns: number;
  analyzable: number;
  categorical: number;
  complete_rows?: number;
  [key: string]: EngineValue | undefined;
}

/** One row of the Studio run log. GET /api/runs */
export interface RunRecord {
  id: number;
  when_short: string;
  when_long: string;
  tier: string;
  column: string;
  group: string | null;
  dataset: string;
  duration_ms: number;
  label: string;
}

/** One entry in the Studio dataset inventory. GET /api/datasets */
export interface DatasetInfo {
  label: string;
  available: boolean;
  blurb: string;
}

/** POST /api/runs body. */
export interface RecordRunBody {
  tier: string;
  column: string;
  group: string | null;
  duration_ms: number;
}

// ---- Figures -------------------------------------------------------------
//
// Unlike a tier result, these ARE precise interfaces. Backend/figures_api.py
// returns a fixed shape per route by construction -- there is no branching on
// the data the way engine.py branches on tier and column -- so the types can be
// exact, and a chart that indexes a field the server stopped sending should
// fail the typecheck rather than render an empty axis.

/** One bar of a histogram: a half-open bin [lo, hi) and how many landed in it. */
export interface HistogramBin {
  lo: number;
  hi: number;
  count: number;
}

/** GET /api/figures/histogram/{column} */
export interface HistogramResponse {
  column: string;
  n: number;
  min: number;
  max: number;
  mean: number;
  median: number;
  q1: number;
  q3: number;
  std: number | null;
  bins: HistogramBin[];
}

/** One box: the five-number summary plus what the whiskers excluded. */
export interface BoxSummary {
  label: string;
  n: number;
  q1: number;
  median: number;
  q3: number;
  mean: number;
  /** Whisker ends — the furthest real observations within 1.5 IQR of the box. */
  low: number;
  high: number;
  outliers: number;
}

/** GET /api/figures/box/{column}?group= */
export interface BoxResponse {
  column: string;
  group: string | null;
  boxes: BoxSummary[];
  /** Groups omitted for having fewer than `min_group_n` values. */
  dropped_groups: number;
  min_group_n: number;
}

/** GET /api/figures/scatter/{x}/{y} */
export interface ScatterResponse {
  x: string;
  y: string;
  /** Complete pairs in the dataset. `r` and the fit line are computed on all of them. */
  n: number;
  /** Points actually returned — capped, so a big dataset stays a small payload. */
  drawn: number;
  sampled: boolean;
  xs: number[];
  ys: number[];
  r: number;
  r_squared: number;
  slope: number;
  intercept: number;
  x_min: number;
  x_max: number;
  y_min: number;
  y_max: number;
}

/** GET /api/figures/correlation. `matrix[i][j]` is r for columns[i] vs columns[j]. */
export interface CorrelationResponse {
  columns: string[];
  /** null where a pair had too little overlap to correlate — not zero. */
  matrix: (number | null)[][];
  method: string;
  min_overlap: number;
}
