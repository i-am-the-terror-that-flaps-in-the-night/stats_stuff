"""
study.py -- the ten-step analysis the project's research protocol specifies.

WHAT THIS IS, AND HOW IT DIFFERS FROM THE ENGINE
    engine.py is a general-purpose statistics engine: hand it any
    spreadsheet and any column and it will describe it. It knows nothing about
    livers. Its tiers are deliberately question-agnostic, and that is what
    makes them reusable.

    This part is the opposite. It answers ONE set of pre-specified questions
    about ONE cohort, in a fixed order, with the roles of every variable decided
    in advance: ALT is the outcome, dietary sugar is the exposure, BMI is the
    mediator, sex and age are controls. That is a study protocol, not a feature
    of a spreadsheet, so it lives in its own module and calls the engine's shared
    helpers rather than growing a new tier inside DataAnalyzer.

    That boundary still protects the honest part of the engine's design. Because
    the roles here are fixed and declared up front, this part may legitimately
    do things engine.py refuses to do on an arbitrary column -- apply a
    sex-specific clinical threshold, decompose an association into direct and
    mediated parts -- precisely because the protocol committed to them before
    seeing the results.

THE ANALYTICAL HIERARCHY IS PRE-SPECIFIED
    The protocol distinguishes three grades of claim, and every step below is
    tagged with which one it is:

        primary     the hypothesis the study was designed to test. One model --
                    Model B, the protocol's full specification -- fitted twice:
                    without body mass (step 4, sugar's total association) and
                    with it (step 5, sugar's direct association). The sugar
                    coefficient in the SECOND of those is the single
                    pre-specified test, declared before the data were seen.
        supporting  pre-registered analyses that give the primary result context.
        exploratory generated hypotheses, not tests of them. The risk score and
                    the subgroup work are here. Uncorrected, and read as
                    suggestions for the next study rather than findings of this
                    one.

    That ordering exists to stop a null primary result from being quietly
    replaced by whichever subgroup happened to clear p < 0.05. It is declared in
    the protocol, and STEPS below is written in that order.

HOW THE SURVEY DESIGN IS HANDLED
    NHANES is not a simple random sample. It oversamples some groups and
    under-samples others, and it does so in clusters. Getting this wrong in
    either of two ways produces confident nonsense:

      * Ignoring the WEIGHTS (WTDRD1) makes the sample describe the people NHANES
        happened to recruit rather than U.S. adolescents. Every estimate here is
        weighted, so the coefficients generalize.
      * The CLUSTERING is a limitation this study reports rather than corrects.
        Two adolescents from the same sampled location are more alike than two
        strangers, so classical standard errors treat the sample as slightly
        more informative than it is. The protocol specifies weighted least
        squares with its ordinary (classical) standard errors, and that is what
        every model here fits -- the Revised Results were derived that way and
        this code reproduces them to the last digit. The 30 PSU-within-stratum
        clusters are counted and reported beside each model so the limitation
        is visible; see SURVEY_DESIGN_CAVEAT. (An earlier version used
        cluster-robust errors, which widen most intervals modestly; with only
        30 clusters they are themselves approximate, so neither choice is
        exact, and the protocol's is the one reported.)

WHAT THIS MODULE WILL NOT CLAIM
    Everything here is an association measured in observational, cross-sectional
    data. Diet, blood and body measurements were taken at essentially one point
    in time, so nothing here can establish that changing sugar intake would
    change anyone's ALT -- not even the mediation step, which decomposes an
    association into two associations and is named accordingly. The step that
    comes closest to a causal shape is the one flagged hardest; see
    MEDIATION_CAVEAT.
"""

from __future__ import annotations

from functools import lru_cache
from typing import cast

import numpy as np
import pandas as pd

# Two import paths because these modules are reached two ways: with Backend/ on
# sys.path (pytest, the `python Backend/cli.py` CLI) and with the repo root on
# it (`uvicorn main:app`, which imports Backend.app). Same idiom as app.py's
# _load_engine(). The dependency runs one way -- engine, cohort, study,
# predictor -- so none of these can close a cycle.
try:
    from engine import (
        ALPHA,
        DESCRIPTIVE,
        INFERENTIAL,
        NOT_CAUSAL,
        PREDICTIVE,
        _is_significant,
        _magnitude,
        _num,
        _significance_report,
    )
except ImportError:
    from Backend.engine import (
        ALPHA,
        DESCRIPTIVE,
        INFERENTIAL,
        NOT_CAUSAL,
        PREDICTIVE,
        _is_significant,
        _magnitude,
        _num,
        _significance_report,
    )

try:
    from cohort import (
        ALT_ELEVATED,
        ALT_THRESHOLD_SOURCE,
        COHORT_N_NOTE,
        METABOLIC_VARIABLES,
        cohort_attrition,
        load_cohort,
        risk_score,
    )
except ImportError:
    from Backend.cohort import (
        ALT_ELEVATED,
        ALT_THRESHOLD_SOURCE,
        COHORT_N_NOTE,
        METABOLIC_VARIABLES,
        cohort_attrition,
        load_cohort,
        risk_score,
    )


PRIMARY = "primary"
SUPPORTING = "supporting"
EXPLORATORY = "exploratory"

# The smallest p-value the study section will print as a number. _num() rounds
# p-values to four decimals, which is right for a dashboard but wrong here: a
# result at p = 0.000003 comes back as 0.0, and "p = 0" is not a thing that can
# happen -- it reads as certainty, which is the one claim a p-value never makes.
# Below this floor the report carries "< 0.0001" as text instead.
P_VALUE_FLOOR = 0.0001


def _report(p_value, effect_size=None) -> dict:
    """engine.py's significance block, with the p = 0 display bug closed."""
    report = _significance_report(p_value, effect_size)
    if report["p_value"] is not None and report["p_value"] < P_VALUE_FLOOR:
        report["p_value_text"] = f"< {P_VALUE_FLOOR}"
    else:
        report["p_value_text"] = str(report["p_value"])
    return report


SURVEY_DESIGN_CAVEAT = (
    "Estimates are weighted by the day-1 dietary weight (WTDRD1) so they "
    "describe U.S. adolescents rather than this sample. Standard errors are the "
    "classical weighted-least-squares ones the protocol specifies; they do not "
    "account for NHANES' clustered sampling (30 PSU-within-stratum clusters in "
    "this cohort), which makes them somewhat optimistic. Read p-values near the "
    "0.05 line as suggestive rather than exact."
)

MEDIATION_CAVEAT = (
    "Comparing a model with BMI against one without it decomposes an association "
    "into a part that travels with body mass and a part that does not. Calling "
    "the first part 'mediated' is a causal reading, and it holds only if sugar "
    "precedes BMI which precedes ALT, and nothing unmeasured causes both BMI and "
    "ALT. This is one-time-point observational data, so it can support none of "
    "those assumptions -- the decomposition is reported because the protocol "
    "pre-specified it, and it is consistent with mediation without demonstrating "
    "it. Total physical activity, diet quality beyond sugar, and genetics are all "
    "plausible common causes that are not adjusted for here."
)

LOG_TRANSFORM_NOTE = (
    "ALT is modelled as its natural log because the raw values are strongly "
    "right-skewed -- a long tail of high readings that would otherwise dominate "
    "a least-squares fit and violate its constant-variance assumption. The cost "
    "is that coefficients are no longer in U/L: a coefficient b means a "
    "proportional change, so a one-unit rise in the predictor multiplies ALT by "
    "exp(b). Small coefficients read as roughly 100*b percent."
)

# Sugar's coefficient is reported per 10 grams rather than per gram. A gram of
# sugar a day is far below the resolution a 24-hour recall can actually measure,
# so a per-gram coefficient is a number with four leading zeros that reads as
# "no effect" whatever it is. Per 10 g is still a small, realistic contrast (a
# few bites) and puts the estimate on a scale where its size can be judged.
SUGAR_UNIT = 10.0
SUGAR_UNIT_LABEL = "per 10 g/day"


