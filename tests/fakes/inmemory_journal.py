"""In-memory audit double for the write-gate tests.

The in-memory journal double was replaced by the real
:class:`~kgent.router.journal.Journal` in Task 5.4. The audit log remains an
in-memory double until Task 5.5 (audit.py) lands.
"""

from __future__ import annotations

from typing import Any

__all__ = ["InMemoryAudit"]


class InMemoryAudit:
    """Append-only in-memory audit log with the Task 5.5 append shape."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def append(self, entry: dict[str, Any]) -> None:
        self.entries.append(entry)

    @property
    def latest(self) -> dict[str, Any] | None:
        return self.entries[-1] if self.entries else None
