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
