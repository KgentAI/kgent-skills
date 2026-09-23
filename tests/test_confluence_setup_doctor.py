"""Setup/doctor confluence legs (spec 2026-09-22, A2-adjacent): transport ladder.

Discovery reports the confluence entry with its resolved transport
(``acli`` | ``mcp`` | ``unavailable``, ADR 0015): acli on PATH wins; else an
Atlassian server in the host MCP config; else unavailable (reported, not an
enable blocker — the skill degrades). Doctor surfaces the same read-only.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from kgent.capabilities.detect import discover
from kgent.config.validate import doctor

WIN = sys.platform == "win32"


def _fake_acli_dir(tmp_path: Path) -> str:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / ("acli.cmd" if WIN else "acli")
    if WIN:
        stub.write_text("@echo off\r\nexit /b 0\r\n", encoding="ascii")
    else:
        stub.write_text("#!/bin/sh\nexit 0\n", encoding="ascii")
        stub.chmod(0o755)
    return str(bin_dir)


def _write_atlassian_mcp(home: Path) -> None:
    (home / ".claude.json").write_text(
        json.dumps({"mcpServers": {"atlassian": {"url": "https://mcp.atlassian.com/mcp"}}}),
        encoding="utf-8",
    )


class TestDiscoveryTransportLadder:
    def test_skill_prefix_discovers_confluence_integration(self, tmp_path, monkeypatch):
        skills = tmp_path / "home" / ".claude" / "skills" / "confluence-integration"
        skills.mkdir(parents=True)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("PATH", "")
        report = discover(tmp_path, dict(os.environ))
        entry = report.backends.get("confluence")
        assert entry is not None
        assert entry["found_via"] == "skill"
        assert entry["adapter_name"] == "confluence-integration"

    def test_transport_acli_when_on_path(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv(
            "PATH", _fake_acli_dir(tmp_path) + os.pathsep + os.environ.get("PATH", "")
        )
        report = discover(tmp_path, dict(os.environ))
        entry = report.backends.get("confluence")
        assert entry is not None
        assert entry["transport"] == "acli"

    def test_transport_mcp_fallback(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        _write_atlassian_mcp(home)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("PATH", "")
        report = discover(tmp_path, dict(os.environ))
        entry = report.backends.get("confluence")
        assert entry is not None
        assert entry["transport"] == "mcp"

    def test_transport_unavailable_when_neither(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("PATH", "")
        report = discover(tmp_path, dict(os.environ))
        # no skill dir either → backend absent entirely; ladder value is unavailable
        entry = report.backends.get("confluence")
        if entry is not None:
            assert entry["transport"] == "unavailable"
        # and no acli entry may leak in from the bare PATH
        assert report.backends.get("acli") is None


class TestDoctorFindings:
    def _config_with_confluence(self, home: Path, enabled: bool) -> None:
        (home / "config.yaml").write_text(
            "version: 1\n"
            "backends:\n"
            "  confluence:\n"
            f"    enabled: {str(enabled).lower()}\n"
            "    type: skill\n"
            "    skill_name: confluence-integration\n"
            "    trust_zone: internal\n",
            encoding="utf-8",
        )

    def test_enabled_without_transport_reports_unavailable(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        self._config_with_confluence(home, enabled=True)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("PATH", "")
        findings, _code = doctor(home)
        assert any("confluence" in f and "unavailable" in f for f in findings)

    def test_enabled_with_mcp_reports_informational_fallback(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        self._config_with_confluence(home, enabled=True)
        _write_atlassian_mcp(home)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("PATH", "")
        findings, _code = doctor(home)
        assert any("confluence" in f and "transport mcp" in f for f in findings)

    def test_enabled_with_acli_is_silent(self, tmp_path, monkeypatch):
        import os

        home = tmp_path / "home"
        home.mkdir()
        self._config_with_confluence(home, enabled=True)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv(
            "PATH", _fake_acli_dir(tmp_path) + os.pathsep + os.environ.get("PATH", "")
        )
        findings, _code = doctor(home)
        assert not any("confluence" in f for f in findings)

    def test_disabled_confluence_is_silent(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        self._config_with_confluence(home, enabled=False)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("PATH", "")
        findings, _code = doctor(home)
        assert not any("confluence" in f for f in findings)
