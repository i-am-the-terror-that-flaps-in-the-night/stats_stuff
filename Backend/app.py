"""
app.py -- the ASGI web service that Render runs.

WHY THIS EXISTS
    fastapi was already a declared dependency, but nothing actually defined an
    app or a server entry point, so there was nothing for Render to start. This
    is that entry point: a minimal FastAPI app that

      * exposes a health check (for Render's health probe),
      * serves the built React frontend (frontend/dist),
      * exposes a JSON API (backed by engine.py) that the frontend calls to
        compute statistics on Data/nhanes_adolescent.csv -- the study's analytic
        cohort of U.S. adolescents aged 12-17, derived from the raw NHANES
        2017-2018 merge by engine.py's cohort builder, and
      * serves the project's actual research at /api/study/* (engine.py, part three):
        the pre-specified ten-step analysis of dietary sugar, metabolic markers
        and liver stress, with its cohort, its models and its caveats.

    The dataset and the study are the same body of work seen two ways. The
    generic tiers let a reader explore the cohort column by column; the study
    routes answer the questions the protocol committed to before the data were
    looked at. Both run on exactly the same 699 adolescents, which is what keeps
    a number quoted from one consistent with the other.

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
    GET  /api/cache                     live memo hit/miss counts
    GET  /api/stats/{column}            descriptive stats (the basic tier)
    GET  /api/analyze/{tier}/{column}   any tier, optional ?group=
    GET  /api/figures/histogram/{col}   binned distribution      (figures.py)
    GET  /api/figures/box/{col}         five-number summaries    (figures.py)
    GET  /api/figures/scatter/{x}/{y}   sampled cloud + fit line (figures.py)
    GET  /api/figures/correlation       the r matrix             (figures.py)
    GET  /api/lab/cohort/{col}          filtered subset summary  (lab_api.py)
    GET  /api/lab/sample-size/{col}     n vs. interval width     (lab_api.py)
    GET  /api/lab/bootstrap/{col}       resampled distribution   (lab_api.py)
    GET  /api/lab/outliers/{col}        four outlier policies    (lab_api.py)
    GET  /api/lab/screen                bulk tests + corrections (lab_api.py)
    GET  /api/study                     the whole ten-step study (study_api.py)
    GET  /api/study/headline            the summary-card numbers (study_api.py)
    GET  /api/study/steps               step index + grades      (study_api.py)
    GET  /api/study/step/{name}         one step                 (study_api.py)
    GET  /api/study/cohort              the attrition table      (study_api.py)
    GET  /api/predict/model             the ALT model card       (predict_api.py)
    POST /api/predict                   prediction + SHAP        (predict_api.py)
    POST /api/predict/explain           the same, narrated       (predict_api.py)
    GET  /api/predict/llm               LLM setup diagnostic     (predict_api.py)
    GET  /api/datasets                  dataset inventory        (studio.py)
    GET  /api/runs, POST /api/runs      the saved-run log        (studio.py)
    GET  /                              the SPA shell (frontend/dist/index.html)
    /assets/*                           the fingerprinted Vite bundle
    anything else that accepts HTML     the SPA shell, for client-side routes

SPEED AND MEMORY ON RENDER
    The free plan gives this service 0.1 vCPU and 512 MB, and spins it down when
    idle so boot is paid over and over. Both limits are real constraints on the
    design, and the budget is worth writing down because almost none of it is
    this application's own code. Measured on a development machine, in the shape
    the deploy actually runs in (multiply the times by roughly ten for a tenth of
    a CPU; the megabytes carry over as they are):

        interpreter                                    15 MB
        + fastapi / starlette / pydantic / uvicorn      34 MB    135 ms
        + numpy                                        12 MB     47 ms
        + pandas                                       45 MB    211 ms
        + scipy.stats                                  56 MB    460 ms
        + statsmodels.api                              29 MB    254 ms
        + the cohort, every cache and every warm answer  3 MB
        --------------------------------------------------------------
        resident, fully warmed                        184 MB
        + lightgbm, only if /api/predict is opened     10 MB     25 ms
        + the trained booster and its card              1 MB

    lightgbm is listed below the line because it is genuinely optional at run
    time: it is imported inside engine.py's predictor functions, so a visitor
    who never opens the Predict page never loads it. That 10 MB is also the
    entire cost of the SHAP explanations -- the `shap` package would have added
    scikit-learn, numba and llvmlite on top, which this budget cannot absorb.
    See engine.py's PART FOUR.

    So the cohort is a rounding error and the libraries are the whole bill. What
    follows from that:

      * pandas, scipy and engine.py are imported *lazily* -- inside the functions
        that use them, never at module load. uvicorn binds the port and /healthz
        answers in 135 ms against a 49 MB process, and the SPA shell and its
        assets serve from there while the rest loads behind them.
      * a background warm-up on startup (see `lifespan`) does that loading, and
        the precomputing, off the request path -- so the first /api call finds
        the caches warm without readiness having waited for any of it.
      * when the warm-up finishes it hands everything it built to the garbage
        collector permanently (gc.freeze), because otherwise every full
        collection for the rest of the process's life re-walks 167,000 objects
        that will never be collected.

    The one thing that ever threatened the 512 MB was reading the 17 MB raw
    NHANES merge at request time to rebuild the attrition table: 109 MB of peak
    RSS, more than pandas and scipy together, to recompute five fixed rows. That
    is now a committed artifact -- see cohort_attrition() in engine.py.

CACHING, IN FOUR LAYERS
    Nothing in this app can change while it runs -- the CSV is read once and is
    immutable thereafter -- so every answer is a pure function of its arguments
    and is worth keeping. The layers, outermost first:

      1. The browser. API responses carry a long max-age plus
         stale-while-revalidate, so a repeat view costs no network at all and a
         stale one is served instantly while it refreshes behind the reader.
      2. Revalidation. Every API GET carries an ETag built from the deployed
         code+data and the URL (see etag_middleware), so when the browser does
         ask, an unchanged answer is a ~200-byte 304 rather than its payload.
         This is what makes layer 1 safe: a redeploy changes every tag at once.
      3. The process. lru_cache on every compute path, unbounded, because the
         key space is small and fully validated -- 15 columns, 5 tiers, 4 group
         choices. Nothing can ever be evicted and recomputed.
      4. Startup. A background thread fills layer 3 before anyone asks (see
         _warm_caches), so the first visitor after a cold start finds the
         answers already there.

    Static assets are separate and simpler: fingerprinted bundles are immutable
    for a year, and index.html is "no-cache" with an ETag so a redeploy is picked
    up on the next navigation rather than after a TTL.
"""

