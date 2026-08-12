// Methodology — the pipeline, the tiers, the formulas, and the missing-data rule.
//
// Same shape as every other route: content as data at the top, composition at
// the bottom, page furniture from components/Page.tsx.

import type { JSX, ReactNode } from "react";
import { Crumbs, Masthead, Module, Ribbon, Table } from "../components/Page";
import type { RibbonCell, SpecRow } from "../components/Page";

/** Shorthand for the monospaced inline-code span used throughout this page. */
function Expr({ children }: { children: ReactNode }): JSX.Element {
  return <span className="expr">{children}</span>;
}

const SPEC: SpecRow[] = [
  { k: "Tiers", v: "05" },
  { k: "Estimator", v: "Sample · n−1" },
  { k: "Missing", v: "Dropped" },
  { k: "Imputation", v: "None" },
];

const HEADLINE: RibbonCell[] = [
  { v: "4", k: "Pipeline stages" },
  { v: "5", k: "Analysis tiers" },
  { v: "8", k: "Base statistics" },
  { v: "0", k: "Values imputed" },
];

const PIPELINE: ReactNode[][] = [
  [
    "1 · Ingest",
    "Read the CSV into a dataframe.",
    'Missing file → a clean "dataset unavailable", never a crash.',
  ],
  [
    "2 · Clean",
    "Trim the frame, normalize blanks and null-like tokens.",
    <>
      Stray whitespace or <Expr>NA</Expr> masquerading as data.
    </>,
  ],
  [
    "3 · Coerce",
    "Cast each analyzed column to numbers; unreadable cells become missing.",
    "A single text cell silently poisoning a whole column.",
  ],
  [
    "4 · Analyse",
    "Run the requested tier and return the figures.",
    "Recomputation — identical requests are served from cache.",
  ],
];

const TIERS: ReactNode[][] = [
  [
    "basic",
    "1 numeric column",
    "Centre & spread: count, mean, median, mode, min, max, std, variance.",
  ],
  [
    "medium",
    "numeric + optional group",
    "Distribution shape, a confidence interval, and group comparisons — each test paired with an effect size.",
  ],
  [
    "advanced",
    "numeric + optional group",
    "Relationships — correlation and regression against other fields, plus covariate adjustment when you name the roles.",
  ],
  [
    "expert",
    "numeric + optional group",
    "Whether the models can be trusted — multicollinearity (VIF), residual diagnostics, published clinical thresholds, and trend tests.",
  ],
  ["categorical", "1 label column", "Counts, proportions and cross-tabs for each distinct label."],
];

const FORMULAS: ReactNode[][] = [
  ["count", "Values that survived coercion.", <Expr>n</Expr>],
  ["mean", "Arithmetic average; pulled by outliers.", <Expr>(Σ xᵢ) / n</Expr>],
  ["median", "Middle value once sorted; robust to outliers.", <Expr>50th percentile</Expr>],
  ["mode", "Most frequent value(s); every tie is returned.", <Expr>argmax freq(x)</Expr>],
  ["min / max", "Smallest and largest observed values.", <Expr>min x · max x</Expr>],
  ["variance", "Mean squared distance from the mean.", <Expr>Σ(xᵢ − mean)² / (n − 1)</Expr>],
  ["std", "Typical distance from the mean; same units as the data.", <Expr>√variance</Expr>],
];

export function Methodology(): JSX.Element {
  return (
    <>
      <Crumbs here="Methodology" />

      <Masthead
        eyebrow="Reference · statistical method"
        title="Methodology"
        tagline="Every figure the engine reports, and the rule that keeps it honest: a clean path from raw CSV to descriptive statistics, with nothing invented along the way."
        byline="By Anirudh Gupta"
        spec={SPEC}
        specLabel="Method specification"
      />

      <Ribbon cells={HEADLINE} />

      <Module index="01" title="The Pipeline" meta="Ingest → Report">
        <p className="text">
          A request walks through four stages. Each stage is pure: the same CSV always produces the
          same numbers, so a result can be cached and trusted.
        </p>
        <Table
          corner="Stage"
          head={["Does", "Guards against"]}
          rows={PIPELINE}
          caption="Stages, in order"
        />
      </Module>

      <Module index="02" title="The Five Tiers" meta="Depth on demand">
        <p className="text">
          One column, five depths of question. The numeric tiers build on each other; the
          categorical tier answers a different kind of question entirely.
        </p>
        <Table corner="Tier" head={["Input", "Answers"]} rows={TIERS} />
      </Module>

      <Module index="03" title="The Formulas" meta="8 figures">
        <p className="text">
          The base tier reports eight figures over the <Expr>n</Expr> values that survive coercion.
          Spread uses the <strong>sample</strong> estimator — dividing by <Expr>n − 1</Expr>, not{" "}
          <Expr>n</Expr> — because the data is a sample, not the whole population.
        </p>
        <Table corner="Statistic" head={["Meaning", "Formula"]} rows={FORMULAS} />
      </Module>

      <Module index="04" title="Missing Data" meta="Dropped, never invented">
        <p className="text">This is the rule the whole engine is built to protect.</p>
        <p className="prose">
          A cell that can&rsquo;t be read as a number — a blank, <Expr>NA</Expr>, <Expr>?</Expr>, or{" "}
          <Expr>null</Expr> — is <strong>dropped from that column&rsquo;s statistics</strong>, never
          replaced with a zero or an average. Filling a gap with a made-up number would quietly pull
          the mean, shrink the variance, and dress a hole up as a data point. So the engine refuses
          to.
        </p>
        <p className="prose">
          The visible cost is honest, and it is uneven. The live cohort is 699 adolescents, and the
          biomarkers they were selected on — <Expr>ALT</Expr>, <Expr>BMI</Expr>,{" "}
          <Expr>HbA1c</Expr>, <Expr>Triglycerides</Expr> — are complete for all 699. The
          questionnaire measures are not: <Expr>ScreenTime</Expr> is present for{" "}
          <strong>586</strong>, because 113 adolescents did not answer both screen-time questions,
          and <Expr>IncomeRatio</Expr> for <strong>627</strong>. Neither gap is filled in. The{" "}
          <Expr>count</Expr> is reported alongside every result precisely so that reduction is never
          hidden.
        </p>
        <p className="prose">
          That is also why screen time is <em>not</em> an entry criterion for the cohort. Requiring
          it would have cost 16% of the sample to serve the two analyses that use it, so it is a
          variable with its own smaller n instead — and the models that use it say so.
        </p>
      </Module>

      <Module index="05" title="Determinism & Caching" meta="Same in, same out">
        <p className="prose">
          The dataframe is immutable for the life of the process, and every tier is a pure function
          of <Expr>(tier, column, group)</Expr>. That means each answer is stable — so the engine
          memoises it. The first request for a figure computes it; every identical request after
          that is served straight from memory, no recomputation. The heavy one-time cost of the
          advanced tier&rsquo;s regression import is paid once, then never again.
        </p>
      </Module>
    </>
  );
}