def analysis_frame(columns, *, cohort=None) -> pd.DataFrame:
    """Complete cases on exactly the columns an analysis touches, plus design.

    Every model in the study starts here, and it takes the column list rather
    than assuming a fixed sample, because the samples genuinely differ: the
    metabolic (Model B) analyses run on the 314 adolescents in the fasting
    subsample and the lifestyle ones on all 695. Building the
    frame per analysis is what keeps each reported n true of the numbers next to
    it -- and, critically, what lets two models being COMPARED be forced onto one
    shared sample (see incremental_value), because a change in R-squared between
    two different samples measures nothing.
    """
    frame = load_cohort() if cohort is None else cohort
    needed = ["DietWeight", "SurveyPSU", "SurveyStratum", *columns]
    frame = frame.dropna(subset=[c for c in needed if c in frame.columns]).copy()
    frame["Male"] = (frame["Sex"] == "Male").astype(float)
    frame["LogALT"] = np.log(frame["ALT"].where(frame["ALT"] > 0))
    frame["Sugar10g"] = frame["TotalSugars"] / SUGAR_UNIT
    return frame


# ======================================================================
# WEIGHTED / SURVEY-AWARE PRIMITIVES
#
# Weighted versions of the everyday summaries. numpy has np.average(weights=)
# and nothing else, so the rest are written out here once.
# ======================================================================


def _wmean(values, weights) -> float:
    values, weights = np.asarray(values, float), np.asarray(weights, float)
    ok = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if not ok.any():
        return float("nan")
    return float(np.average(values[ok], weights=weights[ok]))


def _wstd(values, weights) -> float:
    """Weighted standard deviation.

    Uses the frequency-weight convention: the weights say how many people each
    row stands for, so the divisor is the summed weight rather than a count of
    rows. This is the right convention for a survey weight, which is exactly a
    "this person represents N Americans" statement.
    """
    values, weights = np.asarray(values, float), np.asarray(weights, float)
    ok = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if ok.sum() < 2:
        return float("nan")
    values, weights = values[ok], weights[ok]
    mean = np.average(values, weights=weights)
    return float(np.sqrt(np.average((values - mean) ** 2, weights=weights)))


def _wquantile(values, weights, q) -> float:
    """Weighted quantile: the smallest observed value whose weighted CDF
    reaches q, with tied values pooled.

    WHY THIS IS NOT INTERPOLATED, AND WHY THAT IS A BUG FIX
        The obvious implementation sorts the rows, puts one CDF point on each,
        and interpolates. That is what this function used to do, and it made the
        answer depend on the order tied rows happened to land in: a block of
        participants sharing a value contributes CDF points positioned by each
        row's individual weight, so which of them sorts first moves the number
        that gets read off.

        That is not hypothetical. numpy's default sort is introsort -- not
        stable, and SIMD-dispatched per architecture -- so this cohort sorted on
        an arm64 laptop broke ties differently from the same cohort on an x86_64
        CI runner. Six adolescents sit at exactly BMI 22.3 and three at 22.4,
        straddling the median, and the weighted median came out anywhere in
        22.20 to 22.29 depending on the machine. A published number that changes
        with the computer that produced it is not a published number. CI caught
        it on the predictor's model card; the same function also sets the
        study's sugar quartile boundaries.

        Pooling the ties and taking the CDF crossing fixes it at the root rather
        than papering over it with a stable sort, which would only have made one
        arbitrary tie-break reproducible. One entry per DISTINCT value, carrying
        the summed weight of every row holding it, is order-independent by
        construction: no sort's tie-breaking can reach it.

    THE CONVENTION, AND WHAT IT COSTS
        This is the inverse-CDF ("lower") quantile -- the definition survey
        packages use for weighted quantiles, and it returns a value somebody
        actually had. That matters on this cohort, which is mostly discrete:
        interpolating a median age across 695 adolescents aged 12-17 produces
        something like 14.6, which is not an age and not a median. The
        interpolating conventions differ only for continuous variables, where
        they land between the two adjacent observations instead of on the lower
        one.
    """
    values, weights = np.asarray(values, float), np.asarray(weights, float)
    ok = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if not ok.any():
        return float("nan")
    values, weights = values[ok], weights[ok]
    # np.unique returns the distinct values already sorted, so this pools the
    # ties and orders them in one pass.
    distinct, index = np.unique(values, return_inverse=True)
    pooled = np.bincount(index, weights=weights)
    cdf = np.cumsum(pooled) / np.sum(pooled)
    # side="left" gives the first value whose cumulative weight REACHES q. The
    # clamp is for the top of the range only: floating-point summation can leave
    # cdf[-1] a hair under 1.0, and q = 1 would then index past the end.
    position = int(np.searchsorted(cdf, q, side="left"))
    return float(distinct[min(position, len(distinct) - 1)])


def _clusters(frame: pd.Series | pd.DataFrame) -> pd.Series:
    """PSU nested within stratum, as one grouping label.

    NHANES numbers its PSUs 1 and 2 *within* each stratum, so PSU 1 of stratum
    145 and PSU 1 of stratum 146 are different places that share a code.
    Clustering on the raw PSU column would pool them into two giant clusters and
    quietly undo the correction. Combining both fields gives the 30 real ones.
    """
    return (
        frame["SurveyStratum"].astype(int).astype(str)
        + "_"
        + frame["SurveyPSU"].astype(int).astype(str)
    )


# ======================================================================
# THE MODEL
# ======================================================================


def fit_model(
    frame: pd.DataFrame, outcome: str, predictors: list[str], *, label: str = ""
):
    """Weighted least squares with classical standard errors.

    Returns a dict describing the fit -- coefficients with standard errors,
    confidence intervals, standardized betas, R-squared and n -- plus the
    statsmodels result object under "_model" for callers that need to run a
    joint test on it (incremental_value does).

    WLS, not OLS, because the survey weight makes the sample represent the
    population. Classical errors, not cluster-robust, because that is the
    "weighted least squares regression" the protocol specifies and the Revised
    Results report; the clustering is counted and disclosed, not corrected
    (see the module docstring).
    """
    import statsmodels.api as sm

    design = cast(
        pd.DataFrame,
        sm.add_constant(frame[predictors].astype(float), has_constant="add"),
    )
    model = sm.WLS(
        frame[outcome].astype(float),
        design,
        # The stub types `weights` as a scalar float; WLS in fact takes one
        # weight per observation, which is the whole point of using it here.
        weights=frame["DietWeight"].to_numpy(dtype=float),  # pyright: ignore[reportArgumentType]
    )
    result = model.fit()

    # Standardized betas, computed with the SAME weights as the fit. A beta says
    # "a one-standard-deviation rise in this predictor moves the outcome this
    # many of its own standard deviations", which is what makes predictors on
    # different units (grams, kg/m^2, %) comparable -- and comparing sugar
    # against Trig/HDL is the protocol's secondary hypothesis.
    weights = frame["DietWeight"]
    outcome_sd = _wstd(frame[outcome], weights)

    coefficients = {}
    intervals = result.conf_int()
    for name in design.columns:
        estimate = float(result.params[name])
        beta = None
        if name != "const" and outcome_sd and np.isfinite(outcome_sd):
            predictor_sd = _wstd(frame[name], weights)
            if np.isfinite(predictor_sd):
                beta = estimate * predictor_sd / outcome_sd
        p_value = float(result.pvalues[name])
        coefficients[name] = {
            "estimate": _num(estimate, 5),
            "std_error": _num(float(result.bse[name]), 5),
            "t": _num(float(result.tvalues[name]), 3),
            "ci_low": _num(float(intervals.loc[name, 0]), 5),
            "ci_high": _num(float(intervals.loc[name, 1]), 5),
            "standardized_beta": _num(beta, 4),
            "significance": _report(p_value),
        }

    return {
        "label": label,
        "outcome": outcome,
        "predictors": predictors,
        "n": int(result.nobs),
        "clusters": int(_clusters(frame).nunique()),
        "r_squared": _num(float(result.rsquared), 4),
        "adjusted_r_squared": _num(float(result.rsquared_adj), 4),
        "coefficients": coefficients,
        "estimator": "WLS (WTDRD1) with classical standard errors",
        "layer": PREDICTIVE,
        "not_causal": NOT_CAUSAL,
        "_model": result,
    }


def _public(model: dict) -> dict:
    """Strip the statsmodels object so a fit can be serialized to JSON."""
    return {k: v for k, v in model.items() if not k.startswith("_")}


def _percent_change(coefficient: float | None) -> float | None:
    """Turn a log-outcome coefficient into a percent change in ALT.

    exp(b) - 1, not b: the linear reading is a decent approximation only for
    coefficients near zero, and being exact costs one function call.
    """
    if coefficient is None or not np.isfinite(coefficient):
        return None
    return _num((np.exp(coefficient) - 1) * 100, 3)


# ======================================================================
# STEP 1 -- COHORT AND ATTRITION
# ======================================================================


