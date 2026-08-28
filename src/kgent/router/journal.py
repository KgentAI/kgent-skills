"""Append-only write journal + snapshots + undo + retention (§6.7).

The journal is the local, append-only record of every executed write. It is
the source of truth for ``kgent undo`` and ``kgent sync`` and feeds the audit
log (§8.4). Each entry is one JSON object per line (NDJSON) with
``schema_version: 1`` so the file survives forward migration.

Local-state protection (S43): the ``~/.kgent`` home directory is created
``0700`` and every file under it ``0600`` — the journal enforces both on every
append, not just at creation time (a pre-existing directory or file with looser
permissions is tightened).

Confidentiality guard (S51/S52): ``build_entry`` is the *only* place an entry
takes its fixed schema shape. It never serializes fields outside that schema,
so a token/credential passed as an extra keyword (e.g. ``token="sk-live-…"``)
is dropped — it never reaches the file. Separately, when ``sensitivity ==
"confidential"`` and encryption is off, ``snapshot.content_before`` is omitted
so the confidential body is never persisted (metadata only, undo unavailable).

``undo`` restores the pre-write state captured in each entry's snapshot,
best-effort across backends, and journals the undo itself.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from itertools import count as _count
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from kgent.types import Document, DocumentMetadata
from kgent.uri import parse_uri

if TYPE_CHECKING:
    from kgent.router.policy import OpResult

__all__ = ["Journal", "build_entry", "undo", "write_entry"]

#: Monotonic per-process counter so undo op ids never collide (§6.7).
_UNDO_SEQ = _count(1)


class UndoBackend(Protocol):
    """Backend surface ``undo`` needs (read + update + delete for now)."""

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

    def delete_document(
        self,
        doc_uri: str,
        approval_token: str | None,
        idempotency_key: str,
        expected_version: str | None,
    ) -> None: ...


class Journal:
    """Append-only NDJSON write journal under ``<home>/journal/journal.ndjson``.

    ``home`` is the ``~/.kgent`` directory itself (resolved from the
    ``KGENT_HOME`` environment variable when set, else ``~/.kgent``). The
    journal keeps an in-memory index of every entry (loaded on construction,
    extended on append) so ``get``/``list_failed``/``list_partial`` are cheap;
    the on-disk NDJSON file remains the durable source of truth.
    """

    def __init__(
        self,
        home: str | os.PathLike[str] | None = None,
        *,
        encrypt: bool = False,
        retention_days: int = 30,
    ) -> None:
        if home is None:
            home = os.environ.get("KGENT_HOME", str(Path.home() / ".kgent"))
        self.home = Path(home)
        self.encrypt = encrypt
        self.retention_days = retention_days
        self.journal_dir = self.home / "journal"
        self.path = self.journal_dir / "journal.ndjson"
        self.entries: list[dict[str, Any]] = []
        self._by_op: dict[str, dict[str, Any]] = {}
        self._load()

    # -- persistence -----------------------------------------------------

    def _load(self) -> None:
        """Load existing entries (best-effort: malformed lines are skipped)."""
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                self.entries.append(entry)
                op_id = entry.get("op_id")
                if isinstance(op_id, str):
                    self._by_op[op_id] = entry

    def _ensure_permissions(self) -> None:
        """Create/tighten ``~/.kgent`` 0700 and the journal file 0600 (S43)."""
        os.makedirs(self.journal_dir, mode=0o700, exist_ok=True)
        os.chmod(self.home, 0o700)
        os.chmod(self.journal_dir, 0o700)
        if not self.path.exists():
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            os.close(fd)
        os.chmod(self.path, 0o600)

    def append(self, entry: dict[str, Any]) -> None:
        """Append one entry (NDJSON line) and index it in memory."""
        self._ensure_permissions()
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self.entries.append(entry)
        op_id = entry.get("op_id")
        if isinstance(op_id, str):
            self._by_op[op_id] = entry

    def _rewrite(self) -> None:
        """Rewrite the file from ``self.entries`` (used by retention pruning)."""
        self._ensure_permissions()
        tmp = self.path.with_name(self.path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.writelines(json.dumps(entry, ensure_ascii=False) + "\n" for entry in self.entries)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)
        os.chmod(self.path, 0o600)

    # -- queries ---------------------------------------------------------

    def get(self, op_id: str) -> dict[str, Any] | None:
        """Return the entry for ``op_id`` or ``None``."""
        return self._by_op.get(op_id)

    def list_failed(self) -> list[dict[str, Any]]:
        """Entries with ``status == "failed"``."""
        return [e for e in self.entries if e.get("status") == "failed"]

    def list_partial(self) -> list[dict[str, Any]]:
        """Entries with ``status == "partial"``."""
        return [e for e in self.entries if e.get("status") == "partial"]

    def list_ops(self) -> list[dict[str, Any]]:
        """All entries, in append order."""
        return list(self.entries)

    @property
    def latest(self) -> dict[str, Any] | None:
        """The most recent entry (``None`` when the journal is empty)."""
        return self.entries[-1] if self.entries else None

    # -- retention (FM9) -------------------------------------------------

    def prune_older_than(self, days: int) -> int:
        """Drop entries older than ``days`` and rewrite the file (FM9).

        Retention is purely age-based (``ts`` vs ``datetime.now(UTC)``); an
        entry with an unparseable ``ts`` is kept (fail-safe, never silently
        dropped). Returns the number of entries pruned.
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        kept: list[dict[str, Any]] = []
        pruned = 0
        for entry in self.entries:
            ts = entry.get("ts")
            try:
                when = datetime.fromisoformat(str(ts))
            except (TypeError, ValueError):
                kept.append(entry)
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            if when >= cutoff:
                kept.append(entry)
            else:
                pruned += 1
        self.entries = kept
        self._by_op = {e["op_id"]: e for e in kept if isinstance(e.get("op_id"), str)}
        self._rewrite()
        return pruned


