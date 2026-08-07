"""
figures_api.py -- chart-ready aggregates for the frontend's Figures page.

    (Named figures_api rather than figures because the repo root already has a
    `figures/` directory of exported PDFs. Launched from the root -- which is
    how Render runs it -- a top-level `figures` resolves to that directory as a
    namespace package, and the router import fails.)

WHY THIS EXISTS
    engine.py answers questions in *numbers* -- mean, r, p, eta-squared. Those
    are the project's point, but a number cannot show you that BMI is
    right-skewed with a long tail, or that a correlation of 0.31 is a fat cloud
    rather than a line. The four endpoints here return the small, pre-aggregated
    arrays a chart needs, so the browser draws pictures of the same dataset the
    engine reports on.

WHAT THIS IS NOT
    It is not a second statistics engine. Everything here is descriptive
    geometry -- bin counts, quartiles, a least-squares line, a correlation
    matrix. Anything that carries an inferential claim (a p-value, an effect
    size, a confidence interval) stays in engine.py, where it ships with the
    caveats that belong to it. A figure here is allowed to *show* a
    relationship; only the engine is allowed to *characterize* one.

AGGREGATE ON THE SERVER, NOT IN THE BROWSER
    Every route returns tens of numbers, not thousands of rows. The dataset is
    9,254 rows; shipping it to the client to bin it there would mean a ~1 MB
    payload and a re-computation on every render, on a phone. Binning here costs
    one pandas pass, is memoized for the life of the process, and puts ~2 KB of
    JSON on the wire. The single exception is the scatter, which needs real
    points -- so it draws a bounded, deterministic SAMPLE (see _sample_points).

CACHING
    Same contract as the rest of the API: the dataframe is immutable for the
    life of the process, so every answer here is a pure function of its
    arguments and is memoized with lru_cache. Nothing is invalidated because
    nothing can change; a redeploy is what resets it.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, HTTPException, Response

router = APIRouter(prefix="/api/figures", tags=["figures"])

# The scatter is the one route that returns per-row data. 1,500 points is enough
# to read the SHAPE of a cloud (density, curvature, heteroscedasticity) while
# staying a ~25 KB payload that renders as SVG without dropping frames; past a
# few thousand marks the plot is a solid blob anyway and the browser is the only
# thing that notices the difference.
SCATTER_SAMPLE = 1500

# A fixed seed, so the same request returns the same points every time. This is
# not cosmetic: an unseeded sample would make the response uncacheable in any
# honest sense (same URL, different bytes) and would reshuffle the cloud under
# the reader every time they revisited the page.
SCATTER_SEED = 20260806

# Freedman-Diaconis picks the bin width from the IQR and n, which is the right
# default for real, skewed data -- Sturges' rule badly under-bins a long tail.
# The clamp is a readability floor and ceiling, not a statistical one: under ~8
# bars there is no shape left to see, and past ~40 the bars are thinner than the
# gaps between them on a phone.
MIN_BINS, MAX_BINS = 8, 40

# Whiskers use the standard Tukey rule: extend to the furthest observation still
# within 1.5 IQR of the box, and everything beyond is drawn as an outlier count
# rather than as points (at n = 9,254 the outlier marks alone would obscure the
# boxes).
WHISKER_IQR = 1.5

# Below this a "group" is noise -- a handful of rows whose quartiles are not
# meaningful and whose box would still take a full slot on the axis. NHANES's
# Education column carries "Don't know" and "Refused" categories that land here.
MIN_GROUP_N = 30


def _app():
    """Import the sibling app module lazily.

    Same two-path dance as app.py's _load_engine(): this package is imported
    both as `app` (uvicorn app:app from Backend/) and as `Backend.app` (uvicorn
    main:app from the repo root). Deferred to call time to avoid the circular
    import -- app.py includes this router, so this module cannot import it at
    module scope.
    """
    try:
        import app as app_module
    except ModuleNotFoundError:
        from Backend import app as app_module
    return app_module


def _numeric_series(column: str):
    """One column, coerced to numbers, with un-parseable cells dropped.

    Matches engine.py's own coercion rule so a figure is drawn from exactly the
    values the engine reported on -- if the two disagreed about which rows count,
    the picture would quietly contradict the numbers printed beside it.
    """
    import pandas as pd

    app_module = _app()
    if column not in app_module.analyzable_columns():
        raise HTTPException(status_code=404, detail=f"Unknown column: {column!r}")
    series = pd.to_numeric(app_module.load_data()[column], errors="coerce").dropna()
    if series.empty:
        raise HTTPException(status_code=422, detail=f"No numeric values in {column!r}.")
    return series


def _num(value, digits: int = 4):
    """Round for the wire. JSON has no float32, and full doubles trip the payload
    size up by a third for digits no chart can draw."""
    return None if value is None else round(float(value), digits)


@lru_cache(maxsize=None)
def histogram(column: str) -> dict:
    """Bin one column, plus the centre/spread marks a reader needs to place it."""
    import numpy as np

    series = _numeric_series(column)
    values = series.to_numpy(dtype=float)
    n = int(values.size)

    q1, median, q3 = (float(x) for x in np.percentile(values, [25, 50, 75]))
    iqr = q3 - q1
    lo, hi = float(values.min()), float(values.max())

    # Freedman-Diaconis. A degenerate IQR (a column where over half the values
    # are identical) gives a zero width, so fall back to a fixed bin count
    # rather than dividing by zero.
    width = 2 * iqr / (n ** (1 / 3)) if iqr > 0 else 0
    bins = MIN_BINS if width <= 0 else int(np.ceil((hi - lo) / width))
    bins = max(MIN_BINS, min(MAX_BINS, bins))

    counts, edges = np.histogram(values, bins=bins)
    return {
        "column": column,
        "n": n,
        "min": _num(lo),
        "max": _num(hi),
        "mean": _num(values.mean()),
        "median": _num(median),
        "q1": _num(q1),
        "q3": _num(q3),
        "std": _num(values.std(ddof=1)) if n > 1 else None,
        "bins": [
            {"lo": _num(edges[i]), "hi": _num(edges[i + 1]), "count": int(counts[i])}
            for i in range(len(counts))
        ],
    }


@lru_cache(maxsize=None)
def box_plot(column: str, group: str | None) -> dict:
    """Five-number summaries -- one box for the whole column, or one per group.

    Grouped mode is the visual companion to the medium tier's ANOVA: the test
    says whether the groups differ, this shows *how* and by how much, which is
    the part a p-value cannot tell you.
    """
    import numpy as np
    import pandas as pd

    app_module = _app()
    series = _numeric_series(column)

    if group is None:
        pairs = [("All rows", series)]
    else:
        if group not in set(app_module.load_data().columns):
            raise HTTPException(status_code=404, detail=f"Unknown group column: {group!r}")
        frame = pd.DataFrame(
            {"value": series, "group": app_module.load_data()[group]}
        ).dropna()
        pairs = [(str(label), part["value"]) for label, part in frame.groupby("group", sort=True)]

    boxes = []
    dropped = 0
    for label, part in pairs:
        values = part.to_numpy(dtype=float)
        if values.size < MIN_GROUP_N:
            dropped += 1
            continue
        q1, median, q3 = (float(x) for x in np.percentile(values, [25, 50, 75]))
        iqr = q3 - q1
        lo_fence, hi_fence = q1 - WHISKER_IQR * iqr, q3 + WHISKER_IQR * iqr
        inside = values[(values >= lo_fence) & (values <= hi_fence)]
        boxes.append(
            {
                "label": label,
                "n": int(values.size),
                "q1": _num(q1),
                "median": _num(median),
                "q3": _num(q3),
                "mean": _num(values.mean()),
                # The whiskers stop at real observations, not at the fences --
                # a whisker drawn to the fence itself would claim data exists
                # where none was measured.
                "low": _num(inside.min() if inside.size else values.min()),
                "high": _num(inside.max() if inside.size else values.max()),
                "outliers": int(values.size - inside.size),
            }
        )

    if not boxes:
        raise HTTPException(
            status_code=422,
            detail=f"No group of {column!r} by {group!r} has {MIN_GROUP_N}+ values.",
        )
    return {
        "column": column,
        "group": group,
        "boxes": boxes,
        "dropped_groups": dropped,
        "min_group_n": MIN_GROUP_N,
    }


def _sample_points(frame, limit: int):
    """Take at most `limit` rows, deterministically. Returns (frame, sampled?)."""
    if len(frame) <= limit:
        return frame, False
    return frame.sample(n=limit, random_state=SCATTER_SEED), True


@lru_cache(maxsize=None)
def scatter(x: str, y: str) -> dict:
    """A sampled x/y cloud with its least-squares line and Pearson r.

    The line and r are computed on ALL complete pairs, not on the drawn sample --
    the sample is a rendering budget, and letting it move the reported statistic
    would make the figure disagree with the advanced tier for no reason.
    """
    import numpy as np
    import pandas as pd

    app_module = _app()
    numeric = app_module.analyzable_columns()
    for name in (x, y):
        if name not in numeric:
            raise HTTPException(status_code=404, detail=f"Unknown column: {name!r}")
    if x == y:
        raise HTTPException(status_code=422, detail="Pick two different columns.")

    df = app_module.load_data()
    frame = pd.DataFrame(
        {
            "x": pd.to_numeric(df[x], errors="coerce"),
            "y": pd.to_numeric(df[y], errors="coerce"),
        }
    ).dropna()
    if len(frame) < 3:
        raise HTTPException(status_code=422, detail="Too few overlapping values to plot.")

    xs_all = frame["x"].to_numpy(dtype=float)
    ys_all = frame["y"].to_numpy(dtype=float)
    r = float(np.corrcoef(xs_all, ys_all)[0, 1])
    slope, intercept = (float(v) for v in np.polyfit(xs_all, ys_all, 1))

    drawn, sampled = _sample_points(frame, SCATTER_SAMPLE)
    return {
        "x": x,
        "y": y,
        "n": int(len(frame)),
        "drawn": int(len(drawn)),
        "sampled": sampled,
        # Parallel arrays, not [[x, y], ...]: half the JSON punctuation for the
        # same numbers, which on the largest payload here is worth the shape.
        "xs": [_num(v) for v in drawn["x"]],
        "ys": [_num(v) for v in drawn["y"]],
        "r": _num(r),
        "r_squared": _num(r * r),
        "slope": _num(slope, 6),
        "intercept": _num(intercept, 6),
        "x_min": _num(xs_all.min()),
        "x_max": _num(xs_all.max()),
        "y_min": _num(ys_all.min()),
        "y_max": _num(ys_all.max()),
    }


@lru_cache(maxsize=1)
def correlation_matrix() -> dict:
    """Pearson r between every pair of numeric columns, pairwise-complete.

    This is the map that makes the scatter worth opening: it shows which of the
    105 available pairs have anything in them, so a reader picks a pair to look
    at instead of guessing.
    """
    import pandas as pd

    app_module = _app()
    df = app_module.load_data()
    columns = sorted(app_module.analyzable_columns())
    numeric = pd.DataFrame(
        {col: pd.to_numeric(df[col], errors="coerce") for col in columns}
    )
    corr = numeric.corr(method="pearson", min_periods=30)
    return {
        "columns": columns,
        # None, not 0, where a pair has too little overlap: a missing r is not a
        # zero r, and painting it as the neutral midpoint would be a lie the
        # colour scale cannot walk back.
        "matrix": [
            [None if pd.isna(v) else _num(v, 3) for v in corr.loc[row].tolist()]
            for row in columns
        ],
        "method": "pearson",
        "min_overlap": 30,
    }


def _cached(response: Response) -> None:
    """Stamp the shared API Cache-Control on a figure response."""
    response.headers["Cache-Control"] = _app().API_CACHE_CONTROL


@router.get("/histogram/{column}")
def histogram_route(column: str, response: Response):
    """Binned distribution of one numeric column."""
    _cached(response)
    return histogram(column)


@router.get("/box/{column}")
def box_route(column: str, response: Response, group: str | None = None):
    """Five-number summary for one column, optionally split by a label column."""
    _cached(response)
    return box_plot(column, group)


@router.get("/scatter/{x}/{y}")
def scatter_route(x: str, y: str, response: Response):
    """A sampled x/y cloud with its fitted line."""
    _cached(response)
    return scatter(x, y)


@router.get("/correlation")
def correlation_route(response: Response):
    """Pearson r for every pair of numeric columns."""
    _cached(response)
    return correlation_matrix()
