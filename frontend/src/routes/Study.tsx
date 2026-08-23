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
import { useStudyIndex, useStudyStep } from "../lib/hooks";
import type { ClaimGrade, Coefficient, StudyModel, StudyStep } from "../types/engine";

const SPEC: SpecRow[] = [
  { k: "Cohort", v: "NHANES 17–18" },
  { k: "Estimator", v: "WLS · robust" },
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

/** One model's coefficient table: estimate, robust interval, beta, p. */
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
        head={["Estimate", "95% CI (robust)", "β", "p"]}
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

      <Module index="03" title="How To Read This" meta="Claims & limits">
        <p className="prose">
          Every estimate is weighted by the NHANES day-1 dietary weight, so it describes U.S.
          adolescents rather than the people who happened to be recruited, and every standard error
          is cluster-robust by primary sampling unit within stratum, so the clustered design does
          not make the results look more precise than they are. There are 30 such clusters, which is
          enough for the correction to be worth making and few enough that the p-values are
          approximate.
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
