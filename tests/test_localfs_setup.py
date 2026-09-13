"""kgent setup local-fs leg (spec A2): entry, store prep, mode variants, merge-on-rerun."""

# pyright: basic
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kgent.capabilities.detect import _prepare_local_fs_store, discover, setup
from kgent.config import _yaml
from kgent.errors import ConfigError


def _write_config(home: Path, body: str) -> None:
    (home / "config.yaml").write_text(body, encoding="utf-8", newline="\n")


def _backends(home: Path) -> dict:
    raw = _yaml.parse((home / "config.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw["backends"]


def test_discover_always_reports_local_fs(tmp_path: Path) -> None:
    report = discover(tmp_path, {"PATH": "", "HOME": str(tmp_path)})
    entry = report.backends["local-fs"]
    assert entry["found_via"] == "local"
    assert entry["adapter_name"] == "local-fs-integration"
    assert isinstance(entry["git"], bool)
    assert isinstance(entry["rg"], bool)


def test_setup_fresh_appends_disabled_without_store_prep(tmp_path: Path) -> None:
    _report, code = setup(tmp_path)
    assert code == 0
    entry = _backends(tmp_path)["local-fs"]
    assert entry["enabled"] is False
    assert entry["type"] == "skill"
    assert entry["skill_name"] == "local-fs-integration"
    assert entry["trust_zone"] == "internal"
    # disabled fresh append: no store side effects
    assert not (tmp_path / "local-fs").exists()


def test_setup_enabled_git_backed_prepares_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KGENT_LOCAL_FS_ROOT", str(tmp_path / "store"))
    _write_config(
        tmp_path,
        "version: 1\nbackends:\n  local-fs:\n    enabled: true\n    type: skill\n"
        "    skill_name: local-fs-integration\n    trust_zone: internal\n",
    )
    setup(tmp_path)
    root = tmp_path / "store"
    assert (root / ".git").exists()
    assert (root / ".gitattributes").read_text(encoding="utf-8") == "* -text\n"


def test_setup_enabled_snapshot_mode_skips_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KGENT_LOCAL_FS_ROOT", str(tmp_path / "store"))
    _write_config(
        tmp_path,
        "version: 1\nbackends:\n  local-fs:\n    enabled: true\n    type: skill\n"
        "    skill_name: local-fs-integration\n    trust_zone: internal\n    mode: snapshot\n",
    )
    setup(tmp_path)
    root = tmp_path / "store"
    assert root.exists() and not (root / ".git").exists()


def test_setup_git_missing_default_mode_fails_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KGENT_LOCAL_FS_ROOT", str(tmp_path / "store"))
    _write_config(
        tmp_path,
        "version: 1\nbackends:\n  local-fs:\n    enabled: true\n    type: skill\n"
        "    skill_name: local-fs-integration\n    trust_zone: internal\n",
    )
    from kgent import localfs

    monkeypatch.setattr(localfs, "git_path", lambda: None)
    with pytest.raises(ConfigError, match="git not found on PATH"):
        setup(tmp_path)
    assert not (tmp_path / "store" / ".git").exists()


def test_setup_rerun_merges_and_stays_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KGENT_LOCAL_FS_ROOT", str(tmp_path / "store"))
    _write_config(
        tmp_path,
        "version: 1\nbackends:\n  local-fs:\n    enabled: true\n    type: skill\n"
        "    skill_name: local-fs-integration\n    trust_zone: internal\n    root: custom\n",
    )
    setup(tmp_path)
    assert any(tmp_path.glob("config.yaml.bak-*"))  # backup written on rewrite (ADR 0002)
    setup(tmp_path)
    entry = _backends(tmp_path)["local-fs"]
    assert entry["root"] == "custom"  # user keys survive rerun (ADR 0001)
    log = subprocess.run(
        ["git", "-C", str(tmp_path / "store"), "log", "--oneline"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert len(log.stdout.strip().splitlines()) == 1  # still one seed commit


def test_store_prep_noop_when_config_absent(tmp_path: Path) -> None:
    """守卫分支：home 无 config.yaml → store prep 直接返回（A2 无副作用）。"""
    _prepare_local_fs_store(tmp_path)
    assert not (tmp_path / "local-fs").exists()


def test_store_prep_noop_when_config_is_not_a_mapping(tmp_path: Path) -> None:
    """守卫分支：config 顶层不是 mapping（如 list）→ 直接返回，不 raise。"""
    _write_config(tmp_path, "- a\n- b\n")
    _prepare_local_fs_store(tmp_path)
    assert not (tmp_path / "local-fs").exists()


def test_store_prep_noop_when_backends_is_not_a_mapping(tmp_path: Path) -> None:
    """守卫分支：backends 不是 mapping（如 list）→ 直接返回，不 raise。"""
    _write_config(tmp_path, "version: 1\nbackends: []\n")
    _prepare_local_fs_store(tmp_path)
    assert not (tmp_path / "local-fs").exists()
