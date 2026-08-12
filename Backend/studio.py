"""
studio.py -- JSON endpoints backing the Studio pages.

WHY THIS EXISTS
    The Studio used to be server-rendered Jinja: this module built HTML tables and
    bar widths in Python. The frontend is now a React + TypeScript app (frontend/),
    so presentation moved to the client and this module kept only what the client
    genuinely cannot compute for itself -- the dataset inventory (a filesystem
    question) and the saved-run log (a SQLite question).

    It still calls app.py's *own* cached functions directly -- same process, same
    memory -- so a request never makes a second HTTP hop. It's mounted by app.py
    (app.include_router) at the very bottom of that file, after every cached
    helper is defined, because we call back into it (see WHY THE IMPORTS ARE LAZY).

WHAT IT SERVES
    GET  /api/datasets   the dataset inventory, each with a live `available` flag
    GET  /api/runs       the saved-run log, newest first (?limit=N to cap it)
    POST /api/runs       append a run to the log, returns the stored row

    The analysis itself is /api/analyze/{tier}/{column} in app.py -- the Studio
    and the dashboard now share exactly one analysis endpoint instead of having
    a rendered twin each.

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
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA_DIR = ROOT / "Data"
RUNS_DB = HERE / "studio_runs.db"  # local lab-notebook; gitignored, not deployed

router = APIRouter()

# Datasets shown on the index and the guide, in provenance order: the cohort the
# engine runs on, the raw merge it was derived from, then the leftovers.
# Availability is derived from the filesystem, never hard-coded.
#
# nhanes_analytic.csv is tracked in Git LFS, so in a deployed checkout it is
# usually present as a small pointer file rather than the real 17 MB export.
# That is the expected online state and nothing at runtime needs it -- see
# _dataset_status, which tells the two apart instead of reporting a 130-byte
# pointer as a full dataset.
DATASETS = (
    {
        "file": "nhanes_adolescent.csv",
        "blurb": "The study's analytic cohort -- U.S. adolescents aged 12-17. What the live engine runs on.",
    },
    {
        "file": "nhanes_analytic.csv",
        "blurb": "Full raw NHANES 2017-2018 merge (412 columns) the cohort is derived from. Git LFS.",
    },
    {
        "file": "nhanes.csv",
        "blurb": "Earlier curated 18-column NHANES slice, superseded by the cohort. Kept for reference.",
    },
    {
        "file": "data.csv",
        "blurb": "Small synthetic practice dataset, kept for quick local testing.",
    },
    {
        "file": "trial_full.csv",
        "blurb": "Full research export -- stays on the lab machine.",
    },
    {
        "file": "followup.csv",
        "blurb": "Follow-up measurements -- stays on the lab machine.",
    },
)

# A Git LFS pointer is a short text stub standing in for the real file. They are
# well under a kilobyte; every real dataset here is far larger. Sizing is enough
# to tell them apart and costs one stat() call.
LFS_POINTER_MAX_BYTES = 1024


def _app():
    """The initialised app.py module. Imported lazily to dodge the circular
    import (app.py imports us) and to work from either launch directory."""
    try:
        import app as module
    except ModuleNotFoundError:
        import Backend.app as module
    return module


# ----------------------------------------------------------------------------
# Dataset inventory
# ----------------------------------------------------------------------------


def _dataset_status(path):
    """Whether a dataset is really here, really absent, or an unfetched LFS stub.

    Three states rather than two, because `is_file()` cannot tell a 17 MB CSV
    from the 130-byte pointer Git LFS leaves in its place. Reporting the stub as
    "available" would send a reader to rebuild the cohort from a file that holds
    an object hash and nothing else, and the error they would get back names
    neither LFS nor the fix.
    """
    if not path.is_file():
        return {"available": False, "state": "absent"}
    size = path.stat().st_size
    if size <= LFS_POINTER_MAX_BYTES:
        return {
            "available": False,
            "state": "lfs-pointer",
            "hint": "Tracked in Git LFS but not fetched here -- run `git lfs pull`.",
        }
    return {"available": True, "state": "present", "bytes": size}


def _datasets():
    """DATASETS with a live availability flag read off the filesystem."""
    return [
        {
            "label": d["file"],
            "blurb": d["blurb"],
            **_dataset_status(DATA_DIR / d["file"]),
        }
        for d in DATASETS
    ]


def _validate(app, tier: str, column: str):
    """Resolve and validate (tier, column) the same way app.analyze_column does.
    Raises HTTPException on a bad tier or column; returns nothing on success."""
    if tier not in app.NUMERIC_TIERS and tier != "categorical":
        raise HTTPException(status_code=404, detail=f"Unknown tier: {tier!r}")
    valid = (
        app.analyzable_columns()
        if tier in app.NUMERIC_TIERS
        else app.categorical_columns()
    )
    if column not in valid:
        raise HTTPException(status_code=404, detail=f"Unknown column: {column!r}")


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


def _record_run(
    tier: str, column: str, group: str | None, dataset: str, duration_ms: int
) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO runs (ts, tier, column, group_col, dataset, duration_ms) VALUES (?, ?, ?, ?, ?, ?)",
            (
                datetime.now().isoformat(timespec="seconds"),
                tier,
                column,
                group,
                dataset,
                duration_ms,
            ),
        )


def _read_runs(limit: int | None = None):
    with _connect() as conn:
        sql = "SELECT * FROM runs ORDER BY id DESC"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        return [_run_view(row) for row in conn.execute(sql).fetchall()]


def _run_view(row: sqlite3.Row) -> dict:
    """Shape one DB row for the client, with both short and long timestamps."""
    try:
        stamp = datetime.fromisoformat(row["ts"])
        when_short = stamp.strftime("%m-%d %H:%M")
        when_long = stamp.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:  # unparseable timestamp -- show it raw rather than crash
        when_short = when_long = row["ts"]
    return {
        "id": row["id"],
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


class RunIn(BaseModel):
    """A run the client asks us to log. The duration is the client's measured
    round trip; the dataset is filled in server-side so a caller can't misreport
    which file the numbers came from."""

    tier: str
    column: str
    group: str | None = None
    duration_ms: int = Field(ge=0)


@router.get("/api/datasets")
def list_datasets():
    """The dataset inventory with a live availability flag.

    Availability is a filesystem fact the browser can't see, which is why this
    stays on the server: the raw NHANES export and the larger research files are
    deliberately absent online, and the UI says so rather than pretending.
    """
    return _datasets()


@router.get("/api/runs")
def list_runs(limit: int | None = None):
    """The saved-run log, newest first."""
    if limit is not None and limit <= 0:
        raise HTTPException(status_code=422, detail="limit must be positive")
    return _read_runs(limit=limit)


@router.post("/api/runs", status_code=201)
def create_run(run: RunIn):
    """Append a run to the log.

    The (tier, column) pair is validated the same way /api/analyze validates it,
    so the log can't accumulate rows for analyses that could never have run.
    """
    app = _app()
    tier = run.tier.lower()
    _validate(app, tier, run.column)

    group = run.group if tier in ("medium", "advanced", "expert") else None
    if group and group not in set(app.load_data().columns):
        group = None

    _record_run(tier, run.column, group, app.DATA_CSV.name, run.duration_ms)
    latest = _read_runs(limit=1)
    if not latest:  # pragma: no cover -- the insert above just succeeded
        raise HTTPException(status_code=500, detail="Run was not stored")
    return latest[0]
