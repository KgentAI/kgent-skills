"""One end-to-end happy-path test per skill feature.

Skills orchestrate via the real Router (policy, journal, audit) against fake
backends. The e2e fixture from test_cli.py is reused.
"""

# pyright: basic
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
def router(tmp_home, monkeypatch):
    """Build a Router with fake backends + shared config."""
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
    yield r
    registry.clear()


def test_e2e_knowledge_storage_creates_with_provenance(router):
    """store_workflow creates with provenance."""
    from kgent.skills.knowledge_storage import store_workflow

    proposal = store_workflow("save the new doc 'Welcome to kgent'", {}, router)
    assert proposal.operation == "create"
    # pi-lens-ignore: python-sql-injection
    result = router.execute(proposal, confirmation="interactive-yes")
    assert result.exit_code == 0
    assert router.backends["lark"].docs


def test_e2e_knowledge_storage_update_first(router):
    """store_workflow is update-first (N18)."""
    from kgent.skills.knowledge_storage import store_workflow

    p1 = store_workflow("save 'API Guidelines'", {}, router)
    # pi-lens-ignore: python-sql-injection
    router.execute(p1, confirmation="interactive-yes")
    p2 = store_workflow("save 'API Guidelines' - add more details", {}, router)
    assert p2.operation == "update"  # update-first bias
    assert p2.targets[0][1] is not None


def test_e2e_question_answering_cites_sources(router):
    """QA answer cites sources (S68, N11)."""
    from kgent.skills.question_answering import answer

    # Seed a doc
    router.backends["lark"].create_document(
        title="Policy",
        content="Onboarding requires security training.",
        metadata=_meta("lark", "Policy"),
    )
    ans = answer("What does onboarding require?", router)
    assert ans.claims
    assert all(c.source_uri for c in ans.claims if c.supported)


def test_e2e_wiki_setup_multi_target_journaled(router, tmp_home):
    """wiki-setup creates across backends, journaled."""
    from kgent.skills.wiki_setup import setup_wiki

    result = setup_wiki(
        [
            {"title": "Team Wiki", "content": "home", "backend": "lark"},
            {"title": "External", "content": "partner", "backend": "dingtalk"},
        ],
        router,
    )
    assert result.exit_code == 0
    assert router.backends["lark"].docs
    assert router.backends["dingtalk"].docs
    assert Journal(tmp_home).list_ops()  # journaled → undoable
