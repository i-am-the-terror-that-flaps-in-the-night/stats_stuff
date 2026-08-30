// Predict — the part of this site a judge can touch.
//
// Everything else here reports a finished analysis. This page hands the reader
// seven sliders, runs the study's own specification through a gradient boosting
// model, and shows exactly how the answer was assembled: a predicted ALT, a
// decomposition into per-input SHAP contributions, and — separately — a
// paragraph of plain English from a language model.
//
// THE ORDER OF OPERATIONS IS THE DESIGN
//   The prediction and its chart render first, from /api/predict, which touches
//   nothing outside this server and answers in about a millisecond. Only then
//   does the page ask /api/predict/explain for prose, and it does so in a way
//   that cannot hold anything up: the explanation panel has its own loading
//   state and its own failure state, and neither can empty the page above it.
//
//   That is not a nicety. The prediction is the science and the paragraph is the
//   caption, so bad venue wifi, a rate limit or an unset API key has to degrade
//   this to "still fully working, minus the prose" — never to a spinner in front
//   of a judge. The server's own three-step failover means the panel almost
//   always fills anyway; when it falls back, the page says so rather than
//   passing canned text off as a model's.
//
// THE FORM IS BUILT FROM THE SERVER'S MODEL CARD
//   Not from seven hard-coded sliders. Ranges, steps, defaults and the copy under
//   each control all come from /api/predict/model, which derives them from the
//   cohort at training time. So a retrain that shifts a range shifts the control
//   with it, and the page can never offer a value the model was not fitted on.
//
// EVERY ANSWER IS DEBOUNCED, NOT DEFERRED
//   Dragging a slider fires a request per frame otherwise. The prediction is
//   cheap enough to re-run on a short debounce (it feels live), the explanation
//   is not, so prose is requested only when the reader stops moving — and is
//   cleared the moment they start again, because a paragraph describing the
//   previous position is worse than none.

import type { JSX } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Crumbs, Legend, Masthead, Module, Ribbon, Status, Table } from "../components/Page";
import type { RibbonCell, SpecRow } from "../components/Page";
import { Figure } from "../components/figures/ChartFrame";
import {
  ContributionChart,
  ContributionLegend,
} from "../components/figures/ContributionChart";
import { ask, explain, predict } from "../lib/api";
import { usePredictor } from "../lib/hooks";
import type {
  AskTurn,
  ExplainAttempt,
  ExplainResponse,
  PredictBody,
  PredictionResponse,
  PredictorCard,
  PredictorInput,
  SuggestedQuestions,
} from "../types/engine";

// Long enough that a drag does not fire a request per frame, short enough that
// releasing the handle feels like the number was already there.
const PREDICT_DEBOUNCE_MS = 120;
// Longer, because this one may reach a language model. It runs only after the
// reader has actually stopped.
const EXPLAIN_DEBOUNCE_MS = 700;

const SPEC: SpecRow[] = [
  { k: "Model", v: "LightGBM" },
  { k: "Explainer", v: "TreeSHAP" },
  { k: "Cohort", v: "NHANES 17–18" },
  { k: "Outcome", v: "ln(ALT)" },
];

function num(value: number | null | undefined, digits = 3): string {
  return value === null || value === undefined ? "—" : value.toFixed(digits);
}

/** One control. A choice renders as buttons; everything else as a slider. */
function Control({
  spec,
  value,
  onChange,
}: {
  spec: PredictorInput;
  value: number;
  onChange: (next: number) => void;
}): JSX.Element {
  const id = `input-${spec.name}`;
  // The control moves in the model's units and reads out in the reader's. Only
  // sugar differs between the two (see PredictorInput.display_factor), and the
  // conversion is display-only -- `value` is what gets posted.
  const factor = spec.display_factor ?? 1;
  const shown = Number((value * factor).toFixed(2));

  return (
    <div className="predict-field">
      <label className="predict-label" htmlFor={id}>
        {spec.label}
        <span className="predict-unit">{spec.display_unit ?? spec.unit}</span>
      </label>

      {spec.choices ? (
        <div className="predict-choices" role="group" aria-labelledby={id}>
          {spec.choices.map((choice) => (
            <button
              key={choice.value}
              type="button"
              className={`predict-choice${value === choice.value ? " is-active" : ""}`}
              aria-pressed={value === choice.value}
              onClick={() => onChange(choice.value)}
            >
              {choice.label}
            </button>
          ))}
        </div>
      ) : (
        <div className="predict-slider">
          <input
            id={id}
            type="range"
            min={spec.min}
            max={spec.max}
            step={spec.step}
            value={value}
            onChange={(event) => onChange(Number(event.target.value))}
          />
          <output className="predict-value" htmlFor={id}>
            {shown}
          </output>
        </div>
      )}

      <p className="predict-about">
        {spec.about}{" "}
        <span className="predict-median">
          Cohort median {Number((spec.cohort_median * factor).toFixed(2))}
          {spec.display_unit ? ` ${spec.display_unit}` : ""}.
        </span>
      </p>
    </div>
  );
}

