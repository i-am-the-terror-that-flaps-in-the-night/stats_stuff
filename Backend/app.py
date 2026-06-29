"""
app.py -- the ASGI web service that Render runs.

WHY THIS EXISTS
    fastapi was already a declared dependency, but nothing actually defined an
    app or a server entry point, so there was nothing for Render to start. This
    is that entry point: a minimal FastAPI app that

      * exposes a health check (for Render's health probe),
      * serves the static preview (index.html at the repo root, assets under Web/), and
      * exposes a small JSON API (backed by extra.py) that the preview calls to
        compute descriptive stats on Data/data.csv.

RUNNING IT
    Locally:   uvicorn app:app --reload          (from this Backend/ directory)
    On Render:  see ../render.yaml (rootDir: Backend, uvicorn app:app)
    Then open:  http://127.0.0.1:8000/

ROUTES
    GET /healthz             -> {"status": "ok"}     liveness probe for Render
    GET /                    -> the static preview (index.html), or info JSON if absent
    GET /api/columns         -> available columns in Data/data.csv
    GET /api/stats/{column}  -> descriptive stats for one column
    /Web/*                   -> the Web/ directory (CSS/JS), served as static files
"""

from functools import lru_cache
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

try:  # launched from inside Backend/ (e.g. `uvicorn app:app`)
    from extra import DataAnalyzer, df_cleanup
except ModuleNotFoundError:  # launched from the repo root (e.g. `uvicorn Backend.app:app`)
    from Backend.extra import DataAnalyzer, df_cleanup

# Resolve paths from __file__ so they're correct regardless of the working
# directory. index.html, Web/ and Data/ all live at the repo root, one level up.
ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "Web"
DATA_CSV = ROOT / "Data" / "data.csv"
INDEX_HTML = ROOT / "index.html"  # references Web/CSS and Web/JS (served at /Web)

app = FastAPI(title="stats-and-more")

# Allow the static page to call the API even when it's opened from a different
# origin (e.g. a separate dev server or file://). Permissive is fine for a demo.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@lru_cache(maxsize=1)
def get_dataframe() -> pd.DataFrame:
    """Load and clean Data/data.csv once, then reuse it across requests."""
    return df_cleanup(pd.read_csv(DATA_CSV))


def load_data() -> pd.DataFrame:
    """get_dataframe(), but turn a missing file into a clean 503 for the client."""
    try:
        return get_dataframe()
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail=f"Dataset not found: {DATA_CSV.name}")


@app.get("/healthz")
def healthz():
    """Liveness probe -- Render hits this to decide if the service is up."""
    return {"status": "ok"}


@app.get("/api/columns")
def list_columns():
    """List the columns available for analysis in Data/data.csv."""
    df = load_data()
    return {"dataset": DATA_CSV.name, "columns": list(df.columns)}


@app.get("/api/stats/{column}")
def column_stats(column: str):
    """Return mean/median/mode/min/max/std/variance for one column."""
    df = load_data()
    if column not in df.columns:
        raise HTTPException(status_code=404, detail=f"Unknown column: {column!r}")

    result = DataAnalyzer(df).basic_analysis(column)
    if "error" in result:
        # Column exists but has no numeric values to summarize.
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@app.get("/")
def root():
    """Serve the static preview (index.html), falling back to info if it's gone."""
    if INDEX_HTML.is_file():
        return FileResponse(INDEX_HTML)
    return {"service": "stats-and-more", "status": "ok", "preview": None}


# Mount the static frontend last so it can't shadow the routes above. index.html
# lives at the repo root (served by "/") and pulls its CSS/JS from /Web, so we
# mount Web/ at /Web to match the page's Web/CSS and Web/JS links.
if WEB_DIR.is_dir():
    app.mount("/Web", StaticFiles(directory=WEB_DIR), name="web")
