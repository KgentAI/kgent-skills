"""Write-proposal confirmation gate (§5.6, S1–S4, N1) + optimistic concurrency (§3.9, S5–S7).

The N1-critical invariant enforced here: the router never writes without a
*recorded confirmation* that matches the targets actually executed. No write
leg runs that was not confirmed, and the journal entry records exactly the
uris written — no extra legs.

Optimistic concurrency (F2): update legs pass the proposal's read-time
``expected_version`` to the adapter; a :class:`VersionConflict` is journaled
with ``status == "conflict"`` at exit code 4, never re-raised as a generic
error, and a fresh proposal re-pinned to the re-read document's current
version is offered (S6). Backends without revision tokens fall back to an
``updated_at`` comparison (S7).

Two stages:

* :func:`confirm` turns an interactive answer or the ``--yes`` bypass into an
  explicit confirmation token (``"interactive-yes"``, ``"--yes"``, or
  ``"rejected"``). The ``--yes`` bypass still requires explicit ``--backends``
  *and* full (non-empty) content — it never silently bypasses (S3).

* :func:`execute_confirmed` runs every sensitivity zone check *before* the
  first write (so a rejected ``confidential`` write performs zero writes, N4),
  then executes exactly the confirmed targets and appends one journal entry.

Only ``create`` and ``update`` are wired for now; ``delete``/``archive``/
``unarchive`` degrade to a safe no-op with a warning until a later task.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from itertools import count as _count
from typing import Any, Protocol, cast

from kgent.errors import ApprovalBindingMismatch, ApprovalRequired, PolicyError, VersionConflict
from kgent.fingerprint import content_fingerprint
from kgent.router.approval import execute_approved
from kgent.router.concurrency import check_version
from kgent.router.journal import Journal, build_entry
from kgent.router.sensitivity import enforce_zone
from kgent.types import Document, DocumentMetadata, WriteProposal

__all__ = ["OpResult", "confirm", "execute_confirmed"]

#: Monotonic per-process op counter: op ids double as idempotency keys, so
#: they must never be reused within a process (F1 review finding).
_OP_SEQ = _count(1)


def _next_op_id() -> str:
    """Unique ``op-<yyyymmdd>-<seq>`` id (plan format "op-20260826-01")."""
    return f"op-{datetime.now(UTC).strftime('%Y%m%d')}-{next(_OP_SEQ):02d}"


class WriteTarget(Protocol):
    """Minimal write surface an adapter must expose (create/update for now)."""

    trust_zone: str

    def create_document(self, title: str, content: str, metadata: DocumentMetadata) -> str: ...

    def read_document(self, doc_uri: str) -> Document: ...

    def update_document(
        self,
        doc_uri: str,
        content: str,
        metadata: DocumentMetadata,
        approval_token: str | None,
        idempotency_key: str,
        expected_version: str | None,
    ) -> None: ...


class JournalAppender(Protocol):
    """Append-only journal; the Task 5.4 real Journal matches this shape."""

    def append(self, entry: dict[str, object]) -> None: ...


@dataclass(frozen=True, slots=True)
class OpResult:
    """Outcome of an executed write (§5.6).

    ``status``: ``"ok"`` | ``"partial"`` | ``"blocked"`` | ``"conflict"``.
    Approval-blocked legs (§3.4, S22–S28) never write: all-legs-blocked
    journals a ``"blocked"`` entry at exit 3 (policy-rejected); a mix of
    blocked and executed legs is ``"partial"`` at exit 2 with one journal
    entry per leg.

    On a :class:`VersionConflict` the result carries ``exit_code=4``, a
    journal entry with ``status == "conflict"``, the conflict message in
    ``error``, and — best-effort — a ``fresh_proposal`` re-pinned to the
    re-read document's current version (S6/S7).
    """

    op_id: str
    exit_code: int
    journal_entry: dict[str, object]
    status: str = "ok"
    fresh_proposal: WriteProposal | None = None
    error: str | None = None


def _metadata(proposal: WriteProposal, backend_name: str, *, doc_uri: str) -> DocumentMetadata:
    """Minimal metadata sidecar for the write adapter."""
    return DocumentMetadata(
        doc_uri=doc_uri,
        title=proposal.title or "",
        backend=backend_name,
        content_type=proposal.content_type,
        sensitivity=proposal.sensitivity,
    )


def _capture_before(backend: WriteTarget, uri: str) -> tuple[str | None, dict[str, Any]]:
    """Re-read the document to snapshot its pre-write state (S44, best-effort).

    Returns ``(content, metadata_dict)``; on any read failure returns
    ``(None, {})`` and the write proceeds without a snapshot (the adapter
    remains the source of truth).
    """
    try:
        current = backend.read_document(uri)
    except Exception:  # noqa: BLE001 — best-effort snapshot: any failure falls
        # through to a snapshot-less write.
        return None, {}
    meta = current.metadata
    metadata_before: dict[str, Any] = {
        "doc_uri": meta.doc_uri,
        "title": meta.title,
        "backend": meta.backend,
        "version": meta.version,
        "updated_at": meta.updated_at.isoformat() if meta.updated_at is not None else None,
    }
    return current.content, metadata_before


def _no_token_guard(proposal: WriteProposal, backend: WriteTarget, uri: str) -> None:
    """No-token fallback: compare read-time vs current ``updated_at`` (S7).

    Best-effort — if the current document cannot be re-read (e.g. it was
    deleted on-platform), the write proceeds and the adapter remains the
    source of truth. A mismatch raises :class:`VersionConflict`.
    """
    try:
        current = backend.read_document(uri)
    except Exception:  # noqa: BLE001 — best-effort re-read: any failure falls
        # through to the adapter, which remains the source of truth.
        return
    check_version(
        None,
        current.metadata.version,
        proposal.expected_updated_at,
        current.metadata.updated_at,
        uri,
    )


def _fresh_proposal(
    proposal: WriteProposal, backend: WriteTarget, uri: str
) -> WriteProposal | None:
    """Best-effort re-read → fresh proposal pinned to the current version.

    The user's edit, targets, and every other field are preserved; only the
    read-time version/updated_at are re-pinned (§3.9.3: never auto-merge or
    overwrite — review and retry). Returns ``None`` when the re-read fails.
    """
    try:
        current = backend.read_document(uri)
    except Exception:  # noqa: BLE001 — best-effort re-read: on any failure no
        # fresh proposal is offered.
        return None
    return replace(
        proposal,
        expected_version=current.metadata.version,
        expected_updated_at=current.metadata.updated_at,
    )


def _conflict_entry(
    *,
    op_id: str,
    ts: str,
    proposal: WriteProposal,
    confirmation: str,
    executed: list[str],
) -> dict[str, object]:
    """Journal entry for a failed optimistic-concurrency check (S6/S7).

    Same schema as the ok-path entry with ``status == "conflict"``; targets
    record exactly the uris actually written so far (N1).
    """
    return {
        "schema_version": 1,
        "op_id": op_id,
        "ts": ts,
        "operation": proposal.operation,
        "targets": executed,
        "idempotency_key": op_id,
        "snapshot": {},
        "proposal_hash": hashlib.sha256(repr(proposal).encode("utf-8")).hexdigest(),
        "confirmation": confirmation,
        "sensitivity": proposal.sensitivity,
        "status": "conflict",
    }


def _token_for(
    approval_tokens: dict[str, str] | None, backend_name: str, uri: str | None
) -> str | None:
    """Look up a per-target approval token: by concrete doc_uri, else backend.

    Gated writes bind approvals to a document (§3.4), so the uri is the
    primary key; the backend name is a fallback for create-style targets.
    """
    if not approval_tokens:
        return None
    if uri is not None and uri in approval_tokens:
        return approval_tokens[uri]
    return approval_tokens.get(backend_name)


def _blocked_entry(
    *,
    op_id: str,
    ts: str,
    proposal: WriteProposal,
    confirmation: str,
    blocked_uris: list[str],
) -> dict[str, object]:
    """Journal entry for a leg blocked by the approval gate (§3.4, S22–S28).

    Same fixed schema as the ok-path entry with ``status == "blocked"``;
    ``targets`` names the blocked uris (nothing was written — or, in a
    partial op, these uris specifically were refused).
    """
    return {
        "schema_version": 1,
        "op_id": op_id,
        "ts": ts,
        "operation": proposal.operation,
        "targets": blocked_uris,
        "idempotency_key": op_id,
        "snapshot": {},
        "proposal_hash": hashlib.sha256(repr(proposal).encode("utf-8")).hexdigest(),
        "confirmation": confirmation,
        "sensitivity": proposal.sensitivity,
        "status": "blocked",
    }


def _audit_append(
    audit: object | None,
    *,
    op_id: str,
    ts: str,
    operation: str,
    targets: list[str],
    confirmation: str,
    sensitivity: str,
    outcome: str,
) -> None:
    """Duck-typed §8.4 audit append; skipped when ``audit`` has no append."""
    if audit is not None and hasattr(audit, "append"):
        cast(Any, audit).append(
            {
                "op_id": op_id,
                "ts": ts,
                "operation": operation,
                "targets": targets,
                "confirmation": confirmation,
                "sensitivity": sensitivity,
                "outcome": outcome,
            }
        )


def confirm(
    proposal: WriteProposal,
    mode: str,
    *,
    answer: str = "yes",
    explicit_backends: bool = True,
) -> str:
    """Resolve a confirmation to ``"interactive-yes"`` | ``"--yes"`` | ``"rejected"``.

    Interactive mode accepts exactly ``answer == "yes"``; ``no``/``timeout``/
    ``eof`` reject. The ``--yes`` mode only bypasses when ``explicit_backends``
    is set, targets are non-empty, and ``content`` has ≥1 character; any other
    case rejects and surfaces a ``--yes``-specific warning (S3).
    """
    if mode == "interactive":
        return "interactive-yes" if answer == "yes" else "rejected"
    if mode == "--yes":
        if explicit_backends and proposal.targets and len(proposal.content) >= 1:
            return "--yes"
        reason = "missing explicit --backends"
        if explicit_backends:
            reason = "missing full content to write"
        proposal.warnings.append(f"--yes requires explicit --backends ({reason})")
        return "rejected"
    proposal.warnings.append(f"unknown confirmation mode: {mode}")
    return "rejected"


def execute_confirmed(
    proposal: WriteProposal,
    confirmation: str,
    *,
    backends: dict[str, WriteTarget],
    journal: JournalAppender | None = None,
    audit: object | None = None,
    approval_tokens: dict[str, str] | None = None,
    op_id: str | None = None,
) -> OpResult:
    """Execute the confirmed write and journal one entry per leg (S1–S4, N1).

    A ``"rejected"`` confirmation is refused outright (zero writes, zero
    journal entries) — this is the last line of defense for N1. Otherwise all
    zone checks run before the first write (N4), then only the confirmed
    targets execute, and the journal records exactly the executed uris (N1).

    **Approval gate (§3.4, S22–S28).** When ``proposal.approval_required`` is
    set, each target's leg is verified via :func:`execute_approved` against
    ``approval_tokens`` (keyed by doc_uri, else backend name) *before* the
    adapter call — a missing/expired/rejected (or incorrectly bound) token
    blocks that leg with zero writes. All legs blocked → one ``"blocked"``
    journal entry, exit 3, ``status="blocked"``; some legs blocked → the ok
    legs write, one ``"ok"`` entry and one ``"blocked"`` entry are journaled
    (per leg), exit 2, ``status="partial"``. A verified token is passed to
    the adapter as ``approval_token``; un-gated writes pass ``None``.

    ``journal`` defaults to the real :class:`~kgent.router.journal.Journal`
    (home from ``KGENT_HOME``/``~/.kgent``); update legs capture the pre-write
    ``content_before`` snapshot before the write (S44). If ``audit`` exposes
    an ``append`` method it is called with a full §8.4 entry (op_id,
    operation, targets, confirmation, sensitivity, outcome); otherwise audit
    is skipped, duck-typed.
    """
    if journal is None:
        journal = Journal()
    if confirmation == "rejected":
        raise PolicyError("refusing to execute write: confirmation was rejected")

    # Phase 1 — enforce every zone before any write (N4): a rejected
    # confidential write must perform zero writes.
    for backend_name, _uri in proposal.targets:
        if proposal.sensitivity != "internal":
            enforce_zone(
                proposal.sensitivity,
                backends[backend_name].trust_zone,
                backend_name,
            )

    ts = datetime.now(UTC).isoformat()
    op_id = op_id or _next_op_id()
    executed: list[str] = []
    snapshots: dict[str, dict[str, Any]] = {}
    blocked: list[str] = []
    block_reasons: list[str] = []
    failed_legs: list[str] = []
    failed_targets: list[str] = []
    # Approval gate (§3.4): fingerprint the proposal content once so every
    # gated leg is verified against the same binding.
    write_fingerprint = (
        content_fingerprint(proposal.title or "", proposal.content)
        if proposal.approval_required
        else None
    )
    for backend_name, uri in proposal.targets:
        backend = backends[backend_name]
        token = _token_for(approval_tokens, backend_name, uri)
        if proposal.approval_required:
            # Phase 2a — approval gate per target (§3.4, S22–S28): the leg is
            # verified BEFORE any adapter call; a missing/expired/rejected or
            # incorrectly-bound token blocks the leg with zero writes.
            if uri is None:
                # A gated write must bind to a concrete document; a create
                # target without a doc_uri fails closed (safe).
                blocked.append(backend_name)
                block_reasons.append(
                    "ApprovalRequired: gated target has no concrete doc_uri to bind an approval to"
                )
                continue
            try:
                execute_approved(
                    uri, token or "", proposal.content, valid_fingerprint=write_fingerprint
                )
            except (ApprovalRequired, ApprovalBindingMismatch) as exc:
                blocked.append(uri)
                block_reasons.append(str(exc))
                continue
        if proposal.operation == "create":
            try:
                created_uri = backend.create_document(
                    title=proposal.title or "",
                    content=proposal.content,
                    metadata=_metadata(proposal, backend_name, doc_uri=""),
                )
                executed.append(created_uri)
            except Exception as exc:  # noqa: BLE001 — per-target backend failure
                failed_targets.append(f"{backend_name}: {exc}")
                failed_legs.append(backend_name)
        elif proposal.operation == "update" and uri is not None:
            content_before, metadata_before = _capture_before(backend, uri)
            try:
                if proposal.expected_version is None:
                    # No-token path (§3.9.4): the backend has no revision
                    # token, so guard with the read-time vs current
                    # ``updated_at`` comparison before the write.
                    _no_token_guard(proposal, backend, uri)
                backend.update_document(
                    doc_uri=uri,
                    content=proposal.content,
                    metadata=_metadata(proposal, backend_name, doc_uri=uri),
                    approval_token=(token if proposal.approval_required else None),
                    idempotency_key=op_id,
                    expected_version=proposal.expected_version,
                )
                executed.append(uri)
                if content_before is not None:
                    snapshots[uri] = {
                        "content_before": content_before,
                        "metadata_before": metadata_before,
                    }
            except VersionConflict as exc:
                # F2 (S6/S7): a stale write journals ``status: conflict`` and
                # exits 4 — the conflict is surfaced, never re-raised as a
                # generic error, and a fresh proposal from a re-read is
                # offered so the caller can review-and-retry.
                conflict_entry = _conflict_entry(
                    op_id=op_id,
                    ts=ts,
                    proposal=proposal,
                    confirmation=confirmation,
                    executed=executed,
                )
                journal.append(conflict_entry)
                _audit_append(
                    audit,
                    op_id=op_id,
                    ts=ts,
                    operation=proposal.operation,
                    targets=executed,
                    confirmation=confirmation,
                    sensitivity=proposal.sensitivity,
                    outcome="conflict",
                )
                return OpResult(
                    op_id=op_id,
                    exit_code=4,
                    journal_entry=conflict_entry,
                    status="conflict",
                    fresh_proposal=_fresh_proposal(proposal, backend, uri),
                    error=str(exc),
                )
        else:
            # delete/archive/unarchive (and any unmapped op) degrade to a safe
            # no-op with a warning until a later task wires them.
            proposal.warnings.append(
                f"operation '{proposal.operation}' not yet wired; "
                f"no-op for '{backend_name}' (create/update only)"
            )

    snapshot: dict[str, Any]
    if len(snapshots) == 1:
        snapshot = dict(next(iter(snapshots.values())))
    elif len(snapshots) > 1:
        snapshot = {"targets": dict(snapshots)}
    else:
        snapshot = {}
    entry = build_entry(
        op_id=op_id,
        ts=ts,
        operation=proposal.operation,
        targets=executed,
        idempotency_key=op_id,
        snapshot=snapshot,
        proposal_hash=hashlib.sha256(repr(proposal).encode("utf-8")).hexdigest(),
        confirmation=confirmation,
        sensitivity=proposal.sensitivity,
        status="ok",
        encrypt=getattr(journal, "encrypt", False),
    )
    if blocked:
        # Approval gate (§3.4, S22–S28): blocked legs never wrote. All legs
        # blocked → one "blocked" entry, exit 3 (policy-rejected); a mix of
        # blocked and executed legs → keep one journal entry per leg (ok +
        # blocked), exit 2, status "partial" — each leg is individually
        # reported so sync/repair can target exactly the blocked ones.
        blocked_entry = _blocked_entry(
            op_id=op_id,
            ts=ts,
            proposal=proposal,
            confirmation=confirmation,
            blocked_uris=blocked,
        )
        reason = "; ".join(block_reasons)
        if not executed:
            # All legs blocked: zero writes, but the refusal is journaled
            # (S22 — journal status "blocked", exit 3, policy-rejected).
            journal.append(blocked_entry)
            _audit_append(
                audit,
                op_id=op_id,
                ts=ts,
                operation=proposal.operation,
                targets=executed,
                confirmation=confirmation,
                sensitivity=proposal.sensitivity,
                outcome="blocked",
            )
            return OpResult(
                op_id=op_id,
                exit_code=3,
                journal_entry=blocked_entry,
                status="blocked",
                error=reason,
            )
        journal.append(entry)
        journal.append(blocked_entry)
        _audit_append(
            audit,
            op_id=op_id,
            ts=ts,
            operation=proposal.operation,
            targets=executed,
            confirmation=confirmation,
            sensitivity=proposal.sensitivity,
            outcome="partial",
        )
        return OpResult(
            op_id=op_id,
            exit_code=2,
            journal_entry=entry,
            status="partial",
            error=reason,
        )
    if failed_legs:
        # Backend failure on one or more legs: journal the partial result so
        # ``kgent sync --repair`` can target exactly the failed targets.
        partial_entry = build_entry(
            op_id=op_id,
            ts=ts,
            operation=proposal.operation,
            targets=executed,
            idempotency_key=op_id,
            snapshot=snapshot,
            proposal_hash=hashlib.sha256(repr(proposal).encode("utf-8")).hexdigest(),
            confirmation=confirmation,
            sensitivity=proposal.sensitivity,
            status="partial",
            encrypt=getattr(journal, "encrypt", False),
            failed_targets=failed_targets,
        )
        journal.append(partial_entry)
        _audit_append(
            audit,
            op_id=op_id,
            ts=ts,
            operation=proposal.operation,
            targets=executed,
            confirmation=confirmation,
            sensitivity=proposal.sensitivity,
            outcome="partial",
        )
        reason = "; ".join(failed_targets)
        return OpResult(
            op_id=op_id,
            exit_code=2,
            journal_entry=partial_entry,
            status="partial",
            error=reason,
        )
    journal.append(entry)
    _audit_append(
        audit,
        op_id=op_id,
        ts=ts,
        operation=proposal.operation,
        targets=executed,
        confirmation=confirmation,
        sensitivity=proposal.sensitivity,
        outcome="ok",
    )
    return OpResult(op_id=op_id, exit_code=0, journal_entry=entry, status="ok")