/**
 * The explanation panel.
 *
 * Three states, all of them legible: waiting, a model's paragraph, or the
 * server's generated fallback. The fallback is labelled as one — an
 * unattributed paragraph would be the page's only dishonest pixel, and the
 * difference is exactly what a judge asking "did the AI write this?" is owed.
 */
function Explanation({
  answer,
  loading,
  llmConfigured,
}: {
  answer: ExplainResponse | null;
  loading: boolean;
  llmConfigured: boolean | null;
}): JSX.Element {
  if (loading) {
    return (
      <div className="predict-prose is-waiting">
        <p className="text">Asking the language model to describe the breakdown…</p>
        <p className="footnote">
          The prediction and the chart above are already final. This paragraph is
          the only thing still loading, and nothing above it depends on it.
        </p>
      </div>
    );
  }

  if (!answer) {
    return (
      <div className="predict-prose">
        <p className="text">Move a control to get an explanation.</p>
      </div>
    );
  }

  const fromModel = answer.source === "llm";
  return (
    <div className="predict-prose">
      <p className="text predict-explanation">{answer.explanation}</p>
      <p className="footnote">
        {fromModel ? (
          <>
            Written by <b>{answer.model}</b> via OpenRouter
            {answer.attempts.length > 1 && " (the faster model did not answer in time)"}.{" "}
            {answer.disclaimer}
          </>
        ) : (
          <>
            <b>Written by this server, not by a language model.</b>{" "}
            {llmConfigured === false
              ? "No API key is configured on this deployment, so the demo is running on its offline fallback: "
              : "The language model did not answer, so the demo fell back to its own text: "}
            a sentence assembled from the same contributions the model would have
            been given. The numbers are unaffected — they never came from a
            language model in the first place.
          </>
        )}
      </p>
      {!fromModel && answer.attempts.length > 0 && (
        <p className="footnote predict-attempts">
          {answer.attempts.map((a) => `${a.model}: ${a.failure ?? "no answer"}`).join(" · ")}
        </p>
      )}
    </div>
  );
}

/**
 * The follow-up conversation.
 *
 * WHAT THIS IS CAREFUL ABOUT
 *   A visitor at a poster does not know what to ask a model, so the starter
 *   questions come from the server — where they sit beside the prompt that has
 *   to handle them. One of them ("Is this adolescent at risk?") is chosen
 *   because the right answer is a refusal, and a judge seeing that refusal
 *   learns more about the project than a fluent answer would teach them.
 *
 *   A fallback answer here is NOT an answer. Unlike the caption's, which the
 *   server can generate from the SHAP contributions, an unanswerable question
 *   comes back as "the model is unavailable" — so this labels it as the
 *   non-answer it is rather than styling it like the real ones.
 *
 *   The transcript is cleared whenever the inputs move, in `Predict` below. An
 *   answer about the previous adolescent sitting under a new chart is the one
 *   way this feature could mislead somebody, and it is the obvious way to build
 *   it if nobody thinks about it.
 */
