"""Setup/doctor confluence legs (ADR 0017): MCP-only transport.

confluence has exactly one transport — the Atlassian Remote MCP server in the
host config (single auth = host OAuth; ADR 0017 supersedes the ADR 0015
ladder). Discovery reports ``transport: "mcp" | "unavailable"``; acli on PATH
is irrelevant (the acli lane is retired). Doctor surfaces the same read-only:
a connected server is healthy-silent, unavailable degrades with a finding.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from kgent.capabilities.detect import confluence_transport, discover
from kgent.config.validate import doctor


def _write_atlassian_mcp(home: Path) -> None:
    (home / ".claude.json").write_text(
        json.dumps({"mcpServers": {"atlassian": {"url": "https://mcp.atlassian.com/v2/mcp"}}}),
        encoding="utf-8",
    )


def _write_other_mcp(home: Path) -> None:
    (home / ".claude.json").write_text(
        json.dumps({"mcpServers": {"context7": {"url": "https://mcp.context7.com/mcp"}}}),
        encoding="utf-8",
    )


class TestTransportMcpOnly:
    def test_mcp_when_atlassian_server_configured(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        _write_atlassian_mcp(home)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("PATH", "")
        assert confluence_transport(dict(os.environ)) == "mcp"

    def test_unavailable_without_atlassian_server(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        _write_other_mcp(home)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("PATH", "")
        assert confluence_transport(dict(os.environ)) == "unavailable"

    def test_acli_on_path_is_irrelevant(self, tmp_path, monkeypatch):
        # ADR 0017: the acli lane is retired — its presence must not flip the
        # transport, even though the official binary may sit on PATH.
        home = tmp_path / "home"
        home.mkdir()
        _write_other_mcp(home)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("PATH", "")
        assert confluence_transport(dict(os.environ)) == "unavailable"

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

    def test_discovery_attaches_mcp_transport(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        skills = home / ".claude" / "skills" / "confluence-integration"
        skills.mkdir(parents=True)
        _write_atlassian_mcp(home)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("PATH", "")
        report = discover(tmp_path, dict(os.environ))
        entry = report.backends.get("confluence")
        assert entry is not None
        assert entry["transport"] == "mcp"

    def test_discovery_marks_unavailable_when_no_server(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        skills = home / ".claude" / "skills" / "confluence-integration"
        skills.mkdir(parents=True)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("PATH", "")
        report = discover(tmp_path, dict(os.environ))
        entry = report.backends.get("confluence")
        assert entry is not None
        assert entry["transport"] == "unavailable"

    def test_no_confluence_entry_without_skill_or_server(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("PATH", "")
        report = discover(tmp_path, dict(os.environ))
        assert report.backends.get("confluence") is None


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

    def test_enabled_with_mcp_is_silent(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        self._config_with_confluence(home, enabled=True)
        _write_atlassian_mcp(home)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("PATH", "")
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
