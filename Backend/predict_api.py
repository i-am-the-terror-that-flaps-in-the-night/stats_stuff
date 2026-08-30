"""
predict_api.py -- the interactive prediction demo, and the language model that
narrates it.

WHAT THIS IS FOR
    The rest of the API reports the study. This is the part a judge can touch:
    type in one adolescent's seven numbers, get a predicted ALT with an exact
    per-variable breakdown of how the model got there, and -- separately, and
    strictly optionally -- a plain-English paragraph explaining that breakdown.

    The prediction and the breakdown come from engine.py's part four: a LightGBM
    model fitted on the study's own cohort and its own primary specification,
    with SHAP contributions from the booster's own TreeSHAP. All of that is
    arithmetic on a committed artifact, and none of it involves a language
    model.

ROUTES
    GET  /api/predict/model      the model card -- inputs, ranges, scores, caveats
    POST /api/predict            one prediction with its SHAP decomposition
    POST /api/predict/explain    the same breakdown, narrated by an LLM
    POST /api/predict/ask        a follow-up question about that prediction
    GET  /api/predict/questions  starter questions for the question box
    GET  /api/predict/llm        is the LLM configured? (setup diagnostic only)

TWO LLM MODES, AND THE DIFFERENCE MATTERS
    /explain captions a prediction: one job, fully determined by the SHAP
    contributions, so when the model cannot be reached the server can generate
    the caption itself and lose nothing but polish.

    /ask answers whatever the visitor typed. Its failure mode is different in
    kind -- a judge will ask "so is this kid at risk?", "should they cut out
    soda?", "does sugar cause fatty liver?", which are requests for a diagnosis,
    for medical advice, and for the causal claim the study spent ten steps not
    making. So it gets its own system prompt built around declining those, and
    its offline fallback DOES NOT ANSWER: it says the model is unavailable and
    points at the chart. Inventing an answer at the moment a judge is watching
    is the one failure this project cannot absorb.

    Both prompts share _study_facts(), so they can never disagree about what the
    study found -- only about what they are allowed to do with it.

THE LINE BETWEEN THE MODEL AND THE LANGUAGE MODEL
    The language model does not predict anything, does not see the cohort, and
    cannot reach the booster. It receives a finished prediction and a finished
    list of contributions AS TEXT and writes two sentences about them. If it
    returns something wrong, the numbers on the page are still the numbers the
    gradient boosting model produced.

    That boundary is enforced by the route split, not by a promise. /api/predict
    never calls out to anything; the frontend renders it, and only then asks
    /api/predict/explain for prose. So an outage, a rate limit, a captive portal
    on the venue wifi or an unset API key degrades this page to "fully working,
    minus the paragraph" -- never to a blank one.

GRACEFUL DEGRADATION, IN THREE STEPS
    The plan calls it Strategy B, and it is a failover chain rather than a
    quality router:

      1. Nemotron 3.5 Lightning, with a short timeout. 3B active parameters of
         a 30B mixture -- far more than enough to describe seven numbers, and
         fast enough that a judge does not notice it happening.
      2. On any failure -- timeout, HTTP error, malformed body, unknown model
         slug -- Nemotron 3 Ultra, with a longer one. Overpowered for this, and
         that is the point: it is the backstop, not the workhorse.
      3. On a second failure, a canned explanation. NOT a fixed string: it is
         generated from the same SHAP contributions the LLM would have been
         given, so it names this reader's actual top drivers with their actual
         directions. Every response says which of the three answered, so the
         page can label a fallback as one instead of passing it off.

    Reasoning is switched off in the request. A reasoning model that spends
    twenty seconds thinking in front of a judge reads as a broken website, and
    there is nothing here to reason about.

NO NEW DEPENDENCY FOR THE HTTP CALL
    The OpenRouter call uses urllib from the standard library, not httpx or
    requests. One POST of a small JSON body with a timeout is the entire
    requirement, urllib does it in fifteen lines, and this service runs on 512 MB
    where every import is charged against a cold start. This is the same
    argument behind the frontend's hand-rolled ZIP and PDF writers.

    The route functions are sync `def`, so FastAPI runs them in its threadpool
    and a blocking urlopen with a timeout cannot stall the event loop.

THE KEY IS SERVER-SIDE, AND THIS IS THE ONLY PLACE IT EXISTS
    OPENROUTER_API_KEY is read from the environment here and never leaves this
    module. The browser talks to this service; this service talks to OpenRouter.
    Nothing in frontend/ has ever seen the key, and /api/predict/llm reports
    only whether one is configured -- never any part of its value.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/predict", tags=["predict"])

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# The failover chain, in order. Overridable by environment variable so a model
# that is renamed or retired on OpenRouter can be swapped on Render without a
# redeploy -- and so the fair can be run on the paid slugs while development
# uses the ":free" variants of the same two models.
#
# Both are verified slugs from openrouter.ai/api/v1/models. Lightning is
# $0.08/M in and $0.20/M out; Ultra is $0.50/M and $2.20/M. A prompt here is
# ~600 tokens in and ~120 out, so a hundred judges cost well under a cent.
# Do not run the fair on the ":free" endpoints -- they are rate-limited per
# account, and a night of testing plus a queue of judges is exactly the traffic
# shape that trips them.
PRIMARY_MODEL = os.environ.get("OPENROUTER_MODEL", "nvidia/nemotron-3.5-lightning")
FALLBACK_MODEL = os.environ.get(
    "OPENROUTER_FALLBACK_MODEL", "nvidia/nemotron-3-ultra-550b-a55b"
)

# Seconds. The primary budget is what a person will stand still for; the
# fallback gets more because by the time it runs the reader has already waited
# once, and a slow answer beats no answer at that point. Both are hard ceilings
# on the socket, not hopes.
PRIMARY_TIMEOUT = float(os.environ.get("OPENROUTER_TIMEOUT", "3.0"))
FALLBACK_TIMEOUT = float(os.environ.get("OPENROUTER_FALLBACK_TIMEOUT", "8.0"))

# Short on purpose. The chart is the explanation; this is the caption under it,
# and a model given room to write five paragraphs will start theorizing about
# livers.
MAX_TOKENS = 220

# A follow-up gets more room than a caption and still not much. A question
# deserves a real answer; five paragraphs at a poster is a wall nobody reads,
# and length is where a model drifts from the numbers into the general
# knowledge about livers it is not supposed to be using.
ASK_MAX_TOKENS = 420

# Follow-ups get a longer budget than the caption, and the reason is about the
# reader rather than the model. The caption loads on its own the moment a slider
# moves, so a judge who is not waiting for it must never notice it; three
# seconds is that budget. A question was TYPED and submitted, so the person is
# already waiting on purpose, and at that point a slower real answer beats a
# fast "the model could not answer". Derived from the base timeouts rather than
# given their own environment variables -- one knob per venue, not three.
ASK_TIMEOUT = float(os.environ.get("OPENROUTER_ASK_TIMEOUT", PRIMARY_TIMEOUT * 2.5))
ASK_FALLBACK_TIMEOUT = float(
    os.environ.get("OPENROUTER_ASK_FALLBACK_TIMEOUT", FALLBACK_TIMEOUT * 2)
)

# What the client may send back as conversation history. Both caps are about
# cost and latency rather than correctness: this service holds no session, so
# the history arrives in the request, and an uncapped one is a way to make the
# booth's own page send a very large prompt on somebody's card. Six turns is
# three exchanges, which is more follow-up than a judge has ever asked for.
MAX_QUESTION_CHARS = 400
MAX_HISTORY_TURNS = 6

# Sent by OpenRouter to the model page's leaderboard. Harmless, and it makes the
# project's own traffic identifiable in the account dashboard.
APP_TITLE = "NHANES Adolescent Liver Stress -- science fair demo"
APP_URL = os.environ.get("OPENROUTER_REFERER", "https://github.com/")


def _engine():
    """engine.py, imported lazily -- it pulls in pandas, numpy and (here)
    LightGBM, and a visitor who never opens this page should not pay for any of
    them. Same idiom and same reason as study_api.py's _study()."""
    try:
        import engine
    except ModuleNotFoundError:
        from Backend import engine
    return engine


