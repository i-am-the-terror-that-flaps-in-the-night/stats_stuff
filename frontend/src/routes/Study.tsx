// Study — the project's actual research, served from Backend/engine.py (part three).
//
// Every other route on this site is a tool: pick a column, get statistics. This
// one is the finding. It renders the pre-specified ten-step analysis in protocol
// order, with each step's claim grade visible, because the ordering is the point
// — a null primary result that gets quietly replaced by whichever subgroup
// cleared p < 0.05 is the failure mode the hierarchy exists to prevent.
//
// The contents list and the headline load on mount; a step's models are fetched
// when the reader opens it. One step carries every coefficient of every model in
// it, so pulling all ten up front would move a lot of bytes nobody asked for.

import type { JSX, ReactNode } from "react";
import { useState } from "react";
import { Crumbs, Masthead, Module, Ribbon, Status, Table } from "../components/Page";
import type { RibbonCell, SpecRow } from "../components/Page";
import { Hint, Term } from "../components/Term";
import { useStudyIndex, useStudyStep } from "../lib/hooks";
import type { ClaimGrade, Coefficient, StudyModel, StudyStep } from "../types/engine";

const SPEC: SpecRow[] = [
  { k: "Cohort", v: "NHANES 17–18" },
  { k: "Estimator", v: "WLS · classical" },
  { k: "Steps", v: "10" },
  { k: "Imputation", v: "None" },
];

/** Shorthand for the monospaced inline-code span used across the site. */
function Expr({ children }: { children: ReactNode }): JSX.Element {
  return <span className="expr">{children}</span>;
}

/** A claim-grade badge. The grade is the reason the step is worth its position. */
function Grade({ grade }: { grade: ClaimGrade }): JSX.Element {
  return <span className={`grade grade-${grade}`}>{grade}</span>;
}

/** Format a p-value, preferring the server's text form where it has one.
 *
 * The server sends "< 0.0001" for anything that would round to a flat 0. A
 * displayed "p = 0" reads as certainty, which is the one claim a p-value never
 * makes, so the text form wins whenever it is present. */
function pValue(sig: { p_value: number | null; p_value_text?: string }): string {
  if (sig.p_value_text) return sig.p_value_text;
  return sig.p_value === null ? "—" : String(sig.p_value);
}

function num(value: number | null | undefined, digits = 3): string {
  return value === null || value === undefined ? "—" : value.toFixed(digits);
}

/** One model's coefficient table: estimate, interval, beta, p. */
function ModelTable({ model }: { model: StudyModel }): JSX.Element {
  const rows: ReactNode[][] = Object.entries(model.coefficients)
    // The intercept is a fitted number, not a finding -- it is the predicted
    // outcome when every predictor is zero, which describes a 0-year-old with a
    // BMI of 0. Kept out of the table rather than inviting it to be read.
    .filter(([name]) => name !== "const")
    .map(([name, c]: [string, Coefficient]) => [
      name,
      num(c.estimate, 5),
      `${num(c.ci_low, 4)} … ${num(c.ci_high, 4)}`,
      num(c.standardized_beta, 3),
      pValue(c.significance),
    ]);

  return (
    <>
      <Table
        corner="Predictor"
        head={["Estimate", "95% CI", "Beta", "p"]}
        rows={rows}
        numeric={[1, 2, 3, 4]}
        caption={`${model.label || model.outcome} · n = ${model.n} · R² = ${num(model.r_squared, 4)} · ${model.clusters} clusters`}
      />
      <p className="footnote">{model.estimator}</p>
    </>
  );
}

/** Pull a model out of a step's loosely-typed extra fields. */
function modelAt(step: StudyStep, key: string): StudyModel | null {
  const value = step[key];
  return value && typeof value === "object" && "coefficients" in value
    ? (value as StudyModel)
    : null;
}

/**
 * Render whatever a step actually contains.
 *
 * Steps differ in shape — one holds two models and a decomposition, another a
 * quartile table, another a set of score bands. Rather than a renderer per step
 * (ten components that drift apart), this walks the keys it knows how to draw
 * and shows the step's own prose for the rest. A new field added server-side
 * therefore appears as prose instead of vanishing or breaking the build.
 */
function StepBody({ step }: { step: StudyStep }): JSX.Element {
  const models = [
    "model",
    "total_model",
    "direct_model",
    "lifestyle_model",
    "combined_model",
  ]
    .map((key) => [key, modelAt(step, key)] as const)
    .filter((pair): pair is readonly [string, StudyModel] => pair[1] !== null);

  const quartiles = Array.isArray(step.quartiles) ? step.quartiles : null;
  const bands = Array.isArray(step.bands) ? step.bands : null;
  const attrition = Array.isArray(step.attrition) ? step.attrition : null;
  const variables = Array.isArray(step.variables) ? step.variables : null;

  return (
    <div className="step-body">
      <p className="text">{step.question}</p>

      {attrition && (
        <Table
          corner="Step"
          head={["Rule", "Remaining", "Removed"]}
          rows={attrition.map((row: Record<string, unknown>) => [
            String(row.step),
            String(row.rule),
            String(row.n),
            row.removed === null ? "—" : String(row.removed),
          ])}
          numeric={[2, 3]}
          caption="Every rule that decided who is in the study"
        />
      )}

      {variables && (
        <Table
          corner="Variable"
          head={["Unit", "n", "Weighted mean", "SD", "Median"]}
          rows={variables.map((row: Record<string, unknown>) => [
            String(row.variable),
            String(row.unit),
            String(row.n),
            String(row.weighted_mean),
            String(row.weighted_sd),
            String(row.weighted_median),
          ])}
          numeric={[2, 3, 4, 5]}
          caption="Weighted to U.S. adolescents aged 12–17"
        />
      )}

      {quartiles && (
        <Table
          corner="Quartile"
          head={["n", "Mean sugar (g)", "Mean ALT (U/L)", "SE", "% elevated"]}
          rows={quartiles.map((row: Record<string, unknown>) => [
            `Q${String(row.quartile)}`,
            String(row.n),
            String(row.weighted_mean_sugar_g),
            String(row.weighted_mean_alt),
            `± ${String(row.standard_error_alt)}`,
            String(row.percent_elevated_alt),
          ])}
          numeric={[1, 2, 3, 4, 5]}
          caption="Weighted means within each quartile of daily sugar"
        />
      )}

      {bands && (
        <Table
          corner="Score"
          head={["n", "Mean ALT (U/L)", "% elevated"]}
          rows={bands.map((row: Record<string, unknown>) => [
            String(row.score),
            String(row.n),
            String(row.weighted_mean_alt),
            String(row.percent_elevated_alt),
          ])}
          numeric={[1, 2, 3]}
          caption="Mean ALT and elevated-ALT prevalence by composite risk score"
        />
      )}

      {models.length > 0 && (
        <Hint title="Reading the tables">
          <p>
            Each row is one predictor. <b>Estimate</b> is how much ln(ALT) changes per one unit
            of that predictor with everything else held fixed — multiply by 100 for roughly the
            % change in ALT. <b>95% CI</b> is the range of estimates the data allow; if it spans
            zero, that predictor cannot be told apart from no effect. <b>Beta</b> (standardized
            β) puts every predictor on the same scale so you can see which matters most.{" "}
            <b>p</b> below 0.05 counts as significant. R² under each table is the share of ALT
            variation the whole model explains.
          </p>
        </Hint>
      )}

      {models.map(([key, model]) => (
        <ModelTable key={key} model={model} />
      ))}

      {typeof step.interpretation === "string" && (
        <p className="prose">{step.interpretation}</p>
      )}
      {typeof step.note === "string" && <p className="footnote">{step.note}</p>}
      {typeof step.caveat === "string" && <p className="footnote">{step.caveat}</p>}
      {typeof step.multiplicity === "string" && (
        <p className="footnote">{step.multiplicity}</p>
      )}
      {typeof step.not_causal === "string" && <p className="footnote">{step.not_causal}</p>}
    </div>
  );
}


/**
 * The answers most likely to be needed under questioning, written to be said
 * aloud. Every number here is one the engine computes -- they are restated
 * rather than fetched so this list still reads when the backend is asleep.
 * Keep in step with Backend/study.py and the Revised Results 6.1.26 doc.
 */
const QUICK_ANSWERS: { q: string; a: ReactNode }[] = [
  {
    q: "What was the question?",
    a: "Does the sugar an adolescent eats predict their liver-enzyme level (ALT), once you account for body mass and the metabolic markers that sit between diet and the liver?",
  },
  {
    q: "What is ALT and why does it matter?",
    a: (
      <>
        <Term>ALT</Term> is an enzyme that leaks from stressed liver cells into the blood. It is
        the standard early marker of fatty-liver disease, which is now the commonest liver
        disease in children. About 10.5% of U.S. adolescents are above the pediatric cutoff
        (&gt; 26 U/L boys, &gt; 22 U/L girls).
      </>
    ),
  },
  {
    q: "Where did the data come from?",
    a: (
      <>
        <Term>NHANES</Term> 2017–2018, the CDC survey that examines and draws blood from a
        representative sample of Americans. I did not collect data; this is a secondary analysis.
        Starting from 9,254 participants: 907 were aged 12–17, 804 had a reliable diet recall,
        802 had no hepatitis B or C, and 695 had every lifestyle variable. Triglycerides need
        fasting blood, so the full model has 314 (147 boys, 167 girls).
      </>
    ),
  },
  {
    q: "What did you find?",
    a: (
      <>
        Sugar does <em>not</em> independently predict ALT: in the pre-specified model with BMI,
        its p-value is 0.30 and its β is 0.05. What does predict ALT is <Term>BMI</Term> (β 0.42,
        p &lt; 0.001), being male (β 0.31, p &lt; 0.001) and the <Term>Trig/HDL ratio</Term> (β
        0.13, p = 0.016). The model explains about 30% of the variation in ALT (R² = 0.30).
      </>
    ),
  },
  {
    q: "Why is a null result worth presenting?",
    a: "Because it was the pre-registered primary test, and because it changes the message: telling adolescents to cut sugar, on its own, is unlikely to move liver stress. Weight and lipid dysregulation are where the signal is. A well-run null is a result; a subgroup fished out after the fact is not.",
  },
  {
    q: "What does the dose-response step show?",
    a: "Splitting the 695 by sugar quartile, mean ALT is 15.9, 15.9, 15.7 and 16.7 U/L — flat. The trend test gives p = 0.11, ANOVA p = 0.86, and the share with elevated ALT does not differ across quartiles (p = 0.28). A real sugar effect would leave a gradient; there is none.",
  },
  {
    q: "What is Model A versus Model B?",
    a: (
      <>
        <Term>Model A</Term> is lifestyle only: sugar, screen time, age, sex. <Term>Model B</Term>{" "}
        adds the Trig/HDL ratio and HbA1c, then BMI. R² goes 0.09 → 0.16 → 0.30 on the same 314
        people, so the metabolic markers and body mass carry most of the explanatory power.
      </>
    ),
  },
  {
    q: "What is a p-value, in one sentence?",
    a: "How surprising the result would be if there were truly no effect — small means hard to explain by chance, and 0.05 is the conventional line. It is not the probability the finding is true, and it says nothing about how big the effect is; that is what β is for.",
  },
  {
    q: "Why log ALT? Why weights?",
    a: "ALT is heavily right-skewed (skewness 4.4) — most adolescents are low with a long tail of high values — so I model its natural log, which brings skewness to 1.0 and makes coefficients read as percent changes. NHANES weights (WTDRD1) make every estimate describe U.S. adolescents rather than the people who happened to be sampled.",
  },
  {
    q: "What about boys versus girls?",
    a: "Boys average 18.9 U/L, girls 13.6. Fitting the model separately, the Trig/HDL slope is stronger in boys (interaction p = 0.04) while the sugar slope does not differ (p = 0.39). This is exploratory — two tests, uncorrected — so it is a lead, not a finding.",
  },
  {
    q: "What is the risk score?",
    a: "0–6 points: one for each of sugar, screen time, Trig/HDL, HbA1c and BMI above the cohort median, plus one for male sex. Mean ALT rises about 13.7% (≈ 2.5 U/L) per point and the share with elevated ALT climbs with it (Cochran–Armitage p < 0.001). It is relative — cut at this sample's medians — so it would need validating in a new sample before anyone screened with it.",
  },
  {
    q: "What are the limitations?",
    a: "Cross-sectional, so association not causation. Diet is one self-reported day. Standard errors are the classical WLS ones the protocol specifies, not cluster-adjusted for NHANES' design, so p-values near 0.05 are approximate. Triglycerides exist for only 314 of 695. And the risk score is exploratory.",
  },
  {
    q: "Is this causal?",
    a: "No. Everything was measured at one visit. The study shows what goes together in U.S. adolescents; it cannot show that changing sugar, or BMI, would change ALT.",
  },
];

export function Study(): JSX.Element {
  const { index, headline, error, loading } = useStudyIndex();
  const [open, setOpen] = useState<string | null>(null);
  const { step, loading: stepLoading } = useStudyStep(open);

  const cells: RibbonCell[] = [
    { v: headline ? String(headline.n) : "—", k: "Adolescents" },
    { v: headline ? pValue({ p_value: headline.sugar_p }) : "—", k: "Sugar · p (adj. BMI)" },
    { v: headline ? num(headline.trig_hdl_beta, 3) : "—", k: "Trig/HDL · β" },
    {
      v: headline ? <>{num(headline.elevated_alt_percent, 1)}<small> %</small></> : "—",
      k: "Elevated ALT",
    },
  ];

  return (
    <>
      <Crumbs here="Study" />

      <Masthead
        eyebrow="Original research · secondary data analysis"
        title="Sugar, Sex and Liver Stress"
        tagline="Dietary sugar does not independently predict liver-enzyme levels in U.S. adolescents once body mass is accounted for. Sex and the triglyceride/HDL ratio do."
        byline="By Anirudh Gupta"
        spec={SPEC}
        specLabel="Study specification"
      />

      <Ribbon cells={cells} />

      <Module index="01" title="The Finding" meta="Primary result">
        {error && <Status message={error} isError />}
        {loading && !error && <Status message="Loading the study…" />}
        {headline && (
          <>
            <p className="text">{headline.primary_finding}</p>
            <p className="prose">
              Across {headline.n} adolescents aged 12–17 in NHANES 2017–2018, daily dietary sugar
              carries no detectable independent association with blood ALT once BMI is in the model
              (<Expr>p = {pValue({ p_value: headline.sugar_p })}</Expr>). The downstream lipid
              marker does: the triglyceride/HDL ratio has a standardized β of{" "}
              <Expr>{num(headline.trig_hdl_beta, 3)}</Expr> (
              <Expr>p = {pValue({ p_value: headline.trig_hdl_p })}</Expr>). Boys average{" "}
              <strong>{num(headline.sex_difference_in_alt.male, 1)} U/L</strong> against{" "}
              <strong>{num(headline.sex_difference_in_alt.female, 1)} U/L</strong> in girls.
            </p>
            <p className="prose">
              A null primary result is a result. It says that public-health messaging aimed only at
              sugar, without addressing weight and lipid dysregulation, is unlikely to move
              adolescent liver stress — and the dose-response step below shows no gradient across
              sugar quartiles either, which is the pattern a real effect would leave behind.
            </p>
            <p className="footnote">{headline.not_causal}</p>
          </>
        )}
      </Module>

      <Module index="02" title="The Ten Steps" meta="Protocol order">
        <p className="text">
          The analysis was specified before the data were looked at, and each step is tagged with
          the grade of claim it can support. Open one to see its models. Two steps are{" "}
          <Grade grade="primary" />: those are the hypothesis the study was built to test.
        </p>

        {index && (
          <ul className="step-list" role="list">
            {index.steps.map((entry) => {
              const isOpen = open === entry.name;
              return (
                <li key={entry.name} className={`step${isOpen ? " is-open" : ""}`}>
                  <button
                    type="button"
                    className="step-head"
                    aria-expanded={isOpen}
                    onClick={() => setOpen(isOpen ? null : entry.name)}
                  >
                    <span className="step-index">
                      {entry.step === null ? "S" : String(entry.step).padStart(2, "0")}
                    </span>
                    <span className="step-title">{entry.title}</span>
                    <Grade grade={entry.grade} />
                    <span className="step-n">{entry.n === null ? "" : `n = ${entry.n}`}</span>
                  </button>
                  {isOpen && (
                    <div className="step-panel">
                      {stepLoading && <Status message="Fitting…" />}
                      {step && !stepLoading && <StepBody step={step} />}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Module>

      <Module index="03" title="Quick Answers" meta="If you blank">
        <p className="text">
          The facts a question is most likely to be about, each in one breath. Numbers come from
          the engine above, so they match the written results.
        </p>
        <dl className="qa">
          {QUICK_ANSWERS.map((row) => (
            <div className="qa-row" key={row.q}>
              <dt className="qa-q">{row.q}</dt>
              <dd className="qa-a">{row.a}</dd>
            </div>
          ))}
        </dl>
      </Module>

      <Module index="04" title="How To Read This" meta="Claims & limits">
        <p className="prose">
          Every estimate is weighted by the NHANES day-1 dietary weight, so it describes U.S.
          adolescents rather than the people who happened to be recruited. Standard errors are the
          classical weighted-least-squares ones the protocol specifies, which is how the written
          results were computed. They do not correct for the clustered sampling design (30 primary
          sampling units within strata here, counted beside each model), so p-values near the 0.05
          line are suggestive rather than exact.
        </p>
        <p className="prose">
          Nothing here is causal. The data are cross-sectional — diet, blood and body measurements
          come from essentially one visit — so the mediation step decomposes an{" "}
          <em>association</em> into two associations, and is labelled that way. The composite risk
          score is exploratory and relative: five of its six components are cut at this cohort&rsquo;s
          own median, so it ranks these adolescents against each other and would need validation
          in a separate sample before it meant anything as a screening tool.
        </p>
      </Module>
    </>
  );
}
