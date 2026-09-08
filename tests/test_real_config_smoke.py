"""Real-config read-only smoke（gauntlet layer B）。

单测跑在 FakeBackend 上；这层用**真实 ``~/.kgent/config.yaml``** 对**安装件
（PATH 上的 ``kgent``）**做只读触碰——杀 "mock 边界与真实边界不一致" 类
（2026-09-06：真实 LarkAdapter 无 ``trust_zone``，FakeBackend 全绿掩蔽）。

只读：route（本身只读）/ audit / doctor，无任何写。无真实 config（CI）→
skip。``kgent`` 缺席 → skip（装好与否是 artifact-smoke 层的职责）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

CONFIG = Path.home() / ".kgent" / "config.yaml"

requires_config = pytest.mark.skipif(
    not CONFIG.exists(), reason="no real ~/.kgent/config.yaml (CI)"
)
requires_artifact = pytest.mark.skipif(
    shutil.which("kgent") is None, reason="no installed kgent on PATH (artifact-smoke 层职责)"
)

pytestmark = [pytest.mark.e2e, pytest.mark.real_config, requires_config, requires_artifact]


def _kgent(*args: str) -> subprocess.CompletedProcess[str]:
    """跑 PATH 上的安装件（artifact gate 的深测形态），叶子子命令收尾 --json。"""
    return subprocess.run(
        ["kgent", *args, "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        shell=False,
        check=False,
    )


def _backend_names() -> list[str]:
    data = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    return sorted((data.get("backends") or {}).keys())


def test_route_adjudicates_every_configured_backend() -> None:
    """B7 的真实 config 形态：每个已配置 backend 过一遍 route，绝不崩。"""
    for name in _backend_names():
        result = _kgent("route", "--content", "read-only smoke probe", "--backends", name)
        assert result.returncode in (0, 3), (
            f"route crashed on real config for backend {name!r}: {result.stderr}"
        )


def test_route_json_payload_shape() -> None:
    result = _kgent("route", "--content", "smoke", "--backends", "lark")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert "sensitivity" in payload
    assert "allowed_backends" in payload


def test_audit_reads_real_ledger_and_audit_log() -> None:
    result = _kgent("audit")
    assert result.returncode == 0, f"audit crashed on real home: {result.stderr}"


def test_doctor_runs() -> None:
    result = _kgent("doctor")
    assert result.returncode == 0, f"doctor failed on real home: {result.stderr}"