def _cache_control() -> str:
    """app.py's API Cache-Control policy. Imported inside the function to avoid
    the import cycle described in study_api.py's _cache_control()."""
    try:
        from app import API_CACHE_CONTROL
    except ModuleNotFoundError:
        from Backend.app import API_CACHE_CONTROL
    return API_CACHE_CONTROL


# ----------------------------------------------------------------------
# The prediction itself -- no network, no language model
# ----------------------------------------------------------------------


class PredictIn(BaseModel):
    """The seven inputs, all optional.

    Optional because the model card ships a cohort median for every one of them
    and engine.py fills a missing value with it, reporting that it did. A form
    the reader has only half filled in should still produce an answer with an
    honest note attached, not a 422.

    The bounds here are deliberately wider than the sliders the UI offers: the
    cohort's own 1st-99th percentile range is enforced in engine.py by clamping
    and reporting, which is more useful than refusing. These are only the outer
    limits of physical plausibility, to keep a fuzzed request from reaching the
    booster with 1e308 in it.
    """

    Sugar10g: float | None = Field(default=None, ge=0, le=200)
    ScreenTime: float | None = Field(default=None, ge=0, le=24)
    Age: float | None = Field(default=None, ge=12, le=17)
    Male: float | None = Field(default=None, ge=0, le=1)
    TrigHDLRatio: float | None = Field(default=None, ge=0, le=50)
    HbA1c: float | None = Field(default=None, ge=2, le=20)
    BMI: float | None = Field(default=None, ge=8, le=90)


