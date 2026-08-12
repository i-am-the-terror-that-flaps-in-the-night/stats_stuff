"""
Tests for the ten-step analysis in Backend/study.py.

A statistics bug does not raise. It returns a number, and the number is wrong in
a way no reader can see. So these tests do not check that the coefficients equal
particular values -- that would just re-assert whatever the code currently does,
and would have to be rewritten the moment the cohort changed. They check the
properties that make the numbers mean what the write-up says they mean:

  * the survey design is actually applied -- weights change the answer, and the
    clusters are PSU-within-stratum rather than two giant PSUs;
  * two models being COMPARED are fitted on the same people, without which a
    change in R-squared measures the sample rather than the predictors;
  * every reported test carries an effect size and a usable p-value, including
    one too small to round to four decimals; and
  * the claim grades and the caveats are still attached, because those are what
    separate this from a script that prints coefficients.

Run from the repo root with `uv run pytest`.
"""

import numpy as np
import pandas as pd
import pytest

import study
from cohort import COHORT_CSV

pytestmark = pytest.mark.skipif(not COHORT_CSV.is_file(), reason="cohort CSV not built")


# ----------------------------------------------------------------------
# Weighted primitives
# ----------------------------------------------------------------------


def test_weighted_mean_respects_the_weights():
    values = pd.Series([10.0, 20.0])

    assert study._wmean(values, pd.Series([1.0, 1.0])) == pytest.approx(15.0)
    assert study._wmean(values, pd.Series([3.0, 1.0])) == pytest.approx(12.5)


def test_weighted_quantile_matches_the_plain_one_when_weights_are_equal():
    values = pd.Series(np.arange(1.0, 101.0))
    weights = pd.Series(np.ones(100))

    # Interpolation conventions differ slightly at the edges, so this is a
    # closeness check, not an identity -- the point is that a uniform weight
    # does not move the answer somewhere else entirely.
    assert study._wquantile(values, weights, 0.5) == pytest.approx(50.5, abs=1.0)


def test_clusters_nest_psu_inside_stratum():
    """PSU 1 of stratum 145 and PSU 1 of stratum 146 are different places.

    Clustering on the raw PSU column would pool every stratum's PSU 1 into one
    cluster, collapsing 30 clusters into 2 and quietly undoing the correction.
    """
    frame = pd.DataFrame(
        {"SurveyStratum": [145, 145, 146, 146], "SurveyPSU": [1, 2, 1, 2]}
    )

    assert study._clusters(frame).nunique() == 4


def test_the_real_cohort_has_the_expected_cluster_structure():
    frame = study.analysis_frame(["ALT", "TotalSugars", "Age", "Sex", "BMI"])

    assert study._clusters(frame).nunique() == 30  # 15 strata x 2 PSUs


# ----------------------------------------------------------------------
# The model
# ----------------------------------------------------------------------


def test_models_are_weighted_and_the_weights_change_the_answer():
    """If weighting were a no-op, every 'nationally representative' claim on the
    site would be decoration. This checks it actually does something."""
    frame = study.analysis_frame(["ALT", "TotalSugars", "Age", "Sex", "BMI"])

    weighted = study.fit_model(frame, "LogALT", ["Sugar10g", "Age", "Male", "BMI"])
    unweighted = study.fit_model(
        frame.assign(DietWeight=1.0), "LogALT", ["Sugar10g", "Age", "Male", "BMI"]
    )

    assert weighted["n"] == unweighted["n"]
    assert (
        weighted["coefficients"]["Sugar10g"]["estimate"]
        != unweighted["coefficients"]["Sugar10g"]["estimate"]
    )


def test_every_coefficient_reports_an_interval_and_a_p_value():
    frame = study.analysis_frame(["ALT", "TotalSugars", "Age", "Sex", "BMI"])

    model = study.fit_model(frame, "LogALT", ["Sugar10g", "Age", "Male", "BMI"])

    for name, info in model["coefficients"].items():
        assert info["ci_low"] is not None and info["ci_high"] is not None, name
        assert info["ci_low"] <= info["estimate"] <= info["ci_high"], name
        assert "p_value_means" in info["significance"], name
    assert model["clusters"] == 30
    assert "cluster-robust" in model["estimator"]


def test_standardized_betas_are_unitless_and_comparable():
    """The secondary hypothesis compares sugar against Trig/HDL, which is only
    meaningful if both are on the same scale."""
    step = study.run_step("mechanism")

    betas = [row["standardized_beta"] for row in step["ranked_by_standardized_beta"]]
    assert all(b is not None for b in betas)
    # Ranked strongest-first, by absolute size.
    assert betas == sorted(betas, key=lambda b: abs(b), reverse=True)


# ----------------------------------------------------------------------
# The steps' statistical integrity
# ----------------------------------------------------------------------


def test_incremental_value_compares_two_models_on_one_sample():
    """A change in R-squared across two different samples is not a comparison.

    The lifestyle model needs screen time, which 113 adolescents lack; if the
    combined model were allowed to run on the other 699 the delta would mostly
    measure the sample swap.
    """
    step = study.run_step("incremental")

    assert step["lifestyle_model"]["n"] == step["combined_model"]["n"] == step["n"]
    assert step["n"] < 699  # the screen-time subsample, as expected
    assert step["delta_r_squared"] == pytest.approx(
        step["combined_model"]["r_squared"] - step["lifestyle_model"]["r_squared"],
        abs=1e-9,
    )