def step_cohort() -> dict:
    """Who is in the study, and every rule that decided it."""
    frame = load_cohort()
    return {
        "step": 1,
        "protocol_step": 1,
        "title": "Cohort derivation and attrition",
        "grade": SUPPORTING,
        "layer": DESCRIPTIVE,
        "question": "Which adolescents does this study describe, and what removed the rest?",
        "attrition": cohort_attrition(),
        "n": len(frame),
        "n_note": COHORT_N_NOTE,
        "fasting_subsample_n": int(len(frame.dropna(subset=METABOLIC_VARIABLES))),
        "fasting_subsample_note": (
            "Triglycerides are measured only on NHANES' morning fasting subsample, "
            "so the Trig/HDL ratio -- and every Model B analysis -- exists for "
            f"{int(len(frame.dropna(subset=METABOLIC_VARIABLES)))} of the "
            f"{len(frame)} adolescents. Model A (lifestyle) runs on all of them."
        ),
        "design": SURVEY_DESIGN_CAVEAT,
    }


# ======================================================================
# STEP 2 -- WEIGHTED DESCRIPTIVE PROFILE
# ======================================================================

PROFILE_VARIABLES = [
    ("Age", "years"),
    ("ALT", "U/L"),
    ("TotalSugars", "g/day"),
    ("Energy", "kcal/day"),
    ("BMI", "kg/m^2"),
    ("Triglycerides", "mg/dL"),
    ("HDLCholesterol", "mg/dL"),
    ("TrigHDLRatio", "ratio"),
    ("HbA1c", "%"),
    ("ScreenTime", "hours/day"),
]


def step_profile() -> dict:
    """What the cohort looks like, weighted up to U.S. adolescents."""
    frame = load_cohort()
    weights = frame["DietWeight"]

    variables = []
    for name, unit in PROFILE_VARIABLES:
        values = frame[name]
        present = values.notna()
        variables.append(
            {
                "variable": name,
                "unit": unit,
                "n": int(present.sum()),
                "weighted_mean": _num(_wmean(values[present], weights[present]), 3),
                "weighted_sd": _num(_wstd(values[present], weights[present]), 3),
                "weighted_median": _num(
                    _wquantile(values[present], weights[present], 0.5), 3
                ),
                "unweighted_mean": _num(values.mean(), 3),
            }
        )

    elevated = frame["ALTElevated"]
    return {
        "step": 2,
        "protocol_step": 1,
        "title": "Weighted descriptive profile",
        "grade": SUPPORTING,
        "layer": DESCRIPTIVE,
        "question": "What are U.S. adolescents aged 12-17 like on these measures?",
        "n": len(frame),
        "sex": {
            "male": int((frame["Sex"] == "Male").sum()),
            "female": int((frame["Sex"] == "Female").sum()),
            "weighted_percent_male": _num(
                _wmean(frame["Sex"] == "Male", weights) * 100, 2
            ),
        },
        "variables": variables,
        "elevated_alt": {
            "count": int(elevated.sum()),
            "percent_unweighted": _num(elevated.mean() * 100, 2),
            "percent_weighted": _num(_wmean(elevated.astype(float), weights) * 100, 2),
            "thresholds": ALT_ELEVATED,
            "source": ALT_THRESHOLD_SOURCE,
        },
        "weighting_note": (
            "Weighted and unweighted means are both shown. Where they differ, the "
            "weighted one is the estimate for U.S. adolescents and the unweighted "
            "one describes only who NHANES recruited."
        ),
    }


# ======================================================================
# STEP 3 -- THE OUTCOME'S DISTRIBUTION
# ======================================================================


def step_outcome_distribution() -> dict:
    """Check ALT's shape and justify modeling it on the log scale."""
    import scipy.stats as sp

    frame = analysis_frame(["ALT"])
    raw, logged = frame["ALT"], frame["LogALT"]

    def shape(values, name):
        return {
            "scale": name,
            "skewness": _num(float(sp.skew(values)), 3),
            "kurtosis_excess": _num(float(sp.kurtosis(values)), 3),
            # Shapiro-Wilk tests departure from normality. On n=695 it detects
            # departures far too small to matter for a regression, so it is
            # reported for completeness and the skewness is what the decision
            # actually rests on.
            "shapiro_p": _num(float(sp.shapiro(values).pvalue), 6),
        }

    raw_shape, log_shape = shape(raw, "ALT (U/L)"), shape(logged, "ln(ALT)")
    improved = abs(log_shape["skewness"] or 0) < abs(raw_shape["skewness"] or 0)

    return {
        "step": 3,
        "protocol_step": 2,
        "title": "Outcome distribution and log transformation",
        "grade": SUPPORTING,
        "layer": DESCRIPTIVE,
        "question": "Is ALT shaped in a way least-squares regression can model honestly?",
        "n": len(frame),
        "raw": raw_shape,
        "log": log_shape,
        "transformation_applied": "natural log",
        "transformation_justified": bool(improved),
        "verdict": (
            f"Raw ALT is right-skewed (skewness {raw_shape['skewness']}); the log "
            f"scale reduces that to {log_shape['skewness']}, so every model below "
            "uses ln(ALT)."
            if improved
            else "The log transform did not reduce skewness; see the numbers above."
        ),
        "note": LOG_TRANSFORM_NOTE,
    }


# ======================================================================
# STEPS 4 AND 5 -- THE PRIMARY HYPOTHESIS
# ======================================================================

BASE_CONTROLS = ["Age", "Male"]

# ----------------------------------------------------------------------
# THE PROTOCOL'S TWO MODELS, WRITTEN ONCE
#
# The revised protocol names exactly two model specifications and then reuses
# them across four of its ten steps, so they are defined here rather than
# retyped at each call site -- a step that quietly dropped a covariate would
# otherwise be indistinguishable from one that did not.
#
#   Model A (lifestyle)   sugar, screen time, age, sex.
#   Model B (full)        Model A plus the Trig/HDL ratio and HbA1c.
#
# Model B is fitted TWICE, and which one is the primary test is pre-specified:
#
#   without BMI   sugar's TOTAL association, including whatever part travels
#                 through body mass.
#   with BMI      sugar's DIRECT association, net of body mass. This is the
#                 study's single primary test (protocol Step 5).
#
# BMI's dual role is the reason for the pair: excess sugar can raise body mass,
# and body mass raises ALT, so BMI is partly a consequence of the exposure
# (a mediator) and partly an independent cause of the outcome (a confounder).
# Adjusting for it answers one question and not adjusting answers another, and
# the protocol commits to reporting both rather than picking afterwards.
MODEL_A = ["Sugar10g", "ScreenTime", *BASE_CONTROLS]
MODEL_B = [*MODEL_A, "TrigHDLRatio", "HbA1c"]
MODEL_B_WITH_BMI = [*MODEL_B, "BMI"]

# The raw cohort columns Model B needs a participant to have. Everything fitted
# on the Model B specification -- with BMI or without, pooled or by sex -- draws
# its frame from this list, so all of those fits share one sample and their
# coefficients and R-squareds are comparable to each other. Because the
# Trig/HDL ratio exists only for the fasting subsample, this sample IS the
# fasting subsample: the protocol's n = 314.
MODEL_B_COLUMNS = [
    "ALT",
    "TotalSugars",
    "ScreenTime",
    "Age",
    "Sex",
    "TrigHDLRatio",
    "HbA1c",
    "BMI",
]

# The pre-registered multicollinearity threshold (original proposal, Step 5).
VIF_THRESHOLD = 5.0

MODEL_LABELS = {
    "A": "Model A -- lifestyle (sugar, screen time, age, sex)",
    "B": "Model B -- full, BMI excluded (sugar's total association)",
    "B_BMI": "Model B -- full, BMI included (sugar's direct association)",
}


def step_total_effect() -> dict:
    """Model B without BMI -- sugar's total association with ALT."""
    frame = analysis_frame(MODEL_B_COLUMNS)
    model = fit_model(frame, "LogALT", MODEL_B, label=MODEL_LABELS["B"])
    sugar = model["coefficients"]["Sugar10g"]

    return {
        "step": 4,
        "protocol_step": 5,
        "title": "Model B without BMI -- sugar's total association with ALT",
        "grade": PRIMARY,
        "layer": PREDICTIVE,
        "question": (
            "Does daily dietary sugar predict ALT in adolescents, before "
            "accounting for body mass?"
        ),
        "n": len(frame),
        "model": _public(model),
        "specification": MODEL_B,
        "sugar_per_10g": {
            "coefficient": sugar["estimate"],
            "percent_change_in_alt": _percent_change(sugar["estimate"]),
            "units": SUGAR_UNIT_LABEL,
            "significance": sugar["significance"],
        },
        "interpretation": _sugar_verdict(
            sugar, "with screen time, the metabolic markers, age and sex controlled"
        ),
        "note": LOG_TRANSFORM_NOTE,
        "not_causal": NOT_CAUSAL,
    }