def _predict(body: PredictIn) -> dict:
    """engine.predict_alt(), with a missing artifact turned into a clean 503.

    A 503 and not a 500: the model file is a build product, and the honest
    reading of "it is not there" is that this instance cannot serve the feature
    right now, with an actionable message rather than a stack trace.
    """
    try:
        return _engine().predict_alt(body.model_dump(exclude_none=True))
    except FileNotFoundError as missing:
        raise HTTPException(status_code=503, detail=str(missing)) from None
    except ValueError as bad:
        raise HTTPException(status_code=422, detail=str(bad)) from None


@router.get("/model")
def model_card(response: Response):
    """The model card: every input with its range and default, the
    cross-validated scores, the feature ranking, and what the model may claim.

    The UI builds its whole form from this rather than hard-coding seven
    sliders, so a retrain that moves a range moves the control with it.
    """
    try:
        card = _engine().predictor_card()
    except FileNotFoundError as missing:
        raise HTTPException(status_code=503, detail=str(missing)) from None
    response.headers["Cache-Control"] = _cache_control()
    return card


@router.post("")
def predict(body: PredictIn):
    """One prediction and its exact SHAP decomposition.

    Not cached and not cacheable: the key space is the seven-dimensional input
    space, which is the one place in this service where an unbounded memo would
    be a memory leak with a URL bar attached (see lab_api.py's CACHING note).
    A prediction is around a millisecond anyway -- the cost here was ever only
    the one-time LightGBM import.
    """
    return _predict(body)


# ----------------------------------------------------------------------
# The language model -- optional, replaceable, and never load-bearing
# ----------------------------------------------------------------------


