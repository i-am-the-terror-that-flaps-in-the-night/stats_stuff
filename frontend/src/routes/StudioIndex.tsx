// Studio index — the dataset summary, the column pickers, and recent runs.
//
// Same shape as every other route: hooks, then guard clauses, then composition
// from components/Page.tsx.

import type { JSX } from "react";
import { Link } from "react-router";
import { Crumbs, Masthead, Module, Status, StatGrid, Table } from "../components/Page";
import { useStudioIndex } from "../lib/hooks";

export function StudioIndex(): JSX.Element {
  const { columns, overview, datasets, recent, error } = useStudioIndex();

  return (
    <>
      <Crumbs here="Studio" />

      <Masthead
        eyebrow="Analysis console"
        title="Studio"
        tagline="Run any tier against any column, then save the run to the log."
        byline="By Anirudh Gupta"
        spec={[
          { k: "Dataset", v: columns?.dataset ?? "…" },
          { k: "Numeric", v: columns?.columns.length ?? "…" },
          { k: "Categorical", v: columns?.categorical.length ?? "…" },
          { k: "Saved runs", v: recent.length },
        ]}
        specLabel="Console status"
      />

      {error && <Status message={error} isError />}

      <Module index="01" title="Columns" meta={columns?.dataset ?? "loading…"}>
        {overview && (
          <StatGrid
            cells={[
              { k: "Records", v: overview.rows },
              { k: "Fields", v: overview.columns },
              { k: "Analyzable", v: overview.analyzable },
              { k: "Categorical", v: overview.categorical },
            ]}
          />
        )}
        <p className="field-label">Numeric — opens at the basic tier</p>
        <ul className="channel-grid" role="list">
          {columns?.columns.map((c) => (
            <li key={c}>
              <Link className="channel" to={`/studio/analyze/basic/${encodeURIComponent(c)}`}>
                {c}
              </Link>
            </li>
          ))}
        </ul>
        <p className="field-label">Categorical</p>
        <ul className="channel-grid" role="list">
          {columns?.categorical.map((c) => (
            <li key={c}>
              <Link className="channel" to={`/studio/analyze/categorical/${encodeURIComponent(c)}`}>
                {c}
              </Link>
            </li>
          ))}
        </ul>
      </Module>

      <Module index="02" title="Datasets" meta="Availability is live">
        <Table
          corner="File"
          head={["Status", "What it is"]}
          rows={datasets.map((d) => [d.label, d.available ? "available" : "local only", d.blurb])}
        />
      </Module>

      <Module index="03" title="Recent Runs" meta={<Link to="/studio/runs">full log</Link>}>
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
