#!/usr/bin/env bash
# Artifact smoke (gauntlet layer A): verify the INSTALLED kgent exposes the
# full documented surface. Kills the "green suite, stale install" class —
# 2026-09-06: PATH kgent lacked route/journal while the repo suite was green.
#
# Artifact resolution order (printed for the record):
#   1. ~/.local/bin/kgent     — the user-facing installed artifact (uv tool)
#   2. kgent on PATH          — any other installed entry point
# The repo venv copy is deliberately NOT preferred: tests already exercise
# source; this layer exists to exercise what users actually run.
#
# Fail closed: missing binary, manifest missing, or any probe failing → exit 1.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST="$SCRIPT_DIR/surface-manifest.txt"

ARTIFACT=""
for cand in "$HOME/.local/bin/kgent" "$(command -v kgent || true)"; do
  if [ -n "$cand" ] && [ -x "$cand" ]; then
    ARTIFACT="$cand"
    break
  fi
done
if [ -z "$ARTIFACT" ]; then
  echo "artifact-smoke FAILURE: no installed kgent found (~/.local/bin/kgent or PATH)" >&2
  exit 1
fi
echo "artifact under test: $ARTIFACT"

if [ ! -f "$MANIFEST" ]; then
  echo "artifact-smoke FAILURE: manifest missing: $MANIFEST" >&2
  exit 1
fi

FAILED=0
TOTAL=0
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|'#'*) continue ;; esac
  TOTAL=$((TOTAL + 1))
  # shellcheck disable=SC2086 — the manifest is intentionally word-split
  if "$ARTIFACT" $line >/dev/null 2>&1; then
    echo "  ok   kgent $line"
  else
    echo "  FAIL kgent $line"
    FAILED=$((FAILED + 1))
  fi
done < "$MANIFEST"

if [ "$FAILED" -ne 0 ]; then
  echo "artifact-smoke FAILURE: $FAILED/$TOTAL probes failed on $ARTIFACT" >&2
  echo "hint: the installed copy is stale — run 'uv cache clean kgent && uv tool install --force --reinstall --from . kgent' (or bash tools/install-skills.sh) and re-run" >&2
  exit 1
fi
echo "artifact-smoke: $TOTAL/$TOTAL surface probes passed"
