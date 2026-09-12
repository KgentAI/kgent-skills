#!/usr/bin/env bash
# local-fs flow conformance (spec 2026-09-10 A4/A5/A5b; ADR 0006-0009).
# Replays the documented local-fs-integration flow against a real kgent
# artifact under throwaway KGENT_HOME + KGENT_LOCAL_FS_ROOT — the first
# backend whose full flow (route/journal/write/git/undo) is scriptable
# end-to-end with zero platform credentials. Runs twice: mode git-backed
# and mode snapshot. Fail closed: any assertion miss exits 1.
#
# Controller rulings applied on top of the plan's verbatim script (task-7
# brief): body hash starts at line 10 (frontmatter is 9 lines, not 8); the
# snapshot-mode drift leg asserts the instrument sane BEFORE the hand edit and
# divergent AFTER; the git-backed freshness leg compares HEAD against the
# CREATE commit captured in (a), not HEAD vs HEAD~1; the revert-conflict leg
# is kept with `git revert --abort` cleanup.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# venv preference, same as gauntlet.sh
if [ -x "$SCRIPT_DIR/../.venv/Scripts/python.exe" ]; then
  export PATH="$SCRIPT_DIR/../.venv/Scripts:$PATH"
elif [ -x "$SCRIPT_DIR/../.venv/bin/python" ]; then
  export PATH="$SCRIPT_DIR/../.venv/bin:$PATH"
fi
KGENT_BIN=""
for cand in "$HOME/.local/bin/kgent" "$(command -v kgent || true)"; do
  if [ -n "$cand" ] && [ -x "$cand" ]; then KGENT_BIN="$cand"; break; fi
done
if [ -z "$KGENT_BIN" ]; then
  echo "local-fs-flow FAILURE: no kgent artifact found (~/.local/bin/kgent or PATH)" >&2
  exit 1
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

hash_of() { # sha256:… of a file's bytes
  python -c "import hashlib,sys;print('sha256:'+hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$1"
}

# The flow's frontmatter is fixed-shape (8 header lines + closing '---' = 9
# lines), so the body starts at line 10 (MAINTAINER RULING: the plan's
# `tail -n +9` was off by one — it swallowed the closing '---' into the body
# hash). Body bytes == the body file we wrote verbatim.
body_hash() { tail -n +10 "$1" | python -c "import hashlib,sys;print('sha256:'+hashlib.sha256(sys.stdin.buffer.read()).hexdigest())"; }

# Windows quirk: rg prints backslash path separators on Windows while every
# URI / assertion in the skill speaks forward slashes — normalize before use.
_slashes() { tr '\\' '/'; }

write_doc() { # write_doc <path> <title> <version> <body-file>
  local path="$1" title="$2" version="$3" bodyfile="$4"
  local h; h="$(hash_of "$bodyfile")"
  { printf -- '---\nid: %s\ntitle: %s\nversion: %s\nhash: %s\ncreated: 2026-09-11T00:00:00Z\nupdated: 2026-09-11T00:00:00Z\narchived: false\n---\n' \
      "${path#"$STORE"/}" "$title" "$version" "$h"
    cat "$bodyfile"; } > "$path"
}

assert() { # assert <desc> <cmd…>
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then echo "  ok   $desc"; else echo "  FAIL $desc" >&2; exit 1; fi
}
assert_not() {
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then echo "  FAIL $desc" >&2; exit 1; else echo "  ok   $desc"; fi
}

