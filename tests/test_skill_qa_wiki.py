"""QA + wiki-setup skill tests (Task 9.3; S68, S69)."""

from __future__ import annotations

import pytest

from kgent.adapters import registry
from kgent.router.audit import AuditLog
from kgent.router.core import Router
from kgent.router.journal import Journal
from kgent.types import DocumentMetadata
from tests.fakes.fake_backend import FakeBackend


def _full_caps() -> dict:
    return {
        "document_storage": {
            "supported": True,
            "features": ["create", "read", "update", "delete", "list"],
        },
        "document_search": {"supported": True, "features": {"search_by_keywords": True}},
        "approval_flow": {"supported": True, "features": ["request_approval", "execute_approved"]},
    }


def _meta(backend: str, title: str) -> DocumentMetadata:
    return DocumentMetadata(doc_uri="", title=title, backend=backend)


@pytest.fixture
def router_env(tmp_home, monkeypatch):
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
        "content_type_mapping:\n  default: lark\n",
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
# S68: QA answers cite sources
# ---------------------------------------------------------------------------


def test_s68_qa_answer_cites_sources(router_env):
    """S68: every factual claim in a QA answer carries a source doc_uri."""
    from kgent.skills.question_answering import answer

    # Seed some docs
    lark = router_env["backends"]["lark"]
    lark.create_document(title="Onboarding", content="Welcome to the team", metadata=_meta("lark", "Onboarding"))
    lark.create_document(title="Benefits", content="Health insurance included", metadata=_meta("lark", "Benefits"))

    result = answer("What is the onboarding process?", router_env["router"])
    # Every claim must have a source_uri
    for claim in result.claims:
        if claim.supported:
            assert claim.source_uri is not None
            assert claim.source_uri.startswith("kgent://")


def test_s68_qa_unsupported_claims_marked(router_env):
    """S68: claims without sources are marked as unsupported, never fabricated."""
    from kgent.skills.question_answering import answer

    result = answer("What is the secret project?", router_env["router"])
    # All claims should be marked unsupported when no source exists
    for claim in result.claims:
        if claim.source_uri is None:
            assert not claim.supported


# ---------------------------------------------------------------------------
# S69: wiki-setup drives approvals and journals
# ---------------------------------------------------------------------------


def test_s69_wiki_setup_creates_with_journal(router_env):
    """S69: wiki-setup creates docs, each confirmed+journaled+undoable."""
    from kgent.skills.wiki_setup import setup_wiki

    items = [
        {"title": "Team Wiki", "content": "Welcome page", "backend": "lark"},
        {"title": "External Docs", "content": "Partner guide", "backend": "dingtalk"},
    ]
    result = setup_wiki(items, router_env["router"])
    assert result.exit_code == 0
    # The multi-target create is journaled (one entry with multiple targets)
    ops = router_env["router"].journal.list_ops()
    assert len(ops) >= 1
    # Docs exist in backends
    assert router_env["backends"]["lark"].docs
    assert router_env["backends"]["dingtalk"].docs


def test_s69_wiki_setup_failed_leg_repairable(router_env):
    """S69: failed leg per-backend is repairable via sync."""
    from kgent.skills.wiki_setup import setup_wiki

    # Inject fault on dingtalk
    router_env["backends"]["dingtalk"].fault = lambda m, kw: (_ for _ in ()).throw(RuntimeError("boom"))
    items = [
        {"title": "Team Wiki", "content": "Welcome", "backend": "lark"},
        {"title": "External Docs", "content": "Partner", "backend": "dingtalk"},
    ]
    result = setup_wiki(items, router_env["router"])
    # Should be partial (exit 2) due to dingtalk failure
    assert result.exit_code == 2
    # Repair
    router_env["backends"]["dingtalk"].fault = None
    partial = router_env["router"].journal.list_partial()
    assert partial
    op_id = partial[0]["op_id"]
    from kgent.router.repair import sync_repair
    repair_result = sync_repair(op_id, journal=router_env["router"].journal, backends=router_env["router"].backends)
    assert repair_result.exit_code == 0
