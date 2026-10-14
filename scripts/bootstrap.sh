#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is required." >&2
  exit 1
fi
PY_MINOR="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)'; then
  echo "ERROR: Python 3.11+ required; found ${PY_MINOR}." >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example. No API key was added."
fi
mkdir -p artifacts

echo
echo "Bootstrap complete. Next:"
echo "  .venv/bin/pytest"
echo "  .venv/bin/resiliant doctor"
echo "  .venv/bin/resiliant demo --hypotheses local"
echo "  .venv/bin/resiliant serve"
