from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from kgent.types import Document, DocumentMetadata, SearchResult


@dataclass
class FakeBackend:
    name: str
    trust_zone: str  # internal | external
    capabilities: dict[str, Any]
    owner: str | None = None
    docs: dict[str, Document] = field(default_factory=dict)
    archived: dict[str, Document] = field(default_factory=dict)
    write_calls: list[dict] = field(default_factory=list)
    fault: Callable[[str, dict], None] | None = None  # (method, kwargs) -> raise
    version_counter: int = field(default=0, init=False)

    def _bump(self) -> str:
        self.version_counter += 1
        return f"v{self.version_counter}"

    def _check(self, method: str, **kwargs: Any) -> None:
        if self.fault:
            self.fault(method, kwargs)

    def create_document(self, title: str, content: str, metadata: DocumentMetadata) -> str:
        self._check("create_document", title=title, content=content, metadata=metadata)
        uri = f"kgent://{self.name}/doc{len(self.docs) + 1}"
        self.docs[uri] = Document(
            doc_uri=uri, title=title, content=content, metadata=metadata, version=self._bump()
        )
        self.write_calls.append({"method": "create_document", "uri": uri})
        return uri

    def read_document(self, doc_uri: str) -> Document:
        self._check("read_document", doc_uri=doc_uri)
        if doc_uri in self.docs:
            return self.docs[doc_uri]
        raise LookupError(doc_uri)

    def update_document(
        self,
        doc_uri: str,
        content: str,
        metadata: DocumentMetadata,
        approval_token: str | None,
        idempotency_key: str,
        expected_version: str | None,
    ) -> None:
        self._check("update_document", doc_uri=doc_uri, expected_version=expected_version)
        doc = self.docs[doc_uri]
        if expected_version is not None and doc.version != expected_version:
            from kgent.errors import VersionConflict

            raise VersionConflict(doc_uri, expected_version, doc.version)
        doc.content = content
        doc.metadata = metadata
        doc.version = self._bump()
        self.write_calls.append({"method": "update_document", "uri": doc_uri})

    def delete_document(
        self,
        doc_uri: str,
        approval_token: str | None,
        idempotency_key: str,
        expected_version: str | None,
    ) -> None:
        self._check("delete_document", doc_uri=doc_uri)
        del self.docs[doc_uri]
        self.write_calls.append({"method": "delete_document", "uri": doc_uri})

    def archive_document(
        self, doc_uri: str, approval_token: str | None, idempotency_key: str
    ) -> None:
        self._check("archive_document", doc_uri=doc_uri)
        doc = self.docs.pop(doc_uri)
        self.archived[doc_uri] = doc
        self.write_calls.append({"method": "archive_document", "uri": doc_uri})

    def unarchive_document(
        self, doc_uri: str, approval_token: str | None, idempotency_key: str
    ) -> None:
        self._check("unarchive_document", doc_uri=doc_uri)
        doc = self.archived.pop(doc_uri)
        self.docs[doc_uri] = doc
        self.write_calls.append({"method": "unarchive_document", "uri": doc_uri})

    def list_documents(self, filters: Any, limit: int) -> list[DocumentMetadata]:
        return [d.metadata for d in list(self.docs.values())[:limit]]

    def search(self, query: str, mode: str, top_k: int, timeout: float) -> list[SearchResult]:
        self._check("search", query=query, mode=mode, top_k=top_k)
        out = []
        for i, (uri, doc) in enumerate(list(self.docs.items())[:top_k], start=1):
            out.append(
                SearchResult(
                    doc_uri=uri,
                    metadata=doc.metadata,
                    snippet=doc.content[:80],
                    rank=i,
                    score_native=None,
                    mode_used=mode,
                    also_available_in=[],
                    access="ok",
                )
            )
        return out
