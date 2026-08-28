"""Capability declaration + fallback resolution (§3.2, §3.3)."""

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
