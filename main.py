"""
Deployment entry point at the repo root.

Render's default start command is `uvicorn main:app`, run from the repo root.
The real app lives in Backend/app.py -- this module just re-exports it, so that
default command resolves without any extra Render dashboard configuration.

These all start the same app:

    uvicorn main:app --reload                 # from the repo root (this file)
    uvicorn Backend.app:app --reload          # from the repo root
    cd Backend && uvicorn app:app --reload    # the README's local instructions
"""

try:
    from Backend.app import app
except ModuleNotFoundError:  # if Backend/ is already on the path
    from app import app

__all__ = ["app"]
