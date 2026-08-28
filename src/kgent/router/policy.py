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

from kgent.errors import PolicyError, VersionConflict
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

    On a :class:`VersionConflict` the result carries ``exit_code=4``, a
    journal entry with ``status == "conflict"``, the conflict message in
    ``error``, and — best-effort — a ``fresh_proposal`` re-pinned to the
    re-read document's current version (S6/S7).
    """

    op_id: str
    exit_code: int
    journal_entry: dict[str, object]
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


def _capture_before(
    backend: WriteTarget, uri: str
) -> tuple[str | None, dict[str, Any]]:
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
) -> OpResult:
    """Execute the confirmed write and journal one entry (S1–S4, N1).

    A ``"rejected"`` confirmation is refused outright (zero writes, zero
    journal entries) — this is the last line of defense for N1. Otherwise all
    zone checks run before the first write (N4), then only the confirmed
    targets execute, and the journal records exactly the executed uris (N1).
    ``journal`` defaults to the real :class:`~kgent.router.journal.Journal`
    (home from ``KGENT_HOME``/``~/.kgent``); update legs capture the pre-write
    ``content_before`` snapshot before the write (S44). If ``audit`` exposes
    an ``append`` method it is called with a minimal entry (Task 5.5 replaces
    this; otherwise audit is skipped, duck-typed).
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
    op_id = _next_op_id()
    executed: list[str] = []
    snapshots: dict[str, dict[str, Any]] = {}
    for backend_name, uri in proposal.targets:
        backend = backends[backend_name]
        if proposal.operation == "create":
            created_uri = backend.create_document(
                title=proposal.title or "",
                content=proposal.content,
                metadata=_metadata(proposal, backend_name, doc_uri=""),
            )
            executed.append(created_uri)
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
                    approval_token=None,
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
                if audit is not None and hasattr(audit, "append"):
                    cast(Any, audit).append(
                        {
                            "op_id": op_id,
                            "operation": proposal.operation,
                            "targets": executed,
                            "confirmation": confirmation,
                            "ts": ts,
                            "status": "conflict",
                        }
                    )
                return OpResult(
                    op_id=op_id,
                    exit_code=4,
                    journal_entry=conflict_entry,
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
    journal.append(entry)
    if audit is not None and hasattr(audit, "append"):
        cast(Any, audit).append(
            {
                "op_id": op_id,
                "operation": proposal.operation,
                "targets": executed,
                "confirmation": confirmation,
                "ts": ts,
            }
        )
    return OpResult(op_id=op_id, exit_code=0, journal_entry=entry)