function Conversation({
  turns,
  pending,
  prompts,
  llmConfigured,
  lastAttempts,
  onAsk,
}: {
  turns: AskTurn[];
  pending: string | null;
  prompts: SuggestedQuestions | null;
  llmConfigured: boolean | null;
  lastAttempts: ExplainAttempt[];
  onAsk: (question: string) => void;
}): JSX.Element {
  const [draft, setDraft] = useState("");
  const limit = prompts?.max_chars ?? 400;

  function submit(question: string): void {
    const trimmed = question.trim();
    if (!trimmed || pending) return;
    setDraft("");
    onAsk(trimmed);
  }

  return (
    <div className="ask">
      {turns.length === 0 && !pending && (
        <p className="text ask-intro">
          Ask about this prediction — why one input mattered more than another,
          what the model does not know, how far to trust it.
          {llmConfigured === false && (
            <>
              {" "}
              <b>No language model is configured on this deployment</b>, so a
              question will come back saying so rather than being answered.
            </>
          )}
        </p>
      )}

      {(turns.length > 0 || pending) && (
        <ol className="ask-thread">
          {turns.map((turn, index) => (
            <li
              // Index is a safe key here and only here: the thread is
              // append-only and is thrown away wholesale when the inputs move,
              // so no entry is ever reordered or removed in place.
              key={index}
              className={turn.role === "user" ? "ask-turn is-you" : "ask-turn is-model"}
            >
              <span className="ask-who">{turn.role === "user" ? "You" : "Model"}</span>
              <p className="ask-text">{turn.content}</p>
            </li>
          ))}
          {pending && (
            <>
              <li className="ask-turn is-you">
                <span className="ask-who">You</span>
                <p className="ask-text">{pending}</p>
              </li>
              <li className="ask-turn is-model is-waiting">
                <span className="ask-who">Model</span>
                <p className="ask-text">Thinking…</p>
              </li>
            </>
          )}
        </ol>
      )}

      {prompts && prompts.questions.length > 0 && (
        <div className="ask-suggestions">
          {prompts.questions.map((question) => (
            <button
              key={question}
              type="button"
              className="ask-suggestion"
              disabled={pending !== null}
              onClick={() => submit(question)}
            >
              {question}
            </button>
          ))}
        </div>
      )}

      <form
        className="ask-form"
        onSubmit={(event) => {
          event.preventDefault();
          submit(draft);
        }}
      >
        <input
          className="ask-input"
          type="text"
          value={draft}
          maxLength={limit}
          placeholder="Ask a follow-up about this prediction…"
          aria-label="Ask a follow-up question about this prediction"
          disabled={pending !== null}
          onChange={(event) => setDraft(event.target.value)}
        />
        <button
          type="submit"
          className="ask-send"
          disabled={pending !== null || draft.trim().length === 0}
        >
          Ask
        </button>
      </form>

      {lastAttempts.length > 0 && (
        <p className="footnote predict-attempts">
          {lastAttempts.map((a) => `${a.model}: ${a.failure ?? "no answer"}`).join(" · ")}
        </p>
      )}

      <p className="footnote">
        The model is given this prediction, its SHAP breakdown and the study's
        results, and nothing else — it cannot run the model again or look
        anything up. It has no access to the numbers above and cannot change
        them. It will not give medical advice or assess a real person.
      </p>
    </div>
  );
}

/** The model card's own disclosures, rendered as a table rather than prose. */
function ModelCard({ card }: { card: PredictorCard }): JSX.Element {
  const scores = card.validation;
  return (
    <>
      <Table
        corner="Estimator"
        head={["Out-of-fold R² on ln(ALT)", "Mean absolute error"]}
        rows={[
          [
            "Gradient boosting (this page)",
            num(scores.gradient_boosting.r_squared_log_alt, 4),
            `${num(scores.gradient_boosting.mean_absolute_error_u_per_l, 2)} U/L`,
          ],
          [
            "The study's linear Model B",
            num(scores.linear_model_b_with_bmi.r_squared_log_alt, 4),
            `${num(scores.linear_model_b_with_bmi.mean_absolute_error_u_per_l, 2)} U/L`,
          ],
        ]}
        numeric={[1, 2]}
        caption={`${scores.folds} folds · n = ${card.n} · ${scores.clusters} sampling clusters · ${card.rounds} boosting rounds`}
      />
      <p className="footnote">{scores.note}</p>

      <Table
        corner="Input"
        head={["Mean |SHAP|", "Share of split gain"]}
        rows={card.importance.map((row) => [
          row.label,
          num(row.mean_abs_shap, 5),
          row.gain_percent === null ? "—" : `${row.gain_percent.toFixed(1)}%`,
        ])}
        numeric={[1, 2]}
        caption="How much each input moves a prediction on average, and how much the model leaned on it while fitting."
      />
    </>
  );
}

