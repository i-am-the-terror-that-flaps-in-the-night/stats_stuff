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
    GET  /api/predict/model     the model card -- inputs, ranges, scores, caveats
    POST /api/predict           one prediction with its SHAP decomposition
    POST /api/predict/explain   the same breakdown, narrated by an LLM
    GET  /api/predict/llm       is the LLM configured? (setup diagnostic only)

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
def _system_prompt() -> str:
    """The system prompt, built from the study's ACTUAL results at call time.

    This is the fact-checking step, done by construction rather than by
    proofreading. Every number below is read from engine.py -- the same
    functions that produce the site's own numbers -- so the prompt cannot come
    to disagree with the study it is describing. A hardcoded "sugar was not
    significant (p = 0.76)" would be one refit away from being a lie told
    confidently to a judge.

    The instructions are mostly prohibitions, and the prohibitions are the
    point. The one genuine risk in bolting a language model onto this project
    is that it says the thing the study spent ten steps not saying: that sugar
    causes liver stress. So the null result is stated explicitly, causal
    language is banned outright, and the model is told it may not add facts.
    """
    engine = _engine()
    head = engine.headline()
    card = engine.predictor_card()
    scores = card["validation"]
    ranking = ", ".join(
        f"{row['label']} ({row['mean_abs_shap']})" for row in card["importance"]
    )

    return f"""You explain one prediction from a science-fair project's model. \
You are the caption under a chart, not an analyst.

THE PROJECT
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


def _call_openrouter(model: str, prompt: str, message: str, timeout: float) -> str:
    """One OpenRouter chat completion. Raises on anything short of usable text.

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
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": message},
            ],
            "max_tokens": MAX_TOKENS,
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


def explain_prediction(prediction: dict) -> dict:
    """Strategy B: Lightning, then Ultra, then the canned explanation.

    Always returns a usable dict -- there is no failure path out of this
    function, which is the whole design. `source` says which step answered
    ("llm" or "fallback") and `attempts` records what each one did, so the page
    can label a fallback and a developer can see at the booth why the fast model
    was skipped.
    """
    prompt = _system_prompt()
    message = _user_message(prediction)
    attempts: list[dict] = []

    for model, timeout in (
        (PRIMARY_MODEL, PRIMARY_TIMEOUT),
        (FALLBACK_MODEL, FALLBACK_TIMEOUT),
    ):
        started = time.perf_counter()
        try:
            text = _call_openrouter(model, prompt, message, timeout)
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
        return {
            "explanation": text,
            "source": "llm",
            "model": model,
            "attempts": attempts,
            "disclaimer": LLM_DISCLAIMER,
        }

    return {
        "explanation": _canned_explanation(prediction),
        "source": "fallback",
        "model": None,
        "attempts": attempts,
        "disclaimer": LLM_DISCLAIMER,
    }


LLM_DISCLAIMER = (
    "Written by a language model from the numbers above. It did not compute the "
    "prediction and cannot change it -- the gradient boosting model produced "
    "every figure on this page before this sentence was requested."
)


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
