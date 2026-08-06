"""
Tests for the stats engine in Backend/engine.py.

These lock in the things that are easy to regress:
  * basic_analysis() computes the expected descriptive stats and handles the
    edge cases (no numeric values, tied modes);
  * df_cleanup() coerces mostly-numeric columns *without* imputing the gaps,
    so missing values are dropped before stats are computed -- not silently
    replaced with the mean (which would inflate n and shrink variance/std); and
  * the engine's statistical SEMANTICS -- that it refuses to guess causal roles,
    never passes a dataset median off as a clinical threshold, and always pairs
    a p-value with an effect size. Those are the claims the numbers are wrapped
    in, and they can rot while every calculation stays correct.

Run from the repo root with `uv run pytest` (pyproject puts Backend/ on the path).
"""

import math

import numpy as np
import pandas as pd

from engine import ANALYTIC_MISSING_SENTINEL, DataAnalyzer, _num, df_cleanup


def _grouped_frame():
    """A small frame with a numeric column, a grouping column, and covariates."""
    rng = np.random.default_rng(0)
    n = 60
    age = rng.normal(50, 10, n)
    bmi = 25 + 0.1 * age + rng.normal(0, 2, n)
    return pd.DataFrame(
        {
            "outcome": 100 + 0.5 * age + 0.3 * bmi + rng.normal(0, 5, n),
            "age": age,
            "bmi": bmi,
            "group": ["a", "b"] * (n // 2),
        }
    )


def test_basic_analysis_numeric_column():
    """A plain numeric column reports the expected descriptive stats."""
    df = pd.DataFrame({"x": [1, 2, 3, 4, 5]})

    result = DataAnalyzer(df).basic_analysis("x")

    assert result["column"] == "x"
    assert result["mean"] == 3.0
    assert result["median"] == 3.0
    assert result["min"] == 1.0
    assert result["max"] == 5.0
    # Sample (n-1) variance of 1..5 is 2.5; std is its square root, rounded to
    # 3 decimals by basic_analysis().
    assert result["variance"] == 2.5
    assert result["std"] == round(math.sqrt(2.5), 3)
    assert "error" not in result


def test_basic_analysis_all_nan_column():
    """A column with no numeric values returns an error rather than NaN stats."""
    df = pd.DataFrame({"label": ["a", "b", "c"]})

    result = DataAnalyzer(df).basic_analysis("label")

    assert result == {"error": "No numeric values in that column."}


def test_basic_analysis_mode_tie_returns_all_modes():
    """When several values tie for the mode, all of them are reported.

    pandas' Series.mode() returns the tied values sorted ascending, and
    basic_analysis() returns that full list -- so a 1-vs-2 tie yields [1, 2].
    """
    df = pd.DataFrame({"x": [1, 1, 2, 2, 3]})

    result = DataAnalyzer(df).basic_analysis("x")

    assert result["mode"] == [1, 2]


def test_df_cleanup_keeps_missing_as_nan():
    """A mostly-numeric column is coerced, but un-parseable cells stay NaN."""
    # 9 numbers + 1 non-numeric -> 90% numeric, above the 0.8 "treat as numeric"
    # threshold, so the column is coerced.
    df = pd.DataFrame({"x": [str(i) for i in range(1, 10)] + ["n/a"]})

    cleaned = df_cleanup(df)

    assert cleaned["x"].isna().sum() == 1  # the "n/a" cell, not imputed with the mean


def test_basic_analysis_drops_missing_not_imputed():
    """Missing cells are dropped before stats, so they don't distort variance/n.

    Values 1..9 (mean 5) plus one missing cell. Dropping the gap gives the
    sample variance of nine points (60 / 8 = 7.5). If the gap were imputed at
    the mean instead, n would be 10 and the variance would shrink to 60 / 9.
    """
    df = pd.DataFrame({"x": [str(i) for i in range(1, 10)] + ["missing"]})

    result = DataAnalyzer(df_cleanup(df)).basic_analysis("x")

    assert result["mean"] == 5.0
    assert result["variance"] == 7.5


def test_num_returns_none_for_unusable_values():
    """_num() is the single exit for every statistic, so it must not raise.

    It caught (TypeError, ValueError) with a Python 2 `except a, b` that never
    parsed, which took the whole module down at import.
    """
    assert _num(2.34567) == 2.346
    assert _num(None) is None  # TypeError branch
    assert _num("not a number") is None  # ValueError branch
    assert _num(float("nan")) is None
    assert _num(float("inf")) is None


def test_missing_sentinel_never_reaches_a_statistic():
    """The analytic file's missing sentinel is a blank, not a measurement near 0."""
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0, ANALYTIC_MISSING_SENTINEL]})

    result = DataAnalyzer(df_cleanup(df)).basic_analysis("x")

    assert result["n"] == 3  # the sentinel row was dropped, not counted
    assert result["mean"] == 2.0
    assert result["min"] == 1.0  # would be ~0 if the sentinel had survived


