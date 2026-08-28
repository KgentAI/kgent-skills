"""Core data types — normative schemas (§3.8, §1.5).

Frozen dataclasses shared by all adapters and the router. Required fields come
before defaulted fields; mutable defaults use ``default_factory``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class DocumentMetadata:
    """Metadata sidecar for a document (§3.8)."""

    doc_uri: str
    title: str
    backend: str
    location_url: str | None = None
    location_description: str | None = None
    content_type: str | None = None
    sensitivity: str = "internal"
    tags: list[str] = field(default_factory=list)
    owner: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    version: str | None = None
    content_fingerprint: str | None = None
    size_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class Document:
    """Canonical document: Markdown body + metadata sidecar (§6.9).

    Version lives on ``metadata`` — there is no separate version field.
    """

    doc_uri: str
    title: str
    content: str
    metadata: DocumentMetadata


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Search hit (§3.8)."""

    doc_uri: str
    metadata: DocumentMetadata
    rank: int = 0
    snippet: str | None = None
    score_native: float | None = None
    mode_used: str | None = None
    also_available_in: list[str] = field(default_factory=list)
    access: str = "ok"


@dataclass(frozen=True, slots=True)
class ApproverDecision:
    """A single approver's decision on an approval (§3.8)."""

    approver: str
    decision: str = "pending"  # accept | reject | pending
    decided_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ApprovalBinding:
    """Cryptographic binding for an approval (§3.8, §3.4)."""

    doc_uri: str
    operation: str  # create | update | delete
    content_fingerprint: str


@dataclass(frozen=True, slots=True)
class ApprovalStatus:
    """State of an approval request (§3.8)."""

    approval_id: str
    state: str = "pending"  # pending | approved | rejected | expired
    requested_at: datetime | None = None
    decided_at: datetime | None = None
    expires_at: datetime | None = None
    approvers: list[ApproverDecision] = field(default_factory=list)
    binding: ApprovalBinding | None = None


@dataclass(frozen=True, slots=True)
class FilterSpec:
    """Typed filter object (§3.7)."""

    tags: list[str] = field(default_factory=list)
    content_type: str | None = None
    created_after: date | None = None
    created_before: date | None = None
    updated_after: date | None = None
    updated_before: date | None = None
    owner: str | None = None


@dataclass(frozen=True, slots=True)
class BackendResolution:
    """Resolved backend + adapter for an operation (§1.5)."""

    backend: str
    adapter_type: str  # skill | cli | mcp
    adapter_name: str
    capabilities_needed: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PolicyGate:
    """A policy gate to enforce around a write (§1.5; minimal until Task 5.2)."""

    name: str
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WriteProposal:
    """Write proposal for mandatory confirmation (§5.6; minimal until Task 5.2)."""

    operation: str
    targets: list[tuple[str, str | None]] = field(default_factory=list)
    title: str | None = None
    content_type: str | None = None
    sensitivity: str = "internal"
    approval_required: bool = False
    provenance: dict[str, str] = field(default_factory=dict)
    degraded: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    snapshot_note: str = ""


@dataclass(frozen=True, slots=True)
class RoutingIntent:
    """Structured router output consumed by the agent loop (§1.5)."""

    operation: str
    doc_uri: str | None = None
    query: str | None = None
    targets: list[BackendResolution] = field(default_factory=list)
    proposal: WriteProposal | None = None
    policy_gates: list[PolicyGate] = field(default_factory=list)
    provenance: dict[str, str] = field(default_factory=dict)
