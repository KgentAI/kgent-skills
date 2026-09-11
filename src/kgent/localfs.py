"""local-fs store helpers: root resolution, store-mode resolution, git init (ADR 0006-0009).

Pure functions over the config mapping (post-``load_config_dict`` shape) and the
filesystem. Execution of document ops lives in the ``local-fs-integration``
skill; this module only backs ``kgent setup`` / ``kgent doctor`` (spec
2026-09-10, "kgent CLI 侧改动").

Fail-closed rules (ADR 0009): ``init_store`` refuses to run git inside another
work tree — kgent never commits into a repo it does not own; every failure is
a named ``RuntimeError`` the caller maps to a config error.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

__all__ = [
    "BACKEND_NAME",
    "DEFAULT_MODE",
    "dirty_paths",
    "effective_mode",
    "git_path",
    "init_store",
    "nested_in_foreign_repo",
    "resolve_root",
]

BACKEND_NAME = "local-fs"
DEFAULT_MODE = "git-backed"
_GITATTRIBUTES = "* -text\n"
_SEED_COMMIT_ENV = [
    ("-c", "user.name=kgent"),
    ("-c", "user.email=kgent@local"),
]


def resolve_root(backends: dict[str, Any]) -> Path:
    """Resolve the store root: env > config ``root`` > ``~/.kgent/local-fs``."""
    env = os.environ.get("KGENT_LOCAL_FS_ROOT")
    if env:
        return Path(env)
    entry = backends.get(BACKEND_NAME)
    if isinstance(entry, dict):
        root = entry.get("root")
        if isinstance(root, str) and root.strip():
            return Path(root).expanduser()
    return Path.home() / ".kgent" / "local-fs"


def git_path() -> str | None:
    """Path to the ``git`` executable, or ``None`` when absent."""
    return shutil.which("git")


def nested_in_foreign_repo(root: Path) -> bool:
    """True when ``root`` resolves into a work tree whose toplevel is not ``root``.

    A root with its own ``.git`` (or outside any repo) is not foreign. Never
    raises: git absence or probe failure counts as "not foreign" — mode
    resolution handles git absence separately.
    """
    git = git_path()
    if git is None:
        return False
    try:
        proc = subprocess.run(
            [git, "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    if proc.returncode != 0:
        return False  # not inside any repository
    toplevel = Path(proc.stdout.strip()).resolve()
    return toplevel != root.resolve()


def effective_mode(mode_cfg: object, root: Path) -> str:
    """Resolve the effective store mode: ``git-backed`` / ``snapshot`` / ``git-backed-unavailable``.

    ``mode_cfg`` comes straight from the merged backend entry; validation has
    already restricted it to ``git-backed | snapshot`` (Task 1), but a None or
    unexpected value degrades to :data:`DEFAULT_MODE` rather than raising.
    git-backed requires git on PATH and a non-foreign root — otherwise the
    mode is *unavailable* (explicit config fails closed at setup/doctor; it is
    never silently downgraded, ADR 0009).
    """
    mode = mode_cfg if mode_cfg in ("git-backed", "snapshot") else DEFAULT_MODE
    if mode == "snapshot":
        return "snapshot"
    if git_path() is None or nested_in_foreign_repo(root):
        return "git-backed-unavailable"
    return "git-backed"


def init_store(root: Path) -> None:
    """Idempotently prepare the store: mkdir, ``.gitattributes``, git init + seed commit.

    Skips everything when ``root/.git`` already exists (spec A2: "已是仓库则跳过
    全部三步"). Raises ``RuntimeError`` with a named message when git is
    missing, the root is inside another work tree, or a git step fails.
    """
    root.mkdir(parents=True, exist_ok=True)
    git = git_path()
    if git is None:
        raise RuntimeError("git not found on PATH; install git or set backends.local-fs.mode: snapshot")
    if (root / ".git").exists():
        return
    if nested_in_foreign_repo(root):
        raise RuntimeError(
            f"{root} is inside another git work tree; refusing to init "
            "(kgent never commits into a repo it does not own — ADR 0009)"
        )
    attrs = root / ".gitattributes"
    if not attrs.exists():
        attrs.write_text(_GITATTRIBUTES, encoding="utf-8", newline="\n")

    def _run(argv: list[str]) -> None:
        proc = subprocess.run([git, *argv], cwd=root, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(argv)} failed: {proc.stderr.strip()}")

    _run(["init"])
    _run(["add", ".gitattributes"])
    _run([*_flatten(_SEED_COMMIT_ENV), "commit", "--no-gpg-sign", "-m", "kgent: seed local-fs store"])


def _flatten(pairs: list[tuple[str, str]]) -> list[str]:
    return [part for pair in pairs for part in pair]


def dirty_paths(root: Path) -> list[str]:
    """Uncommitted changes per ``git status --porcelain`` (read-only), ``[]`` when clean."""
    git = git_path()
    if git is None:
        return []
    try:
        proc = subprocess.run(
            [git, "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    if proc.returncode != 0:
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]
