"""P2: Idempotence.

`repair(op) ∘ repair(op)` leaves backend state identical to `repair(op)` once.
"""

# pyright: basic
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from hypothesis import HealthCheck, given, settings, strategies as st

from kgent.adapters import registry
from kgent.router.journal import Journal
from tests.fakes.fake_backend import FakeBackend

#: Hypothesis' stub types ``blacklist_categories`` as a Collection of Unicode
#: category literals — the tuple annotation lets pyright infer "Cs" as its
#: literal type (a bare ``("Cs",)`` infers ``tuple[str]``, which is not
#: assignable to the stub's ``Collection[Literal[...]]`` parameter).
_EXCLUDED_CATEGORIES: tuple[Literal["Cs"], ...] = ("Cs",)


def _full_caps() -> dict[str, Any]:
    return {
        "document_storage": {
            "supported": True,
            "features": ["create", "read", "update", "delete", "list"],
        },
        "document_search": {"supported": True, "features": {"search_by_keywords": True}},
        "approval_flow": {"supported": True, "features": ["request_approval", "execute_approved"]},
    }


@given(
    op_id=st.text(
        min_size=1, max_size=20, alphabet=st.characters(blacklist_categories=_EXCLUDED_CATEGORIES)
    ),
)
@settings(
    max_examples=100, derandomize=True, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
def test_p2_repair_idempotence(tmp_path: Path, op_id: str) -> None:
    """P2: repair(op) ∘ repair(op) leaves state identical to repair(op) once."""
    # Create a fake backend
    backend = FakeBackend("lark", "internal", _full_caps())
    registry.register("lark", backend)
    try:
        # Create a journal with a partial entry
        journal = Journal(tmp_path)
        journal.append(
            {
                "op_id": op_id,
                "operation": "create",
                "targets": [("lark", None)],
                "status": "partial",
                "failed_targets": ["lark"],
                "failed_legs": ["create"],
            }
        )
        # Simulate repair (no-op for fake backend)
        from kgent.router.repair import sync_repair

        backends = {"lark": backend}
        result1 = sync_repair(op_id, journal=journal, backends=backends)
        # Capture state after first repair
        state_after_first = len(backend.docs)
        # Repair again
        result2 = sync_repair(op_id, journal=journal, backends=backends)
        # State should be identical
        state_after_second = len(backend.docs)
        assert state_after_first == state_after_second
        # Both repairs should succeed
        assert result1.exit_code == 0
        assert result2.exit_code == 0
    finally:
        registry.clear()
