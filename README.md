# stats-and-more

A small Python project pairing a **descriptive-statistics engine** with a minimal
**FastAPI web service** and a static web preview. The live demo runs on a curated slice of
[NHANES 2017–2018](https://wwwn.cdc.gov/nchs/nhanes/continuousnhanes/) data — the same dataset
this project's underlying research analyzes.

## What this repo does

| Component         | Entry point             | What it does                                                            |
|-------------------|-------------------------|------------------------------------------------------------------------|
| **Web service**   | `Backend/app.py`        | FastAPI app: `/healthz` probe, a JSON analysis API, and serves the `Web/` preview + a styled 404; deploys to Render |
| **Stats engine**  | `Backend/engine.py`     | Basic/medium/advanced/expert/categorical analysis tiers on `Data/nhanes.csv`; the engine behind the API |
| **Studio**        | `Backend/studio.py`     | Server-rendered `/studio/` and `/guide/` pages (Jinja templates) — a browsable, no-JS view of the same engine, with a local run log |
| **Web preview**   | `index.html`            | Static page that calls the API to show column stats                    |

> **Note on history:** earlier versions of this repo included a survey-weighted NHANES
> pipeline (`stats_test.py`, `weighted_stats.py`) and an XPT→CSV converter (`main.py`). Those
> scripts have been removed; `main.py` was repurposed into a thin deployment entry point that
> re-exports the FastAPI app (so Render's default `uvicorn main:app` resolves). The NHANES data
> files they produced still live under `Data/` and `extra_data/`; recover the scripts from git
> history if you need them.

## Project structure

```
stats_and_more/
├── index.html             # Static preview, served at / by the FastAPI app
├── 404.html               # Styled 404 page, served for unmatched HTML routes
├── main.py                # Root deploy entry point: re-exports Backend/app.py (Render's `uvicorn main:app`)
├── Backend/
│   ├── app.py             # FastAPI service: /healthz, /favicon.ico, the JSON analysis API, 404 handler, serves index.html
│   ├── engine.py          # Stats engine: basic/medium/advanced/expert/categorical analysis tiers on Data/nhanes.csv
│   ├── studio.py          # /studio/ and /guide/ routes: server-rendered Jinja pages + local SQLite run log
│   └── templates/studio/  # Jinja templates for Studio (index, analyze, runs, guide) + shared base.html
├── Data/
│   ├── nhanes.csv         # Live dataset: 18 curated, human-readable NHANES columns (tracked in git)
│   ├── data.csv           # Small synthetic practice dataset, kept for quick local testing (tracked in git)
│   ├── laptopData.csv     # Secondary practice dataset (gitignored)
│   └── nhanes_analytic.csv  # Full raw NHANES merge, 412 columns -- nhanes.csv was curated from this (gitignored)
├── extra_data/            # Retained NHANES source files (analysis scripts removed)
│   ├── csv_data/          # NHANES component CSV files (gitignored)
│   └── PDF_explanations/  # Variable documentation PDFs
├── Web/                   # Static preview assets (served at /Web)
│   ├── CSS/styles.css     # Main site styles
│   ├── CSS/studio.css     # Studio-specific styles
│   ├── HTML/              # Methodology/Benchmarks/Changelog pages
│   ├── JS/script.js       # Dashboard logic (calls the API, renders results/charts)
│   ├── JS/nav.js          # Client-side SPA navigation between the static pages
│   ├── JS/transition.js   # Boot-splash-to-page transition
│   └── favicon.ico
├── figures/               # Generated plots (gitignored)
├── render.yaml            # Render Blueprint (deploys Backend/app.py)
├── pyproject.toml         # Dependencies (managed with uv)
├── requirements.txt       # Pip-compatible pin list
└── uv.lock
```

## Requirements

- **Python 3.14.6+** (see `.python-version`)
- [uv](https://docs.astral.sh/uv/) recommended, or pip

## Setup

```bash
git clone <repo-url>
cd stats_and_more

# With uv (recommended)
uv sync

# Or with pip (installs just the minimal runtime set — see Key dependencies)
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Web service

`Backend/app.py` is a minimal FastAPI app and the entry point Render runs.

```bash
cd Backend
uv run uvicorn app:app --reload

# ...or from the repo root (main.py re-exports the same app):
uv run uvicorn main:app --reload
```

Then open <http://127.0.0.1:8000/> and pick a column to analyze. Routes:

- `GET /` — serves the static preview (`index.html`)
- `GET /healthz` — liveness probe, returns `{"status": "ok"}`
- `GET /favicon.ico` — the site favicon (avoids a stray 404 on every page load)
- `GET /api/overview` — dataset telemetry: shape, analyzable/categorical split, complete vs reduced columns
- `GET /api/columns` — numeric and categorical columns available in `Data/nhanes.csv`
- `GET /api/stats/{column}` — mean/median/mode/min/max/std/variance for one column (the basic tier; kept for backward compatibility)
- `GET /api/analyze/{tier}/{column}` — run any analysis tier (`basic`/`medium`/`advanced`/`expert`/`categorical`) for a column, optionally with `?group=` for the tiers that support group comparisons
- `GET /studio/`, `GET /studio/analyze/{tier}/{column}/`, `POST /studio/analyze/{tier}/{column}/save/`, `GET /studio/runs/`, `GET /guide/` — the server-rendered Studio pages (see `Backend/studio.py`)
- `/Web/*` — the `Web/` directory (CSS/JS/favicon), served as static files
- Any other unmatched path — a styled `404.html` for browser navigations, or the default JSON error for API/Studio paths

The API is backed by `engine.py`: `df_cleanup()` coerces mostly-numeric columns
(stripping `$`/`,`), and `DataAnalyzer` computes each tier's stats — from
`basic_analysis()` up to `expert_analysis()` (collinearity/VIF, regression
diagnostics, clinical cutoffs, trend tests).

### Studio (`/studio/`, `/guide/`)

`Backend/studio.py` adds a second, server-rendered front end alongside the JSON
API and the JS-driven dashboard: plain HTML pages (Jinja templates in
`Backend/templates/studio/`) that call the same cached `app.py` functions
directly, no HTTP round-trip. `/studio/` lists datasets and tiers, `/studio/analyze/{tier}/{column}/`
renders one analysis as a ledger table (with an inline chart) and a "Save to
run log" button, and `/studio/runs/` shows that log. The log is a local SQLite
file (`Backend/studio_runs.db`, gitignored) — Render's free tier has no
persistent disk, so it's a personal lab notebook, not shared state the site
depends on. `/guide/` is a "how it's built" write-up.

### Deploying to Render

`render.yaml` is a [Render Blueprint](https://render.com/docs/blueprint-spec). Push the repo,
then in the Render dashboard choose **New + → Blueprint** and point it at this repo. It builds
and runs from the repo root, with:

- **Build command:** `pip install -r requirements.txt`
- **Start command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
- **Health check path:** `/healthz`

The root `main.py` re-exports the app from `Backend/app.py`, so Render's default
`uvicorn main:app` start command works without any extra configuration.

> **If you created the service manually** (not via Blueprint), Render ignores `render.yaml` —
> set those same values in the dashboard under **Settings → Build & Deploy**. The
> `Could not import module "main"` error means the start command can't find an app; with the
> root `main.py` in place and the start command above, it resolves.

## Live dataset

`Data/nhanes.csv` is what the web service, the dashboard, and Studio actually run on: 9,254
NHANES 2017–2018 participants, 18 columns curated from the 412-column raw merge in
`Data/nhanes_analytic.csv` (itself joined from the component files under `extra_data/csv_data/`
on `SEQN`). Curation renamed cryptic NHANES variable codes to readable names and mapped
coded categoricals to their text labels (both checked against the codebooks in
`extra_data/PDF_explanations/`):

| Curated column | NHANES variable | Codebook file |
|---|---|---|
| Age, BMI, Weight, Height, Waist | `RIDAGEYR`, `BMXBMI`, `BMXWT`, `BMXHT`, `BMXWAIST` | `DEMO_J`, `BMX_J` |
| SystolicBP, DiastolicBP, Pulse | `BPXSY1`, `BPXDI1`, `BPXPLS` | `BPX_J` |
| TotalCholesterol, HDLCholesterol, Triglycerides | `LBXTC`, `LBDHDD`, `LBXTR` | `TCHOL_J`, `HDL_J`, `TRIGLY_J` |
| HbA1c, HsCRP, SleepHours | `LBXGH`, `LBXHSCRP`, `SLD012` | `GHB_J`, `HSCRP_J`, `SLQ_J` |
| IncomeRatio, Gender, RaceEthnicity, Education | `INDFMPIR`, `RIAGENDR`, `RIDRETH1`, `DMDEDUC2` | `DEMO_J` |

`engine.py`'s `NHANES_MISSING_FILL` handles a sentinel value the raw export uses in place of a
blank; every other column is honest NaN. Real NHANES data is genuinely gap-heavy in a way that
matters for this project's whole "never impute, always report `count`" design: `Age` is present
for 8,897 of 9,254 participants, but `Triglycerides` — a fasting-subsample-only test — only for
2,834. `df_cleanup()` and `DataAnalyzer` don't special-case this: the same descriptive-stats
pipeline that runs on the tiny practice file runs on it unchanged.

`Data/data.csv` is a small synthetic dataset kept for quick local testing (e.g. the CLI example
below), and isn't wired into the running app.

```python
import pandas as pd
from engine import DataAnalyzer, df_cleanup

df = df_cleanup(pd.read_csv("../Data/data.csv"))
DataAnalyzer(df).basic_analysis("price")
# -> {"column": "price", "mean": ..., "median": ..., "mode": ..., ...}
```

## Web preview

A small static page — `index.html` at the repo root, with CSS/JS under `Web/` — served by the
FastAPI app. It loads the column list from `/api/columns`, then fetches `/api/stats/{column}`
and renders the result as a table — a browser front end for the same stats `engine.py`
computes.

```
index.html            # markup, served at / (loaded by the FastAPI "/" route)
Web/
├── CSS/styles.css    # styling
├── JS/script.js      # all the front-end logic (loaded by index.html)
└── favicon.ico
```

The page tries the API on the same origin first (the case when uvicorn serves it), then
falls back to `http://127.0.0.1:8000` — so it also works behind a separate static server or
opened directly as a file, **as long as the backend is running**. Serving it through uvicorn
(open <http://127.0.0.1:8000/>) is the simplest setup and avoids cross-origin entirely.

## Development

Lint and format with Ruff (dev dependency):

```bash
uv run ruff check Backend/
uv run ruff format Backend/
```

Run the tests (pytest, dev dependency) from the repo root:

```bash
uv run pytest
```

`tests/test_engine.py` covers `basic_analysis()` (numeric column, no-numeric-values,
mode ties) and confirms `df_cleanup()` drops missing values rather than imputing them.

## Key dependencies

**Runtime** — what the deployed app actually imports, pinned in `requirements.txt` and kept
minimal so Render builds stay fast:

- **FastAPI** + **uvicorn** — the web service
- **pandas** (with **numpy**) — data handling and statistics
- **jinja2** — templating for the Studio pages (`Backend/studio.py`)

`pyproject.toml` declares the same runtime set plus a little extra for local work —
**matplotlib** and **pandas-stubs** (type stubs), with **ruff** as a dev dependency. `uv sync`
installs that full set (resolved against `uv.lock`); `pip install -r requirements.txt` installs
just the runtime set above.

### Two dependency lists, kept in sync by hand

There are two manifests, and they can drift — so it's worth knowing which one does what:

- **`requirements.txt`** hard-pins exact versions (e.g. `pandas==3.0.3`). **This is what Render
  builds from:** `render.yaml`'s build command is `pip install -r requirements.txt`.
- **`pyproject.toml` + `uv.lock`** drive local `uv sync`. `pyproject.toml` uses floors (e.g.
  `pandas>=3.0.3`); **`uv.lock` is the source of truth** for the exact versions `uv` resolves.

Nothing regenerates `requirements.txt` from the lock file, so when you bump a dependency, update
both — otherwise the version Render ships can quietly diverge from the one you develop against.

## Data sources

- [NHANES 2017–2018](https://wwwn.cdc.gov/nchs/nhanes/continuousnhanes/) — National Health and
  Nutrition Examination Survey (CDC/NCHS); `Data/nhanes.csv` is the curated 18-column subset the
  app runs on, `Data/nhanes_analytic.csv` the full 412-column raw merge it was curated from
- `Data/data.csv` — small synthetic practice dataset, not wired into the running app
- [laptopData.csv](https://www.kaggle.com/code/elhadjimouhamadou/laptop-prices-data-cleaning/input) — Kaggle data cleaning dataset
