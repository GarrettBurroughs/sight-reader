#!/usr/bin/env bash
# Start the API server (port 8000, local only) and the web dev server (port 5173, on the network).
# Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")"
server/.venv/bin/uvicorn app:create_app --factory --app-dir server --host 127.0.0.1 --port 8000 --reload --reload-dir server &
api=$!
trap 'kill $api 2>/dev/null' EXIT
cd web && npm run dev
