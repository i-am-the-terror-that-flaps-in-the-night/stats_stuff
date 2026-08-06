"""
app.py -- the ASGI web service that Render runs.

WHY THIS EXISTS
    fastapi was already a declared dependency, but nothing actually defined an
    app or a server entry point, so there was nothing for Render to start. This
    is that entry point: a minimal FastAPI app that

      * exposes a health check (for Render's health probe),
      * serves the built React frontend (frontend/dist), and
      * exposes a JSON API (backed by engine.py) that the frontend calls to
        compute statistics on Data/nhanes.csv -- a curated, human-readable
        subset (18 renamed columns) of the NHANES 2017-2018 data this project
        analyzes, built from Data/nhanes_analytic.csv (see that file's docstring
        note for provenance; the full 412-column raw export stays local-only).

    The frontend is a Vite + React + TypeScript app under frontend/. It owns all
    presentation and its own URLs; this module is a pure JSON API plus a static
    file server. There is no server-side rendering left -- the Studio pages that
    used to be Jinja templates are routes in the SPA now, fed by studio.py's
    /api/datasets and /api/runs.

RUNNING IT
    Backend only:  uvicorn app:app --reload      (from this Backend/ directory)
    On Render:     see ../render.yaml (from the repo root: uvicorn main:app)

    In development, run the Vite dev server alongside it for hot reload:
        cd frontend && npm run dev      -> http://localhost:5173
    Vite proxies /api to :8000, so the browser stays on one origin and there is
    no CORS in the loop. To serve the built bundle from FastAPI instead:
        cd frontend && npm run build    -> then open http://127.0.0.1:8000/

ROUTES
    GET  /healthz                       {"status": "ok"} -- Render's probe
    GET  /api/columns                   numeric + categorical column lists
    GET  /api/overview                  dataset telemetry
    GET  /api/stats/{column}            descriptive stats (the basic tier)
    GET  /api/analyze/{tier}/{column}   any tier, optional ?group=
    GET  /api/datasets                  dataset inventory        (studio.py)
    GET  /api/runs, POST /api/runs      the saved-run log        (studio.py)
    GET  /                              the SPA shell (frontend/dist/index.html)
    /assets/*                           the fingerprinted Vite bundle
    anything else that accepts HTML     the SPA shell, for client-side routes

SPEED ON RENDER
    Render's free plan spins the service down when idle and cold-starts it on the
    next request, so boot time is paid over and over. Two things keep that fast:

      * pandas/engine.py are imported *lazily* (inside the functions that use
        them), not at module load. Importing pandas+numpy is by far the biggest
        chunk of boot time -- on a shared free-tier CPU it's seconds. Keeping it
        off the import path means uvicorn binds the port, the health probe
        answers, and the SPA shell + its assets serve immediately; only the
        first /api call pays the import (and it's cached after that).
      * a background warm-up on startup (see `lifespan`) pre-imports pandas and
        pre-loads/cleans the CSV off the request path, so even the first /api
        call usually finds the caches already warm -- without delaying readiness.

    Responses are gzip-compressed, and static assets are served "no-cache" with
    ETag/Last-Modified so repeat visits revalidate cheaply (a tiny 304 for unchanged
    CSS/JS) while any redeploy is picked up immediately rather than after a TTL.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

# NOTE: pandas and engine.py are imported lazily inside get_dataframe(),
# analyzable_columns() and compute_stats() -- deliberately NOT at module top --
# to keep the heavy pandas/numpy import off Render's cold-start path. See the
# "SPEED ON RENDER" note in the module docstring.

# Resolve paths from __file__ so they're correct regardless of the working
# directory. Data/ lives at the repo root, one level up; the frontend is the
# Vite build output under frontend/dist (see frontend/vite.config.ts).
ROOT = Path(__file__).resolve().parent.parent
DATA_CSV = ROOT / "Data" / "nhanes.csv"
DIST_DIR = ROOT / "frontend" / "dist"
ASSETS_DIR = DIST_DIR / "assets"
INDEX_HTML = DIST_DIR / "index.html"
FAVICON = DIST_DIR / "favicon.ico"

# Cache-Control, split by what the file actually is.
#
# Vite fingerprints everything under dist/assets (index-CYwdBGtm.js), so those
# names change whenever their contents do and can be cached hard and forever --
# a returning visitor re-downloads nothing, and a deploy can't serve a stale
# asset because the new HTML asks for a different filename.
#
# index.html is the opposite: its name never changes and it is the thing that
# points at the fingerprinted assets, so it must be revalidated every time or a
# deploy would leave browsers requesting bundles that no longer exist.
# "no-cache" means "store it, but check before reusing" -- an unchanged file
# comes back as a tiny 304. Neither setting touches Render's cold-start path;
# that's the server-side pandas import, not asset fetches.
STATIC_CACHE_CONTROL = "public, max-age=31536000, immutable"
INDEX_CACHE_CONTROL = "no-cache"

# Cache-Control for the JSON analysis endpoints. Unlike the static assets above,
# these responses are pure functions of the (already-cached) dataframe -- same
# tier/column/group always yields the same bytes for the life of a running
# process -- so the browser can skip the round-trip entirely instead of just
# revalidating it. A short max-age (not "immutable") caps how long a stale
# result can outlive a redeploy: 5 minutes is enough to make repeat views in
# one session free, without letting a bug-fix deploy hide behind a long-lived
# client cache the way a longer TTL would.
API_CACHE_CONTROL = "public, max-age=300"


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
    """Load and clean Data/nhanes.csv once, then reuse it across requests."""
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
# "expert" is the deepest numeric tier (collinearity/VIF, regression diagnostics,
# published clinical thresholds where one exists, trend tests) -- see engine.py's
# expert_analysis().
NUMERIC_TIERS = ("basic", "medium", "advanced", "expert")


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
    if tier == "expert":
        return analyzer.expert_analysis(column, group)
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


@app.get("/favicon.ico")
def favicon():
    """Browsers request this automatically; without a route it 404s on every
    page load. Served from the same asset index.html already links to."""
    if FAVICON.is_file():
        return FileResponse(FAVICON, headers={"Cache-Control": STATIC_CACHE_CONTROL})
    raise HTTPException(status_code=404, detail="favicon.ico not found")


@app.exception_handler(StarletteHTTPException)
async def spa_fallback_handler(request: Request, exc: StarletteHTTPException):
    """Hand unmatched browser navigations to the client-side router.

    The frontend owns its URLs now (/studio/runs, /methodology, ...), and those
    paths exist only in the browser -- the server has no route for them. So a 404
    on a *navigation* is not an error: it means "a deep link the SPA knows about",
    and the right answer is index.html, which boots the router and renders it.
    React Router then decides whether it is a real page or its own 404.

    Two guards keep that from swallowing genuine errors:
      * /api/... keeps its JSON error body, so a bad column still returns 404
        with a useful detail instead of a page of HTML a fetch() can't read;
      * only requests that actually accept HTML get the fallback, so a script
        never receives a document where it asked for data.
    """
    is_api_path = request.url.path.startswith("/api")
    wants_html = "text/html" in request.headers.get("accept", "")
    if exc.status_code == 404 and wants_html and not is_api_path and INDEX_HTML.is_file():
        # 200, not 404: this is a real page being served, and the router will
        # emit its own not-found view if the path matches nothing.
        return FileResponse(INDEX_HTML, headers={"Cache-Control": INDEX_CACHE_CONTROL})
    return await http_exception_handler(request, exc)


@app.get("/api/columns")
def list_columns(response: Response):
    """List the analyzable (numeric) and categorical (label) columns in the CSV.

    `columns` stays the numeric list it has always been; `categorical` is added
    for the categorical tier and the group-by picker.
    """
    response.headers["Cache-Control"] = API_CACHE_CONTROL
    return {
        "dataset": DATA_CSV.name,
        "columns": sorted(analyzable_columns()),
        "categorical": sorted(categorical_columns()),
    }


@app.get("/api/overview")
def overview(response: Response):
    """Dataset telemetry (shape, analyzable/categorical split, complete vs reduced)."""
    response.headers["Cache-Control"] = API_CACHE_CONTROL
    return dataset_overview()


@app.get("/api/stats/{column}")
def column_stats(column: str, response: Response):
    """Return mean/median/mode/min/max/std/variance for one analyzable column.

    Retained for backward compatibility; it's the basic tier of /api/analyze.
    """
    if column not in analyzable_columns():
        raise HTTPException(status_code=404, detail=f"Unknown column: {column!r}")

    result = compute_stats(column)
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    response.headers["Cache-Control"] = API_CACHE_CONTROL
    return result


@app.get("/api/analyze/{tier}/{column}")
def analyze_column(tier: str, column: str, response: Response, group: str | None = None):
    """Run any analysis tier for a column.

    tier -> one of basic/medium/advanced/expert (numeric columns) or categorical
    (label columns). `group` (optional) names a column to group by and only
    applies to the medium/advanced/expert tiers; it's ignored otherwise.
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
    if tier in ("medium", "advanced", "expert") and group is not None:
        if group not in set(load_data().columns):
            raise HTTPException(
                status_code=404, detail=f"Unknown group column: {group!r}"
            )
    else:
        group = None

    result = compute_tier(tier, column, group)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    response.headers["Cache-Control"] = API_CACHE_CONTROL
    return result