def test_outliers_report_both_rules_and_prefer_iqr_when_skewed():
    """Skewed data gets the robust rule recommended, not the z-score one."""
    # A long right tail: it drags the mean up and inflates the SD, so the z-score
    # rule flags fewer points than the quartile-based rule does.
    df = pd.DataFrame({"x": list(range(1, 41)) + [300.0, 400.0, 500.0]})

    outliers = DataAnalyzer(df).medium_analysis("x")["distribution"]["outliers"]

    assert outliers["recommended_rule"] == "iqr_rule"
    assert outliers["iqr_rule"] > outliers["z_score_gt_3"]


def test_iqr_rule_reports_not_applicable_rather_than_zero():
    """A zero IQR collapses the fences, which is not the same as 'no outliers'."""
    # Half the column is the same value, so Q1 == Q3 and the rule has no width.
    df = pd.DataFrame({"x": [1.0] * 40 + [2.0] * 5 + [50.0, 60.0, 70.0]})

    outliers = DataAnalyzer(df).medium_analysis("x")["distribution"]["outliers"]

    assert outliers["iqr_rule"] is None  # not 0, which would read as "none found"
    assert "Not applicable" in outliers["iqr_rule_note"]
    assert outliers["recommended_rule"] == "z_score_gt_3"


def test_group_tests_pair_every_p_value_with_an_effect_size():
    """Significance and importance are reported as separate numbers."""
    groups = DataAnalyzer(_grouped_frame()).medium_analysis("outcome", "group")[
        "groups"
    ]

    assert groups["primary_test"] == "anova"
    for test in (groups["anova"], groups["median_split_chi_square"]):
        assert "statistically_significant" in test
        assert "p_value_means" in test  # the correct definition travels with it
        assert test["effect_size"]["value"] is not None

    # The coarser test says so itself rather than presenting as an equal option.
    assert "median split" in groups["median_split_chi_square"]["method"]


def test_adjustment_is_not_run_without_explicit_causal_roles():
    """The engine refuses to guess which column is the exposure.

    It used to take others[0] as the exposure and the rest as confounders --
    correct arithmetic wrapped around an invented causal model.
    """
    result = DataAnalyzer(_grouped_frame()).advanced_analysis("outcome")

    adjustment = result["adjustment"]
    assert adjustment["status"] == "not_run"
    assert "how_to_run" in adjustment
    assert set(adjustment["candidates"]) == {"age", "bmi"}
    # No crude/adjusted numbers were produced for roles nobody assigned.
    assert "crude_association" not in adjustment


def test_adjustment_runs_when_roles_are_supplied_and_stays_associational():
    """Naming the roles runs the model -- still labelled association, not effect."""
    result = DataAnalyzer(_grouped_frame()).advanced_analysis(
        "outcome", exposure="bmi", confounders=["age"]
    )

    adjustment = result["adjustment"]
    assert adjustment["status"] == "ran"
    assert adjustment["roles_supplied_by"] == "caller"
    assert adjustment["crude_association"] is not None
    assert adjustment["adjusted_association"] is not None
    assert adjustment["adjusted_for"] == ["age"]
    # Named for what was observed, not for a cause the data can't confirm.
    assert "estimate_moved_over_10_percent" in adjustment
    assert "confounding_detected" not in adjustment


def test_median_is_never_reported_as_a_clinical_threshold():
    """An unknown column gets no clinical block, only an honest median split."""
    result = DataAnalyzer(_grouped_frame()).expert_analysis("outcome")

    assert result["clinical_threshold"]["status"] == "not_run"
    median_split = result["dataset_median_split"]
    assert median_split["layer"] == "descriptive"
    assert "not a clinical threshold" in median_split["note"]


def test_known_column_uses_a_published_threshold_with_its_source():
    """A recognized column classifies against the guideline value, not the median."""
    # Median is 6.0; the ADA diabetes line is 6.5, so the two disagree on one row.
    df = pd.DataFrame({"HbA1c": [5.0, 5.5, 6.0, 6.4, 7.0]})

    threshold = DataAnalyzer(df).expert_analysis("HbA1c")["clinical_threshold"]

    assert threshold["status"] == "ran"
    assert threshold["cutoff"] == 6.5
    assert threshold["unit"] == "%"
    assert threshold["cutoff_source"] == "American Diabetes Association"
    assert threshold["flagged"] == 1  # only the 7.0, not everything above the median
    assert threshold["unit_check"]["status"] == "consistent"


def test_threshold_refused_when_the_column_is_in_different_units():
    """A unit swap must not silently produce a confident, wrong prevalence.

    150 mg/dL is the elevated-triglyceride line; the same line is 1.7 mmol/L. Run
    the mg/dL cutoff over mmol/L data and every row passes, reporting that 0% of
    the population is at risk -- correct arithmetic, invented finding.
    """
    mmol = pd.Series([0.8, 1.0, 1.2, 1.4, 1.6, 2.0, 2.4])  # mmol/L, median 1.4
    df = pd.DataFrame({"Triglycerides": mmol})

    threshold = DataAnalyzer(df).expert_analysis("Triglycerides")["clinical_threshold"]

    assert threshold["status"] == "not_run"
    assert threshold["unit_check"]["status"] == "mismatch"
    # It doesn't just refuse -- it names the unit the values actually look like.
    assert threshold["unit_check"]["suspected_unit"] == "mmol/L"
    assert "mmol/L" in threshold["how_to_run"]


