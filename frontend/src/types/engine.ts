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
  /**
   * The distinct labels of each categorical column, most common first, so the
   * Studio's cohort builder can offer them instead of asking for them typed.
   * Optional: an older backend does not send it, and the builder falls back to
   * a free-text box rather than rendering an empty dropdown.
   */
  values?: Record<string, string[]>;
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

/** One kernel density curve, evaluated on the response's shared grid. */
export interface DensityCurve {
  label: string;
  n: number;
  mean: number;
  median: number;
  /** The smoothing width, in the column's own units. A curve is a choice as
   *  much as a measurement, and this is the choice. */
  bandwidth: number;
  /** Heights at each x in `grid` — same length, same order. */
  density: number[];
}

/** GET /api/figures/density/{column} */
export interface DensityResponse {
  column: string;
  group: string | null;
  /** The x values every curve is evaluated at, shared so areas are comparable. */
  grid: number[];
  curves: DensityCurve[];
  /** The tallest point across all curves — the y-domain, already computed. */
  peak: number;
  dropped_groups: number;
  min_group_n: number;
  method: string;
}

/** GET /api/figures/diagnostics/{model} — residual geometry for one study model. */
export interface DiagnosticsResponse {
  model: string;
  label: string;
  outcome: string;
  predictors: string[];
  n: number;
  r_squared: number | null;
  residual_sd: number | null;
  residual_skewness: number | null;
  residual_kurtosis: number | null;
  /** Parallel arrays: fitted[i] pairs with residuals[i]. */
  fitted: number[];
  residuals: number[];
  fitted_min: number;
  fitted_max: number;
  residual_min: number;
  residual_max: number;
  /** Sorted, so qq_theoretical[i] pairs with qq_observed[i]. */
  qq_theoretical: number[];
  qq_observed: number[];
  /** The line through the first and third quartiles, not the identity. */
  qq_line: { slope: number; intercept: number };
  note: string;
}

/** The three model specifications a diagnostic plot can be drawn for. */
export const DIAGNOSTIC_MODELS = ["lifestyle", "total-effect", "direct-effect"] as const;
export type DiagnosticModel = (typeof DIAGNOSTIC_MODELS)[number];

/** GET /api/figures/correlation. `matrix[i][j]` is r for columns[i] vs columns[j]. */
export interface CorrelationResponse {
  columns: string[];
  /** null where a pair had too little overlap to correlate — not zero. */
  matrix: (number | null)[][];
  method: string;
  min_overlap: number;
}

// ---- The lab (Studio experiments) ----------------------------------------

/** The summary block every experiment reports, so two can be read side by side. */
export interface Summary {
  n: number;
  mean: number | null;
  median: number | null;
  std: number | null;
  min: number | null;
  max: number | null;
}

/** One filter as the server parsed it, with the rows left after applying it. */
export interface AppliedFilter {
  column: string;
  op: string;
  value: string;
  remaining: number;
}

/** GET /api/lab/cohort/{column}?f=… */
export interface CohortResponse {
  column: string;
  filters: AppliedFilter[];
  rows_total: number;
  rows_kept: number;
  kept_share: number | null;
  cohort: Summary;
  overall: Summary;
  /** How far the cohort mean sits from the overall mean, in overall SDs. */
  shift_in_sds: number | null;
  too_small: boolean;
  min_cohort: number;
}

/** One rung of the sample-size ladder: what studies of this size concluded. */
export interface SizeRung {
  n: number;
  mean_of_means: number;
  lo: number;
  hi: number;
  width: number;
  miss_rate: number;
}

/** GET /api/lab/sample-size/{column} */
export interface SampleSizeResponse {
  column: string;
  seed: number;
  population_n: number;
  population_mean: number;
  draws_per_rung: number;
  rungs: SizeRung[];
}

/** GET /api/lab/bootstrap/{column} */
export interface BootstrapResponse {
  column: string;
  statistic: string;
  seed: number;
  n: number;
  draws: number;
  observed: number;
  ci_lower: number;
  ci_upper: number;
  std_error: number;
  bins: HistogramBin[];
}

/** One outlier policy applied to a column. */
export interface OutlierVariant extends Summary {
  rule: string;
  blurb: string;
  removed: number;
  removed_share: number;
  mean_shift: number;
  std_shift: number;
}

/** GET /api/lab/outliers/{column} */
export interface OutliersResponse {
  column: string;
  fences: [number, number];
  results: OutlierVariant[];
}

