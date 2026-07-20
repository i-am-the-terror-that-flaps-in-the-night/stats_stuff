"""
engine.py -- the backend stats engine.

Pure data logic, no printing: it cleans up a spreadsheet and computes statistics
on it. app.py imports df_cleanup and DataAnalyzer from here and serves the
results over HTTP; tests/test_engine.py calls them directly.

HOW THIS FILE IS ORGANIZED
    There are five things you can ask DataAnalyzer for, from simplest to hardest:

        basic_analysis()        mean, median, mode, spread
        medium_analysis()       shape of the data, error bars, group comparisons
        advanced_analysis()     correlation, regression, confounding
        expert_analysis()       collinearity, model checks, clinical cutoffs
        categorical_analysis()  counts and cross-tabs for label columns

    Those five are the ones the rest of the app calls. Everything else in the
    class is a helper with a name starting in "_", and each helper does exactly
    one statistical job. Read the five public methods first: each is short and
    reads like a table of contents for the helpers underneath it.

A NOTE ON MISSING VALUES
    Real spreadsheets have blanks and typos. Everywhere we turn a column into
    numbers we use pd.to_numeric(..., errors="coerce"), which turns anything
    unreadable into NaN ("not a number"), and then we .dropna() those rows.
    We never fill a blank in with the mean -- that would fake extra data points
    and make the results look more certain than they are.

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

# A column counts as "numeric" if at least this fraction of its cells parse as
# numbers. Below that, we treat it as a label column (names, categories, etc.).
NUMERIC_THRESHOLD = 0.8

# The usual cutoff for calling a result "statistically significant": a p-value
# under 0.05 means "this pattern would show up by pure chance less than 5% of
# the time".
ALPHA = 0.05

# NHANES-style analytic files (Data/nhanes_analytic.csv) don't leave missing
# cells blank -- they fill them with this one tiny magic number, which is really
# a stand-in for "no value here", not a real measurement of ~0. Left alone it
# would sink every mean, crush every variance, and fake tens of thousands of
# data points -- exactly what the "missing values" note above warns against. So
# we turn it back into a blank (NaN) on the way in. Real datasets like
# Data/data.csv never contain it, so this is a no-op for them.
NHANES_MISSING_FILL = 5.397605346934028e-79


def _coerce_numeric(series):
    """Parse a column as numbers, treating the NHANES fill value as missing.

    Every place in the engine that turns a raw column into numbers goes through
    here, so that fill value can never sneak into a statistic -- the same reason
    _num() is the single exit every result leaves by. On datasets that don't use
    the fill (like Data/data.csv) the .replace() simply finds nothing.
    """
    numbers = pd.to_numeric(series, errors="coerce")
    return numbers.replace(NHANES_MISSING_FILL, np.nan)


def df_cleanup(df):
    """Turn mostly-numeric text columns into real number columns.

    A CSV read from disk is all text: "1200" and "$1,200" are both strings.
    For each column we strip out "$" and "," and try to read the cells as
    numbers. If at least 80% of them work, we keep the numeric version.

    Cells that still don't parse stay as NaN. We deliberately do NOT fill them
    in with the column mean: fake data points sitting exactly on the mean would
    inflate the sample size and shrink the variance and standard deviation --
    the exact numbers this tool exists to report. The analysis methods drop
    those NaNs instead.
    """
    for col in df.columns:
        text = df[col].astype(str).str.replace(r"[$,]", "", regex=True)
        # _coerce_numeric drops the NHANES fill value before we decide anything:
        # a column that is mostly fill is mostly missing, and shouldn't count as
        # numeric or feed the statistics.
        numbers = _coerce_numeric(text)
        if numbers.notna().mean() >= NUMERIC_THRESHOLD:
            df[col] = numbers
    return df


def _num(x, ndigits=3):
    """Round a number so it is safe to send as JSON, or return None if it isn't
    a usable number.

    Statistics on odd input can come back as NaN or infinity (an empty group, a
    column where every value is identical, a regression that can't be solved).
    Those break JSON and, worse, can look like real answers. Every statistic
    that leaves this file goes through here, so a broken calculation shows up as
    a clean null on the website instead of garbage.
    """
    try:
        value = float(x)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(value):  # NaN or infinity
        return None
    return round(value, ndigits)


def _is_significant(p_value, alpha=ALPHA):
    """True if the p-value is real and below the significance cutoff."""
    return bool(np.isfinite(p_value) and p_value < alpha)


class DataAnalyzer:
    """Runs statistics on one pandas DataFrame.

    Create it once with a cleaned DataFrame, then call whichever analysis tier
    you want:

        analyzer = DataAnalyzer(df_cleanup(pd.read_csv("data.csv")))
        analyzer.basic_analysis("age")
    """

    def __init__(self, df):
        self.df = df

    # ------------------------------------------------------------------
    # Small shared helpers. Every tier below uses these, so the rule for
    # "what counts as a number" lives in exactly one place.
    # ------------------------------------------------------------------

    def _numbers(self, column):
        """One column as numbers, with unreadable and missing cells dropped."""
        return _coerce_numeric(self.df[column]).dropna()

    def _numbers_for(self, *columns):
        """Several columns as numbers, keeping only rows where they are ALL
        present. Correlation and regression need matched-up rows, so a row with
        a gap in any one column has to go."""
        frame = self.df[list(columns)].apply(_coerce_numeric)
        return frame.dropna()

    def _value_and_group(self, value_column, group_column):
        """The numeric column paired with a label column (age vs. sex, say),
        keeping only rows where both are present. The group column stays as
        labels; only the value column is turned into numbers."""
        data = self.df[[value_column, group_column]].copy()
        data[value_column] = _coerce_numeric(data[value_column])
        return data.dropna()

    def _numeric_column_names(self):
        """Names of the columns that are numeric enough to analyze. These are
        the candidate predictors for the correlation and regression tiers."""
        return [
            col
            for col in self.df.columns
            if _coerce_numeric(self.df[col]).notna().mean()
               >= NUMERIC_THRESHOLD
        ]

    def _other_numeric_columns(self, column):
        """Every numeric column except the one being analyzed."""
        return [c for c in self._numeric_column_names() if c != column]

    def _sorted_groups(self, data, group_column):
        """The distinct group labels in a sensible order.

        The sort key puts numbers before strings, because Python refuses to
        compare 3 < "adult" and would crash on a mixed column.
        """
        return sorted(
            data[group_column].unique(), key=lambda g: (isinstance(g, str), g)
        )

    # ==================================================================
    # TIER 1: BASIC -- the stats everyone knows.
    # ==================================================================

    def basic_analysis(self, column):
        """Mean, median, mode, range, and spread for one numeric column."""
        series = self._numbers(column)
        if series.empty:
            return {"error": "No numeric values in that column."}

        # .mode() can return several values when there is a tie for most common,
        # so we report the whole list.
        modes = series.mode()
        mode_values = modes.tolist() if not modes.empty else float("nan")

        return {
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
        whether the groups in group_column differ."""
        series = self._numbers(column)
        if series.empty:
            return {"error": "No numeric values in that column."}

        result: dict[str, Any] = {
            "column": column,
            "distribution": self._distribution_metrics(series),
            "uncertainty": self._uncertainty_metrics(series),
        }
        if group_column is not None:
            result["groups"] = self._group_tests(column, group_column)
        return result

    def _distribution_metrics(self, series):
        """What shape is this data? Quartiles, spread, lopsidedness, outliers."""
        q1 = series.quantile(0.25)  # 25% of values are below this
        median = series.median()  # the middle value
        q3 = series.quantile(0.75)  # 75% of values are below this
        iqr = q3 - q1  # the middle half of the data
        skewness = series.skew()  # + = long tail on the right, - = on the left
        kurtosis = series.kurtosis()  # how heavy the tails are

        # An outlier here means "more than 3 standard deviations from the mean".
        # We report just the count instead of dumping every one. If every value
        # is identical the std is 0 and dividing by it gives NaN, so we skip.
        std = series.std()
        if std and np.isfinite(std) and std != 0:
            z_scores = (series - series.mean()) / std
            outliers = int((z_scores.abs() > 3).sum())
        else:
            outliers = 0

        metrics = {"q1": _num(q1), "median": _num(median), "q3": _num(q3), "iqr": _num(iqr), "skewness": _num(skewness),
                   "kurtosis": _num(kurtosis), "outliers": outliers,
                   "log_transform": self._log_transform(series, skewness)}
        return metrics

    def _log_transform(self, series, skewness):
        """Badly lopsided data (skew above 1 either way) often straightens out if
        you take the logarithm of every value, which makes other tests behave
        better. We only try it when every value is positive -- the log of zero or
        a negative number is undefined and would quietly produce NaN.
        """
        can_take_log = abs(skewness) > 1 and bool((series > 0).all())
        if not can_take_log:
            return {"applied": False, "skewness": None}
        return {"applied": True, "skewness": _num(np.log(series).skew())}

    def _uncertainty_metrics(self, series):
        """How precise is our estimate of the mean?

        We report the standard error (how much the mean would bounce around if we
        collected the data again) and a 95% confidence interval (the range we are
        95% confident the true mean falls inside).
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
            "n": n,
            "sem": _num(standard_error),
            "ci_lower": _num(mean - margin),
            "ci_upper": _num(mean + margin),
            "confidence_level": 0.95,
        }

    def _group_tests(self, value_column, group_column):
        """Do the groups actually differ? Two tests that ask it different ways.

        ANOVA asks whether the group AVERAGES differ. Chi-square asks whether
        being in the top half of the values is ASSOCIATED with the group.
        """
        data = self._value_and_group(value_column, group_column)
        groups = [g[value_column].to_numpy() for _, g in data.groupby(group_column)]

        return {
            "group_column": group_column,
            "n_groups": len(groups),
            "anova": self._anova(groups),
            "chi_square": self._median_split_chi_square(data, value_column, group_column),
        }

    def _anova(self, groups):
        """One-way ANOVA: do the group means differ by more than chance?"""
        # Needs at least 2 groups, and at least 2 values per group (one value has
        # no spread, so there is nothing to compare the difference against).
        if len(groups) < 2 or not all(len(g) >= 2 for g in groups):
            return {"error": "Need >= 2 groups with >= 2 values each for ANOVA."}

        f_statistic, p_value = sp.f_oneway(*groups)
        return {
            "f_statistic": _num(f_statistic),
            "p_value": _num(p_value, 4),
            "significant": _is_significant(p_value),
        }

    def _median_split_chi_square(self, data, value_column, group_column):
        """Chi-square test of independence.

        Chi-square compares two label columns, so we invent one: tag every row
        "high" or "low" depending on whether it beats the overall median. Then we
        count how many highs and lows land in each group and ask whether that
        split looks the same across groups.
        """
        median = data[value_column].median()
        level = np.where(data[value_column] > median, "high", "low")
        table = pd.crosstab(level, data[group_column])

        # The test needs both variables to actually vary -- at least 2 rows and
        # 2 columns in the table.
        if table.shape[0] < 2 or table.shape[1] < 2:
            return {"error": "Need a 2xN table (both variables must vary)."}

        chi2, _p, degrees_of_freedom, _expected = sp.chi2_contingency(table)
        return self._describe_test_statistic(chi2, df=degrees_of_freedom)

    def _describe_test_statistic(self, statistic, df=None, alpha=ALPHA):
        """Turn a raw test statistic into a p-value and a plain-English verdict.

        If we're given degrees of freedom, the statistic is a chi-square (we want
        the chance of getting one this big or bigger). Without them, it's a
        z-score from a normal distribution (we want both tails, so we double).
        """
        if df is not None:
            p_value = float(sp.chi2.sf(statistic, df))
        else:
            p_value = float(2 * sp.norm.sf(abs(statistic)))

        return {
            "statistic": _num(statistic),
            # scipy hands back a numpy integer, which JSON can't serialize.
            # Plain int() fixes it.
            "df": int(df) if df is not None else None,
            "p_value": _num(p_value, 4),
            "alpha": alpha,
            "significant": _is_significant(p_value, alpha),
        }

    # ==================================================================
    # TIER 3: ADVANCED -- how columns relate to each other.
    # ==================================================================

    def advanced_analysis(self, column, group_column=None):
        """Correlation with the other numeric columns, a regression predicting
        this column from them, and a check for confounding."""
        series = self._numbers(column)
        if series.empty:
            return {"error": "No numeric values in that column."}

        others = self._other_numeric_columns(column)
        result: dict[str, Any] = {
            "column": column,
            "correlations": {
                other: self._correlation(column, other) for other in others
            },
            "regression": self._regression(column, others),
        }

        # Confounding needs one "exposure" plus at least one thing to adjust for.
        # We pick automatically -- first other column is the exposure, the rest
        # are the confounders -- and name both choices in the output so it's clear
        # what was compared.
        if len(others) >= 2:
            result["confounding"] = self._confounding(
                outcome=column, exposure=others[0], confounders=others[1:]
            )

        if group_column is not None:
            result["trend"] = self._linear_trend(column, group_column)
        return result

    def _correlation(self, column1, column2):
        """Pearson correlation: do these two columns move together?

        r runs from -1 (perfect opposite) through 0 (unrelated) to +1 (perfect
        match). The p-value says whether an r that size could just be luck.
        """
        data = self._numbers_for(column1, column2)
        if len(data) < 3:
            return {"error": "Not enough overlapping numeric values."}

        r, p_value = sp.pearsonr(data[column1], data[column2])
        return {
            "r": _num(r),
            "p_value": _num(p_value, 4),
            "n": int(len(data)),
            "significant": _is_significant(p_value),
        }

    def _build_design_matrix(self, x_columns):
        """Assemble the predictor columns for a regression.

        Numeric predictors go in as they are. A label predictor ("male"/"female")
        has to become numbers first, so we one-hot encode it: one 0/1 column per
        category. drop_first=True leaves one category out as the baseline that the
        others are measured against -- keeping all of them would make the columns
        add up to a constant and the regression unsolvable.
        """
        parts = []
        for name in x_columns:
            column = self.df[name]
            numbers = _coerce_numeric(column)
            if numbers.notna().mean() >= NUMERIC_THRESHOLD:
                parts.append(numbers.rename(name))
            else:
                parts.append(
                    pd.get_dummies(column, prefix=name, drop_first=True, dtype=float)
                )
        return pd.concat(parts, axis=1)

    def _regression(self, y_column, x_columns, weights=None):
        """Predict y_column from the other columns with a straight-line fit.

        Ordinary least squares (OLS) finds the line closest to all the points.
        Pass a weights column to make some rows count more than others (weighted
        least squares, which survey data often needs).
        """
        try:
            import statsmodels.api as smapi

            y = _coerce_numeric(self.df[y_column])
            design = self._build_design_matrix(x_columns)
            # Line up outcome and predictors, then keep only complete rows.
            frame = pd.concat([y.rename(y_column), design], axis=1).dropna()

            # Weights have to be matched to the rows that survived, and a row with
            # a missing weight has to go -- a single NaN weight turns the entire
            # fit into NaNs.
            row_weights = None
            if weights is not None:
                row_weights = _coerce_numeric(
                    self.df[weights]
                ).reindex(frame.index)
                frame = frame[row_weights.notna()]
                row_weights = row_weights.dropna()

            predictors = [c for c in frame.columns if c != y_column]
            # You need more data points than things you're estimating, or the fit
            # is meaningless (it can pass perfectly through every point).
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
                "outcome": y_column,
                "predictors": predictors,
                # nobs is just the rows that survived filtering above; len(outcome)
                # is the same count and stays a plain int the type checker accepts.
                "n": int(len(outcome)),
                # R-squared: the fraction of the outcome's variation the model
                # explains, from 0 (none) to 1 (all of it).
                "r_squared": _num(model.rsquared),
                # Adjusted R-squared penalizes you for adding useless predictors.
                "adj_r_squared": _num(model.rsquared_adj),
                "coefficients": {k: _num(v) for k, v in model.params.items()},
                "p_values": {k: _num(v, 4) for k, v in model.pvalues.items()},
                "standardized_betas": self._standardized_betas(
                    model, design_with_intercept, outcome
                ),
                "weighted": weights is not None,
            }
        except Exception as exc:  # unsolvable matrix, an all-NaN column, etc.
            return {"error": f"Regression failed: {exc}"}

    def _standardized_betas(self, model, design, outcome):
        """Coefficients rescaled so they can be compared to each other.

        A raw coefficient is in the predictor's own units, so "per year of age"
        and "per pound of weight" can't be ranked. Multiplying by (predictor's
        spread / outcome's spread) puts them all on the same scale, and the
        biggest one is the most influential predictor.
        """
        outcome_std = outcome.std()
        return {
            name: (
                _num(coefficient * design[name].std() / outcome_std)
                if outcome_std
                else None
            )
            for name, coefficient in model.params.items()
            if name != "const"  # the intercept isn't a predictor
        }

    def _confounding(self, outcome, exposure, confounders=None, mediator=None):
        """Is the exposure's apparent effect real, or explained by something else?

        A CONFOUNDER is a lurking third variable that makes a fake link look real
        (ice-cream sales "cause" drownings -- both are really caused by summer).
        Test: measure the exposure's effect alone, then measure it again while
        holding the confounders constant. If the effect moves by more than 10%,
        the confounders were doing some of the work.

        A MEDIATOR is a step ON the causal path (exercise -> lower weight -> lower
        blood pressure). Test: the effect that survives holding the mediator
        constant is the DIRECT effect; whatever's left travelled through the
        mediator and is the INDIRECT effect.
        """
        try:
            import statsmodels.api as smapi

            def effect_of_exposure(predictors):
                """Fit outcome ~ predictors and return the exposure's coefficient."""
                frame = self._numbers_for(outcome, *predictors)
                model = smapi.OLS(
                    frame[outcome], smapi.add_constant(frame[list(predictors)])
                ).fit()
                return model.params[exposure]

            # "Crude" = the exposure's effect with nothing else accounted for.
            crude = effect_of_exposure([exposure])
            result: dict[str, Any] = {
                "outcome": outcome,
                "exposure": exposure,
                "crude_effect": _num(crude),
            }

            if confounders:
                adjusted = effect_of_exposure([exposure, *confounders])
                # How much did the effect shift once we adjusted? (Guard against
                # a crude effect of exactly 0, which we can't divide by.)
                percent_change = abs((crude - adjusted) / crude) * 100 if crude else None
                result["adjusted_effect"] = _num(adjusted)
                result["confounders"] = list(confounders)
                result["percent_change"] = _num(percent_change, 1)
                result["confounding_detected"] = bool(
                    percent_change is not None and percent_change > 10
                )

            if mediator:
                direct = effect_of_exposure([exposure, mediator])
                indirect = crude - direct
                result["mediation"] = {
                    "mediator": mediator,
                    "total_effect": _num(crude),
                    "direct_effect": _num(direct),
                    "indirect_effect": _num(indirect),
                    "proportion_mediated": _num(indirect / crude) if crude else None,
                }
            return result
        except Exception as exc:
            return {"error": f"Confounding analysis failed: {exc}"}

    def _linear_trend(self, column, group_column):
        """Does the value climb (or fall) steadily as you move across the groups?

        We put the groups in order, number them 0, 1, 2, ..., and fit a line
        through (group number, value). A significant slope means a real trend --
        which is more specific than ANOVA's "the groups differ somehow".
        """
        data = self._value_and_group(column, group_column)
        groups = self._sorted_groups(data, group_column)
        if len(data) < 3 or len(groups) < 2:
            return {"error": "Need >= 2 ordered groups with >= 3 total values."}

        group_number = {group: i for i, group in enumerate(groups)}
        x = data[group_column].map(group_number).astype(float)
        line = sp.linregress(x, data[column].astype(float))

        return {
            "group_column": group_column,
            "n_groups": len(groups),
            "group_order": [str(g) for g in groups],
            "slope": _num(line.slope),  # change in value per step up the groups
            "r": _num(line.rvalue),
            "p_value": _num(line.pvalue, 4),
            "significant": _is_significant(line.pvalue),
        }

    # ==================================================================
    # TIER 4: EXPERT -- checking whether the models above can be trusted.
    # ==================================================================

    def expert_analysis(self, column, group_column=None):
        """Collinearity between predictors, checks on the regression's residuals,
        and clinical cutoff counts."""
        series = self._numbers(column)
        if series.empty:
            return {"error": "No numeric values in that column."}

        others = self._other_numeric_columns(column)
        result: dict[str, Any] = {"column": column}

        if len(others) >= 2:
            result["multicollinearity"] = self._multicollinearity(others)
            result["diagnostics"] = self._regression_diagnostics(column, others)

        # With no medical threshold supplied, use the column's own median so
        # there's always something meaningful to classify against.
        result["clinical"] = self._clinical_metrics(
            column, cutoff=float(series.median())
        )

        if group_column is not None:
            result["trend_tests"] = self._trend_in_proportions(column, group_column)
        return result

    def _multicollinearity(self, x_columns):
        """Are the predictors telling us the same thing twice?

        If height-in-inches and height-in-cm are both predictors, the regression
        can't tell which one deserves the credit and its numbers get unstable.
        The variance inflation factor (VIF) measures this per predictor; above 10
        is the usual "this one is redundant" alarm.
        """
        try:
            import statsmodels.api as smapi
            from statsmodels.stats.outliers_influence import variance_inflation_factor

            frame = self._numbers_for(*x_columns)
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
                "n": int(len(frame)),
                "vif": vifs,
                "high_multicollinearity": [
                    name for name, vif in vifs.items() if vif is not None and vif > 10
                ],
            }
        except Exception as exc:
            return {"error": f"VIF computation failed: {exc}"}

    def _regression_diagnostics(self, column, others):
        """Fit column ~ the other numeric columns and inspect what's left over.

        The residuals are the model's misses (actual minus predicted). If the
        model is any good, the misses should be small, centered on zero, and
        randomly scattered -- not patterned.
        """
        try:
            import statsmodels.api as smapi

            frame = self._numbers_for(column, *others)
            if len(frame) <= len(others) + 1:  # not enough rows to fit
                return None
            model = smapi.OLS(frame[column], smapi.add_constant(frame[others])).fit()
            return self._residual_checks(model.resid)
        except Exception as exc:
            return {"error": f"Diagnostics failed: {exc}"}

    def _residual_checks(self, residuals):
        """Are the model's leftover errors well-behaved?

        Shapiro-Wilk tests whether they follow a normal bell curve -- here a HIGH
        p-value is the good news (no evidence they're abnormal). We also count
        the badly-missed points: residuals more than 3 standard deviations out.
        """
        resid = pd.Series(residuals).dropna().astype(float)
        n = int(len(resid))
        checks: dict[str, Any] = {"n": n, "mean_residual": _num(resid.mean())}

        if n >= 3:  # Shapiro-Wilk's minimum sample size
            statistic, p_value = sp.shapiro(resid)
            checks["normality"] = {
                "test": "shapiro-wilk",
                "statistic": _num(statistic),
                "p_value": _num(p_value, 4),
                # Note the flipped logic: p > 0.05 means we FAILED to prove the
                # residuals are abnormal, which is what we want.
                "normal_residuals": bool(np.isfinite(p_value) and p_value > ALPHA),
            }

        std = resid.std()
        if std and np.isfinite(std) and std != 0:
            z_scores = (resid - resid.mean()) / std
            checks["influential_points"] = int((z_scores.abs() > 3).sum())
        return checks

    def _clinical_metrics(self, column, cutoff=None):
        """Split the column at a medical threshold and count each side.

        Also reports the triglyceride-to-HDL ratio (a heart-risk marker) when the
        dataset happens to carry both of those columns.
        """
        series = self._numbers(column)
        metrics: dict[str, Any] = {"column": column, "n": int(series.count())}

        if cutoff is not None and not series.empty:
            at_or_above = int((series >= cutoff).sum())
            metrics["cutoff"] = cutoff
            metrics["at_or_above"] = at_or_above
            metrics["below"] = int((series < cutoff).sum())
            metrics["proportion_at_or_above"] = _num(at_or_above / series.count())

        # Match column names case-insensitively -- files spell it "HDL", "hdl", ...
        by_lowercase_name = {c.lower(): c for c in self.df.columns}
        if "triglycerides" in by_lowercase_name and "hdl" in by_lowercase_name:
            triglycerides = _coerce_numeric(
                self.df[by_lowercase_name["triglycerides"]]
            )
            hdl = _coerce_numeric(self.df[by_lowercase_name["hdl"]])
            # An HDL of 0 would divide to infinity; throw those rows out.
            ratio = (triglycerides / hdl).replace([np.inf, -np.inf], np.nan).dropna()
            metrics["trig_hdl_ratio"] = {
                "mean": _num(ratio.mean()),
                "n": int(ratio.count()),
            }
        return metrics

    def _trend_in_proportions(self, column, group_column, p_values=None,
                              method="bonferroni"):
        """Cochran-Armitage trend test, plus an optional multiple-comparison fix.

        _linear_trend (advanced tier) asks whether the AVERAGE climbs across the
        groups. This asks whether the PERCENTAGE above the median climbs -- the
        same question about a yes/no outcome instead of a number.
        """
        result: dict[str, Any] = {
            "cochran_armitage": self._cochran_armitage(column, group_column)
        }
        if p_values:
            result["multiple_comparisons"] = self._correct_p_values(p_values, method)
        return result

    def _cochran_armitage(self, column, group_column):
        """Does the share of "high" values rise steadily across ordered groups?

        Group them in order, label each row high/low by the median, then compare
        each group's actual number of highs to the number you'd expect if the
        groups were all identical. Weight those gaps by the group's position and
        add them up: a big total means the highs pile up at one end.
        """
        try:
            data = self._value_and_group(column, group_column)
            groups = self._sorted_groups(data, group_column)
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
                (group_size * score ** 2).sum()
                - (group_size * score).sum() ** 2 / total_rows
            )
            variance = overall_high_rate * (1 - overall_high_rate) * spread_of_scores
            if variance <= 0:
                # Every row high, every row low, or only one group has data --
                # there is no trend to measure.
                return {"error": "Zero variance for trend."}

            # Standardize into a z-score, then read off the two-tailed p-value.
            z = trend_statistic / variance ** 0.5
            p_value = float(2 * sp.norm.sf(abs(z)))
            return {
                "group_order": [str(g) for g in groups],
                "z": _num(z),
                "p_value": _num(p_value, 4),
                "significant": _is_significant(p_value),
            }
        except Exception as exc:
            return {"error": f"Trend test failed: {exc}"}

    def _correct_p_values(self, p_values, method="bonferroni"):
        """Run 20 tests and one will look "significant" by luck alone. This raises
        the bar to compensate for how many tests were run."""
        from statsmodels.stats.multitest import multipletests

        rejected, corrected, _, _ = multipletests(p_values, method=method)
        return {
            "method": method,
            "corrected_p_values": [_num(p, 4) for p in corrected],
            "significant": [bool(r) for r in rejected],
        }

    # ==================================================================
    # CATEGORICAL -- for label columns (sex, region, brand) rather than
    # numbers. You can't take the mean of "male", so these get counts.
    # ==================================================================

    def categorical_analysis(self, column):
        """Counts and proportions for a label column, cross-tabulated against the
        next label column if the dataset has one."""
        result: dict[str, Any] = {"summary": self._category_counts(column)}

        numeric = set(self._numeric_column_names())
        other_labels = [
            c for c in self.df.columns if c != column and c not in numeric
        ]
        if other_labels:
            result["contingency"] = self._contingency_table(column, other_labels[0])
        return result

    def _category_counts(self, column):
        """How many rows in each category, and what share of the total."""
        values = self.df[column].dropna().astype(str)
        counts = values.value_counts()
        total = int(counts.sum())

        if total == 0:
            return {"column": column, "n": 0, "unique": 0, "counts": {}}

        return {
            "column": column,
            "n": total,
            "unique": int(counts.size),  # how many distinct categories
            "counts": {name: int(count) for name, count in counts.items()},
            "proportions": {
                name: _num(count / total) for name, count in counts.items()
            },
        }

    def _contingency_table(self, column1, column2):
        """Cross-tabulate two label columns and test them for independence.

        The table counts every combination (how many rows are male AND smokers?).
        Chi-square then asks whether the two labels are related, or whether the
        counts are just what you'd expect if they had nothing to do with each other.
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
            "columns": [column1, column2],
            "table": {
                row: {col: int(counts[i, j]) for j, col in enumerate(col_labels)}
                for i, row in enumerate(row_labels)
            },
        }

        # Both labels have to actually vary for the test to mean anything.
        if table.shape[0] >= 2 and table.shape[1] >= 2:
            chi2, p_value, degrees_of_freedom, _expected = sp.chi2_contingency(table)
            result["chi_square"] = {
                "statistic": _num(chi2),
                "p_value": _num(p_value, 4),
                "df": int(degrees_of_freedom),
                "significant": _is_significant(p_value),
            }
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
        import matplotlib.pyplot as plt
        from pathlib import Path

        if output_dir is not None:
            out = Path(output_dir)
        else:
            out = Path(__file__).resolve().parent.parent / "Data" / "figures"
        out.mkdir(parents=True, exist_ok=True)

        produced = {}
        for column in self._numeric_column_names():
            series = self._numbers(column)
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


# ======================================================================
# COMMAND-LINE ENTRY POINT -- for poking at the engine during development.
# ======================================================================

# Which DataAnalyzer method each tier name maps to. app.py has the same routing
# for its JSON API (see run_analysis there); this is the terminal-side twin so a
# dev can exercise the exact same tiers without booting the web server.
_TIERS = {
    "basic": lambda analyzer, column, group: analyzer.basic_analysis(column),
    "medium": lambda analyzer, column, group: analyzer.medium_analysis(column, group),
    "advanced": lambda analyzer, column, group: analyzer.advanced_analysis(column, group),
    "expert": lambda analyzer, column, group: analyzer.expert_analysis(column, group),
    "categorical": lambda analyzer, column, group: analyzer.categorical_analysis(column),
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

    Kept off the module's import path (argparse/json/pathlib load here, not at the
    top) so importing engine.py stays cheap for Render's cold start.
    """
    import argparse
    import json
    from pathlib import Path

    default_csv = Path(__file__).resolve().parent.parent / "Data" / "nhanes_analytic.csv"

    parser = argparse.ArgumentParser(
        description="Run the stats engine on a CSV from the terminal."
    )
    parser.add_argument(
        "--csv", type=Path, default=default_csv,
        help="CSV file to analyze (default: Data/nhanes_analytic.csv).",
    )
    parser.add_argument(
        "--tier", default="basic", choices=list(_TIERS),
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
    if args.column:
        columns = [args.column]
    elif args.tier == "categorical":
        numeric = set(analyzer._numeric_column_names())
        columns = [c for c in df.columns if c not in numeric]
    else:
        columns = analyzer._numeric_column_names()

    output = {column: run_tier(analyzer, column, args.group) for column in columns}
    # default=str is a safety net for any stray numpy/pandas scalar; _num() has
    # already turned the statistics themselves into plain floats and Nones.
    print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    main()