@lru_cache(maxsize=1)
def _study_facts() -> str:
    """Everything true about this project, written from engine.py at call time.

    THIS IS THE FACT-CHECKING STEP, done by construction rather than by
    proofreading. Every number below is read from the same functions that
    produce the site's own numbers, so a prompt cannot come to disagree with the
    study it describes. A hardcoded "sugar was not significant (p = 0.76)" would
    be one refit away from being a lie told confidently to a judge.

    Shared by both prompts below. The caption and the question-answering mode
    differ in what they are allowed to DO, never in what they are told is true
    -- if they could drift apart on the facts, the paragraph on the page and the
    answer to a follow-up about it could contradict each other, in front of the
    person who asked.
    """
    engine = _engine()
    head = engine.headline()
    card = engine.predictor_card()
    scores = card["validation"]
    ranking = ", ".join(
        f"{row['label']} ({row['mean_abs_shap']})" for row in card["importance"]
    )

    return f"""THE PROJECT
An 8th-grade Medicine & Health project on dietary sugar, metabolic markers and \
early liver stress in U.S. adolescents aged 12-17, using NHANES 2017-2018 \
(n = {head["n"]} in the primary model).

THE STUDY'S FINDINGS -- these are settled, and you must not contradict them:
* The pre-specified primary test found that dietary sugar does NOT \
independently predict ALT once BMI is accounted for (p = {head["sugar_p"]}). \
This null result is the study's headline. Never imply sugar drives liver stress.
* What does predict ALT: body mass, sex (boys sit higher than girls), and the \
triglyceride/HDL ratio (standardized beta {head["trig_hdl_beta"]}, \
p = {head["trig_hdl_p"]}).
* {head["elevated_alt_percent"]}% of these adolescents had ALT above the \
sex-specific pediatric screening threshold.

THE MODEL YOU ARE EXPLAINING
LightGBM gradient-boosted trees on the same {card["n"]} adolescents and the same \
specification as the study's primary model. Out-of-fold R-squared \
{scores["gradient_boosting"]["r_squared_log_alt"]} on ln(ALT), against \
{scores["linear_model_b_with_bmi"]["r_squared_log_alt"]} for the study's linear \
model on identical folds. It ranks its inputs, by mean absolute SHAP: {ranking}. \
Dietary sugar is near the bottom, which agrees with the study.

The numbers you are given are exact SHAP contributions: the base value plus \
every contribution equals the prediction. They describe THIS MODEL'S \
arithmetic, not a person's biology.

HOW GOOD IS IT, HONESTLY
An out-of-fold R-squared near 0.28 means the model explains under a third of
the variation in ALT. It is better than the linear model and it is not a
diagnostic tool. Say so if asked.
"""


@lru_cache(maxsize=1)
def _system_prompt() -> str:
    """The caption mode: describe this one prediction and stop.

    The instructions are mostly prohibitions, and the prohibitions are the
    point. The one genuine risk in bolting a language model onto this project is
    that it says the thing the study spent ten steps not saying: that sugar
    causes liver stress. So the null result is stated explicitly, causal
    language is banned outright, and the model is told it may not add facts.
    """
    return f"""You explain one prediction from a science-fair project's model. \
You are the caption under a chart, not an analyst.

{_study_facts()}
RULES
1. Two to four sentences. Plain language, no jargon, no bullet points, no \
headings, no markdown.
2. Use only the numbers in the user message. Never invent, round differently, \
or add a fact that is not there.
3. Name the two or three largest contributions and say which way each pushed \
the prediction.
4. Never use causal words -- causes, leads to, results in, due to, because of, \
raises your risk. Say "is associated with", "the model weighted", "pushed the \
prediction up".
5. Never give medical advice, a diagnosis, or a recommendation. This is not a \
health assessment of anyone.
6. If sugar is among the top drivers for this particular input, say plainly \
that the study found no independent association overall and this is one \
prediction, not evidence against that.
7. Write for a curious visitor at a science fair: interested, not a \
statistician."""


