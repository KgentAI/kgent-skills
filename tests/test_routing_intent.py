"""Routing precedence + selection-grammar tests (§4.1, §4.2, §4.3)
and ``resolve_intent``/adapter-preference tests (§1.5, S58, S59)."""

from dataclasses import fields

import pytest

from kgent.config.schema import Config
from kgent.errors import ConfigError
from kgent.router.resolve import resolve_backends, resolve_intent


def _caps() -> dict:
    """Declared capabilities shared by every backend (all operations satisfied)."""
    return {
        "document_storage": {
            "supported": True,
            "features": ["create", "read", "update", "delete", "list", "archive", "unarchive"],
        },
        "document_search": {"supported": True, "features": {"search_by_keywords": True}},
    }


FULL = _caps()


def _config(
    *,
    routing_mode: str | None = None,
    default_backends: list[str] | None = None,
    content_type_mapping: dict[str, str] | None = None,
    routing_rules: list[dict] | None = None,
    **backend_overrides: dict,
) -> Config:
    """Local builder: lark/dingtalk enabled, wecom disabled, full capabilities.

    Each backend declares an adapter so §1.5 resolution always has something
    to name: lark ships the ``lark-doc`` skill, the others ship CLIs.
    ``backend_overrides`` merge onto the base spec (e.g. ``lark={"capabilities": {}}``
    strips a skill's capability surface to force the CLI fallback).
    """
    backends = {}
    for name in ("lark", "dingtalk", "wecom"):
        spec = {
            "enabled": name != "wecom",
            "type": "skill" if name == "lark" else "cli",
            "skill_name": "lark-doc" if name == "lark" else None,
            "cli_name": None if name == "lark" else f"{name}-cli",
            "trust_zone": "internal" if name == "lark" else "external",
            "capabilities": _caps(),
        }
        override = backend_overrides.get(name)
        if override:
            spec.update(override)
        backends[name] = spec
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


# --------------------------------------------------------------------------
# §1.5 resolve_intent -> RoutingIntent + adapter preference (S58, S59)
# --------------------------------------------------------------------------


def test_s58_router_returns_structured_intent():
    cfg = _config(lark={"skill_name": "lark-doc", "cli_name": "lark-cli"})
    ri = resolve_intent(cfg, "update", doc_uri="kgent://lark/docA")
    assert ri.operation == "update"
    assert ri.doc_uri == "kgent://lark/docA"
    assert ri.query is None
    assert ri.targets[0].backend == "lark"
    assert {"backend", "adapter_type", "adapter_name", "capabilities_needed"} <= {
        f.name for f in fields(ri.targets[0])
    }
    # router does NOT execute writes — intent carries targets + gates only
    assert ri.proposal is None
    assert {g.name for g in ri.policy_gates} >= {"journal", "audit", "sensitivity"}


def test_s59_platform_skill_preferred_over_cli():
    cfg = _config(lark={"skill_name": "lark-doc", "cli_name": "lark-cli", "capabilities": {**FULL}})
    ri = resolve_intent(cfg, "update", doc_uri="kgent://lark/docA")
    t = ri.targets[0]
    assert t.adapter_type == "skill" and t.adapter_name == "lark-doc"


def test_skill_lacking_capability_falls_back_to_cli():
    cfg = _config(lark={"skill_name": "lark-doc", "cli_name": "lark-cli", "capabilities": {}})
    ri = resolve_intent(cfg, "update", doc_uri="kgent://lark/docA")
    t = ri.targets[0]
    assert t.adapter_type == "cli" and t.adapter_name == "lark-cli"


def test_mcp_used_when_no_skill_or_cli_declared():
    cfg = _config(
        lark={"skill_name": None, "cli_name": None, "mcp_url": "https://mcp.example/lark"}
    )
    ri = resolve_intent(cfg, "update", doc_uri="kgent://lark/docA")
    t = ri.targets[0]
    assert t.adapter_type == "mcp" and t.adapter_name == "https://mcp.example/lark"


def test_search_produces_fanned_out_targets():
    cfg = _config()
    ri = resolve_intent(cfg, "search", query="api design")
    assert ri.query == "api design"
    assert len(ri.targets) == 2
    assert {t.backend for t in ri.targets} == {"lark", "dingtalk"}
    # each fan-out target names a concrete adapter
    assert all(t.adapter_name for t in ri.targets)
    # search is read-only: no write gates
    assert ri.policy_gates == []


def test_doc_uri_backend_wins_over_routing_defaults():
    cfg = _config(
        default_backends=["dingtalk"],
        lark={"skill_name": "lark-doc", "cli_name": "lark-cli"},
    )
    ri = resolve_intent(cfg, "update", doc_uri="kgent://lark/docA")
    assert ri.provenance["targets"] == "doc_uri"
    assert [t.backend for t in ri.targets] == ["lark"]


def test_explicit_selection_recorded_in_provenance():
    cfg = _config(lark={"skill_name": "lark-doc", "cli_name": "lark-cli"})
    ri = resolve_intent(cfg, "search", selection="lark")
    assert ri.provenance["targets"] == "explicit"
    assert [t.backend for t in ri.targets] == ["lark"]


def test_approval_gate_descriptor_when_backend_declares_approval_flow():
    cfg = _config(
        lark={
            "skill_name": "lark-doc",
            "cli_name": "lark-cli",
            "approval_flow": {"supported": True},
        }
    )
    ri = resolve_intent(cfg, "update", doc_uri="kgent://lark/docA")
    assert any(g.name == "approval" for g in ri.policy_gates)


def test_unknown_doc_backend_raises_config_error():
    cfg = _config()
    with pytest.raises(ConfigError):
        resolve_intent(cfg, "update", doc_uri="kgent://nope/docA")
