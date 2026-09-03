"""Write-proposal + confirmation gate (§5.6, S1–S4, N1).

The N1-critical invariant: no write without a recorded confirmation that
matches the executed targets — the router never performs a write leg that was
not confirmed, and the journal entry records exactly the uris actually
executed.
"""

from __future__ import annotations

import pytest

from kgent.errors import PolicyError
from kgent.router.audit import AuditLog
from kgent.router.journal import Journal
from kgent.router.policy import confirm, execute_confirmed
from kgent.types import WriteProposal
from tests.fakes.fake_backend import FakeBackend


def _prop(**kw: object) -> WriteProposal:
    base: dict[str, object] = {
        "operation": "create",
        "targets": [("lark", None)],
        "title": "Retros 2026-08",
        "content": "Retro meeting notes.",
        "content_type": None,
        "sensitivity": "internal",
        "approval_required": False,
        "provenance": {},
        "degraded": [],
        "warnings": [],
        "snapshot_note": "",
    }
    base.update(kw)
    return WriteProposal(**base)  # type: ignore[arg-type]


def test_s1_interactive_confirm_then_write(test_world):
    backend: FakeBackend = test_world["backends"]["lark"]
    journal = Journal()
    audit = AuditLog()
    prop = _prop()
    conf = confirm(prop, "interactive", answer="yes")
    assert conf == "interactive-yes"
    # router executes create on lark and journals the confirmation
    op = execute_confirmed(
        prop, conf, backends=test_world["backends"], journal=journal, audit=audit
    )
    assert len(backend.write_calls) == 1
    assert op.journal_entry["confirmation"] == "interactive-yes"
    assert journal.latest == op.journal_entry


def test_s2_no_confirmation_no_write(test_world):
    prop = _prop()
    for answer in ("no", "timeout", "eof"):
        assert confirm(prop, "interactive", answer=answer) == "rejected"
    # a rejected confirmation must never touch a backend or journal
    assert test_world["backends"]["lark"].write_calls == []


def test_s3_yes_without_backends_does_not_bypass():
    prop = _prop()
    conf = confirm(prop, "--yes", explicit_backends=False)
    assert conf == "rejected"
    # warning containing "--yes requires explicit --backends" is surfaced
    assert any("--yes requires explicit --backends" in w for w in prop.warnings)


def test_s4_yes_with_explicit_backends_but_empty_content_rejects():
    prop = _prop(content="")
    conf = confirm(prop, "--yes", explicit_backends=True)
    assert conf == "rejected"
    # the content-empty guard is a separate rejection reason but must still
    # surface the required warning substring
    assert any("--yes requires explicit --backends" in w for w in prop.warnings)


def test_s4_yes_with_explicit_backends_and_content(test_world):
    backend: FakeBackend = test_world["backends"]["lark"]
    journal = Journal()
    audit = AuditLog()
    prop = _prop()
    conf = confirm(prop, "--yes", explicit_backends=True)
    assert conf == "--yes"
    op = execute_confirmed(
        prop, conf, backends=test_world["backends"], journal=journal, audit=audit
    )
    assert len(backend.write_calls) == 1
    assert op.journal_entry["confirmation"] == "--yes"
    assert journal.latest["confirmation"] == "--yes"


def test_n1_executed_targets_equal_journaled(test_world):
    backend: FakeBackend = test_world["backends"]["lark"]
    journal = Journal()
    audit = AuditLog()
    prop = _prop()
    op = execute_confirmed(
        prop,
        "interactive-yes",
        backends=test_world["backends"],
        journal=journal,
        audit=audit,
    )
    uris = [c["uri"] for c in backend.write_calls]
    assert op.journal_entry["targets"] == uris
    assert journal.latest["targets"] == uris


def test_n4_zones_enforced_before_any_write(test_world):
    """A confidential write to an external-zone backend must do ZERO writes (N4).

    Zone checks run for ALL targets before the first write, so an earlier
    in-zone target is not touched when a later target violates the zone rule.
    """
    journal = Journal()
    audit = AuditLog()
    prop = _prop(
        targets=[("lark", None), ("dingtalk", None)],
        sensitivity="confidential",
    )
    with pytest.raises(PolicyError):
        execute_confirmed(
            prop,
            "interactive-yes",
            backends=test_world["backends"],
            journal=journal,
            audit=audit,
        )
    assert test_world["backends"]["lark"].write_calls == []
    assert test_world["backends"]["dingtalk"].write_calls == []
    assert journal.entries == []


def test_rejected_confirmation_never_executes(test_world):
    backend: FakeBackend = test_world["backends"]["lark"]
    journal = Journal()
    audit = AuditLog()
    prop = _prop()
    with pytest.raises(PolicyError):
        execute_confirmed(
            prop,
            "rejected",
            backends=test_world["backends"],
            journal=journal,
            audit=audit,
        )
    assert backend.write_calls == []
    assert journal.entries == []
