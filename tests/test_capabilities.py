"""Capability declaration, fallback resolution, and cache (§3.2, §3.3, §3.5)."""

from kgent.capabilities.cache import effective_capabilities, read_cache, write_cache
from kgent.capabilities.declaration import (
    BUILTIN_FALLBACK,
    CapabilityDeclaration,
    resolve_mode,
)


def test_builtin_fallback_chain():
    decl = CapabilityDeclaration(features={"search_by_keywords": True}, fallback={})
    assert resolve_mode(decl, "hybrid") == "keyword"  # hybrid→semantic→keyword


def test_config_fallback_overrides_builtin():
    decl = CapabilityDeclaration(
        features={"search_by_keywords": True},
        fallback={"search_by_semantics": "search_by_keywords"},
    )
    assert resolve_mode(decl, "search_by_semantics") == "search_by_keywords"


def test_unsupported_returns_none():
    decl = CapabilityDeclaration(features={}, fallback={})
    assert resolve_mode(decl, "hybrid") is None


def test_supported_mode_returned_as_requested():
    decl = CapabilityDeclaration(features={"search_hybrid": True}, fallback={})
    assert resolve_mode(decl, "hybrid") == "hybrid"


def test_supports_accepts_short_aliases():
    decl = CapabilityDeclaration(features={"search_by_keywords": True})
    assert decl.supports("keyword")
    assert decl.supports("search_by_keywords")
    assert not decl.supports("semantic")


def test_fallback_cycle_returns_none():
    decl = CapabilityDeclaration(features={}, fallback={"a": "b", "b": "a"})
    assert resolve_mode(decl, "a") is None


def test_builtin_fallback_constant():
    assert BUILTIN_FALLBACK == {"hybrid": "semantic", "semantic": "keyword"}


def test_config_cannot_assert_unsupported():
    detected = {"document_search": {"features": {"search_by_keywords": True}}}
    declared = {"document_search": {"features": {"search_by_semantics": True}}}
    eff = effective_capabilities(detected, declared)
    assert eff["document_search"]["features"].get("search_by_semantics") is not True


def test_config_narrows():
    detected = {
        "document_search": {"features": {"search_by_keywords": True, "search_by_semantics": True}}
    }
    declared = {"document_search": {"features": {"search_by_semantics": False}}}
    eff = effective_capabilities(detected, declared)
    assert eff["document_search"]["features"]["search_by_semantics"] is False


def test_cache_round_trip(tmp_home):
    caps = {
        "lark": {
            "document_search": {
                "supported": True,
                "features": {"search_by_keywords": True, "search_by_semantics": True},
                "limits": {"max_results": 100},
            }
        }
    }
    write_cache(tmp_home, caps, "2026-08-27T10:00:00Z")
    cached = read_cache(tmp_home)
    assert cached["backends"]["lark"]["detected_at"] == "2026-08-27T10:00:00Z"
    assert cached["backends"]["lark"]["document_search"] == caps["lark"]["document_search"]


def test_cache_preserves_other_backends(tmp_home):
    write_cache(tmp_home, {"lark": {}}, "2026-08-27T10:00:00Z")
    write_cache(tmp_home, {"dingtalk": {}}, "2026-08-27T11:00:00Z")
    cached = read_cache(tmp_home)
    assert set(cached["backends"]) == {"lark", "dingtalk"}
    assert cached["backends"]["lark"]["detected_at"] == "2026-08-27T10:00:00Z"
    assert cached["backends"]["dingtalk"]["detected_at"] == "2026-08-27T11:00:00Z"


def test_read_cache_missing_returns_empty(tmp_home):
    assert read_cache(tmp_home) == {}
