#!/usr/bin/env bash
# kgent skills installer (design: grilling session 2026-09-01; seams S1-S7 in
# tests/test_install_skills.py).
#
# Contract:
#   - every path derives from $HOME (hermetic under a sandboxed HOME);
#     --hub overrides the hub directory
#   - backend commands (uv/python) are resolved via PATH
#   - exit 0 = installed & healthy; non-zero = failure or usage error
#
# Flags (implemented slices): --copy --backup --uninstall --no-cli --sync
# --keep --force --agents <name[,name...]>. Unknown flags are a usage error
# (exit 2).
#
# Install gate (spec 2026-09-19-install-gate-design.md; ADR 0010): platform
# integration skills install only when backends.<platform>.enabled is true in
# the kgent config - the config is the single gate signal, NEVER native-skill
# presence. The installer only READS the config. Plain install never prunes;
# --sync converges both ways (gate-closed skills are removed, --keep opts
# out); --force opens every gate with a warning; --agents scopes the mirror
# hops (the hub is unconditional).
set -euo pipefail

BACKUP=0
COPY=0
UNINSTALL=0
NO_CLI=0
SYNC=0
KEEP=0
FORCE=0
AGENTS_ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
  --backup) BACKUP=1 ;;
  --copy) COPY=1 ;;
  --uninstall) UNINSTALL=1 ;;
  --no-cli) NO_CLI=1 ;;
  --sync) SYNC=1 ;;
  --keep) KEEP=1 ;;
  --force) FORCE=1 ;;
  --agents)
    if [ $# -lt 2 ] || [ -z "${2:-}" ]; then
      echo "usage: --agents requires a non-empty value" >&2
      exit 2
    fi
    AGENTS_ARG="$2"
    shift
    ;;
  *)
    echo "usage: install-skills.sh [--copy] [--backup] [--uninstall] [--no-cli] [--sync] [--keep] [--force] [--agents <name[,name...]>]" >&2
    exit 2
    ;;
  esac
  shift
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILLS_SRC="$REPO_ROOT/skills"
HUB="${KGENT_SKILLS_HUB:-$HOME/.agents/skills}"
CLAUDE_DIR="$HOME/.claude/skills"
CODEBUDDY_DIR="$HOME/.codebuddy/skills"

KGENT_DIR="${KGENT_HOME:-$HOME/.kgent}"
CONFIG_FILE="$KGENT_DIR/config.yaml"
TARGETS_FILE="$KGENT_DIR/skills-targets.txt"
GATED_SKILL_RE='^(lark|dingtalk|wecom)-integration$'

# Mirror registry: agents that keep their OWN skills dir and need a hop from
# the hub. A new own-dir agent is one entry here - no logic change. Hub-native
# agents (codex opencode openclaw pi) natively scan the hub, so they are NOT
# valid --agents values: the hub is installed unconditionally and cannot be
# scoped per agent.
mirror_dir() {
  case "$1" in
  claude) echo "$HOME/.claude/skills" ;;
  codebuddy) echo "$HOME/.codebuddy/skills" ;;
  *) return 1 ;;
  esac
}
mirror_root() { dirname "$(mirror_dir "$1")"; }
MIRROR_NAMES="claude codebuddy"
HUB_NATIVE_AGENTS="codex opencode openclaw pi"

is_gated() { [[ "$1" =~ $GATED_SKILL_RE ]]; }

is_windows=0
case "$(uname -s)" in
MINGW* | MSYS* | CYGWIN*) is_windows=1 ;;
esac

TS="$(date +%Y%m%d%H%M%S)"

# gate_state <backend> -> "open" | "closed"
# Fail-closed: anything unreadable or unparseable reads CLOSED, never open.
# Leg 1: `kgent config show-effective --json` (the CLI's effective view - the
# same scripting surface the skills consume). Leg 2: a pinned grep over the
# machine-written YAML - block header exactly "  <backend>:", key line exactly
# "    enabled: <value>"; only the literal "true" (inline comment stripped)
# opens the gate. A block that exists in some other shape warns and reads
# closed; a missing key reads closed silently.
gate_state() {
  local backend="$1" state
  state="$(gate_via_cli "$backend")" || state=""
  if [ "$state" = "open" ] || [ "$state" = "closed" ]; then
    echo "$state"
    return 0
  fi
  gate_via_grep "$backend"
}