/** One column's test in the bulk screen, with each correction's verdict. */
export interface ScreenTest {
  column: string;
  p_value: number;
  f_statistic: number;
  eta_squared: number;
  n: number;
  groups: number;
  rank: number;
  raw: boolean;
  bonferroni: boolean;
  benjamini_hochberg: boolean;
  bh_threshold: number | null;
}

/** GET /api/lab/screen?group=… */
export interface ScreenResponse {
  group: string;
  alpha: number;
  tests_run: number;
  /** How many "findings" you would expect if nothing were really different. */
  false_positives_expected: number;
  bonferroni_alpha: number;
  counts: { raw: number; bonferroni: number; benjamini_hochberg: number };
  tests: ScreenTest[];
  not_causal: string;
}

// ---- The study ------------------------------------------------------------
// Backend/engine.py's ten-step analysis (part three). These types cover the shapes the Study
// page actually reads; each step also carries prose fields (interpretation,
// caveat, note) that vary by step and are pulled through an index signature
// rather than enumerated, so adding a caveat server-side never breaks the build.

/** The three grades of claim the protocol pre-specifies. */
export type ClaimGrade = "primary" | "supporting" | "exploratory";

/** The significance block every test in the engine returns. */
export interface Significance {
  p_value: number | null;
  /** "< 0.0001" where the rounded p_value would read as a misleading 0. */
  p_value_text?: string;
  alpha: number;
  statistically_significant: boolean;
  p_value_means: string;
  caveat: string;
}

/** One fitted coefficient, with its robust interval. */
export interface Coefficient {
  estimate: number | null;
  std_error: number | null;
  t: number | null;
  ci_low: number | null;
  ci_high: number | null;
  standardized_beta: number | null;
  significance: Significance;
}

/** One weighted, cluster-robust model fit. */
export interface StudyModel {
  label: string;
  outcome: string;
  predictors: string[];
  n: number;
  clusters: number;
  r_squared: number | null;
  adjusted_r_squared: number | null;
  coefficients: Record<string, Coefficient>;
  estimator: string;
  layer: string;
  not_causal: string;
}

/** One row of the cohort attrition table. */
export interface AttritionRow {
  step: string;
  rule: string;
  n: number;
  removed: number | null;
  note?: string;
}

/**
 * One step of the study. The fields every step shares are named; the rest vary
 * by step (a model here, a quartile table there) and are read through the index
 * signature by the renderer that knows which step it is looking at.
 */
export interface StudyStep {
  step?: number;
  title: string;
  grade: ClaimGrade;
  layer: string;
  question: string;
  n?: number;
  interpretation?: string;
  caveat?: string;
  note?: string;
  not_causal?: string;
  [key: string]: unknown;
}


/**
 * One sugar quartile, as step 6 reports it.
 *
 * Typed here rather than read through StudyStep's index signature because the
 * dose-response figure draws an error bar from `standard_error_alt` and a
 * position from `weighted_mean_alt`, and a chart that silently plots `undefined`
 * is worse than one that fails to compile.
 */
export interface SugarQuartile {
  quartile: number;
  n: number;
  sugar_range_g: [number, number];
  weighted_mean_sugar_g: number | null;
  weighted_mean_alt: number | null;
  standard_error_alt: number | null;
  weighted_median_alt: number | null;
  percent_elevated_alt: number | null;
}

/** The shape of the dose-response step the figure needs. */
export interface DoseResponseStep extends StudyStep {
  quartiles: SugarQuartile[];
  quartile_edges_g: number[];
  trend_test: {
    coefficient_per_quartile: number | null;
    percent_change_in_alt_per_quartile: number | null;
    significance: Significance;
  };
  elevated_alt_chi_square: {
    chi_square: number | null;
    counts_elevated: number[];
    counts_total: number[];
    significance: Significance;
  };
}

/** The shape of the primary-test step the forest plot needs. */
export interface DirectEffectStep extends StudyStep {
  total_model: StudyModel;
  direct_model: StudyModel;
}

/** GET /api/study/steps — the table of contents, without the results. */
export interface StudyIndexEntry {
  name: string;
  step: number | null;
  title: string;
  grade: ClaimGrade;
  question: string;
  n: number | null;
}

export interface StudyIndexResponse {
  steps: StudyIndexEntry[];
  hierarchy: Record<ClaimGrade, string>;
}

/** GET /api/study/headline — the summary card. */
export interface StudyHeadline {
  n: number;
  primary_finding: string;
  sugar_p: number | null;
  trig_hdl_beta: number | null;
  trig_hdl_p: number | null;
  sex_difference_in_alt: { male: number; female: number; difference: number };
  elevated_alt_percent: number | null;
  not_causal: string;
}
