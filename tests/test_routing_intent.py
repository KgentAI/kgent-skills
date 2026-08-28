"""Routing precedence + selection-grammar tests (§4.1, §4.2, §4.3).

Task 4.2 will extend this module with ``resolve_intent`` tests; this section
covers the single precedence chain implemented by ``resolve_backends``.
"""

import pytest

from kgent.config.schema import Config
from kgent.errors import ConfigError
from kgent.router.resolve import resolve_backends


def _caps() -> dict:
    """Declared capabilities shared by every backend (all operations satisfied)."""
    return {
        "document_storage": {
            "supported": True,
            "features": ["create", "read", "update", "delete", "list", "archive", "unarchive"],
        },
        "document_search": {"supported": True, "features": {"search_by_keywords": True}},
    }


def _config(
    *,
    routing_mode: str | None = None,
    default_backends: list[str] | None = None,
    content_type_mapping: dict[str, str] | None = None,
    routing_rules: list[dict] | None = None,
) -> Config:
    """Local builder: lark/dingtalk enabled, wecom disabled, full capabilities."""
    backends = {}
    for name in ("lark", "dingtalk", "wecom"):
        backends[name] = {
            "enabled": name != "wecom",
            "type": "skill" if name == "lark" else "cli",
            "trust_zone": "internal" if name == "lark" else "external",
            "capabilities": _caps(),
        }
    defaults: dict[str, object] = {"default_backends": default_backends or []}
    if routing_mode is not None:
        defaults["routing_mode"] = routing_mode
    return Config(
        version=1,
        defaults=defaults,
        backends=backends,
        routing_rules=routing_rules or [],
        content_type_mapping=content_type_mapping or {},
    )


# --------------------------------------------------------------------------
# §4.1 Step 1: explicit selection overrides everything
# --------------------------------------------------------------------------


def test_explicit_overrides_everything():
    cfg = _config(
        routing_mode="smart",
        default_backends=["lark"],
        content_type_mapping={"x": "lark"},
        routing_rules=[{"match": {"content_type": "x"}, "backends": ["lark"]}],
    )
    assert resolve_backends(cfg, selection="dingtalk", operation="create", content_type="x") == [
        "dingtalk"
    ]


def test_unknown_backend_hard_error():
    cfg = _config()
    with pytest.raises(ConfigError):
        resolve_backends(cfg, selection="nope", operation="create", content_type=None)


def test_all_is_alias_of_all_enabled():
    # wecom disabled -> only lark + dingtalk are enabled with document_search.
    cfg = _config(default_backends=["lark"])
    assert resolve_backends(cfg, selection="all", operation="search", content_type=None) == [
        "lark",
        "dingtalk",
    ]


# --------------------------------------------------------------------------
# §4.1 Steps 2-4: smart rules, mapping, defaults
# --------------------------------------------------------------------------


def test_smart_rule_first_match_wins():
    cfg = _config(
        routing_mode="smart",
        routing_rules=[
            {"match": {"content_type": "x"}, "backends": ["lark"]},
            {"match": {"operation": "create"}, "backends": ["dingtalk"]},
        ],
    )
    assert resolve_backends(cfg, selection=None, operation="create", content_type="x") == ["lark"]


def test_smart_falls_through_to_mapping_when_no_rule_matches():
    cfg = _config(
        routing_mode="smart",
        routing_rules=[{"match": {"content_type": "x"}, "backends": ["lark"]}],
        content_type_mapping={"y": "dingtalk"},
    )
    assert resolve_backends(cfg, selection=None, operation="create", content_type="y") == [
        "dingtalk"
    ]


def test_smart_default_fallback_entry_used_when_nothing_matches():
    cfg = _config(
        routing_mode="smart",
        routing_rules=[
            {"match": {"content_type": "x"}, "backends": ["lark"]},
            {"default": ["dingtalk"]},
        ],
    )
    assert resolve_backends(cfg, selection=None, operation="create", content_type="z") == [
        "dingtalk"
    ]


def test_configured_mode_mapping_default_fallback():
    cfg = _config(
        routing_mode="configured",
        content_type_mapping={"x": "lark", "default": "dingtalk"},
    )
    assert resolve_backends(cfg, selection=None, operation="create", content_type="unknown") == [
        "dingtalk"
    ]


def test_defaults_used_when_mapping_empty():
    cfg = _config(routing_mode="configured", default_backends=["lark", "dingtalk"])
    assert resolve_backends(cfg, selection=None, operation="create", content_type=None) == [
        "lark",
        "dingtalk",
    ]


def test_default_all_configured_for_writes_all_enabled_for_search():
    cfg = _config(routing_mode="configured", content_type_mapping={"doc": "lark"})
    # write default -> all_configured (steps 2-4) -> mapping -> lark
    assert resolve_backends(cfg, selection=None, operation="create", content_type="doc") == ["lark"]
    assert resolve_backends(
        cfg, selection="all_configured", operation="create", content_type="doc"
    ) == ["lark"]
    # search default -> all_enabled (enabled + document_search)
    assert resolve_backends(cfg, selection=None, operation="search", content_type=None) == [
        "lark",
        "dingtalk",
    ]
