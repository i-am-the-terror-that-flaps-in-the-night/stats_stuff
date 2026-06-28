# stats-and-more

Python tools for exploratory statistics and **design-based (survey-weighted) analysis**
of [NHANES 2017–2018](https://wwwn.cdc.gov/nchs/nhanes/continuousnhanes/) data, plus a small practice dataset and an
early web preview scaffold.

## What this repo does

| Workflow             | Scripts                     | Output                                                                    |
|----------------------|-----------------------------|---------------------------------------------------------------------------|
| **NHANES pipeline**  | `main.py` → `stats_test.py` | One wide analytic table (`nhanes_analytic.csv`) merged on participant ID  |
| **Survey estimates** | `weighted_stats.py`         | Weighted means, proportions, subgroup tables, and design-based regression |
| **Practice dataset** | `extra.py`                  | Interactive column stats on `data/data.csv`                               |
| **Web preview**      | `Web/HTML/index.html`       | Minimal static page (work in progress)                                    |

NHANES is a complex multistage sample. Plain `pandas` means, counts, and OLS **ignore survey design** and give wrong
answers. The `Survey` class in `weighted_stats.py` applies the correct weights, strata (`SDMVSTRA`), and PSU clusters (
`SDMVPSU`) with Taylor-linearized standard errors.

## Project structure

```
stats_and_more/
├── Python/
│   ├── main.py            # Optional: convert .xpt → .csv in data/csv_data/
│   ├── stats_test.py      # Merge all NHANES components onto DEMO_J spine
│   ├── weighted_stats.py  # Design-based estimates (means, proportions, OLS)
│   ├── extra.py           # Interactive stats on data/data.csv
│   └── irrelevant.py      # Scratch / early experiments
├── data/
│   ├── data.csv           # Practice dataset (tracked in git)
│   ├── csv_data/          # NHANES component files (.csv or .xpt; not in git)
│   └── PDF_explanations/  # Variable documentation PDFs
├── Web/                   # Static HTML/CSS/TS preview
├── figures/               # Generated plots (gitignored)
├── pyproject.toml         # Dependencies (managed with uv)
└── requirements.txt       # Pip-compatible pin list
```

## Requirements

- **Python 3.14.5+** (see `.python-version`)
- [uv](https://docs.astral.sh/uv/) recommended, or pip

## Setup

```bash
git clone <repo-url>
cd stats_and_more

# With uv (recommended)
uv sync

# Or with pip
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## NHANES workflow

### 1. Download data

Download 2017–2018 cycle **XPT** files from
the [NHANES continuous survey page](https://wwwn.cdc.gov/nchs/nhanes/continuousnhanes/). Place them in `data/csv_data/`.

Included components in a typical setup: `DEMO_J`, `BMX_J`, `BIOPRO_J`, `GLU_J`, `HDL_J`, `TCHOL_J`, `TRIGLY_J`, `GHB_J`,
`HSCRP_J`, `BPX_J`, `DR1TOT_J`, `DR2TOT_J`, `PAQY_J`, `SLQ_J`, and related files. PDF variable guides live in
`data/PDF_explanations/`.

> **Note:** `*.csv` files under `data/csv_data/` are gitignored. You must download or generate them locally.

### 2. Convert XPT to CSV (optional)

`stats_test.py` reads `.csv` or `.xpt` directly. Running `main.py` converts any `.xpt` files in place and removes the
originals once CSVs exist.

```bash
cd Python
uv run python main.py
```

### 3. Build the analytic table

Merges every file in `data/csv_data/` onto `DEMO_J` (the spine) by participant ID (`SEQN`), carrying all design
variables (weights, strata, PSU).

```bash
cd Python
uv run python stats_test.py
```

Writes `data/csv_data/nhanes_analytic.csv` (and a copy may also appear at `data/nhanes_analytic.csv` depending on your
layout).

### 4. Run survey-weighted analysis

```bash
cd Python
uv run python weighted_stats.py
```

The demo prints weighted BMI means, subgroup estimates, obesity prevalence, and a design-based regression. Use the
`Survey` API in your own scripts:

```python
from weighted_stats import Survey, pick_weight
import numpy as np

svy = Survey()
adults = (svy.df["RIDAGEYR"] >= 20).to_numpy()

# Auto-selects WTMEC2YR for BMI
svy.mean("BMXBMI", subpop=adults)

# Auto-selects WTSAF2YR for fasting glucose
svy.mean("LBXGLU", subpop=adults)

# Design-based OLS (cluster-robust on PSU)
svy.ols("LBXGLU", ["BMXBMI"], subpop=adults)
```

**Important:** restrict analyses with the `subpop=` boolean mask over **all rows**. Do not pre-filter the DataFrame —
dropping rows removes PSUs and biases variance estimates.

### Survey weights quick reference

| Weight     | Use for                                                                                    |
|------------|--------------------------------------------------------------------------------------------|
| `WTINT2YR` | Interview-only variables (e.g. `PAQ*`, `SLQ*`, `SLD*`) when no MEC data is in the analysis |
| `WTMEC2YR` | MEC exam and standard labs (BMI, most BIOPRO labs, lipids, BP, etc.)                       |
| `WTSAF2YR` | Fasting subsample labs (`LBXGLU`, `LBXTR`, `LBDLDL`, …)                                    |
| `WTDRD1`   | Day-1 dietary recall (`DR1*`)                                                              |
| `WTDR2D`   | Two-day dietary average (`DR2*`)                                                           |

When mixing variables from different subsamples, use the weight of the **most restrictive** (smallest) subsample.
`pick_weight()` handles common cases; override with `weight=` when needed.

**Glucose note:** fasting plasma glucose is `LBXGLU` (file `GLU_J`, weight `WTSAF2YR`). `LBXSGL` in `BIOPRO_J` is
non-fasting serum glucose on the full MEC sample (`WTMEC2YR`).

## Practice dataset

`data/data.csv` is a smaller dataset for trying basic descriptive stats interactively:

```bash
cd Python
uv run python extra.py
```

Prompts for a column name and prints mean, median, mode, min, max, standard deviation, and variance.

## Web preview

I'm working on setting up a FastAPI backend to share the analysis outside a terminal.

## Development

Lint with Ruff (dev dependency):

```bash
uv run ruff check Python/
uv run ruff format Python/
```

## Key dependencies

- **pandas**, **numpy**, **scipy** — data handling and statistics
- **statsmodels** — weighted least squares with cluster-robust SE
- **scikit-learn**, **matplotlib**, **seaborn** — modeling and visualization
- **openpyxl** — Excel I/O
- **FastAPI**, **python-multipart** — reserved for future API work
- **ipykernel** — Jupyter notebook support

## Data sources

- [NHANES 2017–2018](https://wwwn.cdc.gov/nchs/nhanes/continuousnhanes/) — National Health and Nutrition Examination
  Survey (CDC/NCHS)
- `data/data.csv` — local practice dataset
