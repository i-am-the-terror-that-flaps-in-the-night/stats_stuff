"""
study_api.py -- HTTP access to the ten-step analysis in study.py.

WHY THIS IS A SEPARATE MODULE FROM study.py
    study.py is the science and holds no opinion about HTTP: it returns plain
    dicts, so the tests call it directly and a notebook can import it without
    starting a server. This module is the thin layer that maps those dicts onto
    URLs, validates the one piece of user input there is (a step name), and sets
    cache headers. Keeping them apart means a routing change can never alter a
    published number.

ROUTES
    GET /api/study                  every step in protocol order, plus sensitivity
    GET /api/study/headline         the three numbers the summary card shows
    GET /api/study/steps            the step index -- names, titles, claim grades
    GET /api/study/step/{name}      one step (see study.STEP_NAMES for the names)
    GET /api/study/cohort           the attrition table and the cohort's shape

WHY THE WHOLE STUDY IS ONE ROUTE AS WELL AS ELEVEN
    /api/study is a large response -- every coefficient of every model, with the
    prose that keeps each one honest. It exists anyway because the study is meant
    to be read as a whole and quoted as a whole: one request returns the complete,
    internally consistent set of numbers, which is what a reader checking the
    poster against the site actually wants. The per-step routes are for the UI,
    which renders one section at a time and should not pull the other nine.

    Both are memoized in study.py and gzipped by the app's middleware, so the
    big one costs a few milliseconds and a few KB on the wire after the first
    call.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

router = APIRouter(prefix="/api/study", tags=["study"])


def _cache_control() -> str:
    """app.py's Cache-Control policy for API responses.

    Imported INSIDE the function, not at module scope, and that is load-bearing
    rather than stylistic. app.py imports this module at the bottom of its own
    file to register the router; a module-level `from app import ...` here would
    close that loop, and when study_api happens to be imported first the loop
    resolves to app.py being half-executed and this module's `router` not yet
    existing -- an ImportError naming a circular import, on a line that looks
    completely innocent.

    Deferring it to call time breaks the cycle: by the time any request is
    served, both modules are fully loaded. This is the same pattern studio.py's
    _app() and figures_api use, and for the same reason.
    """
    try:
        from app import API_CACHE_CONTROL
    except ModuleNotFoundError:
        from Backend.app import API_CACHE_CONTROL
    return API_CACHE_CONTROL


def _study():
    """Import study.py lazily.

    Same reason as everywhere else in this app: study.py pulls in statsmodels,
    which is the single slowest import in the dependency set, and Render's free
    plan pays every import on every cold start. A visitor who never opens the
    study page should never pay for statsmodels. See app.py's "SPEED ON RENDER".
    """
    try:
        import study
    except ModuleNotFoundError:
        from Backend import study
    return study


def _cached(response: Response):
    response.headers["Cache-Control"] = _cache_control()


@router.get("")
def whole_study(response: Response):
    """Every step, in protocol order, plus the sensitivity checks."""
    _cached(response)
    return _study().run_study()


@router.get("/headline")
def headline(response: Response):
    """The handful of numbers the summary card needs -- cheap enough to fetch on
    the landing page without pulling the full study."""
    _cached(response)
    return _study().headline()


@router.get("/steps")
def step_index(response: Response):
    """The step list: name, number, title and claim grade, without the results.

    Lets the UI render the table of contents (and the primary/supporting/
    exploratory badges that are the point of the hierarchy) before any model has
    been fitted.
    """
    study = _study()
    _cached(response)
    steps = []
    for name, function in study.STEP_NAMES.items():
        result = study.run_step(name)
        steps.append(
            {
                "name": name,
                "step": result.get("step"),
                "title": result.get("title"),
                "grade": result.get("grade"),
                "question": result.get("question"),
                "n": result.get("n"),
            }
        )
    return {"steps": steps, "hierarchy": study.run_study()["hierarchy"]}


@router.get("/cohort")
def cohort(response: Response):
    """The attrition table -- every rule that decided who is in the study."""
    _cached(response)
    return _study().run_step("cohort")


@router.get("/step/{name}")
def one_step(name: str, response: Response):
    """One step by name. 404 lists the valid names rather than just refusing."""
    study = _study()
    if name not in study.STEP_NAMES:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown step {name!r}. Valid steps: {', '.join(study.STEP_NAMES)}",
        )
    result = study.run_step(name)
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    _cached(response)
    return result
