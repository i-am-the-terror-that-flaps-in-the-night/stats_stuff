"""
lab_api.py -- the Studio's experiments.

WHY THIS EXISTS
    engine.py answers a question. figures_api.py draws the answer. Neither lets
    you ask "what if?" -- and "what if?" is the part of statistics that is worth
    a science fair. Every route here takes a knob the reader can turn and
    reports what turning it does to the numbers:

      cohort         restrict the rows, watch the summary move
      sample-size    shrink n, watch the confidence interval widen
      bootstrap      resample the data, see where a statistic's uncertainty
                     actually comes from
      outliers       three defensible outlier rules, three different answers
      screen         test everything at once, watch false positives appear

    The last one is the point of the whole page. An engine that reports honest
    p-values one at a time can still be used dishonestly by running it twenty
    times and reporting the winner, so the Studio runs all twenty for you and
    shows what that does.

WHAT THIS IS NOT
    It is not a place where new statistics are invented. Where an experiment
    needs a test, it calls the same scipy routines engine.py calls, so a p-value
    here and a p-value on the Overview are the same p-value.

CACHING -- DIFFERENT RULES FROM THE REST OF THE API
    Everywhere else in this service the cache key space is closed: 15 columns,
    5 tiers, 4 groupings, all validated before they reach a memo, so the caches
    are unbounded and nothing is ever evicted. NOT HERE. These routes take
    free-form input -- filter expressions, sample sizes, seeds -- so the key
    space is as large as the query strings anyone cares to send, and an
    unbounded memo would be a slow memory leak with a URL bar attached. Every
    cache below is therefore BOUNDED, and the bound is the point.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, HTTPException, Query, Response

router = APIRouter(prefix="/api/lab", tags=["lab"])

# Bounded, unlike the rest of the API -- see the CACHING note above. A few
# hundred entries covers every knob position a reader will actually try in a
# session while capping what a scripted caller can pin in memory.
CACHE_SIZE = 192

# Bootstrap draws. 2,000 is the usual floor for a stable 95% percentile interval
# and costs ~30 ms on this dataset; going to 10,000 moves the interval bounds by
# less than the third significant figure and is not worth the wait on a free
# worker.
BOOTSTRAP_DRAWS = 2000

# The sample-size ladder. Doubling steps, because the thing being demonstrated
# -- that the interval narrows with the SQUARE ROOT of n -- is only visible on a
# multiplicative scale. Linear steps make it look like a straight line.
SIZE_LADDER = (25, 50, 100, 200, 400, 800, 1600, 3200)

# How many independent samples to draw at each rung. Enough to show the spread
# of what a study of that size might have concluded, cheap enough to do live.
DRAWS_PER_RUNG = 200

# Every filter operator the cohort builder accepts, longest first so that ">="
# is matched before ">".
OPERATORS = (">=", "<=", "!=", ">", "<", "=")

# A cohort cannot be narrowed past this without the statistics becoming a joke.
# Below 10 rows a mean is an anecdote, and the UI should say so rather than
# print six significant figures of nothing.
MIN_COHORT = 10


def _app():
    """The initialised app.py module, imported lazily (it imports us)."""
    try:
        import app as module
    except ModuleNotFoundError:
        import Backend.app as module
    return module


def _num(value, digits: int = 4):
    """Round for the wire, and turn NaN into null.

    NaN matters here in a way it does not elsewhere: an empty cohort makes every
    statistic NaN, and `float('nan')` is not valid JSON -- it serializes to a
    bare `NaN` token that JSON.parse rejects. Explicit null instead.
    """
    if value is None:
        return None
    value = float(value)
    return None if value != value else round(value, digits)


def _pval(p: float) -> float:
    """Round a p-value to three significant figures, NOT to a fixed number of
    decimal places.

    A p-value spans thirty orders of magnitude on this dataset. `round(p, 6)`
    turns every one below 5e-7 into exactly 0.0, which destroys the ordering the
    multiple-comparison corrections depend on -- and then reads as a claim of
    literal impossibility. Significant figures keep 1.4e-30 as 1.4e-30.
    """
    return float(f"{float(p):.3g}")


def _summary(values) -> dict:
    """The same summary block for every experiment, so two of them can be
    compared without the reader having to align two different vocabularies."""
    import numpy as np

    n = int(values.size)
    if n == 0:
        return {"n": 0, "mean": None, "median": None, "std": None, "min": None, "max": None}
    return {
        "n": n,
        "mean": _num(values.mean()),
        "median": _num(np.median(values)),
        "std": _num(values.std(ddof=1)) if n > 1 else None,
        "min": _num(values.min()),
        "max": _num(values.max()),
    }


# ---------------------------------------------------------------------------
# Cohort filters
# ---------------------------------------------------------------------------

def _parse_filter(expression: str) -> tuple[str, str, str]:
    """Split "Age>=40" into ("Age", ">=", "40").

    A hand-rolled split rather than eval or pandas.query, and deliberately so:
    both of those accept arbitrary expressions, and this string arrives from a
    query parameter. The grammar here is exactly one comparison against one
    literal, and anything else is refused.
    """
    for op in OPERATORS:
        index = expression.find(op)
        if index > 0:
            column = expression[:index].strip()
            value = expression[index + len(op) :].strip()
            if column and value:
                return column, op, value
    raise HTTPException(
        status_code=422,
        detail=f"Could not read filter {expression!r}. Use Column>=Value, Column=Label, etc.",
    )


def _apply_filters(df, filters: tuple[str, ...]):
    """Narrow a dataframe by every filter, returning (frame, descriptions)."""
    import pandas as pd

    app_module = _app()
    numeric = app_module.analyzable_columns()
    known = set(df.columns)
    applied = []

    for expression in filters:
        column, op, raw = _parse_filter(expression)
        if column not in known:
            raise HTTPException(status_code=404, detail=f"Unknown column: {column!r}")

        if column in numeric:
            try:
                value = float(raw)
            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail=f"{column!r} is numeric, so {raw!r} is not a value it can be compared to.",
                ) from None
            series = pd.to_numeric(df[column], errors="coerce")
        else:
            if op not in ("=", "!="):
                raise HTTPException(
                    status_code=422,
                    detail=f"{column!r} is a label column, so only = and != apply (got {op!r}).",
                )
            value = raw
            series = df[column].astype(str)

        if op == ">=":
            mask = series >= value
        elif op == "<=":
            mask = series <= value
        elif op == ">":
            mask = series > value
        elif op == "<":
            mask = series < value
        elif op == "!=":
            mask = series != value
        else:
            mask = series == value

        # A comparison against NaN is False in pandas, which is what we want --
        # a row with no value for the filtered column is not evidence that it
        # passes, so it drops out.
        df = df[mask.fillna(False)]
        applied.append({"column": column, "op": op, "value": raw, "remaining": int(len(df))})

    return df, applied


@lru_cache(maxsize=CACHE_SIZE)
def cohort(column: str, filters: tuple[str, ...]) -> dict:
    """Summarize one column over a filtered subset, beside the whole dataset.

    Both halves are returned together on purpose. A cohort mean means nothing on
    its own -- "BMI is 31.2 in this group" is only interesting next to "and 26.6
    overall" -- and putting the comparison in the payload stops the UI from
    having to make two requests and hope they agree.
    """
    import pandas as pd

    app_module = _app()
    if column not in app_module.analyzable_columns():
        raise HTTPException(status_code=404, detail=f"Unknown column: {column!r}")

    df = app_module.load_data()
    total_rows = int(len(df))
    subset, applied = _apply_filters(df, filters)

    everything = pd.to_numeric(df[column], errors="coerce").dropna().to_numpy(dtype=float)
    narrowed = pd.to_numeric(subset[column], errors="coerce").dropna().to_numpy(dtype=float)

    overall = _summary(everything)
    inside = _summary(narrowed)

    # The headline number: how far the cohort's mean sits from the whole
    # dataset's, in standard deviations. Reported as a distance rather than as a
    # test, because a filter chosen after looking at the data is not a hypothesis
    # and running a p-value on it would dress up a fishing expedition.
    shift = None
    if inside["mean"] is not None and overall["mean"] is not None and overall["std"]:
        shift = _num((inside["mean"] - overall["mean"]) / overall["std"], 3)

    return {
        "column": column,
        "filters": applied,
        "rows_total": total_rows,
        "rows_kept": int(len(subset)),
        "kept_share": _num(len(subset) / total_rows, 4) if total_rows else None,
        "cohort": inside,
        "overall": overall,
        "shift_in_sds": shift,
        "too_small": inside["n"] < MIN_COHORT,
        "min_cohort": MIN_COHORT,
    }


# ---------------------------------------------------------------------------
# Sample size
# ---------------------------------------------------------------------------

@lru_cache(maxsize=CACHE_SIZE)
def sample_size(column: str, seed: int) -> dict:
    """What a study of size n would have concluded, for a ladder of n.

    At each rung this draws DRAWS_PER_RUNG independent samples and reports the
    middle 95% of their means. That band is the honest answer to "how much does
    my result depend on who happened to be in the study" -- and it is the same
    quantity a confidence interval estimates from a single sample, arrived at by
    brute force instead of by formula, which is why the two agree.
    """
    import numpy as np

    app_module = _app()
    if column not in app_module.analyzable_columns():
        raise HTTPException(status_code=404, detail=f"Unknown column: {column!r}")

    import pandas as pd

    values = (
        pd.to_numeric(app_module.load_data()[column], errors="coerce")
        .dropna()
        .to_numpy(dtype=float)
    )
    population_mean = float(values.mean())
    rng = np.random.default_rng(seed)

    rungs = []
    for n in SIZE_LADDER:
        if n > values.size:
            break
        # Sampling WITH replacement, so a rung near the full dataset size is
        # still a random draw rather than "almost all of it" -- otherwise the
        # last rung would collapse to the population mean for the wrong reason.
        draws = rng.choice(values, size=(DRAWS_PER_RUNG, n), replace=True)
        means = draws.mean(axis=1)
        lo, hi = (float(x) for x in np.percentile(means, [2.5, 97.5]))
        rungs.append(
            {
                "n": n,
                "mean_of_means": _num(means.mean()),
                "lo": _num(lo),
                "hi": _num(hi),
                "width": _num(hi - lo),
                # The share of samples this size that land more than 1% away
                # from the truth -- the "how often would I have been wrong"
                # number, which lands harder than an interval width.
                "miss_rate": _num(
                    float(np.mean(np.abs(means - population_mean) > abs(population_mean) * 0.01)), 3
                ),
            }
        )

    return {
        "column": column,
        "seed": seed,
        "population_n": int(values.size),
        "population_mean": _num(population_mean),
        "draws_per_rung": DRAWS_PER_RUNG,
        "rungs": rungs,
    }


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

STATISTICS = ("mean", "median", "std")


@lru_cache(maxsize=CACHE_SIZE)
def bootstrap(column: str, statistic: str, seed: int) -> dict:
    """The sampling distribution of one statistic, by resampling.

    Draw a new dataset the same size as the real one, with replacement, compute
    the statistic, repeat. The spread of the results is the uncertainty. This is
    the experiment that makes a confidence interval stop being a formula: the
    histogram it returns IS the interval, drawn.
    """
    import numpy as np
    import pandas as pd

    app_module = _app()
    if column not in app_module.analyzable_columns():
        raise HTTPException(status_code=404, detail=f"Unknown column: {column!r}")
    if statistic not in STATISTICS:
        raise HTTPException(
            status_code=422, detail=f"Unknown statistic: {statistic!r}. Pick one of {STATISTICS}."
        )

    values = (
        pd.to_numeric(app_module.load_data()[column], errors="coerce")
        .dropna()
        .to_numpy(dtype=float)
    )
    n = int(values.size)
    if n < 2:
        raise HTTPException(status_code=422, detail="Too few values to resample.")

    rng = np.random.default_rng(seed)
    draws = rng.choice(values, size=(BOOTSTRAP_DRAWS, n), replace=True)
    if statistic == "mean":
        stats = draws.mean(axis=1)
        observed = float(values.mean())
    elif statistic == "median":
        stats = np.median(draws, axis=1)
        observed = float(np.median(values))
    else:
        stats = draws.std(axis=1, ddof=1)
        observed = float(values.std(ddof=1))

    lo, hi = (float(x) for x in np.percentile(stats, [2.5, 97.5]))
    counts, edges = np.histogram(stats, bins=32)

    return {
        "column": column,
        "statistic": statistic,
        "seed": seed,
        "n": n,
        "draws": BOOTSTRAP_DRAWS,
        "observed": _num(observed),
        "ci_lower": _num(lo),
        "ci_upper": _num(hi),
        "std_error": _num(stats.std(ddof=1)),
        "bins": [
            {"lo": _num(edges[i]), "hi": _num(edges[i + 1]), "count": int(counts[i])}
            for i in range(len(counts))
        ],
    }


# ---------------------------------------------------------------------------
# Outlier rules
# ---------------------------------------------------------------------------

RULES = ("keep", "z3", "iqr", "winsorize")

RULE_BLURB = {
    "keep": "Every value, untouched.",
    "z3": "Drop anything more than 3 standard deviations from the mean.",
    "iqr": "Drop anything more than 1.5 × IQR outside the quartiles.",
    "winsorize": "Pull anything outside 1.5 × IQR back to the fence instead of dropping it.",
}


@lru_cache(maxsize=CACHE_SIZE)
def outlier_rules(column: str) -> dict:
    """The same column under four defensible outlier policies.

    None of these is wrong, and they disagree. That is the finding: a summary
    statistic is a claim about the data PLUS a judgement call about what counts
    as data, and papers rarely report the second half. Running all four side by
    side puts the size of that judgement in numbers.
    """
    import numpy as np
    import pandas as pd

    app_module = _app()
    if column not in app_module.analyzable_columns():
        raise HTTPException(status_code=404, detail=f"Unknown column: {column!r}")

    values = (
        pd.to_numeric(app_module.load_data()[column], errors="coerce")
        .dropna()
        .to_numpy(dtype=float)
    )
    if values.size < 4:
        raise HTTPException(status_code=422, detail="Too few values to compare outlier rules.")

    q1, q3 = (float(x) for x in np.percentile(values, [25, 75]))
    iqr = q3 - q1
    lo_fence, hi_fence = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    mean, std = float(values.mean()), float(values.std(ddof=1))

    variants = {
        "keep": values,
        "z3": values[np.abs(values - mean) <= 3 * std] if std > 0 else values,
        "iqr": values[(values >= lo_fence) & (values <= hi_fence)],
        "winsorize": np.clip(values, lo_fence, hi_fence),
    }

    baseline = _summary(values)
    results = []
    for rule in RULES:
        kept = variants[rule]
        summary = _summary(kept)
        results.append(
            {
                "rule": rule,
                "blurb": RULE_BLURB[rule],
                # Winsorizing changes values without removing rows, so "removed"
                # is genuinely 0 there -- which is exactly the trade it makes.
                "removed": int(values.size - kept.size),
                "removed_share": _num((values.size - kept.size) / values.size, 4),
                **summary,
                "mean_shift": _num((summary["mean"] or 0) - (baseline["mean"] or 0), 4),
                "std_shift": _num((summary["std"] or 0) - (baseline["std"] or 0), 4),
            }
        )

    return {
        "column": column,
        "fences": [_num(lo_fence), _num(hi_fence)],
        "results": results,
    }


# ---------------------------------------------------------------------------
# Multiple comparisons
# ---------------------------------------------------------------------------

@lru_cache(maxsize=CACHE_SIZE)
def screen(group: str, alpha: float) -> dict:
    """Test every numeric column against one grouping, then correct for it.

    The demonstration this page exists for. Testing 15 columns at alpha = 0.05
    means that even if NOTHING differed between the groups, you would expect
    about one "significant" result -- and the temptation is to report that one.

    Two corrections are shown because they answer different questions.
    Bonferroni controls the chance of ANY false positive and is brutal.
    Benjamini-Hochberg controls the expected SHARE of the findings that are
    false and is what most modern papers use. Neither is a formality: on this
    dataset they usually disagree about at least one column, and that column is
    the most interesting row in the table.
    """
    import numpy as np
    import pandas as pd
    import scipy.stats as sp

    app_module = _app()
    df = app_module.load_data()
    if group not in app_module.categorical_columns():
        raise HTTPException(status_code=404, detail=f"Unknown group column: {group!r}")
    if not 0 < alpha < 1:
        raise HTTPException(status_code=422, detail="alpha must be between 0 and 1.")

    columns = sorted(app_module.analyzable_columns())
    tests = []
    for column in columns:
        frame = pd.DataFrame(
            {"value": pd.to_numeric(df[column], errors="coerce"), "group": df[group]}
        ).dropna()
        parts = [
            part["value"].to_numpy(dtype=float)
            for _, part in frame.groupby("group", sort=True)
            if len(part) >= 2
        ]
        if len(parts) < 2:
            continue
        f_statistic, p_value = sp.f_oneway(*parts)
        if p_value != p_value:  # NaN -- zero variance within every group
            continue

        # eta-squared: the share of total variation that lies between groups.
        # Carried alongside every p-value for the same reason engine.py carries
        # it -- at n = 9,254 a p-value of 0.0 can sit on an effect of nothing.
        grand = frame["value"].to_numpy(dtype=float)
        ss_total = float(((grand - grand.mean()) ** 2).sum())
        ss_between = float(sum(len(p) * (p.mean() - grand.mean()) ** 2 for p in parts))
        eta_squared = ss_between / ss_total if ss_total > 0 else 0.0

        tests.append(
            {
                "column": column,
                "p_value": _pval(p_value),
                "f_statistic": _num(f_statistic, 3),
                "eta_squared": _num(eta_squared, 4),
                "n": int(len(frame)),
                "groups": len(parts),
            }
        )

    m = len(tests)
    # NEVER `test["p_value"] or 1.0` here. A real p-value of 0.0 is falsy, so
    # that idiom silently rewrites the strongest results in the table as the
    # weakest -- they sort last and come out "not significant". Read the number.
    def p_of(index: int) -> float:
        return float(tests[index]["p_value"])

    order = sorted(range(m), key=p_of)

    # Benjamini-Hochberg: walk the p-values from largest to smallest and take
    # everything at or below the first one that clears its rank threshold. The
    # backwards walk is what makes it a step-UP procedure -- checking each
    # p-value independently against its own threshold is a different, wrong
    # test that rejects too little.
    bh_cutoff_rank = 0
    for rank in range(m, 0, -1):
        if p_of(order[rank - 1]) <= alpha * rank / m:
            bh_cutoff_rank = rank
            break

    bonferroni_alpha = alpha / m if m else alpha
    for rank, index in enumerate(order, start=1):
        test = tests[index]
        p = p_of(index)
        test["rank"] = rank
        test["raw"] = p <= alpha
        test["bonferroni"] = p <= bonferroni_alpha
        test["benjamini_hochberg"] = rank <= bh_cutoff_rank
        test["bh_threshold"] = _num(alpha * rank / m, 6) if m else None

    tests.sort(key=lambda t: t["rank"])
    counts = {
        "raw": sum(1 for t in tests if t["raw"]),
        "bonferroni": sum(1 for t in tests if t["bonferroni"]),
        "benjamini_hochberg": sum(1 for t in tests if t["benjamini_hochberg"]),
    }

    return {
        "group": group,
        "alpha": alpha,
        "tests_run": m,
        # What you would expect to "find" if every one of these columns were
        # genuinely unrelated to the grouping. The number that makes the raw
        # count above readable.
        "false_positives_expected": _num(alpha * m, 2),
        "bonferroni_alpha": _num(bonferroni_alpha, 6),
        "counts": counts,
        "tests": tests,
        "not_causal": (
            "These are associations in observational data, screened in bulk. A column that "
            "survives correction is worth looking at next -- it is not a finding on its own."
        ),
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _cached(response: Response) -> None:
    response.headers["Cache-Control"] = _app().API_CACHE_CONTROL


@router.get("/cohort/{column}")
def cohort_route(
    column: str,
    response: Response,
    f: list[str] = Query(default=[], description="Filter, e.g. Age>=40 or Gender=Female"),
):
    """One column summarized over a filtered cohort, beside the whole dataset."""
    _cached(response)
    return cohort(column, tuple(f))


@router.get("/sample-size/{column}")
def sample_size_route(column: str, response: Response, seed: int = 1):
    """How much a result depends on how many people were in the study."""
    _cached(response)
    return sample_size(column, seed)


@router.get("/bootstrap/{column}")
def bootstrap_route(column: str, response: Response, statistic: str = "mean", seed: int = 1):
    """The sampling distribution of one statistic, by resampling."""
    _cached(response)
    return bootstrap(column, statistic, seed)


@router.get("/outliers/{column}")
def outliers_route(column: str, response: Response):
    """One column under four different outlier policies."""
    _cached(response)
    return outlier_rules(column)


@router.get("/screen")
def screen_route(response: Response, group: str, alpha: float = 0.05):
    """Every numeric column tested against one grouping, then corrected."""
    _cached(response)
    return screen(group, alpha)