def step_direct_effect() -> dict:
    """Model B with BMI -- the pre-specified primary test, and the mediation comparison.

    This step carries the study's primary result. The protocol declares the
    sugar coefficient HERE -- in the full model with BMI included -- as the one
    test the central hypothesis rises or falls on, and it declared it before the
    data were seen. Everything else in the study is context for this number.
    """
    frame = analysis_frame(MODEL_B_COLUMNS)

    total = fit_model(frame, "LogALT", MODEL_B, label=MODEL_LABELS["B"])
    direct = fit_model(frame, "LogALT", MODEL_B_WITH_BMI, label=MODEL_LABELS["B_BMI"])

    c = total["coefficients"]["Sugar10g"]["estimate"]
    c_prime = direct["coefficients"]["Sugar10g"]["estimate"]

    # The two paths the indirect route is built from: sugar -> BMI, then
    # BMI -> ALT with sugar held constant. Path a is fitted on the same Model B
    # covariates, so it is the association the decomposition actually needs
    # rather than an unadjusted one borrowed from a different specification.
    a_model = fit_model(frame, "BMI", MODEL_B, label="Sugar -> BMI")
    a = a_model["coefficients"]["Sugar10g"]["estimate"]
    b = direct["coefficients"]["BMI"]["estimate"]

    indirect = a * b if None not in (a, b) else None
    proportion = None
    if indirect is not None and c not in (None, 0) and np.sign(indirect) == np.sign(c):
        # Only meaningful when the indirect path runs the same direction as the
        # total: a "proportion mediated" above 1 or below 0 is a sign the
        # decomposition's assumptions have failed, not a finding, so it is left
        # out rather than printed as a number readers would quote.
        proportion = _num(indirect / c, 4)

    return {
        "step": 5,
        "protocol_step": 5,
        "title": (
            "Model B with BMI -- sugar's direct association with ALT "
            "(pre-specified primary test)"
        ),
        "grade": PRIMARY,
        "primary_test": True,
        "question": (
            "Does sugar's association with ALT survive adjustment for BMI, and how "
            "much of it travels through body mass?"
        ),
        "layer": PREDICTIVE,
        "n": len(frame),
        "total_model": _public(total),
        "direct_model": _public(direct),
        "path_a_sugar_to_bmi": _public(a_model),
        "specification": MODEL_B_WITH_BMI,
        "decomposition": {
            "total_c": _num(c, 5),
            "direct_c_prime": _num(c_prime, 5),
            "indirect_a_times_b": _num(indirect, 5),
            "proportion_mediated": proportion,
            "attenuation_percent": _num(
                (1 - c_prime / c) * 100
                if c not in (None, 0) and c_prime is not None
                else None,
                2,
            ),
            "path_a_sugar_to_bmi": _num(a, 5),
            "path_b_bmi_to_logalt": _num(b, 5),
        },
        "interpretation": _mediation_verdict(total, direct),
        "caveat": MEDIATION_CAVEAT,
        "not_causal": NOT_CAUSAL,
    }


def _sugar_verdict(sugar: dict, context: str) -> str:
    significant = sugar["significance"]["statistically_significant"]
    percent = _percent_change(sugar["estimate"])
    if not significant:
        return (
            f"No detectable association {context}: 10 g/day more sugar corresponds "
            f"to a {percent}% difference in ALT, and the interval spans zero "
            f"(p = {sugar['significance']['p_value']}). Read as consistent with no "
            "independent association, not as proof of none -- see the confidence "
            "interval for what sizes remain compatible with these data."
        )
    return (
        f"10 g/day more sugar corresponds to a {percent}% difference in ALT "
        f"{context} (p = {sugar['significance']['p_value']})."
    )


def _mediation_verdict(total: dict, direct: dict) -> str:
    c = total["coefficients"]["Sugar10g"]
    c_prime = direct["coefficients"]["Sugar10g"]
    bmi = direct["coefficients"]["BMI"]
    bits = [
        f"Without BMI, sugar's coefficient is {c['estimate']} "
        f"(p = {c['significance']['p_value']}); with BMI it is {c_prime['estimate']} "
        f"(p = {c_prime['significance']['p_value']}).",
        f"BMI itself is {'' if bmi['significance']['statistically_significant'] else 'not '}"
        f"a significant predictor of ln(ALT) (p = {bmi['significance']['p_value']}).",
    ]
    if not c["significance"]["statistically_significant"]:
        bits.append(
            "The total association is itself not distinguishable from zero, so "
            "there is no established total effect for BMI to mediate. The "
            "decomposition is reported because it was pre-specified, but with a "
            "null total effect its parts describe sampling noise as readily as "
            "structure."
        )
    return " ".join(bits)


# ======================================================================
# STEP 6 -- DOSE-RESPONSE
# ======================================================================


