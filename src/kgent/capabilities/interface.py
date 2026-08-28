"""Capability interfaces — typing protocols for adapter capabilities (§3.1).

Each protocol is a structural contract; any backend adapter implementing the
methods is accepted regardless of class hierarchy. Canonical document URIs
(§3.6) cross all boundaries — backend-native IDs never appear here.
"""

from __future__ import annotations

from typing import Protocol

from kgent.types import ApprovalStatus, Document, DocumentMetadata, FilterSpec, SearchResult


class DocumentStorage(Protocol):
    """Document persistence capability (§3.1)."""

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

    def delete_document(
        self,
        doc_uri: str,
        approval_token: str | None,
        idempotency_key: str,
        expected_version: str | None,
    ) -> None: ...

    def archive_document(
        self, doc_uri: str, approval_token: str | None, idempotency_key: str
    ) -> None: ...

    def unarchive_document(
        self, doc_uri: str, approval_token: str | None, idempotency_key: str
    ) -> None: ...

    def list_documents(self, filters: FilterSpec, limit: int) -> list[DocumentMetadata]: ...


class DocumentSearch(Protocol):
    """Search capability — keyword, semantic, and hybrid modes (§3.1)."""

    def search_by_keywords(
        self,
        query: str,
        filters: FilterSpec | None = None,
        top_k: int = 10,
        fields: list[str] | None = None,
    ) -> list[SearchResult]: ...

    def search_by_semantics(
        self,
        query: str,
        filters: FilterSpec | None = None,
        top_k: int = 10,
        similarity_threshold: float | None = None,
    ) -> list[SearchResult]: ...

    def search_hybrid(
        self,
        query: str,
        filters: FilterSpec | None = None,
        top_k: int = 10,
        keyword_weight: float = 0.3,
        semantic_weight: float = 0.7,
        similarity_threshold: float | None = None,
    ) -> list[SearchResult]: ...


class ApprovalFlow(Protocol):
    """Approval workflow capability — optional, router-enforced (§3.1, §3.4)."""

    def request_approval(self, doc_uri: str, approvers: list[str], operation: str) -> str: ...

    def check_approval(self, approval_id: str) -> ApprovalStatus: ...

    def execute_approved(self, doc_uri: str, approval_id: str) -> None: ...