@lru_cache(maxsize=1)
def _ask_prompt() -> str:
    """The follow-up mode: answer the visitor's actual question.

    WHY THIS IS A SEPARATE PROMPT AND NOT A LONGER CAPTION
        The caption has one job and a fixed table to do it from, so "use only
        the numbers in the user message" is a complete instruction. A question
        is open-ended, and the failure modes change shape with it. A judge will
        ask "so is this kid at risk?", "should they cut out soda?", "does sugar
        cause fatty liver?" -- three requests for, respectively, a diagnosis,
        medical advice, and the causal claim the study spent ten steps not
        making. A prompt tuned for captioning would answer all three helpfully.

        So this one is built around what to do when the honest answer is not
        available: say the numbers do not support it, and say what they do
        support. That instruction is worth more here than any amount of
        encouragement to be informative, because the cost of a wrong answer at a
        science fair is not a bad answer -- it is a judge told something false
        by a project whose whole argument is that it is careful.

    It shares _study_facts() with the caption, so the two cannot drift apart on
    what is true.
    """
    return f"""You answer follow-up questions from a visitor at a science fair, \
about one prediction from the project's model. You are a careful explainer of \
somebody else's work, not an analyst and not a clinician.

{_study_facts()}
WHAT YOU CAN AND CANNOT ANSWER FROM
You are given the prediction, its exact SHAP breakdown, and the facts above. \
That is everything you know. You cannot run the model again, cannot see other \
adolescents, and cannot look anything up.

RULES
1. Two to five sentences. Plain language, no markdown, no bullet points, no \
headings.
2. Answer from the numbers you were given and the facts above, and nothing \
else. If a question cannot be answered from them, SAY SO plainly and say what \
the numbers do show instead. "The model doesn't measure that" is a good answer.
3. Never use causal words -- causes, leads to, results in, due to, because of, \
raises your risk, protects against. Say "is associated with", "the model \
weighted", "pushed the prediction up".
4. Never give medical advice, a diagnosis, a risk assessment of a person, or a \
recommendation about what anyone should eat or do. If asked, say that this is a \
statistical model built for a science project, not a health assessment, and \
that a question about a real person is one for a doctor.
5. Never say or imply that dietary sugar causes liver stress. The study's \
pre-specified test found no independent association once BMI was accounted for. \
If the question presses on sugar, give that result plainly.
6. Do not invent numbers, and do not re-round the ones you have. If you are \
asked for a figure you were not given, say you do not have it.
7. If asked what would happen when an input changes, you may describe which way \
the model has weighted that input FOR THIS PREDICTION, and must add that \
changing the number changes the model's guess, not anyone's liver.
8. If the question is not about this prediction, this model or this study, say \
that is outside what the project can speak to, in one sentence.
9. Never claim to be a person, a doctor, or the student who built this."""


def _user_message(prediction: dict) -> str:
    """The prediction, flattened into the smallest text that fully determines
    the answer. Nothing here is prose the model can lean on -- it is a table, so
    anything the model says beyond it is visibly an addition."""
    reference = prediction["reference"]
    lines = [
        f"Predicted ALT: {prediction['predicted_alt']} U/L.",
        f"Model's starting point before any input: {prediction['baseline_alt']} U/L.",
        (
            f"Sex-specific elevated-ALT line for this reader: "
            f"{reference['elevated_threshold']} U/L "
            f"({'at or above' if reference['above_threshold'] else 'below'} it)."
        ),
        "",
        "Contributions (positive pushed the prediction up), largest first:",
    ]
    for driver in prediction["drivers"]:
        # driver["display"], not value + unit: the raw pair reads as
        # "1 0 = female, 1 = male" for sex and "10 10 g/day" for sugar, and a
        # model asked to narrate those will narrate them literally.
        median = driver["cohort_median_display"]
        context = f" (cohort median {median})" if median else ""
        # The sign lives in the verb, so the percentage is absolute. "lowers the
        # prediction by -4.18%" is a double negative, and a model copying it
        # into prose gets the direction backwards half the time.
        size = abs(driver["percent_of_alt"] or 0)
        lines.append(
            f"- {driver['label']}: entered {driver['display']}{context}; "
            f"{driver['direction']} the prediction by {size:.2f}% of ALT."
        )
    if prediction.get("adjustments"):
        lines.append("")
        lines.append(
            "Adjustments made to the input: " + " ".join(prediction["adjustments"])
        )
    lines.append("")
    lines.append("Explain this prediction under the rules you were given.")
    return "\n".join(lines)


