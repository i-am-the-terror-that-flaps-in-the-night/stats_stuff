// Studio — the bench.
//
// This used to be a directory: a list of columns, each a link to a page that
// ran one tier. That is a browser, not a studio. The difference is that a
// studio has knobs, and turning one changes the answer in front of you.
//
// The knob here is the COHORT. Every statistic on the rest of this site is
// computed over all 9,254 rows, which is the one cohort nobody actually studies
// — real questions are about women over 40, or people with an income ratio
// under 1. Building that subset and watching the summary move is the whole
// point, and the "kept" counter next to each filter is there because the second
// thing that happens when you narrow a population is that you run out of it.

import { useCallback, useMemo, useState } from "react";
import type { JSX } from "react";
import { Link, useNavigate } from "react-router";
import { BarChart } from "../components/BarChart";
import { Crumbs, Masthead, Module, Status, StatGrid, Table } from "../components/Page";
import { Picker } from "../components/figures/ChartFrame";
import { recordRun } from "../lib/api";
import { useAnalysis, useCohort, useStudioIndex } from "../lib/hooks";
import { chartRows, resultRows, scalar } from "../lib/ledger";
import { prettify } from "../lib/format";
import { formatCount, formatTick, labelOf } from "../lib/scales";
import { GROUPING_TIERS, TIERS, isTier } from "../types/engine";
import type { CohortResponse, Summary } from "../types/engine";

// Operators offered per column kind. A label column can only be matched, since
// "Gender > Female" is not a question. Typed as readonly string[] rather than a
// const tuple: the two lists are picked between at runtime, and a union of two
// const tuples narrows `includes` to their INTERSECTION ("="), which rejects
// every operator that is only in one of them.
const NUMERIC_OPS: readonly string[] = [">=", ">", "=", "<", "<="];
const LABEL_OPS: readonly string[] = ["=", "!="];
const DEFAULT_OP = ">=";

interface Draft {
  column: string;
  op: string;
  value: string;
}

/** Two summaries side by side, with the difference spelled out. */
function CohortCompare({ data }: { data: CohortResponse }): JSX.Element {
  const rowsFor = (s: Summary): string[] => [
    formatCount(s.n),
    s.mean === null ? "—" : formatTick(s.mean),
    s.median === null ? "—" : formatTick(s.median),
    s.std === null ? "—" : formatTick(s.std),
  ];
  return (
    <Table
      corner="Rows"
      head={["n", "Mean", "Median", "Std"]}
      numeric={[1, 2, 3, 4]}
      caption={`${labelOf(data.column)} — cohort against everyone`}
      rows={[
        ["This cohort", ...rowsFor(data.cohort)],
        ["Whole dataset", ...rowsFor(data.overall)],
      ]}
    />
  );
}

