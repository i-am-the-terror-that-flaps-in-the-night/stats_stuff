"""
Tests for the cohort derivation in Backend/engine.py (part two).

These lock in the decisions that are invisible once the CSV is written. A
derivation bug does not crash -- it produces a slightly different cohort, and
every number downstream shifts with it while still looking entirely reasonable.
So the things tested here are the ones a reader of the output could never catch:

  * the NHANES answer codes are decoded, not averaged (77 is "refused", not 77
    hours of television; 8 is "none", not 8 hours);
  * the exclusions run on the variables that mean what the protocol needs them
    to mean -- surface ANTIGEN, not the vaccination marker;
  * nothing is imputed, and an incomplete composite scores nothing rather than
    scoring low; and
  * the committed CSV still matches what this code produces.

Most tests build a small synthetic raw frame rather than reading the real 17 MB
merge, which lives in Git LFS and may not be fetched. The ones that do need the
real files are skipped when they are absent.

Run from the repo root with `uv run pytest`.
"""

import numpy as np
import pandas as pd
import pytest

from engine import (
    ALT_ELEVATED,
    ANALYTIC_MISSING_SENTINEL,
    COHORT_CSV,
    NON_ANALYTIC_COLUMNS,
    RAW_CSV,
    build_cohort,
    decode_screen_hours,
    elevated_alt,
    io_roundtrip,
    risk_score,
)

# Raw NHANES columns build_cohort() reads. Anything not set per-test gets a
# healthy default so a test can change one variable and hold the rest fixed.
RAW_DEFAULTS = {
    "RIDAGEYR": 15,
    "RIAGENDR": 1,
    "RIDRETH3": 3,
    "LBDHBG": 2,  # hepatitis B surface antigen negative
    "LBDHCI": 3,  # hepatitis C antibody: negative screen
    "LBXHCR": 3,  # hepatitis C RNA: negative screen
    "LBXSATSI": 15.0,  # ALT
    "DR1TSUGR": 100.0,
    "DR2TSUGR": 100.0,
    "DR1TKCAL": 2000.0,
    "WTDRD1": 1000.0,
    "SDMVPSU": 1,
    "SDMVSTRA": 145,
    "BMXBMI": 22.0,
    "LBXSTR": 90.0,  # triglycerides, biochemistry panel
    "LBDHDD": 50.0,  # HDL
    "LBXGH": 5.2,  # HbA1c
    "INDFMPIR": 2.0,
    "SEQN": 100000,
    "PAQ710": 2,
    "PAQ715": 2,
}


def raw_frame(n=6, **overrides):
    """A synthetic raw-merge frame with `n` participants, all eligible by default."""
    frame = pd.DataFrame({key: [value] * n for key, value in RAW_DEFAULTS.items()})
    frame["SEQN"] = range(100000, 100000 + n)
    for column, values in overrides.items():
        frame[column] = values
    return frame


# ----------------------------------------------------------------------
# Decoding NHANES answer codes
# ----------------------------------------------------------------------


def test_screen_time_codes_are_decoded_not_averaged():
    """The banded answers become hours, and the non-answers become blanks.

    This is the bug that would never look like one: 77 ("refused") and 99
    ("don't know") are real numbers in the file, and left alone they enter the
    mean as the two heaviest screen users in the study.
    """
    codes = pd.Series([0, 1, 2, 3, 4, 5, 8, 77, 99])

    hours = decode_screen_hours(codes)

    assert hours[0] == 0.5  # "less than 1 hour" -> band midpoint
    assert list(hours[1:6]) == [1, 2, 3, 4, 5]
    assert hours[6] == 0.0  # code 8 is "does not watch" -- a real zero
    assert hours[7:].isna().all()  # refused / don't know are missing, not 77 and 99


def test_screen_time_needs_both_parts():
    """Answering about TV but not computers gives no total, not a partial one."""
    frame, _ = build_cohort(raw_frame(n=2, PAQ710=[2, 2], PAQ715=[3, 77]))

    assert frame["ScreenTime"].tolist()[0] == 5.0
    assert pd.isna(frame["ScreenTime"].tolist()[1])


