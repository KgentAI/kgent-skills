"""P4: Bound.

Final search results ≤ requested top_k, for any fan-out shape.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings, strategies as st

from kgent.adapters import registry
from kgent.router.audit import AuditLog
from kgent.router.core import Router
from kgent.router.journal import Journal
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


@given(
    top_k=st.integers(min_value=1, max_value=20),
    num_docs=st.integers(min_value=0, max_value=30),
)
@settings(max_examples=100, derandomize=True, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_p4_search_results_bounded(tmp_path, monkeypatch, top_k: int, num_docs: int):
    """P4: final search results ≤ requested top_k."""
    # Create a fake backend
    backend = FakeBackend("lark", "internal", _full_caps())
    registry.register("lark", backend)
    try:
        # Seed some docs
        from kgent.types import DocumentMetadata

        for i in range(num_docs):
            metadata = DocumentMetadata(doc_uri="", title=f"Doc {i}", backend="lark")
            backend.create_document(title=f"Doc {i}", content=f"content {i}", metadata=metadata)
        # Build router
        (tmp_path / "config.yaml").write_text(
            "version: 1\ndefaults:\n  routing_mode: configured\n"
            "  default_backends: [lark]\n  approval_ttl_hours: 24\n"
            "  timeouts:\n    search_seconds: 10\n    write_seconds: 30\n"
            "  concurrency:\n    max_parallel_backends: 4\n"
            "backends:\n"
            "  lark:\n    enabled: true\n    type: skill\n"
            "    skill_name: lark-doc\n    trust_zone: internal\n"
            "content_type_mapping:\n  default: lark\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("KGENT_HOME", str(tmp_path))
        from kgent.config.loader import load_effective_config

        config, _ = load_effective_config(tmp_path / "config.yaml", tmp_path, {})
        config.backends["lark"]["capabilities"] = backend.capabilities
        journal = Journal(tmp_path)
        audit = AuditLog(path=tmp_path / "audit.ndjson")
        router = Router(config=config, backends={"lark": backend}, journal=journal, audit=audit)
        # Search
        successes, failures, clamps = router.search_sync("content", top_k=top_k)
        # Results should be bounded by top_k
        assert len(successes) <= top_k
    finally:
        registry.clear()
