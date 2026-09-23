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
    deploy that never fetched an LFS object still boots correctly. Rebuild
    the cohort on a machine that has the raw file:

        python Backend/cli.py build-cohort          # rebuild, print attrition
        python Backend/cli.py build-cohort --check  # rebuild in memory, diff
                                           # vs the committed file, change nothing

    --check is what CI runs: it fails if the committed CSV no longer matches
    what this code produces, so the data and the code that derives it cannot
    drift apart silently.

    TWO artifacts come out of that command, not one: the cohort CSV and
    Data/cohort_attrition.json. The log is committed for exactly the same
    reason the cohort is -- producing it is the only thing in the study that
    needs the raw merge, and doing it at request time cost 109 MB of peak RSS
    on a 512 MB instance to recompute five rows that had not changed since the
    last deploy. See cohort_attrition() and raw_merge_available().

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

THE COHORT IS THE REVISED PROTOCOL'S, AND IT REPRODUCES ITS NUMBERS
    The Revised Methods (6.1.26) Step 1 states four rules -- ages 12-17, a
    reliable day-1 dietary recall, no viral hepatitis B or C, and complete data
    on the model's variables -- and the Revised Results report what they
    produce: 907 -> 804 -> 802 -> 695 for the lifestyle model, and 314 in the
    fasting subsample the metabolic model needs (147 males, 167 females).
    Applied here, exactly as written, they produce exactly those counts. The
    attrition log below is that derivation, one row per rule.

    ONE PLACE THE PROTOCOL'S VARIABLE NAME IS CORRECTED, NOT ITS RULE
    The original proposal names "Hepatitis B (HEPB_S_J)" as the exclusion file.
    HEPB_S_J carries the surface *antibody* (LBXHBS) -- a marker of VACCINATION,
    positive in 179 of these adolescents -- and the project's own "Excluding
    HBV" note corrects this: the infection markers are the core antibody
    (LBXHBC) and surface antigen (LBDHBG) in HEPBD_J. Those are what is used.
    See VIRAL_EXCLUSIONS.

    ONE HISTORICAL BUG WORTH KNOWING ABOUT
    The raw merge writes every genuine zero as 5.397605346934028e-79 (an
    artifact of pandas' SAS-transport reader; see engine.XPORT_ZERO). An
    earlier version of this file read that value as "missing" and blanked it,
    which deleted every "less than 1 hour" screen-time answer and left the
    cohort 16% short of the protocol's n. Zeros are now read as zeros.
"""

from __future__ import annotations

import argparse
import json
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

# Two import paths because this file is reached two ways: with Backend/ on
# sys.path (pytest, `python Backend/cli.py build-cohort`) and with the repo
# root on it (`uvicorn main:app`, which imports Backend.app). Same idiom as
# app.py's _load_engine(). engine.py never imports back, so there is no cycle.
try:
    from engine import XPORT_ZERO
except ImportError:
    from Backend.engine import XPORT_ZERO


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
    in Git LFS and the deploy build deliberately never fetches it, so what sits at
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
    "Applying the Revised Methods Step 1 rules as written reproduces the "
    "Revised Results exactly: 907 adolescents, 804 with a reliable day-1 "
    "recall, 802 without viral hepatitis, 695 complete on the lifestyle "
    "model's variables, and 314 of those in the fasting subsample the "
    "metabolic model requires."
)

# Day-1 dietary recall status. 1 = reliable and met the minimum criteria; every
# other code (2 = not reliable, 4 = reported consuming breast milk, 5 = not
# done) means the sugar figure cannot be used. The protocol's Step 2 names this
# as the reason day 1 is the exposure, and its Step 1 applies it as a filter.
RECALL_RELIABLE = 1

# ----------------------------------------------------------------------
# VARIABLE MAP -- NHANES code -> the name this project uses.
#
# Names deliberately match the conventions of the curated extract this cohort
# replaces (BMI, Triglycerides, HDLCholesterol, HbA1c), so the
# Studio, the figures and the clinical-threshold table in engine.py keep working
# against the same identifiers.
# ----------------------------------------------------------------------

# The fasting-subsample triglyceride from TRIGLY_J, as the protocol names it.
# NHANES measures it only on the morning fasting subsample, so it -- and the
# Trig/HDL ratio built from it -- exists for 314 of the 695 adolescents in the
# lifestyle sample. That is the "fasting subsample" the Revised Results report
# Model B on, and the reason Model B runs on fewer people than Model A.
#
# LBXSTR, the same analyte on the non-fasting biochemistry panel, exists for
# nearly everyone and was used by an earlier version of this file to double the
# metabolic sample. It was reverted: a non-fasting triglyceride sits ~14 mg/dL
# high after a meal, it is not what the protocol specifies, and the study's
# written results were derived from the fasting value.
TRIGLYCERIDE_SOURCE = "LBXTR"

VARIABLES = {
    # Identity and survey design
    "SEQN": "SEQN",
    # Dietary day-1 weight. The protocol's chosen weight, and the correct one
    # for any analysis whose exposure comes from the day-1 recall.
    "WTDRD1": "DietWeight",
    "SDMVPSU": "SurveyPSU",
    "SDMVSTRA": "SurveyStratum",
    # Demographics. The poverty-income ratio is deliberately absent: the
    # revised protocol removed it from the analysis.
    "RIDAGEYR": "Age",
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
# why these variables and not the file the original proposal names.
#
# Both hepatitis B markers come from HEPBD_J. LBXHBC is the core antibody --
# positive after any past or current infection -- and LBDHBG the surface
# ANTIGEN, the marker of current infection (1 = Positive, 2 = Negative, 3 =
# Indeterminate). Either positive excludes, per the project's "Excluding HBV"
# note. The original proposal named HEPB_S_J, which is the surface ANTIBODY
# file (LBXHBS): antibody positivity means the immune system has seen the virus
# or, far more commonly in this age group, a vaccine. 179 of these 907
# adolescents are anti-HBs positive, and excluding them would have removed the
# vaccinated from a study about sugar. It is not used.
#
# LBDHCI is the confirmed hepatitis C antibody and LBXHCR the viral RNA. Their
# code 3 ("Negative Screening HCV Antibody") and code 2 are both negative
# results; only 1 (Positive) and, for the antibody, 4 (Positive HCV RNA) mean
# infection.
#
# In this age band the rule removes two adolescents, both core-antibody
# positive, which is the count the Revised Results report (804 -> 802).
VIRAL_EXCLUSIONS = {
    "LBXHBC": (1,),  # hepatitis B core antibody positive (past or current)
    "LBDHBG": (1,),  # hepatitis B surface antigen positive (current)
    "LBDHCI": (1, 4),  # hepatitis C antibody confirmed positive / RNA positive
    "LBXHCR": (1,),  # hepatitis C RNA positive
}

# The variables a participant must have to be in the cohort at all: the
# outcome, the exposure, the survey weight, and everything Model A (the
# lifestyle model: sugar, screen time, age, sex) uses. This is the protocol's
# "missing any variable in the analysis" rule applied to the model every
# participant is eligible for, and it yields the Revised Results' n = 695.
#
# The metabolic markers are NOT here. Triglycerides (and so the Trig/HDL ratio)
# exist only for the fasting subsample, so Model B runs on the 314 who have
# them -- the protocol's "fasting subsample" -- and study.py takes that
# subsample from this cohort at analysis time rather than shrinking the whole
# cohort to it. HbA1c and BMI are kept in the cohort with whatever coverage
# they have; the analyses that need them drop the few who lack them.
ANALYSIS_CORE = [
    "ALT",
    "TotalSugars",
    "DietWeight",
    "ScreenTime",
    "Age",
    "Sex",
]

# What Model B additionally requires. Exposed here beside ANALYSIS_CORE so the
# two sample definitions the study reports live in one place.
METABOLIC_VARIABLES = ["Triglycerides", "HDLCholesterol", "HbA1c", "BMI"]

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

    PAQ710 and PAQ715 are banded choices, decoded exactly as the project's
    Variable Reference and Supplementary Report state ("0-5 hrs; 8 = 8+ hrs;
    99 = DK excluded"):

        0-5 "0 / 1 / 2 / 3 / 4 / 5+ hours" -> as-is (5 is "5 hours or more")
        8   -> 8.0
        77 Refused, 99 Don't know         -> missing

    This is the coding the Revised Results were computed with, and it is what
    lets this code reproduce them to the last digit. Two caveats belong next to
    it. Code 5 is right-censored -- "5 hours or more" becomes 5.0 -- which
    compresses the top of the distribution and, if anything, biases a
    screen-time association toward zero. And the NHANES codebook labels code 8
    as "does not watch TV / use a computer", i.e. a zero; the protocol reads it
    as 8+ hours. 28 of the 907 adolescents give that answer on each question.
    An earlier version of this file decoded 8 as 0.0 and 0 as 0.5; the numbers
    it produced differed from the Revised Results in the second decimal of
    every p-value, and the protocol's coding is the one reported.
    """
    hours = pd.to_numeric(series, errors="coerce")
    return hours.replace({REFUSED: np.nan, DONT_KNOW: np.nan})


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

    # The XPT zero artifact first, before any comparison or count: left in
    # place, "less than 1 hour of TV" reads as 5e-79 hours and a dietary weight
    # of zero passes a "> 0" check.
    raw = raw.replace(XPORT_ZERO, 0.0)

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

    # 2. A reliable day-1 dietary recall. The exposure comes from this recall,
    #    so a participant whose recall NHANES flags as unusable has no exposure.
    d = record(
        "Reliable day-1 dietary recall",
        f"DR1DRSTZ = {RECALL_RELIABLE}",
        d[d["DR1DRSTZ"] == RECALL_RELIABLE],
    )

    # 3. Viral hepatitis. Isolates metabolic liver stress from viral hepatitis,
    #    which raises ALT through an entirely different mechanism.
    infected = pd.Series(False, index=d.index)
    for code, positive in VIRAL_EXCLUSIONS.items():
        infected |= d[code].isin(positive)
    d = record(
        "No viral hepatitis B or C",
        "anti-HBc-, HBsAg-, HCV antibody- and HCV RNA-negative "
        "(LBXHBC/LBDHBG/LBDHCI/LBXHCR)",
        d[~infected],
    )

    # 4. Rename and decode into study variables.
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

    # 5. Constructed measures.
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

    # 6. Complete cases on the lifestyle model's variables. This is the
    #    protocol's n = 695.
    out = record(
        "Complete on the lifestyle model's variables",
        "ALT, sugar, dietary weight, screen time, age and sex all present",
        out.dropna(subset=ANALYSIS_CORE),
    )

    # 7. A usable survey weight. A zero dietary weight means the participant is
    #    not part of the day-1 dietary estimation sample. Every reliable recall
    #    has one, so this removes nobody; it is logged rather than assumed.
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
    """Flag ALT strictly above the sex-specific pediatric screening threshold.

    Returns a nullable boolean: a participant with no ALT or no sex has no flag
    rather than a False, because "not elevated" and "not measured" must not
    collapse into the same value in a prevalence count.
    """
    cutoff = df["Sex"].map(ALT_ELEVATED)
    # Strictly above: the guideline reads "> 26 U/L", and ALT is reported in
    # whole units, so 22 in a girl is normal and 23 is not.
    flag = df["ALT"] > cutoff
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
# reported that way. The score exists only for the fasting subsample, because
# its Trig/HDL component does; see risk_score for where each median is taken.
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

    # Each cut point is the median over everyone in the frame who has that
    # component -- the protocol's "sample median". Hand this the whole cohort:
    # sugar, screen time, BMI and HbA1c are then cut at the full sample's
    # midpoint and only the Trig/HDL ratio at the fasting subsample's, which is
    # the convention the Revised Results' score bands were built on.
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
    except (OSError, ValueError):
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


# ======================================================================
# THE COHORT
# ======================================================================


@lru_cache(maxsize=1)
def load_cohort() -> pd.DataFrame:
    """The analytic cohort, read once and reused.

    Reads the committed, derived CSV -- not the 17 MB raw merge, which lives in
    Git LFS and is absent in production by design -- see build_cohort() above.
    If the
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
    and 137 ms -- inside a 1024 MB serverless function on a shared vCPU,
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