def test_sentinel_is_treated_as_missing():
    """The analytic file's missing sentinel must not survive as a measurement."""
    frame, log = build_cohort(
        raw_frame(n=2, LBXSATSI=[15.0, ANALYTIC_MISSING_SENTINEL])
    )

    # The sentinel row has no ALT, so it fails the complete-core rule.
    assert len(frame) == 1
    assert frame["ALT"].tolist() == [15.0]


# ----------------------------------------------------------------------
# Exclusions
# ----------------------------------------------------------------------


def test_only_adolescents_are_included():
    frame, _ = build_cohort(raw_frame(n=5, RIDAGEYR=[10, 11, 12, 17, 18]))

    assert sorted(frame["Age"].tolist()) == [12, 17]


def test_hepatitis_positive_participants_are_excluded():
    """Each viral marker excludes on its own, on its own positive codes."""
    frame, _ = build_cohort(
        raw_frame(
            n=4,
            LBDHBG=[1, 2, 2, 2],  # 1 = surface antigen positive
            LBDHCI=[3, 1, 3, 3],  # 1 = HCV antibody positive
            LBXHCR=[3, 3, 1, 3],  # 1 = HCV RNA positive
        )
    )

    assert len(frame) == 1  # only the fourth participant survives


def test_hepatitis_b_vaccination_does_not_exclude_anyone():
    """The protocol names the surface ANTIBODY file; excluding on it would drop
    the vaccinated, who are most of this age group. build_cohort() excludes on the
    surface ANTIGEN (LBDHBG) instead, and LBXHBS is not consulted at all."""
    vaccinated = raw_frame(n=3)
    vaccinated["LBXHBS"] = [1, 1, 1]  # anti-HBs positive: vaccinated

    frame, _ = build_cohort(vaccinated)

    assert len(frame) == 3


def test_attrition_log_accounts_for_every_dropped_participant():
    """The log is what makes the final n auditable, so it must actually add up."""
    frame, log = build_cohort(
        raw_frame(n=10, RIDAGEYR=[10, 10, 12, 13, 14, 15, 16, 17, 18, 19])
    )

    assert log[0]["n"] == 10
    assert log[-1]["n"] == len(frame)
    for earlier, later in zip(log, log[1:]):
        assert later["removed"] == earlier["n"] - later["n"]


def test_incomplete_core_variables_are_dropped_not_imputed():
    """A missing biomarker removes the participant; it is never filled in."""
    frame, _ = build_cohort(raw_frame(n=3, LBXGH=[5.2, np.nan, 5.4]))

    assert len(frame) == 2
    assert frame["HbA1c"].notna().all()


def test_screen_time_is_not_an_entry_criterion():
    """Missing screen time keeps the participant, with a blank in that column."""
    frame, _ = build_cohort(raw_frame(n=3, PAQ710=[2, 77, 2]))

    assert len(frame) == 3  # nobody dropped
    assert frame["ScreenTime"].isna().sum() == 1


# ----------------------------------------------------------------------
# Constructed measures
# ----------------------------------------------------------------------


def test_trig_hdl_ratio_is_computed_and_guards_against_a_zero_hdl():
    """A zero HDL yields no ratio rather than an infinity that poisons a mean."""
    frame, _ = build_cohort(raw_frame(n=2, LBXSTR=[90.0, 90.0], LBDHDD=[45.0, 0.0]))

    ratios = frame["TrigHDLRatio"].tolist()
    assert ratios[0] == pytest.approx(2.0)
    assert pd.isna(ratios[1])
    assert np.isfinite(frame["TrigHDLRatio"].dropna()).all()


def test_two_day_sugar_requires_both_days():
    """The sensitivity check's variable exists only for people who gave both
    recalls -- averaging one day with itself would fake a two-day mean."""
    frame, _ = build_cohort(
        raw_frame(n=2, DR1TSUGR=[100.0, 100.0], DR2TSUGR=[200.0, np.nan])
    )

    values = frame["TotalSugars2Day"].tolist()
    assert values[0] == pytest.approx(150.0)
    assert pd.isna(values[1])


def test_elevated_alt_uses_the_sex_specific_threshold():
    """24 U/L is elevated for a girl and not for a boy. One number cannot do both."""
    frame = pd.DataFrame(
        {"ALT": [24.0, 24.0, 21.0, 27.0], "Sex": ["Female", "Male", "Female", "Male"]}
    )

    flags = elevated_alt(frame)

    assert flags.tolist() == [True, False, False, True]
    assert ALT_ELEVATED["Female"] < ALT_ELEVATED["Male"]


