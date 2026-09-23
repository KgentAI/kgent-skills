#!/usr/bin/env bash
set -uo pipefail

# Confluence A1 probe (spec 2026-09-22 / ADR 0015): verify the official acli's
# Confluence surface against the adapter's REQUIRED contract before any e2e
# claim. NOT part of the default gauntlet — real-tenant, opt-in:
#
#   CONFLUENCE_SANDBOX_SPACE=<spaceKey> bash tools/confluence-probe.sh
#
# Prereqs: acli installed AND authenticated (`acli confluence auth login` or
# equivalent); a sandbox space you own; nothing else. The probe creates ONE
# page in the sandbox space and deletes it at the end (trash, restorable).
# Exit 0 = all legs passed; exit 1 = a leg failed (name it in the output);
# exit 0 with SKIP lines = prereqs absent (never a silent skip).

FAILURES=0

die() { echo "PROBE FAIL: $*" >&2; FAILURES=$((FAILURES + 1)); }
note() { echo "PROBE: $*"; }

command -v acli >/dev/null 2>&1 || { note "SKIP: acli not on PATH — install the official Atlassian CLI first (A1 gate, ADR 0015)"; exit 0; }
[ -n "${CONFLUENCE_SANDBOX_SPACE:-}" ] || { note "SKIP: CONFLUENCE_SANDBOX_SPACE not set — no sandbox space targeted"; exit 0; }

note "leg 1/9: spaces list (enumeration + JSON output)"
acli space list --limit 5 --json > /tmp/probe-spaces.json 2> /tmp/probe-spaces.err \
  || die "space list failed: $(cat /tmp/probe-spaces.err)"
python -c "import json,sys; d=json.load(open(sys.argv[1])); assert 'results' in d, d" /tmp/probe-spaces.json \
  || die "space list payload missing results[] (contract anchor: _extract_results)"

note "leg 2/9: CQL search (JSON + result shape)"
acli search --cql "type=page AND text ~ \"probe\"" --limit 3 --json > /tmp/probe-search.json 2>/tmp/probe-search.err \
  || die "search failed: $(cat /tmp/probe-search.err)"
python -c "import json,sys; d=json.load(open(sys.argv[1])); assert isinstance(d.get('results'), list), d" /tmp/probe-search.json \
  || die "search payload missing results[] (contract anchor: _extract_results)"

note "leg 3/9: page create in sandbox space"
CREATE_OUT=$(acli page create --space "$CONFLUENCE_SANDBOX_SPACE" --title "kgent-a1-probe" --content "<p>probe body</p>" --json 2>/tmp/probe-create.err) \
  || die "page create failed: $(cat /tmp/probe-create.err)"
PAGE_ID=$(python -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$CREATE_OUT" 2>/dev/null) \
  || die "page create payload missing id (contract anchor: _extract_native_id)"
[ -n "$PAGE_ID" ] || die "empty page id"

note "leg 4/9: page get (version.number + body.storage present)"
GET_OUT=$(acli page get --id "$PAGE_ID" --body-format storage --json 2>/tmp/probe-get.err) \
  || die "page get failed: $(cat /tmp/probe-get.err)"
python - "$GET_OUT" <<'PY' || die "page get payload missing version.number / body storage (contract anchors: _extract_version/_extract_body_storage)"
import json, sys
d = json.loads(sys.argv[1])
v = d.get("version")
number = v.get("number") if isinstance(v, dict) else v
assert number is not None, d
body = d.get("bodyStorage") or (d.get("body", {}) or {}).get("storage", {}).get("value")
assert isinstance(body, str) and body, d
PY

note "leg 5/9: conditional update (version+1)"
CUR=$(( "$(python -c "import json,sys; d=json.loads(sys.argv[1]); v=d.get('version'); print(v.get('number') if isinstance(v,dict) else v)" "$GET_OUT")" + 1 ))
acli page update --id "$PAGE_ID" --version "$CUR" --content "<p>probe body v2</p>" --json >/dev/null 2>/tmp/probe-update.err \
  || die "conditional update with version=$CUR failed: $(cat /tmp/probe-update.err)"

note "leg 6/9: stale update refused (conflict path)"
acli page update --id "$PAGE_ID" --version 1 --content "<p>stale</p>" --json >/dev/null 2>&1 \
  && die "stale update unexpectedly SUCCEEDED — no version CAS on this surface"

note "leg 7/9: delete to trash"
acli page delete --id "$PAGE_ID" --json >/dev/null 2>/tmp/probe-delete.err \
  || die "page delete failed: $(cat /tmp/probe-delete.err)"

note "leg 8/9: trash restore endpoint available"
acli page restore --id "$PAGE_ID" --json >/dev/null 2>/tmp/probe-restore.err \
  || die "trash restore failed (undo delete-leg depends on it): $(cat /tmp/probe-restore.err)"

note "leg 9/9: cleanup — delete the probe page again (trash)"
acli page delete --id "$PAGE_ID" --json >/dev/null 2>&1 || die "cleanup delete failed for page $PAGE_ID — remove it manually from the sandbox space"

if [ "$FAILURES" -gt 0 ]; then
  echo "PROBE RESULT: $FAILURES leg(s) failed — reconcile argv/_extract_* anchors in kgent/adapters/confluence.py and the confluence-integration skill"
  exit 1
fi
echo "PROBE RESULT: all legs passed — acli Confluence surface matches the REQUIRED contract; e2e claims are unblocked"
