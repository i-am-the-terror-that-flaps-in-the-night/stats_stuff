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
  # Watch only the Python backend. The default is the whole repo; anything that
  # touches the tree (Vite caches, editor files, a stray save in scripts/) can
  # trigger a reload, and a bad reload takes the reloader down with it.
  --reload-dir Backend
  --reload-exclude "__pycache__"
  --reload-exclude ".git"
  --reload-exclude ".pytest_cache"
  --reload-exclude ".ruff_cache"
  --reload-exclude "Data"
  --reload-exclude ".venv"
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

# Shut both servers down on Ctrl-C (or `kill` on this script). If one server
# crashes on its own, restart it instead of taking the other down with it -- a
# brief Vite hiccup during HMR should not cost a full stack restart.
#
# Note what is deliberately NOT here: `set -m`. Enabling job control would put
# each server in its own process group, which sounds tidier but breaks the thing
# that matters most -- pressing Ctrl-C in the terminal signals the foreground
# process *group*, so with the children in our group they get SIGINT directly
# from the shell and die whether or not the trap below ever runs. Isolating them
# would leave Ctrl-C hitting only this script. (It also stops trap delivery
# outright on the bash 3.2 that macOS still ships.)
#
# Children are killed depth-first, because the thing holding the port is usually
# a grandchild -- uvicorn --reload forks a worker -- so signalling only the PID
# we launched leaves the real server orphaned on the port.
kill_tree() {
  local pid=$1 child
  for child in $(pgrep -P "$pid" 2>/dev/null); do
    kill_tree "$child"
  done
  kill -TERM "$pid" 2>/dev/null || true
}

api_pid=0
app_pid=0
shutting_down=false

cleanup() {
  shutting_down=true
  trap - EXIT INT TERM
  for pid in "$api_pid" "$app_pid"; do
    [[ "$pid" != 0 ]] && kill_tree "$pid"
  done
  wait 2>/dev/null || true
}

start_api() {
  uvicorn "${UVICORN_ARGS[@]}" &
  api_pid=$!
}

start_app() {
  # Run vite directly, not through npm -- one fewer wrapper process, no update
  # notifier, and the PID we track is the server that actually holds :5173.
  (cd frontend && exec ./node_modules/.bin/vite) &
  app_pid=$!
}

# INT/TERM must exit explicitly. A bash trap handler RESUMES the interrupted code
# when it returns, so without the exit here Ctrl-C would fall back into the watch
# loop below instead of quitting.
trap 'cleanup; exit 130' INT TERM
trap cleanup EXIT

start_api
start_app

echo
echo "  API  ->  http://127.0.0.1:8000"
echo "  App  ->  http://localhost:5173   <- open this one"
echo

# Poll rather than `wait -n` because macOS still ships bash 3.2, where that
# option doesn't exist. Restart whichever side died; only Ctrl-C stops both.
while ! $shutting_down; do
  if [[ "$api_pid" != 0 ]] && ! kill -0 "$api_pid" 2>/dev/null; then
    wait "$api_pid" 2>/dev/null || true
    echo "API exited -- restarting..." >&2
    start_api
  fi
  if [[ "$app_pid" != 0 ]] && ! kill -0 "$app_pid" 2>/dev/null; then
    wait "$app_pid" 2>/dev/null || true
    echo "App exited -- restarting..." >&2
    start_app
  fi
  sleep 1
done
