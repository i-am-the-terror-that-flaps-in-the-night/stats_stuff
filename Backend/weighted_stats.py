"""
weighted_stats.py -- design-based (weighted) estimates for the NHANES analytic
table that stats_test.py builds.

WHY THIS EXISTS
    nhanes_analytic.csv only *carries* the survey weights and design variables;
    plain pandas .mean() / .value_counts() / OLS on it are WRONG because they
    ignore NHANES's complex multistage sample design. This module applies the
    design correctly and -- the part you asked for -- picks the right weight for
    each variable automatically.

WHAT IT DOES
    pick_weight(var)            choose the correct weight column for a variable:
                                  fasting labs (LBXTR/LBDLDL/LBXGLU ...) -> WTSAF2YR
                                  day-1 diet (DR1*)                       -> WTDRD1
                                  day-2 diet (DR2*)                       -> WTDR2D
                                  interview-only (PAQ*/SLQ*/SLD*)         -> WTINT2YR
                                  everything else (exam + standard labs)  -> WTMEC2YR
                                Override with weight=... . The interview weight
                                is right only when the analysis uses interview
                                data alone; if you pair an interview item with
                                any MEC exam/lab variable, pass weight=WTMEC2YR.

    Survey.mean(var)           Taylor-linearized mean + SE + 95% CI
    Survey.proportion(var)     weighted proportion of each level (categorical)
    Survey.by(var, group)      the above within each level of `group`
    Survey.ols(y, [x1, x2])    design-based linear regression (cluster-robust)

    Standard errors use SDMVSTRA (strata) and SDMVPSU (clusters) via Taylor
    linearization, with proper DOMAIN estimation for subpopulations: pass a
    boolean `subpop` mask -- never pre-filter the DataFrame, because dropping
    rows discards PSUs and biases the variance.

RUN A WORKED DEMO
    cd Backend && uv run python weighted_stats.py
"""

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as _st

STRATA = "SDMVSTRA"
PSU = "SDMVPSU"

WT_MEC, WT_INT = "WTMEC2YR", "WTINT2YR"
WT_SAF, WT_DR1, WT_DR2 = "WTSAF2YR", "WTDRD1", "WTDR2D"

# Variables measured only in the morning fasting subsample -> fasting weight.
FASTING_VARS = {
    "LBXTR",
    "LBDTRSI",
    "LBDLDL",
    "LBDLDLSI",
    "LBDLDLM",
    "LBDLDMSI",
    "LBDLDLN",
    "LBDLDNSI",  # TRIGLY_J (fasting triglycerides / LDL)
    "LBXGLU",
    "LBDGLUSI",  # GLU_J    (fasting plasma glucose)
}

# Variables collected ONLY in the household interview (never in the MEC exam).
# Their unbiased estimate uses the interview weight, which covers the larger
# interviewed sample.  Matched by prefix: PAQ* (physical activity), SLQ*/SLD*
# (sleep).  CAVEAT: this weight is correct only for interview-data-only
# analyses -- pair any of these with a MEC exam/lab variable and you must pass
# weight=WTMEC2YR (NCHS: use the MEC weight whenever any MEC component is in the
# analysis).  Extend this tuple for other interview-only sections you analyze.
INTERVIEW_PREFIXES = ("PAQ", "SLQ", "SLD")


def pick_weight(var):
    """Return the survey weight column appropriate for `var`.

    NOTE: LBXSGL (BIOPRO serum glucose) is NON-fasting -> WTMEC2YR, unlike the
    fasting LBXGLU (GLU_J) -> WTSAF2YR. They are different measurements.

    Interview-only sections (INTERVIEW_PREFIXES) map to WTINT2YR, but only for
    interview-data-only analyses -- override with weight=WTMEC2YR when you pair
    them with any MEC exam/lab variable.
    """
    if var in FASTING_VARS:
        return WT_SAF
    if var.startswith("DR1"):
        return WT_DR1
    if var.startswith("DR2"):
        return WT_DR2
    if var.startswith(INTERVIEW_PREFIXES):
        return WT_INT
    return WT_MEC  # exam + standard labs, and questionnaire-with-exam analyses


def _analytic_path():
    here = Path(__file__).resolve().parent  # Backend/
    for cand in (
        here.parent / "Data" / "nhanes_analytic.csv",  # Data/ (canonical)
        here / "nhanes_analytic.csv",
        here.parent / "nhanes_analytic.csv",
        Path("nhanes_analytic.csv"),
    ):
        if cand.exists():
            return cand
    raise FileNotFoundError("nhanes_analytic.csv not found -- run stats_test.py first.")


