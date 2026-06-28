# stats-and-more

A small Python project pairing **interactive descriptive statistics** with a minimal
**FastAPI web service** and a static web preview. It also retains data assets from an earlier
[NHANES 2017–2018](https://wwwn.cdc.gov/nchs/nhanes/continuousnhanes/) analysis effort.

## What this repo does

| Component         | Entry point             | What it does                                                            |
|-------------------|-------------------------|------------------------------------------------------------------------|
| **Web service**   | `Backend/app.py`        | FastAPI app: `/healthz` probe + serves the static `Web/` preview; deploys to Render |
| **Practice stats**| `Backend/extra.py`      | Interactive descriptive stats on `Data/data.csv`                       |
| **Web preview**   | `Web/HTML/index.html`   | Minimal static page (work in progress)                                 |

> **Note on history:** earlier versions of this repo included a survey-weighted NHANES
> pipeline (`stats_test.py`, `weighted_stats.py`) and an XPT→CSV converter (`main.py`). Those
> scripts have been removed (and `main.py` emptied to a placeholder). The NHANES data files
> they produced still live under `Data/` and `extra_data/`; recover the scripts from git
> history if you need them.

## Project structure

```
stats_and_more/
├── Backend/
│   ├── app.py             # FastAPI service: /healthz + serves Web/ (Render entry point)
│   ├── extra.py           # Interactive descriptive stats on Data/data.csv
│   └── main.py            # Empty placeholder (was the XPT→CSV converter)
├── Data/
│   ├── data.csv           # Practice dataset (tracked in git)
│   ├── laptopData.csv     # Secondary practice dataset (tracked in git)
│   └── nhanes_analytic.csv  # Prebuilt NHANES analytic table (gitignored)
├── extra_data/            # Retained NHANES source files (analysis scripts removed)
│   ├── csv_data/          # NHANES component CSV files (gitignored)
│   └── PDF_explanations/  # Variable documentation PDFs
├── Web/                   # Static preview
│   ├── HTML/index.html
│   ├── CSS/styles.css
│   └── TS/{main.ts,script.js}
├── figures/               # Generated plots (gitignored)
├── render.yaml            # Render Blueprint (deploys Backend/app.py)
├── pyproject.toml         # Dependencies (managed with uv)
├── requirements.txt       # Pip-compatible pin list
└── uv.lock
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

## Web service

`Backend/app.py` is a minimal FastAPI app and the entry point Render runs.

```bash
cd Backend
uv run uvicorn app:app --reload
```

Then:

- `GET /` — redirects to the static preview under `Web/`
- `GET /healthz` — liveness probe, returns `{"status": "ok"}`
- `/web/*` — the `Web/` directory, served as static files

### Deploying to Render

`render.yaml` is a [Render Blueprint](https://render.com/docs/blueprint-spec). Push the repo,
then in the Render dashboard choose **New + → Blueprint** and point it at this repo. The
blueprint builds from `Backend/` (`rootDir: Backend`), starts with
`uvicorn app:app --host 0.0.0.0 --port $PORT`, and uses `/healthz` for zero-downtime health
checks.

## Practice dataset

`Data/data.csv` is a small dataset for trying basic descriptive stats interactively:

```bash
cd Backend
uv run python extra.py
```

It loads the CSV, coerces mostly-numeric columns (stripping `$` and `,`), prints a preview,
then prompts for a column name and reports mean, median, mode, min, max, standard deviation,
and variance.

The `DataAnalyzer.basic_analysis(column)` method returns those same stats as a dict, which is
handy for reuse or for serving over the API:

```python
import pandas as pd
from extra import DataAnalyzer, df_cleanup

df = df_cleanup(pd.read_csv("../Data/data.csv"))
DataAnalyzer(df).basic_analysis("price")
# -> {"column": "price", "mean": ..., "median": ..., "mode": ..., ...}
```

## Web preview

`Web/` holds a minimal static page (HTML/CSS/TS) served by the FastAPI app — currently a
"Hello World" placeholder with a button, while the frontend for sharing analysis outside a
terminal is built out.

## Development

Lint and format with Ruff (dev dependency):

```bash
uv run ruff check Backend/
uv run ruff format Backend/
```

## Key dependencies

- **FastAPI**, **uvicorn**, **python-multipart** — the web service
- **pandas**, **numpy**, **scipy** — data handling and statistics
- **statsmodels**, **scikit-learn** — modeling
- **matplotlib**, **seaborn** — visualization
- **openpyxl** — Excel I/O
- **ipykernel** — Jupyter notebook support

(Dependencies are declared in `pyproject.toml` and pinned in `requirements.txt`.)

## Data sources

- [NHANES 2017–2018](https://wwwn.cdc.gov/nchs/nhanes/continuousnhanes/) — National Health and
  Nutrition Examination Survey (CDC/NCHS)
- `Data/data.csv`, `Data/laptopData.csv` — local practice datasets
