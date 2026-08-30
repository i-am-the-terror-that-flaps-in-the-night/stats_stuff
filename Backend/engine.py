"""
engine.py -- the backend stats engine.

Pure data logic, no printing: it cleans up a spreadsheet and computes statistics
on it. app.py imports df_cleanup and DataAnalyzer from here and serves the
results over HTTP; tests/test_engine.py calls them directly.

HOW THIS FILE IS ORGANIZED
    DataAnalyzer has seven methods and no others:

        basic_analysis()        mean, median, mode, spread
        medium_analysis()       shape of the data, error bars, group comparisons
        advanced_analysis()     correlation, regression, optional adjustment
        expert_analysis()       collinearity, model checks, threshold counts
        categorical_analysis()  counts and cross-tabs for label columns
        figure_production()     histogram and boxplot files for every column
        analysis_utilities()    the odds and ends that fit nowhere above

    Every statistical step lives INSIDE the method it belongs to, as a nested
    function. So a tier is one self-contained unit: open medium_analysis() and
    the ANOVA, the confidence interval and the outlier rules are all right
    there, in the order they are used, with nothing to chase across the file.
    Each method opens with a short list of what it nests.

    The only things outside the class are the constants and the handful of small
    helpers that MORE THAN ONE tier needs -- turning a column into numbers,
    rounding a result, formatting a p-value report. Those cannot nest inside any
    single method without being duplicated, so they sit above the class under
    their own banner, and a fix to one of them lands everywhere at once.

WHAT THIS ENGINE WILL AND WON'T CLAIM
    Statistics comes in layers, and they blur together easily:

        descriptive   what THIS dataset looks like (mean, median, spread)
             |
        inferential   what it suggests about the wider population, and how
             |        uncertain that suggestion is (p-values, confidence intervals)
             |
        predictive    how well one column can be guessed from the others
             |        (regression, R-squared)
             |
        causal        what would happen if you CHANGED something

    Every block this engine returns carries a "layer" key naming which of the
    first three it belongs to. The engine never reaches the fourth on its own.
    A causal claim needs a causal model -- outside knowledge about what affects
    what -- and no amount of column-crunching supplies that. Column order in a
    CSV is not a causal model. Where the output comes closest (covariate
    adjustment, mediation) it runs only when the caller names the roles by hand,
    and it still reports an "adjusted association", never an "effect".

READING P-VALUES AND SIGNIFICANCE
    A p-value is the probability of seeing a result at least this extreme IF the
    null hypothesis and the test's assumptions were both true. It is NOT the
    probability that the result is due to chance, and 1 - p is NOT the
    probability that your hypothesis is right.

    "Statistically significant" and "actually matters" are also different
    questions. With an NHANES-sized sample, a difference far too small to notice
    in a clinic can still clear p < 0.05 easily. So every test here that reports
    a p-value also reports an effect size -- how BIG the pattern is -- and the
    two are labeled separately in the output.

A NOTE ON MISSING VALUES
    Real spreadsheets have blanks and typos. Everywhere we turn a column into
    numbers we use pd.to_numeric(..., errors="coerce"), which turns anything
    unreadable into NaN ("not a number"), and then we .dropna() those rows.
    We never fill a blank in with the mean -- that would fake extra data points
    and make the results look more certain than they are.

    Dropping is not free either. Every tier here does complete-case analysis: a
    row missing any column the analysis touches is gone, so a regression on six
    predictors can quietly run on far fewer people than the file contains, and
    those people are rarely a random subset of it. Watch the "n" reported in each
    block -- it is the sample the numbers actually describe.

    One sentinel value gets special handling on the way in; see
    ANALYTIC_MISSING_SENTINEL, and note what it does and doesn't claim about
    NHANES generally.

IMPORT COST
    Only pandas and scipy load when this file is imported. The website only uses
    the basic tier, so the slow libraries the higher tiers need -- statsmodels
    and matplotlib -- are imported inside the methods that use them. That keeps
    them off Render's cold-start path (see the "SPEED ON RENDER" note in app.py).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

# scipy.stats is NOT imported here. It is the most expensive import in the
# application -- 460 ms and 56 MB, more than pandas -- and every one of its
# twenty uses is inside a function body, so importing it at module scope charged
# the full cost to `import engine` whether or not the request needed a
# statistical test. On a Render free instance (0.1 vCPU, 512 MB) that is roughly
# five seconds of the cold start spent on a module the landing page, the column
# list, the basic tier and every figure endpoint never touch.
#
# So each function that needs it imports it, which is already the idiom
# everywhere else in this project (see figures_api.py and lab_api.py). Python
# caches modules, so the import is paid once and every later one is a dict
# lookup -- the cost moves off the boot path, it does not repeat.

# Minimum share of parseable values required to treat a column as numeric.
NUMERIC_THRESHOLD = 0.8

# Default p-value cutoff for significance checks. A p-value below this does NOT
# mean "there is a 95% chance the pattern is real" -- see P_VALUE_MEANING below.
# 0.05 is a convention, not a law of nature, and nothing important should hinge
# on whether a number lands at 0.049 or 0.051.
ALPHA = 0.05

# The sentinel OUR analytic CSV (Data/nhanes_analytic.csv) uses for a missing
# numeric cell. This is a property of how our preprocessing pipeline wrote that
# file -- it is NOT a universal NHANES convention. NHANES ships SAS XPT files
# whose missing-value representation varies by variable and processing stage, so
# a different NHANES extract may well use blanks, or documented special codes
# like 7/9/777/9999 for "refused"/"don't know". Feed this engine such a file and
# those codes will sail straight through as if they were real measurements; they
# have to be cleaned upstream.
#
# Left alone, this value would sink every mean, crush every variance, and fake
# tens of thousands of data points, so we turn it back into a blank (NaN) on the
# way in. Files that don't use it (Data/data.csv) are unaffected.
ANALYTIC_MISSING_SENTINEL = 5.397605346934028e-79

# Former name, kept so existing callers and notebooks don't break. The rename is
# the point: the old name claimed this was how NHANES represents missing data.
NHANES_MISSING_FILL = ANALYTIC_MISSING_SENTINEL

# The layer of claim each block of output belongs to (see the module docstring).
# Nothing here is ever tagged "causal" -- the engine cannot earn that label.
DESCRIPTIVE = "descriptive"  # what this dataset looks like
INFERENTIAL = "inferential"  # what it suggests about the wider population
PREDICTIVE = "predictive"  # how well the columns predict each other

P_VALUE_MEANING = (
    "A p-value is the probability of a result at least this extreme IF the null "
    "hypothesis and the test's assumptions were both true. It is not the "
    "probability that the pattern arose by chance, and 1 - p is not the "
    "probability that the hypothesis is correct."
)

SIGNIFICANCE_VS_IMPORTANCE = (
    "'Significant' answers 'is this distinguishable from no effect at all?', not "
    "'is this big enough to matter?'. In a sample this size a tiny, practically "
    "meaningless difference can still clear the cutoff, so read the effect size "
    "next to every p-value."
)

NOT_CAUSAL = (
    "This is an association measured in observational data. It does not "
    "establish that changing one variable would change the other."
)

# Published adult thresholds for the columns our curated NHANES extract carries,
# keyed by lowercased column name. These come from guideline bodies that studied
# health outcomes; a dataset's own median never belongs in this table, which is
# the whole point of keeping it separate (see expert_analysis).
#
# A THRESHOLD IS A NUMBER PLUS A UNIT. 150 means "elevated triglycerides" in
# mg/dL and something absurd in mmol/L, where the same line sits at 1.7. Applying
# an mg/dL cutoff to mmol/L data is the sentinel bug wearing a different hat: the
# arithmetic runs perfectly and reports that 0% of a population is at risk. So
# every entry below names its unit, lists the cutoff in each unit it is commonly
# reported in, and carries a plausible_median band per unit.
#
# Those bands are what makes this checkable. Unit systems here differ by roughly
# an order of magnitude, so the column's own median tells you which one you were
# handed: a triglyceride median of 87 is mg/dL, a median of 1.4 is mmol/L, and
# nothing sane sits between the two bands. expert_analysis's check_units() uses
# that to verify the assumed unit before any threshold is applied, and to name
# the likely actual unit when it doesn't fit. It is a sanity check, not a proof
# -- it can't catch a unit swap that preserves magnitude -- but it turns the
# silent failure into a loud one.
#
# Each unit's cutoff is the value that unit's guidelines actually publish, not a
# conversion computed here. Those published equivalents are rounded (6.5% HbA1c
# is 47.5 mmol/mol but published as 48; 150 mg/dL of triglycerides is 1.694
# mmol/L but published as 1.7), so the same people converted between units can
# land a fraction of a percent either side of the line. That is the guidelines'
# rounding showing through, and it is the honest thing to report -- computing
# conversions on the fly would invent cutoffs no guideline ever wrote down.
#
# Sex-specific and age-specific thresholds are deliberately left out. Waist
# circumference (>102 cm in men, >88 cm in women) can't be applied as one number
# to a mixed column, so it isn't listed rather than being listed wrongly. And
# every threshold here is a screening line for adults, not a diagnosis: real
# classification needs repeat measurements and a clinician.
CLINICAL_THRESHOLDS = {
    "bmi": {
        "direction": "at_or_above",
        "source": "WHO adult obesity classification",
        "means": "BMI at or above 30 kg/m^2 is classified as obesity.",
        "default_unit": "kg/m^2",
        "units": {
            "kg/m^2": {"cutoff": 30.0, "plausible_median": (15.0, 45.0)},
        },
    },
    "systolicbp": {
        "direction": "at_or_above",
        "source": "2017 ACC/AHA hypertension guideline",
        "means": "Systolic 130 mmHg or higher meets the stage 1 hypertension line.",
        "default_unit": "mmHg",
        "units": {
            "mmHg": {"cutoff": 130.0, "plausible_median": (90.0, 180.0)},
            "kPa": {"cutoff": 17.3, "plausible_median": (12.0, 24.0)},
        },
    },
    "diastolicbp": {
        "direction": "at_or_above",
        "source": "2017 ACC/AHA hypertension guideline",
        "means": "Diastolic 80 mmHg or higher meets the stage 1 hypertension line.",
        "default_unit": "mmHg",
        "units": {
            "mmHg": {"cutoff": 80.0, "plausible_median": (50.0, 110.0)},
            "kPa": {"cutoff": 10.7, "plausible_median": (6.5, 14.5)},
        },
    },
    "totalcholesterol": {
        "direction": "at_or_above",
        "source": "NCEP ATP III",
        "means": "Total cholesterol at or above 240 mg/dL (6.2 mmol/L) is high.",
        "default_unit": "mg/dL",
        "units": {
            "mg/dL": {"cutoff": 240.0, "plausible_median": (120.0, 300.0)},
            # Cholesterol converts at 38.67 mg/dL per mmol/L.
            "mmol/L": {"cutoff": 6.2, "plausible_median": (3.1, 7.8)},
        },
    },
    "hdlcholesterol": {
        "direction": "below",
        "source": "NCEP ATP III",
        "means": "HDL below 40 mg/dL (1.03 mmol/L) counts as low -- a risk factor.",
        "default_unit": "mg/dL",
        "units": {
            "mg/dL": {"cutoff": 40.0, "plausible_median": (25.0, 90.0)},
            "mmol/L": {"cutoff": 1.03, "plausible_median": (0.65, 2.3)},
        },
    },
    "triglycerides": {
        "direction": "at_or_above",
        "source": "NCEP ATP III",
        "means": "Fasting triglycerides at or above 150 mg/dL (1.7 mmol/L).",
        "default_unit": "mg/dL",
        "units": {
            "mg/dL": {"cutoff": 150.0, "plausible_median": (50.0, 300.0)},
            # Triglycerides convert at 88.57 mg/dL per mmol/L -- a different
            # factor from cholesterol, which is why "lipids" is not one unit.
            "mmol/L": {"cutoff": 1.7, "plausible_median": (0.55, 3.4)},
        },
    },
    "hba1c": {
        "direction": "at_or_above",
        "source": "American Diabetes Association",
        "means": "HbA1c at or above 6.5% (48 mmol/mol) meets the diabetes line.",
        "default_unit": "%",
        "units": {
            # NGSP percent, what US labs and NHANES report.
            "%": {"cutoff": 6.5, "plausible_median": (4.0, 9.0)},
            # IFCC mmol/mol, standard in much of Europe.
            "mmol/mol": {"cutoff": 48.0, "plausible_median": (20.0, 75.0)},
        },
    },
    "hscrp": {
        "direction": "at_or_above",
        "source": "AHA/CDC cardiovascular risk statement",
        "means": "hs-CRP above 3.0 mg/L (0.3 mg/dL) is the higher-risk band.",
        "default_unit": "mg/L",
        "units": {
            "mg/L": {"cutoff": 3.0, "plausible_median": (0.3, 10.0)},
            "mg/dL": {"cutoff": 0.3, "plausible_median": (0.03, 1.0)},
        },
    },
}


# ======================================================================
# SHARED HELPERS -- the only functions outside the class.
#
# Each one is used by SEVERAL of DataAnalyzer's methods, so it cannot nest
# inside any one of them without being copied into the others. Everything
# used by a single tier is nested in that tier instead.
#
# Two groups: turning columns into numbers, and reporting a result.
# ======================================================================


def _coerce_numeric(series):
    """Parse a column as numbers, treating our analytic sentinel as missing.

    Every place in the engine that turns a raw column into numbers goes through
    here, so ANALYTIC_MISSING_SENTINEL can never sneak into a statistic -- the
    same reason _num() is the single exit every result leaves by. On datasets
    that don't use the sentinel the .replace() simply finds nothing.

    The result is always plain float64, and that last part is load-bearing.
    pd.to_numeric() preserves some dtypes that are arithmetically fine but are
    not what the numeric stack expects:

      * a bool column stays bool. True/False are perfectly good 1/0 for a mean,
        so the descriptive tiers never notice -- but hand a bool column to
        statsmodels and the design matrix it builds becomes numpy `object`,
        where the failure surfaces as "ufunc 'isfinite' not supported" from
        inside a VIF calculation, naming nothing that would lead you back here.
      * pandas' nullable extension dtypes (Int64, boolean, Float64) carry
        pd.NA rather than np.nan and also degrade to object on the way into
        numpy.

    Both break only the tiers that fit models -- advanced and expert -- and only
    once a dataset actually contains such a column, which is exactly the kind of
    bug that ships. Casting here fixes it once for every caller instead of at
    each of the half-dozen places a design matrix gets built.
    """
    numbers = pd.to_numeric(series, errors="coerce")
    numbers = numbers.replace(ANALYTIC_MISSING_SENTINEL, np.nan)
    return numbers.astype("float64")


def df_cleanup(df):
    """Normalize mixed and text-formatted numeric columns into real number columns.

    pandas.read_csv already infers dtypes, so a tidy all-digits column arrives as
    numbers without our help. This pass is for the columns it could NOT infer:
    ones where formatting ("$1,200") or a few stray text cells ("n/a", "missing")
    left the whole column as strings. For each column we strip "$" and ",", try
    to parse the cells as numbers, and keep the numeric version if at least 80%
    of them parse. It also re-scans already-numeric columns so the missing-value
    sentinel is mapped to NaN there too.

    Cells that still don't parse stay as NaN. We deliberately do NOT fill them in
    with the column mean: fake data points sitting exactly on the mean would
    inflate the sample size and shrink the variance and standard deviation -- the
    exact numbers this tool exists to report. The analysis methods drop the NaNs
    instead.
    """
    for col in df.columns:
        text = df[col].astype(str).str.replace(r"[$,]", "", regex=True)
        # _coerce_numeric drops the missing sentinel before we decide anything: a
        # column that is mostly sentinel is mostly missing, and shouldn't count as
        # numeric or feed the statistics.
        numbers = _coerce_numeric(text)
        if numbers.notna().mean() >= NUMERIC_THRESHOLD:
            df[col] = numbers
    return df


def _numbers(df, column):
    """One column as numbers, with unreadable and missing cells dropped."""
    return _coerce_numeric(df[column]).dropna()


def _numbers_for(df, *columns):
    """Several columns as numbers, keeping only rows where they are ALL present.
    Correlation and regression need matched-up rows, so a row with a gap in any
    one column has to go."""
    frame = df[list(columns)].apply(_coerce_numeric)
    return frame.dropna()


def _value_and_group(df, value_column, group_column):
    """The numeric column paired with a label column (age vs. sex, say), keeping
    only rows where both are present. The group column stays as labels; only the
    value column is turned into numbers."""
    data = df[[value_column, group_column]].copy()
    data[value_column] = _coerce_numeric(data[value_column])
    return data.dropna()


def _numeric_column_names(df):
    """Names of the columns that are numeric enough to analyze. These are the
    candidate predictors for the correlation and regression tiers."""
    return [
        col
        for col in df.columns
        if _coerce_numeric(df[col]).notna().mean() >= NUMERIC_THRESHOLD
    ]


def _other_numeric_columns(df, column):
    """Every numeric column except the one being analyzed."""
    return [c for c in _numeric_column_names(df) if c != column]


def _sorted_groups(data, group_column):
    """The distinct group labels in a sensible order.

    The sort key puts numbers before strings, because Python refuses to
    compare 3 < "adult" and would crash on a mixed column.
    """
    return sorted(data[group_column].unique(), key=lambda g: (isinstance(g, str), g))


def _num(x, ndigits=3):
    """Round a number so it is safe to send as JSON, or return None if it isn't
    a usable number.

    Statistics on odd input can come back as NaN or infinity (an empty group, a
    column where every value is identical, a regression that can't be solved).
    Those break JSON and, worse, can look like real answers. Every statistic that
    leaves this file goes through here, so a broken calculation shows up as a
    clean null on the website instead of garbage.
    """
    try:
        value = float(x)
    except TypeError, ValueError:
        return None
    if not np.isfinite(value):  # NaN or infinity
        return None
    return round(value, ndigits)


def _is_significant(p_value, alpha=ALPHA):
    """True if the p-value is real and below the significance cutoff.

    Mechanically this is just a comparison. What it does NOT mean is spelled out
    in P_VALUE_MEANING, which every test that calls this reports alongside it.
    """
    return bool(np.isfinite(p_value) and p_value < alpha)


def _magnitude(value, small, medium, large):
    """Bucket an effect size by the usual rule-of-thumb cutoffs.

    These conventions (Cohen's, mostly) are crude and field-agnostic: "small" in
    a lab experiment and "small" in a population health survey can be worlds
    apart in importance. The label is a starting point for judgment, not a
    verdict, so it always travels with the raw number.
    """
    magnitude = abs(value) if np.isfinite(value) else None
    if magnitude is None:
        return None
    if magnitude < small:
        return "negligible"
    if magnitude < medium:
        return "small"
    if magnitude < large:
        return "moderate"
    return "large"


def _significance_report(p_value, effect_size=None, alpha=ALPHA):
    """The standard block every hypothesis test in this engine returns.

    Keeping the p-value, its correct interpretation, and the effect size in one
    place is what stops "significant" from being read as "important". Anything
    with a p-value should return one of these.
    """
    report: dict[str, Any] = {
        "p_value": _num(p_value, 4),
        "alpha": alpha,
        "statistically_significant": _is_significant(p_value, alpha),
        "p_value_means": P_VALUE_MEANING,
        "caveat": SIGNIFICANCE_VS_IMPORTANCE,
    }
    if effect_size is not None:
        report["effect_size"] = effect_size
    return report


def _cramers_v(chi2, table):
    """Cramer's V: chi-square rescaled to 0-1 so sample size stops dominating.

    A chi-square statistic grows with n, so on 5,000 rows a trivial association
    produces an enormous one. V divides that back out and answers "how strongly
    are these two labels related", independent of how many rows you collected.
    Rough reading: 0.1 weak, 0.3 moderate, 0.5 strong.

    Out here rather than nested because two tiers report it: the medium tier's
    median-split chi-square and the categorical tier's contingency table, which
    should report the same number the same way.
    """
    counts = np.asarray(table)
    n = int(counts.sum())
    smaller_dimension = min(counts.shape) - 1
    if n <= 0 or smaller_dimension <= 0:
        return None

    v = float(np.sqrt(chi2 / (n * smaller_dimension)))
    return {
        "measure": "cramers_v",
        "value": _num(v),
        "magnitude": _magnitude(v, 0.1, 0.3, 0.5),
        "means": "Strength of association between the two labels (0-1).",
    }


class DataAnalyzer:
    """Runs statistics on one pandas DataFrame.

    Create it once with a cleaned DataFrame, then call whichever analysis tier
    you want:

        analyzer = DataAnalyzer(df_cleanup(pd.read_csv("data.csv")))
        analyzer.basic_analysis("age")

    Seven methods, listed in the module docstring, and each one holds every step
    it needs as a nested function.
    """

    def __init__(self, df):
        self.df = df

    # ==================================================================
    # TIER 1: BASIC -- the stats everyone knows.
    # ==================================================================

    def basic_analysis(self, column):
        """Mean, median, mode, range, and spread for one numeric column.

        Purely descriptive: these numbers summarize the rows in this file and make
        no claim about anyone outside it. Generalizing to a wider population
        starts at the medium tier, with confidence intervals.

        The only tier with nothing nested inside it -- every line below is the
        answer itself.
        """
        series = _numbers(self.df, column)
        if series.empty:
            return {"error": "No numeric values in that column."}

        # .mode() can return several values when there is a tie for most common,
        # so we report the whole list.
        modes = series.mode()
        mode_values = modes.tolist() if not modes.empty else float("nan")

        return {
            "layer": DESCRIPTIVE,
            "column": column,
            # How many values we actually used. Missing cells were dropped above,
            # so this can be smaller than the number of rows in the file.
            "n": int(series.count()),
            "mean": round(float(series.mean()), 3),
            "median": float(series.median()),
            "mode": mode_values,
            "min": float(series.min()),
            "max": float(series.max()),
            "std": round(float(series.std()), 3),  # typical distance from the mean
            "variance": round(float(series.var()), 3),  # std squared
        }

    # ==================================================================
    # TIER 2: MEDIUM -- the shape of the data, how sure we are, and
    # whether groups differ.
    # ==================================================================

    def medium_analysis(self, column, group_column=None):
        """Distribution shape, a confidence interval, and (optionally) tests for
        whether the groups in group_column differ.

        Nested below, in the order the answer uses them:

            distribution_metrics       quartiles, skew, kurtosis
              outlier_counts           two rules, and which one to trust here
              log_transform            does taking logs straighten this out?
            uncertainty_metrics        standard error and a 95% interval
            group_tests                do the groups differ?
              anova                    the test to read
                eta_squared            ...and how much the difference matters
              median_split_chi_square  the deliberately cruder companion
                describe_test_statistic
        """
        import scipy.stats as sp

        series = _numbers(self.df, column)
        if series.empty:
            return {"error": "No numeric values in that column."}

        def distribution_metrics(series):
            """What shape is this data? Quartiles, spread, lopsidedness, outliers."""
            q1 = series.quantile(0.25)  # 25% of values are below this
            median = series.median()  # the middle value
            q3 = series.quantile(0.75)  # 75% of values are below this
            iqr = q3 - q1  # the middle half of the data
            skewness = series.skew()  # + = long tail on the right, - = on the left
            kurtosis = series.kurtosis()  # how heavy the tails are

            return {
                "layer": DESCRIPTIVE,
                "q1": _num(q1),
                "median": _num(median),
                "q3": _num(q3),
                "iqr": _num(iqr),
                "skewness": _num(skewness),
                "kurtosis": _num(kurtosis),
                "outliers": outlier_counts(series, q1, q3, iqr, skewness),
                "log_transform": log_transform(series, skewness),
            }

        def outlier_counts(series, q1, q3, iqr, skewness):
            """Count unusually extreme values under two different rules.

            There is no such thing as THE outlier count -- it depends entirely on
            the rule you pick, so we report both common ones and say which suits
            the data.

            z-score (more than 3 SDs from the mean) assumes a roughly symmetric,
            bell-shaped distribution. On a right-skewed variable -- which
            describes most biomedical measurements, triglycerides and insulin
            especially -- the long tail drags the mean up and inflates the SD, so
            the rule flags far too few high values and sometimes no low ones at
            all.

            Tukey's IQR rule (outside Q1 - 1.5*IQR to Q3 + 1.5*IQR) is built from
            quartiles, which the tail doesn't move nearly as much, so it holds up
            better on skewed data.

            Flagged is not the same as wrong: an extreme value can be a data-entry
            error or a genuinely extreme person, and only looking at the record
            tells you which. Nothing here is dropped -- these are counts, not a
            filter.
            """
            counts: dict[str, Any] = {}

            # If every value is identical the SD is 0 and dividing by it gives NaN.
            std = series.std()
            if std and np.isfinite(std) and std != 0:
                z_scores = (series - series.mean()) / std
                counts["z_score_gt_3"] = int((z_scores.abs() > 3).sum())
            else:
                counts["z_score_gt_3"] = 0

            # An IQR of zero means the middle half of the data is a single
            # repeated value, so the fences collapse onto it and the rule would
            # flag every other value in the column. That is a degenerate answer,
            # not a count of zero outliers, so we say the rule doesn't apply
            # instead of reporting a number that would be read as "none found".
            iqr_applies = bool(np.isfinite(iqr) and iqr > 0)
            if iqr_applies:
                lower_fence = q1 - 1.5 * iqr
                upper_fence = q3 + 1.5 * iqr
                counts["iqr_rule"] = int(
                    ((series < lower_fence) | (series > upper_fence)).sum()
                )
                counts["iqr_fences"] = [_num(lower_fence), _num(upper_fence)]
            else:
                counts["iqr_rule"] = None
                counts["iqr_fences"] = None
                counts["iqr_rule_note"] = (
                    "Not applicable: the interquartile range is zero, so at least "
                    "half the values are identical and the fences have no width."
                )

            skewed = bool(np.isfinite(skewness) and abs(skewness) > 1)
            if skewed and iqr_applies:
                counts["recommended_rule"] = "iqr_rule"
                counts["why"] = (
                    "This column is skewed (|skewness| > 1), so the quartile-based "
                    "IQR rule is the more trustworthy of the two."
                )
            elif skewed:
                counts["recommended_rule"] = "z_score_gt_3"
                counts["why"] = (
                    "This column is skewed, which normally favours the IQR rule, but "
                    "the IQR is zero here so only the z-score rule can be computed. "
                    "Treat its count with caution."
                )
            else:
                counts["recommended_rule"] = "z_score_gt_3"
                counts["why"] = (
                    "This column is roughly symmetric, so both rules are reasonable."
                )
            return counts

        def log_transform(series, skewness):
            """Badly lopsided data (skew above 1 either way) often straightens out
            if you take the logarithm of every value, which makes other tests
            behave better. We only try it when every value is positive -- the log
            of zero or a negative number is undefined and would quietly produce
            NaN.
            """
            can_take_log = abs(skewness) > 1 and bool((series > 0).all())
            if not can_take_log:
                return {"applied": False, "skewness": None}
            return {"applied": True, "skewness": _num(np.log(series).skew())}

        def uncertainty_metrics(series):
            """How precise is our estimate of the mean?

            We report the standard error (how much the sample mean would bounce
            around if we collected the data again) and a 95% confidence interval.

            The interval is a statement about the PROCEDURE: if you repeated the
            whole study many times, intervals built this way would contain the
            true population mean 95% of the time. It is not "a 95% chance the true
            mean is inside this particular interval" -- that interval either
            contains it or it doesn't. It also only covers random sampling error;
            it says nothing about selection bias, measurement error, or a survey
            design (NHANES has one) that the calculation ignores.
            """
            n = int(series.count())
            if n < 2:
                # With one value there is nothing to be uncertain about yet -- the
                # math would divide by zero. Say so instead of returning NaN.
                return {
                    "n": n,
                    "sem": None,
                    "ci_lower": None,
                    "ci_upper": None,
                    "confidence_level": 0.95,
                    "error": "Need at least 2 values for a confidence interval.",
                }

            mean = float(series.mean())
            standard_error = float(series.sem())
            # The t-distribution's cutoff for 95% confidence. 0.975 (not 0.95)
            # because we leave 2.5% of the probability in each tail.
            t_critical = sp.t.ppf(0.975, df=n - 1)
            margin = t_critical * standard_error

            return {
                "layer": INFERENTIAL,
                "n": n,
                "sem": _num(standard_error),
                "ci_lower": _num(mean - margin),
                "ci_upper": _num(mean + margin),
                "confidence_level": 0.95,
                "covers": (
                    "Random sampling error only, assuming a simple random sample."
                ),
            }

        def group_tests(value_column, group_column):
            """Do the groups actually differ? A primary test and a coarser
            companion.

            ANOVA is the one to read: it uses the values as they are and asks
            whether the group AVERAGES differ. The median-split chi-square asks a
            deliberately cruder question -- is landing in the top half associated
            with the group -- and is included for teaching contrast, not because
            it is a better test. See median_split_chi_square for why it is the
            weaker of the two.
            """
            data = _value_and_group(self.df, value_column, group_column)
            groups = [g[value_column].to_numpy() for _, g in data.groupby(group_column)]

            return {
                "layer": INFERENTIAL,
                "group_column": group_column,
                "n_groups": len(groups),
                "not_causal": NOT_CAUSAL,
                "primary_test": "anova",
                "anova": anova(groups),
                "median_split_chi_square": median_split_chi_square(
                    data, value_column, group_column
                ),
            }

        def anova(groups):
            """One-way ANOVA: do the group means differ by more than chance?

            Reports eta-squared alongside the p-value: the share of the total
            variation in the values that sits BETWEEN groups rather than within
            them. That is the "how much does it matter" number. With NHANES-sized
            samples a p-value near zero routinely comes with an eta-squared of
            0.01, meaning the groups are reliably different and the difference
            explains 1% of what is going on -- both true at once.
            """
            # Needs at least 2 groups, and at least 2 values per group (one value
            # has no spread, so there is nothing to compare the difference
            # against).
            if len(groups) < 2 or not all(len(g) >= 2 for g in groups):
                return {"error": "Need >= 2 groups with >= 2 values each for ANOVA."}

            f_statistic, p_value = sp.f_oneway(*groups)
            result = {
                "test": "one-way ANOVA",
                "f_statistic": _num(f_statistic),
                "assumes": (
                    "Roughly normal values within each group and similar spreads "
                    "across groups; check the distribution block above."
                ),
            }
            result.update(_significance_report(p_value, eta_squared(groups)))
            return result

        def eta_squared(groups):
            """Eta-squared: the fraction of variation explained by group membership.

            Between-group sum of squares over total sum of squares. Cohen's rough
            cutoffs are 0.01 small / 0.06 medium / 0.14 large, and they are rough
            -- what counts as a meaningful gap in blood pressure is a clinical
            question, not a statistical one.
            """
            values = np.concatenate(groups)
            grand_mean = values.mean()
            total = float(((values - grand_mean) ** 2).sum())
            if total <= 0:  # every value identical; nothing to explain
                return None

            between = float(sum(len(g) * (g.mean() - grand_mean) ** 2 for g in groups))
            eta = between / total
            return {
                "measure": "eta_squared",
                "value": _num(eta),
                "magnitude": _magnitude(eta, 0.01, 0.06, 0.14),
                "means": "Share of the total variation that lies between groups (0-1).",
            }

        def median_split_chi_square(data, value_column, group_column):
            """Chi-square on a deliberately coarsened version of the values.

            Chi-square compares two label columns, so we manufacture one: tag every
            row "high" or "low" depending on whether it beats the overall median,
            then ask whether that split looks the same across groups.

            WHY THIS IS THE WEAKER TEST. Cutting a continuous measurement in two
            throws away most of what it told you. Someone one unit above the median
            and someone three standard deviations above it both become "high", while
            two people either side of the median by a hair land in opposite
            categories. That costs real statistical power, and the median is a
            property of whoever happens to be in this dataset, so the same person can
            be "high" in one sample and "low" in another.

            It is here because it is easy to picture and it demonstrates the test.
            When the outcome is a number, ANOVA (or a regression) is the better tool.
            """
            median = data[value_column].median()
            level = np.where(data[value_column] > median, "high", "low")
            table = pd.crosstab(level, data[group_column])

            # The test needs both variables to actually vary -- at least 2 rows and
            # 2 columns in the table.
            if table.shape[0] < 2 or table.shape[1] < 2:
                return {"error": "Need a 2xN table (both variables must vary)."}

            chi2, _p, degrees_of_freedom, _expected = sp.chi2_contingency(table)
            result = describe_test_statistic(chi2, df=degrees_of_freedom)
            result["method"] = "median split (continuous values dichotomized)"
            result["split_at"] = _num(median)
            result["information_loss"] = (
                "The values were reduced to high/low at this dataset's median, "
                "discarding how far above or below each one sat. Prefer the ANOVA "
                "result; this is the demonstration, not the recommendation."
            )
            result["effect_size"] = _cramers_v(chi2, table)
            return result

        def describe_test_statistic(statistic, df=None, alpha=ALPHA):
            """Turn a raw test statistic into a p-value and a plain-English verdict.

            If we're given degrees of freedom, the statistic is a chi-square (we
            want the chance of getting one this big or bigger). Without them, it's
            a z-score from a normal distribution (we want both tails, so we
            double).
            """
            if df is not None:
                p_value = float(sp.chi2.sf(statistic, df))
            else:
                p_value = float(2 * sp.norm.sf(abs(statistic)))

            result = {
                "statistic": _num(statistic),
                # scipy hands back a numpy integer, which JSON can't serialize.
                # Plain int() fixes it.
                "df": int(df) if df is not None else None,
            }
            result.update(_significance_report(p_value, alpha=alpha))
            return result

        result: dict[str, Any] = {
            "column": column,
            "distribution": distribution_metrics(series),
            "uncertainty": uncertainty_metrics(series),
        }
        if group_column is not None:
            result["groups"] = group_tests(column, group_column)
        return result

    # ==================================================================
    # TIER 3: ADVANCED -- how columns relate to each other.
    # ==================================================================

    def advanced_analysis(
        self,
        column,
        group_column=None,
        exposure=None,
        confounders=None,
        mediator=None,
    ):
        """Correlation with the other numeric columns, a regression predicting
        this column from them, and -- only if you name the roles -- an adjusted
        association.

        The adjustment block stays empty unless you pass `exposure` (the variable
        whose association you care about) and `confounders` (what to hold
        constant). The engine will not guess those for you; see
        covariate_adjustment for why guessing is the one thing it must not do.

            analyzer.advanced_analysis("blood_pressure")            # no adjustment
            analyzer.advanced_analysis(
                "blood_pressure", exposure="bmi", confounders=["age", "sex"]
            )

        Nested below:

            correlation            do two columns move together?
            regression             predict this column from the others
              build_design_matrix  numeric predictors, and labels one-hot encoded
              standardized_betas   coefficients put on a common scale
            adjustment_block       run the adjustment, or explain why we didn't
              covariate_adjustment crude vs. adjusted, plus mediation
            linear_trend           does the value climb steadily across groups?
        """
        import scipy.stats as sp

        series = _numbers(self.df, column)
        if series.empty:
            return {"error": "No numeric values in that column."}

        def correlation(column1, column2):
            """Pearson correlation: do these two columns move together?

            r runs from -1 (perfect opposite) through 0 (unrelated) to +1 (perfect
            match). The p-value says whether an r that size could just be luck; r
            itself is the effect size, and r-squared is the share of one column's
            variation that lines up with the other's.

            Pearson only sees STRAIGHT-LINE relationships. A strong curved
            relationship -- common in biology, where a measurement can be dangerous
            at both extremes -- can produce an r near zero. A near-zero r means "no
            linear association", not "no relationship".
            """
            data = _numbers_for(self.df, column1, column2)
            if len(data) < 3:
                return {"error": "Not enough overlapping numeric values."}

            r, p_value = sp.pearsonr(data[column1], data[column2])
            result = {
                "layer": INFERENTIAL,
                "r": _num(r),
                "r_squared": _num(r**2),
                "n": int(len(data)),
                "not_causal": NOT_CAUSAL,
            }
            result.update(
                _significance_report(
                    p_value,
                    {
                        "measure": "pearson_r",
                        "value": _num(r),
                        "magnitude": _magnitude(r, 0.1, 0.3, 0.5),
                        "means": (
                            f"The two columns share {_num(r**2 * 100, 1)}% of their "
                            "variation, along a straight line."
                        ),
                    },
                )
            )
            return result

        def build_design_matrix(x_columns):
            """Assemble the predictor columns for a regression.

            Numeric predictors go in as they are. A label predictor
            ("male"/"female") has to become numbers first, so we one-hot encode it:
            one 0/1 column per category. drop_first=True leaves one category out as
            the baseline that the others are measured against -- keeping all of
            them would make the columns add up to a constant and the regression
            unsolvable.
            """
            parts = []
            for name in x_columns:
                values = self.df[name]
                numbers = _coerce_numeric(values)
                if numbers.notna().mean() >= NUMERIC_THRESHOLD:
                    parts.append(numbers.rename(name))
                else:
                    parts.append(
                        pd.get_dummies(
                            values, prefix=name, drop_first=True, dtype=float
                        )
                    )
            return pd.concat(parts, axis=1)

        def regression(y_column, x_columns, weights=None):
            """Predict y_column from the other columns with a straight-line fit.

            Ordinary least squares (OLS) finds the line closest to all the points.
            Pass a weights column to make some rows count more than others
            (weighted least squares, which survey data often needs).
            """
            try:
                import statsmodels.api as smapi

                y = _coerce_numeric(self.df[y_column])
                design = build_design_matrix(x_columns)
                # Line up outcome and predictors, then keep only complete rows.
                frame = pd.concat([y.rename(y_column), design], axis=1).dropna()

                # Weights have to be matched to the rows that survived, and a row
                # with a missing weight has to go -- a single NaN weight turns the
                # entire fit into NaNs.
                row_weights = None
                if weights is not None:
                    row_weights = _coerce_numeric(self.df[weights]).reindex(frame.index)
                    frame = frame[row_weights.notna()]
                    row_weights = row_weights.dropna()

                predictors = [c for c in frame.columns if c != y_column]
                # You need more data points than things you're estimating, or the
                # fit is meaningless (it can pass perfectly through every point).
                if len(frame) <= len(predictors) + 1:
                    return {"error": "Too few complete rows for this many predictors."}

                outcome = frame[y_column]
                # add_constant adds a column of 1s so the line can have an intercept
                # instead of being forced through the origin.
                design_with_intercept = smapi.add_constant(frame[predictors])

                if row_weights is not None:
                    model = smapi.WLS(
                        outcome, design_with_intercept, weights=row_weights
                    ).fit()
                else:
                    model = smapi.OLS(outcome, design_with_intercept).fit()

                return {
                    "layer": PREDICTIVE,
                    "outcome": y_column,
                    "predictors": predictors,
                    # nobs is just the rows that survived filtering above;
                    # len(outcome) is the same count and stays a plain int the type
                    # checker accepts.
                    "n": int(len(outcome)),
                    # R-squared: the fraction of the outcome's variation the model
                    # explains, from 0 (none) to 1 (all of it).
                    "r_squared": _num(model.rsquared),
                    # Adjusted R-squared penalizes you for adding useless predictors.
                    "adj_r_squared": _num(model.rsquared_adj),
                    "coefficients": {k: _num(v) for k, v in model.params.items()},
                    "p_values": {k: _num(v, 4) for k, v in model.pvalues.items()},
                    "standardized_betas": standardized_betas(
                        model, design_with_intercept, outcome
                    ),
                    "weighted": weights is not None,
                    "coefficients_mean": (
                        "Each coefficient is the average difference in the outcome "
                        "between rows that differ by one unit in that predictor while "
                        "the other predictors in the model sit at the same values. "
                        "That is a description of this fitted surface, not a "
                        "prediction of what would happen if someone's value changed."
                    ),
                    "not_causal": NOT_CAUSAL,
                }
            except Exception as exc:  # unsolvable matrix, an all-NaN column, etc.
                return {"error": f"Regression failed: {exc}"}

        def standardized_betas(model, design, outcome):
            """Coefficients rescaled so their sizes can be compared to each other.

            A raw coefficient is in the predictor's own units, so "per year of age"
            and "per pound of weight" can't be ranked directly. Multiplying by
            (predictor's spread / outcome's spread) restates each one as "standard
            deviations of outcome per standard deviation of predictor", which puts
            them on a common scale.

            WHAT A BIG BETA DOES NOT MEAN. It is not proof that the predictor is the
            most important, or the most causally influential, or the best lever to
            pull. The ranking depends on the spreads in THIS sample (a predictor with
            little variation here gets a small beta even if it matters enormously),
            on which other predictors happen to be in the model, and on the linear
            form we imposed. Correlated predictors trade credit between themselves
            almost arbitrarily -- see the multicollinearity check in the expert tier.
            Read a large beta as "the strongest association in this particular model",
            and nothing more.
            """
            outcome_std = outcome.std()
            betas = {
                name: (
                    _num(coefficient * design[name].std() / outcome_std)
                    if outcome_std
                    else None
                )
                for name, coefficient in model.params.items()
                if name != "const"  # the intercept isn't a predictor
            }
            return {
                "values": betas,
                "units": "SDs of outcome per SD of predictor",
                "caveat": (
                    "A larger beta means a larger association under this model and "
                    "this sample's spreads. It does not rank predictors by importance "
                    "or causal influence."
                ),
            }

        def adjustment_block(exposure, confounders, mediator):
            """Run the adjusted-association analysis, or explain why we didn't.

            Previously this tier picked the exposure and confounders off the front
            of the column list and adjusted away. That was the most dangerous thing
            in the engine: the arithmetic was right and the meaning was invented.
            Now a missing role produces this explanation instead of a fabricated
            causal story.
            """
            if exposure is None:
                return {
                    "status": "not_run",
                    "reason": (
                        "No exposure was named. Deciding which variable is the "
                        "exposure and which are confounders is a claim about how the "
                        "world works, and it has to come from subject-matter "
                        "knowledge -- the engine cannot read it off the data."
                    ),
                    "how_to_run": (
                        "Pass exposure='...' and confounders=['...'] (optionally "
                        "mediator='...') to advanced_analysis()."
                    ),
                    "why_it_is_not_automatic": (
                        "Column order in a CSV carries no causal information. Picking "
                        "the first spare column as the exposure and the rest as "
                        "confounders would produce a confident-looking number with no "
                        "justification behind it -- and adjusting for the wrong "
                        "variable can bias an estimate as easily as ignoring the right "
                        "one. Controlling for a mediator hides part of the very "
                        "relationship you are measuring, and controlling for a common "
                        "consequence of two variables can manufacture an association "
                        "that isn't there at all."
                    ),
                    "candidates": _other_numeric_columns(self.df, column),
                }

            return covariate_adjustment(
                outcome=column,
                exposure=exposure,
                confounders=confounders,
                mediator=mediator,
            )

        def covariate_adjustment(outcome, exposure, confounders=None, mediator=None):
            """How much does the exposure's association move when we hold other
            variables constant?

            THE ROLES COME FROM YOU, NOT FROM THE DATA. "Confounder", "mediator" and
            "exposure" are claims about causal structure, and no test can read them
            off a spreadsheet. The classic confounder makes a fake link look real:
            ice-cream sales and drownings rise together because summer drives both.
            A mediator sits ON the path instead (exercise -> lower weight -> lower
            blood pressure). The arithmetic below is identical either way -- fit the
            model twice, once with the extra variables and once without -- and only
            your labeling says which story the difference tells. Get the roles
            backwards and the numbers are still computed correctly and mean something
            entirely different:

              * adjusting for a MEDIATOR removes part of the very relationship you
                are trying to measure, shrinking the estimate for the wrong reason;
              * adjusting for a COLLIDER (something both variables affect) can
                conjure an association out of two unrelated variables.

            So this reports "crude" and "adjusted" ASSOCIATIONS, and how far apart
            they are. A large gap means the two models disagree about the exposure --
            worth understanding. It does not confirm confounding, and a small gap does
            not rule it out: unmeasured confounders leave no trace here at all,
            because nothing in this dataset can detect a variable the dataset lacks.
            """
            try:
                import statsmodels.api as smapi

                missing = [
                    name
                    for name in [
                        outcome,
                        exposure,
                        *(confounders or []),
                        *([mediator] if mediator else []),
                    ]
                    if name not in self.df.columns
                ]
                if missing:
                    return {"error": f"Column(s) not in the dataset: {missing}"}

                def association_of_exposure(predictors):
                    """Fit outcome ~ predictors, return the exposure's coefficient."""
                    frame = _numbers_for(self.df, outcome, *predictors)
                    model = smapi.OLS(
                        frame[outcome], smapi.add_constant(frame[list(predictors)])
                    ).fit()
                    return model.params[exposure]

                # "Crude" = the exposure's association with nothing else in the model.
                crude = association_of_exposure([exposure])
                result: dict[str, Any] = {
                    "layer": PREDICTIVE,
                    "status": "ran",
                    "outcome": outcome,
                    "exposure": exposure,
                    "roles_supplied_by": "caller",
                    "crude_association": _num(crude),
                    "not_causal": (
                        "Adjusted associations are still associations. Reporting them "
                        "as effects would claim a causal model this engine was never "
                        "given."
                    ),
                }

                if confounders:
                    adjusted = association_of_exposure([exposure, *confounders])
                    # How far did the estimate move once the covariates were in?
                    # (Guard against a crude estimate of exactly 0, which we can't
                    # divide by.)
                    percent_change = (
                        abs((crude - adjusted) / crude) * 100 if crude else None
                    )
                    result["adjusted_association"] = _num(adjusted)
                    result["adjusted_for"] = list(confounders)
                    result["percent_change"] = _num(percent_change, 1)
                    # Deliberately named for what was observed -- the estimate moved --
                    # rather than "confounding_detected", which would assert a cause we
                    # cannot verify. The 10% line is a common epidemiological rule of
                    # thumb, not a test with a p-value.
                    result["estimate_moved_over_10_percent"] = bool(
                        percent_change is not None and percent_change > 10
                    )
                    result["reading_the_change"] = (
                        "The two models disagree about the exposure by this much. "
                        "Whether that is confounding, mediation, collider bias or "
                        "noise depends on the causal roles you assigned, which the "
                        "data cannot check."
                    )

                if mediator:
                    direct = association_of_exposure([exposure, mediator])
                    indirect = crude - direct
                    result["mediation"] = {
                        "mediator": mediator,
                        "total_association": _num(crude),
                        "direct_association": _num(direct),
                        "indirect_association": _num(indirect),
                        "proportion_via_mediator": (
                            _num(indirect / crude) if crude else None
                        ),
                        "assumes": (
                            "This difference-of-coefficients split is only a mediation "
                            "decomposition if the mediator really lies on the causal "
                            "path, the outcome model is linear with no "
                            "exposure-mediator interaction, and nothing unmeasured "
                            "confounds the mediator-outcome pair. Those assumptions "
                            "are asserted here, never tested."
                        ),
                    }
                return result
            except Exception as exc:
                return {"error": f"Adjustment analysis failed: {exc}"}

        def linear_trend(column, group_column):
            """Does the value climb (or fall) steadily as you move across the groups?

            We put the groups in order, number them 0, 1, 2, ..., and fit a line
            through (group number, value). A significant slope means a steady climb
            or fall, which is a more specific finding than ANOVA's "the groups differ
            somehow".

            Numbering the groups 0, 1, 2 asserts that they are ORDERED and evenly
            spaced. That is fair for age brackets or income bands; it is meaningless
            for unordered labels like region or race, where the "trend" would just
            track how the categories happened to sort. Check the group_order in the
            output before reading anything into the slope.
            """
            data = _value_and_group(self.df, column, group_column)
            groups = _sorted_groups(data, group_column)
            if len(data) < 3 or len(groups) < 2:
                return {"error": "Need >= 2 ordered groups with >= 3 total values."}

            group_number = {group: i for i, group in enumerate(groups)}
            x = data[group_column].map(group_number).astype(float)
            line = sp.linregress(x, data[column].astype(float))

            result = {
                "layer": INFERENTIAL,
                "group_column": group_column,
                "n_groups": len(groups),
                "group_order": [str(g) for g in groups],
                "slope": _num(line.slope),  # change in value per step up the groups
                "r": _num(line.rvalue),
                "assumes": "The groups above are genuinely ordered and evenly spaced.",
                "not_causal": NOT_CAUSAL,
            }
            result.update(
                _significance_report(
                    line.pvalue,
                    {
                        "measure": "pearson_r",
                        "value": _num(line.rvalue),
                        "magnitude": _magnitude(line.rvalue, 0.1, 0.3, 0.5),
                        "means": (
                            "How tightly the group averages follow a straight line."
                        ),
                    },
                )
            )
            return result

        others = _other_numeric_columns(self.df, column)
        result: dict[str, Any] = {
            "column": column,
            "correlations": {other: correlation(column, other) for other in others},
            "regression": regression(column, others),
            "adjustment": adjustment_block(exposure, confounders, mediator),
        }

        if group_column is not None:
            result["trend"] = linear_trend(column, group_column)
        return result

    # ==================================================================
    # TIER 4: EXPERT -- checking whether the models above can be trusted.
    # ==================================================================

    def expert_analysis(
        self,
        column,
        group_column=None,
        clinical_cutoff=None,
        cutoff_direction=None,
        units=None,
    ):
        """Collinearity between predictors, checks on the regression's residuals,
        and threshold counts.

        Pass clinical_cutoff to classify against a real medical threshold (and
        cutoff_direction, "at_or_above" or "below", to say which side counts).
        Leave it out and the engine looks the column up in CLINICAL_THRESHOLDS;
        if it isn't there, you get only the dataset median split, which is a
        description of this sample and not a clinical finding.

        Pass units to say what the column is recorded in ("mmol/L", "mmol/mol")
        and get that unit's cutoff. Left out, the engine assumes the table's
        default unit and verifies that assumption against the data before
        applying anything -- see check_units.

        Nested below:

            multicollinearity           are the predictors saying the same thing?
            regression_diagnostics      fit the model and look at what it missed
              residual_checks           are those misses well-behaved?
            clinical_threshold_analysis count against a REAL published cutoff
              check_units               ...but only if the units check out
              count_against_cutoff      the tally itself
            dataset_median_split        count against this sample's own median
            descriptive_ratios          trig/HDL, reported without a cutoff
            trend_in_proportions        does the share of "high" values climb?
              cochran_armitage
        """
        import scipy.stats as sp

        series = _numbers(self.df, column)
        if series.empty:
            return {"error": "No numeric values in that column."}

        def multicollinearity(x_columns):
            """Are the predictors telling us the same thing twice?

            If height-in-inches and height-in-cm are both predictors, the regression
            can't tell which one deserves the credit and its numbers get unstable.
            The variance inflation factor (VIF) measures this per predictor; above 10
            is the usual "this one is redundant" alarm.
            """
            try:
                import statsmodels.api as smapi
                from statsmodels.stats.outliers_influence import (
                    variance_inflation_factor,
                )

                frame = _numbers_for(self.df, *x_columns)
                # add_constant sticks a "const" column of 1s on the front. Take the
                # names from the result it actually produced, not from an assumed
                # layout: if a predictor is already constant (which the complete-case
                # filtering above can cause) add_constant skips its own column, and a
                # hand-built ["const", ...] list would then be one name too long.
                # add_constant returns a DataFrame here (it's given one), but the
                # stubs type it as a bare ndarray -- cast so .columns resolves.
                design = cast(pd.DataFrame, smapi.add_constant(frame))
                matrix = np.asarray(design)
                names = list(design.columns)

                vifs = {
                    name: _num(variance_inflation_factor(matrix, i))
                    for i, name in enumerate(names)
                    if name != "const"  # the intercept has no VIF worth reporting
                }
                return {
                    "layer": PREDICTIVE,
                    "n": int(len(frame)),
                    "vif": vifs,
                    "high_multicollinearity": [
                        name
                        for name, vif in vifs.items()
                        if vif is not None and vif > 10
                    ],
                    "note": (
                        "10 is a rule of thumb, not a law; 5 is also widely used. High "
                        "VIF inflates the standard errors of the affected coefficients "
                        "and makes them unstable, which is exactly why a large "
                        "standardized beta among correlated predictors shouldn't be "
                        "read as 'this one matters most'. It does not hurt the model's "
                        "overall predictions or R-squared."
                    ),
                }
            except Exception as exc:
                return {"error": f"VIF computation failed: {exc}"}

        def regression_diagnostics(column, others):
            """Fit column ~ the other numeric columns and inspect what's left over.

            The residuals are the model's misses (actual minus predicted). If the
            model is any good, the misses should be small, centered on zero, and
            randomly scattered -- not patterned.
            """
            try:
                import statsmodels.api as smapi

                frame = _numbers_for(self.df, column, *others)
                if len(frame) <= len(others) + 1:  # not enough rows to fit
                    return None
                model = smapi.OLS(
                    frame[column], smapi.add_constant(frame[others])
                ).fit()
                return residual_checks(model.resid)
            except Exception as exc:
                return {"error": f"Diagnostics failed: {exc}"}

        def residual_checks(residuals):
            """Are the model's leftover errors well-behaved?

            Shapiro-Wilk asks whether the residuals are consistent with a normal bell
            curve. Read its result carefully in BOTH directions:

              * a small p-value says the residuals are detectably non-normal;
              * a large p-value does NOT establish that they are normal. It means the
                test found insufficient evidence against normality, which on a small
                sample mostly reflects the test having little power to find anything.

            Sample size cuts both ways, and that is why this is reported rather than
            used as a gate. On tens of thousands of NHANES rows Shapiro-Wilk will flag
            deviations far too small to affect the regression -- least squares
            estimates stay unbiased regardless of residual shape, and with a sample
            this large the central limit theorem keeps the standard errors roughly
            honest anyway. So we also report the residuals' skewness and kurtosis: a
            picture of HOW non-normal they are is more useful than a yes/no verdict on
            WHETHER they are.
            """
            resid = pd.Series(residuals).dropna().astype(float)
            n = int(len(resid))
            checks: dict[str, Any] = {
                "layer": PREDICTIVE,
                "n": n,
                "mean_residual": _num(resid.mean()),
                "skewness": _num(resid.skew()),
                "kurtosis": _num(resid.kurtosis()),
            }

            if n >= 3:  # Shapiro-Wilk's minimum sample size
                statistic, p_value = sp.shapiro(resid)
                detectably_non_normal = _is_significant(p_value)
                normality: dict[str, Any] = {
                    "test": "shapiro-wilk",
                    "statistic": _num(statistic),
                    "p_value": _num(p_value, 4),
                    # Named for what the test can actually support. The old key was
                    # "normal_residuals", which turned "we failed to reject" into "it's
                    # normal" -- the classic way to misread a goodness-of-fit test.
                    "detectably_non_normal": detectably_non_normal,
                    "means": (
                        "The residuals deviate from a normal curve by more than "
                        "sampling noise explains. Check the skewness and kurtosis "
                        "above to see whether the deviation is large enough to care "
                        "about -- at this sample size it often isn't."
                        if detectably_non_normal
                        else "No detectable departure from normality. That is an "
                        "absence of evidence, not evidence the residuals are normal."
                    ),
                    "caveat": (
                        "Shapiro-Wilk gets more sensitive as n grows: on large samples "
                        "it rejects trivial deviations, and on small ones it misses "
                        "real ones. Treat it as one input, not a pass/fail gate."
                    ),
                }
                # scipy warns about this itself above n = 5000, which is most of our
                # NHANES columns -- so the p-value is doubly weak evidence here.
                if n > 5000:
                    normality["accuracy_warning"] = (
                        f"n = {n}. scipy's Shapiro-Wilk p-value is only approximate "
                        "above 5,000 observations. Read the skewness and kurtosis, or "
                        "a Q-Q plot, instead of this p-value."
                    )
                checks["normality"] = normality

            std = resid.std()
            if std and np.isfinite(std) and std != 0:
                z_scores = (resid - resid.mean()) / std
                checks["large_residuals"] = {
                    "count": int((z_scores.abs() > 3).sum()),
                    "rule": "more than 3 SDs from the mean residual",
                    "note": (
                        "These are points the model fits poorly. That is not the same "
                        "as an influential point, which is one that visibly moves the "
                        "fitted line -- measuring that needs leverage or Cook's "
                        "distance, which this block does not compute."
                    ),
                }
            return checks

        def check_units(series, reference, declared_unit=None):
            """Work out which unit a column is in before applying a threshold to it.

            A cutoff is only meaningful in the unit it was written for, and a unit
            swap is invisible to the arithmetic: apply the 150 mg/dL triglyceride
            line to mmol/L data and every row passes, so the engine cheerfully reports
            that nobody in the population is at risk. That is the same failure as the
            missing-value sentinel -- code that runs correctly and means something
            else -- and it deserves the same treatment: catch it on the way in.

            The check is possible because unit systems differ by roughly an order of
            magnitude. Each unit in CLINICAL_THRESHOLDS carries the band a population
            median plausibly falls in, and those bands don't overlap, so the column's
            own median identifies the unit. Returns one of:

                declared    the caller named the unit; we use it, no guessing
                consistent  the median fits the default unit's band
                mismatch    it doesn't -- and we name the unit it does fit, if any

            The median is the right statistic here: it survives the outliers and long
            tails these variables are full of, so the verdict reflects the bulk of the
            column rather than its extremes. What this CANNOT catch is a swap that
            preserves magnitude (mg/dL vs. mg/100mL, which are the same number), or a
            column whose values are wrong in some other way entirely.
            """
            units = reference["units"]
            median = float(series.median())

            if declared_unit is not None:
                if declared_unit not in units:
                    return {
                        "status": "unknown_unit",
                        "declared_unit": declared_unit,
                        "known_units": sorted(units),
                    }
                return {
                    "status": "declared",
                    "unit": declared_unit,
                    "observed_median": _num(median),
                }

            def fits(unit_name):
                low, high = units[unit_name]["plausible_median"]
                return low <= median <= high

            default_unit = reference["default_unit"]
            low, high = units[default_unit]["plausible_median"]
            if fits(default_unit):
                return {
                    "status": "consistent",
                    "unit": default_unit,
                    "observed_median": _num(median),
                    "expected_median_range": [low, high],
                }

            # The median is outside the assumed unit's band. See whether it lands
            # squarely inside another unit we know this measurement is reported in --
            # that turns "these numbers look wrong" into "these look like mmol/L".
            suspected = next((u for u in units if u != default_unit and fits(u)), None)
            return {
                "status": "mismatch",
                "assumed_unit": default_unit,
                "observed_median": _num(median),
                "expected_median_range": [low, high],
                "suspected_unit": suspected,
            }

        def clinical_threshold_analysis(
            column, series, cutoff=None, direction=None, unit=None
        ):
            """Count how many rows fall on each side of a REAL medical threshold.

            A clinical cutoff comes from a guideline body that studied outcomes --
            triglycerides at 150 mg/dL, HbA1c at 6.5% -- and it stays put no matter
            whose data you load. The dataset's own median does not qualify: load a
            healthier sample, and it moves, which is exactly what a diagnostic
            threshold must not do. So if no cutoff is supplied and the column isn't in
            CLINICAL_THRESHOLDS, this block runs nothing and says so, rather than
            quietly substituting the median (which is what the engine used to do while
            labeling the output "clinical").

            A threshold from the table is applied only once its unit checks out; see
            check_units. A caller-supplied cutoff is applied as given -- you brought
            the number, so you own the units, and the output says so.
            """
            if cutoff is not None:
                cutoff = float(cutoff)
                return count_against_cutoff(
                    column,
                    series,
                    cutoff=cutoff,
                    direction=direction or "at_or_above",
                    source="supplied by the caller",
                    meaning=None,
                    unit_check={
                        "status": "not_checked",
                        "why": (
                            "The cutoff came from the caller, so the engine has no "
                            "reference unit to check the column against. Make sure the "
                            f"cutoff {cutoff} is in the same units as '{column}'."
                        ),
                    },
                )

            reference = CLINICAL_THRESHOLDS.get(column.strip().lower())
            if reference is None:
                return {
                    "status": "not_run",
                    "reason": (
                        f"No published threshold on file for '{column}', and none was "
                        "supplied."
                    ),
                    "how_to_run": (
                        "Pass clinical_cutoff=<value> (and cutoff_direction="
                        "'at_or_above' or 'below') from the relevant guideline."
                    ),
                    "note": (
                        "The dataset_median_split block below is a description of this "
                        "sample, not a substitute for a clinical threshold."
                    ),
                }

            unit_check = check_units(series, reference, unit)

            # Refuse rather than guess. Every branch below has a threshold available
            # and declines to apply it, because applying a cutoff in the wrong unit
            # produces a confident, precise, completely wrong prevalence.
            if unit_check["status"] == "unknown_unit":
                return {
                    "status": "not_run",
                    "reason": (
                        f"Unit '{unit_check['declared_unit']}' isn't one this engine "
                        f"has a {column} threshold for."
                    ),
                    "known_units": unit_check["known_units"],
                    "unit_check": unit_check,
                }

            if unit_check["status"] == "mismatch":
                suspected = unit_check["suspected_unit"]
                low, high = unit_check["expected_median_range"]
                reason = (
                    f"This column's median is {unit_check['observed_median']}, outside "
                    f"the {low}-{high} range expected for "
                    f"{unit_check['assumed_unit']}, so the published cutoff was not "
                    "applied."
                )
                if suspected:
                    reason += f" The values look like {suspected}."
                return {
                    "status": "not_run",
                    "reason": reason,
                    "how_to_run": (
                        f"Pass units='{suspected}' to use that unit's cutoff."
                        if suspected
                        else "Check the column's units, or pass an explicit "
                        "clinical_cutoff in whatever units it is recorded in."
                    ),
                    "why_this_matters": (
                        "A cutoff in the wrong unit doesn't error -- it silently "
                        "flags everyone or no one, and the result looks like a real "
                        "prevalence."
                    ),
                    "unit_check": unit_check,
                }

            applied_unit = unit_check["unit"]
            return count_against_cutoff(
                column,
                series,
                cutoff=reference["units"][applied_unit]["cutoff"],
                direction=direction or reference["direction"],
                source=reference["source"],
                meaning=reference["means"],
                unit=applied_unit,
                unit_check=unit_check,
            )

        def count_against_cutoff(
            column,
            series,
            cutoff,
            direction,
            source,
            meaning,
            unit=None,
            unit_check=None,
        ):
            """Tally a column either side of a cutoff that has already been vetted."""
            at_or_above = int((series >= cutoff).sum())
            below = int((series < cutoff).sum())
            total = int(series.count())
            flagged = at_or_above if direction == "at_or_above" else below

            result: dict[str, Any] = {
                "status": "ran",
                "layer": DESCRIPTIVE,
                "column": column,
                "n": total,
                "cutoff": _num(cutoff),
                "unit": unit,
                "direction": direction,
                "cutoff_source": source,
                "at_or_above": at_or_above,
                "below": below,
                "flagged": flagged,
                "proportion_flagged": _num(flagged / total) if total else None,
                "caveat": (
                    "A share of this sample, not a prevalence estimate for the "
                    "population: NHANES rows carry survey weights that this count "
                    "ignores. A single measurement on a single day also isn't a "
                    "diagnosis -- guidelines generally require repeat testing and "
                    "clinical context."
                ),
            }
            if meaning:
                result["threshold_means"] = meaning
            if unit_check is not None:
                result["unit_check"] = unit_check
            return result

        def dataset_median_split(column, series):
            """Split the column at its own median and count each half.

            Honest framing: this is a description of who is in this dataset. The
            median moves with the sample, roughly half the rows land on each side by
            construction, and "above the median" carries no medical meaning. It is
            useful for showing the shape of a distribution, and it is what the
            median-split chi-square and Cochran-Armitage tests dichotomize on.
            """
            median = float(series.median())
            total = int(series.count())
            at_or_above = int((series >= median).sum())
            return {
                "layer": DESCRIPTIVE,
                "column": column,
                "n": total,
                "median": _num(median),
                "at_or_above": at_or_above,
                "below": int((series < median).sum()),
                "proportion_at_or_above": _num(at_or_above / total) if total else None,
                "note": (
                    "The median is a property of this sample, not a clinical "
                    "threshold. Roughly half of any dataset sits above its own median "
                    "by definition, and a different sample moves the line."
                ),
            }

        def descriptive_ratios():
            """Derived ratios, reported when the dataset carries both ingredients.

            The triglyceride-to-HDL ratio is watched as a cardiometabolic marker, but
            it has no single agreed cutoff -- proposed values differ by guideline, by
            assay units (the ratio is not unit-free: mg/dL and mmol/L give different
            numbers), and by population. So this reports the ratio's central tendency
            and stops there; no threshold, no risk classification.
            """
            # Match column names case-insensitively -- files spell it "HDL", "hdl", ...
            by_lowercase_name = {c.lower(): c for c in self.df.columns}
            triglyceride_name = next(
                (n for n in ("triglycerides", "trig") if n in by_lowercase_name), None
            )
            hdl_name = next(
                (n for n in ("hdl", "hdlcholesterol") if n in by_lowercase_name), None
            )
            if triglyceride_name is None or hdl_name is None:
                return {}

            triglycerides = _coerce_numeric(
                self.df[by_lowercase_name[triglyceride_name]]
            )
            hdl = _coerce_numeric(self.df[by_lowercase_name[hdl_name]])
            # An HDL of 0 would divide to infinity; throw those rows out.
            ratio = (triglycerides / hdl).replace([np.inf, -np.inf], np.nan).dropna()
            if ratio.empty:
                return {}

            return {
                "trig_hdl_ratio": {
                    "layer": DESCRIPTIVE,
                    "mean": _num(ratio.mean()),
                    # The ratio is right-skewed, so the median describes a typical
                    # person better than the mean does.
                    "median": _num(ratio.median()),
                    "n": int(ratio.count()),
                    "note": (
                        "Descriptive only. This ratio has no single agreed clinical "
                        "cutoff and its value depends on the measurement units used."
                    ),
                }
            }

        def trend_in_proportions(column, group_column):
            """Cochran-Armitage trend test.

            advanced_analysis's trend block asks whether the AVERAGE climbs across
            the groups. This asks whether the PERCENTAGE above the median climbs --
            the same question about a yes/no outcome instead of a number.

            Cochran-Armitage is designed for outcomes that are genuinely binary
            (survived / didn't). Here the "yes/no" is manufactured by cutting a
            continuous column at its median, which costs power and makes the split
            line sample-dependent. When the outcome really is a number, the advanced
            tier's trend test is the stronger one.

            Running several of these raises the multiple-comparison problem; the
            correction for it lives in analysis_utilities(), because it depends on
            how many tests you ran overall and not on this column.
            """
            return {"cochran_armitage": cochran_armitage(column, group_column)}

        def cochran_armitage(column, group_column):
            """Does the share of "high" values rise steadily across ordered groups?

            Group them in order, label each row high/low by the median, then compare
            each group's actual number of highs to the number you'd expect if the
            groups were all identical. Weight those gaps by the group's position and
            add them up: a big total means the highs pile up at one end.
            """
            try:
                data = _value_and_group(self.df, column, group_column)
                groups = _sorted_groups(data, group_column)
                if len(data) < 3 or len(groups) < 2:
                    return {"error": "Need >= 2 ordered groups."}

                is_high = (data[column] > data[column].median()).astype(int)
                # Position of each group: 0, 1, 2, ...
                score = pd.Series(range(len(groups)), index=groups, dtype=float)
                # Rows per group, and "high" rows per group.
                group_size = data.groupby(group_column).size().reindex(groups).fillna(0)
                group_highs = (
                    is_high.groupby(data[group_column]).sum().reindex(groups).fillna(0)
                )

                total_rows = int(group_size.sum())
                overall_high_rate = int(group_highs.sum()) / total_rows

                # Expected highs if the rate were the same everywhere, versus actual.
                expected_highs = group_size * overall_high_rate
                trend_statistic = float((score * (group_highs - expected_highs)).sum())

                # How much that statistic would wobble by chance alone.
                spread_of_scores = float(
                    (group_size * score**2).sum()
                    - (group_size * score).sum() ** 2 / total_rows
                )
                variance = (
                    overall_high_rate * (1 - overall_high_rate) * spread_of_scores
                )
                if variance <= 0:
                    # Every row high, every row low, or only one group has data --
                    # there is no trend to measure.
                    return {"error": "Zero variance for trend."}

                # Standardize into a z-score, then read off the two-tailed p-value.
                z = trend_statistic / variance**0.5
                p_value = float(2 * sp.norm.sf(abs(z)))
                result: dict[str, Any] = {
                    "layer": INFERENTIAL,
                    "group_order": [str(g) for g in groups],
                    "z": _num(z),
                    "split_at": _num(float(data[column].median())),
                    "method": "median split (continuous values dichotomized)",
                    "information_loss": (
                        "The values were reduced to high/low at this dataset's median "
                        "before testing, so how far above or below each row sat is "
                        "gone, and the split line moves with the sample. Use "
                        "advanced_analysis()'s trend block, which keeps the values "
                        "intact, unless the outcome is genuinely yes/no."
                    ),
                    "assumes": (
                        "The groups above are genuinely ordered and evenly spaced."
                    ),
                }
                result.update(_significance_report(p_value))
                return result
            except Exception as exc:
                return {"error": f"Trend test failed: {exc}"}

        others = _other_numeric_columns(self.df, column)
        result: dict[str, Any] = {"column": column}

        if len(others) >= 2:
            result["multicollinearity"] = multicollinearity(others)
            result["diagnostics"] = regression_diagnostics(column, others)

        # Two separate blocks on purpose. One is a medical threshold; the other is
        # an arbitrary split of this dataset. Merging them under the word
        # "clinical" -- which is what this engine used to do -- dressed up the
        # sample median as medicine.
        result["clinical_threshold"] = clinical_threshold_analysis(
            column, series, clinical_cutoff, cutoff_direction, units
        )
        result["dataset_median_split"] = dataset_median_split(column, series)
        result["ratios"] = descriptive_ratios()

        if group_column is not None:
            result["trend_tests"] = trend_in_proportions(column, group_column)
        return result

    # ==================================================================
    # CATEGORICAL -- for label columns (sex, region, brand) rather than
    # numbers. You can't take the mean of "male", so these get counts.
    # ==================================================================

    def categorical_analysis(self, column):
        """Counts and proportions for a label column, cross-tabulated against the
        next label column if the dataset has one.

        Nested below:

            category_counts    how many rows per category, and what share
            contingency_table  cross-tabulate two labels and test them
        """

        import scipy.stats as sp

        def category_counts(column):
            """How many rows in each category, and what share of the total."""
            values = self.df[column].dropna().astype(str)
            counts = values.value_counts()
            total = int(counts.sum())

            if total == 0:
                return {"column": column, "n": 0, "unique": 0, "counts": {}}

            return {
                "layer": DESCRIPTIVE,
                "column": column,
                "n": total,
                "unique": int(counts.size),  # how many distinct categories
                "counts": {name: int(count) for name, count in counts.items()},
                "proportions": {
                    name: _num(count / total) for name, count in counts.items()
                },
            }

        def contingency_table(column1, column2):
            """Cross-tabulate two label columns and test them for independence.

            The table counts every combination (how many rows are male AND smokers?).
            Chi-square then asks whether the two labels are related, or whether the
            counts are just what you'd expect if they had nothing to do with each
            other.
            """
            data = self.df[[column1, column2]].dropna().astype(str)
            table = pd.crosstab(data[column1], data[column2])

            # Read counts off the raw numpy array. Going through table.loc[r, c]
            # returns a broadly-typed scalar the type checker won't let us pass to
            # int(); the array cell is a plain integer.
            counts = np.asarray(table)
            row_labels = [str(r) for r in table.index]
            col_labels = [str(c) for c in table.columns]

            result: dict[str, Any] = {
                "layer": DESCRIPTIVE,
                "columns": [column1, column2],
                "table": {
                    row: {col: int(counts[i, j]) for j, col in enumerate(col_labels)}
                    for i, row in enumerate(row_labels)
                },
            }

            # Both labels have to actually vary for the test to mean anything.
            if table.shape[0] >= 2 and table.shape[1] >= 2:
                chi2, p_value, degrees_of_freedom, expected = sp.chi2_contingency(table)
                chi_square: dict[str, Any] = {
                    "layer": INFERENTIAL,
                    "statistic": _num(chi2),
                    "df": int(degrees_of_freedom),
                    "not_causal": NOT_CAUSAL,
                }
                # The chi-square approximation gets unreliable when the expected count
                # in a cell is tiny; 5 is the usual warning line.
                smallest_expected = float(np.asarray(expected).min())
                if smallest_expected < 5:
                    chi_square["assumption_warning"] = (
                        f"The smallest expected cell count is "
                        f"{_num(smallest_expected)}, below the usual minimum of 5, so "
                        "this p-value is approximate. Fisher's exact test is the safer "
                        "choice on a sparse table."
                    )
                chi_square.update(
                    _significance_report(p_value, _cramers_v(chi2, table))
                )
                result["chi_square"] = chi_square
            return result

        result: dict[str, Any] = {"summary": category_counts(column)}

        numeric = set(_numeric_column_names(self.df))
        other_labels = [c for c in self.df.columns if c != column and c not in numeric]
        if other_labels:
            result["contingency"] = contingency_table(column, other_labels[0])
        return result

    # ==================================================================
    # FIGURES
    # ==================================================================

    def figure_production(self, output_dir=None):
        """Draw a histogram and a boxplot for every numeric column.

        Each pair is saved twice: PDF (crisp for printing and downloads) and SVG
        (what the website displays). Returns {column: {"pdf": path, "svg": path}}.

        matplotlib is imported here rather than at the top of the file, and forced
        onto the "Agg" backend, which draws straight to a file instead of opening
        a window -- a server has no screen to open one on. Importing it here also
        keeps it off the startup path, so the site boots fast.
        """
        import matplotlib

        matplotlib.use("Agg")
        from pathlib import Path

        import matplotlib.pyplot as plt

        if output_dir is not None:
            out = Path(output_dir)
        else:
            out = Path(__file__).resolve().parent.parent / "Data" / "figures"
        out.mkdir(parents=True, exist_ok=True)

        produced = {}
        for column in _numeric_column_names(self.df):
            series = _numbers(self.df, column)
            if series.empty:
                continue

            # One figure, two side-by-side plots: the histogram shows the shape,
            # the boxplot shows the middle half and the outliers.
            figure, (histogram, boxplot) = plt.subplots(1, 2, figsize=(8, 3))
            histogram.hist(series, bins="auto", edgecolor="white")
            histogram.set_title(f"{column} — distribution")
            boxplot.boxplot(series, orientation="vertical")
            boxplot.set_title(f"{column} — spread")
            boxplot.set_xticks([])
            figure.tight_layout()

            pdf_path = out / f"{column}.pdf"
            svg_path = out / f"{column}.svg"
            figure.savefig(pdf_path)
            figure.savefig(svg_path)
            plt.close(figure)  # free the memory; we're done with this figure

            produced[column] = {"pdf": str(pdf_path), "svg": str(svg_path)}
        return produced

    # ==================================================================
    # UTILITIES -- the odds and ends that belong to no single tier.
    # ==================================================================

    def analysis_utilities(self, p_values=None, correction="bonferroni"):
        """The leftovers: things the tiers need to be usable, but that aren't a
        tier themselves.

            column_inventory   which columns each tier can actually handle
            correct_p_values   raise the bar when many tests were run

        The inventory is what the command line and the website use to decide what
        to offer: run the number tiers on the numeric columns, the categorical
        tier on the rest. It reports a property of the FILE, not of any column.

        The multiple-comparison correction is here rather than inside a tier
        because it corrects across the tests you chose to run -- a fact about your
        whole session, not about one column. No tier can see that, and a tier that
        silently corrected its own p-values would be answering a question you
        didn't ask.

            analyzer.analysis_utilities()["columns"]["numeric"]
            analyzer.analysis_utilities(p_values=[0.01, 0.04, 0.2])
        """

        def column_inventory():
            """Which columns are numbers, and which are labels."""
            numeric = _numeric_column_names(self.df)
            labels = [c for c in self.df.columns if c not in set(numeric)]
            return {
                "layer": DESCRIPTIVE,
                "n_rows": int(len(self.df)),
                "numeric": numeric,
                "categorical": labels,
                "rule": (
                    f"A column counts as numeric when at least "
                    f"{int(NUMERIC_THRESHOLD * 100)}% of its cells parse as numbers."
                ),
            }

        def correct_p_values(p_values, method):
            """Run 20 tests at p < 0.05 and, even with nothing going on, roughly one
            will look "significant" by luck. This raises the bar to compensate for
            how many tests were run.

            The correction only knows about the p-values you hand it. Every test you
            ran and didn't pass in still happened -- including the ones this engine
            runs across a whole file when you analyze every column -- so the honest
            denominator is how many comparisons you actually looked at, not how many
            you chose to report. Bonferroni is the strict option (it controls the
            chance of ANY false positive, at the cost of missing real effects);
            method="fdr_bh" controls the false discovery RATE instead and is the
            usual choice when screening many variables.
            """
            from statsmodels.stats.multitest import multipletests

            rejected, corrected, _, _ = multipletests(p_values, method=method)
            return {
                "layer": INFERENTIAL,
                "method": method,
                "n_tests": len(p_values),
                "corrected_p_values": [_num(p, 4) for p in corrected],
                "still_significant": [bool(r) for r in rejected],
                "note": (
                    "Corrects only for the p-values supplied here. Tests you ran and "
                    "left out still inflate the real false-positive rate."
                ),
            }

        result: dict[str, Any] = {"columns": column_inventory()}
        if p_values:
            result["multiple_comparisons"] = correct_p_values(p_values, correction)
        return result


# ====================================================================
# PART TWO -- THE COHORT
# ====================================================================
#
# Turn the raw NHANES merge into the study's analytic cohort.
#
# WHAT THIS IS FOR
#     Data/nhanes_analytic.csv is the full 2017-2018 merge: 9,254 participants of
#     every age by 412 raw-coded columns. The study this project exists to run is
#     much narrower than that -- U.S. adolescents aged 12-17, a dozen named
#     variables, viral hepatitis excluded -- and every analysis downstream assumes
#     that narrowing has already happened.
#
#     This module is that narrowing, written down once. It reads the raw merge,
#     applies the inclusion and exclusion rules, decodes NHANES' numeric answer
#     codes into real quantities, renames the variables to something a human can
#     read, derives the handful of constructed measures the analysis needs, and
#     writes Data/nhanes_adolescent.csv -- roughly 700 rows and 100 KB, which is
#     small enough to commit and to load in a few milliseconds on a cold start.
#
#     That split is deliberate and it is what makes the deploy work. The raw merge
#     is 17 MB and lives in Git LFS; the *derived* cohort is an ordinary tracked
#     file. Production reads the derived file and never touches the raw one, so a
#     Render dyno that never fetched an LFS object still boots correctly. Rebuild
#     the cohort on a machine that has the raw file:
#
#         python Backend/engine.py build-cohort          # rebuild, print attrition
#         python Backend/engine.py build-cohort --check  # rebuild in memory, diff
#                                            # vs the committed file, change nothing
#
#     --check is what CI runs: it fails if the committed CSV no longer matches
#     what this code produces, so the data and the code that derives it cannot
#     drift apart silently.
#
#     TWO artifacts come out of that command, not one: the cohort CSV and
#     Data/cohort_attrition.json. The log is committed for exactly the same
#     reason the cohort is -- producing it is the only thing in the study that
#     needs the raw merge, and doing it at request time cost 109 MB of peak RSS
#     on a 512 MB instance to recompute five rows that had not changed since the
#     last deploy. See cohort_attrition() and raw_merge_available().
#
# EVERY DECISION THAT SHRINKS THE SAMPLE IS RECORDED
#     build_cohort() returns the cohort *and* an attrition log -- one row per
#     filter, naming the rule and how many participants it removed. Nothing here
#     drops a participant without that showing up in the log, which is what makes
#     the final n auditable rather than asserted. The log ships to the API as
#     /api/study/cohort, so the number on the website traces back to a named rule.
#
#     NOTHING IS EVER IMPUTED. A participant missing a variable the analysis needs
#     is dropped from analyses that need it, exactly as engine.py does everywhere
#     else. See ANALYSIS_CORE below for what "needs it" means, and note that screen
#     time is deliberately NOT in that set.
#
# THREE PLACES THIS DEPARTS FROM THE WRITTEN PROTOCOL
#     Each is a case where the protocol names a variable that does not mean what
#     the name suggests, or does not exist at the stated sample size. They are
#     corrections, not preferences, and each is spelled out at its definition:
#
#       1. Hepatitis B. The protocol excludes on "Hepatitis B Surface Antigen
#          (HEPB_S_J)". HEPB_S_J is the surface *antibody* file -- a marker of
#          VACCINATION, positive in 179 of these adolescents. Excluding on it
#          would have thrown out the vaccinated. The surface *antigen* (the actual
#          infection marker) is LBDHBG, in HEPBD_J. See VIRAL_EXCLUSIONS.
#       2. Triglycerides. The protocol names TRIGLY_J (LBXTR), which is drawn only
#          from the fasting subsample and exists for 341 of these adolescents --
#          it cannot support the stated n. LBXSTR, the same analyte on the MEC
#          biochemistry panel, exists for 749. See TRIGLYCERIDE_SOURCE.
#       3. Screen time. Present as specified, but missing for 113 adolescents who
#          otherwise qualify, so requiring it would cost 16% of the sample. It is
#          a variable with its own reduced n rather than an entry criterion.
#
#     The resulting cohort is n = 699. The protocol says 695. The four-participant
#     gap is not explained by any rule stated in the protocol -- pregnancy status,
#     recall reliability, a positive dietary weight and a positive ALT are all
#     already true of every one of the 699 -- so this code reports what the stated
#     rules actually produce rather than reverse-engineering a filter to land on
#     695. See COHORT_N_NOTE.
# ====================================================================


ROOT = Path(__file__).resolve().parent.parent
RAW_CSV = ROOT / "Data" / "nhanes_analytic.csv"
COHORT_CSV = ROOT / "Data" / "nhanes_adolescent.csv"
# The attrition log, derived beside the cohort and committed with it, for the
# same reason the cohort itself is: producing it is the only thing in the study
# that needs the 17 MB raw merge, and production must never read that. See
# cohort_attrition().
ATTRITION_JSON = ROOT / "Data" / "cohort_attrition.json"

# The first line of a Git LFS pointer file -- what a checkout that never fetched
# the object leaves behind at RAW_CSV's path. See raw_merge_available().
LFS_POINTER_HEAD = b"version https://git-lfs.github.com/spec/v1"


def raw_merge_available(path: Path | None = None) -> bool:
    """True when the raw NHANES merge is really there -- not a Git LFS stub.

    `path.is_file()` is NOT this question, and mistaking one for the other is a
    production outage rather than a nicety. Data/nhanes_analytic.csv is tracked
    in Git LFS and render.yaml deliberately never fetches it, so what sits at
    that path on the deploy is a 133-BYTE POINTER FILE: a real file, with a real
    size, that is_file() reports as present. Hand it to read_csv and the pointer
    metadata is parsed as a header, after which the first NHANES column looked
    up raises KeyError -- 500s on /api/study, from a guard that thought it was
    checking for the file's absence.

    Reads the first 41 bytes. A pointer is ~133 bytes and the real merge is
    17 MB, so this never touches more than one disk block either way.
    """
    path = RAW_CSV if path is None else path
    try:
        with path.open("rb") as handle:
            head = handle.read(len(LFS_POINTER_HEAD))
    except OSError:  # missing, a directory, unreadable
        return False
    return head != LFS_POINTER_HEAD


# Age band. The protocol's target population, and the age range PAQY_J (the
# youth activity questionnaire that carries screen time) is administered over.
AGE_MIN, AGE_MAX = 12, 17

COHORT_N_NOTE = (
    "The protocol states n = 695; applying the rules it states yields n = 699. "
    "Every additional exclusion the protocol mentions -- pregnancy, an "
    "unreliable dietary recall, a non-positive survey weight, a non-positive "
    "ALT -- is already true of all 699, so none of them closes the gap. The "
    "difference is reported rather than engineered away."
)

# ----------------------------------------------------------------------
# VARIABLE MAP -- NHANES code -> the name this project uses.
#
# Names deliberately match the conventions of the curated extract this cohort
# replaces (BMI, Triglycerides, HDLCholesterol, HbA1c, IncomeRatio), so the
# Studio, the figures and the clinical-threshold table in engine.py keep working
# against the same identifiers.
# ----------------------------------------------------------------------

# The MEC biochemistry-profile triglyceride, NOT the fasting-subsample one the
# protocol names. LBXTR (TRIGLY_J) is measured only on the morning fasting
# subsample and exists for 341 of these adolescents; LBXSTR is the same analyte
# on the standard biochemistry panel, drawn from everyone who gave the MEC blood
# sample, and exists for 749 -- the same 749 who have ALT, because it is the
# same tube.
#
# The two agree closely where both exist. Among the 339 adolescents measured
# both ways, r = 0.997: they rank people near-identically, which is what matters
# for a variable used as a PREDICTOR. What differs is level, not order -- LBXSTR
# averages ~14 mg/dL higher, because it is not fasting and triglycerides rise
# after a meal. So the ratio built from it is sound for regression and for
# ranking, and any ABSOLUTE cutoff applied to it (see the risk score in part three)
# reads slightly high. That trade -- a known, bounded upward bias on levels, in
# exchange for doubling the sample -- is the reason for the substitution, and it
# is why the ratio's cut point is defined as a cohort quantile rather than a
# published clinical line.
TRIGLYCERIDE_SOURCE = "LBXSTR"

VARIABLES = {
    # Identity and survey design
    "SEQN": "SEQN",
    # Dietary day-1 weight. The protocol's chosen weight, and the correct one
    # for any analysis whose exposure comes from the day-1 recall.
    "WTDRD1": "DietWeight",
    "SDMVPSU": "SurveyPSU",
    "SDMVSTRA": "SurveyStratum",
    # Demographics
    "RIDAGEYR": "Age",
    "INDFMPIR": "IncomeRatio",
    # Outcome
    "LBXSATSI": "ALT",
    # Primary exposure
    "DR1TSUGR": "TotalSugars",
    "DR2TSUGR": "TotalSugarsDay2",
    "DR1TKCAL": "Energy",
    # Mediator / confounder
    "BMXBMI": "BMI",
    # Downstream metabolic markers
    TRIGLYCERIDE_SOURCE: "Triglycerides",
    "LBDHDD": "HDLCholesterol",
    "LBXGH": "HbA1c",
}

# Answer codes NHANES uses across questionnaire variables for a non-answer.
# These are real numbers in the file and would sail straight into a mean as
# "77 hours of television" if they were not mapped out first.
REFUSED, DONT_KNOW = 77, 99

# Screen-time components, both from PAQY_J, both asked of 2-17 year olds.
# Banded answers, not raw hours -- see decode_screen_hours for the mapping.
SCREEN_TIME_PARTS = ("PAQ710", "PAQ715")  # TV/videos, computer/games

# Viral hepatitis exclusions: the variable, the codes that mean "infected", and
# why this variable and not the one the protocol names.
#
# LBDHBG is the surface ANTIGEN, from HEPBD_J -- the marker of current hepatitis
# B infection (1 = Positive, 2 = Negative, 3 = Indeterminate). The protocol names
# HEPB_S_J, which is the surface ANTIBODY file (LBXHBS): antibody positivity
# means the immune system has seen the virus or, far more commonly in this age
# group, a vaccine. 179 of these 907 adolescents are anti-HBs positive, and
# excluding them would have removed the vaccinated from a study about sugar.
#
# LBDHCI is the confirmed hepatitis C antibody and LBXHCR the viral RNA. Their
# code 3 ("Negative Screening HCV Antibody") and code 2 are both negative
# results; only 1 (Positive) and, for the antibody, 4 (Positive HCV RNA) mean
# infection.
VIRAL_EXCLUSIONS = {
    "LBDHBG": (1,),  # hepatitis B surface antigen positive
    "LBDHCI": (1, 4),  # hepatitis C antibody confirmed positive / RNA positive
    "LBXHCR": (1,),  # hepatitis C RNA positive
}

# The variables an analysis must have to count a participant at all. Screen time
# is pointedly absent: it is missing for 113 otherwise-eligible adolescents, and
# making it an entry criterion would shrink every analysis in the study -- most
# of which never use it -- by 16% to serve the two that do. Models that use
# screen time therefore run on their own smaller sample and report it.
ANALYSIS_CORE = [
    "ALT",
    "TotalSugars",
    "DietWeight",
    "BMI",
    "HbA1c",
    "Triglycerides",
    "HDLCholesterol",
    "Age",
    "Sex",
]

# Columns that are in the file for bookkeeping, not for analysis. They are real
# numbers, so anything that decides "is this column numeric?" by trying to parse
# it will say yes -- and then happily report that the mean participant ID is
# 98,234 and the mean survey stratum is 152.4. Both are arithmetic performed on
# a label, and neither means anything.
#
# The study needs every one of them (the weight and the design codes are what
# make the estimates population estimates), so they stay in the dataframe. They
# are excluded from the column list the website OFFERS, which is a different
# question: what can a reader usefully ask for the mean of?
NON_ANALYTIC_COLUMNS = frozenset(
    {
        "SEQN",  # participant identifier
        "DietWeight",  # survey weight -- an input to estimates, not one of them
        "SurveyPSU",  # design code
        "SurveyStratum",  # design code
    }
)

# RIDRETH3, the race/ethnicity variable with Asian broken out. Kept as a label
# column so the engine's group-by and categorical tier can use it; not a study
# variable, and not adjusted for in any model.
RACE_LABELS = {
    1: "Mexican American",
    2: "Other Hispanic",
    3: "Non-Hispanic White",
    4: "Non-Hispanic Black",
    6: "Non-Hispanic Asian",
    7: "Other/Multi-Racial",
}

SEX_LABELS = {1: "Male", 2: "Female"}


def decode_screen_hours(series: pd.Series) -> pd.Series:
    """Turn a PAQY_J screen-time band into hours per day.

    PAQ710 and PAQ715 are not hour counts, they are banded choices, and two of
    the bands are not numbers at all:

        0  "Less than 1 hour"          -> 0.5   (band midpoint)
        1-4 "1/2/3/4 hours"            -> as-is
        5  "5 hours or more"           -> 5.0   (censored -- see below)
        8  "does not watch TV / use a computer" -> 0.0
        77 Refused, 99 Don't know      -> missing

    Two of those deserve flagging. Code 8 is a real, informative zero, not a
    missing value -- reading it as 8 hours would invent the heaviest screen users
    in the dataset out of the people who reported none. And code 5 is
    right-censored: "5 hours or more" becomes 5.0, so anyone at 9 hours is
    recorded at 5. That compresses the top of the distribution toward the mean
    and, if anything, biases an association with screen time toward zero. It is
    a limitation of the instrument, not something a decoding choice can fix.
    """
    hours = pd.to_numeric(series, errors="coerce")
    return hours.replace({REFUSED: np.nan, DONT_KNOW: np.nan, 8: 0.0, 0: 0.5})


def build_cohort(raw: pd.DataFrame | None = None, raw_path: Path | None = None):
    """Derive the analytic cohort. Returns (cohort_df, attrition_log).

    attrition_log is a list of {"step", "rule", "n", "removed"} dicts -- one per
    filter, in the order applied -- so the final n can be traced back through
    every decision that produced it.
    """
    if raw is None:
        # RAW_CSV is read HERE and not taken as a default argument. A default is
        # evaluated once, at import, so `raw_path=RAW_CSV` froze the path a test
        # or a profiler had repointed -- it would set engine.RAW_CSV, see the
        # module honor it in every other function, and still read the real
        # 17 MB file here.
        raw = pd.read_csv(RAW_CSV if raw_path is None else raw_path, low_memory=False)

    # The sentinel first, before any comparison or count: left in place it would
    # read as a real (if absurdly small) measurement everywhere below.
    raw = raw.replace(ANALYTIC_MISSING_SENTINEL, np.nan)

    log: list[dict] = []
    n = len(raw)
    log.append(
        {
            "step": "NHANES 2017-2018 merge",
            "rule": "all participants",
            "n": n,
            "removed": 0,
        }
    )

    def record(step: str, rule: str, frame: pd.DataFrame) -> pd.DataFrame:
        nonlocal n
        log.append(
            {"step": step, "rule": rule, "n": len(frame), "removed": n - len(frame)}
        )
        n = len(frame)
        return frame

    # 1. Age band.
    d = record(
        "Adolescents",
        f"RIDAGEYR between {AGE_MIN} and {AGE_MAX}",
        raw[raw["RIDAGEYR"].between(AGE_MIN, AGE_MAX)].copy(),
    )

    # 2. Viral hepatitis. Isolates metabolic liver stress from viral hepatitis,
    #    which raises ALT through an entirely different mechanism. In this age
    #    band it removes nobody -- all three markers are negative for every
    #    adolescent tested -- but the rule is applied and logged rather than
    #    skipped, because "we checked and it was zero" and "we never checked"
    #    are different claims and only one of them is defensible.
    infected = pd.Series(False, index=d.index)
    for code, positive in VIRAL_EXCLUSIONS.items():
        infected |= d[code].isin(positive)
    d = record(
        "No viral hepatitis",
        "HBsAg-, HCV antibody- and HCV RNA-negative (LBDHBG/LBDHCI/LBXHCR)",
        d[~infected],
    )

    # 3. Rename and decode into study variables.
    out = pd.DataFrame(index=d.index)
    for code, name in VARIABLES.items():
        out[name] = pd.to_numeric(d[code], errors="coerce")

    out["Sex"] = d["RIAGENDR"].map(SEX_LABELS)
    out["RaceEthnicity"] = d["RIDRETH3"].map(RACE_LABELS)

    # Screen time: the two bands, decoded and summed. Missing if either part is
    # missing -- a participant who answered about television but not about
    # computers has no total, and calling their TV hours the total would
    # understate them.
    parts = [decode_screen_hours(d[code]) for code in SCREEN_TIME_PARTS]
    out["ScreenTime"] = parts[0] + parts[1]

    # 4. Constructed measures.
    #
    # Trig/HDL: the protocol's mechanistic marker, a clinical proxy for insulin
    # resistance and hepatic steatosis. Guarded against a non-positive HDL --
    # there is none in this cohort, but a divide-by-zero that silently produces
    # inf would poison every downstream mean.
    hdl = out["HDLCholesterol"].where(out["HDLCholesterol"] > 0)
    out["TrigHDLRatio"] = out["Triglycerides"] / hdl

    # The two-day sugar average, for the sensitivity check only. Averaged across
    # whichever days exist so a participant with one recall is not silently
    # promoted to a two-day mean: this is NaN unless BOTH days are present,
    # which is exactly the subsample the sensitivity check is about.
    out["TotalSugars2Day"] = (out["TotalSugars"] + out["TotalSugarsDay2"]) / 2

    # 5. Complete cases on the core analysis set.
    out = record(
        "Complete core variables",
        "ALT, sugar, weight, BMI, HbA1c, triglycerides, HDL, age, sex all present",
        out.dropna(subset=ANALYSIS_CORE),
    )

    # 6. A usable survey weight. A zero or negative dietary weight means the
    #    participant is not part of the day-1 dietary estimation sample, so
    #    weighting them contributes nothing and dividing by them is undefined.
    #    Removes nobody here; logged for the same reason as the hepatitis rule.
    out = record("Positive dietary weight", "WTDRD1 > 0", out[out["DietWeight"] > 0])

    out = out.sort_values("SEQN").reset_index(drop=True)
    out["ALTElevated"] = elevated_alt(out)
    out["RiskScore"] = risk_score(out)["score"]
    return out, log


# ----------------------------------------------------------------------
# DERIVED CLINICAL MEASURES
#
# Both of these are used by part three at analysis time AND written into the
# committed CSV, so the generic engine tiers can explore them. One definition,
# imported by both -- a second copy in the API layer is how the website and the
# paper end up quoting different numbers.
# ----------------------------------------------------------------------

# Sex-specific pediatric ALT screening thresholds, in U/L. These are the
# biopsy-anchored values from the SAFETY study (Schwimmer et al., 2010), adopted
# by NASPGHAN's 2017 pediatric NAFLD guideline as the level above which a child
# warrants evaluation. They are far below the adult reference ceilings a
# hospital lab prints (~40 U/L), which is the entire point: applying an adult
# ceiling to adolescents misses most pediatric liver disease.
#
# This is why the thresholds live here and not in engine.py's CLINICAL_THRESHOLDS
# table. That table deliberately refuses sex-specific cutoffs, because it applies
# to a bare column with no guarantee that sex is even present. Here sex is a
# required variable for every participant, so the cutoff can be applied per
# person, which is the only correct way to apply it.
ALT_ELEVATED = {"Male": 26.0, "Female": 22.0}
ALT_THRESHOLD_SOURCE = (
    "Schwimmer et al. 2010 (SAFETY study); adopted in the NASPGHAN 2017 "
    "pediatric NAFLD screening guideline"
)


def elevated_alt(df: pd.DataFrame) -> pd.Series:
    """Flag ALT above the sex-specific pediatric screening threshold.

    Returns a nullable boolean: a participant with no ALT or no sex has no flag
    rather than a False, because "not elevated" and "not measured" must not
    collapse into the same value in a prevalence count.
    """
    cutoff = df["Sex"].map(ALT_ELEVATED)
    flag = df["ALT"] >= cutoff
    return flag.where(df["ALT"].notna() & cutoff.notna()).astype("boolean")


# The composite risk score's six components. Each contributes exactly one point,
# so the score runs 0-6 as the protocol specifies.
#
# The cut point is the COHORT MEDIAN for every continuous component, which is
# what the revised protocol's Step 9 specifies: "one point for each of the
# following risk factors, using the sample median as the cutoff for the
# continuous variables". Male sex is a category, not a cut point, and is the
# sixth.
#
# Why a median and not a published clinical line: there is no adolescent
# screening threshold this project can honestly cite for most of these. There is
# no published "grams of sugar per day above which a 14-year-old's liver is at
# risk", and BMI in adolescents is scored against CDC growth-chart percentiles
# that are age- and sex-specific to the month -- a table this project does not
# carry. HbA1c does have one (the ADA's 5.7% prediabetes line, kept below as
# HBA1C_PREDIABETES) but almost no adolescent in this cohort crosses it, so
# using it would make that component fire for a handful of people and turn a
# six-point score into an effectively five-point one. The protocol chose a
# median split for all five, and a median split is what the score uses.
#
# That makes the score a RELATIVE instrument: it ranks this cohort against
# itself and cannot be carried to another population unchanged, because the cut
# points would move. It is labeled exploratory in the protocol and it is
# reported that way. Splitting at the cohort's own median is also why the
# Trig/HDL component is unaffected by the non-fasting triglyceride's upward
# level shift (see TRIGLYCERIDE_SOURCE) -- a shift that moves every value moves
# the median with it, and the same people land above it either way.
RISK_MEDIAN_COMPONENTS = (
    "TotalSugars",
    "ScreenTime",
    "TrigHDLRatio",
    "HbA1c",
    "BMI",
)

# The ADA prediabetes line. Not used as a score cut point (see above); kept
# because the profile step reports how many adolescents sit above it.
HBA1C_PREDIABETES = 5.7


def risk_score(df: pd.DataFrame) -> dict:
    """The 0-6 composite risk score, plus the cut points that produced it.

    Returns {"score": Series, "cutpoints": {...}}. The cut points are returned,
    not just applied, because a score whose thresholds are invisible cannot be
    checked -- and these are computed from the cohort, so they are a property of
    this run rather than a constant someone can look up.

    A participant missing any component gets no score (NaN) rather than a
    partial one: a 2 out of 4 measured components is not a 2 out of 6, and
    silently treating it as one would make the incomplete look low-risk.
    """
    cutpoints: dict[str, float] = {}
    points = []

    for column in RISK_MEDIAN_COMPONENTS:
        cut = float(df[column].median())
        cutpoints[column] = cut
        points.append((df[column] > cut).where(df[column].notna()))

    # Male sex, per the protocol's hypothesis that risk is higher in males.
    points.append((df["Sex"] == "Male").where(df["Sex"].notna()))

    score = pd.concat(points, axis=1).sum(axis=1, min_count=len(points))
    return {"score": score, "cutpoints": cutpoints}


# ----------------------------------------------------------------------
# BUILD / CHECK
# ----------------------------------------------------------------------


def _format_attrition(log: list[dict]) -> str:
    width = max(len(row["step"]) for row in log)
    lines = [f"{'step'.ljust(width)}  {'n':>6}  {'removed':>7}"]
    lines += [
        f"{row['step'].ljust(width)}  {row['n']:>6}  {row['removed']:>7}" for row in log
    ]
    return "\n".join(lines)


def build_cohort_cli(argv=None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[1])
    parser.add_argument(
        "--check",
        action="store_true",
        help="rebuild in memory and compare against the committed CSV; write nothing",
    )
    parser.add_argument("--raw", type=Path, default=RAW_CSV)
    parser.add_argument("--out", type=Path, default=COHORT_CSV)
    args = parser.parse_args(argv)

    if not raw_merge_available(args.raw):
        print(f"Raw merge not usable: {args.raw}", file=sys.stderr)
        print(
            "It is stored in Git LFS -- run `git lfs pull` to fetch it. A "
            "checkout that has not fetched it leaves a 133-byte pointer file "
            "at that path, which looks present to is_file() but is not the "
            "data. The committed cohort CSV and attrition log are what "
            "production reads, so this is only needed to REBUILD them.",
            file=sys.stderr,
        )
        return 2

    cohort, log = build_cohort(raw_path=args.raw)
    print(_format_attrition(log))
    print(f"\ncohort: {len(cohort)} rows x {len(cohort.columns)} columns")

    if args.check:
        if not args.out.is_file():
            print(
                f"\nNo committed cohort at {args.out} to check against.",
                file=sys.stderr,
            )
            return 1
        committed = pd.read_csv(args.out)
        rebuilt = pd.read_csv(io_roundtrip(cohort))
        stale = [args.out.name] if not committed.equals(rebuilt) else []

        # The attrition log is checked too, and for a sharper reason than the
        # cohort: production SERVES it from that file and never recomputes it,
        # so a stale one is a wrong number on the website with nothing left in
        # the running system to contradict it.
        if not ATTRITION_JSON.is_file():
            stale.append(f"{ATTRITION_JSON.name} (missing)")
        elif _read_attrition() != log:
            stale.append(ATTRITION_JSON.name)

        if not stale:
            print(
                f"\nOK -- {args.out.name} and {ATTRITION_JSON.name} match "
                "what this code produces."
            )
            return 0
        print(
            f"\nDRIFT -- {', '.join(stale)} does NOT match what this code "
            "produces. Re-run without --check to regenerate.",
            file=sys.stderr,
        )
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    cohort.to_csv(args.out, index=False)
    ATTRITION_JSON.write_text(json.dumps(log, indent=2) + "\n")
    print(f"wrote {args.out}")
    print(f"wrote {ATTRITION_JSON}")
    return 0


def _read_attrition():
    """The committed attrition log, or None if it cannot be read as one."""
    try:
        return json.loads(ATTRITION_JSON.read_text())
    except OSError, ValueError:
        return None


def io_roundtrip(df: pd.DataFrame):
    """Serialize a frame to CSV in memory and hand back a readable buffer.

    --check compares the rebuilt cohort against a file that has been through
    to_csv/read_csv, which is lossy in small ways -- float formatting, and an
    all-integer nullable column coming back as plain int64. Comparing the
    in-memory frame directly would report drift on every run for reasons that
    have nothing to do with the data. Putting both sides through the same round
    trip compares what is actually stored.
    """
    import io

    buffer = io.StringIO()
    df.to_csv(buffer, index=False)
    buffer.seek(0)
    return buffer


# ====================================================================
# PART THREE -- THE STUDY
# ====================================================================
#
# The ten-step analysis the project's research protocol specifies.
#
# WHAT THIS IS, AND HOW IT DIFFERS FROM PART ONE
#     Part one of this file is a general-purpose statistics engine: hand it any
#     spreadsheet and any column and it will describe it. It knows nothing about
#     livers. Its tiers are deliberately question-agnostic, and that is what
#     makes them reusable.
#
#     This part is the opposite. It answers ONE set of pre-specified questions
#     about ONE cohort, in a fixed order, with the roles of every variable decided
#     in advance: ALT is the outcome, dietary sugar is the exposure, BMI is the
#     mediator, sex and age are controls. That is a study protocol, not a feature
#     of a spreadsheet, so it lives in its own module and calls the engine's shared
#     helpers rather than growing a new tier inside DataAnalyzer.
#
#     That boundary still protects the honest part of the engine's design. Because
#     the roles here are fixed and declared up front, this part may legitimately
#     do things engine.py refuses to do on an arbitrary column -- apply a
#     sex-specific clinical threshold, decompose an association into direct and
#     mediated parts -- precisely because the protocol committed to them before
#     seeing the results.
#
# THE ANALYTICAL HIERARCHY IS PRE-SPECIFIED
#     The protocol distinguishes three grades of claim, and every step below is
#     tagged with which one it is:
#
#         primary     the hypothesis the study was designed to test. One model --
#                     Model B, the protocol's full specification -- fitted twice:
#                     without body mass (step 4, sugar's total association) and
#                     with it (step 5, sugar's direct association). The sugar
#                     coefficient in the SECOND of those is the single
#                     pre-specified test, declared before the data were seen.
#         supporting  pre-registered analyses that give the primary result context.
#         exploratory generated hypotheses, not tests of them. The risk score and
#                     the subgroup work are here. Uncorrected, and read as
#                     suggestions for the next study rather than findings of this
#                     one.
#
#     That ordering exists to stop a null primary result from being quietly
#     replaced by whichever subgroup happened to clear p < 0.05. It is declared in
#     the protocol, and STEPS below is written in that order.
#
# HOW THE SURVEY DESIGN IS HANDLED
#     NHANES is not a simple random sample. It oversamples some groups and
#     under-samples others, and it does so in clusters. Getting this wrong in
#     either of two ways produces confident nonsense:
#
#       * Ignoring the WEIGHTS (WTDRD1) makes the sample describe the people NHANES
#         happened to recruit rather than U.S. adolescents. Every estimate here is
#         weighted, so the coefficients generalize.
#       * Ignoring the CLUSTERING makes the standard errors too small, because two
#         adolescents from the same sampled location are more alike than two
#         strangers, and treating them as independent invents information. Every
#         model here uses cluster-robust standard errors grouped by PSU within
#         stratum.
#
#     The honest caveat: this cohort spans 15 strata x 2 PSUs = 30 clusters. That
#     is enough for cluster-robust inference to be worth doing and few enough that
#     its p-values are approximate -- the asymptotics assume many clusters. It is a
#     real improvement over pretending the design is not there, not a substitute
#     for a full Taylor-series survey package. See SURVEY_DESIGN_CAVEAT.
#
# WHAT THIS MODULE WILL NOT CLAIM
#     Everything here is an association measured in observational, cross-sectional
#     data. Diet, blood and body measurements were taken at essentially one point
#     in time, so nothing here can establish that changing sugar intake would
#     change anyone's ALT -- not even the mediation step, which decomposes an
#     association into two associations and is named accordingly. The step that
#     comes closest to a causal shape is the one flagged hardest; see
#     MEDIATION_CAVEAT.
# ====================================================================


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
    Git LFS and is absent in production by design (see part two). If the
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
    """The attrition log -- every rule that decided who is in the study.

    Read from Data/cohort_attrition.json, the artifact `build-cohort` writes
    beside the cohort CSV. Same bargain as the cohort itself: deriving it needs
    the 17 MB raw merge, so it is derived once on a machine that has the merge
    and committed as a small file that production can just read.

    That is not a micro-optimization. Recomputing it live parsed 17 MB and 412
    columns to arrive at a fixed list of five rows, and cost 109 MB of peak RSS
    and 137 ms -- on a Render free instance with 512 MB and a tenth of a vCPU,
    the largest single memory event in the whole application, larger than pandas
    and scipy put together.

    Two fallbacks, in order. Rebuild from the raw merge if it is genuinely
    present, which is the developer who has just changed the derivation and not
    yet regenerated the artifact. Otherwise report what the committed cohort can
    attest to on its own -- honest about being a reconstruction rather than
    hard-coding counts that would go stale the moment a rule changed.
    """
    committed = _read_attrition()
    if committed is not None:
        return committed
    if raw_merge_available():
        _, log = build_cohort()
        return log
    return [
        {
            "step": "Analytic cohort",
            "rule": "derived by build_cohort() from the NHANES 2017-2018 merge",
            "n": len(load_cohort()),
            "removed": None,
            "note": "Per-step counts require Data/nhanes_analytic.csv (Git LFS).",
        }
    ]


def analysis_frame(columns, *, cohort=None) -> pd.DataFrame:
    """Complete cases on exactly the columns an analysis touches, plus design.

    Every model in the study starts here, and it takes the column list rather
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
        "protocol_step": 1,
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
# coefficients and R-squareds are comparable to each other.
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
                # The error bar on the protocol's primary figure. SD / sqrt(n)
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
                "Unweighted and design-naive; the weighted, cluster-robust "
                "trend test below is the design-aware counterpart."
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
    frame = analysis_frame(MODEL_B_COLUMNS)

    lifestyle = fit_model(frame, "LogALT", MODEL_A, label=MODEL_LABELS["A"])
    combined = fit_model(frame, "LogALT", MODEL_B, label=MODEL_LABELS["B"])

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
            f"Both models are fitted on the same {len(frame)} adolescents -- those "
            "with screen time recorded -- so the change in R-squared reflects the "
            "added predictors and not a change of sample. Model A needs nothing "
            "Model B does not, and screen time is the binding constraint for both, "
            "so this shared sample is also Model A's own largest sample: no "
            "adolescent is dropped to make the comparison possible."
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
        frame, "LogALT", ["RiskScore", "Age"], label="log(ALT) across risk score"
    )
    slope = trend["coefficients"]["RiskScore"]

    # The protocol's Step 9 asks for an ordinary least-squares slope on MEAN ALT
    # -- "U/L per point" -- which is the number a reader can put next to the bar
    # chart. The log model above is the one that respects ALT's skew, so both
    # are reported: the raw slope for interpretation, the log slope for the test.
    raw_trend = fit_model(
        frame, "ALT", ["RiskScore"], label="mean ALT across risk score"
    )
    raw_slope = raw_trend["coefficients"]["RiskScore"]

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
            "raw_scale_model": _public(raw_trend),
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
    JSON punctuation. Nothing here is sampled -- the analytic samples are 586
    and 699 rows, which is a payload of a few tens of kilobytes and the whole
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


# ====================================================================
# PART FOUR -- THE PREDICTOR
# ====================================================================
#
# A gradient-boosted tree fitted on the same cohort and the same specification
# as the study's primary model, so a visitor can put in one adolescent's
# numbers and see a predicted ALT with a per-variable breakdown of how it got
# there.
#
# WHY A SECOND MODEL AT ALL, WHEN PART THREE ALREADY HAS ONE
#     Part three answers a hypothesis: does dietary sugar predict ALT once body
#     mass and the metabolic markers are accounted for? That question needs a
#     model whose coefficients are interpretable and whose standard errors
#     respect the survey design, which is why it is weighted least squares and
#     why it will stay that way.
#
#     This part answers a different question -- given these seven numbers, what
#     ALT would we guess, and which of the seven moved the guess? -- and it is
#     the demo the poster stands next to. Gradient boosting is the better tool
#     for that: it finds curvature and interactions the linear model cannot
#     express, and out of fold it does measurably better (see CV_NOTE and the
#     numbers in the committed model card).
#
#     It is also a check on part three rather than a replacement for it. The
#     tree model is free to lean on whatever predicts ALT best, with no
#     specification imposed and no linearity assumed. It leans on BMI and sex,
#     then the metabolic markers, and it puts dietary sugar second from last.
#     That is the study's null result arrived at a second way, by a method with
#     no stake in it -- which is worth more than either result alone.
#
# THE SPECIFICATION IS NOT CHOSEN HERE
#     PREDICTOR_FEATURES is MODEL_B_WITH_BMI, the protocol's primary
#     specification, in the protocol's units. Nothing was added because it
#     helped and nothing was dropped because it did not, so the comparison above
#     is between two estimators of one pre-specified model, not between two
#     different models. A tree given a wider feature set would look better and
#     would answer a question nobody asked.
#
# THE EXPLANATION IS EXACT, AND IT IS NOT AN EXTRA DEPENDENCY
#     Every prediction ships with per-feature SHAP contributions from
#     LightGBM's own `pred_contrib=True`, which runs TreeSHAP inside the
#     booster. These are the same numbers shap.TreeExplainer returns -- it
#     delegates to this implementation for LightGBM models -- so the deployment
#     plan's SHAP explainer is present in full, and the `shap` package is not.
#
#     That matters here more than it usually would. `shap` pulls in
#     scikit-learn, numba, llvmlite, cloudpickle, tqdm and slicer; this service
#     runs on 512 MB of which imported libraries are already ~184 MB, and numba
#     has no wheel for the Python version this project pins. LightGBM alone is
#     a 3.5 MB wheel, adds ~10 MB resident on top of the stack this service
#     already loads, and brings one pure-Python dependency (narwhals). Same
#     numbers, none of the weight. See predict_alt().
#
#     Contributions are additive by construction: base value + the seven
#     contributions = the prediction, exactly, which is what makes the
#     breakdown a decomposition rather than an attribution heuristic.
#     tests/test_predictor.py pins that identity.
#
# THE MODEL IS A COMMITTED ARTIFACT, NEVER TRAINED AT RUNTIME
#     Same bargain as the cohort CSV in part two, for the same reasons. Render's
#     free tier has an ephemeral filesystem, so anything written at runtime is
#     lost on the next restart, and 0.1 vCPU makes even this second of training
#     something no visitor should wait for. So training happens on a developer's
#     machine and its two outputs are committed:
#
#         Backend/model/alt_lgbm.txt    the booster, LightGBM's own text format
#         Backend/model/alt_lgbm.json   the model card -- features, units, the
#                                       cross-validated scores, the input ranges
#                                       the UI offers, and what it may claim
#
#         python Backend/engine.py train-model          # retrain, write both
#         python Backend/engine.py train-model --check  # retrain in memory, diff
#                                             # against the committed pair
#
#     --check is the same drift guard `build-cohort --check` is, and CI runs it
#     for the same reason: a change to the cohort or to the feature list that
#     ships without a retrain leaves the site explaining predictions from a
#     model that no longer matches the data underneath it. Training is
#     deterministic (fixed seed, `deterministic=True`, single-threaded, no
#     bagging), so the check is a byte comparison and not an approximate one.
#
# WHAT A PREDICTION IS ALLOWED TO MEAN
#     Nothing here is a diagnosis and nothing here is causal. The model is
#     fitted on 586 adolescents from one survey cycle; it reports where NHANES
#     adolescents with a given set of numbers tended to sit, and it explains its
#     own arithmetic. Moving a slider changes the model's guess, not anyone's
#     liver. Every response carries PREDICTION_CAVEAT saying so, and the
#     language model that narrates it is handed the same sentence.
# ====================================================================


MODEL_DIR = Path(__file__).resolve().parent / "model"
PREDICTOR_TXT = MODEL_DIR / "alt_lgbm.txt"
PREDICTOR_CARD = MODEL_DIR / "alt_lgbm.json"

# The features, in the order the booster was trained on. This IS
# MODEL_B_WITH_BMI -- written as its own name because the booster's column order
# is part of the committed artifact and must not silently follow a change to the
# protocol list without a retrain. train_predictor() asserts they still match.
PREDICTOR_FEATURES = list(MODEL_B_WITH_BMI)

# Everything a reader needs to type one of these in, and everything the UI needs
# to offer it: what to call it, what it is measured in, and one plain sentence
# saying what it is. The slider bounds are NOT written here -- they are derived
# from the cohort at training time (see _input_spec), because a hand-typed range
# that drifts from the data would let a visitor ask the model about an
# adolescent unlike anyone it ever saw and get an answer with no warning on it.
PREDICTOR_INPUTS = {
    "Sugar10g": {
        "label": "Dietary sugar",
        "unit": "10 g/day",
        "about": (
            "Total sugars from the day-1 24-hour dietary recall. The model "
            "works in tens of grams, because that is the contrast the study "
            "reports; the control shows plain grams."
        ),
        "step": 0.5,
        # The one input whose model scale is not the scale a person thinks in.
        # The feature has to stay per-10 g -- it is what the booster was trained
        # on and what makes the contribution comparable to the study's
        # coefficient -- but "10, in tens of grams" is not a quantity a visitor
        # at a poster can picture, and "100 g/day" is. So the value crossing the
        # wire stays in model units and only its PRESENTATION is scaled.
        "display_factor": 10,
        "display_unit": "g/day",
    },
    "ScreenTime": {
        "label": "Screen time",
        "unit": "hours/day",
        "about": "Self-reported recreational screen time on a typical day.",
        "step": 0.5,
    },
    "Age": {
        "label": "Age",
        "unit": "years",
        "about": "Age at screening. The cohort is adolescents aged 12-17.",
        "step": 1,
    },
    "Male": {
        "label": "Sex",
        "unit": "0 = female, 1 = male",
        "about": (
            "Sex as recorded by NHANES. The strongest single predictor here "
            "after body mass: adolescent boys sit well above girls on ALT."
        ),
        "step": 1,
        "choices": [{"value": 0, "label": "Female"}, {"value": 1, "label": "Male"}],
    },
    "TrigHDLRatio": {
        "label": "Triglyceride / HDL ratio",
        "unit": "ratio",
        "about": (
            "Triglycerides divided by HDL cholesterol, both in mg/dL -- a "
            "standard marker of insulin resistance."
        ),
        "step": 0.1,
    },
    "HbA1c": {
        "label": "HbA1c",
        "unit": "%",
        "about": "Glycated haemoglobin: average blood sugar over ~3 months.",
        "step": 0.1,
    },
    "BMI": {
        "label": "BMI",
        "unit": "kg/m\u00b2",
        "about": (
            "Body mass index. Not age- and sex-standardized here, because the "
            "protocol's models use raw BMI and this model must match them."
        ),
        "step": 0.5,
    },
}

# Fixed and pre-specified, not tuned against the score. Shallow trees
# (num_leaves = 7), a floor of 25 observations per leaf and L2 shrinkage are
# what a 586-row sample can support; a deeper forest memorizes it. Determinism
# is not decoration either -- the committed booster is diffed byte for byte by
# `train-model --check`, so anything that varies run to run (bagging, thread
# scheduling, an unseeded RNG) would make that guard fire at random.
PREDICTOR_PARAMS = {
    "objective": "regression",
    "metric": "l2",
    "num_leaves": 7,
    "min_data_in_leaf": 25,
    "learning_rate": 0.05,
    "feature_fraction": 0.9,
    "lambda_l2": 1.0,
    "bagging_freq": 0,
    "verbosity": -1,
    "seed": 20260830,
    "deterministic": True,
    "force_row_wise": True,
    "num_threads": 1,
}

# The ceiling on boosting rounds the search may pick from. The chosen count
# lands in the forties on this cohort, so 300 is roomy enough not to be a
# binding constraint and small enough that a full nested cross-validation is a
# second of work rather than a minute.
PREDICTOR_MAX_ROUNDS = 300

PREDICTION_CAVEAT = (
    "This is a prediction, not a diagnosis and not a causal statement. The "
    "model reports where NHANES adolescents with these numbers tended to sit, "
    "from one survey cycle and 586 participants. Moving an input changes the "
    "model's guess; it does not tell you what would happen to a real person if "
    "that number changed."
)

CV_NOTE = (
    "Scores are out-of-fold, with the folds split by SAMPLING CLUSTER rather "
    "than by participant: two adolescents from the same sampled location are "
    "more alike than two strangers, so splitting them across the train/test "
    "line would let the model see its own answer and report a score it cannot "
    "reproduce. The number of boosting rounds is chosen INSIDE each training "
    "fold, by a second cross-validation that never touches the held-out "
    "cluster, so the reported score pays for that choice instead of hiding it. "
    "The linear figure beside it is the study's own primary specification "
    "(Model B with BMI) scored on exactly the same folds, which is what makes "
    "the two comparable."
)


# ----------------------------------------------------------------------
# TRAINING -- run from the CLI, never from a request
# ----------------------------------------------------------------------


def _cluster_folds(clusters, k: int, seed: int):
    """Assign whole sampling clusters to k folds.

    Grouped k-fold, hand-rolled, for the same reason the ZIP and PDF writers on
    the frontend are hand-rolled: sklearn's GroupKFold is 120 MB of dependency
    for twelve lines. Clusters are shuffled under a fixed seed and dealt round
    robin, which keeps the folds balanced without needing the group sizes.
    """
    unique = sorted(set(clusters))
    order = np.random.default_rng(seed).permutation(len(unique))
    assignment = {unique[i]: int(position % k) for position, i in enumerate(order)}
    return np.array([assignment[c] for c in clusters])


def _weighted_r2(actual, predicted, weights) -> float:
    """R-squared against a weighted mean, on the log scale the model fits."""
    actual, predicted = np.asarray(actual, float), np.asarray(predicted, float)
    weights = np.asarray(weights, float)
    mean = np.average(actual, weights=weights)
    residual = np.average((actual - predicted) ** 2, weights=weights)
    total = np.average((actual - mean) ** 2, weights=weights)
    return float("nan") if total == 0 else float(1 - residual / total)


def _fit_booster(features, outcome, weights, rounds: int):
    """One booster on one sample. The single place lightgbm.train is called."""
    import lightgbm as lgb

    dataset = lgb.Dataset(
        features,
        label=outcome,
        weight=weights,
        feature_name=list(PREDICTOR_FEATURES),
        params=PREDICTOR_PARAMS,
    )
    return lgb.train(PREDICTOR_PARAMS, dataset, num_boost_round=rounds)


def _choose_rounds(features, outcome, weights, clusters, seed: int) -> int:
    """How many boosting rounds this sample supports, by cross-validation.

    Fits k boosters and reads the whole learning curve out of each one in a
    single pass -- `num_iteration=i+1` predicts with a prefix of the trees, so
    300 candidate round counts cost one fit per fold rather than 300. The round
    count with the best out-of-fold R-squared wins.

    Called on the TRAINING part of an outer fold during scoring, and on the full
    cohort once for the model that actually ships. That is the distinction that
    keeps the published score honest: choosing the round count is part of
    fitting, so it has to happen inside the fold that is being scored.
    """
    fold = _cluster_folds(clusters, 4, seed)
    curve = np.zeros((len(outcome), PREDICTOR_MAX_ROUNDS))
    for held_out in range(4):
        train = fold != held_out
        test = fold == held_out
        booster = _fit_booster(
            features[train], outcome[train], weights[train], PREDICTOR_MAX_ROUNDS
        )
        for i in range(PREDICTOR_MAX_ROUNDS):
            curve[test, i] = booster.predict(features[test], num_iteration=i + 1)
    scores = [
        _weighted_r2(outcome, curve[:, i], weights) for i in range(PREDICTOR_MAX_ROUNDS)
    ]
    return int(np.argmax(scores)) + 1


def _cross_validate(features, outcome, weights, clusters, design) -> dict:
    """Score the tree model and the study's linear model on identical folds.

    Nested: the outer loop holds out clusters and scores, the inner loop (inside
    _choose_rounds) picks the round count using only the outer loop's training
    clusters. The linear comparison is refitted fold by fold too -- scoring a
    model that was fitted on all the data against folds of that same data would
    flatter it for free.
    """
    import statsmodels.api as sm

    outer = _cluster_folds(clusters, 5, 0)
    tree = np.zeros(len(outcome))
    linear = np.zeros(len(outcome))
    rounds_per_fold = []

    for held_out in range(5):
        train = outer != held_out
        test = outer == held_out
        rounds = _choose_rounds(
            features[train],
            outcome[train],
            weights[train],
            clusters[train],
            seed=1 + held_out,
        )
        rounds_per_fold.append(rounds)
        booster = _fit_booster(features[train], outcome[train], weights[train], rounds)
        tree[test] = booster.predict(features[test])
        fit = sm.WLS(outcome[train], design[train], weights=weights[train]).fit()
        linear[test] = fit.predict(design[test])

    def mean_absolute_error(predicted) -> float:
        """Back on the U/L scale, where a reader can judge the size of a miss."""
        return float(
            np.average(np.abs(np.exp(outcome) - np.exp(predicted)), weights=weights)
        )

    return {
        "scheme": "5-fold, grouped by PSU within stratum, rounds chosen in an inner 4-fold",
        "folds": 5,
        "clusters": int(len(set(clusters))),
        "rounds_per_fold": rounds_per_fold,
        "gradient_boosting": {
            "r_squared_log_alt": _num(_weighted_r2(outcome, tree, weights), 4),
            "mean_absolute_error_u_per_l": _num(mean_absolute_error(tree), 2),
        },
        "linear_model_b_with_bmi": {
            "r_squared_log_alt": _num(_weighted_r2(outcome, linear, weights), 4),
            "mean_absolute_error_u_per_l": _num(mean_absolute_error(linear), 2),
        },
        "note": CV_NOTE,
    }


def _input_spec(frame) -> dict:
    """What the UI offers for each input: range, default, and the label copy.

    Bounds are the cohort's own 1st and 99th weighted percentiles, rounded
    outward, and the default is the weighted median. Deriving them rather than
    typing them is what keeps the sliders inside the data: the model has no way
    to signal that a BMI of 60 is outside everything it was fitted on, so the
    control does not offer one. The percentiles are weighted for the same reason
    every other number in this project is -- the sliders should describe U.S.
    adolescents, not this sample.
    """
    weights = frame["DietWeight"]
    spec = {}
    for name in PREDICTOR_FEATURES:
        values = frame[name]
        low = _wquantile(values, weights, 0.01)
        high = _wquantile(values, weights, 0.99)
        median = _wquantile(values, weights, 0.5)
        meta = PREDICTOR_INPUTS[name]
        step = meta["step"]
        spec[name] = {
            "name": name,
            "label": meta["label"],
            "unit": meta["unit"],
            "about": meta["about"],
            "min": _num(math.floor(low / step) * step, 3),
            "max": _num(math.ceil(high / step) * step, 3),
            "step": step,
            "default": _num(round(median / step) * step, 3),
            "cohort_median": _num(median, 3),
        }
        for optional in ("choices", "display_factor", "display_unit"):
            if optional in meta:
                spec[name] = {**spec[name], optional: meta[optional]}
    return spec


def train_predictor() -> tuple[object, dict]:
    """Fit the booster on the whole cohort and build its model card.

    Returns the trained booster and the card as a dict. Writing them is the
    CLI's job, not this function's, so `--check` can retrain in memory and
    compare without touching the repo.
    """
    if PREDICTOR_FEATURES != MODEL_B_WITH_BMI:
        # A guard, not a formality. This model exists to be the protocol's
        # specification fitted a second way; if the protocol gains a covariate
        # and this list does not, the comparison in _cross_validate quietly
        # stops being between two estimators of one model.
        raise ValueError(
            "PREDICTOR_FEATURES has drifted from MODEL_B_WITH_BMI: "
            f"{PREDICTOR_FEATURES} vs {MODEL_B_WITH_BMI}"
        )

    import statsmodels.api as sm

    frame = analysis_frame(MODEL_B_COLUMNS)
    features = frame[PREDICTOR_FEATURES].to_numpy(dtype=float)
    outcome = frame["LogALT"].to_numpy(dtype=float)
    weights = frame["DietWeight"].to_numpy(dtype=float)
    clusters = _clusters(frame).to_numpy()
    design = np.asarray(
        sm.add_constant(frame[MODEL_B_WITH_BMI].astype(float)), dtype=float
    )

    validation = _cross_validate(features, outcome, weights, clusters, design)
    rounds = _choose_rounds(features, outcome, weights, clusters, seed=99)
    booster = _fit_booster(features, outcome, weights, rounds)

    # Gain: the total improvement in squared error every split on a feature
    # bought, as a share of the whole forest's. Reported alongside the mean
    # absolute SHAP contribution because they answer different questions -- gain
    # is how much the model USED a feature while fitting, mean |SHAP| is how far
    # that feature actually moves a prediction. They agree here, which is worth
    # being able to see.
    gain = np.asarray(booster.feature_importance("gain"), dtype=float)
    total_gain = float(gain.sum())
    contributions = np.asarray(booster.predict(features, pred_contrib=True))
    mean_abs = np.average(np.abs(contributions[:, :-1]), axis=0, weights=weights)

    importance = [
        {
            "feature": name,
            "label": PREDICTOR_INPUTS[name]["label"],
            "gain_percent": _num(100 * gain[i] / total_gain, 2) if total_gain else None,
            "mean_abs_shap": _num(float(mean_abs[i]), 5),
        }
        for i, name in enumerate(PREDICTOR_FEATURES)
    ]
    importance.sort(key=lambda row: row["mean_abs_shap"] or 0, reverse=True)

    card = {
        "model": "LightGBM gradient-boosted trees",
        "outcome": "ln(ALT), U/L",
        "outcome_label": "Alanine aminotransferase (ALT)",
        "features": list(PREDICTOR_FEATURES),
        "specification": (
            "Model B with BMI -- the study's pre-specified primary "
            "specification, fitted here by gradient boosting instead of "
            "weighted least squares."
        ),
        "n": int(len(frame)),
        "clusters": int(len(set(clusters))),
        # Phrased as a sentence fragment, not a title, because the UI drops it
        # into running prose. A title-cased string there needs lower-casing to
        # fit, and lower-casing turns WTDRD1 into wtdrd1.
        "weighted": (
            "the day-1 dietary weight (WTDRD1), applied as a per-row training weight"
        ),
        "rounds": int(rounds),
        "params": dict(PREDICTOR_PARAMS),
        "base_value": _num(float(contributions[0, -1]), 5),
        "elevated_alt_thresholds": dict(ALT_ELEVATED),
        "elevated_alt_source": ALT_THRESHOLD_SOURCE,
        "validation": validation,
        "importance": importance,
        "inputs": _input_spec(frame),
        "trained_on": "NHANES 2017-2018, adolescents aged 12-17",
        "caveat": PREDICTION_CAVEAT,
        "not_causal": NOT_CAUSAL,
    }
    return booster, card


def _predictor_drift(fresh_booster, fresh_card: dict) -> list[str]:
    """What differs between a fresh training run and the committed model.

    WHY THIS IS NOT A BYTE COMPARISON
        Training is deterministic -- fixed seed, `deterministic=True`, one
        thread, no bagging -- so on one machine a retrain reproduces the
        committed file exactly, and comparing bytes was the obvious check to
        write. It is the wrong one, because the model is trained on a developer's
        Mac and verified in CI on x86 Linux, and nothing in LightGBM's contract
        promises bit-identical split thresholds across architectures. A guard
        that can fail for a last-digit difference in a threshold is a guard that
        goes red on a repository where nothing is wrong, and a CI check nobody
        trusts is worse than none.

        So this compares the two things a byte comparison was standing in for:

          STRUCTURE, exactly. The feature list, the sample, the cluster count,
          the chosen round count, every hyperparameter, and the input ranges the
          UI offers. Every drift this guard exists to catch -- a changed
          inclusion rule, a covariate added to the protocol, a hyperparameter
          edited and not retrained -- moves at least one of these, and none of
          them is a float that platform noise can nudge.

          BEHAVIOUR, to a tolerance far tighter than any real drift. The two
          boosters must predict the same ALT for all 586 adolescents to within
          1e-6 on the log scale. A model that agrees to six decimals on every
          row of its own training set IS the committed model; a model refitted
          on a cohort that moved does not come close.
    """
    if not PREDICTOR_TXT.is_file() or not PREDICTOR_CARD.is_file():
        return ["Backend/model/ is missing or incomplete -- run train-model"]

    import lightgbm as lgb

    committed_card = json.loads(PREDICTOR_CARD.read_text())
    committed_booster = lgb.Booster(model_str=PREDICTOR_TXT.read_text())
    problems = []

    for field in ("features", "n", "clusters", "rounds", "params", "inputs"):
        if committed_card.get(field) != fresh_card.get(field):
            problems.append(
                f"{field}: committed {committed_card.get(field)!r} != "
                f"fresh {fresh_card.get(field)!r}"
            )

    # The ranking, not the values behind it. Which input matters most is a claim
    # the site and the language model's prompt both make out loud; the fifth
    # decimal of a mean |SHAP| is not.
    def ranking(card: dict) -> list:
        return [row["feature"] for row in card["importance"]]

    if ranking(committed_card) != ranking(fresh_card):
        problems.append(
            f"importance order: committed {ranking(committed_card)} != "
            f"fresh {ranking(fresh_card)}"
        )

    frame = analysis_frame(MODEL_B_COLUMNS)
    features = frame[PREDICTOR_FEATURES].to_numpy(dtype=float)
    gap = float(
        np.max(
            np.abs(
                committed_booster.predict(features) - fresh_booster.predict(features)
            )
        )
    )
    if gap > 1e-6:
        problems.append(
            f"predictions: the committed model and a fresh one differ by up to "
            f"{gap:.3g} in ln(ALT) across the cohort"
        )
    return problems


def train_predictor_cli(argv=None) -> int:
    """`train-model` and `train-model --check`.

    Writes the booster and its card, or -- with --check -- retrains in memory
    and compares against the committed pair without touching them. See
    _predictor_drift() for what "compares" means and why it is not a diff.
    """
    parser = argparse.ArgumentParser(
        prog="engine.py train-model",
        description="Fit the ALT predictor and write Backend/model/.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Retrain in memory and compare with the committed model; write nothing.",
    )
    args = parser.parse_args(list(argv or []))

    booster, card = train_predictor()
    booster_text = booster.model_to_string()
    card_text = json.dumps(card, indent=2, default=str) + "\n"

    if args.check:
        problems = _predictor_drift(booster, card)
        if problems:
            print("Committed model is stale:")
            for problem in problems:
                print(f"  - {problem}")
            print("Fix with: python Backend/engine.py train-model")
            return 1
        print(
            f"Committed model matches its derivation "
            f"(n = {card['n']}, {card['rounds']} rounds)."
        )
        return 0

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    PREDICTOR_TXT.write_text(booster_text)
    PREDICTOR_CARD.write_text(card_text)

    scores = card["validation"]
    print(f"Trained on n = {card['n']} across {card['clusters']} clusters.")
    print(f"  rounds                {card['rounds']}")
    print(
        "  out-of-fold R^2       "
        f"{scores['gradient_boosting']['r_squared_log_alt']} (trees) vs "
        f"{scores['linear_model_b_with_bmi']['r_squared_log_alt']} (Model B linear)"
    )
    print("  drivers, by mean |SHAP|:")
    for row in card["importance"]:
        print(f"    {row['label']:<28} {row['mean_abs_shap']}")
    print(
        f"Wrote {PREDICTOR_TXT.relative_to(ROOT)} and {PREDICTOR_CARD.relative_to(ROOT)}."
    )
    return 0


# ----------------------------------------------------------------------
# SERVING -- what a request actually calls
# ----------------------------------------------------------------------


@lru_cache(maxsize=1)
def load_predictor() -> tuple[object, dict]:
    """The committed booster and its card, read once per process.

    Reads the artifact; never trains. A missing artifact raises rather than
    falling back to training, because the fallback would be a minute of a tenth
    of a vCPU inside somebody's request and would then be thrown away on the
    next restart. predict_api.py turns the error into a clean 503.
    """
    import lightgbm as lgb

    if not PREDICTOR_TXT.is_file() or not PREDICTOR_CARD.is_file():
        raise FileNotFoundError(
            "No trained model in Backend/model/. "
            "Build it with: python Backend/engine.py train-model"
        )
    booster = lgb.Booster(model_str=PREDICTOR_TXT.read_text())
    return booster, json.loads(PREDICTOR_CARD.read_text())


def predictor_card() -> dict:
    """The model card the UI builds its form and its disclosures from."""
    return load_predictor()[1]


def _clamp_inputs(values: dict, card: dict) -> tuple[list[float], list[str]]:
    """Put the seven inputs in the booster's order, inside the cohort's range.

    Out-of-range values are clamped and REPORTED, not rejected. A tree model
    extrapolates by returning the edge leaf, so a BMI of 90 silently produces
    the same answer as the highest BMI in the data -- clamping makes that
    explicit instead of letting the UI present an invented prediction as a real
    one. The returned notes travel all the way to the response and to the
    language model's prompt.
    """
    spec = card["inputs"]
    ordered, notes = [], []
    for name in card["features"]:
        bounds = spec[name]
        given = values.get(name)
        if given is None:
            given = bounds["default"]
            notes.append(f"{bounds['label']} was not given; used the cohort median.")
        number = float(given)
        if not math.isfinite(number):
            raise ValueError(f"{bounds['label']} must be a finite number.")
        low, high = float(bounds["min"]), float(bounds["max"])
        if number < low or number > high:
            notes.append(
                f"{bounds['label']} was {_num(number, 3)}, outside the cohort's "
                f"{low}-{high} {bounds['unit']}; clamped to the edge, where the "
                "model has data."
            )
            number = min(max(number, low), high)
        ordered.append(number)
    return ordered, notes


def _display_value(number: float, spec: dict) -> str:
    """One input's value as a reader would say it aloud.

    Three cases: a choice reads as its own name, a scaled input reads in the
    unit a person thinks in (see Sugar10g's display_factor), and everything else
    reads as itself.
    """
    for choice in spec.get("choices", ()):
        if float(choice["value"]) == number:
            return str(choice["label"])
    factor = float(spec.get("display_factor", 1))
    unit = spec.get("display_unit", spec["unit"])
    return f"{_num(number * factor, 3)} {unit}"


def predict_alt(values: dict) -> dict:
    """One prediction, with its exact SHAP decomposition.

    `pred_contrib=True` runs TreeSHAP in the booster and returns one column per
    feature plus a final base-value column, and those sum to the prediction
    exactly. So the breakdown below is arithmetic on the model's own output --
    "sex added 0.06 to ln(ALT)" is a statement about this forest, checkable by
    addition, not an approximation of one.

    Everything is reported on both scales. The model works in ln(ALT), which is
    where the contributions are additive and comparable; a reader wants U/L,
    which is where they are multiplicative. Giving one without the other invites
    somebody to add up percentages that do not add up.
    """
    booster, card = load_predictor()
    ordered, notes = _clamp_inputs(values, card)

    row = np.asarray([ordered], dtype=float)
    contributions = np.asarray(booster.predict(row, pred_contrib=True))[0]
    base = float(contributions[-1])
    log_prediction = float(base + contributions[:-1].sum())
    prediction = float(np.exp(log_prediction))

    spec = card["inputs"]
    drivers = []
    for i, name in enumerate(card["features"]):
        effect = float(contributions[i])
        drivers.append(
            {
                "feature": name,
                "label": spec[name]["label"],
                "value": _num(ordered[i], 3),
                "unit": spec[name]["unit"],
                # The same value as a person would say it. For a choice input
                # that is the choice's name -- "Male", not "1 0 = female,
                # 1 = male", which is what pasting the raw value next to the
                # unit produces. Built here rather than in the UI because three
                # consumers need it and they must agree: the table, the chart's
                # tooltip, and the text handed to the language model, which
                # would otherwise be asked to narrate a coded number.
                "display": _display_value(ordered[i], spec[name]),
                "cohort_median": spec[name]["cohort_median"],
                # The median in the same units the entered value is shown in,
                # or None for a choice input -- the median of a 0/1 column is a
                # real number and a meaningless one to print next to "Male".
                # Without this the sugar row read "entered 140 g/day (cohort
                # median 9.963)", two scales in one sentence.
                "cohort_median_display": (
                    None
                    if spec[name].get("choices")
                    else _display_value(spec[name]["cohort_median"], spec[name])
                ),
                # The contribution to ln(ALT), which is the additive one...
                "contribution_log": _num(effect, 5),
                # ...and the same thing as a multiplier on ALT, which is what it
                # means in U/L. exp(b) - 1, for the reason _percent_change gives.
                "percent_of_alt": _percent_change(effect),
                "direction": "raises"
                if effect > 0
                else "lowers"
                if effect < 0
                else "neutral",
            }
        )
    drivers.sort(key=lambda d: abs(d["contribution_log"] or 0), reverse=True)

    # The elevated-ALT line is sex-specific (see ALT_ELEVATED), and sex is one
    # of the inputs, so the right threshold is known here. This is a comparison
    # against a published cutoff, not a classification: the model predicts a
    # central value, and half of any real group sits above its own prediction.
    is_male = bool(ordered[card["features"].index("Male")] >= 0.5)
    threshold = ALT_ELEVATED["Male" if is_male else "Female"]

    return {
        "predicted_alt": _num(prediction, 2),
        "predicted_log_alt": _num(log_prediction, 5),
        "base_value_log": _num(base, 5),
        "baseline_alt": _num(float(np.exp(base)), 2),
        "units": "U/L",
        "inputs": {
            name: _num(ordered[i], 3) for i, name in enumerate(card["features"])
        },
        "drivers": drivers,
        "reference": {
            "elevated_threshold": threshold,
            "sex": "male" if is_male else "female",
            "above_threshold": bool(prediction >= threshold),
            "means": (
                f"The predicted value is {'at or above' if prediction >= threshold else 'below'} "
                f"the {threshold} U/L line this project uses for "
                f"{'boys' if is_male else 'girls'}. That line describes a "
                "population, and one prediction sitting near it is not a finding "
                "about a person."
            ),
        },
        "adjustments": notes,
        "layer": PREDICTIVE,
        "caveat": PREDICTION_CAVEAT,
        "not_causal": NOT_CAUSAL,
    }


# ======================================================================
# COMMAND-LINE ENTRY POINT -- for poking at the engine during development.
# ======================================================================

# Which DataAnalyzer method each tier name maps to. app.py has the same routing
# for its JSON API (see run_analysis there); this is the terminal-side twin so a
# dev can exercise the exact same tiers without booting the web server.
_TIERS = {
    "basic": lambda analyzer, column, group: analyzer.basic_analysis(column),
    "medium": lambda analyzer, column, group: analyzer.medium_analysis(column, group),
    "advanced": lambda analyzer, column, group: analyzer.advanced_analysis(
        column, group
    ),
    "expert": lambda analyzer, column, group: analyzer.expert_analysis(column, group),
    "categorical": lambda analyzer, column, group: analyzer.categorical_analysis(
        column
    ),
}


def main(argv=None):
    """Run any analysis tier straight from the terminal and print it as JSON.

    Two other entry points hang off the same command, because the cohort builder
    and the study protocol now live in this file too:

        python Backend/engine.py build-cohort           # rebuild the cohort CSV
        python Backend/engine.py build-cohort --check   # CI's drift check
        python Backend/engine.py study                  # the whole study as JSON
        python Backend/engine.py train-model            # refit the ALT predictor
        python Backend/engine.py train-model --check    # CI's model drift check

    app.py is the real front door, but booting a web server just to see what
    advanced_analysis() returns is slow. This loads a CSV the same way the app
    does (Data/nhanes_analytic.csv by default), runs a tier, and prints the
    result. NHANES columns are coded (RIDAGEYR = age, BMXBMI = BMI):

        python Backend/engine.py --column BMXBMI                    # basic BMI
        python Backend/engine.py --tier medium --column BMXBMI --group RIAGENDR
        python Backend/engine.py --tier advanced --column LBXTC     # total cholesterol
        python Backend/engine.py --csv Data/data.csv --column Age   # the small demo set

    With no --column it runs the tier on every column that fits: the numeric
    columns for the number tiers, the label columns for the categorical tier.
    That split comes from analysis_utilities()'s column inventory, which is the
    same list the website builds its column picker from.

    """
    # Three sub-commands, dispatched before argparse so the tier flags below stay
    # exactly as they were. They are sub-commands rather than separate scripts
    # because the cohort builder, the study protocol and the predictor are parts
    # of this module now, and a part of a module should not need its own file to
    # run.
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "build-cohort":
        return build_cohort_cli(argv[1:])
    if argv and argv[0] == "train-model":
        return train_predictor_cli(argv[1:])
    if argv and argv[0] == "study":
        print(json.dumps(run_study(), indent=2, default=str))
        return 0

    default_csv = (
        Path(__file__).resolve().parent.parent / "Data" / "nhanes_analytic.csv"
    )

    parser = argparse.ArgumentParser(
        description="Run the stats engine on a CSV from the terminal."
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=default_csv,
        help="CSV file to analyze (default: Data/nhanes_analytic.csv).",
    )
    parser.add_argument(
        "--tier",
        default="basic",
        choices=list(_TIERS),
        help="Which analysis tier to run (default: basic).",
    )
    parser.add_argument(
        "--column",
        help="Column to analyze. Omit to run the tier on every applicable column.",
    )
    parser.add_argument(
        "--group",
        help="Optional grouping column for the medium/advanced/expert tiers.",
    )
    args = parser.parse_args(argv)

    df = df_cleanup(pd.read_csv(args.csv))
    analyzer = DataAnalyzer(df)
    run_tier = _TIERS[args.tier]

    # One named column, or every column that fits the tier: numeric columns for
    # the number tiers, the leftover label columns for the categorical tier.
    inventory = analyzer.analysis_utilities()["columns"]
    if args.column:
        columns = [args.column]
    elif args.tier == "categorical":
        columns = inventory["categorical"]
    else:
        columns = inventory["numeric"]

    output = {column: run_tier(analyzer, column, args.group) for column in columns}
    # default=str is a safety net for any stray numpy/pandas scalar; _num() has
    # already turned the statistics themselves into plain floats and Nones.
    print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    raise SystemExit(main() or 0)
