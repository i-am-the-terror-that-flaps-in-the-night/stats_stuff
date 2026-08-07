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
  { k: "Cache", v: "Unbounded · warmed" },
  { k: "Runtime", v: "Pandas" },
];

const HEADLINE: RibbonCell[] = [
  { v: <>0.9<small> ms</small></>, k: "Warm response" },
  { v: <>0.3<small> s</small></>, k: "Boot to ready" },
  { v: <>0.9<small> s</small></>, k: "Background warm-up" },
  { v: "1", k: "Load per process" },
];

const LATENCY: StatCell[] = [
  { k: "Basic · first", v: "0.6", note: "ms" },
  { k: "Advanced · first", v: "42", note: "ms" },
  { k: "Cached · any tier", v: "<0.01", note: "ms" },
  { k: "Dataframe load", v: "175", note: "ms · once" },
  { k: "Resident memory", v: "~170", note: "MB" },
  { k: "Cache capacity", v: "∞", note: "bounded key space" },
];

/** The four places an answer can be waiting, from furthest out to nearest. */
const LAYERS: [string, string, string, string][] = [
  [
    "Browser",
    "1 h fresh + 24 h stale",
    "0 ms",
    "Reuse without asking; then serve the stored copy while refreshing behind you.",
  ],
  [
    "Revalidate",
    "ETag → 304",
    "~200 B",
    "When it does ask, an unchanged answer costs headers instead of its payload.",
  ],
  [
    "Process",
    "lru_cache, unbounded",
    "0.9 ms",
    "Every compute path memoised. Nothing is ever evicted and recomputed.",
  ],
  [
    "Startup",
    "background thread",
    "0.9 s, once",
    "Fills the memos before the first visitor asks, off the readiness path.",
  ],
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

      <Module index="03" title="Caching" meta="Four layers">
        <p className="text">
          Nothing in the service can change while it runs — the CSV is read once and is
          immutable after that — so every answer is a pure function of its inputs and is worth
          keeping. Four layers keep it, and a request stops at the first one that already has
          the answer.
        </p>
        <Table
          corner="Layer"
          head={["Mechanism", "Repeat cost", "What it does"]}
          rows={LAYERS}
          numeric={[2]}
        />
        <p className="prose">
          The long browser TTL is only safe because of the layer under it: every API response
          carries an <span className="expr">ETag</span> derived from the deployed code and data,
          so a redeploy changes every tag at once and the first revalidation after it returns
          real bytes. Without that, an hour of <span className="expr">max-age</span> would mean
          an hour of serving a bug that had already been fixed.
        </p>
        <p className="prose">
          The caches are <strong>unbounded on purpose</strong>, which is only defensible because
          the key space is small and closed: 5 tiers × 15 numeric columns × 4 grouping choices,
          every one validated before it reaches a cache. There is no user input that can grow
          it, so &ldquo;unbounded&rdquo; is a few hundred entries and a bounded LRU could only
          ever evict something that will be asked for again. Live hit counts are at{" "}
          <span className="expr">/api/cache</span>.
        </p>
      </Module>

      <Module index="04" title="How These Were Taken" meta="Scope &amp; honesty">
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
        <p className="prose">
          The <strong>first-call</strong> column above is now the rarer path, not the common one:
          the startup warm-up computes the basic and medium tiers for all 15 columns and all four
          figures before anyone asks, so most cold numbers are paid by a background thread rather
          than by a visitor. They are published anyway — they are what the engine actually costs,
          and a benchmark that only reported the warmed path would be measuring the cache.
        </p>
      </Module>
    </>
  );
}
