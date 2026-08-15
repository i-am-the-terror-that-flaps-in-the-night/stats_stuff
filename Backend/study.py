"""
study.py -- the ten-step analysis the project's research protocol specifies.

WHAT THIS IS, AND WHY IT IS NOT IN engine.py
    engine.py is a general-purpose statistics engine: hand it any spreadsheet and
    any column and it will describe it. It knows nothing about livers. Its tiers
    are deliberately question-agnostic, and that is what makes them reusable.

    This module is the opposite. It answers ONE set of pre-specified questions
    about ONE cohort, in a fixed order, with the roles of every variable decided
    in advance: ALT is the outcome, dietary sugar is the exposure, BMI is the
    mediator, sex and age are controls. That is a study protocol, not a feature
    of a spreadsheet, so it lives in its own module and calls the engine's shared
    helpers rather than growing a new tier inside DataAnalyzer.

    The separation also protects the honest part of the engine's design. Because
    the roles here are fixed and declared up front, this module may legitimately
    do things engine.py refuses to do on an arbitrary column -- apply a
    sex-specific clinical threshold, decompose an association into direct and
    mediated parts -- precisely because the protocol committed to them before
    seeing the results.

THE ANALYTICAL HIERARCHY IS PRE-SPECIFIED
    The protocol distinguishes three grades of claim, and every step below is
    tagged with which one it is:

        primary     the hypothesis the study was designed to test. One question,
                    asked over two steps: the association before body mass is
                    accounted for (step 4) and after it (step 5).
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
      * Ignoring the CLUSTERING makes the standard errors too small, because two
        adolescents from the same sampled location are more alike than two
        strangers, and treating them as independent invents information. Every
        model here uses cluster-robust standard errors grouped by PSU within
        stratum.

    The honest caveat: this cohort spans 15 strata x 2 PSUs = 30 clusters. That
    is enough for cluster-robust inference to be worth doing and few enough that
    its p-values are approximate -- the asymptotics assume many clusters. It is a
    real improvement over pretending the design is not there, not a substitute
    for a full Taylor-series survey package. See SURVEY_DESIGN_CAVEAT.

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

import numpy as np
import pandas as pd

try:
    from cohort import (
        ALT_ELEVATED,
        ALT_THRESHOLD_SOURCE,
        COHORT_CSV,
        COHORT_N_NOTE,
        build_cohort,
        risk_score,
    )
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
except ModuleNotFoundError:  # imported as a package (uvicorn main:app)
    from Backend.cohort import (
        ALT_ELEVATED,
        ALT_THRESHOLD_SOURCE,
        COHORT_CSV,
        COHORT_N_NOTE,
        build_cohort,
        risk_score,
    )
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

PRIMARY = "primary"
SUPPORTING = "supporting"
EXPLORATORY = "exploratory"

# The smallest p-value this module will print as a number. engine.py rounds
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
    "describe U.S. adolescents rather than this sample, and standard errors are "
    "cluster-robust by PSU within stratum so clustered sampling does not inflate "
    "apparent precision. With 30 clusters the robust p-values are approximate: "
    "cluster-robust inference is asymptotic in the number of clusters, and 30 is "
    "modest. Read them as well-calibrated to the design's shape, not as exact."
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


# ======================================================================
# THE COHORT
# ======================================================================


@lru_cache(maxsize=1)
def load_cohort() -> pd.DataFrame:
    """The analytic cohort, read once and reused.

    Reads the committed, derived CSV -- not the 17 MB raw merge, which lives in
    Git LFS and is absent in production by design (see cohort.py). If the
    derived file is missing, fall back to deriving it in memory so a developer
    who has the raw file but has not run the build still gets a working app.
    """
    if COHORT_CSV.is_file():
        frame = pd.read_csv(COHORT_CSV)
    else:
        frame, _ = build_cohort()
    return frame


@lru_cache(maxsize=1)
def cohort_attrition() -> list[dict]:
    """The attrition log. Rebuilt from the raw merge when it is available;
    otherwise reconstructed from what the committed cohort can attest to.

    The reconstruction is honest about being one: it reports the final n and
    says the intermediate counts need the raw file, rather than hard-coding
    numbers that would silently go stale the moment the derivation changed.
    """
    # Local import, and dual-path like every other cross-module import here:
    # launched from the repo root (`uvicorn main:app`, which is what Render
    # runs) there is no bare `cohort` module on the path.
    try:
        from cohort import RAW_CSV
    except ModuleNotFoundError:
        from Backend.cohort import RAW_CSV

    if RAW_CSV.is_file():
        _, log = build_cohort()
        return log
    return [
        {
            "step": "Analytic cohort",
            "rule": "derived by cohort.py from the NHANES 2017-2018 merge",
            "n": len(load_cohort()),
            "removed": None,
            "note": "Per-step counts require Data/nhanes_analytic.csv (Git LFS).",
        }
    ]


def analysis_frame(columns, *, cohort=None) -> pd.DataFrame:
    """Complete cases on exactly the columns an analysis touches, plus design.

    Every model in this module starts here, and it takes the column list rather
    than assuming a fixed sample, because the samples genuinely differ: the
    screen-time models run on 586 adolescents and the rest on 699. Building the
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
    """Weighted quantile, by linear interpolation on the weighted CDF."""
    values, weights = np.asarray(values, float), np.asarray(weights, float)
    ok = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if not ok.any():
        return float("nan")
    values, weights = values[ok], weights[ok]
    order = np.argsort(values)
    values, weights = values[order], weights[order]
    cdf = (np.cumsum(weights) - 0.5 * weights) / np.sum(weights)
    return float(np.interp(q, cdf, values))


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
    """Weighted least squares with cluster-robust standard errors.

    Returns a dict describing the fit -- coefficients with robust standard
    errors, confidence intervals, standardized betas, R-squared and n -- plus
    the statsmodels result object under "_model" for callers that need to run a
    joint test on it (incremental_value does).

    WLS, not OLS, because the survey weight makes the sample represent the
    population. Cluster-robust, not classical, because the design is clustered.
    Together these are the "weighted least squares regression" the protocol
    calls for, with the variance estimator the design requires.
    """
    import statsmodels.api as sm

    design = sm.add_constant(frame[predictors].astype(float), has_constant="add")
    model = sm.WLS(frame[outcome].astype(float), design, weights=frame["DietWeight"])
    result = model.fit(
        cov_type="cluster", cov_kwds={"groups": _clusters(frame)}, use_t=True
    )

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
        "estimator": "WLS (WTDRD1) with cluster-robust SEs by PSU within stratum",
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
        "title": "Cohort derivation and attrition",
        "grade": SUPPORTING,
        "layer": DESCRIPTIVE,
        "question": "Which adolescents does this study describe, and what removed the rest?",
        "attrition": cohort_attrition(),
        "n": len(frame),
        "n_note": COHORT_N_NOTE,
        "screen_time_n": int(frame["ScreenTime"].notna().sum()),
        "screen_time_note": (
            "Screen time is missing for "
            f"{int(frame['ScreenTime'].isna().sum())} otherwise-eligible adolescents, so "
            "it is not an entry criterion. Analyses that use it run on the "
            "smaller sample and report it."
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
    """Check ALT's shape and justify modelling it on the log scale."""
    import scipy.stats as sp

    frame = analysis_frame(["ALT"])
    raw, logged = frame["ALT"], frame["LogALT"]

    def shape(values, name):
        return {
            "scale": name,
            "skewness": _num(float(sp.skew(values)), 3),
            "kurtosis_excess": _num(float(sp.kurtosis(values)), 3),
            # Shapiro-Wilk tests departure from normality. On n=699 it detects
            # departures far too small to matter for a regression, so it is
            # reported for completeness and the skewness is what the decision
            # actually rests on.
            "shapiro_p": _num(float(sp.shapiro(values).pvalue), 6),
        }

    raw_shape, log_shape = shape(raw, "ALT (U/L)"), shape(logged, "ln(ALT)")
    improved = abs(log_shape["skewness"] or 0) < abs(raw_shape["skewness"] or 0)

    return {
        "step": 3,
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


def step_total_effect() -> dict:
    """Sugar and ALT, controlling only for age and sex -- the total association."""
    frame = analysis_frame(["ALT", "TotalSugars", "Age", "Sex"])
    model = fit_model(
        frame, "LogALT", ["Sugar10g", *BASE_CONTROLS], label="Total (BMI excluded)"
    )
    sugar = model["coefficients"]["Sugar10g"]

    return {
        "step": 4,
        "title": "Primary model A -- total association of sugar with ALT",
        "grade": PRIMARY,
        "layer": PREDICTIVE,
        "question": (
            "Does daily dietary sugar predict ALT in adolescents, before "
            "accounting for body mass?"
        ),
        "n": len(frame),
        "model": _public(model),
        "sugar_per_10g": {
            "coefficient": sugar["estimate"],
            "percent_change_in_alt": _percent_change(sugar["estimate"]),
            "units": SUGAR_UNIT_LABEL,
            "significance": sugar["significance"],
        },
        "interpretation": _sugar_verdict(sugar, "with age and sex controlled"),
        "note": LOG_TRANSFORM_NOTE,
        "not_causal": NOT_CAUSAL,
    }


def step_direct_effect() -> dict:
    """The same model with BMI added, and the two compared -- the mediation step."""
    frame = analysis_frame(["ALT", "TotalSugars", "Age", "Sex", "BMI"])

    total = fit_model(frame, "LogALT", ["Sugar10g", *BASE_CONTROLS], label="Total")
    direct = fit_model(
        frame,
        "LogALT",
        ["Sugar10g", *BASE_CONTROLS, "BMI"],
        label="Direct (BMI adjusted)",
    )

    c = total["coefficients"]["Sugar10g"]["estimate"]
    c_prime = direct["coefficients"]["Sugar10g"]["estimate"]

    # The two paths the indirect route is built from: sugar -> BMI, then
    # BMI -> ALT with sugar held constant.
    a_model = fit_model(
        frame, "BMI", ["Sugar10g", *BASE_CONTROLS], label="Sugar -> BMI"
    )
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
        "title": "Primary model B -- sugar adjusted for BMI, and the mediation comparison",
        "grade": PRIMARY,
        "layer": PREDICTIVE,
        "question": (
            "Does sugar's association with ALT survive adjustment for BMI, and how "
            "much of it travels through body mass?"
        ),
        "n": len(frame),
        "total_model": _public(total),
        "direct_model": _public(direct),
        "path_a_sugar_to_bmi": _public(a_model),
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

    # Quartile edges from the weighted distribution, so the groups are quarters
    # of U.S. adolescents rather than quarters of this sample.
    edges = [_wquantile(frame["TotalSugars"], weights, q) for q in (0.25, 0.50, 0.75)]
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
                "weighted_mean_alt": _num(_wmean(block["ALT"], block["DietWeight"]), 3),
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
        "title": "Dose-response across sugar quartiles",
        "grade": SUPPORTING,
        "layer": INFERENTIAL,
        "question": "Does ALT rise steadily with sugar intake, or is the pattern flat?",
        "n": len(frame),
        "quartile_edges_g": [_num(e, 1) for e in edges],
        "quartiles": quartiles,
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
        "not_causal": NOT_CAUSAL,
    }


# ======================================================================
# STEP 7 -- MECHANISM: TRIG/HDL AGAINST SUGAR
# ======================================================================


def step_mechanism() -> dict:
    """Put sugar and the Trig/HDL ratio in one model and compare their betas."""
    frame = analysis_frame(
        ["ALT", "TotalSugars", "Age", "Sex", "BMI", "TrigHDLRatio", "HbA1c"]
    )
    model = fit_model(
        frame,
        "LogALT",
        ["Sugar10g", "TrigHDLRatio", "HbA1c", *BASE_CONTROLS, "BMI"],
        label="Sugar and downstream metabolic markers together",
    )

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

    return {
        "step": 7,
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
    # One frame for both models. This is the whole point: R-squared compared
    # across two different samples is not a comparison, and the lifestyle model
    # needs screen time, which 113 adolescents lack.
    frame = analysis_frame(
        ["ALT", "TotalSugars", "ScreenTime", "Age", "Sex", "TrigHDLRatio", "HbA1c"]
    )

    lifestyle = fit_model(
        frame,
        "LogALT",
        ["Sugar10g", "ScreenTime", *BASE_CONTROLS],
        label="Lifestyle only",
    )
    combined = fit_model(
        frame,
        "LogALT",
        ["Sugar10g", "ScreenTime", *BASE_CONTROLS, "TrigHDLRatio", "HbA1c"],
        label="Lifestyle + metabolic markers",
    )

    added = ["TrigHDLRatio", "HbA1c"]
    # A joint test that BOTH added coefficients are zero, run against the same
    # cluster-robust covariance the model was fitted with. Testing them one at a
    # time would answer a different question and would need a multiplicity
    # correction to answer it honestly.
    joint = combined["_model"].f_test([f"{name} = 0" for name in added])
    joint_p = float(np.ravel(joint.pvalue)[0])

    delta = None
    if None not in (combined["r_squared"], lifestyle["r_squared"]):
        delta = _num(combined["r_squared"] - lifestyle["r_squared"], 4)

    return {
        "step": 8,
        "title": "Incremental value of the metabolic blood markers",
        "grade": SUPPORTING,
        "layer": PREDICTIVE,
        "question": (
            "Do Trig/HDL and HbA1c explain variation in ALT that diet and screen "
            "time alone do not?"
        ),
        "n": len(frame),
        "shared_sample_note": (
            f"Both models are fitted on the same {len(frame)} adolescents -- those "
            "with screen time recorded -- so the change in R-squared reflects the "
            "added predictors and not a change of sample."
        ),
        "lifestyle_model": _public(lifestyle),
        "combined_model": _public(combined),
        "added_predictors": added,
        "delta_r_squared": delta,
        "joint_test": _report(joint_p),
        "interpretation": (
            f"Adding {' and '.join(added)} moves R-squared from "
            f"{lifestyle['r_squared']} to {combined['r_squared']} (change {delta}); "
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
    frame = analysis_frame(["ALT", "TotalSugars", "Age", "Sex", "BMI", "TrigHDLRatio"])

    strata = {}
    for sex in ("Male", "Female"):
        block = frame[frame["Sex"] == sex]
        strata[sex] = _public(
            fit_model(
                block,
                "LogALT",
                ["Sugar10g", "TrigHDLRatio", "Age", "BMI"],
                label=f"{sex}s only",
            )
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
        ["Sugar10g", "TrigHDLRatio", "Age", "BMI", "Male", "SugarXMale", "RatioXMale"],
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
        "title": "Sex differences",
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
            f"{_num(female_alt, 1)} U/L in females), but the sugar and Trig/HDL "
            f"slopes {'do' if any_interaction else 'do not'} differ detectably "
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

    frame = analysis_frame(
        ["ALT", "TotalSugars", "ScreenTime", "BMI", "TrigHDLRatio", "HbA1c", "Sex"]
    )
    scored = risk_score(frame)
    frame = frame.assign(RiskScore=scored["score"]).dropna(subset=["RiskScore"])

    bands = []
    for score in sorted(frame["RiskScore"].unique()):
        block = frame[frame["RiskScore"] == score]
        bands.append(
            {
                "score": int(score),
                "n": len(block),
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
        frame, "LogALT", ["RiskScore", "Age"], label="ALT across risk score"
    )
    slope = trend["coefficients"]["RiskScore"]

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
        "title": "Composite 0-6 risk score",
        "grade": EXPLORATORY,
        "layer": PREDICTIVE,
        "question": (
            "Does a count of six risk factors separate adolescents by ALT better "
            "than any single factor?"
        ),
        "n": len(frame),
        "components": {
            "quartile_based": list(scored["cutpoints"].keys() - {"HbA1c"}),
            "cutpoints": {k: _num(v, 3) for k, v in scored["cutpoints"].items()},
            "male_sex": "1 point",
        },
        "bands": bands,
        "trend_in_mean_alt": {
            "coefficient_per_point": slope["estimate"],
            "percent_change_per_point": _percent_change(slope["estimate"]),
            "significance": slope["significance"],
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
            f"Mean ALT changes {_percent_change(slope['estimate'])}% per additional "
            f"risk point (p = {slope['significance']['p_value']}), and the share above "
            f"the clinical threshold trends with the score at p = "
            f"{armitage['significance']['p_value']}."
        ),
        "caveat": (
            "Exploratory, and RELATIVE rather than portable: four of the six "
            "components are cut at this cohort's own quartiles, so the score ranks "
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
        "hierarchy": {
            "primary": "The one hypothesis the study was designed to test (steps 4-5).",
            "supporting": "Pre-specified analyses giving the primary result context.",
            "exploratory": "Hypothesis-generating; uncorrected for multiplicity.",
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
