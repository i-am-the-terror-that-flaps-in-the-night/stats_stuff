"""
Deployment entry point at the repo root.

Render's default start command is `uvicorn main:app`, run from the repo root.
This module just re-exports the FastAPI app in Backend/app.py, which owns every
route -- "/", /healthz, /api/*, /Web/*, /docs, and the /studio/ and /guide/
pages (Backend/studio.py, included by app.py). It is a single ASGI app; there is
no dispatcher and no second framework.

    uvicorn main:app --reload                 # from the repo root (this file)
    uvicorn Backend.app:app --reload          # identical -- same app object
    cd Backend && uvicorn app:app --reload    # the README's local instructions
"""

try:
    from Backend.app import app
except ModuleNotFoundError:  # if Backend/ is already on the path
    from app import app  # type: ignore[import-not-found]

__all__ = ["app"]