def step_dose_response() -> dict:
    """Does ALT climb steadily across sugar quartiles, or scatter?"""
    frame = analysis_frame(["ALT", "TotalSugars", "Age", "Sex"])
    weights = frame["DietWeight"]

    # Quartile edges from the SAMPLE distribution: the protocol's Step 3 divides
    # "participants into four equal-sized groups", and the Revised Results'
    # cut points (62, 92, 141 g/day) are those sample quartiles. Weighted
    # quartiles would make the groups quarters of U.S. adolescents instead,
    # which is a different -- and unequal-sized -- grouping.
    edges = [float(frame["TotalSugars"].quantile(q)) for q in (0.25, 0.50, 0.75)]
    rank = np.digitize(frame["TotalSugars"], edges, right=False)
    frame = frame.assign(SugarQuartile=rank + 1)

    quartiles = []
    for q in sorted(frame["SugarQuartile"].unique()):
        block = frame[frame["SugarQuartile"] == q]
        quartiles.append(
            {
                "quartile": int(q),
                "n": len(block),
                "sugar_range_g": [
                    _num(block["TotalSugars"].min(), 1),
                    _num(block["TotalSugars"].max(), 1),
                ],
                "weighted_mean_sugar_g": _num(
                    _wmean(block["TotalSugars"], block["DietWeight"]), 1
                ),
                # The protocol's figure plots the plain sample mean and its
                # standard error per quartile; the weighted mean beside it is
                # the population estimate.
                "mean_alt": _num(float(block["ALT"].mean()), 3),
                "standard_error_mean_alt": _num(
                    float(block["ALT"].std(ddof=1)) / np.sqrt(len(block)), 3
                ),
                "weighted_mean_alt": _num(_wmean(block["ALT"], block["DietWeight"]), 3),
                # The error bar on the weighted mean. SD / sqrt(n)
                # on the ROW count, not on the summed weight: the weight says
                # how many Americans each adolescent stands for, and dividing by
                # millions would produce an error bar of essentially zero drawn
                # around an estimate from a few hundred people.
                "standard_error_alt": _num(
                    _wstd(block["ALT"], block["DietWeight"]) / np.sqrt(len(block)), 3
                ),
                "weighted_median_alt": _num(
                    _wquantile(block["ALT"], block["DietWeight"], 0.5), 3
                ),
                "percent_elevated_alt": _num(
                    _wmean(block["ALTElevated"].astype(float), block["DietWeight"])
                    * 100,
                    2,
                ),
            }
        )

    import scipy.stats as sp

    # One-way ANOVA across the four quartiles (protocol Step 3). It asks the
    # blunter question the trend model does not -- do the four means differ AT
    # ALL, in any arrangement -- and it is unweighted and assumes independent
    # observations, so it ignores the survey design that the trend model below
    # respects. Reported because the protocol pre-specified it, and read as the
    # cruder of the two.
    groups = [
        block["ALT"].to_numpy(float)
        for _, block in frame.groupby("SugarQuartile", sort=True)
    ]
    f_stat, anova_p = sp.f_oneway(*groups)

    # The clinical version of the same question (protocol Step 7): not "is mean
    # ALT higher" but "are more adolescents over the line". A chi-square on the
    # counts, because a proportion crossing a threshold is what a screening
    # question is actually about, and because the count table is what the test
    # needs -- weighted percentages are reported per quartile above, but a
    # chi-square run on population-scaled counts would claim a sample of
    # millions and return a p-value of zero for any difference at all.
    table = pd.crosstab(frame["SugarQuartile"], frame["ALTElevated"].astype(bool))
    chi2, chi_p = sp.chi2_contingency(table.to_numpy())[:2]

    # The trend test: quartile rank entered as a single ordered predictor, so one
    # coefficient answers "does ALT move monotonically across the groups?" rather
    # than three pairwise comparisons answering nothing in particular.
    trend = fit_model(
        frame,
        "LogALT",
        ["SugarQuartile", *BASE_CONTROLS],
        label="Linear trend across quartiles",
    )
    slope = trend["coefficients"]["SugarQuartile"]

    return {
        "step": 6,
        "protocol_step": [3, 7],
        "title": "Dose-response across sugar quartiles",
        "grade": SUPPORTING,
        "layer": INFERENTIAL,
        "question": "Does ALT rise steadily with sugar intake, or is the pattern flat?",
        "n": len(frame),
        "quartile_edges_g": [_num(e, 1) for e in edges],
        "quartiles": quartiles,
        "anova": {
            "f_statistic": _num(float(f_stat), 3),
            "significance": _report(float(anova_p)),
            "note": (
                "Unweighted; the weighted trend test below is the "
                "survey-weighted counterpart."
            ),
        },
        "elevated_alt_chi_square": {
            "chi_square": _num(float(chi2), 3),
            "degrees_of_freedom": int((table.shape[0] - 1) * (table.shape[1] - 1)),
            "counts_elevated": [int(v) for v in table.get(True, 0 * table.iloc[:, 0])],
            "counts_total": [int(v) for v in table.sum(axis=1)],
            "significance": _report(float(chi_p)),
            "threshold": ALT_THRESHOLD_SOURCE,
            "note": (
                "Run on unweighted counts, which is what the test requires; the "
                "per-quartile percentages above are weighted."
            ),
        },
        "trend_test": {
            "coefficient_per_quartile": slope["estimate"],
            "percent_change_in_alt_per_quartile": _percent_change(slope["estimate"]),
            "significance": slope["significance"],
            "model": _public(trend),
        },
        "interpretation": (
            "ALT rises monotonically across sugar quartiles."
            if slope["significance"]["statistically_significant"]
            and (slope["estimate"] or 0) > 0
            else (
                "No monotonic dose-response: moving up a sugar quartile corresponds "
                f"to a {_percent_change(slope['estimate'])}% difference in ALT "
                f"(p = {slope['significance']['p_value']}). A dose-response curve is "
                "one of the stronger observational arguments for a real effect, and "
                "its absence here is consistent with the null primary result."
            )
        ),
        "clinical_interpretation": (
            f"The share of adolescents above the pediatric ALT threshold "
            f"{'differs' if _is_significant(float(chi_p)) else 'does not differ'} "
            f"across sugar quartiles (chi-square = {_num(float(chi2), 2)}, "
            f"p = {_num(float(chi_p), 4)}), and the four quartile means "
            f"{'differ' if _is_significant(float(anova_p)) else 'do not differ'} "
            f"by one-way ANOVA (F = {_num(float(f_stat), 2)}, "
            f"p = {_num(float(anova_p), 4)})."
        ),
        "not_causal": NOT_CAUSAL,
    }


# ======================================================================
# STEP 7 -- MECHANISM: TRIG/HDL AGAINST SUGAR
# ======================================================================


def _vif(frame: pd.DataFrame, predictors: list[str]) -> dict:
    """Variance inflation factors for one specification, and the protocol's verdict.

    The original proposal pre-registered a rule -- if any VIF is 5 or more,
    replace the collinear pair with the Trig/HDL ratio -- and the revised
    protocol builds the ratio in from the start, so the rule is satisfied by
    construction. The factors are still computed and reported: "we checked"
    and "it could not have happened" are different claims, and a reader (or a
    judge) is entitled to the numbers.
    """
    from statsmodels.stats.outliers_influence import variance_inflation_factor

    matrix = np.column_stack([np.ones(len(frame)), frame[predictors].to_numpy(float)])
    vifs = {
        name: _num(variance_inflation_factor(matrix, i + 1), 3)
        for i, name in enumerate(predictors)
    }
    worst = max(vifs.values())
    return {
        "vif": vifs,
        "max_vif": worst,
        "threshold": VIF_THRESHOLD,
        "rule_triggered": bool(worst >= VIF_THRESHOLD),
        "note": (
            "Pre-specified rule: a VIF at or above "
            f"{VIF_THRESHOLD:g} would have replaced the collinear pair with the "
            "Trig/HDL ratio. Triglycerides and HDL enter as that ratio already, "
            f"and the largest VIF is {worst}, so the rule is not triggered."
        ),
    }


def step_mechanism() -> dict:
    """Put sugar and the Trig/HDL ratio in one model and compare their betas."""
    # The protocol's secondary mechanism hypothesis is a comparison BETWEEN two
    # predictors, so it has to be read off a model that contains both. That
    # model is the primary one -- Model B with BMI -- rather than a separate fit,
    # so the ratio's coefficient quoted here is the same number the primary step
    # reports and cannot drift from it.
    frame = analysis_frame(MODEL_B_COLUMNS)
    model = fit_model(frame, "LogALT", MODEL_B_WITH_BMI, label=MODEL_LABELS["B_BMI"])

    ranked = sorted(
        (
            {
                "predictor": name,
                "standardized_beta": info["standardized_beta"],
                "magnitude": _magnitude(
                    abs(info["standardized_beta"] or 0), 0.1, 0.3, 0.5
                ),
                "significance": info["significance"],
            }
            for name, info in model["coefficients"].items()
            if name != "const"
        ),
        key=lambda row: abs(row["standardized_beta"] or 0),
        reverse=True,
    )

    sugar = model["coefficients"]["Sugar10g"]
    ratio = model["coefficients"]["TrigHDLRatio"]
    ratio_wins = abs(ratio["standardized_beta"] or 0) > abs(
        sugar["standardized_beta"] or 0
    )
    vif = _vif(frame, MODEL_B_WITH_BMI)

    return {
        "step": 7,
        "protocol_step": 6,
        "title": "Mechanism -- triglyceride/HDL ratio versus dietary sugar",
        "grade": SUPPORTING,
        "layer": PREDICTIVE,
        "question": (
            "Is the downstream lipid marker a stronger predictor of ALT than the "
            "dietary intake upstream of it?"
        ),
        "n": len(frame),
        "model": _public(model),
        "ranked_by_standardized_beta": ranked,
        "hypothesis_supported": bool(ratio_wins),
        "multicollinearity": vif,
        "interpretation": (
            f"The Trig/HDL ratio carries a standardized beta of "
            f"{ratio['standardized_beta']} against sugar's {sugar['standardized_beta']}, so "
            f"the downstream marker {'is' if ratio_wins else 'is not'} the stronger "
            "predictor. Standardized betas are comparable across predictors "
            "measured in different units; the raw coefficients are not."
        ),
        "note": (
            "Both are measured at the same visit, so 'downstream' is the protocol's "
            "physiological reasoning, not something these data establish."
        ),
        "not_causal": NOT_CAUSAL,
    }


# ======================================================================
# STEP 8 -- INCREMENTAL VALUE OF THE BLOOD MARKERS
# ======================================================================


