#!/usr/bin/env bash
# Start the local API (127.0.0.1:8765) and the UI dev server (127.0.0.1:5173). UNTESTED on macOS/Linux.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
BASE="${NOISEBOX_HOME:-$HOME/.noisebox}"
( cd "$ROOT/backend" && "$BASE/venv/bin/python" run_server.py ) &
API=$!
( cd "$ROOT/frontend" && npm run dev ) &
UI=$!
trap 'kill $API $UI 2>/dev/null || true' EXIT
sleep 6
( command -v xdg-open >/dev/null && xdg-open http://127.0.0.1:5173/ ) || ( command -v open >/dev/null && open http://127.0.0.1:5173/ ) || true
echo "MATLAB takes about 15 s to start; the status pill turns green when ready. Ctrl+C stops both."
wait
