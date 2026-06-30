# stats-and-more

A small Python project pairing a **descriptive-statistics engine** with a minimal
**FastAPI web service** and a static web preview. It also retains data assets from an earlier
[NHANES 2017–2018](https://wwwn.cdc.gov/nchs/nhanes/continuousnhanes/) analysis effort.

## What this repo does

| Component         | Entry point             | What it does                                                            |
|-------------------|-------------------------|------------------------------------------------------------------------|
| **Web service**   | `Backend/app.py`        | FastAPI app: `/healthz` probe, a JSON stats API, and serves the `Web/` preview; deploys to Render |
| **Stats engine**  | `Backend/engine.py`     | Descriptive stats on `Data/data.csv`; the engine behind the API            |
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
├── main.py                # Root deploy entry point: re-exports Backend/app.py (Render's `uvicorn main:app`)
├── Backend/
│   ├── app.py             # FastAPI service: /healthz + serves index.html (the real app)
│   └── engine.py          # Stats engine: descriptive stats on Data/data.csv (backs the API)
├── Data/
│   ├── data.csv           # Practice dataset (tracked in git)
│   ├── laptopData.csv     # Secondary practice dataset (gitignored)
│   └── nhanes_analytic.csv  # Prebuilt NHANES analytic table (gitignored)
├── extra_data/            # Retained NHANES source files (analysis scripts removed)
│   ├── csv_data/          # NHANES component CSV files (gitignored)
│   └── PDF_explanations/  # Variable documentation PDFs
├── Web/                   # Static preview assets (served at /Web)
│   ├── CSS/styles.css
│   ├── JS/script.js
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
- `GET /api/columns` — columns available in `Data/data.csv`
- `GET /api/stats/{column}` — mean/median/mode/min/max/std/variance for one column
- `/Web/*` — the `Web/` directory (CSS/JS/favicon), served as static files

The API is backed by `engine.py`: `df_cleanup()` coerces mostly-numeric columns
(stripping `$`/`,`) and `DataAnalyzer.basic_analysis()` computes the stats.

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

## Practice dataset

`Data/data.csv` is a small dataset for trying basic descriptive stats. `engine.py` is a
library (no CLI) — `df_cleanup()` loads and coerces mostly-numeric columns (stripping `$`
and `,`), and `DataAnalyzer.basic_analysis(column)` reports mean, median, mode, min, max,
standard deviation, and variance.

Exercise it through the web service above, or import it directly. `basic_analysis(column)`
returns the stats as a dict, handy for reuse or for serving over the API:

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
  Nutrition Examination Survey (CDC/NCHS)
- `Data/data.csv` — local practice dataset
- [laptopData.csv](https://www.kaggle.com/code/elhadjimouhamadou/laptop-prices-data-cleaning/input) — Kaggle data cleaning dataset
