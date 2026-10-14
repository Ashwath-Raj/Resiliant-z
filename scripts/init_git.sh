#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -e .git ]]; then
  echo "A Git repository already exists at: $ROOT"
  git status --short --branch
  exit 0
fi
git init -b main
echo "Initialized Git in: $ROOT"
echo "Review files and Docs/, then run:"
echo "  git status --short"
echo "  git add -A"
echo "  git commit -m 'chore: scaffold reproducible RESILIANT-Z benchmark'"
echo "If Git identity is missing, configure it locally with git config user.name and git config user.email."
