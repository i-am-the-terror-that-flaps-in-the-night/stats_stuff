#!/usr/bin/env python
"""
Boot the service exactly the way Render does and hit every route group.

WHY THIS EXISTS SEPARATELY FROM pytest
    pytest puts Backend/ on sys.path (see pyproject's `pythonpath`), so every
    module there resolves by its bare name -- `import study`, `import app`. The
    deploy does not: Render runs `uvicorn main:app` from the repo root, where the
    same modules only resolve as `Backend.study`, `Backend.app`. The two paths
    exercise different halves of every `try: import x / except ModuleNotFoundError:
    import Backend.x` pair in this codebase, and a bug in the half pytest never
    takes is invisible until the site is live.

    That is not hypothetical. study_api.py originally imported app.py at module
    scope, which closed an import cycle: app.py imports the router at the bottom
    of its own file, so whichever of the two got imported first found the other
    half-built. Under pytest it resolved by the bare name and worked. Under
    `uvicorn main:app` it raised ImportError and took out the study API.

WHY IT RUNS A REAL SERVER
    Importing the app proves the module graph loads. It does not prove a request
    can be served -- a route can register and still 500 on its first call,
    because that is when the lazy pandas/statsmodels imports and the cohort load
    actually happen. So this starts uvicorn on a free port, waits for the health
    probe, and makes real requests.

    It also checks the routes are reachable rather than merely present. Modern
    FastAPI keeps an included router as a single `_IncludedRouter` entry rather
    than flattening its routes into `app.routes`, so counting `app.routes` and
    looking for "/api/study" finds nothing and proves nothing. An HTTP request
    is the only honest test of whether a URL works.

    Run it against a checkout with NO Git LFS objects fetched, which is the state
    a Render deploy is in. If anything reads Data/nhanes_analytic.csv on the
    request path, it fails here rather than in production.

    Usage: python scripts/smoke_test.py
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The fixed routes, checked before the per-column sweep below.
#
# Every client-side route is listed too. They all resolve to the same SPA shell,
# so this is not testing the router -- it is testing that the server's HTML
# fallback covers each one, which is what makes a deep link or a refresh work.
BASE_CHECKS = [
    ("/healthz", "application/json"),
    ("/api/overview", "application/json"),
    ("/api/columns", "application/json"),
    ("/api/datasets", "application/json"),
    ("/api/runs", "application/json"),
    ("/api/cache", "application/json"),
    ("/api/figures/correlation", "application/json"),
    # The study: the slowest and most import-heavy group, pulling in statsmodels
    # and fitting every model in the protocol.
    ("/api/study", "application/json"),
    ("/api/study/headline", "application/json"),
    ("/api/study/steps", "application/json"),
    ("/api/study/cohort", "application/json"),
]

STUDY_STEPS = [
    "cohort",
    "profile",
    "distribution",
    "total-effect",
    "direct-effect",
    "dose-response",
    "mechanism",
    "incremental",
    "sex",
    "risk-score",
    "sensitivity",
]

# Client-side routes. Only meaningful once the frontend is built, so a missing
# bundle downgrades these to skips rather than failures.
SPA_ROUTES = [
    "/",
    "/study",
    "/figures",
    "/methodology",
    "/benchmarks",
    "/changelog",
    "/studio",
    "/studio/experiments",
    "/studio/runs",
    "/guide",
]

NUMERIC_TIERS = ("basic", "medium", "advanced", "expert")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def get(url: str, accept: str, timeout: float = 60.0):
    request = urllib.request.Request(url, headers={"Accept": accept})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read()


def embedded_errors(payload: bytes) -> list[str]:
    """Every "error" key anywhere inside a JSON response body.

    A 200 is not success here. The engine is built to degrade rather than crash:
    a tier that cannot compute a block returns {"error": "..."} for that block
    and 200 for the response, which is the right behaviour for a page that
    should still render its other twelve sections. It also means a status-code
    check passes while the page shows "VIF computation failed" -- which is
    exactly what this script did on the run before this one.

    So the body is walked. Anything carrying an `error` is a failure, wherever it
    is nested.
    """
    try:
        body = json.loads(payload)
    except json.JSONDecodeError, UnicodeDecodeError:
        return []  # HTML (the SPA shell) -- nothing to walk

    found: list[str] = []

    def walk(node, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                where = f"{path}.{key}" if path else key
                if key == "error" and isinstance(value, str):
                    found.append(f"{path or '(root)'}: {value}")
                else:
                    walk(value, where)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(body, "")
    return found


def wait_for_health(
    base: str, server: subprocess.Popen, deadline: float = 90.0
) -> None:
    """Poll /healthz until it answers, failing fast if the process has died.

    Checking the process each time round matters: a server that crashed on
    import would otherwise be waited on for the full timeout, and the error
    reported would be "timed out" rather than the traceback that explains it.
    """
    started = time.monotonic()
    while time.monotonic() - started < deadline:
        if server.poll() is not None:
            raise SystemExit(f"server exited early with code {server.returncode}")
        try:
            get(f"{base}/healthz", "application/json", timeout=2.0)
            return
        except urllib.error.URLError, TimeoutError, ConnectionError, OSError:
            time.sleep(0.4)
    raise SystemExit(f"server did not become healthy within {deadline:.0f}s")


def main() -> int:
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    frontend_built = (ROOT / "frontend" / "dist" / "index.html").is_file()

    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=ROOT,  # the repo root -- the same working directory Render uses
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    failures: list[str] = []
    checked = 0

    def check(path: str, accept: str = "application/json", quiet: bool = False) -> None:
        """Request one URL; record a failure for a bad status OR an embedded error."""
        nonlocal checked
        checked += 1
        try:
            status, payload = get(f"{base}{path}", accept)
        except urllib.error.HTTPError as err:
            failures.append(f"{path} -> HTTP {err.code}")
            print(f"  FAIL {path}  HTTP {err.code}")
            return
        except Exception as err:
            failures.append(f"{path} -> {err}")
            print(f"  FAIL {path}  {err}")
            return

        problems = embedded_errors(payload)
        if status != 200:
            failures.append(f"{path} -> HTTP {status}")
        for problem in problems:
            failures.append(f"{path} -> {problem}")

        if status != 200 or problems:
            print(f"  FAIL {path}  {status}")
            for problem in problems:
                print(f"       {problem[:150]}")
        elif not quiet:
            print(f"  ok   {path}  {status} ({len(payload)} bytes)")

    try:
        wait_for_health(base, server)

        for path, accept in BASE_CHECKS:
            check(path, accept)

        for name in STUDY_STEPS:
            check(f"/api/study/step/{name}")

        # The per-column sweep. The bug this script missed was in
        # "expert · TrigHDLRatio" -- one tier on one column -- so checking a
        # single representative column is not enough. The column list comes from
        # the API rather than being hard-coded, so a new cohort column is
        # covered automatically instead of being silently skipped.
        _, payload = get(f"{base}/api/columns", "application/json")
        columns = json.loads(payload)
        numeric = sorted(columns["columns"])
        categorical = sorted(columns["categorical"])
        print(
            f"\n  sweeping {len(numeric)} numeric x {len(NUMERIC_TIERS)} tiers "
            f"(+{len(categorical)} group-bys on the grouping tiers)…"
        )

        for column in numeric:
            for tier in NUMERIC_TIERS:
                check(f"/api/analyze/{tier}/{column}", quiet=True)
                if tier != "basic":
                    for group in categorical:
                        check(f"/api/analyze/{tier}/{column}?group={group}", quiet=True)
            check(f"/api/figures/histogram/{column}", quiet=True)
            check(f"/api/lab/outliers/{column}", quiet=True)
            check(f"/api/lab/bootstrap/{column}", quiet=True)
            check(f"/api/lab/sample-size/{column}", quiet=True)
            check(f"/api/lab/cohort/{column}", quiet=True)
            for group in categorical:
                check(f"/api/figures/box/{column}?group={group}", quiet=True)

        for column in categorical:
            check(f"/api/analyze/categorical/{column}", quiet=True)
            check(f"/api/lab/screen?group={column}", quiet=True)

        print(
            f"  swept {checked - len(BASE_CHECKS) - len(STUDY_STEPS)} column endpoints"
        )

        if frontend_built:
            print()
            for route in SPA_ROUTES:
                check(route, "text/html")
        else:
            print(f"\n  SKIP {len(SPA_ROUTES)} SPA routes (frontend/dist not built)")
    finally:
        server.terminate()
        try:
            output = server.communicate(timeout=10)[0]
        except subprocess.TimeoutExpired:
            server.kill()
            output = server.communicate()[0]

        if failures:
            # The server log is where the traceback is. Only printed on failure,
            # so a passing run stays readable.
            print("\n--- server log ---")
            print(output)

    if failures:
        print(f"\n{len(failures)} smoke check(s) failed out of {checked}:")
        for failure in failures:
            print(f"  - {failure[:200]}")
        return 1

    print(f"\nAll {checked} smoke checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
