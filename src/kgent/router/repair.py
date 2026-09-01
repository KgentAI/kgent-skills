"""Sync / repair for partial fan-outs (S29, S30).

``sync_status`` reports partial and failed journal entries with their
``failed_targets``. ``sync_repair`` re-executes only the failed legs of a
partial op, idempotently (a second repair of the same op is a no-op).
"""

from __future__ import annotations

from typing import Any

from kgent.router.journal import Journal
from kgent.router.policy import OpResult

__all__ = ["sync_repair", "sync_status"]


def sync_status(journal: Journal) -> list[dict[str, Any]]:
    """Return a list of failed/partial ops with their failed targets (S30).

    Each entry has ``op_id``, ``status``, ``operation``, ``failed_targets``.
    """
    result: list[dict[str, Any]] = []
    for entry in journal.list_partial():
        result.append(
            {
                "op_id": entry.get("op_id"),
                "status": entry.get("status"),
                "operation": entry.get("operation"),
                "failed_targets": list(entry.get("failed_targets", [])),
            }
        )
    for entry in journal.list_failed():
        result.append(
            {
                "op_id": entry.get("op_id"),
                "status": entry.get("status"),
                "operation": entry.get("operation"),
                "failed_targets": list(entry.get("failed_targets", [])),
            }
        )
    return result


def sync_repair(
    op_id: str,
    *,
    journal: Journal,
    backends: dict[str, Any],
) -> OpResult:
    """Re-execute the failed legs of a partial op (S29, idempotent).

    If the op is no longer partial (already repaired or not found), returns a
    no-op result. Re-running repair on an already-repaired op does not
    duplicate writes or journal entries.
    """
    from kgent.router.policy import OpResult

    entry = journal.get(op_id)
    if entry is None:
        return OpResult(
            op_id=op_id,
            exit_code=1,
            journal_entry={"op_id": op_id, "status": "not_found"},
            error=f"op {op_id!r} not found in journal",
        )
    status = entry.get("status")
    if status != "partial":
        # Already repaired or not a partial op — idempotent no-op.
        return OpResult(
            op_id=op_id,
            exit_code=0,
            journal_entry={"op_id": op_id, "status": "already_repaired"},
        )
    failed_targets = list(entry.get("failed_targets", []))
    if not failed_targets:
        return OpResult(
            op_id=op_id,
            exit_code=0,
            journal_entry={"op_id": op_id, "status": "nothing_to_repair"},
        )
    # Re-execute the failed legs: for each "backend: error" string, extract
    # the backend name and attempt the original operation.
    operation = str(entry.get("operation", "create"))
    sensitivity = str(entry.get("sensitivity", "internal"))
    title = str(entry.get("proposal_title", ""))
    content = str(entry.get("proposal_content", ""))
    repaired: list[str] = []
    still_failed: list[str] = []
    for target_str in failed_targets:
        backend_name = target_str.split(":")[0]
        backend = backends.get(backend_name)
        if backend is None:
            still_failed.append(target_str)
            continue
        try:
            if operation == "create":
                from kgent.router.policy import _metadata
                from kgent.types import WriteProposal

                # Build a minimal proposal for the re-create.
                proposal = WriteProposal(
                    operation="create",
                    targets=[(backend_name, None)],
                    title=title,
                    content=content,
                    sensitivity=sensitivity,
                )
                created_uri = backend.create_document(
                    title=title,
                    content=content,
                    metadata=_metadata(proposal, backend_name, doc_uri=""),
                )
                repaired.append(created_uri)
            else:
                still_failed.append(target_str)
        except Exception as exc:  # noqa: BLE001 — per-target repair failure
            still_failed.append(f"{backend_name}: {exc}")

    # Mark the original entry as repaired (update its status in-place).
    entry["status"] = "ok" if not still_failed else "partial"
    if still_failed:
        entry["failed_targets"] = still_failed
    else:
        entry.pop("failed_targets", None)
        entry.pop("failed_legs", None)
    # Persist the updated entry (append a repair marker).
    journal.append(
        {
            "schema_version": 1,
            "op_id": f"repair-{op_id}",
            "ts": "",
            "operation": "repair",
            "targets": repaired,
            "idempotency_key": f"repair-{op_id}",
            "snapshot": {},
            "proposal_hash": "",
            "confirmation": "sync",
            "sensitivity": sensitivity,
            "status": "ok" if not still_failed else "partial",
        }
    )
    exit_code = 0 if not still_failed else 2
    return OpResult(
        op_id=op_id,
        exit_code=exit_code,
        journal_entry={"op_id": op_id, "status": "repaired", "repaired_targets": repaired},
    )