from __future__ import annotations

import hashlib
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
# The analytic cohort -- U.S. adolescents aged 12-17, derived from the raw
# NHANES 2017-2018 merge by engine.py's build_cohort(), which is where every inclusion
# rule and variable definition is written down. This is the dataset the whole
# site runs on: the study's cohort, not a general demo slice, so the columns the
# Studio explores are the columns the research analyzes.
#
# It is committed (~100 KB) while the 17 MB raw merge it comes from lives in Git
# LFS. That split is what keeps the deploy honest AND fast: production reads a
# small tracked file and never needs an LFS object, and a cold start loads the
# cohort in milliseconds. Rebuild it with `python Backend/engine.py build-cohort`.
DATA_CSV = ROOT / "Data" / "nhanes_adolescent.csv"
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

# Cache-Control for the JSON analysis endpoints.
#
# These responses are pure functions of the (already-cached) dataframe: the same
# tier/column/group yields the same bytes for the life of the deploy. So the
# browser is told to reuse them WITHOUT asking, for an hour -- and then, for the
# next day, to keep using the stored copy while it refreshes in the background
# (stale-while-revalidate). A returning visitor therefore never waits on the
# network for a figure they have already seen, even after the freshness window
# closes, and never waits on a Render cold start for one either.
#
# What makes that safe rather than reckless is the ETag on every one of these
# responses (see etag_middleware). The tag is derived from the deployed code and
# data, so a redeploy changes every tag at once: the first revalidation after a
# deploy returns new bytes, and every unchanged response after that is a ~200-byte
# 304 instead of a payload. The old 5-minute no-ETag setting had the opposite
# trade -- it re-downloaded everything every 5 minutes to protect against a
# staleness window that revalidation closes properly.
API_CACHE_CONTROL = "public, max-age=3600, stale-while-revalidate=86400"


