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

from typing import Any, cast

import numpy as np
import pandas as pd
import scipy.stats as sp

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
    """
    numbers = pd.to_numeric(series, errors="coerce")
    return numbers.replace(ANALYTIC_MISSING_SENTINEL, np.nan)


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
            your labelling says which story the difference tells. Get the roles
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
                        "proportion_via_mediator": _num(indirect / crude)
                        if crude
                        else None,
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
            healthier sample and it moves, which is exactly what a diagnostic
            threshold must not do. So if no cutoff is supplied and the column isn't in
            CLINICAL_THRESHOLDS, this block runs nothing and says so, rather than
            quietly substituting the median (which is what the engine used to do while
            labelling the output "clinical").

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

    Kept off the module's import path (argparse/json/pathlib load here, not at the
    top) so importing engine.py stays cheap for Render's cold start.
    """
    import argparse
    import json
    from pathlib import Path

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
    main()
