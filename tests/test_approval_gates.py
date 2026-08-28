"""Approval gates (§3.4, S22–S28 / F6).

Platform approvals are *enforced by the router, never advisory*: a proposal
flagged ``approval_required`` cannot reach an adapter without a valid,
unexpired, correctly-bound approval token. The approval layer (binding via
HMAC, TTL expiry, per-target fan-out, approver policy) lives in
``kgent.router.approval``; ``execute_confirmed`` enforces the gate.

Scenario contracts (acceptance §2 F6):
- S22: gated update without a token → blocked (ApprovalRequired), zero writes,
  journal status ``"blocked"``, exit 3.
- S23: expired approval → state ``"expired"``; execution refused; re-request
  needs a fresh approval.
- S24: approval bound to fingerprint F1, execution with F2 → binding mismatch,
  zero writes.
- S25: owner == requester (policy ``owned_only``) → self-approval allowed.
- S26: shared doc (owner bob, requester alice) → denied with the exact reason;
  a non-requester approver is required.
- S27: unknown ownership → fail closed.
- S28: fan-out across two gated targets → exactly two approvals; rejecting the
  wecom leg blocks only that leg (op status ``"partial"``, exit 2).
"""

from __future__ import annotations

import pytest

from kgent.errors import ApprovalBindingMismatch, ApprovalRequired
from kgent.fingerprint import content_fingerprint
from kgent.router.approval import (
    check_approval,
    decide,
    execute_approved,
    fanout_approvals,
    request_approval,
    self_approval_allowed,
)
from kgent.router.audit import AuditLog
from kgent.router.journal import Journal
from kgent.router.policy import OpResult, execute_confirmed
from kgent.types import Document, DocumentMetadata, WriteProposal

LARK_URI = "kgent://lark/docShared"
WECOM_URI = "kgent://wecom/docX"


def _prop(**kw: object) -> WriteProposal:
    base: dict[str, object] = {
        "operation": "update",
        "targets": [("lark", LARK_URI)],
        "title": "Retros 2026-08",
        "content": "Retro meeting notes.",
        "content_type": None,
        "sensitivity": "internal",
        "approval_required": True,
        "provenance": {},
        "degraded": [],
        "warnings": [],
        "snapshot_note": "",
    }
    base.update(kw)
    return WriteProposal(**base)  # type: ignore[arg-type]


def _seed_doc(backend: object, uri: str) -> None:
    """Seed a target document directly (no write_calls recorded)."""
    backend.docs[uri] = Document(  # type: ignore[attr-defined]
        doc_uri=uri,
        title="old",
        content="old body",
        metadata=DocumentMetadata(
            doc_uri=uri,
            title="old",
            backend=backend.name,
            version="v1",
            owner="bob",  # type: ignore[attr-defined]
        ),
    )


def _run(
    test_world: dict, prop: WriteProposal, journal: Journal, audit: AuditLog, tokens: dict[str, str]
) -> OpResult:
    return execute_confirmed(
        prop,
        "interactive-yes",
        backends=test_world["backends"],  # type: ignore[arg-type]
        journal=journal,
        audit=audit,
        approval_tokens=tokens,
    )


def test_s22_ungated_direct_write_blocked(test_world):
    """A gated update with no approval token is blocked with ApprovalRequired."""
    journal = Journal()
    audit = AuditLog()
    prop = _prop()  # approval_required=True, no tokens at all
    op = _run(test_world, prop, journal, audit, tokens={})
    # the router rejects the call: policy-rejected, journal "blocked", exit 3
    assert op.exit_code == 3
    assert op.status == "blocked"
    assert "ApprovalRequired" in (op.error or "")
    assert op.journal_entry["status"] == "blocked"
    # zero write calls reach lark
    assert test_world["backends"]["lark"].write_calls == []
    assert journal.latest is not None
    assert journal.latest["status"] == "blocked"