export function Predict(): JSX.Element {
  const { card, llm, prompts, error, loading } = usePredictor();

  const [values, setValues] = useState<Record<string, number> | null>(null);
  const [prediction, setPrediction] = useState<PredictionResponse | null>(null);
  const [answer, setAnswer] = useState<ExplainResponse | null>(null);
  const [explaining, setExplaining] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  // The follow-up conversation. Held here rather than in Conversation so that
  // the effect below can clear it: this service keeps no session, so the
  // transcript lives in the browser and is sent back with each question.
  const [turns, setTurns] = useState<AskTurn[]>([]);
  const [pending, setPending] = useState<string | null>(null);
  const [askAttempts, setAskAttempts] = useState<ExplainAttempt[]>([]);

  // The request in flight, so a slower earlier answer cannot overwrite a newer
  // one. Debouncing narrows that window; it does not close it.
  const generation = useRef(0);

  // Seed the form from the card's defaults once it arrives.
  useEffect(() => {
    if (!card || values) return;
    const seeded: Record<string, number> = {};
    for (const [name, spec] of Object.entries(card.inputs)) seeded[name] = spec.default;
    setValues(seeded);
  }, [card, values]);

  // The prediction. Re-run on every change, debounced just enough to survive a
  // drag; this is local arithmetic on a committed model, so it is meant to feel
  // instantaneous rather than to be rationed.
  useEffect(() => {
    if (!values) return;
    const mine = ++generation.current;
    // Clear the prose immediately: a paragraph describing the position the
    // reader has just moved away from is worse than an empty panel.
    setAnswer(null);
    // And the conversation with it. An answer about the previous adolescent
    // sitting under a new chart is the one way this page could actively
    // mislead somebody -- the words would still be fluent and specific, and
    // they would be about numbers no longer on screen.
    setTurns([]);
    setPending(null);
    setAskAttempts([]);
    const timer = setTimeout(() => {
      void predict(values as PredictBody)
        .then((next) => {
          if (generation.current === mine) {
            setPrediction(next);
            setFailure(null);
          }
        })
        .catch((err: unknown) => {
          if (generation.current === mine) {
            setFailure(err instanceof Error ? err.message : "Could not reach the model.");
          }
        });
    }, PREDICT_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [values]);

  // The explanation. Longer debounce, and it never sets `failure`: the server's
  // failover means this call is not supposed to be able to fail, and if it does,
  // the page above it is still correct and should stay on screen.
  useEffect(() => {
    if (!values) return;
    const mine = generation.current;
    const timer = setTimeout(() => {
      setExplaining(true);
      void explain(values as PredictBody)
        .then((next) => {
          if (generation.current === mine) setAnswer(next);
        })
        .catch(() => {
          // Deliberately silent. The chart is the explanation; this was the
          // caption, and a missing caption is not an error worth a red banner.
        })
        .finally(() => {
          if (generation.current === mine) setExplaining(false);
        });
    }, EXPLAIN_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [values]);

  const askQuestion = useCallback(
    (question: string) => {
      if (!values) return;
      const mine = generation.current;
      setPending(question);
      setAskAttempts([]);
      void ask(values as PredictBody, question, turns)
        .then((reply) => {
          // Discard if the inputs moved while this was in flight -- the answer
          // is about a prediction that is no longer on screen.
          if (generation.current !== mine) return;
          setTurns((current) => [
            ...current,
            { role: "user", content: question },
            { role: "assistant", content: reply.answer },
          ]);
          setAskAttempts(reply.source === "fallback" ? reply.attempts : []);
        })
        .catch(() => {
          if (generation.current !== mine) return;
          // The request itself did not land (offline, server down). The server's
          // own failover never surfaces here -- it answers 200 either way.
          setTurns((current) => [
            ...current,
            { role: "user", content: question },
            {
              role: "assistant",
              content:
                "That question did not reach the server. The prediction and the " +
                "chart above are unaffected — they were computed before this was asked.",
            },
          ]);
        })
        .finally(() => {
          if (generation.current === mine) setPending(null);
        });
    },
    [values, turns],
  );

  const set = useCallback((name: string, next: number) => {
    setValues((current) => (current ? { ...current, [name]: next } : current));
  }, []);

  const reset = useCallback(() => {
    if (!card) return;
    const seeded: Record<string, number> = {};
    for (const [name, spec] of Object.entries(card.inputs)) seeded[name] = spec.default;
    setValues(seeded);
  }, [card]);

  if (loading) return <Status message="Loading the model…" />;
  if (error || !card) return <Status message={error ?? "No model available."} isError />;

  const ribbon: RibbonCell[] = [
    {
      v: prediction ? `${prediction.predicted_alt} U/L` : "—",
      k: "Predicted ALT",
    },
    {
      v: prediction ? `${prediction.reference.elevated_threshold} U/L` : "—",
      k: `Elevated-ALT line (${prediction?.reference.sex ?? "—"})`,
    },
    { v: card.n, k: "Adolescents trained on" },
    {
      v: num(card.validation.gradient_boosting.r_squared_log_alt, 3),
      k: "Out-of-fold R²",
    },
  ];

  return (
    <>
      <Crumbs here="Predict" />
      <Masthead
        eyebrow="Interactive demo"
        title="Predict one adolescent's ALT, and see why"
        tagline={
          <>
            The study's own specification, fitted by gradient boosting instead of
            regression. Every prediction comes with an exact decomposition — the
            model's baseline plus one bar per input equals the answer, and you can
            check the addition.
          </>
        }
        byline="Anirudh Gupta · NHANES 2017–2018"
        spec={SPEC}
      />

      <Ribbon cells={ribbon} />

      {/* `meta` is a short chip (it is `white-space: nowrap`), so the full
          specification sentence goes in the body. Putting it in the head made
          this page 838px wide inside a 430px viewport. */}
      <Module index="01" title="The inputs" meta="Model B + BMI">
        <p className="text">
          Seven values, the same seven the study's primary model uses —{" "}
          {card.specification.replace(/^Model B with BMI -- /, "")} Each slider
          spans the cohort's own 1st to 99th percentile, so nothing here asks the
          model about an adolescent unlike anyone it was fitted on.
        </p>

        <div className="predict-form">
          {card.features.map((name) => {
            const spec = card.inputs[name];
            const value = values?.[name];
            if (!spec || value === undefined) return null;
            return (
              <Control key={name} spec={spec} value={value} onChange={(v) => set(name, v)} />
            );
          })}
        </div>

        <div className="predict-actions">
          <button type="button" className="bundle-go" onClick={reset}>
            Reset to the cohort median
          </button>
        </div>

        {failure && <Status message={failure} isError />}
      </Module>

      {prediction && (
        <Module
          index="02"
          title="The prediction"
          meta={`${prediction.predicted_alt} ${prediction.units}`}
        >
          <Figure
            title="How each input moved the prediction"
            caption={
              <>
                Exact SHAP contributions from the model's own TreeSHAP. The bars
                are a decomposition, not a ranking: the {prediction.baseline_alt} U/L
                baseline plus every bar equals {prediction.predicted_alt} U/L.
              </>
            }
            meta={`baseline ${prediction.baseline_alt} → ${prediction.predicted_alt} U/L`}
            legend={<ContributionLegend data={prediction} />}
            footnote={prediction.caveat}
          >
            <ContributionChart data={prediction} />
          </Figure>

          <Table
            corner="Input"
            head={["Entered", "Cohort median", "Moved ALT by", "ln(ALT) contribution"]}
            rows={prediction.drivers.map((d) => [
              d.label,
              d.display,
              d.cohort_median_display ?? "—",
              d.percent_of_alt === null
                ? "—"
                : `${d.percent_of_alt > 0 ? "+" : ""}${d.percent_of_alt.toFixed(2)}%`,
              d.contribution_log.toFixed(5),
            ])}
            numeric={[1, 2, 3, 4]}
            caption="The chart above, as numbers. The last column is the additive one."
          />

          <Legend
            rows={[
              {
                term: "Against the screening line",
                def: prediction.reference.means,
              },
              ...(prediction.adjustments.length > 0
                ? [
                    {
                      term: "Adjustments",
                      tag: "input",
                      def: prediction.adjustments.join(" "),
                    },
                  ]
                : []),
              { term: "What this is not", tag: "caveat", def: prediction.not_causal },
            ]}
          />
        </Module>
      )}

      {prediction && (
        <Module
          index="03"
          title="In plain language, and your questions"
          meta={answer?.source === "llm" ? "language model" : "fallback"}
        >
          <Explanation
            answer={answer}
            loading={explaining && !answer}
            llmConfigured={llm?.configured ?? null}
          />

          <Conversation
            turns={turns}
            pending={pending}
            prompts={prompts}
            llmConfigured={llm?.configured ?? null}
            lastAttempts={askAttempts}
            onAsk={askQuestion}
          />
        </Module>
      )}

      <Module index="04" title="What the model is, and how well it works">
        <p className="text">
          {card.model}, fitted on {card.n} adolescents in {card.clusters} sampling
          clusters. {card.specification} Each row carries {card.weighted}.
        </p>
        <ModelCard card={card} />
        <Legend
          rows={[
            {
              term: "Why a second model at all",
              def: (
                <>
                  The study answers a hypothesis and needs interpretable
                  coefficients; this answers "what would you guess, and why", and
                  gradient boosting is better at it. It is also a check: given a
                  free hand, the tree model leans on body mass and sex and puts
                  dietary sugar near the bottom — the study's null result reached
                  a second way, by a method with no stake in it.
                </>
              ),
            },
            { term: "Elevated-ALT thresholds", tag: "clinical", def: card.elevated_alt_source },
            { term: "Trained on", def: card.trained_on },
            { term: "What a prediction means", tag: "caveat", def: card.caveat },
          ]}
        />
      </Module>
    </>
  );
}
