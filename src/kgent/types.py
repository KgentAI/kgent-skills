"""Interim stub data types — finalized/expanded in Task 1.2 (§3.8).

Field-compatible with FakeBackend (tests/fakes/fake_backend.py) and the §3.8
normative schemas. Do NOT extend here; Task 1.2 owns the full schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class DocumentMetadata:
    """Metadata sidecar (§3.8). Interim minimal version."""

    doc_uri: str
    title: str
    backend: str
    sensitivity: str
    location_url: str | None = None
    location_description: str | None = None
    content_type: str | None = None
    tags: list[str] = field(default_factory=list)
    owner: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    version: str | None = None
    content_fingerprint: str | None = None
    size_bytes: int | None = None


@dataclass
class Document:
    """Canonical document: Markdown body + metadata sidecar (§6.9)."""

    doc_uri: str
    title: str
    content: str
    metadata: DocumentMetadata
    version: str | None = None


@dataclass
class SearchResult:
    """Search hit (§3.8)."""

    doc_uri: str
    metadata: DocumentMetadata
    snippet: str | None
    rank: int
    score_native: float | None
    mode_used: str
    also_available_in: list[str] = field(default_factory=list)
    access: str = "ok"