def test_s23_expired_approval_is_rejected(test_world):
    """An approval whose expires_at is in the past reports "expired" and is refused."""
    journal = Journal()
    audit = AuditLog()
    prop = _prop()
    fp = content_fingerprint(prop.title or "", prop.content)
    # ttl_hours=-1 constructs an approval that is already expired (S23: "constructing
    # expired_at in the past") — check_approval must report state "expired".
    appr = request_approval(LARK_URI, ["alice"], "update", fingerprint=fp, ttl_hours=-1)
    status = check_approval(appr.id)
    assert status.state == "expired"
    assert status.expires_at is not None
    # the write does not execute: execute_approved refuses with ApprovalRequired
    with pytest.raises(ApprovalRequired):
        execute_approved(LARK_URI, appr.id, prop.content, valid_fingerprint=fp)
    # the router gate also blocks the expired token: journal "blocked", zero writes
    op = _run(test_world, prop, journal, audit, tokens={LARK_URI: appr.id})
    assert op.exit_code == 3
    assert op.status == "blocked"
    assert test_world["backends"]["lark"].write_calls == []
    assert op.journal_entry["status"] == "blocked"
    # a re-request requires fresh user confirmation: a new request is a new approval
    fresh = request_approval(LARK_URI, ["alice"], "update", fingerprint=fp, ttl_hours=1)
    assert fresh.id != appr.id
    # time-travel sanity: a not-yet-expired approval is still pending
    pending = request_approval(LARK_URI, ["alice"], "update", fingerprint=fp, ttl_hours=1)
    assert check_approval(pending.id).state == "pending"


def test_s24_binding_mismatch_rejected(test_world):
    """An approval bound to fingerprint F1 cannot be executed against content F2."""
    journal = Journal()
    audit = AuditLog()
    prop = _prop()
    fp1 = content_fingerprint(prop.title or "", prop.content)
    appr = request_approval(LARK_URI, ["alice"], "update", fingerprint=fp1)
    decide(appr.id, "alice", "accept")
    assert check_approval(appr.id).state == "approved"
    fp2 = content_fingerprint(prop.title or "", "Different content.")
    with pytest.raises(ApprovalBindingMismatch):
        execute_approved(LARK_URI, appr.id, prop.content, valid_fingerprint=fp2)
    # the router gate computes the proposal's fingerprint and must block too
    _seed_doc(test_world["backends"]["lark"], LARK_URI)
    bad_prop = _prop(content="Different content.")
    op = _run(test_world, prop=bad_prop, journal=journal, audit=audit, tokens={LARK_URI: appr.id})
    assert op.exit_code == 3
    assert op.status == "blocked"
    assert "ApprovalBindingMismatch" in (op.error or "")
    assert test_world["backends"]["lark"].write_calls == []
    assert op.journal_entry["status"] == "blocked"


def test_s24b_correct_binding_then_write_succeeds(test_world):
    """request → check → decide → execute_approved → execute_confirmed writes (positive path)."""
    journal = Journal()
    audit = AuditLog()
    backend = test_world["backends"]["lark"]
    _seed_doc(backend, LARK_URI)
    prop = _prop()
    fp = content_fingerprint(prop.title or "", prop.content)
    appr = request_approval(LARK_URI, ["alice"], "update", fingerprint=fp)
    assert check_approval(appr.id).state == "pending"
    assert check_approval(appr.id).binding is not None
    assert check_approval(appr.id).binding.content_fingerprint == fp  # type: ignore[union-attr]
    decide(appr.id, "alice", "accept")
    assert check_approval(appr.id).state == "approved"
    execute_approved(LARK_URI, appr.id, prop.content, valid_fingerprint=fp)
    op = _run(test_world, prop, journal, audit, tokens={LARK_URI: appr.id})
    assert op.exit_code == 0
    assert op.status == "ok"
    assert len(backend.write_calls) == 1
    assert op.journal_entry["status"] == "ok"
    assert journal.latest["status"] == "ok"


def test_s25_self_approval_own_doc_allowed():
    ok, reason = self_approval_allowed("alice", "alice", "owned_only")
    assert ok
    assert reason == ""
    # the full own-doc flow: alice is requester and sole approver → accepted
    appr = request_approval(LARK_URI, ["alice"], "update", fingerprint="F1")
    decide(appr.id, "alice", "accept")
    assert check_approval(appr.id).state == "approved"


