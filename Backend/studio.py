"""
studio.py -- the server-rendered /studio/ and /guide/ pages.

WHY THIS EXISTS
    app.py serves the dashboard, the JSON API and the static assets. This module
    adds the human-readable browser on top: a set of FastAPI routes that render
    the Jinja2 templates in templates/studio/ and call app.py's *own* cached
    functions directly -- same process, same memory -- so drawing a table never
    makes a second HTTP hop. It's mounted by app.py (app.include_router) at the
    very bottom of that file, after every cached helper is defined, because we
    call back into it (see WHY THE IMPORTS ARE LAZY).

WHAT IT SERVES
    GET  /studio/                              index: dataset summary + tier chips
    GET  /studio/analyze/{tier}/{column}/      one analysis, rendered as a ledger
    POST /studio/analyze/{tier}/{column}/save/ append that run to the log, redirect
    GET  /studio/runs/                         the saved-run log, newest first
    GET  /guide/                               the "how it's built" write-up

THE RUN LOG
    Saved runs go in a local SQLite file next to this module. Render's free tier
    has no persistent disk, so this is a lab-notebook for your own machine, not
    shared state the site depends on -- an empty log is the normal online state.

WHY THE IMPORTS ARE LAZY
    app.py imports THIS module at its bottom and we call back into app.py for the
    cached engine functions, so importing app at studio's module top would be a
    circular import. Every app.py access therefore happens inside a request
    handler (via _app()), by which point app.py has finished importing. _app()
    also tolerates both launch styles -- `uvicorn app:app` from Backend/ (bare
    `app`) and `uvicorn main:app` from the repo root (`Backend.app`) -- the same
    way app.py's _load_engine() does.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA_DIR = ROOT / "Data"
RUNS_DB = HERE / "studio_runs.db"  # local lab-notebook; gitignored, not deployed

templates = Jinja2Templates(directory=str(HERE / "templates"))
router = APIRouter()

# Datasets shown on the index and the guide. Only the practice file ships with
# the project; the larger research exports stay on the lab machine, so "absent"
# is the expected online state. Availability is derived, never hard-coded.
DATASETS = (
    {"file": "data.csv", "blurb": "Practice dataset that ships with the project."},
    {"file": "trial_full.csv", "blurb": "Full research export -- stays on the lab machine."},
    {"file": "followup.csv", "blurb": "Follow-up measurements -- stays on the lab machine."},
)


def _app():
    """The initialised app.py module. Imported lazily to dodge the circular
    import (app.py imports us) and to work from either launch directory."""
    try:
        import app as module
    except ModuleNotFoundError:
        import Backend.app as module
    return module


# ----------------------------------------------------------------------------
# Data assembly
# ----------------------------------------------------------------------------

def _build_data():
    """The dataset summary the templates read as `data`: its overview telemetry
    and its numeric/categorical column lists. Returns None if the CSV can't be
    loaded, which the templates render as a graceful "nothing to report" notice
    rather than a 500."""
    app = _app()
    try:
        overview = app.dataset_overview()
        numeric = sorted(app.analyzable_columns())
        categorical = sorted(app.categorical_columns())
    except Exception:
        return None
    return SimpleNamespace(overview=overview, numeric=numeric, categorical=categorical)


def _datasets():
    """DATASETS with a live `available` flag from the filesystem."""
    return [
        {"label": d["file"], "available": (DATA_DIR / d["file"]).is_file(), "blurb": d["blurb"]}
        for d in DATASETS
    ]


def _scalar(value) -> str:
    """Render one statistic for the ledger table -- readable, never raw repr."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return "n/a" if value != value else f"{value:.4g}"  # value != value catches NaN
    if isinstance(value, (list, tuple)):
        return ", ".join(_scalar(v) for v in value) or "n/a"
    if isinstance(value, dict):
        return ", ".join(f"{k}: {_scalar(v)}" for k, v in value.items()) or "n/a"
    return str(value)


def _result_rows(result: dict):
    """Flatten an engine result dict into (label, value) rows for analyze.html.
    Nested dicts (the medium/advanced tiers return them) are expanded one level
    as "parent.child" so the table stays flat and readable."""
    rows = []
    for key, value in result.items():
        if key == "error":
            continue
        if isinstance(value, dict):
            for subkey, subvalue in value.items():
                rows.append((f"{key}.{subkey}", _scalar(subvalue)))
        else:
            rows.append((key, _scalar(value)))
    return rows


