"""Config schema, defaults, and validation (Appendix C).

Owned by Task 2.1. ``load_config_dict`` validates the top-level shape and
``version``, deep-merges raw values into per-section defaults, and validates
allowed values for ``routing_mode``, ``trust_zone``, ``type``, and the positive
integer fields — raising :class:`~kgent.errors.ConfigError` naming the offending
key on failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kgent.errors import ConfigError

__all__ = ["ALLOWED_TOP_LEVEL_KEYS", "Config", "load_config_dict"]

ALLOWED_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {
        "version",
        "defaults",
        "backends",
        "routing_rules",
        "content_type_mapping",
        "sensitivity_floors",
        "fallback_chains",
        "conflict_resolution",
        "journal",
        "audit",
    }
)

_ROUTING_MODES: frozenset[str] = frozenset({"explicit", "configured", "smart"})
_BACKEND_TYPES: frozenset[str] = frozenset({"skill", "cli", "mcp"})
_TRUST_ZONES: frozenset[str] = frozenset({"internal", "external"})

_DEFAULT_DEFAULTS: dict[str, Any] = {
    "routing_mode": "configured",
    "default_backends": [],
    "approval_ttl_hours": 24,
    "timeouts": {"search_seconds": 10, "write_seconds": 30},
    "concurrency": {"max_parallel_backends": 4},
}

_BACKEND_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "type": None,
    "skill_name": None,
    "cli_name": None,
    "mcp_url": None,
    "trust_zone": "external",
    "capabilities": {},
    "content_types": [],
    "priority": None,
}

_DEFAULT_CONFLICT_RESOLUTION: dict[str, Any] = {
    "enabled": True,
    "strategies": ["link", "comment", "archive", "correct"],
    "require_confirmation": True,
}

_DEFAULT_JOURNAL: dict[str, Any] = {"retention_days": 30, "encrypt": False}

_DEFAULT_AUDIT: dict[str, Any] = {
    "enabled": True,
    "path": "~/.kgent/audit.ndjson",
    "redact_queries": True,
}


@dataclass
class Config:
    """Fully-defaulted, validated configuration (Appendix C)."""

    version: int
    defaults: dict[str, object]
    backends: dict[str, dict]  # type: ignore[type-arg]
    routing_rules: list[dict] = field(default_factory=list)  # type: ignore[type-arg]
    content_type_mapping: dict[str, str] = field(default_factory=dict)
    sensitivity_floors: dict[str, str] = field(default_factory=dict)
    fallback_chains: dict[str, object] = field(default_factory=dict)
    conflict_resolution: dict[str, object] = field(default_factory=dict)
    journal: dict[str, object] = field(default_factory=dict)
    audit: dict[str, object] = field(default_factory=dict)


def load_config_dict(raw: dict[Any, Any]) -> Config:
    """Validate and normalize a raw config dict into a :class:`Config`.

    Raises :class:`ConfigError` on unknown top-level keys (naming the key) and
    on ``version != 1`` (with the ``kgent config migrate`` hint).
    """
    if not isinstance(raw, dict):
        raise ConfigError("config must be a mapping")
    _validate_top_level_keys(raw)
    version = _validate_version(raw)
    if "backends" not in raw:
        raise ConfigError("missing required top-level key: backends")
    return Config(
        version=version,
        defaults=_build_defaults(raw.get("defaults", {})),
        backends=_build_backends(raw.get("backends")),
        routing_rules=_build_routing_rules(raw.get("routing_rules", [])),
        content_type_mapping=_build_string_map(
            raw.get("content_type_mapping", {}), "content_type_mapping"
        ),
        sensitivity_floors=_build_string_map(
            raw.get("sensitivity_floors", {}), "sensitivity_floors"
        ),
        fallback_chains=_build_fallback_chains(raw.get("fallback_chains", {})),
        conflict_resolution=_merge_section(
            raw, "conflict_resolution", _DEFAULT_CONFLICT_RESOLUTION
        ),
        journal=_merge_section(raw, "journal", _DEFAULT_JOURNAL),
        audit=_merge_section(raw, "audit", _DEFAULT_AUDIT),
    )


def _validate_top_level_keys(raw: dict[Any, Any]) -> None:
    for key in raw:
        if key not in ALLOWED_TOP_LEVEL_KEYS:
            raise ConfigError(f"unknown top-level config key: {key!r}")


def _validate_version(raw: dict[Any, Any]) -> int:
    version = raw.get("version")
    if version != 1:
        raise ConfigError(
            f"unsupported config version {version!r}; run 'kgent config migrate' to upgrade"
        )
    return 1


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _merge_section(raw: dict[Any, Any], key: str, default: dict[str, Any]) -> dict[str, Any]:
    value = raw.get(key)
    if value is None:
        return dict(default)
    if not isinstance(value, dict):
        raise ConfigError(f"invalid {key}: expected mapping")
    return _deep_merge(default, value)


def _build_defaults(raw_defaults: Any) -> dict[str, Any]:
    if not isinstance(raw_defaults, dict):
        raise ConfigError("invalid defaults: expected mapping")
    merged = _deep_merge(_DEFAULT_DEFAULTS, raw_defaults)
    _validate_routing_mode(merged)
    _validate_positive_int(merged, "approval_ttl_hours")
    _validate_timeouts(merged)
    _validate_concurrency(merged)
    return merged


def _validate_routing_mode(merged: dict[str, Any]) -> None:
    mode = merged.get("routing_mode")
    if mode not in _ROUTING_MODES:
        raise ConfigError(f"invalid routing_mode: {mode!r} (allowed: explicit, configured, smart)")


def _validate_positive_int(section: dict[str, Any], key: str) -> None:
    value = section.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"invalid {key}: must be a positive int, got {value!r}")


def _validate_timeouts(merged: dict[str, Any]) -> None:
    timeouts = merged.get("timeouts")
    if not isinstance(timeouts, dict):
        raise ConfigError("invalid timeouts: expected mapping")
    for key in ("search_seconds", "write_seconds"):
        value = timeouts.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ConfigError(f"invalid timeouts.{key}: must be a positive int, got {value!r}")


def _validate_concurrency(merged: dict[str, Any]) -> None:
    concurrency = merged.get("concurrency")
    if not isinstance(concurrency, dict):
        raise ConfigError("invalid concurrency: expected mapping")
    value = concurrency.get("max_parallel_backends")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(
            f"invalid concurrency.max_parallel_backends: must be an int >= 1, got {value!r}"
        )


def _build_backends(raw_backends: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw_backends, dict):
        raise ConfigError("invalid backends: expected mapping")
    result: dict[str, dict[str, Any]] = {}
    for name, spec in raw_backends.items():
        if not isinstance(spec, dict):
            raise ConfigError(f"invalid backends.{name}: expected mapping")
        merged = _deep_merge(_BACKEND_DEFAULTS, spec)
        _validate_backend(str(name), merged)
        result[str(name)] = merged
    return result


def _validate_backend(name: str, merged: dict[str, Any]) -> None:
    btype = merged.get("type")
    if btype not in _BACKEND_TYPES:
        raise ConfigError(f"invalid backends.{name}.type: {btype!r} (allowed: skill, cli, mcp)")
    trust_zone = merged.get("trust_zone")
    if trust_zone not in _TRUST_ZONES:
        raise ConfigError(
            f"invalid backends.{name}.trust_zone: {trust_zone!r} (allowed: internal, external)"
        )


def _build_routing_rules(raw_rules: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_rules, list):
        raise ConfigError("invalid routing_rules: expected list")
    return [rule for rule in raw_rules if isinstance(rule, dict)]


def _build_string_map(raw_map: Any, key: str) -> dict[str, str]:
    if not isinstance(raw_map, dict):
        raise ConfigError(f"invalid {key}: expected mapping")
    return {str(k): str(v) for k, v in raw_map.items()}


def _build_fallback_chains(raw_chains: Any) -> dict[str, Any]:
    if not isinstance(raw_chains, dict):
        raise ConfigError("invalid fallback_chains: expected mapping")
    return dict(raw_chains)
