#!/usr/bin/env bash
# Manual mutation harness for the install-gate code (spec
# 2026-09-19-install-gate-design.md — old-coder gauntlet layer "tests that
# assert nothing"). Applies one plausible bug at a time, runs the targeted
# test(s), and expects them to FAIL: a mutant the suite does not kill is a
# hole in the tests, not a pass. The file is restored via git after every
# mutant, and the harness fails closed — an anchor that no longer applies, a
# crashed run, or a surviving mutant all exit non-zero.
#
# Usage: bash tools/mutate-install-gate.sh   (from the repo root; worktree
# must be committed or the restore step cannot be trusted)
set -uo pipefail

mutate_and_test() {
  local desc="$1" file="$2" old="$3" new="$4"
  shift 4
  python - "$file" "$old" "$new" <<'PYEOF'
import sys

path, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path, encoding="utf-8", newline="") as fh:
    src = fh.read()
# the worktree may be CRLF (core.autocrlf); anchors are LF - normalize both
src = src.replace("\r\n", "\n")
if src.count(old) != 1:
    raise SystemExit(f"anchor not unique in {path}: count={src.count(old)}")
with open(path, "w", encoding="utf-8", newline="") as fh:
    fh.write(src.replace(old, new, 1))
PYEOF
  if [ $? -ne 0 ]; then
    echo "MUTANT DID NOT APPLY: $desc" >&2
    git checkout -- "$file" 2>/dev/null
    return 2
  fi
  if PYTHONPATH=src python -m pytest "$@" -q >/dev/null 2>&1; then
    echo "SURVIVED: $desc"
    git checkout -- "$file"
    return 1
  fi
  echo "killed:   $desc"
  git checkout -- "$file"
  return 0
}

fail=0
SCRIPT=tools/install-skills.sh
DETECT=src/kgent/capabilities/detect.py
INSTALL=tests/test_install_skills.py
DOCTOR=tests/test_discovery_doctor.py

# M1: the grep leg's comparison inverted -> open and closed swap
mutate_and_test "M1 grep-leg comparison inverted" "$SCRIPT" \
  'if [ "$val" = "true" ]; then
      echo "open"
    else
      echo "closed"
    fi
    return 0' \
  'if [ "$val" != "true" ]; then
      echo "open"
    else
      echo "closed"
    fi
    return 0' \
  "$INSTALL::test_i2_lark_enabled_installs_lark_integration_only" \
  "$INSTALL::test_i3_all_disabled_no_notice" || fail=1

# M2: the prune whitelist dropped -> sync would consider every skill
mutate_and_test "M2 prune whitelist dropped" "$SCRIPT" \
  'if ! is_gated "$name"; then continue; fi' \
  '' \
  "$INSTALL::test_i15_prune_whitelist_spares_lanes_and_local" || fail=1

# M3: the per-run gate lookup inverted -> every backend reads closed
mutate_and_test "M3 gate_of lookup inverted" "$SCRIPT" \
  'if [ "${gs%%=*}" = "$1" ]; then' \
  'if [ "${gs%%=*}" != "$1" ]; then' \
  "$INSTALL::test_i2_lark_enabled_installs_lark_integration_only" || fail=1

# M4: --force inverted -> forced runs install nothing gated
mutate_and_test "M4 force flag inverted" "$SCRIPT" \
  'if is_gated "$name" && [ "$FORCE" -eq 0 ]; then
    if [ "$(gate_of "${name%-integration}")" = "closed" ]; then
      echo "skip ${name} (install gate closed)"' \
  'if is_gated "$name" && [ "$FORCE" -eq 1 ]; then
    if [ "$(gate_of "${name%-integration}")" = "closed" ]; then
      echo "skip ${name} (install gate closed)"' \
  "$INSTALL::test_i9_force_installs_all_platform_skills_with_warning" || fail=1

# M5: leg 1 no longer authoritative -> a backend missing from the effective
# JSON reads open (the exact fail-closed bug the leg-1 tests pin)
mutate_and_test "M5 leg-1 absence reads open" "$SCRIPT" \
  'enabled = data.get("backends", {}).get(backend, {}).get("enabled", False)' \
  'enabled = data.get("backends", {}).get(backend, {}).get("enabled", True)' \
  "$INSTALL::test_i2b_showeffective_leg_wins_over_config_file" || fail=1

# M6: the doctor probe fails open -> an absent/unreadable location reports
# installed, silencing the alignment finding
mutate_and_test "M6 doctor probe fails open" "$DETECT" \
  '        except OSError:
            continue
        if stat.S_ISREG(st.st_mode):
            return True' \
  '        except OSError:
            return True
        if stat.S_ISREG(st.st_mode):
            return True' \
  "$DOCTOR::test_d5_unreadable_probe_location_fails_closed" || fail=1

# M7: the hub-native --agents rejection branch disabled -> codex falls
# through to the generic unknown-agent error (exit 2, wrong explanation)
mutate_and_test "M7 hub-native rejection disabled" "$SCRIPT" \
  'if echo " $HUB_NATIVE_AGENTS " | grep -q " $piece "; then' \
  'if false; then' \
  "$INSTALL::test_i13b_agents_hub_native_name_rejected_with_explanation" || fail=1

if git diff --quiet -- "$SCRIPT" "$DETECT"; then
  :
else
  echo "WORKTREE DIRTY AFTER MUTANTS - restore failed" >&2
  fail=1
fi

if [ "$fail" -ne 0 ]; then
  echo "MUTATION RESULT: FAILURES ABOVE" >&2
  exit 1
fi
echo "MUTATION RESULT: 7/7 killed"
