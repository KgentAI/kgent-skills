"""In-memory journal/audit doubles for the write-gate tests (S1–S4).

In-memory double — replaced by real Journal/AuditLog in Tasks 5.4/5.5
(same append interface).
"""

from __future__ import annotations

from typing import Any

__all__ = ["InMemoryAudit", "InMemoryJournal"]


class InMemoryJournal:
    """Append-only in-memory write journal with the Task 5.4 append shape."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def append(self, entry: dict[str, Any]) -> None:
        self.entries.append(entry)

    @property
    def latest(self) -> dict[str, Any] | None:
        return self.entries[-1] if self.entries else None


class InMemoryAudit:
    """Append-only in-memory audit log with the Task 5.5 append shape."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def append(self, entry: dict[str, Any]) -> None:
        self.entries.append(entry)

    @property
    def latest(self) -> dict[str, Any] | None:
        return self.entries[-1] if self.entries else None
