// Figures — the dataset as pictures instead of numbers.
//
// The rest of the site reports statistics. This page draws them, because some
// properties of a distribution have no number: a long right tail, a bimodal
// hump, a cloud that fans out as x grows. Each figure is paired with the tier
// that reports the same thing numerically, so the two can be read against each
// other rather than being two separate stories about one dataset.
//
// Everything is computed server-side (Backend/figures_api.py) and drawn here as
// inline SVG with no charting library — see lib/scales.ts for why.

import { useEffect, useState } from "react";
import type { JSX, ReactNode } from "react";
import { Crumbs, Masthead, Module, Status, Table } from "../components/Page";
import type { SpecRow } from "../components/Page";
import { Figure, Picker } from "../components/figures/ChartFrame";
import { Histogram, HistogramLegend } from "../components/figures/Histogram";
import { EcdfChart, EcdfLegend } from "../components/figures/EcdfChart";
import { BoxLegend, BoxPlot } from "../components/figures/BoxPlot";
import { ScatterLegend, ScatterPlot } from "../components/figures/ScatterPlot";
import {
  CorrelationHeatmap,
  CorrelationLegend,
} from "../components/figures/CorrelationHeatmap";
import { DensityLegend, DensityPlot } from "../components/figures/DensityPlot";
import { QQLegend, QQPlot } from "../components/figures/QQPlot";
import { ResidualLegend, ResidualPlot } from "../components/figures/ResidualPlot";
import { ForestLegend, ForestPlot } from "../components/figures/ForestPlot";
import {
  DoseResponseChart,
  DoseResponseLegend,
} from "../components/figures/DoseResponseChart";
import {
  useBox,
  useCorrelation,
  useDensity,
  useDiagnostics,
  useFigureColumns,
  useHistogram,
  useScatter,
  useStudyStep,
} from "../lib/hooks";
import { formatCount, formatTick, labelOf } from "../lib/scales";
import { DIAGNOSTIC_MODELS } from "../types/engine";
import type {
  CorrelationResponse,
  DensityResponse,
  DiagnosticsResponse,
  DirectEffectStep,
  DoseResponseStep,
  HistogramResponse,
} from "../types/engine";

const SPEC: SpecRow[] = [
  { k: "Source", v: "nhanes_adolescent.csv" },
  // The cohort file, not the raw all-ages merge: these figures plot the 699
  // adolescents the study analyses. This row read 9,254 -- the row count of
  // Data/nhanes_analytic.csv -- against the cohort filename, which is a
  // different dataset.
  { k: "Rows", v: "699" },
  { k: "Drawn", v: "Inline SVG" },
  { k: "Library", v: "None" },
  // Every figure exports the SVG that is on screen. PDF comes out as real
  // vector paths and real text, which is what makes it safe to enlarge to
  // poster size — see lib/svgExport.ts.
  { k: "Export", v: "PDF · PNG · SVG" },
];

/** The pair the scatter opens on: strong, real, and not a tautology. */
const DEFAULT_X = "Height";
const DEFAULT_Y = "Weight";

/**
 * A figure with a plot/table switch.
 *
 * The table is not a fallback — it is the accessible reading of the same data,
 * for a screen reader, for a colour-vision difference the palette cannot fully
 * solve, and for anyone who wants the exact number a mark can only approximate.
 */
function Switchable({
  showTable,
  onToggle,
  table,
  children,
}: {
  showTable: boolean;
  onToggle: () => void;
  table: ReactNode;
  children: ReactNode;
}): JSX.Element {
  return (
    <>
      <button className="fig-toggle" type="button" onClick={onToggle} aria-pressed={showTable}>
        {showTable ? "Show chart" : "Show data"}
      </button>
      {showTable ? table : children}
    </>
  );
}

function Loading({ what }: { what: string }): JSX.Element {
  return <div className="fig-placeholder">Computing {what}…</div>;
}

/**
 * The table readings. Pulled out into their own components purely so the data is
 * a non-null prop: written inline they would have sat inside a `data && (…)`
 * guard that TypeScript cannot see through into the row callbacks, and the price
 * would have been a non-null assertion on every cell.
 */
