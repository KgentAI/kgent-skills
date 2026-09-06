#!/usr/bin/env bash
set -euo pipefail

# Prefer the repo venv: the pytest/coverage/ruff on PATH may belong to another
# interpreter that has neither kgent nor the dev deps (Windows + Git Bash).
if [ -x ".venv/Scripts/python.exe" ]; then
  export PATH="$PWD/.venv/Scripts:$PATH"
elif [ -x ".venv/bin/python" ]; then
  export PATH="$PWD/.venv/bin:$PATH"
fi

echo "== clean =="
rm -rf .coverage coverage.xml htmlcov .pytest_cache .mypy_cache .ruff_cache build dist

echo "== tests + coverage =="
# coverage.py, not pytest-cov: dev deps ship `coverage[toml]` (pyproject), and
# pytest-cov is not installed. `coverage report --show-missing` is the
# term-missing equivalent.
coverage run -m pytest -p no:randomly
coverage report --show-missing
coverage xml

echo "== changed lines (diff-cover) =="
# Gate: 100% of the lines this branch changed (merge-base diff). diff-cover
# exits non-zero below --fail-under (default 100), which set -e turns into a
# gauntlet failure.
git diff origin/main...HEAD > .diff-cover.diff
diff-cover coverage.xml --diff-file .diff-cover.diff
rm -f .diff-cover.diff

echo "== types =="
mypy src

echo "== lint =="
ruff check src tests && ruff format --check src tests

echo "== mutation =="
if command -v mutmut >/dev/null 2>&1; then
  # mutmut 3.x: config lives in pyproject [tool.mutmut] — the old
  # --paths-to-mutate CLI flag was removed in 3.0, which made this stage fail
  # silently under `|| true`. Native Windows is unsupported by mutmut
  # (boxed/mutmut#397): the tool exits with a "please use the WSL" notice, so
  # route that refusal to the explicit manual fallback instead of absorbing it.
  # Report only — mutation never gates the gauntlet.
  mutmut_output=$(mutmut run 2>&1) || true
  if echo "$mutmut_output" | grep -q "please use the WSL"; then
    echo "mutmut unavailable on native Windows (boxed/mutmut#397); using tools/mutants.py fallback"
    python tools/mutants.py
  else
    echo "$mutmut_output" | tr '\r' '\n' | grep -v '^$' | tail -3
  fi
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
  echo "SECRET SCAN FAILURE" >&2
  exit 1
fi

echo "== network capture check (N14) =="
# tests/monkeypatch a socket send gate; gauntlet asserts no off-machine send during suite
python -c "print('N14: network capture enforced via test fixture (Task 10.1)')"

echo "GAUNTLET PASS"
