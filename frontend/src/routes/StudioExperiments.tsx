// Studio experiments — four knobs, and what turning them does.
//
// The rest of the site answers questions. This page attacks the answers. Each
// experiment takes something a published result quietly depends on — how many
// people were measured, which values were called outliers, how many questions
// were asked before one came out interesting — and makes it adjustable, so the
// reader can watch a "finding" appear and disappear without the data changing
// at all.
//
// That is the argument the whole project is making, and it is much harder to
// make with a paragraph than with a slider.

import { useEffect, useState } from "react";
import type { JSX } from "react";
import { Link } from "react-router";
import { BarChart } from "../components/BarChart";
import { Crumbs, Masthead, Module, Status, StatGrid, Table } from "../components/Page";
import { Figure, Picker } from "../components/figures/ChartFrame";
import { BootstrapChart, BootstrapLegend } from "../components/figures/BootstrapChart";
import { SampleSizeChart, SampleSizeLegend } from "../components/figures/SampleSizeChart";
import { ScreenChart, ScreenLegend } from "../components/figures/ScreenChart";
import {
  useBootstrap,
  useFigureColumns,
  useOutliers,
  useSampleSize,
  useScreen,
} from "../lib/hooks";
import { formatCount, formatTick, labelOf } from "../lib/scales";
import type { ScreenTest } from "../types/engine";

const STATISTICS = ["mean", "median", "std"];
const ALPHAS = ["0.1", "0.05", "0.01", "0.001"];

/** A reseed button. Every experiment that samples takes one, so it is declared once. */
function Reseed({ seed, onReseed }: { seed: number; onReseed: () => void }): JSX.Element {
  return (
    <span className="fig-pick">
      <span className="fig-pick-label">Seed {seed}</span>
      <button type="button" className="channel" onClick={onReseed}>
        Draw again
      </button>
    </span>
  );
}

function Loading({ what }: { what: string }): JSX.Element {
  return <div className="fig-placeholder">Running {what}…</div>;
}

/**
 * How far a test gets through the corrections, as one phrase.
 *
 * The order is deliberate: Bonferroni is strictly harsher than B–H, so
 * surviving it implies surviving both and there is no need to list them. The
 * interesting output is the middle case — cleared α, cleared the lenient
 * correction, failed the strict one — which is exactly the row a paper would
 * have reported and a replication would have failed.
 */
function survivesLabel(test: ScreenTest): string {
  if (test.bonferroni) return "Bonferroni + B–H";
  if (test.benjamini_hochberg) return "B–H only";
  if (test.raw) return "α only";
  return "nothing";
}

