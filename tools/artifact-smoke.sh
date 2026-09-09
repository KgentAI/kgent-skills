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

# Phase 3 (2026-09-09): probes run under a throwaway KGENT_HOME so functional
# (non---help) probe lines can never touch the real ledger or config. The
# journal end --snapshot-after probe IS a real write: journal end on an unknown
# op-id is fail-closed exit 1, so the line only exits 0 against a seeded open
# op. That flag is exactly what a stale pre-Phase-3 artifact lacks — argparse
# rejects it (unrecognized arguments, exit 2 → CLI 1) → probe FAILS, which is
# what layer A must catch. A `--help`-terminated line cannot do this: argparse
# fires the help action before unrecognized-args errors, so both artifacts exit 0.
PROBE_HOME="$(mktemp -d)"
trap 'rm -rf "$PROBE_HOME"' EXIT
export KGENT_HOME="$PROBE_HOME"

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

# Seed one open ledger op only when the manifest needs it ({op_id} placeholder).
SEEDED_OP_ID=""
if grep -q "{op_id}" "$MANIFEST"; then
  if ! begin_json="$("$ARTIFACT" journal begin --operation update --backend wecom \
      --doc-uri kgent://wecom/artifact-smoke-probe --snapshot-content SMOKE-PROBE --json)"; then
    echo "artifact-smoke FAILURE: could not seed a probe ledger op (kgent journal begin)" >&2
    exit 1
  fi
  SEEDED_OP_ID="$(KGENT_PROBE_BEGIN_JSON="$begin_json" python -c \
    "import json,os;print(json.loads(os.environ['KGENT_PROBE_BEGIN_JSON'])['entry']['op_id'])")"
  if [ -z "$SEEDED_OP_ID" ]; then
    echo "artifact-smoke FAILURE: seeded journal begin produced no op_id" >&2
    exit 1
  fi
fi

FAILED=0
TOTAL=0
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|'#'*) continue ;; esac
  if [ -n "$SEEDED_OP_ID" ]; then
    line="${line//\{op_id\}/$SEEDED_OP_ID}"
  fi
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