@lru_cache(maxsize=1)
def deploy_version() -> str:
    """A token that changes when the deployed code or data changes, and not
    otherwise. It is the identity every API ETag is built on.

    Built from the size and mtime of the dataset and of the modules that decide
    what an answer looks like. Cheap (a few stat() calls, once per process) and
    honest about the two things that can actually change an answer: a new CSV or
    new engine code. A random per-process token would also be correct but would
    throw away every client's cache on each restart -- and Render restarts a free
    service constantly.
    """
    parts = []
    here = Path(__file__)
    sources = (
        DATA_CSV,
        here,
        # engine.py carries the tiers, the cohort derivation, the study
        # protocol and the predictor, so its mtime covers all four. A change to
        # a model specification changes what /api returns just as surely as a
        # new CSV does, and every cached copy has to be invalidated when it
        # happens.
        here.with_name("engine.py"),
        # The trained booster and its card. A retrain changes /api/predict/model
        # -- the ranges the UI's sliders offer and the scores it prints -- while
        # leaving every source file untouched, so without this a redeploy of a
        # new model would serve the old card out of browser caches for an hour.
        here / "model" / "alt_lgbm.json",
    )
    for path in sources:
        try:
            info = path.stat()
            parts.append(f"{path.name}:{info.st_size}:{info.st_mtime_ns}")
        except OSError:
            parts.append(f"{path.name}:missing")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


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
    """Load and clean the analytic cohort once, then reuse it across requests.

    The bookkeeping columns are dropped HERE, on the way in, rather than being
    filtered out of the column lists further down. That distinction turned out
    to matter: hiding them from /api/columns only stops a reader ASKING for the
    mean of a participant ID. It does nothing about the engine, which takes the
    whole dataframe and, in the advanced and expert tiers, regresses the chosen
    column on every other numeric column it can find. With SEQN and the survey
    design codes still present, "expert · TrigHDLRatio" was quietly fitting a
    model on participant ID and sampling stratum, and reporting its VIFs and
    residual diagnostics as though they meant something.

    Dropping the columns at the source is the only version of this that holds,
    because it fixes every consumer at once -- the tiers, the figures, the lab,
    the correlation matrix -- instead of requiring each to remember. Nothing
    served over HTTP needs them. The study does, and it reads the CSV itself
    through study.load_cohort(), where the survey weight and the design codes
    are exactly the point.
    """
    import pandas as pd

    try:
        from engine import NON_ANALYTIC_COLUMNS
    except ModuleNotFoundError:
        from Backend.engine import NON_ANALYTIC_COLUMNS

    _, df_cleanup = _load_engine()
    frame = df_cleanup(pd.read_csv(DATA_CSV))
    return frame.drop(columns=[c for c in NON_ANALYTIC_COLUMNS if c in frame.columns])


def load_data():
    """get_dataframe(), but turn a missing file into a clean 503 for the client."""
    try:
        return get_dataframe()
    except FileNotFoundError:
        detail = f"Dataset not found: {DATA_CSV.name}"
        raise HTTPException(status_code=503, detail=detail) from None


