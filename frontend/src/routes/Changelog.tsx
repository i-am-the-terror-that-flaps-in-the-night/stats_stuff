// Changelog — release history and roadmap.
//
// Same shape as every other route: content as data at the top, composition at
// the bottom, page furniture from components/Page.tsx.

import type { JSX, ReactNode } from "react";
import { Crumbs, Masthead, Module, Table } from "../components/Page";
import type { SpecRow } from "../components/Page";

const SPEC: SpecRow[] = [
  { k: "Current", v: "v1.2.0" },
  { k: "Released", v: "2026·08·06" },
  { k: "Cadence", v: "Iterative" },
  { k: "Status", v: "Stable" },
];

interface Release {
  ver: string;
  date: string;
  current?: boolean;
  items: ReactNode[];
}

const RELEASES: Release[] = [
  {
    ver: "v1.2.0",
    date: "06 Aug 2026",
    current: true,
    items: [
      <>
        <b>Figures</b> — the dataset drawn, not just reported: a distribution, group box plots, a
        scatter with its fitted line, and a correlation matrix for all 105 numeric pairs. Inline
        SVG in TypeScript, no charting library. Hover any mark for its numbers, click a matrix
        cell to plot that pair, or switch any figure to its data table.
      </>,
      <>
        <b>Aggressive caching</b> — four layers: an hour of browser freshness with a day of
        stale-while-revalidate, <span className="expr">ETag</span> revalidation so an unchanged
        answer is a 304 rather than a payload, unbounded in-process memos, and a startup warm-up
        that computes the common answers before the first visitor asks.
      </>,
      <>
        <b>The Studio is a bench</b> — build a cohort out of row filters and watch the summary
        move, with a running count of how many people each filter leaves. Plus four experiments:
        how much a result depends on the number of people in the study, where a confidence
        interval actually comes from, how much a mean is a judgement call about outliers, and how
        false positives appear from nothing when you ask fifteen questions at once.
      </>,
      <>
        <b>No side-scrolling</b> — the nav wraps instead of hiding links off-screen, and the data
        tables fit a 320px viewport rather than swiping sideways.
      </>,
    ],
  },
  {
    ver: "v1.1.0",
    date: "05 Aug 2026",
    items: [
      <>
        <b>Honest statistics</b> — every p-value now ships with an effect size, results carry a{" "}
        <span className="expr">layer</span> (descriptive / inferential / predictive), and nothing is
        ever labelled causal. Confounder adjustment runs only when you name the roles yourself.
      </>,
      <>
        <b>Real clinical thresholds</b> — published guideline cutoffs with their sources, replacing
        the dataset median. Each carries its units, and a mismatched column is refused rather than
        scored against the wrong scale.
      </>,
      <>
        <b>React frontend</b> — the site is a React 19 + Vite + TypeScript 7 single-page app. The
        Studio moved from server-rendered Jinja to client routes over a JSON API.
      </>,
    ],
  },
  {
    ver: "v1.0.0",
    date: "09 Jul 2026",
    items: [
      <>
        <b>Expert tier</b> — the deepest numeric tier: multicollinearity (VIF), regression
        diagnostics, threshold counts, and trend tests, with its own full-RGB &ldquo;deep
        analysis&rdquo; treatment.
      </>,
      <>
        <b>Console redesign</b> — the &ldquo;terminal ledger&rdquo; theme, a staged boot sequence,
        and the multi-page site you&rsquo;re reading now.
      </>,
      <>
        <b>Studio</b> — an analysis browser and run log alongside the live dashboard.
      </>,
      <>
        <b>Consolidated backend</b> — one FastAPI process serves the API, the dashboard, and every
        page.
      </>,
    ],
  },
  {
    ver: "v0.9.0",
    date: "Jun 2026",
    items: [
      <>
        <b>Advanced tier</b> — correlation and regression, wired through statsmodels.
      </>,
      <>
        <b>Group-by</b> — the medium and advanced tiers can split a column across a category.
      </>,
    ],
  },
  {
    ver: "v0.8.0",
    date: "Jun 2026",
    items: [
      <>
        <b>Categorical tier</b> — counts and proportions for label columns.
      </>,
      <>
        <b>Dataset telemetry</b> — live shape, analyzable/categorical split, complete vs. reduced
        counts.
      </>,
    ],
  },
  {
    ver: "v0.5.0",
    date: "May 2026",
    items: [
      <>
        <b>Caching layer</b> — results memoised on{" "}
        <span className="expr">(tier, column, group)</span>; repeat questions are free.
      </>,
      <>
        <b>Overview endpoint</b> — dataset summary served without recomputation.
      </>,
    ],
  },
  {
    ver: "v0.3.0",
    date: "Apr 2026",
    items: [
      <>
        <b>HTTP API</b> — the engine wrapped in a FastAPI service with a JSON contract.
      </>,
      <>
        <b>Static dashboard</b> — the first browser front-end for picking a column and reading the
        result.
      </>,
    ],
  },
  {
    ver: "v0.1.0",
    date: "Mar 2026",
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
    "Result export",
    "Download any readout as CSV or JSON.",
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
