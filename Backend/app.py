"""
app.py -- the ASGI web service that Render runs.

WHY THIS EXISTS
    fastapi was already a declared dependency, but nothing actually defined an
    app or a server entry point, so there was nothing for Render to start. This
    is that entry point: a minimal FastAPI app that

      * exposes a health check (for Render's health probe),
      * serves the static preview (index.html at the repo root, assets under Web/), and
      * exposes a small JSON API (backed by engine.py) that the preview calls to
        compute descriptive stats on Data/data.csv.

RUNNING IT
    Locally:   uvicorn app:app --reload          (from this Backend/ directory)
    On Render:  see ../render.yaml (runs from the repo root: uvicorn main:app)
    Then open:  http://127.0.0.1:8000/

ROUTES
    GET /healthz             -> {"status": "ok"}     liveness probe for Render
    GET /                    -> the static preview (index.html), or info JSON if absent
    GET /api/columns         -> numeric/analyzable columns in Data/data.csv
    GET /api/stats/{column}  -> descriptive stats for one analyzable column
    /Web/*                   -> the Web/ directory (CSS/JS), served as static files
"""

from functools import lru_cache
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Import works whether launched from inside Backend/ (`uvicorn app:app`) or from
# the repo root (`uvicorn main:app`): try the bare module, then the package path.
try:
    from engine import DataAnalyzer, df_cleanup
except ModuleNotFoundError:
    from Backend.engine import DataAnalyzer, df_cleanup

# Resolve paths from __file__ so they're correct regardless of the working
# directory. index.html, Web/ and Data/ all live at the repo root, one level up.
ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "Web"
DATA_CSV = ROOT / "Data" / "data.csv"
INDEX_HTML = ROOT / "index.html"  # references Web/CSS and Web/JS (served at /Web)

app = FastAPI(title="Data Analysis")

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
        detail = f"Dataset not found: {DATA_CSV.name}"
        raise HTTPException(status_code=503, detail=detail) from None


@lru_cache(maxsize=1)
def analyzable_columns() -> frozenset[str]:
    """Columns with at least one numeric value after coercion (same rule as basic_analysis)."""
    df = load_data()
    return frozenset(
        col
        for col in df.columns
        if pd.to_numeric(df[col], errors="coerce").notna().any()
    )


@app.get("/healthz")
def healthz():
    """Liveness probe -- Render hits this to decide if the service is up."""
    return {"status": "ok"}


@app.get("/api/columns")
def list_columns():
    """List numeric/analyzable columns in Data/data.csv."""
    return {"dataset": DATA_CSV.name, "columns": sorted(analyzable_columns())}


@app.get("/api/stats/{column}")
def column_stats(column: str):
    """Return mean/median/mode/min/max/std/variance for one analyzable column."""
    if column not in analyzable_columns():
        raise HTTPException(status_code=404, detail=f"Unknown column: {column!r}")

    result = DataAnalyzer(load_data()).basic_analysis(column)
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@app.get("/")
def root():
    """Serve the static preview (index.html), falling back to info if it's gone."""
    if INDEX_HTML.is_file():
        return FileResponse(INDEX_HTML)
    return {"service": "Data Analysis", "status": "ok", "preview": None}


# Mount the static frontend last so it can't shadow the routes above. index.html
# lives at the repo root (served by "/") and pulls its CSS/JS from /Web, so we
# mount Web/ at /Web to match the page's Web/CSS and Web/JS links.
if WEB_DIR.is_dir():
    app.mount("/Web", StaticFiles(directory=WEB_DIR), name="web")