def step_incremental_value() -> dict:
    """Does adding Trig/HDL and HbA1c to a lifestyle-only model explain more?"""
    # One frame for the compared models. This is the whole point: R-squared
    # compared across two different samples is not a comparison, and Model B
    # exists only for the fasting subsample. Model A is ALSO fitted on the full
    # cohort -- that is the lifestyle model the protocol's Step 4 describes and
    # the Revised Results table reports (n = 695) -- but its R-squared there is
    # not the one the comparison uses.
    frame = analysis_frame(MODEL_B_COLUMNS)
    full = analysis_frame(["ALT", "TotalSugars", "ScreenTime", "Age", "Sex"])

    lifestyle_full = fit_model(full, "LogALT", MODEL_A, label=MODEL_LABELS["A"])
    lifestyle = fit_model(frame, "LogALT", MODEL_A, label=MODEL_LABELS["A"])
    combined = fit_model(frame, "LogALT", MODEL_B, label=MODEL_LABELS["B"])
    combined_bmi = fit_model(
        frame, "LogALT", MODEL_B_WITH_BMI, label=MODEL_LABELS["B_BMI"]
    )

    added = ["TrigHDLRatio", "HbA1c"]
    # A joint test that BOTH added coefficients are zero, run against the same
    # covariance the model was fitted with. Testing them one at a
    # time would answer a different question and would need a multiplicity
    # correction to answer it honestly.
    joint = combined["_model"].f_test([f"{name} = 0" for name in added])
    joint_p = float(np.ravel(joint.pvalue)[0])

    delta = None
    if None not in (combined["r_squared"], lifestyle["r_squared"]):
        delta = _num(combined["r_squared"] - lifestyle["r_squared"], 4)
    delta_bmi = None
    if None not in (combined_bmi["r_squared"], lifestyle["r_squared"]):
        delta_bmi = _num(combined_bmi["r_squared"] - lifestyle["r_squared"], 4)

    return {
        "step": 8,
        "protocol_step": 4,
        "title": "Model A versus Model B -- incremental value of the metabolic markers",
        "grade": SUPPORTING,
        "layer": PREDICTIVE,
        "question": (
            "Do Trig/HDL and HbA1c explain variation in ALT that diet and screen "
            "time alone do not?"
        ),
        "n": len(frame),
        "shared_sample_note": (
            f"The compared models are fitted on the same {len(frame)} adolescents -- "
            "the fasting subsample, the only people with a Trig/HDL ratio -- so the "
            "change in R-squared reflects the added predictors and not a change of "
            f"sample. Model A on its own full sample (n = {len(full)}) is reported "
            "beside them for the coefficients; its R-squared there is not comparable "
            "to Model B's."
        ),
        "lifestyle_model_full_sample": _public(lifestyle_full),
        "lifestyle_model": _public(lifestyle),
        "combined_model": _public(combined),
        "combined_model_with_bmi": _public(combined_bmi),
        "added_predictors": added,
        "delta_r_squared": delta,
        "delta_r_squared_with_bmi": delta_bmi,
        "joint_test": _report(joint_p),
        "interpretation": (
            f"Adding {' and '.join(added)} moves R-squared from "
            f"{lifestyle['r_squared']} to {combined['r_squared']} (change {delta}), "
            f"and to {combined_bmi['r_squared']} once BMI is added (change {delta_bmi}); "
            f"the joint test of both coefficients gives p = {_num(joint_p, 4)}, so the "
            f"pair {'does' if _is_significant(joint_p) else 'does not'} add "
            "detectable predictive value over lifestyle measures alone."
        ),
        "not_causal": NOT_CAUSAL,
    }


# ======================================================================
# STEP 9 -- SEX DIFFERENCES
# ======================================================================


def step_sex_differences() -> dict:
    """Fit the model separately by sex, and test the interaction directly."""
    frame = analysis_frame(MODEL_B_COLUMNS)

    # The protocol re-runs Model B with BMI separately by sex. Within a stratum
    # everyone shares a sex, so the Male indicator is dropped -- a constant
    # column is collinear with the intercept and carries no information -- and
    # the rest of the specification is left exactly as the pooled model has it.
    stratified_spec = [name for name in MODEL_B_WITH_BMI if name != "Male"]

    strata = {}
    for sex in ("Male", "Female"):
        block = frame[frame["Sex"] == sex]
        strata[sex] = _public(
            fit_model(block, "LogALT", stratified_spec, label=f"{sex}s only")
        )

    # The interaction test is the one that actually answers the question. Two
    # separate models can differ -- one significant, one not -- purely because
    # they have different sample sizes; only a term crossing the predictor with
    # sex tests whether the slopes themselves differ.
    interaction = frame.assign(
        SugarXMale=frame["Sugar10g"] * frame["Male"],
        RatioXMale=frame["TrigHDLRatio"] * frame["Male"],
    )
    pooled = fit_model(
        interaction,
        "LogALT",
        [*MODEL_B_WITH_BMI, "SugarXMale", "RatioXMale"],
        label="Pooled with sex interactions",
    )

    tests = {
        name: pooled["coefficients"][name]["significance"]
        for name in ("SugarXMale", "RatioXMale")
    }
    any_interaction = any(t["statistically_significant"] for t in tests.values())

    male_alt = _wmean(
        frame.loc[frame["Sex"] == "Male", "ALT"],
        frame.loc[frame["Sex"] == "Male", "DietWeight"],
    )
    female_alt = _wmean(
        frame.loc[frame["Sex"] == "Female", "ALT"],
        frame.loc[frame["Sex"] == "Female", "DietWeight"],
    )
    sex_main = pooled["coefficients"]["Male"]["significance"]

    return {
        "step": 9,
        "protocol_step": 8,
        "title": "Sex differences",
        "stratified_specification": stratified_spec,
        "grade": EXPLORATORY,
        "layer": PREDICTIVE,
        "question": "Do these associations differ between adolescent males and females?",
        "n": len(frame),
        "stratified_models": strata,
        "interaction_model": _public(pooled),
        "interaction_tests": tests,
        "slopes_differ_by_sex": bool(any_interaction),
        "weighted_mean_alt": {
            "male": _num(male_alt, 3),
            "female": _num(female_alt, 3),
            "difference": _num(male_alt - female_alt, 3),
        },
        "sex_as_main_effect": sex_main,
        "interpretation": (
            "Sex is a substantial predictor of ALT level"
            f" ({'significant' if sex_main['statistically_significant'] else 'not significant'}"
            f" as a main effect, weighted mean {_num(male_alt, 1)} U/L in males vs "
            f"{_num(female_alt, 1)} U/L in females), {'and' if any_interaction else 'but'} "
            f"the sugar and Trig/HDL slopes {'do' if any_interaction else 'do not'} differ detectably "
            "between sexes. A predictor shifting everyone's level and a predictor "
            "changing another predictor's slope are different claims, and only the "
            "interaction terms test the second."
        ),
        "multiplicity": (
            "Exploratory and uncorrected. Two interaction terms are tested here; "
            "at alpha = 0.05 the chance of at least one false positive across them "
            "is about 10% if both nulls are true."
        ),
        "not_causal": NOT_CAUSAL,
    }


# ======================================================================
# STEP 10 -- THE COMPOSITE RISK SCORE
# ======================================================================


