"""Write-proposal confirmation gate (§5.6, S1–S4, N1).

The N1-critical invariant enforced here: the router never writes without a
*recorded confirmation* that matches the targets actually executed. No write
leg runs that was not confirmed, and the journal entry records exactly the
uris written — no extra legs.

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
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from kgent.errors import PolicyError
from kgent.router.sensitivity import enforce_zone
from kgent.types import DocumentMetadata, WriteProposal

__all__ = ["OpResult", "confirm", "execute_confirmed"]


class WriteTarget(Protocol):
    """Minimal write surface an adapter must expose (create/update for now)."""

    trust_zone: str

    def create_document(self, title: str, content: str, metadata: DocumentMetadata) -> str: ...

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
    """Outcome of an executed write (§5.6)."""

    op_id: str
    exit_code: int
    journal_entry: dict[str, object]


def _metadata(proposal: WriteProposal, backend_name: str, *, doc_uri: str) -> DocumentMetadata:
    """Minimal metadata sidecar for the write adapter."""
    return DocumentMetadata(
        doc_uri=doc_uri,
        title=proposal.title or "",
        backend=backend_name,
        content_type=proposal.content_type,
        sensitivity=proposal.sensitivity,
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
    journal: JournalAppender,
    audit: object | None = None,
) -> OpResult:
    """Execute the confirmed write and journal one entry (S1–S4, N1).

    A ``"rejected"`` confirmation is refused outright (zero writes, zero
    journal entries) — this is the last line of defense for N1. Otherwise all
    zone checks run before the first write (N4), then only the confirmed
    targets execute, and the journal records exactly the executed uris (N1).
    If ``audit`` exposes an ``append`` method it is called with a minimal
    entry (Task 5.5 replaces this; otherwise audit is skipped, duck-typed).
    """
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
    base_id = f"op-{ts}"
    op_id = base_id
    executed: list[str] = []
    for n, (backend_name, uri) in enumerate(proposal.targets):
        op_id = f"{base_id}-{n}"
        backend = backends[backend_name]
        if proposal.operation == "create":
            created_uri = backend.create_document(
                title=proposal.title or "",
                content=proposal.content,
                metadata=_metadata(proposal, backend_name, doc_uri=""),
            )
            executed.append(created_uri)
        elif proposal.operation == "update" and uri is not None:
            backend.update_document(
                doc_uri=uri,
                content=proposal.content,
                metadata=_metadata(proposal, backend_name, doc_uri=uri),
                approval_token=None,
                idempotency_key=op_id,
                expected_version=None,
            )
            executed.append(uri)
        else:
            # delete/archive/unarchive (and any unmapped op) degrade to a safe
            # no-op with a warning until a later task wires them.
            proposal.warnings.append(
                f"operation '{proposal.operation}' not yet wired; "
                f"no-op for '{backend_name}' (create/update only)"
            )

    entry: dict[str, object] = {
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
        "status": "ok",
    }
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
