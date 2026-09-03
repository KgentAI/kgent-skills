"""Approval gates (§3.4, F6 S22–S28).

Platform approvals are **enforced by the router, not advisory**: a gated
write (``WriteProposal.approval_required``) never reaches an adapter without a
valid, unexpired, correctly-bound approval token. This module owns the
approval lifecycle — request/check/decide/execute — plus the two primitives
the router and skills build on:

* :func:`bind_approval` — HMAC-SHA256 over ``(doc_uri, operation, fingerprint)``,
  the cryptographic binding that stops an approval being replayed against
  different content (S24).
* :func:`self_approval_allowed` — the approver policy (§3.4.8): self-approval
  is allowed by default only for documents the requester owns; unknown
  ownership fails closed (S25–S27).
* :func:`fanout_approvals` — one approval per gated target for multi-backend
  writes (S28, §3.4.7).

Backends without approval flow fall back to the standard user-confirmation
proposal — *this* module gates only what is declared gated. The state model:

``pending`` → (decide accept) ``approved`` | (decide reject) ``rejected``;
any non-rejected approval whose ``expires_at`` has passed reports
``expired`` (S23) — expired tokens never execute, and a fresh approval must
be requested with fresh user confirmation.

State/registry caveats, documented for later tasks:

* **Session-bound store.** ``_APPROVALS`` is an in-memory registry; persistent
  approval state (surviving process restarts) is a later task.
* **Placeholder secret.** :data:`SECRET_KEY` is a fixed dev key so binding is
  deterministic in tests; Task 8.4 secrets management provisions the real key
  (rotation: re-request approvals, since bindings are keyed on it).
* **TTL default.** :data:`DEFAULT_TTL_HOURS` mirrors
  ``defaults.approval_ttl_hours`` (schema default 24); the Task 8.x CLI passes
  the config-resolved value explicitly and may drop the constant.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import count as _count

from kgent.errors import ApprovalBindingMismatch, ApprovalRequired
from kgent.fingerprint import content_fingerprint
from kgent.types import ApprovalBinding, ApprovalStatus, ApproverDecision

__all__ = [
    "DEFAULT_TTL_HOURS",
    "SECRET_KEY",
    "Approval",
    "ApprovalPolicy",
    "bind_approval",
    "check_approval",
    "decide",
    "execute_approved",
    "fanout_approvals",
    "request_approval",
    "self_approval_allowed",
]

#: Self-approval policies (§3.4.8).
ApprovalPolicy = str  # "deny" | "owned_only" (default) | "always"

#: Session-bound placeholder signing key (deterministic for tests). Task 8.4
#: secrets management provisions the real key and wires it here.
SECRET_KEY = b"kgent-dev-session-bound-secret-key-placeholder"

#: Default approval TTL in hours — mirrors ``defaults.approval_ttl_hours``.
DEFAULT_TTL_HOURS = 24

#: Monotonic per-process approval-id counter (unique within a session).
_APPROVAL_SEQ = _count(1)

#: In-memory approval registry, keyed by approval id (session-bound).
_APPROVALS: dict[str, Approval] = {}


def _required(msg: str) -> ApprovalRequired:
    """ApprovalRequired whose message names the error class (grep-able, mirrors
    ``VersionConflict on …``)."""
    return ApprovalRequired(f"ApprovalRequired: {msg}")


def _mismatch(msg: str) -> ApprovalBindingMismatch:
    return ApprovalBindingMismatch(f"ApprovalBindingMismatch: {msg}")


def _approval_id() -> str:
    return f"appr-{datetime.now(UTC).strftime('%Y%m%d')}-{next(_APPROVAL_SEQ):02d}"


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class Approval:
    """An approval request (§3.4). Mutable: :func:`decide` advances its state.

    ``token`` is the HMAC binding (:func:`bind_approval`) — the tuple
    ``(doc_uri, operation, content_fingerprint)`` is signed at request time so
    :func:`execute_approved` can detect any tampered binding (S24).
    """

    id: str
    doc_uri: str
    operation: str
    content_fingerprint: str
    expires_at: datetime
    approvers: list[ApproverDecision]
    state: str = "pending"  # pending | approved | rejected | expired
    requested_at: datetime | None = None
    decided_at: datetime | None = None
    token: str = ""


def bind_approval(doc_uri: str, operation: str, fingerprint: str) -> str:
    """HMAC-SHA256 binding keyed on ``(doc_uri, operation, fingerprint)``.

    Deterministic for a given key+triple, so the same content always binds to
    the same token and a different fingerprint yields a different token —
    ``execute_approved`` recomputes and cross-checks this signature.
    """
    message = f"({doc_uri}, {operation}, {fingerprint})".encode()
    return hmac.new(SECRET_KEY, message, hashlib.sha256).hexdigest()


def _resolve_ttl(ttl_hours: int | None) -> int:
    """Default the TTL from ``defaults.approval_ttl_hours`` (schema default 24).

    Negative TTLs are accepted as a test lever (S23 builds an already-expired
    approval by ``expires_at`` construction).
    """
    if ttl_hours is not None:
        return ttl_hours
    return DEFAULT_TTL_HOURS


def request_approval(
    doc_uri: str,
    approvers: list[str],
    operation: str = "update",
    *,
    fingerprint: str,
    ttl_hours: int | None = None,
    now: datetime | None = None,
) -> Approval:
    """Open a pending approval bound to ``(doc_uri, operation, fingerprint)``.

    ``expires_at = now + ttl_hours`` (default: ``defaults.approval_ttl_hours``
    → 24 h). ``approvers`` are resolved platform identities (§3.4.8) —
    recorded as :class:`ApproverDecision` rows with ``decision="pending"``.
    ``now`` is an injectable clock for expiry tests (S23 time travel).
    """
    ts = now if now is not None else _utcnow()
    expiry = ts + timedelta(hours=_resolve_ttl(ttl_hours))
    token = bind_approval(doc_uri, operation, fingerprint)
    approval = Approval(
        id=_approval_id(),
        doc_uri=doc_uri,
        operation=operation,
        content_fingerprint=fingerprint,
        expires_at=expiry,
        approvers=[ApproverDecision(approver=a) for a in approvers],
        requested_at=ts,
        token=token,
    )
    _APPROVALS[approval.id] = approval
    return approval


def _current_state(approval: Approval, now: datetime | None) -> str:
    """Derive the live state: expiry overrides pending/approved (S23)."""
    ts = now if now is not None else _utcnow()
    if approval.state == "rejected":
        return "rejected"
    if approval.expires_at is not None and ts > approval.expires_at:
        return "expired"
    return approval.state


def check_approval(approval_id: str, *, now: datetime | None = None) -> ApprovalStatus:
    """Snapshot an approval's status; ``now`` overrides the clock for tests.

    Raises :class:`ApprovalRequired` when no approval record exists.
    """
    approval = _APPROVALS.get(approval_id)
    if approval is None:
        raise _required(f"no approval record for {approval_id!r}")
    return ApprovalStatus(
        approval_id=approval.id,
        state=_current_state(approval, now),
        requested_at=approval.requested_at,
        decided_at=approval.decided_at,
        expires_at=approval.expires_at,
        approvers=list(approval.approvers),
        binding=ApprovalBinding(
            doc_uri=approval.doc_uri,
            operation=approval.operation,
            content_fingerprint=approval.content_fingerprint,
        ),
    )


def decide(
    approval_id: str,
    approver: str,
    decision: str,
    *,
    now: datetime | None = None,
) -> None:
    """Record an approver's decision (``accept`` | ``reject``) and set state.

    The overall approval becomes ``approved``/``rejected`` on this decision;
    per-approver consensus for multi-approver approvals (e.g. majority rules)
    is orchestrated by the skills layer (Task 9.x) — the gate here only
    honors the recorded state. ``now`` overrides the clock for tests.
    """
    approval = _APPROVALS.get(approval_id)
    if approval is None:
        raise _required(f"no approval record for {approval_id!r}")
    if decision not in ("accept", "reject"):
        raise ValueError(f"invalid approval decision {decision!r}: expected 'accept' or 'reject'")
    ts = now if now is not None else _utcnow()
    for i, row in enumerate(approval.approvers):
        if row.approver == approver:
            approval.approvers[i] = ApproverDecision(
                approver=approver, decision=decision, decided_at=ts
            )
            break
    else:
        approval.approvers.append(
            ApproverDecision(approver=approver, decision=decision, decided_at=ts)
        )
    approval.state = "approved" if decision == "accept" else "rejected"
    approval.decided_at = ts


def execute_approved(
    doc_uri: str,
    approval_id: str,
    content: str,
    *,
    valid_fingerprint: str | None = None,
    now: datetime | None = None,
) -> None:
    """Authorize a write iff the token is a valid, unexpired, bound approval.

    Refuses — with zero writes on every path — when:

    * the approval record is missing (→ :class:`ApprovalRequired`),
    * the approval is expired → ``ApprovalRequired`` (S23; state reports
      ``"expired"`` via :func:`check_approval`),
    * the approval is not yet ``approved`` (pending/rejected)
      → ``ApprovalRequired``,
    * the binding does not match this ``(doc_uri, operation, content)`` —
      ``valid_fingerprint`` vs the stored binding, tamper-evident via the HMAC
      re-signature → :class:`ApprovalBindingMismatch` (S24).

    ``valid_fingerprint`` is supplied by the router (computed from the
    proposal); when omitted it is derived from ``content`` (title-less
    fallback — deterministic, documented as content-only).
    """
    approval = _APPROVALS.get(approval_id)
    if approval is None:
        raise _required(f"no approval record for {approval_id!r}")
    state = _current_state(approval, now)
    if state == "expired":
        raise _required(
            f"approval {approval_id!r} expired at "
            f"{approval.expires_at.isoformat() if approval.expires_at else '?'}; "
            "request a fresh approval with user confirmation"
        )
    if state != "approved":
        raise _required(f"approval {approval_id!r} is not approved (state {state!r})")
    if approval.doc_uri != doc_uri:
        raise _mismatch(
            f"approval {approval_id!r} is bound to {approval.doc_uri!r}, not {doc_uri!r}"
        )
    got = valid_fingerprint if valid_fingerprint is not None else content_fingerprint("", content)
    expected = approval.content_fingerprint
    if got != expected or bind_approval(doc_uri, approval.operation, expected) != approval.token:
        raise _mismatch(
            f"approval {approval_id!r} is bound to content fingerprint {expected!r}, got {got!r}"
        )


def self_approval_allowed(
    doc_owner: str | None,
    requester: str,
    policy: ApprovalPolicy = "owned_only",
) -> tuple[bool, str]:
    """Approver policy §3.4.8: may the requester approve their own request?

    ``owned_only`` (default): yes iff ``doc_owner == requester`` (S25);
    otherwise denied with the owner named (S26). Unknown ownership — owner
    ``None`` or empty — **fails closed** (S27). ``deny`` always denies;
    ``always`` always allows; any unknown policy string fails closed.
    """
    if policy == "always":
        return True, ""
    if policy == "deny":
        return False, "self-approval not allowed: policy 'deny'"
    if policy != "owned_only":
        return False, f"self-approval not allowed: unknown policy {policy!r} (fail closed)"
    if not doc_owner:
        return False, "self-approval not allowed: document owner unknown (fail closed)"
    if doc_owner == requester:
        return True, ""
    return False, f"self-approval not allowed: document owned by {doc_owner}"


def fanout_approvals(
    targets: Iterable[tuple[str, str | None]],
    *,
    approvers: list[str] | None = None,
    operation: str = "update",
    fingerprint: str = "",
    ttl_hours: int | None = None,
    now: datetime | None = None,
) -> list[Approval]:
    """One approval per gated target (§3.4.7, S28).

    ``targets`` mirrors ``WriteProposal.targets`` — ``(backend, doc_uri)``
    pairs. Each target needs a concrete ``doc_uri`` to bind against; a
    create-style ``None`` target cannot be approved under a concrete binding
    and fails closed (ValueError).
    """
    out: list[Approval] = []
    for backend_name, doc_uri in targets:
        if doc_uri is None:
            raise ValueError(
                f"fan-out approval for gated backend {backend_name!r} requires a "
                "concrete doc_uri to bind (approvals are bound to a document)"
            )
        out.append(
            request_approval(
                doc_uri,
                approvers or [],
                operation,
                fingerprint=fingerprint,
                ttl_hours=ttl_hours,
                now=now,
            )
        )
    return out