gate_via_cli() {
  local backend="$1" json py state
  command -v kgent >/dev/null 2>&1 || return 1
  py="$(command -v python || command -v python3)" || return 1
  json="$(kgent config show-effective --json 2>/dev/null)" || return 1
  [ -n "$json" ] || return 1
  state="$("$py" - "$backend" "$json" <<'PYEOF'
import json
import sys

backend, raw = sys.argv[1], sys.argv[2]
try:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("effective config is not an object")
    # a backend the effective view does not report is not enabled in it -
    # leg 1 is authoritative, so absence reads closed (only an unparseable
    # payload falls back to leg 2)
    enabled = data.get("backends", {}).get(backend, {}).get("enabled", False)
except Exception:
    print("error")
    raise SystemExit(0)
print("open" if enabled else "closed")
PYEOF
)" || return 1
  echo "$state"
}

gate_via_grep() {
  local backend="$1" val
  if [ ! -f "$CONFIG_FILE" ]; then
    echo "closed"
    return 0
  fi
  if grep -Eq "^  ${backend}:[[:space:]]*$" "$CONFIG_FILE"; then
    val="$(awk -v b="$backend" '
      $0 == "  " b ":" {inblk = 1; next}
      /^[^ #]/ {inblk = 0}
      inblk && $0 ~ "^[[:space:]]+enabled:" {
        if ($0 ~ "^    enabled:") {
          v = $2
          sub(/#.*/, "", v)
          gsub(/[[:space:]]/, "", v)
          print "VALUE:" v
        } else {
          print "MALFORMED" # an enabled line the pinned shape cannot read
        }
        exit
      }
    ' "$CONFIG_FILE")"
    if [ "$val" = "MALFORMED" ]; then
      echo "install-gate WARNING: ${backend} block in ${CONFIG_FILE} not parseable - treating as closed" >&2
      echo "closed"
      return 0
    fi
    val="${val#VALUE:}"
    if [ "$val" = "true" ]; then
      echo "open"
    else
      echo "closed"
    fi
    return 0
  fi
  # the block exists in some shape, but not the pinned one - never guess open
  if grep -Eq "^[[:space:]]+${backend}:[[:space:]]*$" "$CONFIG_FILE"; then
    echo "install-gate WARNING: ${backend} block in ${CONFIG_FILE} not parseable - treating as closed" >&2
  fi
  echo "closed"
}

# gate_of <backend> -> the per-run gate state from GATE_STATES ("open|closed").
# States are computed ONCE per run (precompute block in the main flow), so the
# gate is read a single time per backend: diagnostics print exactly once and
# no consumer re-reads the config. Unknown backends read closed.
GATE_STATES=""
gate_of() {
  local gs
  for gs in $GATE_STATES; do
    if [ "${gs%%=*}" = "$1" ]; then
      echo "${gs#*=}"
      return 0
    fi
  done
  echo "closed"
}

# validate_targets <sel> <strict|lenient>
# sel is space-separated mirror names or the literal "all". strict (explicit
# --agents) turns an unknown name or a hub-native name into a usage error
# (exit 2, reason named); lenient (persisted targets file) just reports
# invalid so the caller can warn and widen to all.
validate_targets() {
  local sel="$1" strict="$2" piece
  if [ -z "$sel" ]; then return 1; fi
  if [ "$sel" = "all" ]; then return 0; fi
  for piece in $sel; do
    if mirror_dir "$piece" >/dev/null 2>&1; then continue; fi
    if echo " $HUB_NATIVE_AGENTS " | grep -q " $piece "; then
      if [ "$strict" = "strict" ]; then
        echo "'$piece' is a hub-native agent - the hub is installed unconditionally and cannot be scoped per agent (registry: $MIRROR_NAMES)" >&2
        exit 2
      fi
      return 1
    fi
    if [ "$strict" = "strict" ]; then
      echo "unknown agent '$piece' (registry: $MIRROR_NAMES)" >&2
      exit 2
    fi
    return 1
  done
  return 0
}

# resolve_targets: precedence --agents <list> (persisted) > persisted targets
# file > all detected. Prints the "targets:" line and sets ACTIVE_MIRRORS.
ACTIVE_MIRRORS=""
resolve_targets() {
  local sel="" piece comma
  if [ -n "$AGENTS_ARG" ]; then
    sel="${AGENTS_ARG//,/ }"
    validate_targets "$sel" strict
    comma="${sel// /,}"
    mkdir -p "$KGENT_DIR"
    printf '%s\n' "$comma" >"$TARGETS_FILE"
  elif [ -f "$TARGETS_FILE" ]; then
    sel="$(head -n 1 "$TARGETS_FILE")"
    if ! validate_targets "$sel" lenient; then
      echo "install-gate WARNING: invalid targets file ${TARGETS_FILE} - using all detected mirrors" >&2
      sel="all"
    fi
  else
    sel="all"
  fi
  if [ -z "$sel" ]; then sel="all"; fi
  ACTIVE_MIRRORS="$MIRROR_NAMES"
  if [ "$sel" != "all" ]; then ACTIVE_MIRRORS="$sel"; fi
  local line="targets: hub"
  for piece in $ACTIVE_MIRRORS; do
    if [ -d "$(mirror_root "$piece")" ]; then
      line="$line, $piece"
    fi
  done
  echo "$line"
}

# remove_entry <path>
# Distinguishes links from real content: on Windows a junction/symlink is a
# REPARSE POINT removed with os.rmdir - the target is never traversed, so a
# replacement can never damage the repo through the link. On POSIX rm -rf is
# link-safe by construction.
remove_entry() {
  local dst="$1"
  if [ "$is_windows" -eq 1 ]; then
    local py dst_w
    py="$(command -v python || command -v python3)"
    dst_w="$(cygpath -w "$dst")"
    "$py" - "$dst_w" <<'PYEOF'
import os
import shutil
import stat
import sys

p = sys.argv[1]
if not os.path.lexists(p):  # also true for dangling links - nothing to do
    raise SystemExit(0)
st = os.lstat(p)
is_reparse = bool(getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
if os.path.islink(p) or is_reparse:
    try:
        os.rmdir(p)  # removes the junction/symlink only - target untouched
    except OSError:
        os.remove(p)
elif os.path.isdir(p):
    shutil.rmtree(p)  # a stale copy: real content, safe to delete
else:
    os.remove(p)
PYEOF
  else
    rm -rf "$dst"
  fi
}

# sweep_dangling_self
# After a skill rename (e.g. question-answering -> query-knowledge), old links
# in the hub / agent dirs point at repo skill dirs that no longer exist; the
# install and uninstall loops both iterate only CURRENT repo dirs, so those
# entries would linger forever. Reclaim ONLY entries we own, by three
# conditions that must ALL hold: the entry is a link/junction, its target
# resolves under this repo's skills/ dir, and the target no longer exists.
# Real dirs (e.g. --copy leftovers) and anything pointing elsewhere are never
# touched - the hub is shared across agents and tools.
sweep_dangling_self() {
  local py dir dir_arg src_arg dangling entry
  py="$(command -v python || command -v python3)" || return 0
  for dir in "$HUB" "$CLAUDE_DIR" "$CODEBUDDY_DIR"; do
    [ -d "$dir" ] || continue
    if [ "$is_windows" -eq 1 ]; then
      dir_arg="$(cygpath -w "$dir")"
      src_arg="$(cygpath -w "$SKILLS_SRC")"
    else
      dir_arg="$dir"
      src_arg="$SKILLS_SRC"
    fi
    dangling="$("$py" - "$dir_arg" "$src_arg" <<'PYEOF'
import os
import stat
import sys

scan, skills_src = sys.argv[1], sys.argv[2]
try:
    entries = os.listdir(scan)
except OSError:
    raise SystemExit(0)
for name in entries:
    p = os.path.join(scan, name)
    try:
        st = os.lstat(p)
    except OSError:
        continue
    is_reparse = bool(getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    if not (os.path.islink(p) or is_reparse):
        continue  # a real dir/copy - ownership is unknowable, leave it
    try:
        target = os.readlink(p)
    except OSError:
        continue
    # junctions read back with the \\?\ extended-length prefix (and \\?\UNC\
    # for UNC targets) - strip it or the commonpath ownership check fails
    if target.startswith("\\\\?\\UNC\\"):
        target = "\\\\" + target[8:]
    elif target.startswith("\\\\?\\"):
        target = target[4:]
    if not os.path.isabs(target):
        target = os.path.join(scan, target)
    target = os.path.normpath(target)
    src = os.path.normpath(skills_src)
    try:
        inside = os.path.commonpath([target, src]) == src
    except ValueError:
        inside = False
    if inside and not os.path.exists(target):
        print(p)
PYEOF
)"
    while IFS= read -r entry; do
      [ -n "$entry" ] || continue
      echo "removing dangling entry: $entry (target gone from this repo's skills/)"
      remove_entry "$entry"
    done <<<"$dangling"
  done
}

# backup_entry <path> <name>
# Moves a replaced REAL dir into ~/.agents/skills-backups/<name>-<ts> (outside
# the skills dir, so agents never index backups). Links are just removed - the
# repo is their content.
backup_entry() {
  local dst="$1" name="$2"
  local backup_dir="$HOME/.agents/skills-backups/${name}-${TS}"
  mkdir -p "$(dirname "$backup_dir")"
  if [ "$is_windows" -eq 1 ]; then
    local py dst_w dir_w
    py="$(command -v python || command -v python3)"
    dst_w="$(cygpath -w "$dst")"
    dir_w="$(cygpath -w "$backup_dir")"
    "$py" - "$dst_w" "$dir_w" <<'PYEOF'
import os
import shutil
import stat
import sys

p, backup_dst = sys.argv[1], sys.argv[2]
st = os.lstat(p)
is_reparse = bool(getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
if os.path.islink(p) or is_reparse:
    os.rmdir(p)  # a link has no content of its own - the repo is the truth
elif os.path.isdir(p):
    shutil.move(p, backup_dst)
else:
    os.remove(p)
PYEOF
  else
    mv "$dst" "$backup_dir"
  fi
}

# install_entry <source> <destination> <name> <link|copy>
install_entry() {
  local src="$1" dst="$2" name="$3" mode="$4"
  if [ -e "$dst" ] || [ -L "$dst" ]; then
    echo "replacing existing entry: $dst"
    if [ "$BACKUP" -eq 1 ]; then
      backup_entry "$dst" "$name"
    else
      remove_entry "$dst"
    fi
  fi
  if [ "$mode" = "copy" ]; then
    cp -R "$src" "$dst"
  else
    link_entry "$src" "$dst"
  fi
}

# link_entry <source> <destination>
# Windows: a junction (via python's _winapi - no admin, survives rm safely);
# POSIX: a symlink. The destination is replaced if it exists.
link_entry() {
  local src="$1" dst="$2"
  if [ "$is_windows" -eq 1 ]; then
    local py src_w dst_w
    py="$(command -v python || command -v python3)"
    src_w="$(cygpath -w "$src")"
    dst_w="$(cygpath -w "$dst")"
    "$py" - "$src_w" "$dst_w" <<'PYEOF'
import sys

import _winapi

_winapi.CreateJunction(sys.argv[1], sys.argv[2])
PYEOF
  else
    ln -sfn "$src" "$dst"
  fi
}

# install_cli
# Backend chain per the settled design: uv (bootstrapped by the consumer if
# absent) -> dedicated venv + shim -> ambient pip (PEP 668 aware). The chosen
# backend is recorded so --uninstall tears down through the same one.
# KGENT_CLI_BACKEND=none|uv|venv|pip forces a branch (used by tests/CI).
install_cli() {
  local backend="${KGENT_CLI_BACKEND:-auto}"
  local state="$HOME/.kgent/install-backend.txt"
  local py="$(command -v python3 || command -v python || true)"
  if [ "$backend" = "none" ]; then
    echo "WARNING: CLI install disabled (KGENT_CLI_BACKEND=none) - kgent will NOT be available" >&2
    return 0
  fi
  if { [ "$backend" = "auto" ] || [ "$backend" = "uv" ]; } && command -v uv >/dev/null 2>&1; then
    echo "installing kgent CLI via uv"
    # cache clean + --reinstall: uv serves a cached wheel by version, so a same-version
    # rebuild silently ships stale code ("install OK" lies — hit 2026-09-06, missing route)
    (cd "$REPO_ROOT" && uv cache clean kgent && uv tool install --force --reinstall --from . kgent)
    mkdir -p "$HOME/.kgent"
    printf 'uv\n' >"$state"
    return 0
  fi
  if { [ "$backend" = "auto" ] || [ "$backend" = "venv" ]; } && [ -n "$py" ]; then
    local venv_dir="$HOME/.kgent/venv"
    echo "installing kgent CLI via dedicated venv at $venv_dir"
    "$py" -m venv "$venv_dir"
    if [ "$is_windows" -eq 1 ]; then
      "$venv_dir/Scripts/python.exe" -m pip install -q -e "$REPO_ROOT"
      mkdir -p "$HOME/.kgent/bin"
      printf '@echo off\r\n"%s" %%*\r\n' "$(cygpath -w "$venv_dir/Scripts/kgent.exe")" >"$HOME/.kgent/bin/kgent.cmd"
      echo "NOTE: add \\"$HOME\\kgent\\bin\\" to PATH to use the kgent command"
    else
      "$venv_dir/bin/python" -m pip install -q -e "$REPO_ROOT"
      mkdir -p "$HOME/.local/bin"
      ln -sf "$venv_dir/bin/kgent" "$HOME/.local/bin/kgent"
      echo "NOTE: ensure $HOME/.local/bin is on PATH to use the kgent command"
    fi
    mkdir -p "$HOME/.kgent"
    printf 'venv\n' >"$state"
    return 0
  fi
  if [ -n "$py" ]; then
    echo "installing kgent CLI via ambient pip ($py)"
    if ! "$py" -m pip install -q -e "$REPO_ROOT"; then
      echo "ambient pip refused (PEP 668?) - retrying with --user --break-system-packages" >&2
      "$py" -m pip install -q --user --break-system-packages -e "$REPO_ROOT"
    fi
    mkdir -p "$HOME/.kgent"
    printf 'pip\n' >"$state"
    return 0
  fi
  echo "WARNING: no supported CLI backend found - kgent will NOT be available" >&2
  return 1
}

# uninstall_all: skills entries first (safe removal - never traverses links),
# then the CLI through the recorded backend. Without recorded provenance the
# CLI is left in place (we did not install it). Uninstall ignores the gate and
# the targets selection - it tears down everything this repo installed.
uninstall_all() {
  sweep_dangling_self
  for skill_dir in "$SKILLS_SRC"/*/; do
    [ -f "${skill_dir}SKILL.md" ] || continue
    name="$(basename "$skill_dir")"
    if [ -e "$HUB/$name" ] || [ -L "$HUB/$name" ]; then
      remove_entry "$HUB/$name"
    fi
    for m in $MIRROR_NAMES; do
      mdir="$(mirror_dir "$m")"
      if [ -e "$mdir/$name" ] || [ -L "$mdir/$name" ]; then
        remove_entry "$mdir/$name"
      fi
    done
  done
  local state="$HOME/.kgent/install-backend.txt"
  if [ ! -f "$state" ]; then
    echo "no recorded CLI install - leaving any existing kgent command in place"
    return 0
  fi
  local backend
  backend="$(head -n 1 "$state")"
  case "$backend" in
  uv)
    echo "uninstalling kgent CLI via uv"
    uv tool uninstall kgent || true
    ;;
  venv)
    echo "removing dedicated venv"
    rm -rf "$HOME/.kgent/venv"
    rm -f "$HOME/.local/bin/kgent" "$HOME/.kgent/bin/kgent.cmd"
    ;;
  pip)
    echo "uninstalling kgent CLI via pip"
    "$(command -v python3 || command -v python)" -m pip uninstall -y kgent || true
    ;;
  *)
    echo "unknown recorded backend: $backend - leaving CLI in place" >&2
    ;;
  esac
  rm -f "$state"
}

if [ "$UNINSTALL" -eq 1 ]; then
  uninstall_all
  exit 0
fi

# verify: the health check (S7). Verifies the gate-adjusted expectation set
# through public behavior - hub entry SKILL.md resolvable, active mirror hops
# resolvable, and (unless --no-cli) a kgent binary on PATH whose help mentions
# the wiki subcommand. Gate-closed skills are skipped (not installed by
# design); a missing entry in an active mirror is a failure. Prints a
# pass/fail summary and returns non-zero on any failure, which gates the
# script's exit code.
verify() {
  local ok=1 name m mdir
  for skill_dir in "$SKILLS_SRC"/*/; do
    [ -f "${skill_dir}SKILL.md" ] || continue
    name="$(basename "$skill_dir")"
    if is_gated "$name" && [ "$FORCE" -eq 0 ]; then
      if [ "$(gate_of "${name%-integration}")" = "closed" ]; then
        continue
      fi
    fi
    if [ -f "$HUB/$name/SKILL.md" ]; then
      echo "OK   $name (hub)"
    else
      echo "FAIL $name: hub entry broken" >&2
      ok=0
    fi
    for m in $ACTIVE_MIRRORS; do
      if [ -d "$(mirror_root "$m")" ]; then
        mdir="$(mirror_dir "$m")"
        if [ -f "$mdir/$name/SKILL.md" ]; then
          echo "OK   $name ($m)"
        else
          echo "FAIL $name: $m entry broken" >&2
          ok=0
        fi
      fi
    done
  done
  if [ "$NO_CLI" -eq 1 ]; then
    echo "SKIP kgent CLI (--no-cli)"
  elif command -v kgent >/dev/null 2>&1 && kgent --help 2>&1 | grep -q wiki; then
    echo "OK   kgent CLI ($(command -v kgent))"
  else
    echo "FAIL kgent CLI not healthy" >&2
    ok=0
  fi
  if [ "$ok" -eq 1 ]; then
    echo "install OK"
echo "verify: bash tools/artifact-smoke.sh  (install OK does not check freshness - see the 2026-09-06 uv cache incident)"
  else
    echo "install FAILED" >&2
  fi
  [ "$ok" -eq 1 ]
}

sweep_dangling_self

resolve_targets

# evaluate every gated backend exactly once per run (single gate read)
for skill_dir in "$SKILLS_SRC"/*/; do
  [ -f "${skill_dir}SKILL.md" ] || continue
  name="$(basename "$skill_dir")"
  if is_gated "$name"; then
    backend="${name%-integration}"
    state="$(gate_state "$backend")"
    GATE_STATES="$GATE_STATES $backend=$state"
  fi
done

if [ "$FORCE" -eq 1 ]; then
  forced=""
  for skill_dir in "$SKILLS_SRC"/*/; do
    [ -f "${skill_dir}SKILL.md" ] || continue
    name="$(basename "$skill_dir")"
    if is_gated "$name"; then
      if [ -z "$forced" ]; then forced="$name"; else forced="$forced, $name"; fi
    fi
  done
  echo "install-gate forced for: $forced"
elif [ ! -f "$CONFIG_FILE" ]; then
  echo "install-gate: no config at ${CONFIG_FILE} - platform integration skills stay uninstalled (run 'kgent setup', then 'bash tools/install-skills.sh --sync')"
fi

for skill_dir in "$SKILLS_SRC"/*/; do
  [ -f "${skill_dir}SKILL.md" ] || continue
  name="$(basename "$skill_dir")"
  if is_gated "$name" && [ "$FORCE" -eq 0 ]; then
    if [ "$(gate_of "${name%-integration}")" = "closed" ]; then
      echo "skip ${name} (install gate closed)"
      continue
    fi
  fi
  hub_mode=link
  if [ "$COPY" -eq 1 ]; then hub_mode=copy; fi
  mkdir -p "$HUB"
  # the hub carries the chosen mode; mirror hops always link to the hub
  # entry, so a frozen copy still has a single source of truth
  install_entry "${skill_dir%/}" "$HUB/$name" "$name" "$hub_mode"
  for m in $ACTIVE_MIRRORS; do
    if [ -d "$(mirror_root "$m")" ]; then
      mdir="$(mirror_dir "$m")"
      mkdir -p "$mdir"
      install_entry "$HUB/$name" "$mdir/$name" "$name" link
    fi
  done
done

# --sync's prune leg (skill 同步, ADR 0010): converge the installed set DOWN
# to the gate - remove gate-closed platform integration skills from the hub
# and the active mirrors. Plain install never prunes; --keep and --force
# suppress the prune leg.
if [ "$SYNC" -eq 1 ] && [ "$KEEP" -eq 0 ] && [ "$FORCE" -eq 0 ]; then
  for skill_dir in "$SKILLS_SRC"/*/; do
    [ -f "${skill_dir}SKILL.md" ] || continue
    name="$(basename "$skill_dir")"
    if ! is_gated "$name"; then continue; fi
    if [ "$(gate_of "${name%-integration}")" != "closed" ]; then continue; fi
    if [ -e "$HUB/$name" ] || [ -L "$HUB/$name" ]; then
      remove_entry "$HUB/$name"
      echo "removed ${name} from hub"
    fi
    for m in $ACTIVE_MIRRORS; do
      mdir="$(mirror_dir "$m")"
      if [ -e "$mdir/$name" ] || [ -L "$mdir/$name" ]; then
        remove_entry "$mdir/$name"
        echo "removed ${name} from $m"
      fi
    done
  done
  sweep_dangling_self
fi

if [ "$NO_CLI" -eq 1 ]; then
  echo "SKIP kgent CLI install (--no-cli)"
else
  install_cli
fi
verify
