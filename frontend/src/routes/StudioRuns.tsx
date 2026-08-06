// Studio run log — every saved analysis, newest first.

import type { JSX } from "react";
import { Crumbs, Masthead, Module, Status, Table } from "../components/Page";
import { useRuns } from "../lib/hooks";

export function StudioRuns(): JSX.Element {
  const { runs, error } = useRuns();

  return (
    <>
      <Crumbs here="Runs" />

      <Masthead
        eyebrow="Run log"
        title="Saved Runs"
        tagline="Every analysis saved from the Studio, newest first. The log is a local SQLite file, so an empty list is the normal online state."
        byline="By Anirudh Gupta"
        spec={[
          { k: "Entries", v: runs.length },
          { k: "Store", v: "SQLite" },
          { k: "Scope", v: "Local" },
          { k: "Order", v: "Newest first" },
        ]}
        specLabel="Log status"
      />

      {error && <Status message={error} isError />}

      <Module index="01" title="Log" meta={`${runs.length} runs`}>
        {!error && runs.length === 0 ? (
          <p className="text">Nothing saved yet.</p>
        ) : (
          <Table
            corner="When"
            head={["Tier", "Column", "Group", "Dataset", "ms"]}
            rows={runs.map((r) => [
              r.when_short,
              r.tier,
              r.column,
              r.group ?? "—",
              r.dataset,
              r.duration_ms,
            ])}
            numeric={[5]}
          />
        )}
      </Module>
    </>
  );
}