def test_mediation_reports_both_models_on_the_same_sample():
    """The total and direct effects have to be comparable, so BMI's own
    missingness must not silently shrink one of them."""
    step = study.run_step("direct-effect")

    assert step["total_model"]["n"] == step["direct_model"]["n"] == step["n"]
    decomposition = step["decomposition"]
    assert decomposition["total_c"] is not None
    assert decomposition["direct_c_prime"] is not None


def test_mediation_suppresses_a_nonsensical_proportion_mediated():
    """A proportion mediated only means anything when the indirect path runs the
    same way as the total. Otherwise it is a ratio of noise and must not be
    printed as a percentage someone will quote."""
    step = study.run_step("direct-effect")
    decomposition = step["decomposition"]

    proportion = decomposition["proportion_mediated"]
    if proportion is not None:
        indirect, total = decomposition["indirect_a_times_b"], decomposition["total_c"]
        assert np.sign(indirect) == np.sign(total)


def test_log_transform_is_justified_by_the_data_not_assumed():
    step = study.run_step("distribution")

    assert step["raw"]["skewness"] > step["log"]["skewness"]
    assert step["transformation_justified"] is True


def test_risk_score_flags_its_sparse_bands():
    """The top bands hold a handful of adolescents, and a mean of one person
    must not be presented with the same confidence as a mean of 183."""
    step = study.run_step("risk-score")

    assert step["sparse_bands"], "sparse bands should be reported, not hidden"
    small = [band for band in step["bands"] if band["n"] < 20]
    assert len(small) == len(step["sparse_bands"])


def test_risk_score_is_compared_against_single_factors():
    """'Better than any one factor alone' is the claim, so the comparison has to
    actually be computed rather than asserted."""
    step = study.run_step("risk-score")

    comparison = step["r_squared_vs_single_factors"]
    assert "RiskScore" in comparison
    assert len(comparison) >= 3


def test_cochran_armitage_detects_a_trend_and_its_direction():
    rising = study._cochran_armitage(
        np.array([0.0, 1.0, 2.0, 3.0]),
        np.array([2.0, 10.0, 25.0, 45.0]),
        np.array([50.0, 50.0, 50.0, 50.0]),
    )

    assert rising["applicable"] is True
    assert rising["direction"] == "increasing"
    assert rising["significance"]["statistically_significant"] is True


def test_cochran_armitage_declines_when_it_cannot_apply():
    flat = study._cochran_armitage(
        np.array([0.0, 1.0, 2.0]),
        np.array([0.0, 0.0, 0.0]),
        np.array([10.0, 10.0, 10.0]),
    )

    assert flat["applicable"] is False


# ----------------------------------------------------------------------
# Reporting discipline
# ----------------------------------------------------------------------


def test_a_tiny_p_value_is_never_reported_as_zero():
    """p = 0 reads as certainty, which is the one thing a p-value never means."""
    report = study._report(1e-12)

    assert report["p_value_text"] == "< 0.0001"
    assert report["statistically_significant"] is True


def test_an_ordinary_p_value_keeps_its_number():
    report = study._report(0.0342)

    assert report["p_value_text"] == "0.0342"


def test_every_step_declares_its_claim_grade_and_layer():
    """The primary/supporting/exploratory hierarchy is what stops a null primary
    result being replaced by whichever subgroup cleared 0.05."""
    for name in study.STEP_NAMES:
        step = study.run_step(name)
        assert step["grade"] in {study.PRIMARY, study.SUPPORTING, study.EXPLORATORY}, (
            name
        )
        assert "title" in step, name

    graded = [study.run_step(n)["grade"] for n in study.STEP_NAMES]
    assert graded.count(study.PRIMARY) == 2  # exactly the two pre-specified models


def test_causal_language_is_never_attached_to_a_model():
    for name in ("total-effect", "direct-effect", "mechanism", "risk-score"):
        step = study.run_step(name)
        assert "not_causal" in step, name


def test_the_mediation_step_carries_its_assumptions():
    """This is the step whose shape most invites a causal reading, so the caveat
    has to travel with it rather than living only in the module docstring."""
    step = study.run_step("direct-effect")

    assert "caveat" in step
    assert "unmeasured" in step["caveat"] or "assumptions" in step["caveat"].lower()


def test_exploratory_steps_admit_they_are_uncorrected():
    sex = study.run_step("sex")

    assert sex["grade"] == study.EXPLORATORY
    assert "multiplicity" in sex


def test_sensitivity_checks_rerun_the_primary_model_several_ways():
    checks = study.sensitivity_checks()

    assert len(checks["checks"]) >= 4
    for check in checks["checks"]:
        assert check["n"] > 0
        assert "why" in check
        assert "statistically_significant" in check["significance"]


def test_the_whole_study_is_json_serializable():
    """The API returns this verbatim, so a stray numpy scalar or a statsmodels
    object left in the payload is a 500 in production, not a formatting nit."""
    import json

    payload = study.run_study()

    encoded = json.dumps(payload)  # raises TypeError if anything is not plain JSON
    assert len(payload["steps"]) == 10
    # The exact key, quoted -- a bare "_model" substring also matches the
    # legitimate "total_model" and "direct_model" keys.
    assert '"_model"' not in encoded  # the statsmodels handle must be stripped


def test_headline_matches_the_step_it_summarizes():
    """The summary card and the full study must not be able to disagree."""
    headline = study.headline()
    direct = study.run_step("direct-effect")

    assert headline["n"] == direct["n"]
    assert (
        headline["sugar_p"]
        == direct["direct_model"]["coefficients"]["Sugar10g"]["significance"]["p_value"]
    )