def test_elevated_alt_distinguishes_not_measured_from_not_elevated():
    """A missing ALT must not count as a healthy one in a prevalence."""
    frame = pd.DataFrame({"ALT": [10.0, np.nan], "Sex": ["Male", "Male"]})

    flags = elevated_alt(frame)

    assert flags[0] is not None and bool(flags[0]) is False
    assert pd.isna(flags[1])


def test_risk_score_spans_zero_to_six_and_needs_every_component():
    """An incomplete score is blank, not low: 2 of 4 measured is not 2 of 6."""
    n = 40
    frame = pd.DataFrame(
        {
            "TotalSugars": np.linspace(20, 300, n),
            "ScreenTime": np.linspace(0, 10, n),
            "BMI": np.linspace(15, 40, n),
            "TrigHDLRatio": np.linspace(0.5, 6, n),
            "HbA1c": np.linspace(4.5, 6.5, n),
            "Sex": ["Male", "Female"] * (n // 2),
        }
    )
    frame.loc[0, "ScreenTime"] = np.nan

    scored = risk_score(frame)
    score = scored["score"]

    assert pd.isna(score[0])  # one component missing -> no score at all
    assert score.dropna().between(0, 6).all()
    assert set(scored["cutpoints"]) == {
        "TotalSugars",
        "ScreenTime",
        "BMI",
        "TrigHDLRatio",
        "HbA1c",
    }
    # Every continuous component is split at the cohort's own median, which is
    # what the revised protocol's Step 9 specifies.
    for column, cut in scored["cutpoints"].items():
        assert cut == pytest.approx(frame[column].median())


# ----------------------------------------------------------------------
# The committed artifact
# ----------------------------------------------------------------------


@pytest.mark.skipif(not COHORT_CSV.is_file(), reason="cohort CSV not built")
def test_committed_cohort_has_the_expected_shape_and_no_gaps_in_core_variables():
    frame = pd.read_csv(COHORT_CSV)

    assert len(frame) == 699
    for column in ("ALT", "TotalSugars", "BMI", "HbA1c", "Triglycerides", "Sex"):
        assert frame[column].notna().all(), f"{column} has gaps in the committed cohort"
    assert set(frame["Sex"]) == {"Male", "Female"}
    # Screen time is the deliberate exception -- present for most, not required.
    assert 0 < frame["ScreenTime"].isna().sum() < len(frame)


@pytest.mark.skipif(not COHORT_CSV.is_file(), reason="cohort CSV not built")
def test_bookkeeping_columns_are_present_but_marked_non_analytic():
    """The study needs the weight and design codes; the website must not offer
    to compute their means. Both facts have to hold at once."""
    frame = pd.read_csv(COHORT_CSV)

    for column in NON_ANALYTIC_COLUMNS:
        assert column in frame.columns
    assert "SEQN" in NON_ANALYTIC_COLUMNS
    assert "DietWeight" in NON_ANALYTIC_COLUMNS


@pytest.mark.skipif(
    not RAW_CSV.is_file() or not COHORT_CSV.is_file(),
    reason="raw merge not fetched (git lfs pull) or cohort not built",
)
def test_committed_cohort_matches_what_the_code_produces():
    """The committed CSV and the code that derives it must not drift apart.

    This is the test that makes the data reviewable: the CSV is a build artifact,
    and without this check a change to the derivation could ship while the file
    kept the old numbers.
    """
    rebuilt, _ = build_cohort()
    committed = pd.read_csv(COHORT_CSV)

    # Compare what would be STORED, not what is in memory. RiskScore holds
    # nullable integers in the frame and comes back from a CSV as floats with
    # NaN -- identical data, different dtype, and comparing the two directly
    # reports drift on every run for a reason that has nothing to do with the
    # cohort. io_roundtrip puts both sides through the same serialization.
    rebuilt = pd.read_csv(io_roundtrip(rebuilt))

    assert len(rebuilt) == len(committed)
    assert list(rebuilt.columns) == list(committed.columns)
    pd.testing.assert_frame_equal(rebuilt, committed, rtol=1e-9)