@lru_cache(maxsize=1)
def analyzable_columns() -> frozenset[str]:
    """Columns with at least one numeric value after coercion (same rule as
    basic_analysis). The bookkeeping columns are already gone -- get_dataframe()
    drops them on the way in -- so this is the plain numeric test again."""
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
    analyzable_columns). These feed the categorical tier and the group-by
    picker."""
    df = load_data()
    numeric = analyzable_columns()
    return frozenset(col for col in df.columns if col not in numeric)


@lru_cache(maxsize=1)
def label_values() -> dict[str, list[str]]:
    """The distinct values of each label column, most common first.

    Exposed so the Studio's cohort builder can OFFER the labels rather than ask
    the reader to type them. "Non-Hispanic White" typed from memory is a cohort
    of nobody, and a filter that silently matches nothing is the worst possible
    failure mode for a tool whose whole job is showing how cohorts shrink.

    Capped at 24 per column: these are label columns by definition, and anything
    with more distinct values than that is a free-text field that has been
    misclassified, not a category worth listing in a dropdown.
    """
    df = load_data()
    out: dict[str, list[str]] = {}
    for column in sorted(categorical_columns()):
        counts = df[column].dropna().astype(str).value_counts()
        out[column] = [str(v) for v in counts.index[:24]]
    return out


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
    categorical = categorical_columns()
    return {
        "dataset": DATA_CSV.name,
        "rows": total,
        # The columns the engine actually sees. get_dataframe() has already
        # dropped the cohort's bookkeeping columns, so `columns` is the width of
        # the analyzable frame and numeric + categorical partition it exactly.
        "columns": len(df.columns),
        "numeric": len(numeric),
        "categorical": len(categorical),
        "complete": complete,
        "reduced": len(numeric) - complete,
    }


@lru_cache(maxsize=None)
def compute_stats(column: str):
    """Descriptive stats for one column, memoized.

    The dataframe is loaded once (get_dataframe is itself cached) and never
    changes over the process lifetime, so a given column's stats are stable --
    caching them makes repeat requests for the same column O(1) instead of
    re-running the pandas reductions each time.

    Unbounded (maxsize=None), because the key space is: the input is one of 15
    column names, validated against analyzable_columns() before this is called,
    so "unbounded" tops out at 15 entries of a few hundred bytes. An LRU bound
    here could only ever evict an entry that will be asked for again.
    """
    DataAnalyzer, _ = _load_engine()
    return DataAnalyzer(load_data()).basic_analysis(column)


# The analysis tiers that operate on a numeric column. The categorical branch is
# handled separately (it works on label columns), so it's kept out of this set.
# "expert" is the deepest numeric tier (collinearity/VIF, regression diagnostics,
# published clinical thresholds where one exists, trend tests) -- see engine.py's
# expert_analysis().
NUMERIC_TIERS = ("basic", "medium", "advanced", "expert")


@lru_cache(maxsize=None)
def compute_tier(tier: str, column: str, group: str | None):
    """Run one analysis tier for a column, memoized on (tier, column, group).

    Same rationale as compute_stats: the dataframe is immutable over the process
    lifetime, so each (tier, column, group) answer is stable and worth caching --
    it also means the one-time statsmodels import the advanced tier pays is
    only paid once per distinct request.

    Unbounded, and bounded in practice by the inputs: 5 tiers × 15 numeric
    columns × (no group + 3 label columns) is 240 possible keys, every one of
    them validated before it reaches here. The old 256-entry LRU was therefore
    sized just under the point where it would start evicting the most expensive
    answers in the app -- an expert-tier result costs ~40 ms to recompute, and
    the whole space costs a few megabytes to simply keep.
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
    """Fill every cache the first visitor would otherwise fill for us.

    Runs in a background thread on startup, so none of it delays readiness --
    uvicorn has already bound the port and /healthz already answers by the time
    this starts. That is what lets it be greedy: the work below costs a few
    seconds of one background thread, once, and in exchange the first visitor
    after a cold start finds the answers already computed instead of paying for
    them one click at a time.

    Ordered cheapest-and-most-likely-first, so if the process is killed partway
    through (Render can, mid-boot) the highest-value entries are already there.
    Every stage is individually guarded: a column the engine cannot analyze must
    not stop the warm-up for the fourteen that follow.
    """

    def attempt(label, work) -> None:
        try:
            work()
        except Exception:
            # A warm-up failure is not an error -- it just means the request path
            # computes that answer lazily, exactly as it did before. Swallowed
            # rather than logged so a missing CSV doesn't fill the log on every
            # boot of a service that is otherwise fine.
            _ = label

    # 1. The dataframe itself. Imports pandas and reads+cleans the CSV -- by far
    #    the biggest single cost, and everything below depends on it.
    attempt("dataframe", analyzable_columns)
    attempt("overview", dataset_overview)
    attempt("categorical", categorical_columns)
    attempt("labels", label_values)
    attempt("version", deploy_version)

    try:
        columns = sorted(analyzable_columns())
        labels = sorted(categorical_columns())
    except Exception:
        return

    # 2. The basic tier for every numeric column. This is what the landing page
    #    asks for first, it is cheap (~0.6 ms each), and it covers the whole
    #    column list rather than guessing which one gets clicked.
    for column in columns:
        attempt(f"basic:{column}", lambda c=column: compute_tier("basic", c, None))

    # 3. The figures. Each is one pandas pass and they are what the Figures page
    #    opens with; the correlation matrix is the most expensive single answer
    #    in the app (105 pairwise correlations) and the most reused.
    try:
        from figures_api import box_plot, correlation_matrix, histogram
    except ModuleNotFoundError:
        from Backend.figures_api import box_plot, correlation_matrix, histogram

    attempt("correlation", correlation_matrix)
    for column in columns:
        attempt(f"hist:{column}", lambda c=column: histogram(c))
    for label in labels:
        attempt(
            f"box:{label}",
            lambda g=label: box_plot("BMI" if "BMI" in columns else columns[0], g),
        )

    # 4. The medium tier, ungrouped. The deepest thing worth precomputing: the
    #    advanced and expert tiers pull in statsmodels and take tens of
    #    milliseconds each, so warming all 15 would spend real CPU on answers
    #    most visitors never open. Their statsmodels import IS worth paying for
    #    up front, though, which one call buys for all of them.
    for column in columns:
        attempt(f"medium:{column}", lambda c=column: compute_tier("medium", c, None))
    attempt("statsmodels", lambda: compute_tier("advanced", columns[0], None))

    # 5. The study itself, last and most expensive: eleven weighted regressions
    #    plus the statsmodels import. It goes at the end because everything above
    #    is cheaper and more likely to be asked for first, and it is warmed at all
    #    because the study IS the site -- the landing page opens with its headline
    #    numbers, and computing those on the first visitor's request is the one
    #    place a cold start would still be visible.
    def warm_study():
        try:
            from engine import headline, run_study
        except ModuleNotFoundError:
            from Backend.engine import headline, run_study
        headline()
        run_study()

    attempt("study", warm_study)

    # 6. The predictor. Last, because it is the only stage that imports a
    #    library nothing else needs (LightGBM, ~10 MB and ~25 ms) and the only
    #    one a visitor can skip entirely by not opening the Predict page. Doing
    #    it here means the judge who does open it finds the import already paid
    #    and the booster already parsed, rather than waiting four seconds on a
    #    tenth of a vCPU for a page that is supposed to feel instant.
    #
    #    A missing Backend/model/ artifact makes this a no-op, exactly like
    #    every other stage: attempt() swallows it and /api/predict answers 503
    #    with instructions instead of the process failing to boot.
    def warm_predictor():
        try:
            from engine import predict_alt, predictor_card
        except ModuleNotFoundError:
            from Backend.engine import predict_alt, predictor_card
        card = predictor_card()
        # One real prediction at the cohort medians. Parses the booster, runs
        # TreeSHAP once and builds the system prompt's inputs -- everything the
        # first click would otherwise do.
        predict_alt({name: spec["default"] for name, spec in card["inputs"].items()})

    attempt("predictor", warm_predictor)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    import asyncio
    import gc

    def warm_then_freeze() -> None:
        """The warm-up, then hand everything it built to the GC permanently.

        A full (generation-2) collection walks every object the collector
        tracks, and once the warm-up has finished that is around 167,000 of
        them: module constants, pandas internals, the cohort frame and the
        cached answers above. Essentially all of it lives until the process
        exits, so every one of those walks is work with a foregone conclusion --
        30 ms here, and on Render's free tier, where the service gets a tenth of
        a vCPU, closer to 300 ms, repeated whenever the threshold trips for the
        rest of the process's life.

        gc.freeze() moves those objects into a permanent generation the
        collector never visits again. Measured on this app, it takes a full
        gc.collect(2) from 30 ms to 0.

        The collect() before it is what makes it safe rather than a leak: it
        clears out anything that is already garbage, so only objects that
        genuinely survive the warm-up get frozen. Nothing frozen here is ever
        evicted -- the caches above are all maxsize=None or maxsize=1.
        """
        try:
            _warm_caches()
        finally:
            gc.collect()
            gc.freeze()

    # Fire-and-forget in a worker thread: we don't await it, so the port binds
    # and the health probe answers immediately while pandas loads in the
    # background.
    asyncio.get_running_loop().run_in_executor(None, warm_then_freeze)
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