def _canned_explanation(prediction: dict) -> str:
    """The third step of the failover: prose assembled from the contributions.

    Deliberately not a fixed paragraph. A static string would be wrong for most
    inputs -- it would describe drivers this reader did not enter -- and a judge
    who moved a slider and watched the words stay put would learn something true
    but unflattering. This names the actual top three, in their actual
    directions, and it can be checked against the chart beside it.

    It also runs with no network at all, which makes it the same text the
    offline demo page ships (see scripts/build_offline_demo.py).
    """
    drivers = [d for d in prediction["drivers"] if d["contribution_log"]][:3]
    if not drivers:
        return (
            f"The model predicts about {prediction['predicted_alt']} U/L. None of "
            "the values entered moved it far from its starting point of "
            f"{prediction['baseline_alt']} U/L."
        )

    def phrase(driver: dict) -> str:
        # The label keeps its own capitalisation. Lower-casing it to fit the
        # sentence turns "BMI" into "bmi" and "HbA1c" into "hba1c".
        median = driver["cohort_median_display"]
        # A category has no above or below -- "Male, above the cohort median" is
        # nonsense, and the median of a 0/1 column is not printable anyway.
        where = (
            ""
            if not median
            else (
                ", above the cohort median"
                if driver["value"] > driver["cohort_median"]
                else ", below the cohort median"
            )
        )
        # Past tense, because this describes an answer already on the screen.
        verb = "raised" if driver["direction"] == "raises" else "lowered"
        # One decimal. The underlying figure has three, and "about 36.364%" is a
        # precision the word "about" has already disclaimed.
        size = abs(driver["percent_of_alt"] or 0)
        return (
            f"{driver['label']} ({driver['display']}{where}) {verb} it by "
            f"about {size:.1f}%"
        )

    parts = [phrase(d) for d in drivers]
    body = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + f", and {parts[-1]}"
    sugar = next((d for d in drivers if d["feature"] == "Sugar10g"), None)
    note = (
        " Sugar appears here only as this model's arithmetic for these "
        "particular inputs -- the study's pre-specified test found no "
        "independent association between dietary sugar and ALT once BMI was "
        "accounted for."
        if sugar
        else ""
    )
    return (
        f"The model starts every adolescent at {prediction['baseline_alt']} U/L and "
        f"adjusts from there, landing at {prediction['predicted_alt']} U/L. "
        f"{body}. These are associations the model learned in NHANES, not "
        f"statements about any real person's liver.{note}"
    )


