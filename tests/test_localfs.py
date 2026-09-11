"""local-fs store helper tests (ADR 0007-0009): root/mode resolution, git init, dirty check."""

# pyright: basic
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kgent.localfs import (
    DEFAULT_MODE,
    dirty_paths,
    effective_mode,
    init_store,
    nested_in_foreign_repo,
    resolve_root,
)


def _git() -> str:
    import shutil

    git = shutil.which("git")
    if git is None:  # pragma: no cover - dev/CI environments have git
        pytest.skip("git not available")
    return git


def test_resolve_root_env_overrides_everything(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KGENT_LOCAL_FS_ROOT", str(tmp_path / "env-root"))
    assert resolve_root({"local-fs": {"root": str(tmp_path / "cfg-root")}}) == tmp_path / "env-root"


def test_resolve_root_config_then_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KGENT_LOCAL_FS_ROOT", raising=False)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    assert resolve_root({"local-fs": {"root": str(tmp_path / "cfg-root")}}) == tmp_path / "cfg-root"
    assert resolve_root({}) == tmp_path / ".kgent" / "local-fs"


def test_init_store_git_backed(tmp_path: Path) -> None:
    git = _git()
    root = tmp_path / "store"
    init_store(root)
    assert (root / ".git").exists()
    assert (root / ".gitattributes").read_text(encoding="utf-8") == "* -text\n"
    log = subprocess.run(
        [git, "-C", str(root), "log", "--oneline"], capture_output=True, text=True, check=True
    )
    assert len(log.stdout.strip().splitlines()) == 1  # seed commit


def test_init_store_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "store"
    init_store(root)
    (root / "keep.md").write_text("keep", encoding="utf-8", newline="\n")
    init_store(root)  # second run: no re-init, no second commit, attributes untouched
    log = subprocess.run(
        ["git", "-C", str(root), "log", "--oneline"], capture_output=True, text=True, check=True
    )
    assert len(log.stdout.strip().splitlines()) == 1


def test_init_store_refuses_foreign_work_tree(tmp_path: Path) -> None:
    _git()
    outer = tmp_path / "outer"
    outer.mkdir()
    subprocess.run(["git", "init", str(outer)], capture_output=True, text=True, check=True)
    nested = outer / "nested-store"
    with pytest.raises(RuntimeError, match="another git work tree"):
        init_store(nested)


def test_effective_mode_snapshot_short_circuits(tmp_path: Path) -> None:
    assert effective_mode("snapshot", tmp_path) == "snapshot"


def test_effective_mode_git_backed_unavailable_without_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import kgent.localfs as localfs

    monkeypatch.setattr(localfs, "git_path", lambda: None)
    assert effective_mode("git-backed", tmp_path) == "git-backed-unavailable"


def test_dirty_paths_empty_then_dirty(tmp_path: Path) -> None:
    root = tmp_path / "store"
    init_store(root)
    assert dirty_paths(root) == []
    (root / "a.md").write_text("x", encoding="utf-8", newline="\n")
    dirty = dirty_paths(root)
    assert dirty and dirty[0].startswith("??")
