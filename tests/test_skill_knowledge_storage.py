"""Knowledge-storage skill tests (Task 9.1; S60–S64).

Tests the ``store_workflow`` function that orchestrates context gathering,
update-first search, proposal building with provenance, and execution via
the Router primitives.
"""

from __future__ import annotations

import pytest

from kgent.adapters import registry
from kgent.router.audit import AuditLog
from kgent.router.core import Router
from kgent.router.journal import Journal
from kgent.types import DocumentMetadata
from tests.fakes.fake_backend import FakeBackend


def _meta(backend: str, title: str) -> DocumentMetadata:
    return DocumentMetadata(doc_uri="", title=title, backend=backend)


def _full_caps() -> dict:
    return {
        "document_storage": {
            "supported": True,
            "features": ["create", "read", "update", "delete", "list"],
        },
        "document_search": {
            "supported": True,
            "features": {"search_by_keywords": True},
        },
        "approval_flow": {"supported": True, "features": []},
    }


@pytest.fixture
def router_env(tmp_home, monkeypatch):
    """Build a Router with fake backends for skill tests."""
    backends = {
        "lark": FakeBackend("lark", "internal", _full_caps()),
        "dingtalk": FakeBackend("dingtalk", "external", _full_caps()),
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
        "content_type_mapping:\n  meeting_notes: lark\n  default: lark\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("KGENT_HOME", str(tmp_home))
    from kgent.config.loader import load_effective_config
    config, _ = load_effective_config(tmp_home / "config.yaml", tmp_home, {})
    # Enrich backends with capabilities
    for name, b in backends.items():
        config.backends[name]["capabilities"] = b.capabilities
    journal = Journal(tmp_home)
    audit = AuditLog(path=tmp_home / "audit.ndjson")
    r = Router(config=config, backends=backends, journal=journal, audit=audit)
    yield {"router": r, "backends": backends, "home": tmp_home}
    registry.clear()


# ---------------------------------------------------------------------------
# S60: context gathering records provenance
# ---------------------------------------------------------------------------


def test_s60_provenance_records_intent_and_target(router_env):
    """S60: provenance records intent=update and target=lark from context."""
    from kgent.skills.knowledge_storage import store_workflow

    # Seed an existing doc
    lark = router_env["backends"]["lark"]
    lark.create_document(
        title="API Design Guidelines",
        content="v1",
        metadata=_meta("lark", "API Design Guidelines"),
    )
    context = {
        "conversation": "discussed API Design Guidelines v2",
        "preferences": {"target_backend": "lark"},
    }
    proposal = store_workflow("save API Design Guidelines", context, router_env["router"])
    # Provenance should record the source of each inferred field
    assert hasattr(proposal, "provenance")
    prov = proposal.provenance
    assert prov.get("intent") == "update"  # from conversation + existing doc
    assert prov.get("target") == "lark"  # from preferences


# ---------------------------------------------------------------------------
# S61: update-first never proposes CREATE when a match exists
# ---------------------------------------------------------------------------


def test_s61_update_first_proposes_update_not_create(router_env):
    """S61: when a matching doc exists, propose UPDATE, never CREATE."""
    from kgent.skills.knowledge_storage import store_workflow

    lark = router_env["backends"]["lark"]
    lark.create_document(title="API Guidelines", content="v1", metadata=_meta("lark", "API Guidelines"))
    context = {}
    proposal = store_workflow("save API Guidelines v2", context, router_env["router"])
    assert proposal.operation == "update"
    assert proposal.targets[0][1] is not None  # has a doc_uri (not None)


def test_s61_no_match_proposes_create(router_env):
    """S61: when no match exists, propose CREATE."""
    from kgent.skills.knowledge_storage import store_workflow

    context = {}
    proposal = store_workflow("save new doc", context, router_env["router"])
    assert proposal.operation == "create"


# ---------------------------------------------------------------------------
# S62: multiple matches offer per-copy options
# ---------------------------------------------------------------------------


def test_s62_multiple_matches_offer_options(router_env):
    """S62: multiple matches → proposal includes match_uris for per-copy options."""
    from kgent.skills.knowledge_storage import store_workflow

    # Seed matching docs in both backends
    lark = router_env["backends"]["lark"]
    dingtalk = router_env["backends"]["dingtalk"]
    lark.create_document(title="API Guidelines", content="lark v1", metadata=_meta("lark", "API Guidelines"))
    dingtalk.create_document(title="API Guidelines", content="dingtalk v1", metadata=_meta("dingtalk", "API Guidelines"))
    context = {}
    proposal = store_workflow("save API Guidelines v2", context, router_env["router"])
    # When multiple matches exist, the proposal should list them
    assert hasattr(proposal, "match_uris")
    assert len(proposal.match_uris) >= 2


# ---------------------------------------------------------------------------
# S63: skill invokes primitives via routing intent
# ---------------------------------------------------------------------------


def test_s63_skill_uses_resolve_intent(router_env):
    """S63: skill calls resolve_intent and consumes targets[0].adapter_name."""
    from kgent.skills.knowledge_storage import store_workflow

    context = {}
    proposal = store_workflow("save doc", context, router_env["router"])
    # The proposal should have targets resolved via resolve_intent
    assert proposal.targets
    # Execute via router (which uses resolve_intent internally)
    result = router_env["router"].execute(proposal, confirmation="interactive-yes")
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# S64: skill write requires confirmation
# ---------------------------------------------------------------------------


def test_s64_unconfirmed_write_blocked(router_env):
    """S64: router blocks unconfirmed skill write (no journal, no backend call)."""
    from kgent.errors import PolicyError
    from kgent.skills.knowledge_storage import store_workflow

    context = {}
    proposal = store_workflow("save doc", context, router_env["router"])
    # Attempt to execute with "rejected" confirmation — raises PolicyError
    with pytest.raises(PolicyError):
        router_env["router"].execute(proposal, confirmation="rejected")
    # No journal entry
    assert router_env["router"].journal.list_ops() == []
    # No backend write
    assert not router_env["backends"]["lark"].docs