export function StudioIndex(): JSX.Element {
  const { columns, overview, datasets, recent, error } = useStudioIndex();
  const navigate = useNavigate();

  const numeric = columns?.columns ?? [];
  const labels = columns?.categorical ?? [];

  // ---- the cohort knob ----
  const [filters, setFilters] = useState<string[]>([]);
  const [draft, setDraft] = useState<Draft>({ column: "", op: ">=", value: "" });
  const [subject, setSubject] = useState<string>("");

  // Joined, because a hook dep list compares by identity and a fresh array
  // every render would re-fire the request forever. Newline is the separator:
  // it cannot appear in a filter expression built by the pickers.
  const filterKey = filters.join("\n");
  const activeSubject = subject || numeric[0] || null;
  const cohort = useCohort(activeSubject, filterKey);

  const draftColumn = draft.column || numeric[0] || "";
  const draftIsLabel = labels.includes(draftColumn);
  const ops = draftIsLabel ? LABEL_OPS : NUMERIC_OPS;
  // Switching from a numeric to a label column can leave ">=" selected, which
  // that column does not accept — fall back rather than sending it.
  const activeOp = ops.includes(draft.op) ? draft.op : (ops[0] ?? DEFAULT_OP);

  // A label column offers its actual values; a numeric one takes a typed number.
  // A free-text box for Gender is a way to build a cohort of nobody and not
  // understand why — "Non-Hispanic White" is not a string anyone types
  // correctly from memory, and a filter that matches nothing looks identical to
  // a cohort that genuinely is empty.
  const labelValues = useMemo(
    () => (draftIsLabel ? (columns?.values?.[draftColumn] ?? []) : []),
    [draftIsLabel, draftColumn, columns],
  );

  // A label dropdown shows its first option before anything is picked, so an
  // untouched dropdown has to mean that option — otherwise Add filter is dead
  // until you re-select the value already on screen.
  const draftValue = (draft.value || labelValues[0] || "").trim();

  const addFilter = useCallback(() => {
    if (!draftColumn || !draftValue) return;
    const next = `${draftColumn}${activeOp}${draftValue}`;
    setFilters((current) => (current.includes(next) ? current : [...current, next]));
    setDraft((current) => ({ ...current, value: "" }));
  }, [draftValue, draftColumn, activeOp]);

  const removeFilter = useCallback((expression: string) => {
    setFilters((current) => current.filter((f) => f !== expression));
  }, []);

  // ---- the analysis knob ----
  const [tier, setTier] = useState<string>("basic");
  const [analysisColumn, setAnalysisColumn] = useState<string>("");
  const [group, setGroup] = useState<string>("");
  const activeColumn = analysisColumn || numeric[0] || null;
  const groupable = isTier(tier) && GROUPING_TIERS.has(tier);
  const analysis = useAnalysis(tier, activeColumn, groupable ? group : "");

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const save = useCallback(async () => {
    if (!activeColumn) return;
    setSaving(true);
    setSaveError(null);
    try {
      await recordRun({
        tier,
        column: activeColumn,
        group: groupable && group ? group : null,
        duration_ms: analysis.elapsedMs,
      });
      void navigate("/studio/runs");
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Could not save the run.");
    } finally {
      setSaving(false);
    }
  }, [tier, activeColumn, group, groupable, analysis.elapsedMs, navigate]);

  const ledger = analysis.result ? resultRows(analysis.result) : [];
  const bars = analysis.result ? chartRows(analysis.result) : [];

  return (
    <>
      <Crumbs here="Studio" />

      <Masthead
        eyebrow="The bench"
        title="Studio"
        tagline={
          <>
            Build a cohort, run a tier against it, and save what you find. Everything here is a
            knob — the dataset does not change, but which slice of it you are looking at does,
            and the numbers move when you turn one.
          </>
        }
        byline="By Anirudh Gupta"
        spec={[
          { k: "Dataset", v: columns?.dataset ?? "…" },
          { k: "Cohort", v: cohort.data ? formatCount(cohort.data.rows_kept) : "…" },
          { k: "Filters", v: filters.length || "none" },
          { k: "Saved runs", v: recent.length },
        ]}
        specLabel="Bench status"
      />

      {error && <Status message={error} isError />}

      <Module
        index="01"
        title="Cohort"
        meta={
          cohort.data
            ? `${formatCount(cohort.data.rows_kept)} of ${formatCount(cohort.data.rows_total)} rows`
            : "all rows"
        }
      >
        <p className="text">
          Narrow the dataset, then watch what the narrowing did. Each filter shows how many rows
          survived it — a cohort that runs out of people is the most common way an interesting
          finding turns out to be noise.
        </p>

        <div className="fig-controls">
          <Picker
            label="Where"
            value={draftColumn}
            options={[...numeric, ...labels]}
            onChange={(next) => setDraft((c) => ({ ...c, column: next, value: "" }))}
          />
          <Picker
            label="Is"
            value={activeOp}
            options={[...ops]}
            onChange={(next) => setDraft((c) => ({ ...c, op: next }))}
          />
          {labelValues.length > 0 ? (
            <Picker
              label="Value"
              value={draft.value || (labelValues[0] ?? "")}
              options={labelValues}
              onChange={(next) => setDraft((c) => ({ ...c, value: next }))}
            />
          ) : (
            <span className="fig-pick">
              <label className="fig-pick-label" htmlFor="filter-value">
                Value
              </label>
              <input
                id="filter-value"
                className="fig-pick-input"
                inputMode={draftIsLabel ? "text" : "decimal"}
                value={draft.value}
                placeholder={draftIsLabel ? "e.g. Female" : "e.g. 40"}
                onChange={(event) => setDraft((c) => ({ ...c, value: event.target.value }))}
                onKeyDown={(event) => {
                  if (event.key === "Enter") addFilter();
                }}
              />
            </span>
          )}
          <button type="button" className="channel" onClick={addFilter} disabled={!draftValue}>
            Add filter
          </button>
          {filters.length > 0 && (
            <button type="button" className="channel" onClick={() => setFilters([])}>
              Clear all
            </button>
          )}
        </div>

        {filters.length === 0 ? (
          <p className="text">
            No filters — the cohort is everyone. Add one above, or try{" "}
            <code className="expr">Age &gt;= 40</code>.
          </p>
        ) : (
          <ul className="chip-row" role="list" aria-label="Active filters">
            {filters.map((expression, index) => {
              const applied = cohort.data?.filters[index];
              return (
                <li key={expression}>
                  <button
                    type="button"
                    className="chip is-removable"
                    onClick={() => removeFilter(expression)}
                    aria-label={`Remove filter ${expression}`}
                  >
                    {expression}
                    {applied && <b>{formatCount(applied.remaining)} left</b>}
                    <span aria-hidden="true">×</span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}

        <div className="fig-controls">
          <Picker
            label="Summarise"
            value={activeSubject ?? ""}
            options={numeric}
            onChange={setSubject}
          />
        </div>

        {cohort.error && <Status message={cohort.error} isError />}
        {cohort.data && (
          <>
            {cohort.data.too_small && (
              <Status
                message={`Only ${cohort.data.cohort.n} values left — under ${cohort.data.min_cohort}, these numbers describe individuals rather than a group.`}
              />
            )}
            <StatGrid
              cells={[
                { k: "Rows kept", v: formatCount(cohort.data.rows_kept) },
                {
                  k: "Share of dataset",
                  v: cohort.data.kept_share === null ? "—" : `${(cohort.data.kept_share * 100).toFixed(1)}%`,
                },
                {
                  k: "Cohort mean",
                  v: cohort.data.cohort.mean === null ? "—" : formatTick(cohort.data.cohort.mean),
                  note: labelOf(cohort.data.column),
                },
                {
                  k: "Shift",
                  v: cohort.data.shift_in_sds === null ? "—" : cohort.data.shift_in_sds.toFixed(2),
                  note: "SDs from everyone",
                },
              ]}
            />
            <CohortCompare data={cohort.data} />
            <p className="fig-footnote">
              &ldquo;Shift&rdquo; is the gap between the two means measured in the whole
              dataset&rsquo;s standard deviations. It is deliberately not a p-value: a cohort you
              chose after looking at the data is not a hypothesis, and testing it would dress up a
              fishing expedition as a finding.
            </p>
          </>
        )}
      </Module>

      <Module
        index="02"
        title="Run a Tier"
        meta={analysis.loading ? "computing…" : `${analysis.elapsedMs} ms`}
      >
        <p className="text">
          The engine, on the bench. Pick a depth and a column; deeper tiers add distribution
          shape, then group comparisons, then regression diagnostics.
        </p>
        <div className="fig-controls">
          <Picker label="Tier" value={tier} options={[...TIERS]} onChange={setTier} />
          <Picker
            label="Column"
            value={activeColumn ?? ""}
            options={tier === "categorical" ? labels : numeric}
            onChange={setAnalysisColumn}
          />
          {groupable && (
            <Picker
              label="Group by"
              value={group}
              options={labels}
              onChange={setGroup}
              allowNone
              noneLabel="No split"
            />
          )}
          <button
            type="button"
            className="channel"
            onClick={() => void save()}
            disabled={saving || !analysis.result}
          >
            {saving ? "Saving…" : "Save this run"}
          </button>
        </div>

        {analysis.error && <Status message={analysis.error} isError />}
        {saveError && <Status message={saveError} isError />}

        {bars.length > 0 && <BarChart entries={bars} format={scalar} />}

        {ledger.length === 0 && !analysis.error ? (
          <p className="text">{analysis.loading ? "Computing…" : "Nothing to report."}</p>
        ) : (
          <Table
            corner="Statistic"
            head={["Value"]}
            rows={ledger.map(([k, v]) => [prettify(k), v])}
            numeric={[1]}
          />
        )}
        <p className="fig-footnote">
          This runs against the WHOLE dataset, not the cohort above — the engine&rsquo;s tiers take
          a column and a grouping, not a row filter. The cohort panel is the row-filter experiment;
          keeping them separate is what stops a saved run from meaning something different
          depending on what was typed into a text box three modules ago.
        </p>
      </Module>

      <Module index="03" title="Experiments" meta={<Link to="/studio/experiments">open the lab</Link>}>
        <p className="text">
          Four experiments that turn a knob you cannot turn anywhere else on this site: how much a
          result depends on the number of people in the study, on which values you call outliers,
          and on how many questions you asked before you found the answer you liked.
        </p>
        <Table
          corner="Experiment"
          head={["The knob", "What it shows"]}
          rows={[
            ["Sample size", "How many people", "Why a small study can land anywhere"],
            ["Bootstrap", "Resample the data", "Where a confidence interval comes from"],
            ["Outlier rules", "What counts as data", "How much a summary is a judgement call"],
            ["Multiple comparisons", "How many questions", "How false positives appear from nothing"],
          ]}
        />
      </Module>

      <Module index="04" title="Columns" meta={columns?.dataset ?? "loading…"}>
        {overview && (
          <StatGrid
            cells={[
              { k: "Records", v: formatCount(overview.rows) },
              { k: "Fields", v: overview.columns },
              { k: "Numeric", v: numeric.length },
              { k: "Categorical", v: labels.length },
            ]}
          />
        )}
        <p className="field-label">Numeric — opens at the basic tier</p>
        <ul className="channel-grid" role="list">
          {numeric.map((c) => (
            <li key={c}>
              <Link className="channel" to={`/studio/analyze/basic/${encodeURIComponent(c)}`}>
                {c}
              </Link>
            </li>
          ))}
        </ul>
        <p className="field-label">Categorical</p>
        <ul className="channel-grid" role="list">
          {labels.map((c) => (
            <li key={c}>
              <Link className="channel" to={`/studio/analyze/categorical/${encodeURIComponent(c)}`}>
                {c}
              </Link>
            </li>
          ))}
        </ul>
      </Module>

      <Module index="05" title="Datasets" meta="Availability is live">
        <Table
          corner="File"
          head={["Status", "What it is"]}
          rows={datasets.map((d) => [d.label, d.available ? "available" : "local only", d.blurb])}
        />
      </Module>

      <Module index="06" title="Recent Runs" meta={<Link to="/studio/runs">full log</Link>}>
        {recent.length === 0 ? (
          <p className="text">No runs saved yet.</p>
        ) : (
          <Table
            corner="When"
            head={["Tier", "Column", "Group", "ms"]}
            rows={recent.map((r) => [r.when_short, r.tier, r.column, r.group ?? "—", r.duration_ms])}
            numeric={[4]}
          />
        )}
      </Module>
    </>
  );
}
