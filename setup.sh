#!/usr/bin/env bash
# One-time setup for macOS / Linux. UNTESTED: written from the Windows steps; adjust MATLAB_ROOT and PYTHON.
# Requires MATLAB with the Engine API for Python, a supported Python (R2023a: 3.8-3.10) and Node.js.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
BASE="${NOISEBOX_HOME:-$HOME/.noisebox}"
MATLAB_ROOT="${NOISEBOX_MATLAB_ROOT:?set NOISEBOX_MATLAB_ROOT to your MATLAB folder, e.g. /Applications/MATLAB_R2023a.app}"
PYTHON="${PYTHON:-python3.10}"

mkdir -p "$BASE"
[ -d "$BASE/venv" ] || "$PYTHON" -m venv "$BASE/venv"
"$BASE/venv/bin/pip" install --upgrade pip
"$BASE/venv/bin/pip" install -r "$ROOT/backend/requirements.txt"

# The Engine must be built from its own folder (pip install of the folder fails).
( cd "$MATLAB_ROOT/extern/engines/python" && "$BASE/venv/bin/python" setup.py build --build-base="$BASE/engbuild" install )
"$BASE/venv/bin/python" -c "import matlab.engine; print('MATLAB Engine import OK')"

# node_modules outside the synced folder; the directory must be named node_modules
mkdir -p "$BASE/fe/node_modules"
[ -e "$ROOT/frontend/node_modules" ] || ln -s "$BASE/fe/node_modules" "$ROOT/frontend/node_modules"
( cd "$ROOT/frontend" && npm install --no-audit --no-fund )
echo "Setup complete. Run ./start.sh"