@app.middleware("http")
async def etag_middleware(request: Request, call_next):
    """Give every API GET a strong ETag, and answer If-None-Match with a 304.

    This is what makes the long max-age above safe. The tag identifies the
    deploy plus the exact request, so:

      * an unchanged answer costs a ~200-byte 304 instead of its payload -- the
        correlation matrix and the scatter cloud are the ones that matter, at
        1.6 KB and 17 KB;
      * a redeploy changes deploy_version(), so every tag changes at once and
        the first revalidation after a deploy returns real bytes. Nothing can
        be pinned to a stale answer by a long TTL.

    The tag is built from the URL rather than from the response body on purpose.
    Hashing the body would mean serializing and digesting every response on
    every request -- paying CPU on the server to save bytes on the wire, which
    is backwards on a single free-tier worker. The URL plus the deploy token
    already identifies the answer uniquely, because that is exactly the pair the
    lru_caches are keyed on.
    """
    response = await call_next(request)

    is_api = request.url.path.startswith("/api")
    if (
        request.method not in ("GET", "HEAD")
        or not is_api
        or response.status_code != 200
    ):
        return response

    # blake2b, not the builtin hash(): Python randomizes string hashing per
    # process, so hash() would mint a different tag for the same URL after every
    # restart -- and a free-tier service restarts constantly. The whole point is
    # that a client's stored copy survives a restart.
    url_digest = hashlib.blake2b(str(request.url).encode(), digest_size=6).hexdigest()
    etag = f'"{deploy_version()}-{url_digest}"'
    response.headers["ETag"] = etag

    if request.headers.get("if-none-match") == etag:
        # 304 carries no body, so hand back only the headers that still describe
        # the cached copy the client already holds.
        keep = {"etag", "cache-control", "vary"}
        headers = {k: v for k, v in response.headers.items() if k.lower() in keep}
        return Response(status_code=304, headers=headers)
    return response


