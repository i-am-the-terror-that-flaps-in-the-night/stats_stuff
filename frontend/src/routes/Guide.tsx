// Docs — what the engine will and won't claim, and where its data comes from.

import type { JSX } from "react";
import { Crumbs, Legend, Masthead, Module, Table } from "../components/Page";
import { useDatasets } from "../lib/hooks";
import { GLOSSARY } from "../lib/glossary";
import type { GlossaryEntry } from "../lib/glossary";

const LAYERS = [
  {
    term: "descriptive",
    def: "What this dataset looks like — mean, median, spread, counts.",
  },
  {
    term: "inferential",
    def: "What it suggests about the wider population, and how uncertain that is — p-values and confidence intervals, each paired with an effect size.",
  },
  {
    term: "predictive",
    def: "How well one column can be predicted from the others — regression, R².",
  },
  {
    term: "causal",
    tag: "never",
    def: "Requires a causal model the data cannot supply. Adjusted associations run only when you name the exposure and confounders yourself.",
  },
];

const GROUPS: { key: GlossaryEntry["group"]; title: string; meta: string }[] = [
  { key: "variables", title: "The Variables", meta: "What each column measures" },
  { key: "study", title: "The Study's Terms", meta: "Models, grades, cohort" },
  { key: "statistics", title: "Statistics", meta: "Every term the engine prints" },
];

function byTerm(a: GlossaryEntry, b: GlossaryEntry): number {
  return a.term.localeCompare(b.term, "en", { sensitivity: "base" });
}

export function Guide(): JSX.Element {
  const datasets = useDatasets();

  return (
    <>
      <Crumbs here="Docs" />

      <Masthead
        eyebrow="Reference"
        title="Docs"
        tagline="How the engine is wired, and what it will and won't claim."
        byline="By Anirudh Gupta"
        spec={[
          { k: "Glossary", v: String(GLOSSARY.length) },
          { k: "Layers", v: "03" },
          { k: "Causal", v: "Never" },
          { k: "Effect sizes", v: "Always" },
          { k: "Imputation", v: "None" },
        ]}
        specLabel="Claim policy"
      />

      <Module index="01" title="Claim Layers" meta="How strong a claim">
        <p className="text">
          Every block the engine returns carries a <span className="expr">layer</span> saying how
          strong a claim it supports. Nothing is ever labelled causal.
        </p>
        <Legend rows={LAYERS} />
      </Module>

      <Module index="02" title="Significance" meta="Two different questions">
        <p className="prose">
          A p-value is the probability of a result at least this extreme <em>if</em> the null
          hypothesis and the test&rsquo;s assumptions both hold. It is not the probability that the
          pattern arose by chance, and 1 − p is not the probability that the hypothesis is correct.
        </p>
        <p className="prose">
          &ldquo;Statistically significant&rdquo; and &ldquo;big enough to matter&rdquo; are also
          different questions. At NHANES sample sizes a difference far too small to notice in a
          clinic clears p &lt; 0.05 easily, so every test reports an effect size beside its p-value.
        </p>
      </Module>

      {GROUPS.map((group, i) => (
        <Module
          key={group.key}
          index={String(i + 3).padStart(2, "0")}
          title={group.title}
          meta={group.meta}
        >
          {i === 0 && (
            <p className="text">
              Every dotted-underlined label on the site opens one of these definitions in place.
              This is the same list, in full, for reading through before a presentation.
            </p>
          )}
          <Legend
            plain
            rows={GLOSSARY.filter((e) => e.group === group.key)
              .sort(byTerm)
              .map((e) => ({ term: e.term, ...(e.unit ? { tag: e.unit } : {}), def: e.def }))}
          />
        </Module>
      ))}

      <Module index="06" title="Datasets" meta="Availability is live">
        <Table
          corner="File"
          head={["Status", "What it is"]}
          rows={datasets.map((d) => [d.label, d.available ? "available" : "local only", d.blurb])}
        />
      </Module>
    </>
  );
}
