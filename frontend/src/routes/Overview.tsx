// Overview — the masthead, the live analysis widget, and dataset telemetry.
//
// Same shape as every other route: content as data at the top, composition at
// the bottom, page furniture from components/Page.tsx, data through lib/hooks.

import type { JSX } from "react";
import { useEffect, useMemo, useState } from "react";
import { Masthead, Module, Ribbon, StatGrid, Status } from "../components/Page";
import type { RibbonCell, SpecRow } from "../components/Page";
import { ResultView } from "../components/ResultView";
import { useAnalysis, useDataset } from "../lib/hooks";
import type { Tier } from "../types/engine";
import { GROUPING_TIERS, TIERS } from "../types/engine";

const HEADLINE: RibbonCell[] = [
  { v: "05", k: "Analysis tiers" },
  { v: "08", k: "Statistics / column" },
  { v: <>&lt;1<small> ms</small></>, k: "Core compute" },
  { v: <>100<small> %</small></>, k: "Deterministic · cached" },
];

/** A row of selectable chips — the tier, column and group pickers are identical. */
function ChipRow({
  label,
  note,
  options,
  selected,
  onPick,
  withTierAttr = false,
}: {
  label: string;
  note?: string;
  options: string[];
  selected: string | null;
  onPick: (value: string) => void;
  withTierAttr?: boolean;
}): JSX.Element {
  return (
    <div className="field">
      <p className="field-label">
        {label} {note && <span className="field-note">{note}</span>}
      </p>
      <ul className="channel-grid" role="list" aria-label={label}>
        {options.length === 0 && <li className="channel-empty">Loading…</li>}
        {options.map((option) => (
          <li key={option}>
            {/* data-tier drives the expert tier's full-RGB treatment --
                see .channel[data-tier="expert"] in styles.css. */}
            <button
              type="button"
              className={`channel${option === selected ? " is-active" : ""}`}
              {...(withTierAttr ? { "data-tier": option } : {})}
              aria-pressed={option === selected}
              onClick={() => onPick(option)}
            >
              {option || "none"}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function Overview(): JSX.Element {
  const { columns, overview, error: datasetError } = useDataset();

  const [tier, setTier] = useState<Tier>("basic");
  const [column, setColumn] = useState<string | null>(null);
  const [group, setGroup] = useState("");

  const available = useMemo(
    () => (tier === "categorical" ? (columns?.categorical ?? []) : (columns?.columns ?? [])),
    [tier, columns],
  );

  // Keep the selection valid when the tier swaps which column list applies.
  useEffect(() => {
    if (available.length === 0) return;
    setColumn((current) =>
      current && available.includes(current) ? current : (available[0] ?? null),
    );
  }, [available]);

  const effectiveGroup = GROUPING_TIERS.has(tier) ? group : "";
  const { result, elapsedMs, error: analysisError, loading } = useAnalysis(
    tier,
    column,
    effectiveGroup,
  );

  const dataset = columns?.dataset ?? "nhanes.csv";
  const spec: SpecRow[] = [
    { k: "Engine", v: "FastAPI" },
    { k: "Frontend", v: "React · TS" },
    { k: "Runtime", v: "Pandas" },
    { k: "Status", v: <span className="spec-live">Live demo</span> },
  ];

  const status =
    datasetError ??
    analysisError ??
    (loading
      ? `Computing ${tier} for ${column}…`
      : result
        ? `${tier} · ${column}${effectiveGroup ? ` by ${effectiveGroup}` : ""}`
        : `${available.length} analyzable columns in ${dataset}.`);

  return (
    <>
      <Masthead
        eyebrow="Descriptive-statistics engine"
        title="Data Analysis"
        tagline={
          <>
            The analysis engine behind my Medicine &amp; Health science-fair project — try it live
            below.
          </>
        }
        byline="By Anirudh Gupta"
        spec={spec}
        specLabel="Engine specification"
      />

      <Ribbon cells={HEADLINE} />

      <Module index="01" title="Statistical Analysis" meta="Live compute">
        <p className="text">
          Pick an analysis tier and a column from <code>{dataset}</code> — a curated slice of the
          NHANES 2017–2018 data behind this project — optionally grouped by a category — and the
          engine computes the rest.
        </p>

        <div className="fields">
          <ChipRow
            label="Tier"
            options={[...TIERS]}
            selected={tier}
            onPick={(value) => setTier(value as Tier)}
            withTierAttr
          />
          <ChipRow label="Column" options={available} selected={column} onPick={setColumn} />
          {GROUPING_TIERS.has(tier) && (
            <ChipRow
              label="Group by"
              note="optional"
              options={["", ...(columns?.categorical ?? [])]}
              selected={group}
              onPick={setGroup}
            />
          )}
        </div>

        <Status message={status} isError={Boolean(datasetError ?? analysisError)} />

        {result && <ResultView result={result} tier={tier} elapsedMs={elapsedMs} />}
      </Module>

      <Module index="02" title="Dataset Telemetry" meta={<>Source <code>{dataset}</code></>}>
        <p className="text">Live readout from the source this engine is wired to.</p>
        <StatGrid
          cells={[
            { k: "Records", v: overview?.rows ?? "—" },
            { k: "Fields", v: overview?.columns ?? "—" },
            { k: "Analyzable", v: overview?.analyzable ?? "—" },
            { k: "Categorical", v: overview?.categorical ?? "—" },
            { k: "Complete", v: overview?.complete_rows ?? "—" },
          ]}
        />
      </Module>
    </>
  );
}