def step_risk_score() -> dict:
    """Does the 0-6 count separate adolescents by ALT better than one factor?"""

    # Scored on the whole cohort so each cut point is the full sample's median
    # (see cohort.risk_score); only the fasting subsample can then be scored,
    # because only it has the Trig/HDL component.
    scored = risk_score(load_cohort())
    frame = analysis_frame(
        ["ALT", "TotalSugars", "ScreenTime", "BMI", "TrigHDLRatio", "HbA1c", "Sex"]
    )
    frame = frame.assign(RiskScore=scored["score"]).dropna(subset=["RiskScore"])

    bands = []
    for score in sorted(frame["RiskScore"].unique()):
        block = frame[frame["RiskScore"] == score]
        bands.append(
            {
                "score": int(score),
                "n": len(block),
                # The protocol's figure plots the plain sample mean and share
                # per band; the weighted versions beside them are the
                # population estimates.
                "mean_alt": _num(float(block["ALT"].mean()), 3),
                "percent_elevated_alt_unweighted": _num(
                    float(block["ALTElevated"].astype(float).mean()) * 100, 2
                ),
                "weighted_mean_alt": _num(_wmean(block["ALT"], block["DietWeight"]), 3),
                "percent_elevated_alt": _num(
                    _wmean(block["ALTElevated"].astype(float), block["DietWeight"])
                    * 100,
                    2,
                ),
                "count_elevated": int(block["ALTElevated"].sum()),
            }
        )

    trend = fit_model(
        frame, "LogALT", ["RiskScore", "Age"], label="log(ALT) across risk score"
    )
    slope = trend["coefficients"]["RiskScore"]

    # The protocol's Step 9 asks for an ORDINARY least-squares slope on mean
    # ALT -- "U/L per point", unweighted -- which is the number a reader can put
    # next to the bar chart and the one the Revised Results report. The
    # weighted log model above is the one that respects ALT's skew and the
    # survey design, so both are reported: the raw slope for interpretation,
    # the log slope as the design-aware test.
    import statsmodels.api as sm

    raw_trend = sm.OLS(
        frame["ALT"].astype(float),
        sm.add_constant(frame["RiskScore"].astype(float)),
    ).fit()
    raw_slope = {
        "estimate": _num(float(raw_trend.params["RiskScore"]), 5),
        "significance": _report(float(raw_trend.pvalues["RiskScore"])),
    }

    # Cochran-Armitage for the prevalence trend: the means test above says
    # nothing about whether the proportion CROSSING the clinical line rises, and
    # that proportion is what a screening score would actually be used for.
    table = (
        frame.groupby("RiskScore")["ALTElevated"]
        .agg(["sum", "count"])
        .rename(columns={"sum": "elevated"})
    )
    scores = table.index.to_numpy(float)
    elevated = table["elevated"].to_numpy(float)
    totals = table["count"].to_numpy(float)
    armitage = _cochran_armitage(scores, elevated, totals)

    # Every score band is a comparison against the single strongest single
    # factor, which is what "better than any one factor alone" has to mean.
    single = {}
    for name in ("TrigHDLRatio", "BMI", "TotalSugars"):
        model = fit_model(frame, "LogALT", [name, "Age"], label=f"{name} alone")
        single[name] = model["r_squared"]
    single["RiskScore"] = trend["r_squared"]

    sparse = [band for band in bands if band["n"] < 20]

    return {
        "step": 10,
        "protocol_step": 9,
        "title": "Composite 0-6 risk score",
        "grade": EXPLORATORY,
        "layer": PREDICTIVE,
        "question": (
            "Does a count of six risk factors separate adolescents by ALT better "
            "than any single factor?"
        ),
        "n": len(frame),
        "components": {
            "median_split": list(scored["cutpoints"]),
            "cutpoints": {k: _num(v, 3) for k, v in scored["cutpoints"].items()},
            "male_sex": "1 point",
            "rule": (
                "One point per component: above this cohort's median on each of "
                "the five continuous factors, plus one for male sex."
            ),
        },
        "bands": bands,
        "trend_in_mean_alt": {
            "coefficient_per_point": slope["estimate"],
            "percent_change_per_point": _percent_change(slope["estimate"]),
            "significance": slope["significance"],
            "u_per_litre_per_point": raw_slope["estimate"],
            "u_per_litre_significance": raw_slope["significance"],
            "raw_scale_model": {
                "label": "mean ALT across risk score (ordinary least squares, unweighted)",
                "outcome": "ALT",
                "predictors": ["RiskScore"],
                "n": int(raw_trend.nobs),
                "r_squared": _num(float(raw_trend.rsquared), 4),
                "estimator": "OLS, unweighted, as the protocol's Step 9 specifies",
            },
        },
        "trend_in_prevalence": armitage,
        "r_squared_vs_single_factors": single,
        "sparse_bands": (
            [
                f"score {band['score']} has only {band['n']} adolescents"
                for band in sparse
            ]
            or None
        ),
        "interpretation": (
            f"Mean ALT changes {_percent_change(slope['estimate'])}% -- about "
            f"{raw_slope['estimate']} U/L -- per additional "
            f"risk point (p = {slope['significance']['p_value']}), and the share above "
            f"the clinical threshold trends with the score at p = "
            f"{armitage['significance']['p_value']}."
        ),
        "caveat": (
            "Exploratory, and RELATIVE rather than portable: five of the six "
            "components are cut at this cohort's own median, so the score ranks "
            "these adolescents against each other and its thresholds would move in "
            "another population. It is also evaluated on the same data that defined "
            "its cut points, which flatters it -- a real screening instrument needs "
            "validation in a separate sample."
        ),
        "not_causal": NOT_CAUSAL,
    }


def _cochran_armitage(scores, elevated, totals) -> dict:
    """Cochran-Armitage test for a linear trend in a proportion across ordered groups.

    Chi-square would only say the proportions differ SOMEHOW; this asks the
    sharper question the score is built around -- does the proportion climb in
    step with it? Written out here because scipy has no implementation, and it is
    a short one: regress the counts on the scores and compare the observed slope
    against its variance under the null of no trend.
    """
    import scipy.stats as sp

    n = totals.sum()
    if n <= 0 or len(scores) < 3:
        return {"applicable": False, "reason": "needs at least three ordered groups"}

    p = elevated.sum() / n
    mean_score = float((totals * scores).sum() / n)
    numerator = float((elevated * (scores - mean_score)).sum())
    variance = float(p * (1 - p) * (totals * (scores - mean_score) ** 2).sum())
    if variance <= 0:
        return {"applicable": False, "reason": "no variation in outcome or scores"}

    z = numerator / np.sqrt(variance)
    p_value = float(2 * sp.norm.sf(abs(z)))
    return {
        "applicable": True,
        "test": "Cochran-Armitage trend test",
        "z": _num(z, 3),
        "direction": "increasing" if z > 0 else "decreasing",
        "significance": _report(p_value),
        "note": (
            "Unweighted: the test works on counts, so it describes this sample "
            "rather than the U.S. adolescent population. The weighted "
            "percentages in each band are the population estimate."
        ),
    }


# ======================================================================
# SENSITIVITY -- does the primary answer depend on how it was measured?
# ======================================================================


def sensitivity_checks() -> dict:
    """Re-run the primary model under the choices that could have driven it.

    A null result is only worth reporting if it survives the arbitrary decisions
    made on the way to it. Each check below changes exactly one of those and
    refits; if the answer flips, that is a finding about the method, not the
    liver.
    """
    checks = []

    # 1. Two-day average sugar instead of day 1. Trades measurement error for
    #    sample size: averaging two recalls estimates usual intake better than
    #    one, but only the subset who completed both can be used.
    two_day = analysis_frame(["ALT", "TotalSugars2Day", "Age", "Sex", "BMI"])
    two_day = two_day.assign(Sugar10g=two_day["TotalSugars2Day"] / SUGAR_UNIT)
    model = fit_model(two_day, "LogALT", ["Sugar10g", *BASE_CONTROLS, "BMI"])
    checks.append(
        {
            "check": "Two-day average sugar (DR1 + DR2) instead of day 1",
            "why": "Averages out day-to-day variation, at the cost of the participants who gave only one recall.",
            "n": model["n"],
            "sugar_coefficient": model["coefficients"]["Sugar10g"]["estimate"],
            "significance": model["coefficients"]["Sugar10g"]["significance"],
        }
    )

    # 2. Unweighted OLS. Isolates how much the survey weights are doing.
    base = analysis_frame(["ALT", "TotalSugars", "Age", "Sex", "BMI"])
    unweighted = base.assign(DietWeight=1.0)
    model = fit_model(unweighted, "LogALT", ["Sugar10g", *BASE_CONTROLS, "BMI"])
    checks.append(
        {
            "check": "Unweighted (every participant counted once)",
            "why": "Shows whether the survey weights, not the data, drive the result.",
            "n": model["n"],
            "sugar_coefficient": model["coefficients"]["Sugar10g"]["estimate"],
            "significance": model["coefficients"]["Sugar10g"]["significance"],
        }
    )

    # 3. Raw ALT instead of log. Confirms the transformation is not what
    #    produced the answer.
    model = fit_model(base, "ALT", ["Sugar10g", *BASE_CONTROLS, "BMI"])
    checks.append(
        {
            "check": "Raw ALT in U/L instead of ln(ALT)",
            "why": "Confirms the log transformation is not what produced the result.",
            "n": model["n"],
            "sugar_coefficient": model["coefficients"]["Sugar10g"]["estimate"],
            "significance": model["coefficients"]["Sugar10g"]["significance"],
        }
    )

    # 4. Energy-adjusted sugar. Sugar and total calories move together, so a
    #    sugar coefficient may just be reading "eats more of everything".
    energy = analysis_frame(["ALT", "TotalSugars", "Energy", "Age", "Sex", "BMI"])
    model = fit_model(energy, "LogALT", ["Sugar10g", "Energy", *BASE_CONTROLS, "BMI"])
    checks.append(
        {
            "check": "Adjusted for total energy intake",
            "why": "Separates sugar specifically from simply eating more of everything.",
            "n": model["n"],
            "sugar_coefficient": model["coefficients"]["Sugar10g"]["estimate"],
            "significance": model["coefficients"]["Sugar10g"]["significance"],
        }
    )

    significant = [c for c in checks if c["significance"]["statistically_significant"]]
    return {
        "title": "Sensitivity checks on the primary result",
        "grade": SUPPORTING,
        "layer": PREDICTIVE,
        "question": "Does the primary answer depend on a choice made along the way?",
        "checks": checks,
        "any_check_significant": bool(significant),
        "interpretation": (
            "The primary result holds under every variation tried: none of the four "
            "refits makes sugar a significant independent predictor of ALT."
            if not significant
            else "At least one variation changes the answer -- see which, above; a "
            "result that depends on the measurement choice needs that choice "
            "justified before it is reported as a finding."
        ),
    }