def test_s26_self_approval_shared_doc_denied():
    ok, reason = self_approval_allowed("bob", "alice", "owned_only")
    assert not ok
    assert "self-approval not allowed: document owned by bob" in reason
    # denial requires a non-requester approver — the caller adds one (bob)
    approvers = ["alice", "bob"]
    assert any(approver != "alice" for approver in approvers)
    appr = request_approval(LARK_URI, approvers, "update", fingerprint="F1")
    decide(appr.id, "bob", "accept")
    assert check_approval(appr.id).state == "approved"


def test_s27_unknown_ownership_fails_closed():
    for owner in (None, ""):
        ok, reason = self_approval_allowed(owner, "alice", "owned_only")
        assert not ok
        assert reason  # fail closed with an explanation
    # "deny" policy always denies; "always" always allows
    assert self_approval_allowed("bob", "alice", "deny") == (
        False,
        "self-approval not allowed: policy 'deny'",
    )
    assert self_approval_allowed("bob", "alice", "always") == (True, "")
    # unknown policy strings also fail closed
    ok, reason = self_approval_allowed("bob", "alice", "everyone")  # type: ignore[arg-type]
    assert not ok
    assert reason


def test_s28_fanout_per_target_approvals(test_world):
    """Two gated targets → two approvals; rejecting wecom fails only that leg."""
    journal = Journal()
    audit = AuditLog()
    lark = test_world["backends"]["lark"]
    wecom = test_world["backends"]["wecom"]
    _seed_doc(lark, LARK_URI)
    _seed_doc(wecom, WECOM_URI)
    prop = _prop(targets=[("lark", LARK_URI), ("wecom", WECOM_URI)])
    fp = content_fingerprint(prop.title or "", prop.content)
    approvals = fanout_approvals(
        [("lark", LARK_URI), ("wecom", WECOM_URI)],
        approvers=["alice"],
        operation="update",
        fingerprint=fp,
    )
    # exactly two approvals, one per target
    assert len(approvals) == 2
    by_uri = {a.doc_uri: a for a in approvals}
    assert set(by_uri) == {LARK_URI, WECOM_URI}
    lark_appr = by_uri[LARK_URI]
    wecom_appr = by_uri[WECOM_URI]
    # approve lark, reject wecom — the wecom leg must fail even though its token
    # is supplied (a rejected approval is not a valid token)
    decide(lark_appr.id, "alice", "accept")
    decide(wecom_appr.id, "alice", "reject")
    assert check_approval(wecom_appr.id).state == "rejected"
    op = _run(
        test_world,
        prop,
        journal,
        audit,
        tokens={LARK_URI: lark_appr.id, WECOM_URI: wecom_appr.id},
    )
    assert op.exit_code == 2
    assert op.status == "partial"
    assert "ApprovalRequired" in (op.error or "")
    # lark leg proceeded, wecom leg never wrote
    assert len(lark.write_calls) == 1
    assert wecom.write_calls == []
    # journal keeps one entry per leg: the ok leg and the blocked leg
    statuses = {e["status"] for e in journal.entries}
    assert "ok" in statuses
    assert "blocked" in statuses


def test_approval_binding_deterministic():
    """bind_approval is a deterministic HMAC keyed on (doc_uri, operation, fingerprint)."""
    from kgent.router.approval import bind_approval

    t1 = bind_approval(LARK_URI, "update", "F1")
    t2 = bind_approval(LARK_URI, "update", "F1")
    t3 = bind_approval(LARK_URI, "update", "F2")
    assert t1 == t2
    assert t1 != t3
    assert len(t1) == 64  # sha256 hexdigest


def test_decide_reject_sets_state_and_refuses_execution():
    appr = request_approval(LARK_URI, ["alice"], "update", fingerprint="F1")
    decide(appr.id, "alice", "reject")
    assert check_approval(appr.id).state == "rejected"
    with pytest.raises(ApprovalRequired):
        execute_approved(LARK_URI, appr.id, "", valid_fingerprint="F1")