def _validate(app, tier: str, column: str):
    """Resolve and validate (tier, column) the same way app.analyze_column does.
    Raises HTTPException on a bad tier or column; returns nothing on success."""
    if tier not in app.NUMERIC_TIERS and tier != "categorical":
        raise HTTPException(status_code=404, detail=f"Unknown tier: {tier!r}")
    valid = app.analyzable_columns() if tier in app.NUMERIC_TIERS else app.categorical_columns()
    if column not in valid:
        raise HTTPException(status_code=404, detail=f"Unknown column: {column!r}")


def _run_analysis(app, tier: str, column: str, group: str | None):
    """Run one tier and time it. Grouping only applies to medium/advanced, and a
    non-existent group column is treated as no grouping (mirrors app.py). Returns
    (result_dict, effective_group, elapsed_ms)."""
    if tier in ("medium", "advanced", "expert") and group:
        if group not in set(app.load_data().columns):
            group = None
    else:
        group = None
    started = time.perf_counter()
    result = app.compute_tier(tier, column, group)
    elapsed_ms = int(round((time.perf_counter() - started) * 1000))
    return result, group, elapsed_ms


# ----------------------------------------------------------------------------
# Run log (SQLite)
# ----------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(RUNS_DB)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT    NOT NULL,
            tier        TEXT    NOT NULL,
            column      TEXT    NOT NULL,
            group_col   TEXT,
            dataset     TEXT    NOT NULL,
            duration_ms INTEGER NOT NULL
        )
        """
    )
    return conn


def _record_run(tier: str, column: str, group: str | None, dataset: str, duration_ms: int) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO runs (ts, tier, column, group_col, dataset, duration_ms) VALUES (?, ?, ?, ?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), tier, column, group, dataset, duration_ms),
        )


def _read_runs(limit: int | None = None):
    with _connect() as conn:
        sql = "SELECT * FROM runs ORDER BY id DESC"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        return [_run_view(row) for row in conn.execute(sql).fetchall()]


def _run_view(row: sqlite3.Row) -> dict:
    """Shape one DB row for the templates, with both short and long timestamps."""
    try:
        stamp = datetime.fromisoformat(row["ts"])
        when_short = stamp.strftime("%m-%d %H:%M")
        when_long = stamp.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:  # unparseable timestamp -- show it raw rather than crash
        when_short = when_long = row["ts"]
    return {
        "when_short": when_short,
        "when_long": when_long,
        "tier": row["tier"],
        "column": row["column"],
        "group": row["group_col"],
        "dataset": row["dataset"],
        "duration_ms": row["duration_ms"],
        "label": f"{row['tier']} / {row['column']}",
    }


# ----------------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------------

@router.get("/studio/")
def studio_index(request: Request):
    app = _app()
    return templates.TemplateResponse(
        request,
        "studio/index.html",
        {
            "data": _build_data(),
            "tiers": app.NUMERIC_TIERS,
            "datasets": _datasets(),
            "recent": _read_runs(limit=5),
        },
    )


@router.get("/studio/analyze/{tier}/{column}/")
def studio_analyze(request: Request, tier: str, column: str, group: str | None = None):
    app = _app()
    tier = tier.lower()
    _validate(app, tier, column)
    result, group, elapsed_ms = _run_analysis(app, tier, column, group)

    error = result["error"] if isinstance(result, dict) and "error" in result else None
    return templates.TemplateResponse(
        request,
        "studio/analyze.html",
        {
            "tier": tier,
            "column": column,
            "group": group,
            "error": error,
            "elapsed_ms": elapsed_ms,
            "result": None if error else _result_rows(result),
            "data": _build_data(),
        },
    )


@router.post("/studio/analyze/{tier}/{column}/save/")
async def studio_save(request: Request, tier: str, column: str):
    app = _app()
    tier = tier.lower()
    _validate(app, tier, column)

    # Parse the form body by hand (a single `group` field) so we don't need the
    # python-multipart dependency just for one hidden input.
    body = (await request.body()).decode("utf-8", "replace")
    group = (parse_qs(body).get("group") or [""])[0] or None

    result, group, elapsed_ms = _run_analysis(app, tier, column, group)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])

    _record_run(tier, column, group, app.DATA_CSV.name, elapsed_ms)
    # 303 so the browser re-fetches with GET -- a refresh won't re-submit the save.
    return RedirectResponse("/studio/runs/", status_code=303)


@router.get("/studio/runs/")
def studio_runs(request: Request):
    return templates.TemplateResponse(request, "studio/runs.html", {"runs": _read_runs()})


@router.get("/guide/")
def studio_guide(request: Request):
    return templates.TemplateResponse(request, "studio/docs.html", {"datasets": _datasets()})
