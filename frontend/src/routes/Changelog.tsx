// Changelog — release history and roadmap.
//
// Same shape as every other route: content as data at the top, composition at
// the bottom, page furniture from components/Page.tsx.

import type { JSX, ReactNode } from "react";
import { Crumbs, Masthead, Module, Table } from "../components/Page";
import type { SpecRow } from "../components/Page";

const SPEC: SpecRow[] = [
  { k: "Current", v: "v4.1.2" },
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
    ver: "v4.1.2",
    date: "22 Sep 2026",
    current: true,
    items: [
      <>
        <b>Definition cards, placed properly</b> — the hover card is now portalled onto the
        document body. It was <span className="expr">position: fixed</span> inside panels that
        run the page-load reveal, and an element with a transform animation in effect becomes
        the containing block for its fixed children, so every card rendered offset by wherever
        its panel sat. Only one card is ever open, Escape dismisses it, and it follows the word
        on scroll.
      </>,
    ],
  },
  {
    ver: "v4.1.1",
    date: "22 Sep 2026",
    items: [
      <>
        <b>Glossary, expanded</b> — 126 entries, up from 80: the statistical
        vocabulary a reader is most likely to stumble on (null hypothesis, power, false
        positives, multiplicity, confounding, heteroscedasticity, percentiles, eta squared,
        Cramér&rsquo;s V, Shapiro&ndash;Wilk, cross-validation, SHAP, overfitting) alongside the
        study&rsquo;s own terms. A test now fails the build if two entries claim the same label.
      </>,
    ],
  },
  {
    ver: "v4.1.0",
    date: "20 Sep 2026",
    items: [
      <>
        <b>Glossary</b> — every statistic label, column name and study term the site prints now
        has a plain-language definition. Labels the glossary knows carry a dotted underline and
        show their meaning on hover, focus or tap; the full list lives on the Docs page.
      </>,
      <>
        <b>Plain-words hints</b> — the Overview describes the tier and column you picked in one
        paragraph; the Study explains how to read a coefficient table once per step.
      </>,
      <>
        <b>Quick Answers</b> — a module on the Study page with the thirteen questions most likely
        to be asked, each answered in one breath with the numbers the engine reports.
      </>,
    ],
  },
  {
    ver: "v4.0.0",
    date: "20 Sep 2026",
    major: true,
    items: [
      <>
        <b>Observatory</b> — the interface rebuilt from scratch. Dark is native: a deep ink-blue
        ground under a faint star field, cool off-white text, one ice-cyan accent that means
        &ldquo;live&rdquo; or &ldquo;selected&rdquo; and nothing else. Warm colour is reserved for
        data that needs a second pole. A day theme is the alternate, switched from the strip and
        remembered.
      </>,
      <>
        <b>Type</b> — Young Serif for display, Sora for reading, Martian Mono for every number, all
        self-hosted and bundled (about 85 KB of latin woff2; no CDN).
      </>,
      <>
        <b>Layout</b> — one sticky instrument strip carries the brand, the numbered routes, the
        live readouts and the theme switch; the masthead is a full-bleed observatory panel with a
        seeded star-scatter; modules open with oversized serif numerals; tables are ruled ledgers;
        the tier picker is a segmented control; the boot splash is an aperture opening.
      </>,
      <>
        <b>Motion</b> — one staggered page-load reveal, line charts that draw themselves in, a sky
        that drifts once every ninety seconds; all CSS, all off under reduced motion.
      </>,
      <>
        <b>Exports</b> — the figure exporter now resolves hex, <span className="expr">color(srgb)</span>{" "}
        and <span className="expr">oklab()</span> paints, so dark-theme SVG/PNG/PDF downloads carry
        their real ground and the heatmap&rsquo;s mixed cells survive into PDF.
      </>,
    ],
  },
  {
    ver: "v3.3.0",
    date: "20 Sep 2026",
    major: true,
    items: [
      <>
        <b>The cohort now reproduces the revised protocol exactly</b> — 907 → 804 → 802 →{" "}
        <b>695</b>, with <b>314</b> (147 males, 167 females) in the fasting subsample. Three
        things changed: the day-1 recall reliability rule (<span className="expr">DR1DRSTZ = 1</span>)
        and the hepatitis B core antibody (<span className="expr">LBXHBC</span>) are applied as the
        protocol states; triglycerides come from the fasting file the protocol names (
        <span className="expr">LBXTR</span>), not the non-fasting panel; and elevated ALT is
        strictly <em>above</em> the NASPGHAN line, as the guideline reads.
      </>,
      <>
        <b>A zero is a zero</b> — the raw merge writes every 0 as{" "}
        <span className="expr">5.397605346934028e-79</span>, an artifact of pandas&rsquo;
        SAS-transport reader. The engine had been reading that as <em>missing</em> and blanking it,
        which deleted every &ldquo;less than 1 hour&rdquo; screen-time answer and left the cohort
        16% short of the protocol&rsquo;s n. Renamed <span className="expr">XPORT_ZERO</span> and
        mapped to 0.0 on the way in.
      </>,
      <>
        <b>Study</b> — Model A is also fitted on its full sample (n = 695) beside the shared-sample
        comparison; ΔR² reported for Model B both without and with BMI; a VIF check on the primary
        specification, against the pre-registered threshold of 5; sugar quartiles are the sample
        quartiles the protocol&rsquo;s &ldquo;four equal-sized groups&rdquo; describe, with the plain
        mean ± SE the protocol&rsquo;s figure plots.
      </>,
      <>
        <b>Figures</b> — two new: the sex-stratified coefficient plot and the composite risk-score
        bands. Both are in the Downloads bundle.
      </>,
      <>
        <b>Estimator and coding as written</b> — classical weighted-least-squares standard errors
        (the earlier cluster-robust ones widened intervals the protocol never asked for), and
        screen-time bands read exactly as the Variable Reference states. Every coefficient, R² and
        p-value in the Revised Results now falls out of the code to the last digit.
      </>,
      <>
        <b>Predict</b> — the LightGBM model retrained on the 314-adolescent primary sample.
      </>,
    ],
  },
  {
    ver: "v3.2.0",
    date: "30 Aug 2026",
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
