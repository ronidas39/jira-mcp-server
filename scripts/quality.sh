#!/usr/bin/env bash
# Run all quality gates. Exit non-zero on any failure.
# Usage: ./scripts/quality.sh

set -euo pipefail

echo "==> ruff check"
ruff check src tests

echo "==> ruff format check"
ruff format --check src tests

echo "==> mypy"
mypy src

echo "==> pytest"
pytest

echo ""
echo "✅ All quality gates passed."
