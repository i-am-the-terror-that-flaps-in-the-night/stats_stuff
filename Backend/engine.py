"""
engine.py -- the backend stats engine.

Pure data logic, no console I/O: load-time cleaning of the dataframe and the
descriptive-statistics computations. app.py imports df_cleanup and DataAnalyzer
from here and exposes them over HTTP; tests/test_engine.py exercises them directly.

DataAnalyzer keeps a small public surface -- one entry point per level of
statistical complexity (basic -> medium -> advanced -> expert) plus a categorical
branch. Each of the higher tiers keeps its own helper routines nested inside it,
so the machinery for a tier lives with the method that owns it.

IMPORT COST
    Only pandas and scipy load at module import; the web service uses just the
    basic tier, so the heavyweights the higher tiers need -- statsmodels and
    matplotlib -- are imported lazily inside the methods that use them, keeping
    them off Render's cold-start path (see the "SPEED ON RENDER" note in app.py).
"""

import numpy as np
import pandas as pd
import scipy.stats as sp


def df_cleanup(df):
    """Coerce columns that are >=80% numeric (after stripping $ and ,) to numeric
    dtype, leaving the rest unchanged."""
    for col in df.columns:
        cleaned = df[col].astype(str).str.replace(r"[$,]", "", regex=True)
        coerced = pd.to_numeric(cleaned, errors="coerce")
        # noinspection SpellCheckingInspection
        if coerced.notna().mean() >= 0.8:  # mostly numbers -> treat as numeric
            # Keep the un-parseable cells as NaN rather than imputing them with the
            # mean. Imputing would silently inflate n and shrink variance/std (the
            # filled points sit exactly on the mean), distorting the very stats this
            # tool reports. basic_analysis() drops these NaNs before summarizing.
            df[col] = coerced
    return df


def _num(x, ndigits=3):
    """Round to a JSON-friendly float, mapping NaN/inf (and non-numbers) to None.

    Every stat that reaches an HTTP response goes through here so a degenerate
    input (empty group, zero variance, singular design matrix) surfaces as a
    clean null instead of a NaN that breaks JSON or a silently wrong number.
    """
    try:
        val = float(x)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(val):
        return None
    return round(val, ndigits)


