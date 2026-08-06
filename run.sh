#!/bin/bash
# Development launcher.
#
#   ./run.sh          both dev servers, hot reload on each side (the usual one)
#   ./run.sh build    build the frontend, then serve it from FastAPI alone
#
# WHY TWO SERVERS IN DEV
#   The frontend is a Vite app now, so "run the site" means two processes:
#   uvicorn on :8000 holding the API, and Vite on :5173 serving the React app
#   with hot module reload. Vite proxies /api to :8000 (see frontend/vite.config.ts),
#   so the browser only ever talks to :5173 and there is no CORS in the loop.
#
#   Open http://localhost:5173 -- NOT :8000. Port 8000 serves whatever was last
#   built into frontend/dist, which in dev is usually stale or absent.
#
#   `./run.sh build` is the pre-deploy check: it produces the real bundle and
#   serves it exactly the way Render will, from FastAPI at :8000.

set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
  echo "No .venv here. Create it first:  uv sync" >&2
  exit 1
fi
source .venv/bin/activate

UVICORN_ARGS=(
  main:app --reload
  --reload-exclude "__pycache__"
  --reload-exclude ".git"
  --reload-exclude ".pytest_cache"
  --reload-exclude ".ruff_cache"
  --reload-exclude "Data"
  --reload-exclude ".venv"
  # Without this, every Vite rebuild rewrites frontend/dist and kicks uvicorn
  # into a reload loop -- restarting the Python server because a JS file moved.
  --reload-exclude "frontend"
)

if [[ "${1:-}" == "build" ]]; then
  (cd frontend && npm run build)
  echo
  echo "Serving the built bundle at http://127.0.0.1:8000/"
  exec uvicorn "${UVICORN_ARGS[@]}"
fi

if [[ ! -d frontend/node_modules ]]; then
  echo "Installing frontend dependencies..."
  (cd frontend && npm ci)
fi

# Shut both servers down together: on Ctrl-C, and if either one dies on its own.
# A half-running stack (API up, UI down) reads as a bug in the app rather than a
# crashed process, and costs far more time to diagnose than it saves.
#
# Note what is deliberately NOT here: `set -m`. Enabling job control would put
# each server in its own process group, which sounds tidier but breaks the thing
# that matters most -- pressing Ctrl-C in the terminal signals the foreground
# process *group*, so with the children in our group they get SIGINT directly
# from the shell and die whether or not the trap below ever runs. Isolating them
# would leave Ctrl-C hitting only this script. (It also stops trap delivery
# outright on the bash 3.2 that macOS still ships.)
#
# The trap therefore covers the cases the terminal doesn't: one server crashing,
# and `kill` from another shell. Children are killed depth-first, because the
# thing holding the port is usually a grandchild -- `npm run dev` execs vite, and
# uvicorn --reload forks a worker -- so signalling only the PID we launched
# leaves the real server orphaned on the port.
kill_tree() {
  local pid=$1 child
  for child in $(pgrep -P "$pid" 2>/dev/null); do
    kill_tree "$child"
  done
  kill -TERM "$pid" 2>/dev/null || true
}

pids=()
cleanup() {
  trap - EXIT INT TERM
  for pid in "${pids[@]}"; do
    kill_tree "$pid"
  done
  wait 2>/dev/null || true
}

# INT/TERM must exit explicitly. A bash trap handler RESUMES the interrupted code
# when it returns, so without the exit here Ctrl-C would fall back into the watch
# loop below -- and that loop's `kill -0` check still succeeds against the
# just-killed children while they sit unreaped, so it would spin forever instead
# of quitting. EXIT stays a plain cleanup (it is already on the way out).
trap 'cleanup; exit 130' INT TERM
trap cleanup EXIT

uvicorn "${UVICORN_ARGS[@]}" &
pids+=($!)

(cd frontend && npm run dev) &
pids+=($!)

echo
echo "  API  ->  http://127.0.0.1:8000"
echo "  App  ->  http://localhost:5173   <- open this one"
echo

# Return as soon as EITHER process exits, so a crash on one side doesn't leave
# the other running silently. Polling rather than `wait -n` because macOS still
# ships bash 3.2, where that option doesn't exist.
while true; do
  for pid in "${pids[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "A dev server exited -- shutting the other one down." >&2
      exit 1
    fi
  done
  sleep 1
done
