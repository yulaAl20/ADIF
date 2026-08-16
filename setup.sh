#!/usr/bin/env bash
# ADIF setup — Linux / macOS. Run from the repository root:
#     bash setup.sh
set -euo pipefail

echo; echo "ADIF setup"; printf '=%.0s' {1..60}; echo

[ -f requirements.txt ] || {
  echo "ERROR: run this from the repository root."
  echo "You should see README.md, requirements.txt and src/ here."
  echo "Current folder: $(pwd)"; exit 1; }

PY=""
for v in python3.12 python3.11 python3; do
  if command -v "$v" >/dev/null 2>&1; then
    if "$v" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] in {(3,11),(3,12)} else 1)'; then
      PY="$v"; break
    fi
  fi
done
[ -n "$PY" ] || { echo "ERROR: Python 3.11 or 3.12 not found."; exit 1; }
echo; echo "Using $PY ($($PY --version))"

[ -d .venv ] && echo "Virtual environment exists — reusing it." || { echo "Creating virtual environment..."; "$PY" -m venv .venv; }

echo "Installing dependencies..."
.venv/bin/python -m pip install --upgrade pip --quiet
.venv/bin/python -m pip install -r requirements.txt --quiet

echo; echo "Running tests..."
.venv/bin/python -m pytest -q

printf '=%.0s' {1..60}; echo
cat <<'MSG'
Setup complete.

Activate the environment:
    source .venv/bin/activate

Then try:
    python -m scripts.check_environment
    python -m scripts.demo
    uvicorn src.api.main:app --reload      then open http://127.0.0.1:8000/review
MSG