function HistogramTable({ data }: { data: HistogramResponse }): JSX.Element {
  return (
    <Table
      corner="Range"
      head={["Count", "Share"]}
      numeric={[1, 2]}
      caption={`${labelOf(data.column)} — ${data.bins.length} bins over ${formatCount(data.n)} values`}
      rows={data.bins.map((bin) => [
        `${formatTick(bin.lo)} – ${formatTick(bin.hi)}`,
        formatCount(bin.count),
        `${((bin.count / data.n) * 100).toFixed(1)}%`,
      ])}
    />
  );
}

/**
 * The cumulative curve as numbers: each bin's upper edge and the share at or
 * below it. Running total rather than per-bin count, so the table answers the
 * same question the chart does instead of repeating the histogram's.
 */
function EcdfTable({ data }: { data: HistogramResponse }): JSX.Element {
  let running = 0;
  const rows = data.bins.map((bin) => {
    running += bin.count;
    const share = data.n > 0 ? running / data.n : 0;
    return [
      `≤ ${formatTick(bin.hi)}`,
      formatCount(running),
      `${(share * 100).toFixed(1)}%`,
      `${((1 - share) * 100).toFixed(1)}%`,
    ];
  });
  return (
    <Table
      corner="Value"
      head={["Cumulative", "At or below", "Above"]}
      numeric={[1, 2, 3]}
      caption={`${labelOf(data.column)} — running total over ${formatCount(data.n)} values`}
      rows={rows}
    />
  );
}

function CorrelationTable({ data }: { data: CorrelationResponse }): JSX.Element {
  // Upper triangle only: the matrix is symmetric, so walking all of it would
  // print every pair twice and the diagonal's meaningless r = 1.
  const rows = data.columns.flatMap((rowCol, i) =>
    data.columns.slice(i + 1).map((colCol, j) => {
      const r = data.matrix[i]?.[i + 1 + j] ?? null;
      return [`${labelOf(rowCol)} × ${labelOf(colCol)}`, r === null ? "—" : r.toFixed(3)];
    }),
  );
  // Strongest first: 105 pairs in alphabetical order buries the handful that
  // matter, and the point of the matrix is to find those.
  rows.sort((a, b) => Math.abs(Number(b[1])) - Math.abs(Number(a[1])));
  return (
    <Table
      corner="Pair"
      head={["Pearson r"]}
      numeric={[1]}
      caption={`${rows.length} pairs, strongest first`}
      rows={rows}
    />
  );
}


/**
 * The new figures' table readings.
 *
 * Same rule as the four above: the table is the accessible reading of the
 * figure, not a fallback. Where a chart draws hundreds of marks — every
 * residual, every Q-Q point — the table gives the summary a reader could
 * actually use rather than 586 rows nobody will scroll, and says so.
 */
function DensityTable({ data }: { data: DensityResponse }): JSX.Element {
  return (
    <Table
      corner="Group"
      head={["n", "Mean", "Median", "Bandwidth"]}
      numeric={[1, 2, 3, 4]}
      caption={`${labelOf(data.column)} — ${data.method}`}
      rows={data.curves.map((curve) => [
        curve.label,
        formatCount(curve.n),
        formatTick(curve.mean),
        formatTick(curve.median),
        formatTick(curve.bandwidth),
      ])}
    />
  );
}

function DoseResponseTable({ data }: { data: DoseResponseStep }): JSX.Element {
  return (
    <Table
      corner="Quartile"
      head={["Sugar (g/day)", "n", "Mean ALT", "± SE", "Above threshold"]}
      numeric={[1, 2, 3, 4, 5]}
      caption="Weighted to U.S. adolescents; the standard error uses the row count."
      rows={data.quartiles.map((q) => [
        `Q${q.quartile}`,
        `${formatTick(q.sugar_range_g[0])} – ${formatTick(q.sugar_range_g[1])}`,
        formatCount(q.n),
        formatTick(q.weighted_mean_alt ?? 0),
        formatTick(q.standard_error_alt ?? 0),
        `${formatTick(q.percent_elevated_alt ?? 0)}%`,
      ])}
    />
  );
}

