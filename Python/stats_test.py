"""
Build one analytic table from every NHANES 2017-2018 file in data/csv_data/.

THE ONE RULE: every file joins on SEQN (unique participant ID).
THE ONE STRUCTURE: DEMO_J is the spine. Everything LEFT-joins onto it, because
DEMO contains every participant plus the design variables (weights, strata, PSU)
that all weighted analysis needs.

This pulls EVERY column from EVERY file in data/csv_data/ -- the output is the
full union of variables, not a hand-picked subset. Files are read from the
pre-converted .csv (pd.read_csv); raw .xpt is still handled transparently.
Download files from: https://wwwn.cdc.gov/nchs/nhanes/continuousnhanes/
  (Cycle 2017-2018; each component page has an "XPT Data File" link.)

--- SURVEY WEIGHTS: which weight goes with which variable --------------------
NHANES is a complex multistage sample; never analyze it unweighted, and always
cluster on SDMVPSU nested in SDMVSTRA. Pick the weight of the MOST RESTRICTIVE
(smallest-subsample) variable in a given analysis:

  WTINT2YR  interview-only variables (questionnaires not repeated in the MEC)
  WTMEC2YR  MEC exam + standard labs  (BMX, BIOPRO, HDL, TCHOL, GHB, HSCRP, BPX)
  WTSAF2YR  fasting-subsample labs    (TRIGLY: LBXTR/LBDLDL; GLU: LBXGLU)  ~1/3
  WTDRD1    day-1 dietary recall       (DR1TOT)
  WTDR2D    2-day dietary average      (use when combining DR1TOT + DR2TOT)

There is NO valid single weight for mixing two different subsamples (e.g. a
fasting lab with a dietary variable) -- use the rarest subsample's weight and
treat the estimate as approximate.

GLUCOSE NOTE: fasting plasma glucose is LBXGLU (GLU_J), analyzed with WTSAF2YR.
The LBXSGL in BIOPRO_J is NON-fasting serum glucose on the full MEC sample
(WTMEC2YR) -- do not use it as a fasting measure.
"""

import pandas as pd
from pathlib import Path

DATA_DIR = Path("../data/csv_data")  # folder holding the data files
SPINE_FILE = "DEMO_J.csv"  # demographics + design variables


def read_nhanes(path):
    """Read one NHANES .csv (or raw .xpt), keyed on integer SEQN."""
    p = Path(path)
    if p.suffix.lower() == ".csv":
        df = pd.read_csv(p)
    else:
        df = pd.read_sas(p, format="xport")
    df["SEQN"] = df["SEQN"].astype("int64")
    return df


def merge_onto_demo(spine, files):
    """LEFT-join every component file onto the DEMO spine, reporting coverage.

    Aligns each component to the spine's participant order and concatenates all
    columns in a single pass -- no chained merges, no frame fragmentation, no
    silent column-collision suffixes.
    """
    base = spine.reset_index(drop=True)  # SEQN stays a normal column
    key = base["SEQN"]  # participant order to align everyone to
    seen = set(base.columns)  # columns already claimed (DEMO wins)
    parts = [base]
    for p in files:
        d = read_nhanes(p).set_index("SEQN")
        # A duplicate SEQN would silently fan out rows on join -- make it loud.
        if not d.index.is_unique:
            raise ValueError(f"{p.name}: duplicate SEQN -> would fan out rows")
        # Drop any column already supplied by an earlier file so we never create
        # silent duplicates -- e.g. WTDRD1/WTDR2D/DRABF/DRDINT shared by DR1TOT
        # & DR2TOT, and the DEMO design variables are never overwritten.
        dupes = [c for c in d.columns if c in seen]
        if dupes:
            d = d.drop(columns=dupes)
        seen.update(d.columns)
        matched = key.isin(d.index).sum()
        # reindex to the spine's SEQN order (NaN where this file has no row),
        # then drop the key so every part shares one positional index.
        parts.append(d.reindex(key).reset_index(drop=True))
        skip = f" (skipped dup cols: {', '.join(dupes)})" if dupes else ""
        print(
            f"{p.name:14} +{d.shape[1]:>3} cols | "
            f"matched {matched:>5}/{len(base)}{skip}"
        )
    return pd.concat(parts, axis=1)


# ---- Spine: full demographics (carries WTINT2YR/WTMEC2YR/SDMVSTRA/SDMVPSU) ---
demo = read_nhanes(DATA_DIR / SPINE_FILE)

# ---- Every other file in the folder, in stable alphabetical order -----------
components = sorted(
    p
    for p in DATA_DIR.glob("*")
    if p.suffix.lower() in (".csv", ".xpt") and p.name != SPINE_FILE
)

analytic = merge_onto_demo(demo, components)
out_file = DATA_DIR / "nhanes_analytic.csv"  # data/nhanes_analytic.csv
analytic.to_csv(out_file, index=False)
print(
    f"\nFinal analytic table: {analytic.shape[0]} rows x "
    f"{analytic.shape[1]} cols across {len(components) + 1} files "
    f"-> {out_file}"
)