class Survey:
    """A NHANES complex-survey design over the analytic table."""

    def __init__(self, df=None, strata=STRATA, psu=PSU):
        if df is None:
            df = pd.read_csv(_analytic_path())
        self.df = df.reset_index(drop=True)
        self._h = self.df[strata].to_numpy()
        # Unique (stratum, PSU) cluster id over the FULL sample.  Group on the
        # (stratum, PSU) pair directly: no assumption that PSU < 100, and no
        # int cast that would crash on a NaN/float design code -- a malformed
        # design is reported here as a clear error, not a cryptic cast crash.
        if self.df[[strata, psu]].isna().to_numpy().any():
            raise ValueError(
                f"design columns {strata!r}/{psu!r} contain missing values; "
                "every row needs a valid stratum and PSU."
            )
        self._hj = self.df.groupby([strata, psu], sort=False).ngroup().to_numpy()
        # Design integrity: Taylor linearization needs >=2 PSUs per stratum.
        # A singleton ("lonely") PSU makes the n_h/(n_h-1) factor in _lin_mean
        # blow up to inf, and inf*0 -> NaN; pandas .sum() then *silently skips*
        # that NaN, dropping the stratum from the variance and underestimating
        # every SE with no error. That only happens if rows were pre-filtered,
        # so refuse it loudly here (use subpop= instead -- see class docstring).
        # NOTE: this catches the singleton *symptom*, which is the failure mode
        # for a >=2-PSU-per-stratum design like NHANES (drop a PSU -> singleton).
        # It cannot see partial PSU loss in a >2-PSU design (3 PSUs filtered to
        # 2 still passes yet biases the variance), because the frame carries no
        # record of the original design -- so always pass the full sample.
        psu_per_stratum = (
            pd.DataFrame({"h": self._h, "hj": self._hj})
            .drop_duplicates()
            .groupby("h")
            .size()
        )
        lonely = list(psu_per_stratum.index[psu_per_stratum < 2])
        if lonely:
            raise ValueError(
                f"{len(lonely)} stratum/strata have a single PSU "
                f"(e.g. {strata}={lonely[:5]}), which biases the design "
                "variance. Do NOT pre-filter the DataFrame -- pass the full "
                "sample and restrict with the subpop= mask instead."
            )

    # --------------------------------------------------------------- estimates
    def mean(self, var, weight=None, subpop=None):
        """Design-based mean of a continuous variable."""
        w = self._weight_col(var, weight)
        y = pd.to_numeric(self.df[var], errors="coerce").to_numpy(float)
        dom = self._mask(subpop) & np.isfinite(y) & (w > 0)
        return self._lin_mean(y, w, dom, label=var)

    def proportion(self, var, weight=None, subpop=None):
        """Design-based proportion of each level of a categorical variable."""
        w = self._weight_col(var, weight)
        col = self.df[var]
        base = self._mask(subpop) & col.notna().to_numpy() & (w > 0)
        rows = []
        for level in sorted(pd.unique(col[base])):
            ind = (col == level).to_numpy(float)
            r = self._lin_mean(ind, w, base, label=f"{var}={level}")
            r["level"] = level
            rows.append(r)
        return pd.DataFrame(rows).reset_index(drop=True)

    def by(self, var, group, weight=None, subpop=None):
        """Design-based mean of `var` within each level of `group`."""
        g = self.df[group]
        base = self._mask(subpop) & g.notna().to_numpy()
        rows = []
        for level in sorted(pd.unique(g[base])):
            sub = base & (g == level).to_numpy()
            r = self.mean(var, weight=weight, subpop=sub)
            r[group] = level
            rows.append(r)
        return pd.DataFrame(rows).reset_index(drop=True)

    def ols(self, y, X, weight=None, subpop=None, add_const=True):
        """Design-based linear regression: WLS + cluster-robust SE on PSU.

        This is the standard Python stand-in for svyglm. It clusters on PSU but
        does not credit the variance reduction from stratification, so SEs are
        slightly CONSERVATIVE. For descriptive estimates prefer .mean/.proportion
        (full Taylor linearization). When predictors come from a more restrictive
        subsample than `y`, pass weight=... for the rarest subsample.
        """
        import statsmodels.api as sm

        w = self._weight_col(y, weight)
        cols = [y] + list(X)
        data = self.df[cols].apply(pd.to_numeric, errors="coerce")
        ok = self._mask(subpop) & (w > 0) & data.notna().all(axis=1).to_numpy()
        Xm = data.loc[ok, list(X)]
        if add_const:
            Xm = sm.add_constant(Xm)
        model = sm.WLS(data.loc[ok, y], Xm, weights=w[ok])
        return model.fit(cov_type="cluster", cov_kwds={"groups": self._hj[ok]})

    # --------------------------------------------------------------- internals
    def _weight_col(self, var, weight):
        col = weight or pick_weight(var)
        return pd.to_numeric(self.df[col], errors="coerce").to_numpy(float)

    def _mask(self, subpop):
        n = len(self.df)
        if subpop is None:
            return np.ones(n, dtype=bool)
        s = np.asarray(subpop)
        if s.dtype.kind != "b" or s.shape != (n,):
            raise ValueError("subpop must be a boolean mask over all rows")
        return s

    def _lin_mean(self, y, w, dom, label):
        """Mean over a domain with Taylor-linearized (strata+PSU) variance."""
        W = w[dom].sum()
        if W == 0:
            return dict(
                stat=label,
                mean=np.nan,
                se=np.nan,
                ci_low=np.nan,
                ci_high=np.nan,
                n=0,
                N_hat=0.0,
                dof=0,
            )
        ybar = (w[dom] * y[dom]).sum() / W
        # Linearized residual; 0 outside the domain so out-of-domain PSUs stay
        # in the design with a zero total (correct domain estimation).
        u = np.where(dom, w * (y - ybar) / W, 0.0)
        tab = pd.DataFrame({"h": self._h, "hj": self._hj, "u": u})
        psu_tot = tab.groupby("hj", sort=False).agg(h=("h", "first"), t=("u", "sum"))
        n_h = psu_tot.groupby("h")["t"].transform("size")
        tbar = psu_tot.groupby("h")["t"].transform("mean")
        var = float((n_h / (n_h - 1) * (psu_tot["t"] - tbar) ** 2).sum())
        dof = int(len(psu_tot) - psu_tot["h"].nunique())  # #PSUs - #strata
        se = float(np.sqrt(var))
        tcrit = float(_st.t.ppf(0.975, dof)) if dof > 0 else np.nan
        return dict(
            stat=label,
            mean=float(ybar),
            se=se,
            ci_low=float(ybar - tcrit * se),
            ci_high=float(ybar + tcrit * se),
            n=int(dom.sum()),
            N_hat=float(W),
            dof=dof,
        )


