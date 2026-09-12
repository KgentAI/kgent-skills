"""kgent doctor local-fs findings (spec A3): read-only, mode-aware, fail-closed."""

# pyright: basic
from __future__ import annotations

from pathlib import Path

import pytest

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
