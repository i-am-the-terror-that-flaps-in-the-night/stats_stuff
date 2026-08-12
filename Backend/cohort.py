"""
cohort.py -- turn the raw NHANES merge into the study's analytic cohort.

WHAT THIS IS FOR
    Data/nhanes_analytic.csv is the full 2017-2018 merge: 9,254 participants of
    every age by 412 raw-coded columns. The study this project exists to run is
    much narrower than that -- U.S. adolescents aged 12-17, a dozen named
    variables, viral hepatitis excluded -- and every analysis downstream assumes
    that narrowing has already happened.

    This module is that narrowing, written down once. It reads the raw merge,
    applies the inclusion and exclusion rules, decodes NHANES' numeric answer
    codes into real quantities, renames the variables to something a human can
    read, derives the handful of constructed measures the analysis needs, and
    writes Data/nhanes_adolescent.csv -- roughly 700 rows and 100 KB, which is
    small enough to commit and to load in a few milliseconds on a cold start.

    That split is deliberate and it is what makes the deploy work. The raw merge
    is 17 MB and lives in Git LFS; the *derived* cohort is an ordinary tracked
    file. Production reads the derived file and never touches the raw one, so a
    Render dyno that never fetched an LFS object still boots correctly. Rebuild
    the cohort on a machine that has the raw file:

        python Backend/cohort.py            # rebuild, print the attrition table
        python Backend/cohort.py --check    # rebuild in memory, diff vs the
                                            # committed file, change nothing

    --check is what CI runs: it fails if the committed CSV no longer matches
    what this code produces, so the data and the code that derives it cannot
    drift apart silently.

EVERY DECISION THAT SHRINKS THE SAMPLE IS RECORDED
    build_cohort() returns the cohort *and* an attrition log -- one row per
    filter, naming the rule and how many participants it removed. Nothing here
    drops a participant without that showing up in the log, which is what makes
    the final n auditable rather than asserted. The log ships to the API as
    /api/study/cohort, so the number on the website traces back to a named rule.

    NOTHING IS EVER IMPUTED. A participant missing a variable the analysis needs
    is dropped from analyses that need it, exactly as engine.py does everywhere
    else. See ANALYSIS_CORE below for what "needs it" means, and note that screen
    time is deliberately NOT in that set.

THREE PLACES THIS DEPARTS FROM THE WRITTEN PROTOCOL
    Each is a case where the protocol names a variable that does not mean what
    the name suggests, or does not exist at the stated sample size. They are
    corrections, not preferences, and each is spelled out at its definition:

      1. Hepatitis B. The protocol excludes on "Hepatitis B Surface Antigen
         (HEPB_S_J)". HEPB_S_J is the surface *antibody* file -- a marker of
         VACCINATION, positive in 179 of these adolescents. Excluding on it
         would have thrown out the vaccinated. The surface *antigen* (the actual
         infection marker) is LBDHBG, in HEPBD_J. See VIRAL_EXCLUSIONS.
      2. Triglycerides. The protocol names TRIGLY_J (LBXTR), which is drawn only
         from the fasting subsample and exists for 341 of these adolescents --
         it cannot support the stated n. LBXSTR, the same analyte on the MEC
         biochemistry panel, exists for 749. See TRIGLYCERIDE_SOURCE.
      3. Screen time. Present as specified, but missing for 113 adolescents who
         otherwise qualify, so requiring it would cost 16% of the sample. It is
         a variable with its own reduced n rather than an entry criterion.

    The resulting cohort is n = 699. The protocol says 695. The four-participant
    gap is not explained by any rule stated in the protocol -- pregnancy status,
    recall reliability, a positive dietary weight and a positive ALT are all
    already true of every one of the 699 -- so this code reports what the stated
    rules actually produce rather than reverse-engineering a filter to land on
    695. See COHORT_N_NOTE.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW_CSV = ROOT / "Data" / "nhanes_analytic.csv"
COHORT_CSV = ROOT / "Data" / "nhanes_adolescent.csv"

# The sentinel the analytic merge writes for a missing numeric cell. Shared with
# engine.py, which applies it on every read; repeated here because this module
# reads the raw CSV itself, before any engine code touches it.
ANALYTIC_MISSING_SENTINEL = 5.397605346934028e-79

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
# ranking, and any ABSOLUTE cutoff applied to it (see study.py's risk score)
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


def build_cohort(raw: pd.DataFrame | None = None, raw_path: Path = RAW_CSV):
    """Derive the analytic cohort. Returns (cohort_df, attrition_log).

    attrition_log is a list of {"step", "rule", "n", "removed"} dicts -- one per
    filter, in the order applied -- so the final n can be traced back through
    every decision that produced it.
    """
    if raw is None:
        raw = pd.read_csv(raw_path, low_memory=False)

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
# Both of these are used by study.py at analysis time AND written into the
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
# On where the cut points come from -- two of them are published clinical lines
# and four are cohort quantiles, and the difference is not arbitrary:
#
#   * HbA1c 5.7% is the ADA's prediabetes line, a real external threshold.
#   * Male sex is a category, not a cut point.
#   * Sugar, screen time, BMI and Trig/HDL have no adolescent screening
#     threshold this project can honestly cite. There is no published "grams of
#     sugar per day above which a 14-year-old's liver is at risk", and BMI in
#     adolescents is scored against CDC growth-chart percentiles that are
#     age- and sex-specific to the month -- a table this project does not carry.
#     So these four are defined as the cohort's own top quartile.
#
# That makes the score a RELATIVE instrument: it ranks this cohort against
# itself and cannot be carried to another population unchanged, because the cut
# points would move. It is labelled exploratory in the protocol and it is
# reported that way. Using the cohort's own quartiles is also why the Trig/HDL
# component is unaffected by the non-fasting triglyceride's upward level shift
# (see TRIGLYCERIDE_SOURCE) -- a shift that moves every value moves the quartile
# with it, and the same people land in the top quartile either way.
RISK_QUARTILE_COMPONENTS = ("TotalSugars", "ScreenTime", "BMI", "TrigHDLRatio")
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

    for column in RISK_QUARTILE_COMPONENTS:
        cut = float(df[column].quantile(0.75))
        cutpoints[column] = cut
        points.append((df[column] >= cut).where(df[column].notna()))

    cutpoints["HbA1c"] = HBA1C_PREDIABETES
    points.append((df["HbA1c"] >= HBA1C_PREDIABETES).where(df["HbA1c"].notna()))

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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument(
        "--check",
        action="store_true",
        help="rebuild in memory and compare against the committed CSV; write nothing",
    )
    parser.add_argument("--raw", type=Path, default=RAW_CSV)
    parser.add_argument("--out", type=Path, default=COHORT_CSV)
    args = parser.parse_args(argv)

    if not args.raw.is_file():
        print(f"Raw merge not found: {args.raw}", file=sys.stderr)
        print(
            "It is stored in Git LFS -- run `git lfs pull` to fetch it. The "
            "committed cohort CSV is what production reads, so this is only "
            "needed to REBUILD the cohort.",
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
        if committed.equals(rebuilt):
            print(f"\nOK -- {args.out.name} matches what this code produces.")
            return 0
        print(
            f"\nDRIFT -- {args.out.name} does NOT match what this code produces. "
            "Re-run without --check to regenerate it.",
            file=sys.stderr,
        )
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    cohort.to_csv(args.out, index=False)
    print(f"wrote {args.out}")
    return 0


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


if __name__ == "__main__":
    raise SystemExit(main())