# --------------------------------------------------------------------- demo ---
if __name__ == "__main__":
    svy = Survey()
    print(f"Loaded {len(svy.df)} participants from {_analytic_path().name}\n")

    def show(d, name=None):
        print(
            f"  {name or d['stat']:26} mean={d['mean']:8.3f}  "
            f"SE={d['se']:6.3f}  95% CI [{d['ci_low']:7.3f}, "
            f"{d['ci_high']:7.3f}]  n={int(d['n'])}"
        )

    adults = (svy.df["RIDAGEYR"] >= 20).to_numpy()

    print(f"Mean BMI  (auto weight -> {pick_weight('BMXBMI')}), adults 20+:")
    show(svy.mean("BMXBMI", subpop=adults))

    print("\nMean BMI by sex (RIAGENDR 1=male, 2=female), adults 20+:")
    for _, r in svy.by("BMXBMI", "RIAGENDR", subpop=adults).iterrows():
        show(r, name=f"RIAGENDR={int(r['RIAGENDR'])}")

    print(
        f"\nMean fasting glucose LBXGLU (auto weight -> "
        f"{pick_weight('LBXGLU')}), adults 20+:"
    )
    show(svy.mean("LBXGLU", subpop=adults))

    print("\nObesity prevalence (BMI >= 30), adults 20+:")
    bmi = svy.df["BMXBMI"]
    # Build a small design-only frame for the derived 0/1 indicator (a Survey
    # works on any frame carrying the design columns).
    small = svy.df[[STRATA, PSU, WT_MEC, "RIDAGEYR"]].copy()
    small["_obese"] = np.where(bmi.notna(), (bmi >= 30).astype(float), np.nan)
    svy_o = Survey(small)
    d = svy_o.mean("_obese", weight=WT_MEC, subpop=(small["RIDAGEYR"] >= 20).to_numpy())
    print(
        f"  prevalence = {d['mean'] * 100:5.1f}%   SE={d['se'] * 100:.2f}%   "
        f"95% CI [{d['ci_low'] * 100:.1f}%, {d['ci_high'] * 100:.1f}%]  "
        f"n={int(d['n'])}"
    )

    print(
        "\nDesign-based regression  LBXGLU ~ BMXBMI  (fasting subsample, adults 20+):"
    )
    res = svy.ols("LBXGLU", ["BMXBMI"], subpop=adults)
    print(res.summary().tables[1])
