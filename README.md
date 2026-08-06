# stats-and-more

A small project pairing a **descriptive-statistics engine** with a minimal
**FastAPI web service** and a React + TypeScript frontend. The live demo runs on a curated slice of
[NHANES 2017–2018](https://wwwn.cdc.gov/nchs/nhanes/continuousnhanes/) data — the same dataset
this project's underlying research analyzes.

## What this repo does

| Component         | Entry point             | What it does                                                            |
|-------------------|-------------------------|------------------------------------------------------------------------|
| **Web service**   | `Backend/app.py`        | FastAPI app: `/healthz` probe, the JSON analysis API, and serves the built frontend; deploys to Render |
| **Stats engine**  | `Backend/engine.py`     | Basic/medium/advanced/expert/categorical analysis tiers on `Data/nhanes.csv`; the engine behind the API |
| **Studio API**    | `Backend/studio.py`     | `/api/datasets` and `/api/runs` — the dataset inventory and the local SQLite run log |
| **Frontend**      | `frontend/`             | React 19 + Vite 8 + TypeScript 7 single-page app: the dashboard, the static pages and the Studio |

> **Note on history:** earlier versions of this repo included a survey-weighted NHANES
> pipeline (`stats_test.py`, `weighted_stats.py`) and an XPT→CSV converter (`main.py`). Those
> scripts have been removed; `main.py` was repurposed into a thin deployment entry point that
> re-exports the FastAPI app (so Render's default `uvicorn main:app` resolves). The NHANES data
> files they produced still live under `Data/` and `extra_data/`; recover the scripts from git
> history if you need them.

## Project structure

```
stats_and_more/
├── main.py                # Root deploy entry point: re-exports Backend/app.py (Render's `uvicorn main:app`)
├── Backend/
│   ├── app.py             # FastAPI service: /healthz, the JSON analysis API, serves frontend/dist + SPA fallback
│   ├── engine.py          # Stats engine: basic/medium/advanced/expert/categorical analysis tiers on Data/nhanes.csv
│   └── studio.py          # /api/datasets and /api/runs: dataset inventory + local SQLite run log
├── Data/
│   ├── nhanes.csv         # Live dataset: 18 curated, human-readable NHANES columns (tracked in git)
│   ├── data.csv           # Small synthetic practice dataset, kept for quick local testing (tracked in git)
│   ├── laptopData.csv     # Secondary practice dataset (gitignored)
│   └── nhanes_analytic.csv  # Full raw NHANES merge, 412 columns -- nhanes.csv was curated from this (gitignored)
├── extra_data/            # Retained NHANES source files (analysis scripts removed)
│   ├── csv_data/          # NHANES component CSV files (gitignored)
│   └── PDF_explanations/  # Variable documentation PDFs
├── frontend/              # React + Vite + TypeScript SPA (built to frontend/dist, gitignored)
│   ├── index.html         # Vite entry document
│   ├── vite.config.ts     # base "/" (required for nested routes) + /api dev proxy
│   ├── tsconfig*.json     # TypeScript 7, strict
│   └── src/
│       ├── main.tsx       # Mounts <BootLoader><App/></BootLoader>
│       ├── App.tsx        # Routes
│       ├── lib/api.ts     # Typed API client + backend-origin discovery
│       ├── lib/format.ts  # Shape guards driving the generic result renderer
│       ├── types/         # API payload types
│       ├── components/    # Shell, BootLoader, ResultView
│       ├── routes/        # Overview, Methodology, Benchmarks, Changelog, Studio, Guide
│       └── styles/        # styles.css, studio.css
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

- `GET /` — serves the built frontend (`frontend/dist/index.html`)
- `GET /healthz` — liveness probe, returns `{"status": "ok"}`
- `GET /favicon.ico` — the site favicon (avoids a stray 404 on every page load)
- `GET /api/overview` — dataset telemetry: shape, analyzable/categorical split, complete vs reduced columns
- `GET /api/columns` — numeric and categorical columns available in `Data/nhanes.csv`
- `GET /api/stats/{column}` — mean/median/mode/min/max/std/variance for one column (the basic tier; kept for backward compatibility)
- `GET /api/analyze/{tier}/{column}` — run any analysis tier (`basic`/`medium`/`advanced`/`expert`/`categorical`) for a column, optionally with `?group=` for the tiers that support group comparisons
- `GET /api/datasets` — the dataset inventory, each with a live `available` flag
- `GET /api/runs`, `POST /api/runs` — the Studio run log (see `Backend/studio.py`)
- `/assets/*` — the fingerprinted Vite bundle, cached immutably
- Any other unmatched path that accepts HTML — the SPA shell, so client-side routes deep-link correctly; `/api/*` keeps its JSON error body

The API is backed by `engine.py`: `df_cleanup()` coerces mostly-numeric columns
(stripping `$`/`,`), and `DataAnalyzer` computes each tier's stats — from
`basic_analysis()` up to `expert_analysis()` (collinearity/VIF, regression
diagnostics, published clinical thresholds, trend tests).

Every block of output carries a `layer` key — `descriptive`, `inferential` or
`predictive` — naming how strong a claim it supports. Nothing is ever labelled
causal: the engine reports adjusted *associations*, and only when the caller
names the exposure and confounders itself (`advanced_analysis(..., exposure=...,
confounders=[...])`). Every p-value ships with an effect size, because
statistical significance and practical importance are different questions.

Clinical thresholds come from `CLINICAL_THRESHOLDS` (published adult guideline
values, each with its source), never from the dataset's own median. Because a
cutoff is a number *plus a unit*, each entry stores its cutoff per unit and the
band a population median plausibly falls in for that unit. Before applying
anything, the engine checks the column's median against that band: if the data
looks like mmol/L when the cutoff is mg/dL, it refuses and names the unit it
suspects rather than reporting a precise, confident, wrong prevalence. Declare
units explicitly with `expert_analysis(column, units="mmol/L")`.

### Studio (`/studio`, `/guide`)

The Studio is a route in the SPA, not a server-rendered page. `/studio` lists the
columns, datasets and recent runs; `/studio/analyze/:tier/:column` renders one
analysis as a ledger table with an inline chart and a "Save this run" button; and
`/studio/runs` shows the log.

`Backend/studio.py` keeps only what the browser genuinely cannot work out for
itself: the dataset inventory (a filesystem question) and the run log (a SQLite
question). It still calls `app.py`'s cached functions in-process, with no HTTP
round-trip. The log is a local SQLite file (`Backend/studio_runs.db`, gitignored)
— Render's free tier has no persistent disk, so it's a personal lab notebook, not
shared state the site depends on. An empty log is the normal online state.

## Frontend

```bash
./run.sh           # both servers: API on :8000, app on :5173  <- open :5173
./run.sh build     # build the frontend, then serve it from FastAPI at :8000
```

`./run.sh` is the everyday command. It runs uvicorn and the Vite dev server
together, installs `frontend/node_modules` on first use, and shuts both down as
one — Ctrl-C, or either server crashing, stops the other. Open **:5173**, not
:8000: Vite serves the app with hot reload and proxies `/api` through to uvicorn,
so there is no CORS in the loop. Port 8000 serves whatever was last built into
`frontend/dist`, which in development is usually stale.

Use `./run.sh build` before deploying — it produces the real bundle and serves it
exactly the way Render will.

To run either side alone:

```bash
cd frontend && npm run dev   # frontend only (no API)
uv run uvicorn main:app --reload   # backend only
```

```bash
npm run build      # tsc -b (typecheck) then vite build -> frontend/dist
npm run typecheck  # types only
```

`frontend/dist` is gitignored and built on deploy (see `render.yaml`), so there
is no committed bundle that can drift from the source it came from.

Two things worth knowing before changing the build:

- **`base` must stay `"/"`.** `index.html` is served for every deep link, so a
  relative base makes `/studio/runs` resolve `./assets/index.js` against
  `/studio/` and 404 — the HTML still returns 200, so the page just goes blank
  with no build or type error to warn you.
- **Import from `react-router`, not `react-router-dom`.** v7 merged everything
  into the one package; `react-router-dom` is a legacy re-export whose 7.12–8.2
  range carries a CSRF advisory.

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
