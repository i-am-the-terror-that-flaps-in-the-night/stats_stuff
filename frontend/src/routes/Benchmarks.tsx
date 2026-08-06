// Benchmarks — measured timings for the engine, cold and cached.
//
// Content is data at the top, composition at the bottom; the page furniture
// comes from components/Page.tsx. Every route in this directory is shaped the
// same way, so a change to the masthead or a module head happens in one place
// rather than five.

import type { JSX } from "react";
import { Crumbs, Masthead, Module, Ribbon, StatGrid, Table } from "../components/Page";
import type { RibbonCell, SpecRow, StatCell } from "../components/Page";

const SPEC: SpecRow[] = [
  { k: "Dataset", v: "9,254 × 18" },
  { k: "Worker", v: "1 · free tier" },
  { k: "Cache", v: "LRU · in-proc" },
  { k: "Runtime", v: "Pandas" },
];

const HEADLINE: RibbonCell[] = [
  { v: <>0.6<small> ms</small></>, k: "Median first compute" },
  { v: <>~0<small> ms</small></>, k: "Cached lookup" },
  { v: "256", k: "Memoised results" },
  { v: "1", k: "Load per process" },
];

const LATENCY: StatCell[] = [
  { k: "Basic · first", v: "0.6", note: "ms" },
  { k: "Advanced · first", v: "42", note: "ms" },
  { k: "Cached · any tier", v: "<0.01", note: "ms" },
  { k: "Dataframe load", v: "175", note: "ms · once" },
  { k: "Resident memory", v: "~170", note: "MB" },
  { k: "Cache capacity", v: "256", note: "results" },
];

const BY_TIER: [string, string, string, string][] = [
  ["basic", "0.6 ms", "<0.01 ms", "Pure aggregation over one column."],
  ["medium", "9.9 ms", "<0.01 ms", "Repeats basic across each group."],
  ["advanced", "42 ms", "<0.01 ms", "Correlation / regression via statsmodels."],
  ["expert", "40 ms", "<0.01 ms", "VIF, residual diagnostics & trend tests — the deepest tier."],
  ["categorical", "28 ms", "<0.01 ms", "Value counts and proportions."],
];

export function Benchmarks(): JSX.Element {
  return (
    <>
      <Crumbs here="Benchmarks" />

      <Masthead
        eyebrow="Performance · measured"
        title="Benchmarks"
        tagline={
          <>
            The engine caches every answer, so the interesting question isn&rsquo;t &ldquo;how fast
            is a request&rdquo; but &ldquo;how fast is the <em>first</em> one.&rdquo; Both are below.
          </>
        }
        byline="By Anirudh Gupta"
        spec={SPEC}
        specLabel="Benchmark environment"
      />

      <Ribbon cells={HEADLINE} label="Headline figures" />

      <Module index="01" title="Compute Latency" meta="Per request">
        <p className="text">
          Time to compute one tier for one column, excluding network. The dataset is loaded and
          cleaned once per process, so these figures measure statistics, not I/O.
        </p>
        <StatGrid cells={LATENCY} />
      </Module>

      <Module index="02" title="By Tier" meta="Cold vs. warm">
        <p className="text">
          The gap between the first (cold) call and every repeat (warm, from cache) is the whole
          point of the caching layer — the advanced tier pays a real one-time cost and then
          effectively nothing.
        </p>
        <Table
          corner="Tier"
          head={["First call", "Cached", "Notes"]}
          rows={BY_TIER}
          numeric={[1, 2]}
        />
      </Module>

      <Module index="03" title="How These Were Taken" meta="Scope &amp; honesty">
        <p className="prose">
          Figures are <strong>indicative, measured locally</strong> against the curated NHANES
          dataset — <strong>9,254 rows by 18 fields</strong> — on a single worker, the same
          free-tier shape the live demo runs on. They describe this dataset at this size; a larger
          file would move the first-call numbers, though the cached path stays flat by construction.
        </p>
        <p className="prose">
          &ldquo;Cached&rdquo; is the honest common case: because results are memoised on{" "}
          <span className="expr">(tier, column, group)</span>, anyone re-opening a figure — or a
          second visitor asking the same question — is served from memory. The point of publishing
          the cold numbers too is that nothing here is hidden behind the cache.
        </p>
      </Module>
    </>
  );
}