# ======================================================================
# MODEL DIAGNOSTICS -- the pictures behind the regression's assumptions
# ======================================================================

# Every coefficient the study reports rests on two assumptions that no
# coefficient can show you: that the residuals are roughly normal, and that
# their spread does not grow with the fitted value. expert_analysis()'s
# residual_checks already TESTS both and returns numbers. What it cannot do is
# show the reader the shape -- a Q-Q plot that bends only in the last two points
# and one that bows through its whole range give similar test statistics and
# mean completely different things. So this returns the geometry, and the
# Figures page draws it.
#
# The three specifications a reader can ask about are the three the protocol
# actually fits. They are looked up here rather than passed in as a formula:
# a diagnostic plot of a model the study never ran would be a picture of
# nothing, and letting the URL name arbitrary predictors would make this an
# open-ended regression service rather than a view onto the protocol.
DIAGNOSTIC_MODELS = {
    "lifestyle": (MODEL_A, MODEL_LABELS["A"]),
    "total-effect": (MODEL_B, MODEL_LABELS["B"]),
    "direct-effect": (MODEL_B_WITH_BMI, MODEL_LABELS["B_BMI"]),
}


def model_diagnostics(name: str) -> dict:
    """Fitted values, residuals and normal-quantile pairs for one study model.

    Returns parallel arrays rather than rows, matching the convention the
    figures API already uses for the scatter: the same numbers with half the
    JSON punctuation. Nothing here is sampled -- the analytic samples are 314
    and 695 rows, which is a payload of a few tens of kilobytes and the whole
    point of a diagnostic plot is that no observation was hidden from you.
    """
    import scipy.stats as sp

    if name not in DIAGNOSTIC_MODELS:
        return {"error": f"Unknown model: {name!r}"}

    predictors, label = DIAGNOSTIC_MODELS[name]
    frame = analysis_frame(MODEL_B_COLUMNS)
    fit = fit_model(frame, "LogALT", predictors, label=label)
    result = fit["_model"]

    fitted = np.asarray(result.fittedvalues, dtype=float)
    residuals = np.asarray(result.resid, dtype=float)
    spread = float(residuals.std(ddof=1))
    standardized = residuals / spread if spread > 0 else residuals

    # Blom's plotting positions, (i - 3/8) / (n + 1/4). The choice matters only
    # in the tails, which is exactly where a Q-Q plot is read, and Blom is the
    # convention statsmodels and R both default to for a normal probability plot.
    count = standardized.size
    order = np.argsort(standardized)
    ranks = np.arange(1, count + 1)
    theoretical = sp.norm.ppf((ranks - 0.375) / (count + 0.25))
    observed = standardized[order]

    # The reference line is drawn through the first and third quartiles, not as
    # the identity: it is the line the points would follow if they were normal
    # with THIS sample's center and spread, which is the comparison a reader
    # wants. An identity line would also flag a simple scale difference as
    # non-normality.
    q_theory = np.asarray(sp.norm.ppf([0.25, 0.75]), dtype=float)
    q_observed = np.asarray(np.percentile(observed, [25, 75]), dtype=float)
    slope = (q_observed[1] - q_observed[0]) / (q_theory[1] - q_theory[0])
    intercept = q_observed[0] - slope * q_theory[0]

    return {
        "model": name,
        "label": label,
        "outcome": "LogALT",
        "predictors": predictors,
        "n": int(count),
        "r_squared": fit["r_squared"],
        "residual_sd": _num(spread, 5),
        "residual_skewness": _num(float(sp.skew(residuals)), 3),
        "residual_kurtosis": _num(float(sp.kurtosis(residuals)), 3),
        "fitted": [_num(v, 4) for v in fitted],
        "residuals": [_num(v, 4) for v in residuals],
        "fitted_min": _num(float(fitted.min()), 4),
        "fitted_max": _num(float(fitted.max()), 4),
        "residual_min": _num(float(residuals.min()), 4),
        "residual_max": _num(float(residuals.max()), 4),
        "qq_theoretical": [_num(v, 4) for v in theoretical],
        "qq_observed": [_num(v, 4) for v in observed],
        "qq_line": {
            "slope": _num(float(slope), 5),
            "intercept": _num(float(intercept), 5),
        },
        "note": (
            "Residuals from the weighted fit. The formal tests of the same two "
            "assumptions -- normality and constant variance -- are in the expert "
            "tier's residual_checks; these are the shapes behind them."
        ),
        "not_causal": NOT_CAUSAL,
    }


# ======================================================================
# THE WHOLE STUDY
# ======================================================================

STEPS = (
    step_cohort,
    step_profile,
    step_outcome_distribution,
    step_total_effect,
    step_direct_effect,
    step_dose_response,
    step_mechanism,
    step_incremental_value,
    step_sex_differences,
    step_risk_score,
)

STEP_NAMES = {
    "cohort": step_cohort,
    "profile": step_profile,
    "distribution": step_outcome_distribution,
    "total-effect": step_total_effect,
    "direct-effect": step_direct_effect,
    "dose-response": step_dose_response,
    "mechanism": step_mechanism,
    "incremental": step_incremental_value,
    "sex": step_sex_differences,
    "risk-score": step_risk_score,
    "sensitivity": sensitivity_checks,
}


@lru_cache(maxsize=None)
def run_step(name: str) -> dict:
    """One step by name, memoized. The cohort never changes while the process
    runs, so every step is a pure function of its name."""
    step = STEP_NAMES.get(name)
    if step is None:
        return {"error": f"Unknown step: {name!r}"}
    return step()


@lru_cache(maxsize=1)
def run_study() -> dict:
    """Every step, in protocol order, plus the sensitivity checks."""
    return {
        "title": (
            "Sex and metabolic factors, not dietary sugar, predict early-stage "
            "liver stress in U.S. adolescents"
        ),
        "dataset": "NHANES 2017-2018, adolescents aged 12-17",
        "alpha": ALPHA,
        "protocol": (
            "Revised Methods, sections 3-6. Each step below carries the "
            "protocol_step it implements."
        ),
        "hierarchy": {
            "primary": (
                "The sugar coefficient in Model B with BMI (step 5) -- the single "
                "pre-specified test the central hypothesis rises or falls on. Step 4 "
                "is the same model without BMI, reported alongside it."
            ),
            "supporting": (
                "Pre-specified analyses giving the primary result context: the "
                "quartile dose-response and its chi-square (step 6), the mechanism "
                "comparison (step 7), and Model A versus Model B (step 8). Read at "
                "the standard 0.05 threshold."
            ),
            "exploratory": (
                "Hypothesis-generating, uncorrected for multiplicity, and explicitly "
                "not able to rescue a null primary result: the sex-stratified models "
                "(step 9) and the composite risk score (step 10)."
            ),
        },
        "design": SURVEY_DESIGN_CAVEAT,
        "steps": [step() for step in STEPS],
        "sensitivity": sensitivity_checks(),
        "not_causal": NOT_CAUSAL,
    }


@lru_cache(maxsize=1)
def headline() -> dict:
    """The three numbers the study turns on, for the site's summary card."""
    direct = run_step("direct-effect")
    mechanism = run_step("mechanism")
    sex = run_step("sex")
    sugar = direct["direct_model"]["coefficients"]["Sugar10g"]
    ratio = mechanism["model"]["coefficients"]["TrigHDLRatio"]

    return {
        "n": direct["n"],
        "primary_finding": (
            "Dietary sugar does not independently predict ALT once BMI is "
            "accounted for."
            if not sugar["significance"]["statistically_significant"]
            else "Dietary sugar independently predicts ALT after BMI adjustment."
        ),
        "sugar_p": sugar["significance"]["p_value"],
        "trig_hdl_beta": ratio["standardized_beta"],
        "trig_hdl_p": ratio["significance"]["p_value"],
        "sex_difference_in_alt": sex["weighted_mean_alt"],
        "elevated_alt_percent": run_step("profile")["elevated_alt"]["percent_weighted"],
        "not_causal": NOT_CAUSAL,
    }
