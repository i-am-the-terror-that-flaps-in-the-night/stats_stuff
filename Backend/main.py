"""
Entry-point alias. The real FastAPI app lives in app.py; this module just
re-exports it so you can start the server as `main:app` as well as `app:app`.

All of these run the same app (the one with /api/columns, /api/stats, etc.):

    cd Backend && uvicorn app:app --reload     # what render.yaml uses
    cd Backend && uvicorn main:app --reload
    uvicorn Backend.app:app --reload           # from the repo root
    uvicorn Backend.main:app --reload          # from the repo root

If you ever see GET / return {"message": "API is alive"} and /api/columns 404,
you're running a stray `app = FastAPI()` stub instead of app.py -- this
re-export exists to stop that from happening.
"""

try:  # launched from inside Backend/
    from app import app
except ModuleNotFoundError:  # launched from the repo root
    from Backend.app import app

__all__ = ["app"]
