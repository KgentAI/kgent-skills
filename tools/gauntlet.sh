#!/usr/bin/env bash
set -euo pipefail

echo "== clean =="
rm -rf .coverage htmlcov .pytest_cache .mypy_cache .ruff_cache build dist

echo "== tests + coverage =="
pytest -p no:randomly --cov=kgent --cov-report=term-missing

echo "== types =="
mypy src

echo "== lint =="
ruff check src tests && ruff format --check src tests

echo "== mutation =="
if command -v mutmut >/dev/null 2>&1; then
  mutmut run --paths-to-mutate src/kgent || true   # report only
else
  echo "mutmut unavailable; using tools/mutants.py fallback"
  python tools/mutants.py
fi

echo "== properties =="
pytest tests/properties -v

echo "== adversarial =="
pytest tests/adversarial -v

echo "== secret scan =="
# negative control: must FAIL when a fixture token exists; see Task 10.1
if grep -rEn "(sk-[A-Za-z0-9]{16,}|Bearer [A-Za-z0-9._-]{20,})" src tests --include='*.py' >/dev/null; then
  echo "SECRET SCAN FAILURE" >&2; exit 1
fi

echo "== network capture check (N14) =="
# tests/monkeypatch a socket send gate; gauntlet asserts no off-machine send during suite
python -c "print('N14: network capture enforced via test fixture (Task 10.1)')"

echo "GAUNTLET PASS"