# Compress text responses (HTML/CSS/JS/JSON) so less goes over the wire -- Render
# doesn't gzip dynamic responses for you. Added before CORS so CORS stays the
# outermost layer and still short-circuits preflight requests.
#
# 256, not 500: the JSON here is highly compressible (repeated keys, long prose
# caveats, digit strings) and several real responses -- /api/columns, a basic
# tier result, a box summary -- land in the 300-500 byte gap the old floor let
# through uncompressed.
app.add_middleware(GZipMiddleware, minimum_size=256)

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
    if (
        exc.status_code == 404
        and wants_html
        and not is_api_path
        and INDEX_HTML.is_file()
    ):
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
        # Additive: existing callers read `columns` and `categorical` and are
        # unaffected. The Studio's cohort builder needs the actual labels to
        # offer them as choices.
        "values": label_values(),
    }


@app.get("/api/overview")
def overview(response: Response):
    """Dataset telemetry (shape, analyzable/categorical split, complete vs reduced)."""
    response.headers["Cache-Control"] = API_CACHE_CONTROL
    return dataset_overview()


@app.get("/api/cache")
def cache_stats(response: Response):
    """Live hit/miss counts for every memo in the process.

    Real numbers, read straight off each function's cache_info(), so the caching
    claims elsewhere on the site are checkable rather than asserted -- and so a
    regression that silently stops caching something shows up as a hit rate that
    fell, instead of as a page that merely feels slower.

    Deliberately NOT cached itself: a cached view of the cache would be stale by
    definition, and would count its own hits.
    """
    try:
        from figures_api import box_plot, correlation_matrix, histogram, scatter
    except ModuleNotFoundError:
        from Backend.figures_api import box_plot, correlation_matrix, histogram, scatter

    memos = {
        "dataframe": get_dataframe,
        "columns": analyzable_columns,
        "overview": dataset_overview,
        "stats": compute_stats,
        "tiers": compute_tier,
        "histogram": histogram,
        "box": box_plot,
        "scatter": scatter,
        "correlation": correlation_matrix,
    }

    caches = {}
    hits = misses = 0
    for name, fn in memos.items():
        # pylint can't see through the lru_cache wrapper on these functions and
        # reads `.cache_info()` as a call to the wrapped function itself.
        info = fn.cache_info()  # pylint: disable=too-many-function-args
        hits += info.hits
        misses += info.misses
        caches[name] = {
            "hits": info.hits,
            "misses": info.misses,
            "stored": info.currsize,
            # None means unbounded -- see the note on compute_tier for why the
            # bounded key space makes that the right choice here.
            "capacity": info.maxsize,
        }

    total = hits + misses
    response.headers["Cache-Control"] = "no-store"
    return {
        "version": deploy_version(),
        "hits": hits,
        "misses": misses,
        "hit_rate": round(hits / total, 4) if total else None,
        "caches": caches,
    }


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
def analyze_column(
    tier: str, column: str, response: Response, group: str | None = None
):
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
    valid_columns = (
        analyzable_columns() if tier in NUMERIC_TIERS else categorical_columns()
    )
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

