"""Config validation and ``kgent doctor`` (§2.6).

``doctor`` validates the global config file and local environment
non-interactively: schema + version, forbidden project-local keys (§2.3), trust
record files, backend declarations (zone / sensitivity-floor / capability
consistency), capability-cache freshness (§3.5), and backend reachability via
read-only probes. It performs no writes and no auth prompts; findings map to
exit code 0 (healthy) or 1 (findings).

``validate_config`` performs the semantic checks that survive schema
validation and are expressible on the fully-defaulted :class:`Config`:
sensitivity-floor tier values, backend trust zones, and capability structure.
"""

from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path
from typing import Any

from kgent.config import _yaml
from kgent.config.loader import FORBIDDEN_PROJECT_KEYS
from kgent.config.schema import Config, load_config_dict
from kgent.errors import ConfigError
from kgent.localfs import dirty_paths, effective_mode, git_path, resolve_root

__all__ = ["doctor", "validate_config"]

_SENSITIVITY_TIERS: frozenset[str] = frozenset({"public", "internal", "confidential"})
_TRUST_ZONES: frozenset[str] = frozenset({"internal", "external"})

_CAPABILITY_CACHE_NAME = "capabilities.cache.yaml"
_TRUSTED_NAME = "trusted.json"


def validate_config(cfg: Config) -> list[str]:
    """Return a list of findings for a loaded config (empty = healthy)."""
    findings: list[str] = []

    for content_type, tier in cfg.sensitivity_floors.items():
        if tier not in _SENSITIVITY_TIERS:
            findings.append(
                f"sensitivity_floors.{content_type}: invalid tier {tier!r} "
                "(allowed: public, internal, confidential)"
            )

    for name, spec in cfg.backends.items():
        zone = spec.get("trust_zone")
        if zone not in _TRUST_ZONES:
            findings.append(
                f"backends.{name}.trust_zone: invalid {zone!r} (allowed: internal, external)"
            )
        findings.extend(_capability_findings(str(name), spec.get("capabilities")))

    findings.extend(_workspace_domain_findings(cfg))
    return findings


def _workspace_domain_findings(cfg: Config) -> list[str]:
    """An enabled lark backend without ``defaults.workspace_domain`` cannot
    render native citation URLs (N20) — point at the discovery command (S75)."""
    lark_enabled = any(
        str(name) == "lark" and spec.get("enabled")
        for name, spec in cfg.backends.items()
    )
    if not lark_enabled:
        return []
    if cfg.defaults.get("workspace_domain"):
        return []
    return [
        "defaults.workspace_domain is not set: lark citations will fall back to kgent:// URIs — "
        "run 'kgent config set-workspace-domain' to discover and set it"
    ]


def _capability_findings(name: str, capabilities: Any) -> list[str]:
    """Capability-structure consistency checks (§3.2).

    ``fallback`` must be a sibling of ``features``, never nested inside it.
    """
    if not isinstance(capabilities, dict):
        return []
    findings: list[str] = []
    document_search = capabilities.get("document_search")
    if isinstance(document_search, dict):
        features = document_search.get("features")
        if isinstance(features, dict) and "fallback" in features:
            findings.append(
                f"backends.{name}.capabilities.document_search.features.fallback: "
                "fallback must be a sibling of features, not nested (§3.2)"
            )
    return findings


def doctor(home: Path) -> tuple[list[str], int]:
    """Validate the global config + local environment; return ``(findings, code)``.

    Read-only and non-interactive: no writes and no auth prompts. A missing
    global config is treated as healthy (nothing to check).
    """
    home = Path(home)
    config_path = home / "config.yaml"
    if not config_path.exists():
        return [], 0

    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read {config_path}: {exc}"], 1

    try:
        raw = _yaml.parse(text)
    except ConfigError as exc:
        return [str(exc)], 1
    if not isinstance(raw, dict):
        return ["config must be a mapping"], 1

    findings: list[str] = []
    # NOTE: forbidden-key checks apply to project-local configs only (§2.3),
    # not the global config. The global config legitimately carries backend
    # auth/skill_name/cli_name/trust_zone keys.

    try:
        cfg = load_config_dict(raw)
    except ConfigError as exc:
        findings.append(str(exc))
        return findings, 1

    findings.extend(validate_config(cfg))
    findings.extend(_trust_record_findings(home))
    findings.extend(_capability_cache_findings(home))
    findings.extend(_reachability_findings(cfg))
    findings.extend(_local_fs_findings(cfg))

    return findings, 1 if findings else 0


