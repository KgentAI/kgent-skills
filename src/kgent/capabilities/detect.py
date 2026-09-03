"""Read-only backend discovery and ``kgent setup`` (§2.2, S42, S53, N12).

Discovery is strictly read-only: it performs no sample writes, no document
mutations, and no approval requests. Permitted probes are ``--version`` and
structured capability-introspection output only. Capability data is extracted
from *structured* metadata (skill manifests, MCP tool listings) — never from
free-form ``--help`` prose, so untrusted text can never become configuration
input (N12).

``discover`` scans:

1. ``~/.claude/skills/`` for ``lark-*`` / ``dingtalk-*`` / ``wecom-*`` skill
   directories and reads their structured manifests (``.json``/``.yaml``).
2. ``PATH`` for ``lark-cli`` / ``dingtalk-cli`` / ``wecom-cli``, verifying
   installation with ``--version`` and reading structured ``--describe`` JSON
   when available (else marking capabilities *unverified*).
3. Claude Desktop config for MCP server entries (stub-level: capabilities and
   TLS are recorded as *unverified* until Task 7.x/10.x deepens them).

Authentication is never prompted during discovery; every detected backend
reports ``auth: "deferred"`` (S53).

``setup`` runs discovery against ``os.environ`` and writes the generated
``config.yaml`` (all detected backends ``enabled: false``) plus the capability
cache via :func:`kgent.capabilities.cache.write_cache`, without prompting.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kgent.capabilities.cache import write_cache
from kgent.config import _yaml
from kgent.errors import ConfigError

__all__ = ["DiscoveryReport", "discover", "setup"]

#: Skill directory prefixes mapped to backend names (§2.2 step 1).
_SKILL_PREFIXES: tuple[tuple[str, str], ...] = (
    ("lark", "lark"),
    ("dingtalk", "dingtalk"),
    ("wecom", "wecom"),
)

#: Structured manifest files accepted during skill discovery (never prose).
_MANIFEST_NAMES: tuple[str, ...] = ("manifest.json", "manifest.yaml", "manifest.yml")

#: CLI names mapped to backend names (§2.2 step 2).
_CLI_BACKENDS: tuple[tuple[str, str], ...] = (
    ("lark-cli", "lark"),
    ("dingtalk-cli", "dingtalk"),
    ("wecom-cli", "wecom"),
)

_PLAIN_RE = re.compile(r"^[A-Za-z0-9_./-]+$")
_RESERVED_SCALARS = frozenset({"true", "false", "null", "~"})


@dataclass(frozen=True, slots=True)
class DiscoveryReport:
    """Result of read-only discovery: one entry per detected backend.

    Each backend entry is a mapping with at least ``auth`` (always
    ``"deferred"``), ``capabilities``, ``found_via``, and ``adapter_name``;
    it may also carry ``version``, ``mcp_url``, and an ``unverified`` list of
    aspects that could not be confirmed from structured metadata.
    """

    backends: dict[str, dict[str, Any]]


def discover(home: Path, env: Mapping[str, str]) -> DiscoveryReport:
    """Discover backends read-only; never prompts and never writes (§2.2).

    ``env["PATH"]`` is searched for CLIs and ``env["HOME"]`` locates
    ``~/.claude/skills`` and the Claude Desktop config. ``home`` is the kgent
    home directory (only used as a fallback when no ``HOME`` is set).
    """
    home_path = Path(home)
    path_env = env.get("PATH", "")
    home_env = env.get("HOME") or env.get("USERPROFILE") or str(home_path)

    backends: dict[str, dict[str, Any]] = {}
    backends.update(_discover_skills(Path(home_env)))
    for name, entry in _discover_clis(path_env).items():
        backends.setdefault(name, entry)
    for name, entry in _discover_mcp(Path(home_env), env).items():
        backends.setdefault(name, entry)
    return DiscoveryReport(backends=backends)


def setup(home: Path) -> tuple[DiscoveryReport, int]:
    """Run discovery, then generate ``config.yaml`` + capability cache (§2.2).

    Never prompts. Returns ``(report, 0)``; the report carries one entry per
    detected backend with ``auth: "deferred"``.
    """
    home_path = Path(home)
    report = discover(home_path, os.environ)
    _write_config(home_path, report)
    caps_by_backend: dict[str, dict[str, Any]] = {}
    for name, entry in report.backends.items():
        caps = entry.get("capabilities")
        caps_by_backend[str(name)] = dict(caps) if isinstance(caps, dict) else {}
    write_cache(home_path, caps_by_backend, _now_iso())
    return report, 0


# ---------------------------------------------------------------------------
# Skill discovery (§2.2 step 1)
# ---------------------------------------------------------------------------


def _discover_skills(home_env: Path) -> dict[str, dict[str, Any]]:
    skills_root = home_env / ".claude" / "skills"
    if not skills_root.is_dir():
        return {}
    result: dict[str, dict[str, Any]] = {}
    for skill_dir in sorted((p for p in skills_root.iterdir() if p.is_dir()), key=lambda p: p.name):
        backend = _skill_backend_for(skill_dir.name)
        if backend is None or backend in result:
            continue
        result[backend] = _skill_entry(skill_dir.name, _read_skill_manifest(skill_dir))
    return result


def _skill_backend_for(skill_name: str) -> str | None:
    for prefix, backend in _SKILL_PREFIXES:
        if skill_name.startswith(prefix + "-"):
            return backend
    return None


def _read_skill_manifest(skill_dir: Path) -> dict[str, Any] | None:
    for name in _MANIFEST_NAMES:
        path = skill_dir / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        return _parse_structured(text)
    return None


def _skill_entry(skill_name: str, manifest: dict[str, Any] | None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "auth": "deferred",
        "capabilities": {},
        "found_via": "skill",
        "adapter_name": skill_name,
    }
    if manifest is None:
        entry["unverified"] = ["capabilities"]
        return entry
    caps = manifest.get("capabilities")
    if isinstance(caps, dict):
        entry["capabilities"] = dict(caps)
    else:
        entry["unverified"] = ["capabilities"]
    version = manifest.get("version")
    if version is not None:
        entry["version"] = str(version)
    return entry


def _parse_structured(text: str) -> dict[str, Any] | None:
    """Parse a structured manifest (JSON, then the YAML subset); never prose."""
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, dict):
        return data
    try:
        data = _yaml.parse(text)
    except ConfigError:
        return None
    if isinstance(data, dict):
        return data
    return None


# ---------------------------------------------------------------------------
# CLI discovery (§2.2 step 2)
# ---------------------------------------------------------------------------


def _discover_clis(path_env: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for cli_name, backend in _CLI_BACKENDS:
        exe = shutil.which(cli_name, path=path_env or None)
        if exe is None:
            continue
        version = _probe_version(exe)
        capabilities, verified = _probe_cli_capabilities(exe)
        entry: dict[str, Any] = {
            "auth": "deferred",
            "capabilities": capabilities,
            "found_via": "cli",
            "adapter_name": cli_name,
        }
        if version is not None:
            entry["version"] = version
        if not verified:
            entry["unverified"] = ["capabilities"]
        result[backend] = entry
    return result


def _probe_version(exe: str) -> str | None:
    try:
        proc = subprocess.run(
            [exe, "--version"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or "").strip() or None


def _probe_cli_capabilities(exe: str) -> tuple[dict[str, Any], bool]:
    """Structured ``--describe --json`` output only; never help prose (N12)."""
    try:
        proc = subprocess.run(
            [exe, "--describe", "--json"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return {}, False
    if proc.returncode != 0:
        return {}, False
    try:
        data = json.loads(proc.stdout or "")
    except ValueError:
        return {}, False
    if not isinstance(data, dict):
        return {}, False
    caps = data.get("capabilities")
    return (dict(caps), True) if isinstance(caps, dict) else ({}, False)


# ---------------------------------------------------------------------------
# MCP discovery (§2.2 step 3, stub-level)
# ---------------------------------------------------------------------------


def _discover_mcp(home_env: Path, env: Mapping[str, str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in _mcp_config_paths(home_env, env):
        for name, url in _read_mcp_servers(path).items():
            entry: dict[str, Any] = {
                "auth": "deferred",
                "capabilities": {},
                "found_via": "mcp",
                "adapter_name": None,
                "unverified": ["capabilities", "tls"],
            }
            if url is not None:
                entry["mcp_url"] = url
            result[name] = entry
    return result


def _mcp_config_paths(home_env: Path, env: Mapping[str, str]) -> list[Path]:
    paths = [home_env / ".claude.json"]
    appdata = env.get("APPDATA")
    if appdata:
        paths.append(Path(appdata) / "Claude" / "claude_desktop_config.json")
    paths.append(
        home_env / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    )
    return paths


def _read_mcp_servers(path: Path) -> dict[str, str | None]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        return {}
    result: dict[str, str | None] = {}
    for name, spec in servers.items():
        url: str | None = None
        if isinstance(spec, dict):
            value = spec.get("url")
            if value is None:
                value = spec.get("command")
            url = str(value) if value is not None else None
        elif isinstance(spec, str):
            url = spec
        result[str(name)] = url
    return result


# ---------------------------------------------------------------------------
# config.yaml generation (§2.2 step 4)
# ---------------------------------------------------------------------------


def _write_config(home: Path, report: DiscoveryReport) -> None:
    created = not home.exists()
    home.mkdir(parents=True, exist_ok=True)
    if created:
        os.chmod(home, 0o700)
    text = _emit_config(report)
    path = home / "config.yaml"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, 0o600)


def _emit_config(report: DiscoveryReport) -> str:
    lines = ["version: 1"]
    if not report.backends:
        lines.append("backends: {}")
        return "\n".join(lines) + "\n"
    lines.append("backends:")
    for name in sorted(report.backends):
        entry = report.backends[name]
        btype = _backend_type(entry)
        lines.append(f"  {_scalar(name)}:")
        lines.append("    enabled: false")
        lines.append(f"    type: {btype}")
        if btype == "skill" and entry.get("adapter_name"):
            lines.append(f"    skill_name: {_scalar(entry['adapter_name'])}")
        elif btype == "cli" and entry.get("adapter_name"):
            lines.append(f"    cli_name: {_scalar(entry['adapter_name'])}")
        elif btype == "mcp" and entry.get("mcp_url"):
            lines.append(f"    mcp_url: {_scalar(entry['mcp_url'])}")
        lines.append("    trust_zone: external")
    return "\n".join(lines) + "\n"


def _backend_type(entry: dict[str, Any]) -> str:
    via = entry.get("found_via")
    if via == "mcp":
        return "mcp"
    if via == "cli":
        return "cli"
    return "skill"


def _scalar(value: str) -> str:
    if _PLAIN_RE.match(value) and value.lower() not in _RESERVED_SCALARS:
        return value
    if "'" not in value:
        return f"'{value}'"
    return f'"{value}"'


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
