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
import { useBox, useCorrelation, useFigureColumns, useHistogram, useScatter } from "../lib/hooks";
import { formatCount, formatTick, labelOf } from "../lib/scales";
import type { CorrelationResponse, HistogramResponse } from "../types/engine";

const SPEC: SpecRow[] = [
  { k: "Source", v: "nhanes_adolescent.csv" },
  { k: "Rows", v: "9,254" },
  { k: "Drawn", v: "Inline SVG" },
  { k: "Library", v: "None" },
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

  const histogram = useHistogram(column);
  const box = useBox(column, group);
  const scatter = useScatter(x, y);
  const correlation = useCorrelation();

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
            Five views of the same NHANES slice the engine reports on. A statistic is a
            summary — these show what it is a summary <em>of</em>, which is where a long
            tail or a fat cloud stops being invisible.
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
    </>
  );
}
