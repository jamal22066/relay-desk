#!/usr/bin/env bash
# Dependency CVE scan. pip-audit is installed via pipx, so it must be pointed
# at the project venv explicitly or it audits its own environment instead.
set -e
cd "$(dirname "$0")/.."
echo "== python =="
PIPAPI_PYTHON_LOCATION="$(pwd)/.venv/bin/python" pip-audit
echo
echo "== javascript =="
(cd web && npm audit)
echo
echo "== static analysis =="
semgrep --config=p/default --config=p/security-audit --config=p/react --config=p/python --quiet .
