"""Config loading, precedence, and the project trust model (§2.3).

``load_effective_config`` layers configuration in precedence order (highest
wins): CLI overrides > trusted project-local ``.kgent-config.yaml`` > global
``~/.kgent/config.yaml``. Untrusted project-local config is ignored with a
warning; forbidden project-local keys are rejected with a :class:`ConfigError`
naming the offending key.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

from kgent.config import _yaml
from kgent.config.schema import Config, load_config_dict
from kgent.config.trusted import is_trusted
from kgent.errors import ConfigError

__all__ = ["FORBIDDEN_PROJECT_KEYS", "load_effective_config"]

#: Dotted key paths that a project-local config may never contain (§2.3).
#: Wildcard patterns match any backend name; the ``backends.lark.*`` literal
#: is included so membership assertions (S18) hold verbatim.
FORBIDDEN_PROJECT_KEYS: frozenset[str] = frozenset(
    {
        "backends.*.auth",
        "backends.*.skill_name",
        "backends.*.cli_name",
        "backends.*.mcp_url",
        "backends.*.type",
        "backends.*.enabled",
        "backends.*.trust_zone",
        "backends.lark.skill_name",
    }
)

_ALLOWED_PROJECT_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {"version", "defaults", "routing_rules", "content_type_mapping"}
)
_ALLOWED_PROJECT_DEFAULTS_KEYS: frozenset[str] = frozenset({"routing_mode", "default_backends"})

PROJECT_CONFIG_NAME = ".kgent-config.yaml"


def load_effective_config(
    global_path: Path, project_dir: Path, cli_overrides: dict[str, Any]
) -> tuple[Config, list[str]]:
    """Load config applying §2.3 precedence; return ``(config, warnings)``.

    Raises :class:`ConfigError` when a trusted project-local config contains a
    forbidden key, a disallowed section, or targets an unknown backend.
    """
    warnings: list[str] = []
    global_path = Path(global_path)
    global_raw: dict[str, Any] = {}

    if global_path.exists():
        parsed = _yaml.parse(global_path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise ConfigError("config must be a mapping")
        global_raw = parsed
    else:
        warnings.append("no global config")

    project_dir = Path(project_dir)
    project_file = project_dir / PROJECT_CONFIG_NAME
    trusted_path = global_path.parent / "trusted.json"

    project_raw: dict[str, Any] | None = None
    if project_file.exists():
        if is_trusted(project_dir, trusted_path):
            parsed_project = _yaml.parse(project_file.read_text(encoding="utf-8"))
            if not isinstance(parsed_project, dict):
                raise ConfigError("project config must be a mapping")
            project_raw = parsed_project
            _validate_project_keys(project_raw)
            _validate_content_type_mapping(project_raw, global_raw)
        else:
            warnings.append(".kgent-config.yaml (untrusted directory)")

    merged = _merge_project_into_global(global_raw, project_raw)
    merged = _apply_cli_overrides(merged, cli_overrides)
    merged.setdefault("backends", {})

    return load_config_dict(merged), warnings


def _validate_project_keys(project_raw: dict[str, Any]) -> None:
    """Reject forbidden and disallowed keys, naming the offending key (§2.3)."""
    for path, _value in _walk_paths(project_raw):
        for pattern in FORBIDDEN_PROJECT_KEYS:
            if fnmatch.fnmatchcase(path, pattern):
                raise ConfigError(f"forbidden project-local key: {path}")
    for key in project_raw:
        if key not in _ALLOWED_PROJECT_TOP_LEVEL_KEYS:
            raise ConfigError(f"forbidden project-local key: {key}")
    defaults = project_raw.get("defaults")
    if defaults is not None:
        if not isinstance(defaults, dict):
            raise ConfigError("invalid defaults: expected mapping")
        for key in defaults:
            if key not in _ALLOWED_PROJECT_DEFAULTS_KEYS:
                raise ConfigError(f"forbidden project-local key: defaults.{key}")


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


def _validate_content_type_mapping(project_raw: dict[str, Any], global_raw: dict[str, Any]) -> None:
    """Minimal §2.3 backend restriction for ``content_type_mapping``.

    Enforcement is deliberately shallow: without any declared backends we
    cannot judge "unknown", so the deep check is left to Task 4.x / ``kgent
    doctor``. When backends ARE declared, a mapping to an undeclared backend
    is rejected by name.
    """
    mapping = project_raw.get("content_type_mapping")
    if mapping is None:
        return
    if not isinstance(mapping, dict):
        raise ConfigError("invalid content_type_mapping: expected mapping")
    backends = global_raw.get("backends", {})
    known_backends = set(backends) if isinstance(backends, dict) else set()
    if not known_backends:
        return
    for backend in mapping.values():
        if str(backend) not in known_backends:
            raise ConfigError(f"content_type_mapping targets unknown backend: {backend!r}")


def _merge_project_into_global(
    global_raw: dict[str, Any], project_raw: dict[str, Any] | None
) -> dict[str, Any]:
    result = dict(global_raw)
    if not project_raw:
        return result
    project_defaults = project_raw.get("defaults")
    if project_defaults is not None:
        result["defaults"] = _deep_merge(result.get("defaults", {}), project_defaults)
    project_ctm = project_raw.get("content_type_mapping")
    if project_ctm is not None:
        result["content_type_mapping"] = _deep_merge(
            result.get("content_type_mapping", {}), project_ctm
        )
    if "routing_rules" in project_raw:
        result["routing_rules"] = project_raw["routing_rules"]
    if "version" in project_raw:
        result["version"] = project_raw["version"]
    return result


def _apply_cli_overrides(merged: dict[str, Any], cli_overrides: dict[str, Any]) -> dict[str, Any]:
    result = dict(merged)
    for key, value in cli_overrides.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = _deep_merge(existing, value)
        else:
            result[key] = value
    return result


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged
