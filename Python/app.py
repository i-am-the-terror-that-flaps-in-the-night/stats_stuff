"""
app.py -- the ASGI web service that Render runs.

WHY THIS EXISTS
    fastapi was already a declared dependency, but nothing actually defined an
    app or a server entry point, so there was nothing for Render to start. This
    is that entry point: a minimal FastAPI app exposing a health check (for
    Render's health probe) and serving the static preview under Web/.

RUNNING IT
    Locally:   uvicorn app:app --reload          (from this Python/ directory)
    On Render:  see ../render.yaml (rootDir: Python, uvicorn app:app)

ROUTES
    GET /healthz   -> {"status": "ok"}     liveness probe for Render
    GET /          -> redirect to the static preview (or info JSON if absent)
    /web/*         -> the Web/ directory, served as static files
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

# Web/ lives at the repo root, one level up from this file -- resolve it from
# __file__ so the path is correct no matter what the working directory is.
WEB_DIR = Path(__file__).resolve().parent.parent / "Web"
PREVIEW = "/web/HTML/index.html"  # index.html references ../CSS and ../TS

app = FastAPI(title="stats-and-more")


@app.get("/healthz")
def healthz():
    """Liveness probe -- Render hits this to decide if the service is up."""
    return {"status": "ok"}


@app.get("/")
def root():
    """Send visitors to the static preview, falling back to info if it's gone."""
    if WEB_DIR.is_dir():
        return RedirectResponse(PREVIEW)
    return {"service": "stats-and-more", "status": "ok", "preview": None}


# Mount the static frontend last so it can't shadow the routes above. Mounting
# Web/ (not Web/HTML/) at /web keeps the page's ../CSS and ../TS links working.
if WEB_DIR.is_dir():
    app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")