def _omit_snapshot_bodies(value: Any) -> Any:
    """Recursively strip every ``content_before`` body from a snapshot (S51).

    Confidential bodies must never reach the journal when encryption is off:
    in the flat single-target shape AND recursively nested per-target under
    ``snapshot["targets"][uri]``. All other keys (``metadata_before`` and any
    future metadata-only fields) are preserved.
    """
    if isinstance(value, dict):
        return {
            key: _omit_snapshot_bodies(val) for key, val in value.items() if key != "content_before"
        }
    if isinstance(value, list):
        return [_omit_snapshot_bodies(item) for item in value]
    return value


def build_entry(
    op_id: str,
    ts: str,
    operation: str,
    targets: list[str],
    idempotency_key: str,
    proposal_hash: str,
    confirmation: str,
    sensitivity: str,
    status: str,
    *,
    schema_version: int = 1,
    snapshot: dict[str, Any] | None = None,
    content_before: str | None = None,
    metadata_before: dict[str, Any] | None = None,
    encrypt: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    """Build a journal entry with exactly the fixed schema (§6.7).

    **Secrets never enter the journal (S52).** ``extra`` swallows any keyword
    that is not part of the fixed schema (``token=…``, ``secret=…``,
    ``credential=…``) and discards it — nothing outside the schema is ever
    serialized. Legitimate document content lives in ``content_before`` and is
    *not* mangled.

    **Confidentiality guard (S51).** When ``sensitivity == "confidential"``
    and ``encrypt`` is ``False``, every ``content_before`` body is omitted —
    the flat single-target one *and* the per-target bodies nested under
    ``snapshot["targets"][uri]`` in multi-target entries — so the confidential
    body is never persisted (metadata only).
    """
    snap: dict[str, Any] = dict(snapshot) if snapshot else {}
    if metadata_before is not None:
        snap["metadata_before"] = metadata_before
    if content_before is not None:
        snap["content_before"] = content_before
    if sensitivity == "confidential" and not encrypt:
        snap = _omit_snapshot_bodies(snap)
    return {
        "schema_version": schema_version,
        "op_id": op_id,
        "ts": ts,
        "operation": operation,
        "targets": targets,
        "idempotency_key": idempotency_key,
        "snapshot": snap,
        "proposal_hash": proposal_hash,
        "confirmation": confirmation,
        "sensitivity": sensitivity,
        "status": status,
    }


#: ``write_entry`` is the plan's name for :func:`build_entry`; both are the
#: single entry-shaping choke point.
write_entry = build_entry


def _undo_op_id(original: str) -> str:
    return f"undo-{original}-{next(_UNDO_SEQ):02d}"


def _undo_entry(
    op_id: str,
    ts: str,
    targets: list[str],
    status: str,
    sensitivity: str,
    confirmation: str,
) -> dict[str, Any]:
    return build_entry(
        op_id=op_id,
        ts=ts,
        operation="undo",
        targets=targets,
        idempotency_key=op_id,
        proposal_hash="",
        confirmation=confirmation,
        sensitivity=sensitivity,
        status=status,
    )


def _content_before_by_uri(snapshot: dict[str, Any], targets: list[str]) -> dict[str, str | None]:
    """Map each update target uri → its pre-write ``content_before``.

    Handles the two snapshot shapes: flat (single target, §6.7 example) and
    ``{"targets": {uri: {…}}}`` (multi-target).
    """
    inner = snapshot.get("targets")
    if isinstance(inner, dict):
        result: dict[str, str | None] = {}
        for key, value in inner.items():
            if isinstance(value, dict):
                cb = value.get("content_before")
                result[str(key)] = cb if isinstance(cb, str) else None
        return result
    if len(targets) == 1 and "content_before" in snapshot:
        cb = snapshot.get("content_before")
        return {targets[0]: cb if isinstance(cb, str) else None}
    return {}


def undo(
    op_id: str,
    *,
    backends: dict[str, UndoBackend],
    journal: Journal,
    audit: object | None = None,
) -> OpResult:
    """Restore the pre-write state recorded for ``op_id`` (§6.7, S44).

    Best-effort across backends: ``update`` legs restore ``content_before``
    onto the document's *current* version (so a concurrent edit is never
    silently clobbered — the adapter raises :class:`VersionConflict`),
    ``create`` legs delete the created document. Unsupported operations and
    missing snapshots (confidential, unencrypted — S51) are reported per-target
    and surfaced in ``error``. The undo itself is journaled.
    """
    # Local import avoids a policy ↔ journal import cycle at module load.
    from kgent.router.policy import OpResult

    entry = journal.get(op_id)
    undo_op_id = _undo_op_id(op_id)
    ts = datetime.now(UTC).isoformat()

    if entry is None:
        error: str | None = f"unknown op id: {op_id!r}"
        undo_entry = _undo_entry(undo_op_id, ts, [], "failed", "internal", "undo")
        journal.append(undo_entry)
        return OpResult(op_id=op_id, exit_code=1, journal_entry=undo_entry, error=error)

    operation = str(entry.get("operation", ""))
    targets = [t for t in (entry.get("targets") or []) if isinstance(t, str)]
    snapshot = entry.get("snapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    sensitivity = str(entry.get("sensitivity", "internal"))
    confirmation = str(entry.get("confirmation", "undo"))

    content_before_by_uri = _content_before_by_uri(snapshot, targets)

    restored: list[str] = []
    failures: list[str] = []
    for uri in targets:
        try:
            backend_name, _ = parse_uri(uri)
            backend = backends[backend_name]
            if operation == "create":
                backend.delete_document(uri, None, undo_op_id, None)
            elif operation == "update":
                content_before = content_before_by_uri.get(uri)
                if content_before is None:
                    failures.append(f"undo unavailable for {uri}: snapshot has no content_before")
                    continue
                current = backend.read_document(uri)
                backend.update_document(
                    doc_uri=uri,
                    content=content_before,
                    metadata=current.metadata,
                    approval_token=None,
                    idempotency_key=undo_op_id,
                    expected_version=current.metadata.version,
                )
            else:
                failures.append(f"undo of operation {operation!r} not supported")
                continue
            restored.append(uri)
        except Exception as exc:  # noqa: BLE001 — best-effort undo across backends
            failures.append(f"{uri}: {exc}")

    if restored and not failures:
        status, exit_code = "ok", 0
    elif restored and failures:
        status, exit_code = "partial", 2
    else:
        status, exit_code = "failed", 1

    undo_entry = _undo_entry(undo_op_id, ts, restored, status, sensitivity, confirmation)
    journal.append(undo_entry)
    if audit is not None and hasattr(audit, "append"):
        cast(Any, audit).append(
            {
                "op_id": undo_op_id,
                "operation": "undo",
                "targets": restored,
                "ts": ts,
                "sensitivity": sensitivity,
                # §8.4 audit schema: the undo outcome mirrors the journal status.
                "outcome": status,
            }
        )
    error = "; ".join(failures) if failures else None
    return OpResult(op_id=op_id, exit_code=exit_code, journal_entry=undo_entry, error=error)