function ForestTable({ data }: { data: DirectEffectStep }): JSX.Element {
  const rows: string[][] = [];
  for (const [label, model] of [
    ["Without BMI", data.total_model],
    ["With BMI", data.direct_model],
  ] as const) {
    for (const [name, c] of Object.entries(model.coefficients)) {
      if (name === "const") continue;
      rows.push([
        `${labelOf(name)} — ${label}`,
        formatTick(c.estimate ?? 0),
        c.ci_low === null || c.ci_high === null
          ? "—"
          : `${formatTick(c.ci_low)} to ${formatTick(c.ci_high)}`,
        formatTick(c.standardized_beta ?? 0),
        c.significance.p_value_text ?? String(c.significance.p_value ?? "—"),
      ]);
    }
  }
  return (
    <Table
      corner="Predictor"
      head={["Estimate", "95% CI", "Standardized β", "p"]}
      numeric={[1, 2, 3, 4]}
      caption="Weighted least squares with cluster-robust standard errors."
      rows={rows}
    />
  );
}

function DiagnosticsTable({ data }: { data: DiagnosticsResponse }): JSX.Element {
  return (
    <Table
      corner="Measure"
      head={["Value"]}
      numeric={[1]}
      caption={`${data.label} — ${formatCount(data.n)} residuals`}
      rows={[
        ["Predictors", data.predictors.map(labelOf).join(", ")],
        ["R²", formatTick(data.r_squared ?? 0)],
        ["Residual SD", formatTick(data.residual_sd ?? 0)],
        ["Skewness (0 if normal)", formatTick(data.residual_skewness ?? 0)],
        ["Excess kurtosis (0 if normal)", formatTick(data.residual_kurtosis ?? 0)],
        ["Q-Q line slope", formatTick(data.qq_line.slope ?? 0)],
        ["Fitted range", `${formatTick(data.fitted_min)} to ${formatTick(data.fitted_max)}`],
        ["Residual range", `${formatTick(data.residual_min)} to ${formatTick(data.residual_max)}`],
      ]}
    />
  );
}

