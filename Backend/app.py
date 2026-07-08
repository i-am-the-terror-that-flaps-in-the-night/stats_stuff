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

SPEED ON RENDER
    Render's free plan spins the service down when idle and cold-starts it on the
    next request, so boot time is paid over and over. Two things keep that fast:

      * pandas/engine.py are imported *lazily* (inside the functions that use
        them), not at module load. Importing pandas+numpy is by far the biggest
        chunk of boot time -- on a shared free-tier CPU it's seconds. Keeping it
        off the import path means uvicorn binds the port, the health probe
        answers, and index.html + the static assets serve immediately; only the
        first /api call pays the import (and it's cached after that).
      * a background warm-up on startup (see `lifespan`) pre-imports pandas and
        pre-loads/cleans the CSV off the request path, so even the first /api
        call usually finds the caches already warm -- without delaying readiness.

    Responses are gzip-compressed and static assets carry Cache-Control headers,
    so less goes over the wire and repeat visits skip re-fetching unchanged CSS/JS.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# NOTE: pandas and engine.py are imported lazily inside get_dataframe(),
# analyzable_columns() and compute_stats() -- deliberately NOT at module top --
# to keep the heavy pandas/numpy import off Render's cold-start path. See the
# "SPEED ON RENDER" note in the module docstring.

# Resolve paths from __file__ so they're correct regardless of the working
# directory. index.html, Web/ and Data/ all live at the repo root, one level up.
ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "Web"
DATA_CSV = ROOT / "Data" / "data.csv"
INDEX_HTML = ROOT / "index.html"  # references Web/CSS and Web/JS (served at /Web)

# Cache-Control for the static frontend. The assets aren't content-hashed, so we
# use a moderate max-age: long enough that repeat visits skip the network, short
# enough that a redeploy propagates within the hour. StaticFiles still sends
# ETag/Last-Modified, so even after it expires the browser revalidates with a
# cheap 304 rather than re-downloading.
STATIC_CACHE_CONTROL = "public, max-age=3600"
# index.html changes more often than its assets and is the entry point, so give
# it a shorter TTL (it's tiny, and 304s keep re-fetches cheap anyway).
INDEX_CACHE_CONTROL = "public, max-age=300"


def _load_engine():
    """Import the stats engine lazily. Works whether launched from inside
    Backend/ (`uvicorn app:app`) or the repo root (`uvicorn main:app`): try the
    bare module first, then the package path. Kept out of module scope so the
    pandas import it triggers stays off the cold-start path."""
    try:
        from engine import DataAnalyzer, df_cleanup
    except ModuleNotFoundError:
        from Backend.engine import DataAnalyzer, df_cleanup
    return DataAnalyzer, df_cleanup


@lru_cache(maxsize=1)
def get_dataframe():
    """Load and clean Data/data.csv once, then reuse it across requests."""
    import pandas as pd

    _, df_cleanup = _load_engine()
    return df_cleanup(pd.read_csv(DATA_CSV))


def load_data():
    """get_dataframe(), but turn a missing file into a clean 503 for the client."""
    try:
        return get_dataframe()
    except FileNotFoundError:
        detail = f"Dataset not found: {DATA_CSV.name}"
        raise HTTPException(status_code=503, detail=detail) from None


@lru_cache(maxsize=1)
def analyzable_columns() -> frozenset[str]:
    """Columns with at least one numeric value after coercion (same rule as basic_analysis)."""
    import pandas as pd

    df = load_data()
    return frozenset(
        col
        for col in df.columns
        if pd.to_numeric(df[col], errors="coerce").notna().any()
    )


@lru_cache(maxsize=1)
def categorical_columns() -> frozenset[str]:
    """Label columns -- those with no numeric values at all (the complement of
    analyzable_columns). These feed the categorical tier and the group-by picker."""
    df = load_data()
    numeric = analyzable_columns()
    return frozenset(col for col in df.columns if col not in numeric)


@lru_cache(maxsize=1)
def dataset_overview() -> dict[str, str | int]:
    """Real, derivable telemetry about the loaded dataset -- shape, how many
    columns are analyzable vs categorical, and how many numeric columns are
    complete (n == row count) vs reduced by a dropped un-parseable cell. Every
    value comes from the dataframe; nothing is hard-coded."""
    import pandas as pd

    df = load_data()
    numeric = analyzable_columns()
    total = len(df)
    complete = sum(
        1
        for col in numeric
        if int(pd.to_numeric(df[col], errors="coerce").notna().sum()) == total
    )
    return {
        "dataset": DATA_CSV.name,
        "rows": total,
        "columns": len(df.columns),
        "numeric": len(numeric),
        "categorical": len(df.columns) - len(numeric),
        "complete": complete,
        "reduced": len(numeric) - complete,
    }


@lru_cache(maxsize=128)
def compute_stats(column: str):
    """Descriptive stats for one column, memoized.

    The dataframe is loaded once (get_dataframe is itself cached) and never
    changes over the process lifetime, so a given column's stats are stable --
    caching them makes repeat requests for the same column O(1) instead of
    re-running the pandas reductions each time.
    """
    DataAnalyzer, _ = _load_engine()
    return DataAnalyzer(load_data()).basic_analysis(column)


# The analysis tiers that operate on a numeric column. The categorical branch is
# handled separately (it works on label columns), so it's kept out of this set.
# The engine also has an "expert" tier, but the website deliberately doesn't
# expose it -- see engine.py's expert_analysis().
NUMERIC_TIERS = ("basic", "medium", "advanced")


@lru_cache(maxsize=256)
def compute_tier(tier: str, column: str, group: str | None):
    """Run one analysis tier for a column, memoized on (tier, column, group).

    Same rationale as compute_stats: the dataframe is immutable over the process
    lifetime, so each (tier, column, group) answer is stable and worth caching --
    it also means the one-time statsmodels import the advanced tier pays is
    only paid once per distinct request.
    """
    DataAnalyzer, _ = _load_engine()
    analyzer = DataAnalyzer(load_data())
    if tier == "basic":
        return analyzer.basic_analysis(column)
    if tier == "medium":
        return analyzer.medium_analysis(column, group)
    if tier == "advanced":
        return analyzer.advanced_analysis(column, group)
    if tier == "categorical":
        return analyzer.categorical_analysis(column)
    return {"error": f"Unknown tier: {tier}"}


def _warm_caches() -> None:
    """Pre-import pandas and pre-load/clean the CSV so the first real /api call
    finds the caches warm. Runs in a background thread on startup; any failure
    (e.g. a missing CSV) is swallowed so the request path can retry it lazily and
    startup is never blocked on it."""
    try:
        analyzable_columns()  # -> load_data() -> get_dataframe(): imports pandas, reads+cleans the CSV
        dataset_overview()  # derives the telemetry the landing page reads on load
    except Exception:
        pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    import asyncio

    # Fire-and-forget in a worker thread: we don't await it, so the port binds
    # and the health probe answers immediately while pandas loads in the
    # background.
    asyncio.get_running_loop().run_in_executor(None, _warm_caches)
    yield


class CachedStaticFiles(StaticFiles):
    """StaticFiles that adds a Cache-Control header so browsers can skip
    re-fetching unchanged CSS/JS. StaticFiles already sends ETag/Last-Modified
    (so conditional requests still 304); this just lets the browser avoid the
    round-trip entirely until the max-age lapses."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers.setdefault("Cache-Control", STATIC_CACHE_CONTROL)
        return response


app = FastAPI(title="Data Analysis", lifespan=lifespan)

# Compress text responses (HTML/CSS/JS/JSON) so less goes over the wire -- Render
# doesn't gzip dynamic responses for you. Added before CORS so CORS stays the
# outermost layer and still short-circuits preflight requests.
app.add_middleware(GZipMiddleware, minimum_size=500)

# Allow the static page to call the API even when it's opened from a different
# origin (e.g. a separate dev server or file://). Permissive is fine for a demo.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz():
    """Liveness probe -- Render hits this to decide if the service is up."""
    return {"status": "ok"}


@app.get("/api/columns")
def list_columns():
    """List the analyzable (numeric) and categorical (label) columns in the CSV.

    `columns` stays the numeric list it has always been; `categorical` is added
    for the categorical tier and the group-by picker.
    """
    return {
        "dataset": DATA_CSV.name,
        "columns": sorted(analyzable_columns()),
        "categorical": sorted(categorical_columns()),
    }


@app.get("/api/overview")
def overview():
    """Dataset telemetry (shape, analyzable/categorical split, complete vs reduced)."""
    return dataset_overview()


@app.get("/api/stats/{column}")
def column_stats(column: str):
    """Return mean/median/mode/min/max/std/variance for one analyzable column.

    Retained for backward compatibility; it's the basic tier of /api/analyze.
    """
    if column not in analyzable_columns():
        raise HTTPException(status_code=404, detail=f"Unknown column: {column!r}")

    result = compute_stats(column)
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@app.get("/api/analyze/{tier}/{column}")
def analyze_column(tier: str, column: str, group: str | None = None):
    """Run any analysis tier for a column.

    tier -> one of basic/medium/advanced (numeric columns) or categorical
    (label columns). `group` (optional) names a column to group by and only
    applies to the medium/advanced tiers; it's ignored otherwise.
    """
    tier = tier.lower()
    if tier not in NUMERIC_TIERS and tier != "categorical":
        raise HTTPException(status_code=404, detail=f"Unknown tier: {tier!r}")

    # Numeric tiers draw from the analyzable columns; the categorical tier from
    # the label columns.
    valid_columns = analyzable_columns() if tier in NUMERIC_TIERS else categorical_columns()
    if column not in valid_columns:
        raise HTTPException(status_code=404, detail=f"Unknown column: {column!r}")

    # Grouping only means something for the tiers that run group comparisons.
    if tier in ("medium", "advanced") and group is not None:
        if group not in set(load_data().columns):
            raise HTTPException(
                status_code=404, detail=f"Unknown group column: {group!r}"
            )
    else:
        group = None

    result = compute_tier(tier, column, group)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@app.get("/")
def root():
    """Serve the static preview (index.html), falling back to info if it's gone."""
    if INDEX_HTML.is_file():
        return FileResponse(INDEX_HTML, headers={"Cache-Control": INDEX_CACHE_CONTROL})
    return {"service": "Data Analysis", "status": "ok", "preview": None}


# Mount the static frontend last so it can't shadow the routes above. index.html
# lives at the repo root (served by "/") and pulls its CSS/JS from /Web, so we
# mount Web/ at /Web to match the page's Web/CSS and Web/JS links.
if WEB_DIR.is_dir():
    app.mount("/Web", CachedStaticFiles(directory=WEB_DIR), name="web")