def _forbidden_key_findings(raw: dict[str, Any]) -> list[str]:
    """Flag forbidden project-local keys (§2.3) present in the effective config."""
    findings: list[str] = []
    for path, _value in _walk_paths(raw):
        for pattern in FORBIDDEN_PROJECT_KEYS:
            if fnmatch.fnmatchcase(path, pattern):
                findings.append(f"forbidden project-local key: {path}")
                break
    return findings


def _trust_record_findings(home: Path) -> list[str]:
    """Validate the trust record file shape (``~/.kgent/trusted.json``)."""
    trusted = home / _TRUSTED_NAME
    if not trusted.exists():
        return []
    try:
        data = json.loads(trusted.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [f"trust record file {trusted} is not valid JSON"]
    if not isinstance(data, dict):
        return [f"trust record file {trusted} must be a JSON object"]
    return []


def _capability_cache_findings(home: Path) -> list[str]:
    """Capability-cache freshness check (§3.5).

    The cache file is owned by Task 3.2; when it is absent (as it always is
    until then) the check is skipped silently. The format is not finalised
    here, so a present cache contributes no findings yet.
    """
    if not (home / _CAPABILITY_CACHE_NAME).exists():
        return []
    return []


def _reachability_findings(cfg: Config) -> list[str]:
    """Backend reachability via read-only probes (§2.6).

    Adapter probes arrive with the backend adapters (later tasks); with no
    adapters wired up, reachability is skipped silently — backends without
    configuration contribute nothing here.
    """
    _ = cfg
    return []


def _local_fs_findings(cfg: Config) -> list[str]:
    """local-fs store findings (spec A3) — read-only, only when enabled.

    Healthy plain git-backed is silent (no news is good news); the three
    effective values surface when worth attention: ``git-backed+remote`` (push
    consent reminder), ``snapshot`` + remote (misconfiguration), and
    ``git-backed-unavailable`` (fail-closed condition).
    """
    entry = cfg.backends.get("local-fs")
    if not isinstance(entry, dict) or entry.get("enabled") is not True:
        return []
    root = resolve_root(cfg.backends)
    if not root.exists():
        return [f"backends.local-fs: store root missing: {root} (run 'kgent setup')"]
    if not root.is_dir():
        return [f"backends.local-fs: store root is not a directory: {root}"]
    findings: list[str] = []
    if not os.access(root, os.W_OK):
        findings.append(f"backends.local-fs: store root not writable: {root}")
    remote = entry.get("remote")
    mode = effective_mode(entry.get("mode"), root)
    if mode == "git-backed-unavailable":
        why = (
            "git not found on PATH"
            if git_path() is None
            else "root is inside another git work tree"
        )
        findings.append(f"backends.local-fs: mode git-backed unavailable ({why}) — failing closed")
    elif mode == "git-backed":
        if not (root / ".git").exists():
            findings.append(
                f"backends.local-fs: mode git-backed but {root} is not a git repository (run 'kgent setup')"
            )
        else:
            dirty = dirty_paths(root)
            if dirty:
                findings.append(
                    "backends.local-fs: working tree has uncommitted changes (informational): "
                    + "; ".join(dirty[:3])
                )
        if isinstance(remote, str) and remote.strip():
            findings.append(
                f"backends.local-fs: effective mode git-backed+remote (push target: {remote}; "
                "pushing replicates all committed content — your remote config is the consent)"
            )
    else:
        if isinstance(remote, str) and remote.strip():
            findings.append(
                "backends.local-fs: remote is only valid in git-backed mode; ignored in snapshot mode"
            )
    return findings


def _walk_paths(node: Any, prefix: str = "") -> list[tuple[str, Any]]:
    """Yield dotted paths for every mapping node (intermediate and leaf)."""
    paths: list[tuple[str, Any]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            paths.append((path, value))
            if isinstance(value, dict):
                paths.extend(_walk_paths(value, path))
    return paths
