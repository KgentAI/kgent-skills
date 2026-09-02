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
# Flags (implemented slices): --copy --backup --uninstall --no-cli. Unknown
# flags are a usage error (exit 2).
set -euo pipefail

BACKUP=0
COPY=0
UNINSTALL=0
NO_CLI=0
while [ $# -gt 0 ]; do
  case "$1" in
  --backup) BACKUP=1 ;;
  --copy) COPY=1 ;;
  --uninstall) UNINSTALL=1 ;;
  --no-cli) NO_CLI=1 ;;
  *) echo "usage: install-skills.sh [--copy] [--backup] [--uninstall] [--no-cli]" >&2; exit 2 ;;
  esac
  shift
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILLS_SRC="$REPO_ROOT/skills"
HUB="${KGENT_SKILLS_HUB:-$HOME/.agents/skills}"
CLAUDE_DIR="$HOME/.claude/skills"

is_windows=0
case "$(uname -s)" in
MINGW* | MSYS* | CYGWIN*) is_windows=1 ;;
esac

TS="$(date +%Y%m%d%H%M%S)"

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
    (cd "$REPO_ROOT" && uv tool install --force --from . kgent)
    mkdir -p "$HOME/.kgent"
    printf 'uv\n' > "$state"
    return 0
  fi
  if { [ "$backend" = "auto" ] || [ "$backend" = "venv" ]; } && [ -n "$py" ]; then
    local venv_dir="$HOME/.kgent/venv"
    echo "installing kgent CLI via dedicated venv at $venv_dir"
    "$py" -m venv "$venv_dir"
    if [ "$is_windows" -eq 1 ]; then
      "$venv_dir/Scripts/python.exe" -m pip install -q -e "$REPO_ROOT"
      mkdir -p "$HOME/.kgent/bin"
      printf '@echo off\r\n"%s" %%*\r\n' "$(cygpath -w "$venv_dir/Scripts/kgent.exe")" > "$HOME/.kgent/bin/kgent.cmd"
      echo "NOTE: add \\"$HOME\\kgent\\bin\\" to PATH to use the kgent command"
    else
      "$venv_dir/bin/python" -m pip install -q -e "$REPO_ROOT"
      mkdir -p "$HOME/.local/bin"
      ln -sf "$venv_dir/bin/kgent" "$HOME/.local/bin/kgent"
      echo "NOTE: ensure $HOME/.local/bin is on PATH to use the kgent command"
    fi
    mkdir -p "$HOME/.kgent"
    printf 'venv\n' > "$state"
    return 0
  fi
  if [ -n "$py" ]; then
    echo "installing kgent CLI via ambient pip ($py)"
    if ! "$py" -m pip install -q -e "$REPO_ROOT"; then
      echo "ambient pip refused (PEP 668?) - retrying with --user --break-system-packages" >&2
      "$py" -m pip install -q --user --break-system-packages -e "$REPO_ROOT"
    fi
    mkdir -p "$HOME/.kgent"
    printf 'pip\n' > "$state"
    return 0
  fi
  echo "WARNING: no supported CLI backend found - kgent will NOT be available" >&2
  return 1
}

# uninstall_all: skills entries first (safe removal - never traverses links),
# then the CLI through the recorded backend. Without recorded provenance the
# CLI is left in place (we did not install it).
uninstall_all() {
  for skill_dir in "$SKILLS_SRC"/*/; do
    [ -f "${skill_dir}SKILL.md" ] || continue
    name="$(basename "$skill_dir")"
    if [ -e "$HUB/$name" ] || [ -L "$HUB/$name" ]; then
      remove_entry "$HUB/$name"
    fi
    if [ -e "$CLAUDE_DIR/$name" ] || [ -L "$CLAUDE_DIR/$name" ]; then
      remove_entry "$CLAUDE_DIR/$name"
    fi
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

# verify: the health check (S7). Verifies the whole chain through public
# behavior - hub entry SKILL.md resolvable, claude hop resolvable, and (unless
# --no-cli) a kgent binary on PATH whose help mentions the wiki subcommand.
# Prints a pass/fail summary and returns non-zero on any failure, which gates
# the script's exit code.
verify() {
  local ok=1 name
  for skill_dir in "$SKILLS_SRC"/*/; do
    [ -f "${skill_dir}SKILL.md" ] || continue
    name="$(basename "$skill_dir")"
    if [ -f "$HUB/$name/SKILL.md" ]; then
      echo "OK   $name (hub)"
    else
      echo "FAIL $name: hub entry broken" >&2
      ok=0
    fi
    if [ -d "$HOME/.claude" ]; then
      if [ -f "$CLAUDE_DIR/$name/SKILL.md" ]; then
        echo "OK   $name (claude)"
      else
        echo "FAIL $name: claude entry broken" >&2
        ok=0
      fi
    fi
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
  else
    echo "install FAILED" >&2
  fi
  [ "$ok" -eq 1 ]
}

for skill_dir in "$SKILLS_SRC"/*/; do
  [ -f "${skill_dir}SKILL.md" ] || continue
  name="$(basename "$skill_dir")"
  hub_mode=link
  if [ "$COPY" -eq 1 ]; then hub_mode=copy; fi
  mkdir -p "$HUB"
  # the hub carries the chosen mode; the claude hop always links to the hub
  # entry, so a frozen copy still has a single source of truth
  install_entry "${skill_dir%/}" "$HUB/$name" "$name" "$hub_mode"
  if [ -d "$HOME/.claude" ]; then
    mkdir -p "$CLAUDE_DIR"
    install_entry "$HUB/$name" "$CLAUDE_DIR/$name" "$name" link
  fi
done

if [ "$NO_CLI" -eq 1 ]; then
  echo "SKIP kgent CLI install (--no-cli)"
else
  install_cli
fi
verify
