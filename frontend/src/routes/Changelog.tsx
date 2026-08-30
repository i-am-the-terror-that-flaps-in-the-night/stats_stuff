// Changelog — release history and roadmap.
//
// Same shape as every other route: content as data at the top, composition at
// the bottom, page furniture from components/Page.tsx.

import type { JSX, ReactNode } from "react";
import { Crumbs, Masthead, Module, Table } from "../components/Page";
import type { SpecRow } from "../components/Page";

const SPEC: SpecRow[] = [
  { k: "Current", v: "v3.2.0" },
  { k: "Released", v: "2026·08·30" },
  { k: "Cadence", v: "Iterative" },
  { k: "Status", v: "Stable" },
];

interface Release {
  ver: string;
  date: string;
  major?: boolean;
  current?: boolean;
  items: ReactNode[];
}

const RELEASES: Release[] = [
  {
    ver: "v3.2.0",
    date: "30 Aug 2026",
    current: true,
    items: [
      <>
        <b>Predict</b> — a new page and API (<span className="expr">/api/predict/*</span>) built on
        a fourth part of <span className="expr">engine.py</span>: a LightGBM model fitted on the
        study's own cohort and its own primary specification, with exact per-feature SHAP
        contributions from the booster's own TreeSHAP — no <span className="expr">shap</span>{" "}
        package, no scikit-learn/numba weight added.
      </>,
      <>
        <b>LLM narration, with a failover chain</b> — Nemotron 3.5 Lightning first, Nemotron 3
        Ultra on any failure, and a generated (never fixed-string) fallback on a second failure,
        built from the same SHAP contributions. The language model only narrates a finished
        prediction; it cannot reach the booster or the cohort, and an unset API key degrades the
        page to &ldquo;working, minus the paragraph,&rdquo; never to broken.
      </>,
      <>
        <b>Offline demo</b> — <span className="expr">offline/index.html</span>, one self-contained
        file with six baked-in predictions for venues with no network.
      </>,
      <>
        <b>Model drift guards</b> — <span className="expr">train-model --check</span> and{" "}
        <span className="expr">build_offline_demo.py --check</span> added to CI alongside the
        existing cohort guard, plus the Render config for the new environment variables.
      </>,
    ],
  },
  {
    ver: "v3.1.0",
    date: "30 Aug 2026",
    items: [
      <>
        <b>Downloads</b> — a dedicated page for exporting a run as a{" "}
        <span className="expr">.zip</span>, bundling figures, tables, and the underlying data
        instead of one file at a time.
      </>,
    ],
  },
  {
    ver: "v3.0.1",
    date: "29 Aug 2026",
    items: [
      <>
        Python version requirement raised and README documentation expanded.
      </>,
      <>
        Argument parsing hardened, model fitting corrected to use proper dtypes.
      </>,
    ],
  },
  {
    ver: "v3.0.0",
    date: "22 Aug 2026",
    major: true,
    items: [
      <>
        <b>Revised protocol</b> — the study analysis rearchitected: Model A/B, a median-cut risk
        score, and the ten-step protocol rewritten for clarity. <span className="expr">cohort.py</span>{" "}
        and <span className="expr">study.py</span> merged back into a single{" "}
        <span className="expr">engine.py</span>. This changes what the engine outputs for study
        runs, not just how it&rsquo;s organized — hence the major version.
      </>,
    ],
  },
  {
    ver: "v2.2.0",
    date: "15 Aug 2026",
    items: [
      <>
        Study protocol descriptions clarified across Figures and Methodology; cohort data made
        explicit.
      </>,
    ],
  },
  {
    ver: "v2.1.0",
    date: "10–12 Aug 2026",
    items: [
      <>
        <b>Figures</b> — the dataset drawn, not just reported: a distribution, group box plots, a
        scatter with its fitted line, an ECDF, and an outlier-rule chart. Inline SVG in
        TypeScript, no charting library.
      </>,
      <>
        Study analysis types formalized, with smoke tests covering them.
      </>,
    ],
  },
  {
    ver: "v2.0.0",
    date: "06 Aug 2026",
    major: true,
    items: [
      <>
        <b>React frontend</b> — the server-rendered Jinja site and its vanilla-JS dashboard were
        deleted outright and replaced with a React 19 + Vite + TypeScript single-page app. Every
        page became a client route over a JSON API; no old URL kept working unchanged — hence the
        major version, not a point release.
      </>,
      <>
        <span className="expr">engine.py</span> nearly doubled in the same push, restructured to
        serve that API instead of rendering templates.
      </>,
    ],
  },
  {
    ver: "v1.0.0",
    date: "04 Aug 2026",
    items: [
      <>
        <b>Studio</b> — an analysis browser and SQLite run ledger alongside the live dashboard,
        live at last, migrated onto a curated NHANES dataset.
      </>,
      <>
        All five analysis tiers (basic, medium, advanced, expert, categorical) supported in one
        pass, with response caching on the JSON endpoints.
      </>,
    ],
  },
  {
    ver: "v0.9.0",
    date: "19–20 Jul 2026",
    items: [
      <>
        Studio, runs, benchmarks, changelog, and methodology page templates scaffolded, with
        client-side navigation between them.
      </>,
      <>
        <b>Expert tier</b> — the deepest numeric tier: multicollinearity (VIF), regression
        diagnostics, threshold counts, and trend tests.
      </>,
    ],
  },
  {
    ver: "v0.8.0",
    date: "13–14 Jul 2026",
    items: [
      <>Engine readability refactor; a proper CLI entry point added.</>,
    ],
  },
  {
    ver: "v0.7.0",
    date: "08–09 Jul 2026",
    items: [
      <>Boot transition animation; static-asset caching strategy revisited; dependency and .gitignore cleanup for security.</>,
    ],
  },
  {
    ver: "v0.6.0",
    date: "06 Jul 2026",
    items: [
      <>
        <b>Categorical tier</b> and <b>dataset telemetry</b> — live shape, analyzable/categorical
        split, complete vs. reduced counts — plus a loading splash and lazy loading for
        performance.
      </>,
    ],
  },
  {
    ver: "v0.5.0",
    date: "04 Jul 2026",
    items: [
      <>
        <b>Advanced tier</b> — correlation and regression wired through statsmodels, with
        group-by support and a footer added to the UI.
      </>,
    ],
  },
  {
    ver: "v0.4.0",
    date: "30 Jun 2026",
    items: [<>Dark theme; filtering restricted to numeric columns; statistical dependencies added.</>],
  },
  {
    ver: "v0.3.0",
    date: "27–29 Jun 2026",
    items: [
      <>
        <b>HTTP API</b> — the engine wrapped in a FastAPI service with a JSON contract, plus the
        first static dashboard for picking a column and reading the result.
      </>,
    ],
  },
  {
    ver: "v0.2.0",
    date: "25 Jun 2026",
    items: [
      <>
        NHANES XPT→CSV pipeline and weighted survey estimates; first web preview scaffold.
      </>,
    ],
  },
  {
    ver: "v0.1.0",
    date: "02–17 Jun 2026",
    items: [
      <>
        <b>The engine</b> — <span className="expr">engine.py</span>: basic descriptive statistics
        over a cleaned dataframe, and the missing-data rule that everything since has protected.
      </>,
    ],
  },
];

const ROADMAP: ReactNode[][] = [
  [
    "Bring-your-own CSV",
    "Upload a file and analyse it in place, without redeploying.",
    <span className="tag tag--next">Planned</span>,
  ],
  [
    "Inline charts",
    "A small distribution sparkline beside each numeric result.",
    <span className="tag tag--next">Exploring</span>,
  ],
  [
    "Shareable runs",
    "A permalink that reopens an exact tier / column / group.",
    <span className="tag tag--next">Exploring</span>,
  ],
];

function ReleaseEntry({ release }: { release: Release }): JSX.Element {
  return (
    <li className={`release${release.current ? " release--now" : ""}`}>
      <div className="release-head">
        <span className="release-ver">{release.ver}</span>
        {release.current && <span className="tag tag--now">Current</span>}
        {release.major && <span className="tag tag--major">Major</span>}
        <span className="release-date">{release.date}</span>
      </div>
      <ul className="release-list">
        {release.items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </li>
  );
}

export function Changelog(): JSX.Element {
  return (
    <>
      <Crumbs here="Changelog" />

      <Masthead
        eyebrow="Release notes"
        title="Changelog"
        tagline="How a short basic-statistics script grew into a five-tier engine with a JSON API, a caching layer, and its own analysis console."
        byline="By Anirudh Gupta"
        spec={SPEC}
        specLabel="Release status"
      />

      <Module index="01" title="Release History" meta="Newest first">
        <ul className="timeline">
          {RELEASES.map((release) => (
            <ReleaseEntry release={release} key={release.ver} />
          ))}
        </ul>
      </Module>

      <Module index="02" title="Roadmap" meta="Planned">
        <p className="text">
          Where this is headed. Nothing below is live yet — it&rsquo;s the shortlist for the next
          iterations.
        </p>
        <Table corner="Item" head={["What it adds", "Status"]} rows={ROADMAP} />
      </Module>
    </>
  );
}