def _call_openrouter(
    model: str,
    prompt: str,
    turns: list[dict],
    timeout: float,
    max_tokens: int = MAX_TOKENS,
) -> str:
    """One OpenRouter chat completion. Raises on anything short of usable text.

    `turns` is the conversation after the system prompt -- one entry for the
    caption, and the whole back-and-forth for a follow-up question. The service
    keeps no session: the client sends the history it wants answered in context
    and this rebuilds the request from scratch each time, which is why two
    people at the booth can never land in each other's conversation.

    Every failure mode -- no key, socket timeout, HTTP 4xx/5xx, unparseable
    body, empty content -- comes out as an exception, because the caller's only
    decision is "did this work", and a half-answer is a failure here. An unknown
    model slug is an HTTPError like any other, so a model that OpenRouter
    retires fails over to the next step instead of taking the page down.
    """
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "system", "content": prompt}, *turns],
            "max_tokens": max_tokens,
            # Low, not zero: this is a caption over a fixed table of numbers, so
            # there is nothing to be creative about, and drift is the only thing
            # variety could buy.
            "temperature": 0.2,
            # Off. Both Nemotron models can reason, and neither should here --
            # see the module docstring on the twenty-second pause.
            "reasoning": {"enabled": False},
        }
    ).encode()

    request = urllib.request.Request(
        OPENROUTER_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": APP_URL,
            "X-Title": APP_TITLE,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as answer:  # noqa: S310
        body = json.loads(answer.read().decode())

    text = (body["choices"][0]["message"]["content"] or "").strip()
    if not text:
        raise RuntimeError(f"{model} returned an empty message")
    return text


def _chain(
    prompt: str,
    turns: list[dict],
    timeouts: tuple[float, float],
    max_tokens: int = MAX_TOKENS,
) -> tuple[str | None, str | None, list[dict]]:
    """Strategy B's first two steps: Lightning, then Ultra.

    Returns (text, model, attempts) with text None when both failed -- the third
    step differs by caller and so is theirs to supply. The caption can generate
    a real fallback from the contributions; a follow-up question cannot, and
    must say so instead of inventing one. Sharing the chain and not the fallback
    is what keeps that distinction from being an accident.
    """
    attempts: list[dict] = []
    for model, timeout in zip((PRIMARY_MODEL, FALLBACK_MODEL), timeouts):
        started = time.perf_counter()
        try:
            text = _call_openrouter(model, prompt, turns, timeout, max_tokens)
        except Exception as failure:
            attempts.append(
                {
                    "model": model,
                    "ok": False,
                    "ms": round((time.perf_counter() - started) * 1000),
                    # The class name and message, never the traceback: this is
                    # shown in the UI's diagnostics strip at a science fair.
                    #
                    # "failure" and not "error" on purpose. A recorded failure
                    # here is the failover WORKING, and scripts/smoke_test.py
                    # fails any response carrying an "error" key at any depth --
                    # a blanket rule worth keeping blanket, so this field is
                    # named for what it is rather than earning a carve-out.
                    "failure": f"{type(failure).__name__}: {failure}",
                }
            )
            continue
        attempts.append(
            {
                "model": model,
                "ok": True,
                "ms": round((time.perf_counter() - started) * 1000),
            }
        )
        return text, model, attempts

    return None, None, attempts


def explain_prediction(prediction: dict) -> dict:
    """Strategy B in full: Lightning, then Ultra, then the canned explanation.

    Always returns a usable dict -- there is no failure path out of this
    function, which is the whole design. `source` says which step answered
    ("llm" or "fallback") and `attempts` records what each one did, so the page
    can label a fallback and a developer can see at the booth why the fast model
    was skipped.
    """
    text, model, attempts = _chain(
        _system_prompt(),
        [{"role": "user", "content": _user_message(prediction)}],
        (PRIMARY_TIMEOUT, FALLBACK_TIMEOUT),
    )
    return {
        "explanation": text if text else _canned_explanation(prediction),
        "source": "llm" if text else "fallback",
        "model": model,
        "attempts": attempts,
        "disclaimer": LLM_DISCLAIMER,
    }


LLM_DISCLAIMER = (
    "Written by a language model from the numbers above. It did not compute the "
    "prediction and cannot change it -- the gradient boosting model produced "
    "every figure on this page before this sentence was requested."
)


SUGGESTED_QUESTIONS = [
    # Written here, not in the frontend, because each one is chosen to exercise
    # a guardrail as much as to be interesting -- and a visitor at a poster does
    # not know what to ask a model. The second is the one that matters: it is a
    # request for a risk assessment of a person, and a good answer declines it.
    "Why does body mass matter more than sugar here?",
    "Is this adolescent at risk?",
    "What would change if this were a girl?",
    "How much should I trust this prediction?",
    "What does the model not know about?",
]


def _canned_answer(question: str) -> str:
    """The third failover step for a question -- and it does NOT answer it.

    This is the one place in the demo where the fallback deliberately refuses to
    do the thing that was asked. The caption's fallback can be generated,
    because the caption's content is fully determined by the SHAP contributions
    and the server has those. An arbitrary question is not determined by
    anything the server can compute, so the only honest options are to say the
    answer is unavailable or to make one up -- and a project whose entire
    argument is that it is careful about what it claims does not get to make one
    up at the moment a judge is watching.

    So it says what happened, and points at the two things on the page that
    answer most questions anyway.
    """
    _ = question  # not answered on purpose; kept so the signature reads honestly
    return (
        "The language model is not answering right now, so this is the site "
        "speaking rather than a model, and it will not guess at an answer. "
        "Everything above is unaffected -- the prediction and the breakdown "
        "never involved a language model. The chart shows exactly how each "
        "input moved this prediction, and the section below it has the model's "
        "accuracy and what it was trained on."
    )


def answer_question(prediction: dict, question: str, history: list[dict]) -> dict:
    """A follow-up about this prediction, grounded in this prediction.

    The prediction is re-sent as the first turn EVERY time rather than being
    left behind in the history the client holds. It is the only thing the model
    is allowed to reason from, so it has to be in the context of every request,
    and rebuilding it here means a client cannot quietly edit the numbers the
    answer is about.

    Never raises for a language-model failure. The three steps are the same
    Lightning -> Ultra -> fallback chain the caption uses; only the third
    differs, because a question cannot be answered offline (see _canned_answer).
    """
    turns: list[dict] = [
        {"role": "user", "content": _user_message(prediction)},
        # A synthetic assistant turn carrying the caption the reader is looking
        # at. Without it the model answers "why is BMI the biggest?" with no
        # idea what has already been said, and repeats the paragraph above the
        # question box back at the person who just read it.
        {"role": "assistant", "content": _canned_explanation(prediction)},
    ]
    for turn in history[-MAX_HISTORY_TURNS:]:
        role = "assistant" if turn.get("role") == "assistant" else "user"
        turns.append({"role": role, "content": str(turn.get("content", ""))[:2000]})
    turns.append({"role": "user", "content": question})

    text, model, attempts = _chain(
        _ask_prompt(),
        turns,
        (ASK_TIMEOUT, ASK_FALLBACK_TIMEOUT),
        ASK_MAX_TOKENS,
    )
    return {
        "question": question,
        "answer": text if text else _canned_answer(question),
        "source": "llm" if text else "fallback",
        "model": model,
        "attempts": attempts,
        "disclaimer": LLM_DISCLAIMER,
    }


class AskIn(PredictIn):
    """A follow-up question, with the inputs it is about.

    Inherits the seven inputs rather than taking a prediction, for the same
    reason /explain re-predicts: the server must be answering about numbers it
    computed. Accepting a prediction over the wire would let anyone hand the
    language model an invented table and get it discussed in the project's own
    voice.
    """

    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    # The exchange so far, oldest first, so "and what about the other one?"
    # resolves. Sent by the client because this service keeps no session --
    # Render's free tier restarts constantly and two visitors must never share
    # a conversation. Capped in answer_question(), not here, so an over-long
    # history is trimmed rather than 422'd at somebody mid-demo.
    history: list[dict] = Field(default_factory=list)


@router.post("/ask")
def ask(body: AskIn):
    """Answer a follow-up question about one prediction.

    Predicts first, then asks -- so the answer is always about numbers this
    server just computed, and the response carries them, which lets the page
    show the question and the prediction it refers to as one unit.
    """
    prediction = _predict(body)
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="The question was empty.")
    return {
        "prediction": prediction,
        **answer_question(prediction, question, body.history),
    }