def test_declaring_the_unit_applies_that_units_published_cutoff():
    """Saying what the column is in gets the right guideline value for it."""
    mmol = pd.Series([0.8, 1.0, 1.2, 1.4, 1.6, 2.0, 2.4])  # two rows at/above 1.7
    df = pd.DataFrame({"Triglycerides": mmol})

    threshold = DataAnalyzer(df).expert_analysis("Triglycerides", units="mmol/L")[
        "clinical_threshold"
    ]

    assert threshold["status"] == "ran"
    assert threshold["cutoff"] == 1.7  # the SI value, not the mg/dL one
    assert threshold["unit"] == "mmol/L"
    assert threshold["flagged"] == 2
    assert threshold["unit_check"]["status"] == "declared"


def test_unit_check_agrees_across_unit_systems():
    """The same people are flagged whichever unit their data arrives in."""
    # Values kept clear of the cutoff, where the two unit systems agree exactly.
    mgdl = pd.Series([60.0, 90.0, 120.0, 200.0, 300.0, 400.0])
    df_mgdl = pd.DataFrame({"Triglycerides": mgdl})
    df_mmol = pd.DataFrame({"Triglycerides": mgdl / 88.57})

    in_mgdl = DataAnalyzer(df_mgdl).expert_analysis("Triglycerides")
    in_mmol = DataAnalyzer(df_mmol).expert_analysis("Triglycerides", units="mmol/L")

    assert (
        in_mgdl["clinical_threshold"]["flagged"]
        == in_mmol["clinical_threshold"]["flagged"]
        == 3
    )


def test_published_si_cutoffs_are_rounded_and_can_disagree_at_the_boundary():
    """Right at the line the two unit systems can disagree, by design.

    ATP III's line is 150 mg/dL, published in SI as 1.7 mmol/L -- but the exact
    conversion is 150 / 88.57 = 1.694, just under it. So a row sitting exactly on
    the mg/dL cutoff falls a hair below the mmol/L one. We report each unit's
    published value rather than converting on the fly, because computing 1.694
    would invent a cutoff no guideline ever wrote down. This pins the resulting
    edge behaviour so it stays a known quirk rather than a surprise.
    """
    mgdl = [90.0, 120.0, 150.0]
    exactly_on_the_line = pd.DataFrame({"Triglycerides": mgdl})
    converted = pd.DataFrame({"Triglycerides": [v / 88.57 for v in mgdl]})

    in_mgdl = DataAnalyzer(exactly_on_the_line).expert_analysis("Triglycerides")
    in_mmol = DataAnalyzer(converted).expert_analysis("Triglycerides", units="mmol/L")

    assert in_mgdl["clinical_threshold"]["flagged"] == 1  # 150 >= 150
    assert in_mmol["clinical_threshold"]["flagged"] == 0  # 1.694 < 1.7


def test_unknown_unit_is_refused_rather_than_guessed():
    """An unrecognized unit name doesn't fall back to the default unit's cutoff."""
    df = pd.DataFrame({"Triglycerides": [60.0, 90.0, 120.0, 200.0]})

    threshold = DataAnalyzer(df).expert_analysis("Triglycerides", units="g/L")[
        "clinical_threshold"
    ]

    assert threshold["status"] == "not_run"
    assert threshold["unit_check"]["status"] == "unknown_unit"
    assert "mg/dL" in threshold["known_units"]


def test_caller_supplied_cutoff_is_applied_but_flagged_as_unchecked():
    """The engine can't verify units for a number it didn't provide, and says so."""
    df = pd.DataFrame({"SleepHours": [4.0, 6.0, 7.0, 9.0]})

    threshold = DataAnalyzer(df).expert_analysis("SleepHours", clinical_cutoff=7.0)[
        "clinical_threshold"
    ]

    assert threshold["status"] == "ran"
    assert threshold["cutoff"] == 7.0
    assert threshold["cutoff_source"] == "supplied by the caller"
    assert threshold["unit_check"]["status"] == "not_checked"


def test_standardized_betas_carry_their_caveat():
    """The biggest beta is the largest association in one model, not 'the most
    influential predictor'."""
    regression = DataAnalyzer(_grouped_frame()).advanced_analysis("outcome")[
        "regression"
    ]

    assert regression["layer"] == "predictive"
    assert set(regression["standardized_betas"]["values"]) == {"age", "bmi"}
    assert (
        "does not rank predictors by importance"
        in (regression["standardized_betas"]["caveat"])
    )


def test_normality_check_does_not_claim_residuals_are_normal():
    """Shapiro-Wilk is reported as evidence against normality, never as proof of it."""
    diagnostics = DataAnalyzer(_grouped_frame()).expert_analysis("outcome")[
        "diagnostics"
    ]

    normality = diagnostics["normality"]
    assert "detectably_non_normal" in normality
    assert "normal_residuals" not in normality  # the old, misleading key
    # A shape description sits alongside the yes/no, so the test isn't a gate.
    assert diagnostics["skewness"] is not None
    assert diagnostics["kurtosis"] is not None
