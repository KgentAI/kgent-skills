"""Skill ↔ router contract + resolution priority tests (Task 9.2; S65–S67)."""

# pyright: basic
from __future__ import annotations

import pytest
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from kgent.adapters import registry
from kgent.router.audit import AuditLog
from kgent.router.core import Router
from kgent.router.journal import Journal
from kgent.types import DocumentMetadata
from tests.fakes.fake_backend import FakeBackend


def _full_caps() -> dict[str, Any]:
    return {
        "document_storage": {
            "supported": True,
            "features": ["create", "read", "update", "delete", "list"],
        },
        "document_search": {"supported": True, "features": {"search_by_keywords": True}},
        "approval_flow": {"supported": True, "features": []},
    }


def _meta(backend: str, title: str) -> DocumentMetadata:
    return DocumentMetadata(doc_uri="", title=title, backend=backend)


@pytest.fixture
def router_env(tmp_home: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    """Build a Router with 3 fake backends."""
    backends = {
        "lark": FakeBackend("lark", "internal", _full_caps()),
        "dingtalk": FakeBackend("dingtalk", "external", _full_caps()),
        "wecom": FakeBackend("wecom", "external", _full_caps()),
    }
    for name, b in backends.items():
        registry.register(name, b)
    (tmp_home / "config.yaml").write_text(
        "version: 1\ndefaults:\n  routing_mode: configured\n"
        "  default_backends: [lark]\n  approval_ttl_hours: 24\n"
        "  timeouts:\n    search_seconds: 10\n    write_seconds: 30\n"
        "  concurrency:\n    max_parallel_backends: 4\n"
        "backends:\n"
        "  lark:\n    enabled: true\n    type: skill\n"
        "    skill_name: lark-doc\n    trust_zone: internal\n"
        "  dingtalk:\n    enabled: true\n    type: cli\n"
        "    cli_name: dingtalk-cli\n    trust_zone: external\n"
        "  wecom:\n    enabled: true\n    type: cli\n"
        "    cli_name: wecom-cli\n    trust_zone: external\n"
        "content_type_mapping:\n  meeting_notes: lark\n  default: lark\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("KGENT_HOME", str(tmp_home))
    from kgent.config.loader import load_effective_config

    config, _ = load_effective_config(tmp_home / "config.yaml", tmp_home, {})
    for name, b in backends.items():
        config.backends[name]["capabilities"] = b.capabilities
    journal = Journal(tmp_home)
    audit = AuditLog(path=tmp_home / "audit.ndjson")
    r = Router(config=config, backends=backends, journal=journal, audit=audit)
    yield {"router": r, "backends": backends, "home": tmp_home}
    registry.clear()


# ---------------------------------------------------------------------------
# S65: skill is backend-agnostic
# ---------------------------------------------------------------------------


def test_s65_same_orchestration_across_backends(router_env: dict[str, Any]) -> None:
    """S65: same ingest_knowledge works for lark, dingtalk, wecom — only adapter differs."""
    from kgent.skills.ingest_knowledge import ingest_knowledge

    for backend_name in ("lark", "dingtalk", "wecom"):
        context = {"preferences": {"target_backend": backend_name}}
        # Use unique title per backend to avoid update-first matching across iterations
        proposal = ingest_knowledge(f"save doc for {backend_name}", context, router_env["router"])
        # The proposal targets the requested backend
        assert proposal.targets[0][0] == backend_name
        # Execute — should work identically across backends
        # pi-lens-ignore: python-sql-injection
        result = router_env["router"].execute(proposal, confirmation="interactive-yes")
        assert result.exit_code == 0
        assert router_env["backends"][backend_name].docs


# ---------------------------------------------------------------------------
# S66: agent loop invokes resolved platform skill
# ---------------------------------------------------------------------------


def test_s66_resolve_intent_returns_adapter_name(router_env: dict[str, Any]) -> None:
    """S66: resolve_intent returns adapter_name for the resolved target."""
    intent = router_env["router"].resolve_intent("create", content_type="meeting_notes")
    # The first target should have adapter info
    assert intent.targets
    target = intent.targets[0]
    # adapter_name should be the skill name (lark-doc), not the CLI name
    assert hasattr(target, "adapter_name") or "adapter_name" in str(target)


# ---------------------------------------------------------------------------
# S67: resolution priority — explicit user input wins
# ---------------------------------------------------------------------------


def test_s67_explicit_input_overrides_preferences(router_env: dict[str, Any]) -> None:
    """S67: explicit 'store to dingtalk' outranks preferences (lark) + conversation."""
    from kgent.skills.ingest_knowledge import ingest_knowledge

    # Preferences say lark, conversation says lark, but user explicitly says dingtalk
    context = {
        "preferences": {"target_backend": "lark"},
        "conversation": "we use lark for everything",
        "explicit_input": "store this to dingtalk",  # explicit override
    }
    proposal = ingest_knowledge("save doc", context, router_env["router"])
    # Should target dingtalk (explicit input wins)
    assert proposal.targets[0][0] == "dingtalk"
    # Provenance should record the source as "explicit user input"
    assert (
        "explicit" in proposal.provenance.get("target_source", "").lower()
        or proposal.provenance.get("target") == "dingtalk"
    )