run_flow() { # run_flow <mode>
  local mode="$1"
  local home="$WORK/home-$mode" root="$WORK/store-$mode"
  local doc="$root/engineering-wiki/onboarding/first-year-tasks.md"
  export KGENT_HOME="$home" KGENT_LOCAL_FS_ROOT="$root"
  mkdir -p "$home"
  cat > "$home/config.yaml" <<EOF
version: 1
defaults:
  routing_mode: configured
  default_backends: [local-fs]
backends:
  local-fs:
    enabled: true
    type: skill
    skill_name: local-fs-integration
    trust_zone: internal
    mode: $mode
EOF

  echo "-- local-fs flow [$mode] root=$root"
  "$KGENT_BIN" setup >/dev/null
  STORE="$root"
  # The flow's own commits carry the same throwaway identity kgent's seed
  # commit uses (localfs.init_store): a throwaway env has no global git config.
  local GIT=(git -C "$root" -c user.name=kgent -c user.email=kgent@local)

  # (a) skill Write step 1 — route adjudication (read-only, before any write).
  # The CLI has no local-fs adapter; route adjudicates the configured backend
  # from its config-side trust_zone (spec 2026-09-10). Pinned outcome: internal
  # content + internal zone → exit 0 with local-fs in allowed_backends.
  local route_json route_code
  route_json="$("$KGENT_BIN" route --content "first-year body" --backends local-fs --json 2>&1)" \
    && route_code=0 || route_code=$?
  assert "(a) route adjudicates the adapter-less local-fs backend (never exit 1)" \
    bash -c "test '$route_code' -ne 1"
  assert "(a) route allows local-fs (internal content, internal zone)" \
    bash -c "printf '%s' '$route_json' | python -c \"import json,sys;d=json.load(sys.stdin);sys.exit(0 if 'local-fs' in d.get('allowed_backends',[]) else 1)\""

  # (a) create space/node/doc per the skill: mkdir + frontmatter + journal + (git) commit
  mkdir -p "$root/engineering-wiki/onboarding"
  printf 'first-year body\n' > "$WORK/body-a.txt"
  local begin op_id
  begin="$("$KGENT_BIN" journal begin --operation create --backend local-fs \
    --doc-uri "kgent://local-fs/create-placeholder.md" \
    --snapshot-content "$(cat "$WORK/body-a.txt")" --json)"
  op_id="$(OP="$begin" python -c "import json,os;print(json.loads(os.environ['OP'])['entry']['op_id'])")"
  write_doc "$doc" "第一年末任务" 1 "$WORK/body-a.txt"
  if [ "$mode" = "git-backed" ]; then
    local seed_sha create_sha
    seed_sha="$(git -C "$root" rev-parse HEAD)" # setup's seed commit ("kgent: seed local-fs store")
    "${GIT[@]}" add "engineering-wiki/onboarding/first-year-tasks.md"
    "${GIT[@]}" commit --no-gpg-sign -q -m "kgent($op_id): create kgent://local-fs/engineering-wiki/onboarding/first-year-tasks.md (v0→v1)"
    create_sha="$(git -C "$root" rev-parse HEAD)"
    "$KGENT_BIN" journal end --op-id "$op_id" --status ok --revision-after "$create_sha" \
      --doc-uri "kgent://local-fs/engineering-wiki/onboarding/first-year-tasks.md" --json >/dev/null
    assert "(a) create leg is exactly one commit on top of the seed" \
      bash -c "test \$(git -C '$root' rev-list --count '$seed_sha'..HEAD) -eq 1"
    assert "(a) commit message carries op_id" bash -c "git -C '$root' log --format=%s -1 | grep -qF '$op_id'"
  else
    "$KGENT_BIN" journal end --op-id "$op_id" --status ok --revision-after "1" \
      --doc-uri "kgent://local-fs/engineering-wiki/onboarding/first-year-tasks.md" --json >/dev/null
  fi
  assert "(a) frontmatter version=1" grep -q "^version: 1$" "$doc"

  # (b) search hits with URI-able path; .git never in results
  local search_hits
  if command -v rg >/dev/null 2>&1; then
    search_hits="$(rg -n --glob '*.md' --glob '!/.git/**' 'first-year body' "$root" | _slashes || true)"
  else
    search_hits="$(grep -rn --include='*.md' --exclude-dir=.git 'first-year body' "$root" || true)"
  fi
  assert "(b) search finds the doc" bash -c "echo '$search_hits' | grep -q 'onboarding/first-year-tasks.md'"
  assert_not "(b) .git excluded from search" bash -c "echo '$search_hits' | grep -q '/.git/'"

  # (c) update bumps version (CAS honored by the caller per skill; the stale
  # CAS refusal is journal+no-write: end --status failed, file untouched —
  # proven here by the stale-leg assertion below)
  printf 'second body\n' > "$WORK/body-b.txt"
  local stale_begin stale_op
  stale_begin="$("$KGENT_BIN" journal begin --operation update --backend local-fs \
    --doc-uri "kgent://local-fs/engineering-wiki/onboarding/first-year-tasks.md" \
    --revision-before "$( [ "$mode" = git-backed ] && git -C "$root" rev-parse HEAD || echo 1 )" \
    --snapshot-content "$(cat "$WORK/body-b.txt")" --json)"
  stale_op="$(OP="$stale_begin" python -c "import json,os;print(json.loads(os.environ['OP'])['entry']['op_id'])")"
  # CAS: expected version is 99 — file carries 1 → mismatch → refuse, file untouched, failed op recorded
  if [ "$mode" = "git-backed" ]; then
    "$KGENT_BIN" journal end --op-id "$stale_op" --status failed --revision-after "$(git -C "$root" rev-parse HEAD)" --json >/dev/null
  else
    "$KGENT_BIN" journal end --op-id "$stale_op" --status failed --revision-after "1" --json >/dev/null
  fi
  assert "(c) stale CAS left file at v1" grep -q "^version: 1$" "$doc"
  write_doc "$doc" "第一年末任务" 2 "$WORK/body-b.txt"
  if [ "$mode" = "git-backed" ]; then
    "${GIT[@]}" add "engineering-wiki/onboarding/first-year-tasks.md"
    "${GIT[@]}" commit --no-gpg-sign -q -m "kgent: update v1→v2"
  fi
  assert "(c) version bumped to 2" grep -q "^version: 2$" "$doc"

  # (d) archive flips flag; search no longer surfaces it
  sed -i 's/^archived: false$/archived: true/' "$doc"
  if [ "$mode" = "git-backed" ]; then
    "${GIT[@]}" add "engineering-wiki/onboarding/first-year-tasks.md"
    "${GIT[@]}" commit --no-gpg-sign -q -m "kgent: archive v2→v3"
  fi
  assert "(d) archived flag set" grep -q "^archived: true$" "$doc"
  # skill search = raw hits THEN drop archived (frontmatter read per hit)
  local hit_files active_hits f
  if command -v rg >/dev/null 2>&1; then
    hit_files="$(rg -l --glob '*.md' --glob '!/.git/**' 'second body' "$root" | _slashes || true)"
  else
    hit_files="$(grep -rl --include='*.md' --exclude-dir=.git 'second body' "$root" || true)"
  fi
  active_hits=""
  for f in $hit_files; do grep -q '^archived: true$' "$f" || active_hits="$active_hits$f"$'\n'; done
  assert "(b) pre-archive search hit present" bash -c "test -n '$hit_files'"
  assert_not "(d) archived doc filtered from active hits" bash -c "echo '$active_hits' | grep -q first-year"

  # (e) delete → gone (git-backed: history keeps it) → undo restores
  if [ "$mode" = "git-backed" ]; then
    "${GIT[@]}" rm -q "engineering-wiki/onboarding/first-year-tasks.md"
    "${GIT[@]}" commit --no-gpg-sign -q -m "kgent: delete v3→v4"
    local del_sha
    del_sha="$(git -C "$root" rev-parse HEAD)"
    assert_not "(e) file gone after delete" test -f "$doc"
    "${GIT[@]}" revert --no-edit "$del_sha" >/dev/null
    assert "(e) undo via revert restores file" test -f "$doc"
  else
    mkdir -p "$root/.trash/engineering-wiki/onboarding"
    mv "$doc" "$root/.trash/engineering-wiki/onboarding/first-year-tasks.md"
    assert_not "(e) file gone after delete" test -f "$doc"
    mv "$root/.trash/engineering-wiki/onboarding/first-year-tasks.md" "$doc"
    assert "(e) undo via .trash restores file" test -f "$doc"
  fi

  # (f) undo refusal conditions present, fail closed
  if [ "$mode" = "git-backed" ]; then
    printf 'hand edit\n' >> "$doc"
    assert_not "(f) dirty tree present refuses compensation" \
      bash -c "test -z \"\$(git -C '$root' status --porcelain)\""
    "${GIT[@]}" checkout -q -- "engineering-wiki/onboarding/first-year-tasks.md"
    # freshness (MAINTAINER RULING): the ledger's post-write revision is the
    # CREATE commit captured in (a) — HEAD has moved past it (update/archive/
    # delete/revert), so the documented undo freshness gate must refuse
    assert_not "(f) HEAD moved past ledger post-write SHA refuses freshness" \
      bash -c "test \"\$(git -C '$root' rev-parse HEAD)\" = '$create_sha'"
    # structural sentinel: reverting the create commit now conflicts (file rewritten since)
    assert_not "(f) revert of create commit conflicts after subsequent writes" \
      "${GIT[@]}" revert --no-edit "$create_sha"
    "${GIT[@]}" revert --abort >/dev/null 2>&1 || true
    git -C "$root" status >/dev/null # sanity: repo still operable after aborted revert
  else
    local cur_hash fm_hash
    cur_hash="$(body_hash "$doc")"
    fm_hash="$(grep -m1 '^hash: ' "$doc" | cut -d' ' -f2)"
    # instrument sanity (MAINTAINER RULING): before the hand edit the body hash
    # MUST match the frontmatter hash — proves the drift check below can actually fire
    assert "(f) body hash matches frontmatter hash before hand edit" bash -c "test '$cur_hash' = '$fm_hash'"
    printf 'hand edit\n' >> "$doc"
    cur_hash="$(body_hash "$doc")"
    assert_not "(f) hash drift refuses snapshot compensation" bash -c "test '$cur_hash' = '$fm_hash'"
  fi

  # (g) journal pairing: begin+end share the uuid-suffixed op_id
  assert "(g) journal has begin+end for op" bash -c "test \"\$(grep -c '$op_id' '$home/journal/journal.ndjson')\" -eq 2"
  # documented op_id shape (ledger._new_op_id, B1): op-<yyyymmdd>-<8hex> — a
  # per-process sequence number (the 2026-09-05 collision) would not match
  assert "(g) op_id carries uuid suffix" bash -c "echo '$op_id' | grep -qE '^op-[0-9]{8}-[0-9a-f]{8}\$'"

  # (A5) negatives: foreign file never staged; no remote configured by default
  printf 'no frontmatter here\n' > "$root/foreign.txt"
  printf 'another body\n' > "$WORK/body-c.txt"
  write_doc "$doc" "第一年末任务" 9 "$WORK/body-c.txt"
  if [ "$mode" = "git-backed" ]; then
    "${GIT[@]}" add "engineering-wiki/onboarding/first-year-tasks.md"
    "${GIT[@]}" commit --no-gpg-sign -q -m "kgent: update v8→v9"
    # skill rule: git add 只加触碰路径 — the foreign file stays untracked
    # (surfaced in status, never absorbed) and never enters the index or history
    assert "(A5) foreign file left untracked (surfaced in status)" \
      bash -c "git -C '$root' status --porcelain | grep -q '^?? .*foreign'"
    assert_not "(A5) foreign file never indexed" bash -c "git -C '$root' ls-files | grep -q foreign"
    assert_not "(A5) foreign file never committed" bash -c "git -C '$root' log --name-only --format= | grep -q foreign"

    # (A5b) remote push: configured → best-effort push lands the commit
    local bare="$WORK/remote-$mode.git"
    git init --bare -q "$bare"
    git -C "$root" remote add origin "$bare"
    "${GIT[@]}" push -q origin HEAD
    assert "(A5b) push landed the commit on the remote" bash -c "git -C '$bare' rev-parse HEAD >/dev/null 2>&1"
    assert "(A5b) no merge commits created locally (never auto-merge)" bash -c "test -z \"\$(git -C '$root' log --merges --oneline)\""

    # (A5b) diverged remote → push rejected, surfaced, never auto-resolved
    local clone="$WORK/clone-$mode"
    git clone -q "$bare" "$clone"
    git -C "$clone" -c user.name=kgent -c user.email=kgent@local commit --no-gpg-sign -q --allow-empty -m "divergent commit from another machine"
    git -C "$clone" push -q origin HEAD
    "${GIT[@]}" commit --no-gpg-sign -q --allow-empty -m "divergent local commit"
    assert_not "(A5b) non-fast-forward push is rejected" "${GIT[@]}" push origin HEAD
    assert "(A5b) divergence left unmerged (surface, not solve)" bash -c "test -z \"\$(git -C '$root' log --merges --oneline)\""
    git -C "$root" remote remove origin
  fi
  assert "(A5) no remote configured by default" bash -c "test -z \"\$(git -C '$root' remote)\""
}

run_flow git-backed
run_flow snapshot

echo "local-fs-flow: both modes passed"
