// Studio analyze — one analysis as a flat ledger, with a save-to-log action.
//
// The Overview renders the same result as a nested tree (components/ResultView);
// this is the flat reading of it. Both consume the identical /api/analyze payload.

import type { JSX } from "react";
import { useCallback, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { BarChart } from "../components/BarChart";
import { Crumbs, Masthead, Module, Status, Table } from "../components/Page";
import { recordRun } from "../lib/api";
import { useAnalysis } from "../lib/hooks";
import { chartRows, resultRows, scalar } from "../lib/ledger";
import { prettify } from "../lib/format";
import { TIERS } from "../types/engine";

export function StudioAnalyze(): JSX.Element {
  const { tier = "basic", column = "" } = useParams();
  const [params] = useSearchParams();
  const group = params.get("group") ?? "";
  const navigate = useNavigate();

  const { result, elapsedMs, error, loading } = useAnalysis(tier, column, group);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const save = useCallback(async () => {
    setSaving(true);
    setSaveError(null);
    try {
      await recordRun({ tier, column, group: group || null, duration_ms: elapsedMs });
      void navigate("/studio/runs");
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Could not save the run.");
    } finally {
      setSaving(false);
    }
  }, [tier, column, group, elapsedMs, navigate]);

  const rows = result ? resultRows(result) : [];
  const bars = result ? chartRows(result) : [];
  // A categorical column can only run the categorical tier, and vice versa.
  const offered = TIERS.filter((t) =>
    tier === "categorical" ? t === "categorical" : t !== "categorical",
  );

  return (
    <>
      <Crumbs here={`${tier} / ${column}`} />

      <Masthead
        eyebrow={`${tier} tier`}
        title={column}
        tagline={group ? `Grouped by ${group}.` : "Ungrouped."}
        byline="By Anirudh Gupta"
        spec={[
          { k: "Tier", v: tier },
          { k: "Group", v: group || "none" },
          { k: "Elapsed", v: `${elapsedMs} ms` },
          { k: "Rows", v: rows.length },
        ]}
        specLabel="Run detail"
      />

      <Module index="01" title="Tier" meta={loading ? "computing…" : `${elapsedMs} ms`}>
        <ul className="channel-grid" role="list" aria-label="Analysis tier">
          {offered.map((t) => (
            <li key={t}>
              <Link
                className={`channel${t === tier ? " is-active" : ""}`}
                data-tier={t}
                to={`/studio/analyze/${t}/${encodeURIComponent(column)}${
                  group ? `?group=${encodeURIComponent(group)}` : ""
                }`}
              >
                {t}
              </Link>
            </li>
          ))}
        </ul>
        {error && <Status message={error} isError />}
        {saveError && <Status message={saveError} isError />}
      </Module>

      {bars.length > 0 && (
        <Module index="02" title="Shape" meta="Same-scale figures">
          <BarChart entries={bars} format={scalar} title={`${column} — ${tier}`} />
        </Module>
      )}

      <Module index={bars.length > 0 ? "03" : "02"} title="Ledger" meta={`${rows.length} figures`}>
        {rows.length === 0 && !error ? (
          <p className="text">{loading ? "Computing…" : "Nothing to report."}</p>
        ) : (
          <Table
            corner="Statistic"
            head={["Value"]}
            rows={rows.map(([k, v]) => [prettify(k), v])}
            numeric={[1]}
          />
        )}
        <p>
          <button
            type="button"
            className="channel"
            onClick={() => void save()}
            disabled={saving || !result}
          >
            {saving ? "Saving…" : "Save this run"}
          </button>
        </p>
      </Module>
    </>
  );
}