# The /api/figures/* aggregates the Figures page draws from. Included here for
# the same reason as studio.py: figures_api.py reaches back into this module for
# the cached dataframe and column lists, so it can only be imported once those
# exist. The module is figures_api and not figures because the repo root holds a
# `figures/` directory of PDFs -- launched from the root (uvicorn main:app, which
# is what Render runs) a bare `figures` resolves to that directory as a namespace
# package and the import fails on a name, not on the module.
try:
    from figures_api import router as figures_router
except ModuleNotFoundError:
    from Backend.figures_api import router as figures_router
app.include_router(figures_router)

# The Studio's experiments (/api/lab/*). Same lazy-import reason as above.
try:
    from lab_api import router as lab_router
except ModuleNotFoundError:
    from Backend.lab_api import router as lab_router
app.include_router(lab_router)

# The pre-specified ten-step analysis (/api/study/*). This is the project's
# actual research -- the rest of the API explores the cohort, this one answers
# the questions the protocol committed to in advance. Included last for the same
# lazy-import reason as the routers above.
try:
    from study_api import router as study_router
except ModuleNotFoundError:
    from Backend.study_api import router as study_router
app.include_router(study_router)

# The interactive demo (/api/predict/*): the gradient boosting model, its SHAP
# breakdown, and the language model that narrates one. Same lazy-import reason
# as the routers above, plus one of its own -- this module is the only place in
# the service that reads OPENROUTER_API_KEY, and the only one whose routes can
# make an outbound network call.
try:
    from predict_api import router as predict_router
except ModuleNotFoundError:
    from Backend.predict_api import router as predict_router
app.include_router(predict_router)

# Mount the built assets last so they can't shadow the routes above. Vite emits
# fingerprinted files into dist/assets and references them from dist/index.html
# by ABSOLUTE path (base: "/" in vite.config.ts) -- required, because index.html
# is served for deep links too, and a relative reference would resolve against
# /studio/ on /studio/runs and 404.
if ASSETS_DIR.is_dir():
    app.mount("/assets", CachedStaticFiles(directory=ASSETS_DIR), name="assets")