class DataAnalyzer:
    def __init__(self, df):
        self.df = df

    # --- shared column helpers ------------------------------------------------

    def _numeric_series(self, column):
        """The column coerced to numeric with un-parseable/missing cells dropped --
        the same rule basic_analysis() applies, factored out for the other tiers."""
        return pd.to_numeric(self.df[column], errors="coerce").dropna()

    def _numeric_column_names(self):
        """Columns that are >=80% numeric after coercion -- the analyzable columns
        the regression/correlation tiers draw their predictors from."""
        return [
            c
            for c in self.df.columns
            if pd.to_numeric(self.df[c], errors="coerce").notna().mean() >= 0.8
        ]

    def basic_analysis(self, column):
        series = pd.to_numeric(self.df[column], errors="coerce").dropna()

        if series.empty:
            return {"error": "No numeric values in that column."}

        modes = series.mode()
        mode_vals = modes.tolist() if not modes.empty else float("nan")

        return {
            "column": column,
            # Sample size actually summarized: the NaN cells were dropped above,
            # so for a column with an un-parseable cell this is below the row count.
            "n": int(series.count()),
            "mean": round(float(series.mean()), 3),
            "median": float(series.median()),
            "mode": mode_vals,
            "min": float(series.min()),
            "max": float(series.max()),
            "std": round(float(series.std()), 3),
            "variance": round(float(series.var()), 3),
        }

    def medium_analysis(self, column, group_column=None):
        """Intermediate tier: distribution shape, uncertainty, and group tests.

        The routines this tier is built from are defined as nested helpers below.
        """

        # --- Distribution metrics ---
        def _distribution_metrics(series):
            # Quartiles, spread, shape, an outlier count, and -- for a skewed,
            # strictly-positive column -- what a log transform does to the skew.
            Q1 = series.quantile(0.25)
            Q2 = series.median()
            Q3 = series.quantile(0.75)
            IQR = Q3 - Q1
            skewness = series.skew()
            kurtosis = series.kurtosis()

            # z-scores are per-row; report them as a summary (count of |z| > 3)
            # rather than dumping the whole array. Guard the constant-column case
            # (std == 0) where every z-score would be NaN.
            std = series.std()
            if std and np.isfinite(std) and std != 0:
                z_scores = (series - series.mean()) / std
                outliers = int((z_scores.abs() > 3).sum())
            else:
                outliers = 0

            metrics: dict[str, object] = {
                "q1": _num(Q1),
                "median": _num(Q2),
                "q3": _num(Q3),
                "iqr": _num(IQR),
                "skewness": _num(skewness),
                "kurtosis": _num(kurtosis),
                "outliers": outliers,
            }

            # A right/left skew above ~1 in magnitude often pulls toward normal
            # under a log. Only valid on strictly-positive data -- np.log of a
            # zero/negative silently yields -inf/NaN, so we gate on it and flag
            # when we skipped.
            if abs(skewness) > 1 and bool((series > 0).all()):
                metrics["log_transform"] = {
                    "applied": True,
                    "skewness": _num(np.log(series).skew()),
                }
            else:
                metrics["log_transform"] = {"applied": False, "skewness": None}

            return metrics

        # --- Uncertainty metrics ---
        def _uncertainty_metrics(series):
            # Standard error of the mean and a 95% t-based confidence interval
            # for the mean.
            n = int(series.count())
            if n < 2:
                # df = n - 1 would be <= 0 and t.ppf returns NaN; report the gap
                # instead of emitting a NaN interval.
                return {
                    "n": n,
                    "sem": None,
                    "ci_lower": None,
                    "ci_upper": None,
                    "confidence_level": 0.95,
                    "error": "Need at least 2 values for a confidence interval.",
                }
            mean = series.mean()
            SEM = series.sem()
            t_crit = sp.t.ppf(0.975, df=n - 1)  # two-tailed 95%
            margin = t_crit * SEM
            return {
                "n": n,
                "sem": _num(SEM),
                "ci_lower": _num(mean - margin),
                "ci_upper": _num(mean + margin),
                "confidence_level": 0.95,
            }

        # --- Hypothesis testing ---
        def _hypothesis_testing(statistic, df=None, alpha=0.05):
            # Turn a test statistic into a p-value and classify it. With df we
            # treat the statistic as chi-square (upper tail); without, as a
            # two-tailed standard normal (z). Used by _group_tests for the
            # chi-square below.
            if df is not None:
                p = float(sp.chi2.sf(statistic, df))
            else:
                p = float(2 * sp.norm.sf(abs(statistic)))
            return {
                "statistic": _num(statistic),
                # df arrives from scipy as a numpy int (not JSON-serializable over
                # HTTP); coerce to a plain int.
                "df": int(df) if df is not None else None,
                "p_value": _num(p, 4),
                "alpha": alpha,
                "significant": bool(p < alpha),
            }

        # --- Group analysis ---
        def _group_tests(value_column, group_column):
            # Two complementary tests across the groups:
            #   * one-way ANOVA -- do the group *means* of the numeric value differ?
            #   * chi-square of independence -- is being above/below the overall
            #     median (a derived categorical) associated with the group?
            data = self.df[[value_column, group_column]].copy()
            data[value_column] = pd.to_numeric(data[value_column], errors="coerce")
            data = data.dropna()

            result = {"group_column": group_column}
            grouped = [
                g[value_column].to_numpy() for _, g in data.groupby(group_column)
            ]
            result["n_groups"] = len(grouped)

            if len(grouped) >= 2 and all(len(g) >= 2 for g in grouped):
                f_stat, p = sp.f_oneway(*grouped)
                result["anova"] = {
                    "f_statistic": _num(f_stat),
                    "p_value": _num(p, 4),
                    "significant": bool(np.isfinite(p) and p < 0.05),
                }
            else:
                result["anova"] = {
                    "error": "Need >= 2 groups with >= 2 values each for ANOVA."
                }

            # Median-split the value into a high/low label, cross-tab against the
            # group, and hand the chi-square statistic to _hypothesis_testing.
            median = data[value_column].median()
            level = np.where(data[value_column] > median, "high", "low")
            table = pd.crosstab(level, data[group_column])
            if table.shape[0] >= 2 and table.shape[1] >= 2:
                chi2, _p, dof, _exp = sp.chi2_contingency(table)
                result["chi_square"] = _hypothesis_testing(chi2, df=dof)
            else:
                result["chi_square"] = {
                    "error": "Need a 2xN table (both variables must vary)."
                }
            return result

        # --- Orchestrate ---
        series = self._numeric_series(column)
        if series.empty:
            return {"error": "No numeric values in that column."}

        result = {
            "column": column,
            "distribution": _distribution_metrics(series),
            "uncertainty": _uncertainty_metrics(series),
        }
        if group_column is not None:
            result["groups"] = _group_tests(column, group_column)
        return result

    def advanced_analysis(self, column, group_column=None):
        """Advanced tier: correlation, regression, and confounding.

        The routines this tier is built from are defined as nested helpers below.
        """

        def _correlation_analysis(column1, column2):
            # Pearson correlation coefficient (and its p-value) between two numeric
            # columns, over the rows where both are present.
            data = (
                self.df[[column1, column2]]
                .apply(pd.to_numeric, errors="coerce")
                .dropna()
            )
            if len(data) < 3:
                return {"error": "Not enough overlapping numeric values."}
            r, p = sp.pearsonr(data[column1], data[column2])
            return {
                "r": _num(r),
                "p_value": _num(p, 4),
                "n": int(len(data)),
                "significant": bool(np.isfinite(p) and p < 0.05),
            }

        def _regression_models(y_column, x_columns, weights=None):
            # Ordinary least squares of y on the predictors (weighted least squares
            # when a weights column is named). Numeric predictors go in as-is;
            # categorical ones are one-hot / dummy encoded (drop-first). Reports
            # R-squared and standardized beta coefficients.
            try:
                import statsmodels.api as smapi

                y = pd.to_numeric(self.df[y_column], errors="coerce")
                parts = []
                for xc in x_columns:
                    col = self.df[xc]
                    num = pd.to_numeric(col, errors="coerce")
                    if num.notna().mean() >= 0.8:  # numeric predictor
                        parts.append(num.rename(xc))
                    else:  # categorical predictor -> dummies
                        parts.append(
                            pd.get_dummies(col, prefix=xc, drop_first=True, dtype=float)
                        )
                design = pd.concat(parts, axis=1)
                frame = pd.concat([y.rename(y_column), design], axis=1).dropna()

                # When weighting, align the weights to the surviving rows and drop
                # any row whose weight is itself missing -- a NaN weight silently
                # turns the whole fit into NaNs.
                w = None
                if weights is not None:
                    w = pd.to_numeric(self.df[weights], errors="coerce").reindex(
                        frame.index
                    )
                    frame = frame[w.notna()]
                    w = w.dropna()

                predictors = [c for c in frame.columns if c != y_column]
                if len(frame) <= len(predictors) + 1:
                    return {"error": "Too few complete rows for this many predictors."}

                y_clean = frame[y_column]
                X = smapi.add_constant(frame[predictors])
                if w is not None:
                    model = smapi.WLS(y_clean, X, weights=w).fit()
                else:
                    model = smapi.OLS(y_clean, X).fit()

                # Standardized beta = coef * (std of predictor / std of outcome).
                sy = y_clean.std()
                betas = {
                    name: (_num(coef * X[name].std() / sy) if sy else None)
                    for name, coef in model.params.items()
                    if name != "const"
                }

                return {
                    "outcome": y_column,
                    "predictors": predictors,
                    "n": int(model.nobs),
                    "r_squared": _num(model.rsquared),
                    "adj_r_squared": _num(model.rsquared_adj),
                    "coefficients": {k: _num(v) for k, v in model.params.items()},
                    "p_values": {k: _num(v, 4) for k, v in model.pvalues.items()},
                    "standardized_betas": betas,
                    "weighted": weights is not None,
                }
            except Exception as exc:  # singular matrix, all-NaN column, etc.
                return {"error": f"Regression failed: {exc}"}

        def _confounding_analysis(outcome, exposure, confounders=None, mediator=None):
            # Confounding: does the exposure->outcome coefficient move once we
            # adjust for the confounders? (>10% shift is the usual flag.)
            # Mediation: split the total exposure effect into the part that
            # survives adjusting for the mediator (direct) and the rest (indirect).
            try:
                import statsmodels.api as smapi

                def _fit(y, xs):
                    frame = (
                        self.df[[y, *xs]].apply(pd.to_numeric, errors="coerce").dropna()
                    )
                    return smapi.OLS(frame[y], smapi.add_constant(frame[xs])).fit()

                crude = _fit(outcome, [exposure]).params[exposure]
                result = {
                    "outcome": outcome,
                    "exposure": exposure,
                    "crude_effect": _num(crude),
                }

                if confounders:
                    adjusted = _fit(outcome, [exposure, *confounders]).params[exposure]
                    pct = abs((crude - adjusted) / crude) * 100 if crude else None
                    result["adjusted_effect"] = _num(adjusted)
                    result["confounders"] = list(confounders)
                    result["percent_change"] = _num(pct, 1)
                    result["confounding_detected"] = bool(pct is not None and pct > 10)

                if mediator:
                    direct = _fit(outcome, [exposure, mediator]).params[exposure]
                    indirect = crude - direct
                    result["mediation"] = {
                        "mediator": mediator,
                        "total_effect": _num(crude),
                        "direct_effect": _num(direct),
                        "indirect_effect": _num(indirect),
                        "proportion_mediated": (
                            _num(indirect / crude) if crude else None
                        ),
                    }
                return result
            except Exception as exc:
                return {"error": f"Confounding analysis failed: {exc}"}

        def _linear_trend_test(column, group_column):
            # Order the groups, code them 0,1,2,..., and regress the value on that
            # code -- a significant slope means a linear trend across the groups.
            data = self.df[[column, group_column]].copy()
            data[column] = pd.to_numeric(data[column], errors="coerce")
            data = data.dropna()

            groups = sorted(
                data[group_column].unique(), key=lambda g: (isinstance(g, str), g)
            )
            if len(data) < 3 or len(groups) < 2:
                return {"error": "Need >= 2 ordered groups with >= 3 total values."}

            codes = {g: i for i, g in enumerate(groups)}
            x = data[group_column].map(codes).astype(float)
            reg = sp.linregress(x, data[column].astype(float))
            return {
                "group_column": group_column,
                "n_groups": len(groups),
                "group_order": [str(g) for g in groups],
                "slope": _num(reg.slope),
                "r": _num(reg.rvalue),
                "p_value": _num(reg.pvalue, 4),
                "significant": bool(np.isfinite(reg.pvalue) and reg.pvalue < 0.05),
            }

        # --- Orchestrate ---
        series = self._numeric_series(column)
        if series.empty:
            return {"error": "No numeric values in that column."}

        others = [c for c in self._numeric_column_names() if c != column]
        result = {
            "column": column,
            "correlations": {c: _correlation_analysis(column, c) for c in others},
            "regression": _regression_models(column, others),
        }
        # Confounding needs an exposure plus at least one confounder. Following the
        # same auto-pick spirit as the regression above, take the first other
        # numeric as the exposure and the rest as confounders; the result names
        # both so the choice is explicit.
        if len(others) >= 2:
            result["confounding"] = _confounding_analysis(
                column, others[0], confounders=others[1:]
            )
        if group_column is not None:
            result["trend"] = _linear_trend_test(column, group_column)
        return result

    def expert_analysis(self, column, group_column=None):
        """Expert tier: multicollinearity, diagnostics, and clinical metrics.

        The routines this tier is built from are defined as nested helpers below.
        """

        def _multicollinearity(x_columns):
            # Variance inflation factor per predictor. VIF > 10 is the usual
            # "this predictor is badly collinear with the others" threshold.
            try:
                import statsmodels.api as smapi
                from statsmodels.stats.outliers_influence import (
                    variance_inflation_factor,
                )

                frame = (
                    self.df[x_columns].apply(pd.to_numeric, errors="coerce").dropna()
                )
                # add_constant prepends a 'const' column. Work off the raw matrix
                # and the frame's own labels rather than X.values/X.columns: its
                # (ndarray | DataFrame) return type has neither attribute for sure.
                matrix = np.asarray(smapi.add_constant(frame))
                names = ["const", *frame.columns]
                vifs = {
                    name: _num(variance_inflation_factor(matrix, i))
                    for i, name in enumerate(names)
                    if name != "const"
                }
                return {
                    "n": int(len(frame)),
                    "vif": vifs,
                    "high_multicollinearity": [
                        k for k, v in vifs.items() if v is not None and v > 10
                    ],
                }
            except Exception as exc:
                return {"error": f"VIF computation failed: {exc}"}

        def _model_diagnostics(residuals):
            # Checks on a fitted model's residuals. Normality via Shapiro-Wilk;
            # leverage/influence proper need the hat matrix (not just residuals),
            # so we proxy influence with the count of standardized residuals whose
            # magnitude exceeds 3.
            resid = pd.Series(residuals).dropna().astype(float)
            n = int(len(resid))
            out: dict[str, object] = {"n": n, "mean_residual": _num(resid.mean())}
            if n >= 3:
                w, p = sp.shapiro(resid)
                out["normality"] = {
                    "test": "shapiro-wilk",
                    "statistic": _num(w),
                    "p_value": _num(p, 4),
                    "normal_residuals": bool(np.isfinite(p) and p > 0.05),
                }
            std = resid.std()
            if std and np.isfinite(std) and std != 0:
                z = (resid - resid.mean()) / std
                out["influential_points"] = int((z.abs() > 3).sum())
            return out

        def _clinical_metrics(column, cutoff=None):
            # Classify the column against a clinical cutoff (how many at/above vs
            # below), plus the triglyceride-to-HDL ratio when the dataset actually
            # carries those columns.
            series = self._numeric_series(column)
            out = {"column": column, "n": int(series.count())}

            if cutoff is not None and not series.empty:
                at_or_above = int((series >= cutoff).sum())
                out["cutoff"] = cutoff
                out["at_or_above"] = at_or_above
                out["below"] = int((series < cutoff).sum())
                out["proportion_at_or_above"] = _num(at_or_above / series.count())

            lower = {c.lower(): c for c in self.df.columns}
            if "triglycerides" in lower and "hdl" in lower:
                tg = pd.to_numeric(self.df[lower["triglycerides"]], errors="coerce")
                hdl = pd.to_numeric(self.df[lower["hdl"]], errors="coerce")
                ratio = (tg / hdl).replace([np.inf, -np.inf], np.nan).dropna()
                out["trig_hdl_ratio"] = {
                    "mean": _num(ratio.mean()),
                    "n": int(ratio.count()),
                }
            return out

        def _significance_tests(
            column, group_column, p_values=None, method="bonferroni"
        ):
            # Cochran-Armitage trend in proportions: across ordered groups, does
            # the share above the median rise/fall linearly? Plus a multiple-
            # comparison correction of any p-values handed in.
            out = {}
            try:
                data = self.df[[column, group_column]].copy()
                data[column] = pd.to_numeric(data[column], errors="coerce")
                data = data.dropna()

                groups = sorted(
                    data[group_column].unique(), key=lambda g: (isinstance(g, str), g)
                )
                if len(data) >= 3 and len(groups) >= 2:
                    success = (data[column] > data[column].median()).astype(int)
                    scores = pd.Series(range(len(groups)), index=groups, dtype=float)
                    n_i = data.groupby(group_column).size().reindex(groups).fillna(0)
                    r_i = (
                        success.groupby(data[group_column])
                        .sum()
                        .reindex(groups)
                        .fillna(0)
                    )

                    N = int(n_i.sum())
                    R = int(r_i.sum())
                    p_bar = R / N
                    # Cochran-Armitage trend statistic (asymptotically normal).
                    T = float((scores * (r_i - n_i * p_bar)).sum())
                    var = (
                        p_bar
                        * (1 - p_bar)
                        * float((n_i * scores**2).sum() - (n_i * scores).sum() ** 2 / N)
                    )
                    if var > 0:
                        z = T / var**0.5
                        p = float(2 * sp.norm.sf(abs(z)))
                        out["cochran_armitage"] = {
                            "group_order": [str(g) for g in groups],
                            "z": _num(z),
                            "p_value": _num(p, 4),
                            "significant": bool(p < 0.05),
                        }
                    else:
                        out["cochran_armitage"] = {"error": "Zero variance for trend."}
                else:
                    out["cochran_armitage"] = {"error": "Need >= 2 ordered groups."}
            except Exception as exc:
                out["cochran_armitage"] = {"error": f"Trend test failed: {exc}"}

            if p_values:
                from statsmodels.stats.multitest import multipletests

                reject, corrected, _, _ = multipletests(p_values, method=method)
                out["multiple_comparisons"] = {
                    "method": method,
                    "corrected_p_values": [_num(x, 4) for x in corrected],
                    "significant": [bool(x) for x in reject],
                }
            return out

        # --- Orchestrate ---
        series = self._numeric_series(column)
        if series.empty:
            return {"error": "No numeric values in that column."}

        others = [c for c in self._numeric_column_names() if c != column]
        result = {"column": column}

        if len(others) >= 2:
            result["multicollinearity"] = _multicollinearity(others)
            # Diagnostics run on the residuals of column ~ the other numerics.
            try:
                import statsmodels.api as smapi

                frame = (
                    self.df[[column, *others]]
                    .apply(pd.to_numeric, errors="coerce")
                    .dropna()
                )
                if len(frame) > len(others) + 1:
                    model = smapi.OLS(
                        frame[column], smapi.add_constant(frame[others])
                    ).fit()
                    result["diagnostics"] = _model_diagnostics(model.resid)
            except Exception as exc:
                result["diagnostics"] = {"error": f"Diagnostics failed: {exc}"}

        # Default the clinical cutoff to the column's own median so there's always
        # something to classify against even without a domain threshold supplied.
        result["clinical"] = _clinical_metrics(column, cutoff=float(series.median()))

        if group_column is not None:
            result["trend_tests"] = _significance_tests(column, group_column)
        return result

    def categorical_analysis(self, column):
        """Categorical branch: summaries and cross-tabulations for label columns.

        The routines this branch is built from are defined as nested helpers below.
        """

        def _categorical_summary(column):
            # Per-category counts and proportions for a label column.
            s = self.df[column].dropna().astype(str)
            counts = s.value_counts()
            total = int(counts.sum())
            if total == 0:
                return {"column": column, "n": 0, "unique": 0, "counts": {}}
            return {
                "column": column,
                "n": total,
                "unique": int(counts.size),
                "counts": {k: int(v) for k, v in counts.items()},
                "proportions": {k: _num(v / total) for k, v in counts.items()},
            }

        def _contingency_table(column1, column2):
            # Cross-tabulate two label columns and test them for independence.
            data = self.df[[column1, column2]].dropna().astype(str)
            table = pd.crosstab(data[column1], data[column2])
            # Read cells off the raw count matrix: table.loc[r, c] is typed as a
            # broad Scalar (could be complex) that int() rejects; the ndarray cell
            # is a plain integer count.
            counts = np.asarray(table)
            row_labels = [str(r) for r in table.index]
            col_labels = [str(c) for c in table.columns]
            result: dict[str, object] = {
                "columns": [column1, column2],
                "table": {
                    row_labels[i]: {
                        col_labels[j]: int(counts[i, j])
                        for j in range(len(col_labels))
                    }
                    for i in range(len(row_labels))
                },
            }
            if table.shape[0] >= 2 and table.shape[1] >= 2:
                chi2, p, dof, _ = sp.chi2_contingency(table)
                result["chi_square"] = {
                    "statistic": _num(chi2),
                    "p_value": _num(p, 4),
                    "df": int(dof),
                    "significant": bool(np.isfinite(p) and p < 0.05),
                }
            return result

        # --- Orchestrate ---
        result = {"summary": _categorical_summary(column)}
        # Cross-tab against the first *other* categorical column if there is one.
        numeric = set(self._numeric_column_names())
        others = [c for c in self.df.columns if c != column and c not in numeric]
        if others:
            result["contingency"] = _contingency_table(column, others[0])
        return result

    def figure_production(self, output_dir=None):
        """Render a histogram + boxplot per numeric column, saved as PDF (for
        download) and SVG (for the website). Returns {column: {"pdf", "svg"}}.

        matplotlib is imported here (not at module top) and forced onto the
        headless Agg backend so this runs on a server with no display and stays
        off the cold-start import path."""
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from pathlib import Path

        out = (
            Path(output_dir)
            if output_dir is not None
            else Path(__file__).resolve().parent.parent / "Data" / "figures"
        )
        out.mkdir(parents=True, exist_ok=True)

        produced = {}
        for col in self._numeric_column_names():
            series = self._numeric_series(col)
            if series.empty:
                continue
            fig, (ax_hist, ax_box) = plt.subplots(1, 2, figsize=(8, 3))
            ax_hist.hist(series, bins="auto", edgecolor="white")
            ax_hist.set_title(f"{col} — distribution")
            ax_box.boxplot(series, orientation="vertical")
            ax_box.set_title(f"{col} — spread")
            ax_box.set_xticks([])
            fig.tight_layout()

            pdf_path = out / f"{col}.pdf"
            svg_path = out / f"{col}.svg"
            fig.savefig(pdf_path)
            fig.savefig(svg_path)
            plt.close(fig)
            produced[col] = {"pdf": str(pdf_path), "svg": str(svg_path)}
        return produced