export function Figures(): JSX.Element {
  const { columns, categorical, error: columnsError } = useFigureColumns();

  const [column, setColumn] = useState<string | null>(null);
  const [group, setGroup] = useState("");
  const [x, setX] = useState<string | null>(null);
  const [y, setY] = useState<string | null>(null);
  // The correlation matrix is 15 × 15 labelled cells. Painted into a phone-width
  // column its labels fall under 7px, and the alternatives are both worse: an
  // inner side-scroller (the thing this site deliberately does not have) or a
  // chart nobody can read. So on a narrow screen it OPENS as its table and the
  // toggle offers the chart, rather than the other way round. Read once, on
  // mount: this is a starting state, not a live binding, and re-deciding it on
  // every resize would yank the view out from under someone rotating a phone.
  const [tables, setTables] = useState<Record<string, boolean>>(() => ({
    corr: typeof window !== "undefined" && window.matchMedia("(max-width: 700px)").matches,
  }));

  // Seed the pickers once the column list arrives. Guarded on the current value
  // being null so this never fights a choice the reader has already made.
  useEffect(() => {
    if (!columns.length) return;
    // `?? null` on each fallback: indexing a string[] is `string | undefined`
    // under noUncheckedIndexedAccess, and these setters hold `string | null`.
    const pick = (preferred: string, fallbackIndex: number): string | null =>
      columns.includes(preferred) ? preferred : (columns[fallbackIndex] ?? null);
    setColumn((current) => current ?? pick("BMI", 0));
    setX((current) => current ?? pick(DEFAULT_X, 0));
    setY((current) => current ?? pick(DEFAULT_Y, 1));
  }, [columns]);

  useEffect(() => {
    if (!group && categorical.includes("Education")) setGroup("Education");
  }, [categorical, group]);

  // The diagnostics figures share one fit — a Q-Q plot and a residual plot of
  // DIFFERENT models would be two answers to one question — so the picker is
  // page state and both figures read the same response.
  const [diagnosticModel, setDiagnosticModel] = useState<string>("direct-effect");

  const histogram = useHistogram(column);
  const box = useBox(column, group);
  const scatter = useScatter(x, y);
  const correlation = useCorrelation();
  const densityCurves = useDensity(column, group);
  const diagnostics = useDiagnostics(diagnosticModel);
  // The two study figures are drawn from the protocol's own results rather than
  // from a second aggregate: the coefficients and the quartile means are
  // already published at /api/study, and computing them twice is how a figure
  // and the text beside it end up disagreeing.
  const doseStep = useStudyStep("dose-response");
  const primaryStep = useStudyStep("direct-effect");
  const dose = doseStep.step as DoseResponseStep | null;
  const primary = primaryStep.step as DirectEffectStep | null;

  const toggle = (key: string) => () =>
    setTables((current) => ({ ...current, [key]: !current[key] }));

  return (
    <>
      <Crumbs here="Figures" />

      <Masthead
        eyebrow="The dataset · drawn"
        title="Figures"
        tagline={
          <>
            Ten views of the same NHANES slice the engine reports on. A statistic is a
            summary — these show what it is a summary <em>of</em>, which is where a long
            tail or a fat cloud stops being invisible. Every figure downloads as a
            vector PDF, a PNG or its own SVG.
          </>
        }
        byline="By Anirudh Gupta"
        spec={SPEC}
        specLabel="Figure environment"
      />

      {columnsError && <Status message={columnsError} isError />}

      <Module index="01" title="Distribution" meta="One column">
        <p className="text">
          Where the values of one column actually sit. The engine&rsquo;s basic tier reports
          the mean and the median; the distance between the two lines below is what makes
          that pair worth reporting separately.
        </p>
        <Figure
          title={column ? `${labelOf(column)} — distribution` : "Distribution"}
          caption="Bar height is how many people fall in that range of values."
          meta={histogram.data ? `n = ${formatCount(histogram.data.n)}` : undefined}
          controls={
            <Picker
              label="Column"
              value={column ?? ""}
              options={columns}
              onChange={(next) => setColumn(next)}
            />
          }
          legend={histogram.data ? <HistogramLegend data={histogram.data} /> : undefined}
          footnote={
            histogram.data ? (
              <>
                Bin width chosen by the Freedman–Diaconis rule, which sets it from the IQR and
                n rather than from a fixed count — the alternative under-bins a skewed column
                and hides the tail this figure exists to show.
              </>
            ) : undefined
          }
        >
          {histogram.error && <Status message={histogram.error} isError />}
          {!histogram.error && !histogram.data && <Loading what="the distribution" />}
          {histogram.data && (
            <Switchable
              showTable={tables.hist ?? false}
              onToggle={toggle("hist")}
              table={<HistogramTable data={histogram.data} />}
            >
              <Histogram data={histogram.data} />
            </Switchable>
          )}
        </Figure>
      </Module>

      <Module index="02" title="Cumulative Share" meta="Same column, read as percentiles">
        <p className="text">
          The same values as the histogram above, accumulated. This is the view a threshold
          question wants: the expert tier can tell you what share of the sample clears one
          published cutoff, and this tells you the share that clears <em>any</em> value you
          point at — including the ones no guideline picked.
        </p>
        <Figure
          title={column ? `${labelOf(column)} — cumulative share` : "Cumulative share"}
          caption="Height is the share of people at or below that value. Point anywhere to read it."
          meta={histogram.data ? `n = ${formatCount(histogram.data.n)}` : undefined}
          controls={
            <Picker
              label="Column"
              value={column ?? ""}
              options={columns}
              onChange={(next) => setColumn(next)}
            />
          }
          legend={histogram.data ? <EcdfLegend data={histogram.data} /> : undefined}
          footnote={
            histogram.data ? (
              <>
                Built from the same bins as the histogram, so the curve rises straight across
                each bin instead of stepping at every observation — a reading between two bin
                edges is an interpolation, accurate to about one bin width. The exact curve
                would need all {formatCount(histogram.data.n)} raw values in the browser, which
                costs far more than the precision is worth at this size.
              </>
            ) : undefined
          }
        >
          {histogram.error && <Status message={histogram.error} isError />}
          {!histogram.error && !histogram.data && <Loading what="the cumulative share" />}
          {histogram.data && (
            <Switchable
              showTable={tables.ecdf ?? false}
              onToggle={toggle("ecdf")}
              table={<EcdfTable data={histogram.data} />}
            >
              <EcdfChart data={histogram.data} />
            </Switchable>
          )}
        </Figure>
      </Module>

      <Module index="03" title="Group Comparison" meta="Split by a label">
        <p className="text">
          The same column, one box per group. This is the picture that belongs beside the
          medium tier&rsquo;s ANOVA: the test says whether the groups are distinguishable, and
          the boxes say by how much — a question a p-value cannot answer at this sample size.
        </p>
        <Figure
          title={
            column
              ? `${labelOf(column)} by ${group ? labelOf(group) : "all rows"}`
              : "Group comparison"
          }
          caption="Box spans the middle 50%; the line inside is the median, the dot is the mean."
          meta={box.data ? `${box.data.boxes.length} groups` : undefined}
          controls={
            <>
              <Picker
                label="Column"
                value={column ?? ""}
                options={columns}
                onChange={(next) => setColumn(next)}
              />
              <Picker
                label="Group by"
                value={group}
                options={categorical}
                onChange={setGroup}
                allowNone
                noneLabel="No split"
              />
            </>
          }
          legend={<BoxLegend />}
          footnote={
            box.data ? (
              <>
                Whiskers stop at the furthest real observation within 1.5 × IQR of the box —
                not at the fence itself, which would draw a value nobody was measured at.
                {box.data.dropped_groups > 0 && (
                  <>
                    {" "}
                    {box.data.dropped_groups} group
                    {box.data.dropped_groups === 1 ? " was" : "s were"} omitted for having fewer
                    than {box.data.min_group_n} values.
                  </>
                )}
              </>
            ) : undefined
          }
        >
          {box.error && <Status message={box.error} isError />}
          {!box.error && !box.data && <Loading what="the group summaries" />}
          {box.data && (
            <Switchable
              showTable={tables.box ?? false}
              onToggle={toggle("box")}
              table={
                <Table
                  corner="Group"
                  head={["n", "Q1", "Median", "Q3", "Mean", "Outliers"]}
                  numeric={[1, 2, 3, 4, 5, 6]}
                  rows={box.data.boxes.map((b) => [
                    b.label,
                    formatCount(b.n),
                    formatTick(b.q1),
                    formatTick(b.median),
                    formatTick(b.q3),
                    formatTick(b.mean),
                    formatCount(b.outliers),
                  ])}
                />
              }
            >
              <BoxPlot data={box.data} />
            </Switchable>
          )}
        </Figure>
      </Module>

      <Module index="04" title="Relationship" meta="Two columns">
        <p className="text">
          Two columns plotted against each other, with the least-squares line. The advanced
          tier reports r for this pair; the cloud shows the spread that r is a summary of —
          and why a strong correlation still leaves individual people far from the line.
        </p>
        <Figure
          title={x && y ? `${labelOf(y)} against ${labelOf(x)}` : "Relationship"}
          caption="Each dot is one person. Overlapping dots darken, so density reads through."
          meta={scatter.data ? `n = ${formatCount(scatter.data.n)}` : undefined}
          controls={
            <>
              <Picker label="X" value={x ?? ""} options={columns} onChange={(next) => setX(next)} />
              <Picker label="Y" value={y ?? ""} options={columns} onChange={(next) => setY(next)} />
            </>
          }
          legend={scatter.data ? <ScatterLegend data={scatter.data} /> : undefined}
          footnote={
            <>
              An association measured in observational data. It does not establish that changing
              one variable would change the other — the line describes this sample, it does not
              predict an intervention.
              {scatter.data?.sampled && (
                <>
                  {" "}
                  The cloud is a fixed random sample of {formatCount(scatter.data.drawn)} pairs
                  for rendering; r and the fitted line are computed on all{" "}
                  {formatCount(scatter.data.n)}.
                </>
              )}
            </>
          }
        >
          {x !== null && y !== null && x === y && (
            <Status message="Pick two different columns to plot them against each other." />
          )}
          {scatter.error && <Status message={scatter.error} isError />}
          {!scatter.error && !scatter.data && x !== y && <Loading what="the scatter" />}
          {scatter.data && (
            <Switchable
              showTable={tables.scatter ?? false}
              onToggle={toggle("scatter")}
              table={
                <Table
                  corner="Measure"
                  head={["Value"]}
                  numeric={[1]}
                  rows={[
                    ["Pearson r", scatter.data.r.toFixed(3)],
                    ["r²", scatter.data.r_squared.toFixed(3)],
                    ["Slope", scatter.data.slope.toFixed(4)],
                    ["Intercept", scatter.data.intercept.toFixed(3)],
                    ["Complete pairs", formatCount(scatter.data.n)],
                    ["Points drawn", formatCount(scatter.data.drawn)],
                  ]}
                />
              }
            >
              <ScatterPlot data={scatter.data} />
            </Switchable>
          )}
        </Figure>
      </Module>

      <Module index="05" title="Correlation Matrix" meta="Every pair">
        <p className="text">
          Fifteen numeric columns make 105 pairs, which is more than anyone will open one at a
          time. This is the map: blue where two columns rise together, red where one rises as
          the other falls, and flat where there is nothing.{" "}
          <strong>Click any cell to plot that pair above.</strong>
        </p>
        <Figure
          title="Pearson r, every numeric pair"
          caption="Colour is direction and strength; the diagonal is each column against itself."
          meta={correlation.data ? `${correlation.data.columns.length} columns` : undefined}
          legend={<CorrelationLegend />}
          footnote={
            correlation.data ? (
              <>
                Pairwise-complete: each cell uses the rows where both columns have a value, so
                different cells can rest on different row counts. A pair with fewer than{" "}
                {correlation.data.min_overlap} overlapping rows is left blank rather than shown
                as zero — no measurement is not the same as no relationship.
              </>
            ) : undefined
          }
        >
          {correlation.error && <Status message={correlation.error} isError />}
          {!correlation.error && !correlation.data && <Loading what="105 correlations" />}
          {correlation.data && (
            <Switchable
              showTable={tables.corr ?? false}
              onToggle={toggle("corr")}
              table={<CorrelationTable data={correlation.data} />}
            >
              <CorrelationHeatmap
                data={correlation.data}
                selected={x && y ? { x, y } : undefined}
                onPick={(pickedX, pickedY) => {
                  setX(pickedX);
                  setY(pickedY);
                }}
              />
            </Switchable>
          )}
        </Figure>
      </Module>

      <Module index="06" title="Distribution Shape" meta="Smoothed, by group">
        <p className="text">
          The box plot above reduces each group to five numbers. This draws the shape those
          five numbers summarize — and the thing they cannot show, which is a second hump.
          Two groups with identical quartiles, one unimodal and one splitting into a low and a
          high cluster, draw the same box.
        </p>
        <Figure
          title={
            column
              ? `${labelOf(column)} — density${group ? ` by ${labelOf(group)}` : ""}`
              : "Distribution shape"
          }
          caption="Area under each curve is 1, so groups are comparable regardless of size."
          meta={densityCurves.data ? `${densityCurves.data.curves.length} curves` : undefined}
          controls={
            <>
              <Picker
                label="Column"
                value={column ?? ""}
                options={columns}
                onChange={(next) => setColumn(next)}
              />
              <Picker
                label="Group by"
                value={group}
                options={categorical}
                onChange={setGroup}
                allowNone
                noneLabel="No split"
              />
            </>
          }
          legend={densityCurves.data ? <DensityLegend data={densityCurves.data} /> : undefined}
          footnote={
            densityCurves.data ? (
              <>
                A kernel density estimate is a smoothing choice as much as a measurement, which
                is why the bandwidth is in the key: a bump narrower than the bandwidth is the
                smoother talking, not the data. The curve is not extended below zero for a
                quantity that cannot be negative.
                {densityCurves.data.dropped_groups > 0 && (
                  <>
                    {" "}
                    {densityCurves.data.dropped_groups} group
                    {densityCurves.data.dropped_groups === 1 ? " was" : "s were"} omitted for
                    having fewer than {densityCurves.data.min_group_n} values.
                  </>
                )}
              </>
            ) : undefined
          }
        >
          {densityCurves.error && <Status message={densityCurves.error} isError />}
          {!densityCurves.error && !densityCurves.data && <Loading what="the density" />}
          {densityCurves.data && (
            <Switchable
              showTable={tables.density ?? false}
              onToggle={toggle("density")}
              table={<DensityTable data={densityCurves.data} />}
            >
              <DensityPlot data={densityCurves.data} />
            </Switchable>
          )}
        </Figure>
      </Module>

      <Module index="07" title="Dose-Response" meta="Protocol steps 3 and 7">
        <p className="text">
          Does ALT climb as sugar intake climbs? A dose-response gradient is one of the
          stronger observational arguments that an association is real — noise has no reason
          to arrange itself in order. That cuts both ways, which is why this figure matters to
          a null result as much as it would to a positive one.
        </p>
        <Figure
          title="Mean ALT across sugar quartiles"
          caption="Points are weighted means; bars are ± one standard error. Red is the share above the clinical threshold."
          meta={dose ? `n = ${formatCount(dose.n ?? 0)}` : undefined}
          legend={dose ? <DoseResponseLegend quartiles={dose.quartiles} /> : undefined}
          footnote={
            dose ? (
              <>
                The trend test enters quartile rank as one ordered predictor, so a single
                coefficient answers &ldquo;does ALT move monotonically?&rdquo; rather than three
                pairwise comparisons answering nothing in particular. It reports{" "}
                {formatTick(dose.trend_test.percent_change_in_alt_per_quartile ?? 0)}% per
                quartile,{" "}
                {dose.trend_test.significance.statistically_significant
                  ? "which clears"
                  : "which does not clear"}{" "}
                the 0.05 threshold. The error bars use the row count, not the summed survey
                weight — dividing by millions of represented adolescents would draw an error
                bar of essentially zero around an estimate from a few hundred people.
              </>
            ) : undefined
          }
        >
          {primaryStep.error && <Status message={primaryStep.error} isError />}
          {doseStep.error && <Status message={doseStep.error} isError />}
          {!doseStep.error && !dose && <Loading what="the quartile means" />}
          {dose && (
            <Switchable
              showTable={tables.dose ?? false}
              onToggle={toggle("dose")}
              table={<DoseResponseTable data={dose} />}
            >
              <DoseResponseChart quartiles={dose.quartiles} />
            </Switchable>
          )}
        </Figure>
      </Module>

      <Module index="08" title="Model Coefficients" meta="The primary test, drawn">
        <p className="text">
          Every predictor in the study&rsquo;s full model, with its 95% interval, fitted twice:
          once without BMI and once with. The protocol pre-specified that pair before the data
          were seen, and pre-specified the sugar coefficient in the <em>with-BMI</em> model as
          the single test the hypothesis rises or falls on.{" "}
          <strong>An interval that crosses zero is a predictor the model cannot tell apart
          from nothing.</strong>
        </p>
        <Figure
          title="Standardized coefficients, Model B with and without BMI"
          caption="Dot is the estimate; the bar is its 95% confidence interval. Hollow dots include zero."
          meta={primary ? `n = ${formatCount(primary.n ?? 0)}` : undefined}
          legend={
            primary ? (
              <ForestLegend
                models={[
                  { label: "Without BMI", model: primary.total_model },
                  { label: "With BMI", model: primary.direct_model },
                ]}
              />
            ) : undefined
          }
          footnote={
            primary ? (
              <>
                The axis is the standardized β — how many standard deviations of log ALT move
                per standard deviation of the predictor. Sugar is in 10 g/day, BMI in kg/m² and
                HbA1c in percent, so a raw axis would make them incomparable, and comparing
                sugar against the Trig/HDL ratio is exactly the protocol&rsquo;s secondary
                question. Weighted least squares with cluster-robust standard errors; an
                association in observational data, not an effect of an intervention.
              </>
            ) : undefined
          }
        >
          {primaryStep.error && <Status message={primaryStep.error} isError />}
          {!primaryStep.error && !primary && <Loading what="the fitted models" />}
          {primary && (
            <Switchable
              showTable={tables.forest ?? false}
              onToggle={toggle("forest")}
              table={<ForestTable data={primary} />}
            >
              <ForestPlot
                models={[
                  { label: "Without BMI", model: primary.total_model },
                  { label: "With BMI", model: primary.direct_model },
                ]}
              />
            </Switchable>
          )}
        </Figure>
      </Module>

      <Module index="09" title="Normal Q-Q" meta="Regression assumption 1">
        <p className="text">
          Every interval on the figure above assumes the model&rsquo;s residuals are roughly
          normal. The expert tier tests that and returns a number; this shows the{" "}
          <em>shape</em> of the departure, which is what decides whether it matters. A plot
          that tracks the line and lifts off only at the ends is a couple of unusual
          adolescents. One that bows through the middle is a model mis-specified for everyone.
        </p>
        <Figure
          title={diagnostics.data ? `Q-Q — ${diagnostics.data.label}` : "Normal Q-Q"}
          caption="Points on the line are what normal residuals look like."
          meta={diagnostics.data ? `n = ${formatCount(diagnostics.data.n)}` : undefined}
          controls={
            <Picker
              label="Model"
              value={diagnosticModel}
              options={[...DIAGNOSTIC_MODELS]}
              onChange={setDiagnosticModel}
            />
          }
          legend={diagnostics.data ? <QQLegend data={diagnostics.data} /> : undefined}
          footnote={
            <>
              The reference line runs through the first and third quartiles, not the 45°
              identity — an identity line would flag a pure difference in spread as
              non-normality, which is not the question being asked.
            </>
          }
        >
          {diagnostics.error && <Status message={diagnostics.error} isError />}
          {!diagnostics.error && !diagnostics.data && <Loading what="the residuals" />}
          {diagnostics.data && (
            <Switchable
              showTable={tables.qq ?? false}
              onToggle={toggle("qq")}
              table={<DiagnosticsTable data={diagnostics.data} />}
            >
              <QQPlot data={diagnostics.data} />
            </Switchable>
          )}
        </Figure>
      </Module>

      <Module index="10" title="Residuals Against Fitted" meta="Regression assumption 2">
        <p className="text">
          The second assumption: that the model is equally wrong across its whole range. If the
          cloud fans out to the right, the model is more uncertain about high-ALT adolescents
          than about low ones, and a single standard error averaging the two describes neither.
          A flat line at zero is what a well-specified model looks like.
        </p>
        <Figure
          title={
            diagnostics.data ? `Residuals — ${diagnostics.data.label}` : "Residuals against fitted"
          }
          caption="Each dot is one adolescent: what the model predicted, and how far off it was."
          meta={diagnostics.data ? `R² = ${formatTick(diagnostics.data.r_squared ?? 0)}` : undefined}
          controls={
            <Picker
              label="Model"
              value={diagnosticModel}
              options={[...DIAGNOSTIC_MODELS]}
              onChange={setDiagnosticModel}
            />
          }
          legend={diagnostics.data ? <ResidualLegend data={diagnostics.data} /> : undefined}
          footnote={
            <>
              The binned line is a reading aid, not a fit: eyes are bad at judging the centre of
              a cloud and good at following a line, so the residuals are averaged in vertical
              slices. Curvature there means the model is missing something systematic, rather
              than merely being noisy.
            </>
          }
        >
          {diagnostics.error && <Status message={diagnostics.error} isError />}
          {!diagnostics.error && !diagnostics.data && <Loading what="the residuals" />}
          {diagnostics.data && (
            <Switchable
              showTable={tables.resid ?? false}
              onToggle={toggle("resid")}
              table={<DiagnosticsTable data={diagnostics.data} />}
            >
              <ResidualPlot data={diagnostics.data} />
            </Switchable>
          )}
        </Figure>
      </Module>
    </>
  );
}
