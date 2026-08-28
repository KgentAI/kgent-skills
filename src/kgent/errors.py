"""Interim stub error hierarchy — finalized/expanded in Task 1.1.

Only VersionConflict exists today because FakeBackend raises it. Task 1.1
owns the full error hierarchy.
"""

from __future__ import annotations


class VersionConflict(Exception):
    """Raised when a write's expected_version no longer matches the backend (§3.9)."""

    def __init__(
        self,
        doc_uri: str,
        expected_version: str | None,
        actual_version: str | None,
    ) -> None:
        self.doc_uri = doc_uri
        self.expected_version = expected_version
        self.actual_version = actual_version
        super().__init__(
            f"version conflict on {doc_uri}: expected {expected_version}, found {actual_version}"
        )