export function StudioExperiments(): JSX.Element {
  const { columns, categorical, error } = useFigureColumns();

  const [sizeColumn, setSizeColumn] = useState("");
  const [sizeSeed, setSizeSeed] = useState(1);
  const [bootColumn, setBootColumn] = useState("");
  const [bootStat, setBootStat] = useState("mean");
  const [bootSeed, setBootSeed] = useState(1);
  const [outlierColumn, setOutlierColumn] = useState("");
  const [group, setGroup] = useState("");
  const [alpha, setAlpha] = useState(0.05);

  // Seed the pickers once the column list lands, without overriding a choice
  // the reader has already made.
  useEffect(() => {
    if (!columns.length) return;
    const first = columns[0] ?? "";
    const pick = (preferred: string): string => (columns.includes(preferred) ? preferred : first);
    setSizeColumn((c) => c || pick("BMI"));
    setBootColumn((c) => c || pick("BMI"));
    // Triglycerides has the most dramatic outlier disagreement in this dataset,
    // which is the point of opening on it.
    setOutlierColumn((c) => c || pick("Triglycerides"));
  }, [columns]);

  useEffect(() => {
    if (!group && categorical.length) setGroup(categorical[0] ?? "");
  }, [categorical, group]);

  const size = useSampleSize(sizeColumn || null, sizeSeed);
  const boot = useBootstrap(bootColumn || null, bootStat, bootSeed);
  const outliers = useOutliers(outlierColumn || null);
  const screen = useScreen(group || null, alpha);

  return (
    <>
      <Crumbs here="Experiments" />

      <Masthead
        eyebrow="The lab"
        title="Experiments"
        tagline={
          <>
            Four things a published number quietly depends on, each made adjustable. Nothing here
            changes the data — every result on this page comes from the same 9,254 rows as every
            other page. What changes is the question, and that turns out to be enough.
          </>
        }
        byline="By Anirudh Gupta"
        spec={[
          { k: "Dataset", v: "nhanes.csv" },
          { k: "Experiments", v: "04" },
          { k: "Computed", v: "Server-side" },
          { k: "Bench", v: <Link to="/studio">Studio</Link> },
        ]}
        specLabel="Lab status"
      />

      {error && <Status message={error} isError />}

      <Module index="01" title="How Many People" meta="Sample size">
        <p className="text">
          Every rung below simulates {size.data ? formatCount(size.data.draws_per_rung) : "200"}{" "}
          separate studies of that size, drawn from this dataset, and shades the middle 95% of what
          they concluded. A study of 25 people is not a small version of the truth — it is a
          lottery ticket.
        </p>
        <Figure
          title={sizeColumn ? `${labelOf(sizeColumn)} — what a study of size n would find` : "Sample size"}
          caption="The band is where 95% of same-sized studies landed. It narrows with the square root of n, which is why the x-axis is logarithmic."
          meta={size.data ? `${formatCount(size.data.population_n)} available` : undefined}
          controls={
            <>
              <Picker label="Column" value={sizeColumn} options={columns} onChange={setSizeColumn} />
              <Reseed seed={sizeSeed} onReseed={() => setSizeSeed((s) => s + 1)} />
            </>
          }
          legend={size.data ? <SampleSizeLegend data={size.data} /> : undefined}
          footnote={
            <>
              Sampling is with replacement from the full dataset, so a rung near the dataset&rsquo;s
              own size is still a random draw rather than &ldquo;nearly all of it&rdquo;. The seed
              is fixed so the same rung gives the same band on a reload; press{" "}
              <em>Draw again</em> to see how much the whole picture moves when it does not.
            </>
          }
        >
          {size.error && <Status message={size.error} isError />}
          {!size.error && !size.data && <Loading what="200 studies per rung" />}
          {size.data && <SampleSizeChart data={size.data} />}
        </Figure>
        {size.data && size.data.rungs.length > 0 && (
          <Table
            corner="Study size"
            head={["95% of studies found", "Band width", "Off by >1%"]}
            numeric={[2, 3]}
            rows={size.data.rungs.map((r) => [
              formatCount(r.n),
              `${formatTick(r.lo)} – ${formatTick(r.hi)}`,
              formatTick(r.width),
              `${(r.miss_rate * 100).toFixed(0)}%`,
            ])}
          />
        )}
      </Module>

      <Module index="02" title="Where Uncertainty Comes From" meta="Bootstrap">
        <p className="text">
          A confidence interval is usually a formula you are asked to trust. This is the same
          interval, arrived at by brute force: draw a whole new dataset by sampling this one with
          replacement, compute the statistic, repeat {boot.data ? formatCount(boot.data.draws) : "2,000"}{" "}
          times, and look at the spread. The shaded middle 95% <em>is</em> the interval.
        </p>
        <Figure
          title={bootColumn ? `${labelOf(bootColumn)} — ${bootStat} across resampled datasets` : "Bootstrap"}
          caption="Each bar counts resampled datasets whose statistic landed in that range."
          meta={boot.data ? `${formatCount(boot.data.draws)} resamples` : undefined}
          controls={
            <>
              <Picker label="Column" value={bootColumn} options={columns} onChange={setBootColumn} />
              <Picker label="Statistic" value={bootStat} options={STATISTICS} onChange={setBootStat} />
              <Reseed seed={bootSeed} onReseed={() => setBootSeed((s) => s + 1)} />
            </>
          }
          legend={boot.data ? <BootstrapLegend data={boot.data} /> : undefined}
          footnote={
            <>
              Try the <strong>median</strong> and then the <strong>std</strong>. The median&rsquo;s
              distribution is tight and lumpy — it can only land on values that exist in the data —
              while the standard deviation&rsquo;s is wide and skewed, because it is the statistic
              most sensitive to whichever extreme values a resample happened to pick up twice.
              Neither of those facts is visible in the single number each one reports.
            </>
          }
        >
          {boot.error && <Status message={boot.error} isError />}
          {!boot.error && !boot.data && <Loading what="2,000 resamples" />}
          {boot.data && <BootstrapChart data={boot.data} />}
        </Figure>
        {boot.data && (
          <StatGrid
            cells={[
              { k: "Measured", v: formatTick(boot.data.observed), note: boot.data.statistic },
              { k: "95% interval", v: `${formatTick(boot.data.ci_lower)} – ${formatTick(boot.data.ci_upper)}` },
              { k: "Standard error", v: formatTick(boot.data.std_error) },
              { k: "Rows resampled", v: formatCount(boot.data.n) },
            ]}
          />
        )}
      </Module>

      <Module index="03" title="What Counts As Data" meta="Outlier rules">
        <p className="text">
          Four defensible ways to handle extreme values. None of them is wrong, and they disagree —
          sometimes by a lot. A reported mean is a claim about the data <em>plus</em> a judgement
          call about which rows were allowed to be data, and papers rarely report the second half.
        </p>
        <div className="fig-controls">
          <Picker label="Column" value={outlierColumn} options={columns} onChange={setOutlierColumn} />
        </div>
        {outliers.error && <Status message={outliers.error} isError />}
        {!outliers.error && !outliers.data && <Loading what="four outlier policies" />}
        {outliers.data && (
          <>
            {/* Two tables, not one seven-column one. They answer different
                questions — what the rule threw away, and what throwing it away
                did to the answer — and a seven-column numeric table does not
                fit a phone at any type size worth reading. */}
            <Table
              corner="Rule"
              head={["Kept", "Dropped", "Share dropped"]}
              numeric={[1, 2, 3]}
              caption="What each rule removes"
              rows={outliers.data.results.map((r) => [
                r.rule,
                formatCount(r.n),
                formatCount(r.removed),
                `${(r.removed_share * 100).toFixed(1)}%`,
              ])}
            />
            <Table
              corner="Rule"
              head={["Mean", "Δ mean", "Std", "Δ std"]}
              numeric={[1, 2, 3, 4]}
              caption="What that does to the summary"
              rows={outliers.data.results.map((r) => [
                r.rule,
                r.mean === null ? "—" : formatTick(r.mean),
                r.mean_shift === 0 ? "—" : formatTick(r.mean_shift),
                r.std === null ? "—" : formatTick(r.std),
                r.std_shift === 0 ? "—" : formatTick(r.std_shift),
              ])}
            />
            <p className="field-label">Standard deviation under each rule</p>
            <BarChart
              entries={outliers.data.results.map((r) => [r.rule, r.std ?? 0])}
              format={(v) => formatTick(v)}
            />
            <Table
              corner="Rule"
              head={["What it does"]}
              rows={outliers.data.results.map((r) => [r.rule, r.blurb])}
            />
            <p className="fig-footnote">
              Winsorizing drops nothing — it pulls extreme values back to the fence — so its row
              keeps every observation while still moving the mean. That is the trade: it refuses to
              throw away a person, and in exchange it reports a value that person did not have.
              The IQR fences for this column are{" "}
              {formatTick(outliers.data.fences[0])} to {formatTick(outliers.data.fences[1])}.
            </p>
          </>
        )}
      </Module>

      <Module index="04" title="How Many Questions" meta="Multiple comparisons">
        <p className="text">
          The experiment this page exists for. Test every numeric column against one grouping at
          once, and count what comes out &ldquo;significant&rdquo;. At α = 0.05 across{" "}
          {screen.data?.tests_run ?? 15} tests you would expect about{" "}
          <strong>{screen.data?.false_positives_expected ?? "0.75"}</strong> findings from a dataset
          where nothing was really different — so finding one is not a finding.
        </p>
        <Figure
          title={group ? `Every column against ${labelOf(group)}` : "Bulk screen"}
          caption="One dot per column, sorted by p-value. A dot below a line clears that threshold."
          meta={screen.data ? `${screen.data.tests_run} tests` : undefined}
          controls={
            <>
              <Picker label="Group by" value={group} options={categorical} onChange={setGroup} />
              <Picker
                label="α"
                value={String(alpha)}
                options={ALPHAS}
                onChange={(next) => setAlpha(Number(next))}
              />
            </>
          }
          legend={screen.data ? <ScreenLegend data={screen.data} /> : undefined}
          footnote={
            screen.data ? (
              <>
                {screen.data.not_causal} Note the η² column below: on this dataset almost every
                column clears α against almost every grouping, and almost none of them explains
                more than 1% of the variation. A p-value answers &ldquo;could this be
                nothing?&rdquo;; at n = 9,254 the answer is usually no, and it is still the wrong
                question.
              </>
            ) : undefined
          }
        >
          {screen.error && <Status message={screen.error} isError />}
          {!screen.error && !screen.data && <Loading what="15 group comparisons" />}
          {screen.data && <ScreenChart data={screen.data} />}
        </Figure>
        {screen.data && (
          <>
            <StatGrid
              cells={[
                { k: "Tests run", v: screen.data.tests_run },
                { k: "Clear α alone", v: screen.data.counts.raw, note: `α = ${screen.data.alpha}` },
                { k: "Survive Bonferroni", v: screen.data.counts.bonferroni, note: `α/m = ${screen.data.bonferroni_alpha.toExponential(1)}` },
                { k: "Survive B–H", v: screen.data.counts.benjamini_hochberg, note: "false-discovery rate" },
              ]}
            />
            {/* The three verdicts live in ONE column, not three. As three they
                were three columns of "pass" and "—" that pushed the table past
                a phone screen, and the thing a reader wants from them is not
                three booleans but the answer to "how far does this one get?" */}
            <Table
              corner="Column"
              head={["p-value", "η² (effect)", "Survives"]}
              numeric={[1, 2]}
              caption="Sorted by p-value, smallest first"
              rows={screen.data.tests.map((t) => [
                labelOf(t.column),
                t.p_value < 0.001 ? t.p_value.toExponential(1) : t.p_value.toFixed(4),
                t.eta_squared.toFixed(4),
                survivesLabel(t),
              ])}
            />
            <p className="fig-footnote">
              Bonferroni divides α by the number of tests, which controls the chance of{" "}
              <em>any</em> false positive and is brutal. Benjamini–Hochberg instead controls the
              expected <em>share</em> of the findings that are false, using a sloped threshold that
              is strict on the weakest results and nearly as forgiving as α on the strongest. Where
              the two disagree is the most interesting row in the table.
            </p>
          </>
        )}
      </Module>
    </>
  );
}
