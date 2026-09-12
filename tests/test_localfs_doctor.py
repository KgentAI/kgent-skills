"""kgent doctor local-fs findings (spec A3): read-only, mode-aware, fail-closed."""

# pyright: basic
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kgent import localfs
from kgent.config import validate
from kgent.config.validate import doctor
from kgent.localfs import init_store


def _config(home: Path, entry: str) -> Path:
    (home / "config.yaml").write_text(
        "version: 1\nbackends:\n  local-fs:\n"
        + entry
        + "    type: skill\n    skill_name: local-fs-integration\n    trust_zone: internal\n",
        encoding="utf-8",
        newline="\n",
    )
    return home


def test_doctor_silent_when_disabled_or_absent(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text(
        "version: 1\nbackends: {}\n", encoding="utf-8", newline="\n"
    )
    findings, code = doctor(tmp_path)
    assert code == 0 and not any("local-fs" in f for f in findings)

    findings, code = doctor(_config(tmp_path, "    enabled: false\n"))
    assert code == 0 and not any("local-fs" in f for f in findings)


def test_doctor_root_missing_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KGENT_LOCAL_FS_ROOT", str(tmp_path / "nope"))
    findings, code = doctor(_config(tmp_path, "    enabled: true\n"))
    assert code == 1
    assert any("store root missing" in f and "nope" in f for f in findings)
    assert not (tmp_path / "nope").exists()  # read-only: doctor never creates


def test_doctor_git_backed_healthy_no_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KGENT_LOCAL_FS_ROOT", str(tmp_path / "store"))
    init_store(tmp_path / "store")
    findings, code = doctor(_config(tmp_path, "    enabled: true\n"))
    assert code == 0
    assert not any("local-fs" in f for f in findings)


def test_doctor_git_backed_but_no_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KGENT_LOCAL_FS_ROOT", str(tmp_path / "store"))
    (tmp_path / "store").mkdir()
    findings, code = doctor(_config(tmp_path, "    enabled: true\n"))
    assert code == 1
    assert any("not a git repository" in f for f in findings)


def test_doctor_dirty_tree_is_informational(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KGENT_LOCAL_FS_ROOT", str(tmp_path / "store"))
    root = tmp_path / "store"
    init_store(root)
    (root / "hand-edit.md").write_text("x", encoding="utf-8", newline="\n")
    findings, _code = doctor(_config(tmp_path, "    enabled: true\n"))
    assert any("informational" in f for f in findings)


def test_doctor_git_missing_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KGENT_LOCAL_FS_ROOT", str(tmp_path / "store"))
    (tmp_path / "store").mkdir()
    # git is resolved from two namespaces: effective_mode() looks git_path up in
    # kgent.localfs globals, while the doctor finding names it via the by-name
    # import in kgent.config.validate — patch both.
    monkeypatch.setattr(localfs, "git_path", lambda: None)
    monkeypatch.setattr(validate, "git_path", lambda: None)
    findings, code = doctor(_config(tmp_path, "    enabled: true\n"))
    assert code == 1
    assert any("git-backed unavailable" in f and "git not found on PATH" in f for f in findings)


def test_doctor_foreign_work_tree_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KGENT_LOCAL_FS_ROOT", str(tmp_path / "outer" / "store"))
    outer = tmp_path / "outer"
    outer.mkdir()
    subprocess.run(["git", "init", str(outer)], capture_output=True, text=True, check=True)
    (tmp_path / "outer" / "store").mkdir()
    findings, code = doctor(_config(tmp_path, "    enabled: true\n"))
    assert code == 1
    assert any(
        "git-backed unavailable" in f and "inside another git work tree" in f for f in findings
    )


def test_doctor_snapshot_with_remote_flagged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KGENT_LOCAL_FS_ROOT", str(tmp_path / "store"))
    (tmp_path / "store").mkdir()
    findings, _code = doctor(
        _config(
            tmp_path,
            "    enabled: true\n    mode: snapshot\n    remote: https://git.example.com/x.git\n",
        )
    )
    assert any("only valid in git-backed mode" in f for f in findings)


def test_doctor_snapshot_healthy_no_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KGENT_LOCAL_FS_ROOT", str(tmp_path / "store"))
    (tmp_path / "store").mkdir()  # plain dir: snapshot mode needs no .git
    findings, code = doctor(_config(tmp_path, "    enabled: true\n    mode: snapshot\n"))
    assert code == 0
    assert not any("local-fs" in f for f in findings)


def test_doctor_reports_git_backed_plus_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KGENT_LOCAL_FS_ROOT", str(tmp_path / "store"))
    init_store(tmp_path / "store")
    findings, _ = doctor(
        _config(
            tmp_path,
            "    enabled: true\n    remote: https://git.example.com/x.git\n",
        )
    )
    assert any("git-backed+remote" in f for f in findings)