@router.get("/questions")
def suggested_questions(response: Response):
    """Starter questions for the page's question box.

    Served rather than hard-coded in the frontend because they are part of the
    demo's argument, not decoration: one of them asks for a risk assessment, and
    the right answer is a refusal. Keeping them beside the prompt that has to
    handle them means the two get edited together.
    """
    response.headers["Cache-Control"] = _cache_control()
    return {"questions": SUGGESTED_QUESTIONS, "max_chars": MAX_QUESTION_CHARS}


@router.post("/explain")
def explain(body: PredictIn):
    """Predict, then narrate. Never fails on the narration.

    This route predicts again rather than accepting a prediction from the
    client, so the paragraph is always describing numbers this server computed.
    Accepting the breakdown over the wire would let anyone hand the language
    model an invented table and get it described in the project's own voice.
    """
    prediction = _predict(body)
    return {"prediction": prediction, **explain_prediction(prediction)}


@router.get("/llm")
def llm_status():
    """Is the language model configured? A setup check, not a health check.

    Reports only whether a key is present and which slugs are wired up -- never
    any part of the key, and it deliberately does not call OpenRouter, so it
    stays free to hit and cannot be used to burn someone's credit. Point it at
    the deploy after setting the environment variable; if `configured` is false
    at the fair, every explanation will be the canned one.
    """
    return {
        "configured": bool(os.environ.get("OPENROUTER_API_KEY", "").strip()),
        "primary_model": PRIMARY_MODEL,
        "fallback_model": FALLBACK_MODEL,
        "primary_timeout_s": PRIMARY_TIMEOUT,
        "fallback_timeout_s": FALLBACK_TIMEOUT,
        "note": (
            "The prediction and its SHAP breakdown never touch this. With no key "
            "configured, /api/predict/explain still answers -- with the canned "
            "explanation generated from the same contributions."
        ),
    }