@app.get("/")
def root():
    """Serve the built SPA shell.

    If frontend/dist is missing the build simply hasn't run, so say that plainly
    rather than 404-ing: it is the one failure here a developer can fix in one
    command, and the API below it still works meanwhile.
    """
    if INDEX_HTML.is_file():
        return FileResponse(INDEX_HTML, headers={"Cache-Control": INDEX_CACHE_CONTROL})
    return {
        "service": "Data Analysis",
        "status": "ok",
        "frontend": "not built",
        "hint": "cd frontend && npm ci && npm run build",
    }


# The /studio/ and /guide/ pages. Included here at the bottom -- after every
# helper above is defined -- because studio.py calls back into this module for
# the cached engine functions; importing it earlier would be a circular import.
# These routes are registered before the /Web mount so the mount can't shadow
# them, and after "/" so nothing here changes the API's default behaviour.
try:
    from studio import router as studio_router
except ModuleNotFoundError:
    from Backend.studio import router as studio_router
app.include_router(studio_router)

# Mount the built assets last so they can't shadow the routes above. Vite emits
# fingerprinted files into dist/assets and references them from dist/index.html
# by ABSOLUTE path (base: "/" in vite.config.ts) -- required, because index.html
# is served for deep links too, and a relative reference would resolve against
# /studio/ on /studio/runs and 404.
if ASSETS_DIR.is_dir():
    app.mount("/assets", CachedStaticFiles(directory=ASSETS_DIR), name="assets")
