"""In-process backend double implementing the capability interface (§6).

``FakeBackend`` gives the router a real, deterministic backend to write to
without any network/platform boundary: docs and wiki nodes live in-memory as
:class:`~kgent.types.Document` objects, version bumps are explicit, and a
:attr:`fault` hook injects per-method failures for fault-rehearsal tests.

Wiki support (§6.10, F21): backends whose ``capabilities`` declare a
``wiki`` block (``{"supported": True, ...}``) expose knowledge spaces
(:attr:`wiki_spaces`) and hierarchical nodes (:attr:`wiki_nodes`). Wiki nodes
are :class:`Document` objects whose ``metadata.node_type == "wiki_node"`` and
whose position (``space_id`` / ``parent_node_token``) lives on the metadata —
so read/update/undo all work uniformly, and **position is invariant under
update** (N24: an update only ever replaces content/version, never the
hierarchy fields).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from kgent.errors import AdapterError
from kgent.types import Document, DocumentMetadata, SearchResult


@dataclass
class FakeBackend:
    name: str
    trust_zone: str  # internal | external
    capabilities: dict[str, Any]
    owner: str | None = None
    docs: dict[str, Document] = field(default_factory=dict)
    archived: dict[str, Document] = field(default_factory=dict)
    wiki_spaces: dict[str, str] = field(default_factory=dict)  # space_id -> name
    wiki_nodes: dict[str, Document] = field(default_factory=dict)  # uri -> node doc
    write_calls: list[dict[str, Any]] = field(default_factory=list)
    fault: Callable[[str, dict[str, Any]], None] | None = None  # (method, kwargs) -> raise
    version_counter: int = field(default=0, init=False)
    spaces_seq: int = field(default=0, init=False)
    wiki_seq: int = field(default=0, init=False)

    # ---- capability helpers ------------------------------------------------

    @property
    def wiki_supported(self) -> bool:
        """True when ``capabilities`` declare a ``wiki`` block (S79)."""
        wiki = (self.capabilities or {}).get("wiki")
        return bool(isinstance(wiki, dict) and wiki.get("supported"))

    def _require_wiki(self, method: str) -> None:
        """Fail closed when this backend has no knowledge-space product (S79)."""
        if not self.wiki_supported:
            raise AdapterError(
                f"backend {self.name!r} has no knowledge-space product; '{method}' is not supported"
            )

    def _bump(self) -> str:
        self.version_counter += 1
        return f"v{self.version_counter}"

    def _check(self, method: str, **kwargs: Any) -> None:
        if self.fault:
            self.fault(method, kwargs)

    # ---- wiki spaces (§6.10) ----------------------------------------------

    def create_wiki_space(self, name: str, space_id: str | None = None) -> str:
        """Create a knowledge space; return its ``space_id`` (S82).

        ``space_id`` is auto-generated when omitted; explicit ids let tests
        seed the spec's example ids (e.g. ``7123456``).
        """
        self._require_wiki("create_wiki_space")
        self._check("create_wiki_space", name=name)
        if space_id is None:
            self.spaces_seq += 1
            space_id = f"space{self.spaces_seq}"
        self.wiki_spaces[space_id] = name
        self.write_calls.append({"method": "create_wiki_space", "space_id": space_id})
        return space_id

    def list_wiki_spaces(self) -> list[dict[str, str]]:
        """Spaces accessible to the backend, as ``{space_id, name}`` dicts (S82)."""
        self._require_wiki("list_wiki_spaces")
        self._check("list_wiki_spaces")
        return [{"space_id": sid, "name": name} for sid, name in self.wiki_spaces.items()]

    def list_wiki_nodes(
        self, space_id: str, parent_node_token: str | None = None
    ) -> list[DocumentMetadata]:
        """Nodes in ``space_id`` under ``parent_node_token`` (``None`` → root).

        The position inventory the skill layer uses to propose a fitting
        parent (S83 — only tokens returned by this listing are used).
        Returns metadata in insertion order.
        """
        self._require_wiki("list_wiki_nodes")
        self._check("list_wiki_nodes", space_id=space_id, parent_node_token=parent_node_token)
        out: list[DocumentMetadata] = []
        for uri, node in self.wiki_nodes.items():
            if node.metadata.space_id != space_id:
                continue
            if node.metadata.parent_node_token != parent_node_token:
                continue
            out.append(node.metadata)
        return out

    def _node_token(self, meta: DocumentMetadata) -> str:
        """Native node token for ``meta`` (the URI's final segment)."""
        return str(meta.doc_uri.rsplit("/", 1)[-1])

    # ---- wiki nodes (§6.10) ------------------------------------------------

    def create_wiki_node(
        self,
        title: str,
        content: str,
        metadata: DocumentMetadata,
        space_id: str,
        parent_node_token: str | None = None,
    ) -> str:
        """Create a wiki node inside ``space_id`` under ``parent_node_token``
        (``None`` → space root, S78); return its canonical URI (S77).

        The parent token must reference an existing node in the same space —
        a guessed/unknown token fails closed before any write (N22).
        """
        self._require_wiki("create_wiki_node")
        self._check(
            "create_wiki_node",
            title=title,
            content=content,
            space_id=space_id,
            parent_node_token=parent_node_token,
        )
        if space_id not in self.wiki_spaces:
            raise AdapterError(f"unknown wiki space {space_id!r}")
        if parent_node_token is not None:
            parent = self._find_wiki_node(space_id, parent_node_token)
            if parent is None:
                raise AdapterError(
                    f"unknown parent node {parent_node_token!r} in space {space_id!r}"
                )
        self.wiki_seq += 1
        uri = f"kgent://{self.name}/wiki{self.wiki_seq}"
        meta = replace(
            metadata,
            doc_uri=uri,
            version=self._bump(),
            node_type="wiki_node",
            space_id=space_id,
            parent_node_token=parent_node_token,
        )
        self.wiki_nodes[uri] = Document(doc_uri=uri, title=title, content=content, metadata=meta)
        self.write_calls.append(
            {
                "method": "create_wiki_node",
                "uri": uri,
                "space_id": space_id,
                "parent_node_token": parent_node_token,
            }
        )
        return uri

    def _find_wiki_node(self, space_id: str, token: str) -> Document | None:
        """Resolve a native ``token`` to a node document within ``space_id``."""
        expected = f"kgent://{self.name}/{token}"
        node = self.wiki_nodes.get(expected)
        if node is not None and node.metadata.space_id == space_id:
            return node
        return None

    def _locate(self, doc_uri: str) -> tuple[dict[str, Document], str] | None:
        """Which store holds ``doc_uri``: ``(store, key)`` or ``None``.

        Wiki nodes live in :attr:`wiki_nodes`, flat docs in :attr:`docs`,
        archived docs in :attr:`archived`. Store membership — not token
        parsing — identifies the node kind (node_type travels as metadata).
        """
        if doc_uri in self.docs:
            return self.docs, doc_uri
        if doc_uri in self.wiki_nodes:
            return self.wiki_nodes, doc_uri
        if doc_uri in self.archived:
            return self.archived, doc_uri
        return None

    # ---- §3.1 capability methods (docs + wiki nodes) ----------------------

    def create_document(self, title: str, content: str, metadata: DocumentMetadata) -> str:
        self._check("create_document", title=title, content=content, metadata=metadata)
        uri = f"kgent://{self.name}/doc{len(self.docs) + 1}"
        meta = replace(metadata, doc_uri=uri, version=self._bump())
        self.docs[uri] = Document(doc_uri=uri, title=title, content=content, metadata=meta)
        self.write_calls.append({"method": "create_document", "uri": uri})
        return uri

    def read_document(self, doc_uri: str) -> Document:
        self._check("read_document", doc_uri=doc_uri)
        located = self._locate(doc_uri)
        if located is None:
            raise LookupError(doc_uri)
        store, key = located
        return store[key]

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
        located = self._locate(doc_uri)
        if located is None:
            raise LookupError(doc_uri)
        store, key = located
        doc = store[key]
        if expected_version is not None and doc.metadata.version != expected_version:
            from kgent.errors import VersionConflict

            raise VersionConflict(doc_uri, expected_version, doc.metadata.version or "")
        new_meta = replace(metadata, version=self._bump())
        if not new_meta.title:
            # Real adapters update content only (title untouched); mirror that
            # here so an update without a new title never wipes the stored one.
            new_meta = replace(new_meta, title=doc.metadata.title)
        if doc.metadata.node_type == "wiki_node":
            # N24: updating a wiki node modifies content in place — the node
            # never moves within the hierarchy as a side effect of an update.
            new_meta = replace(
                new_meta,
                node_type="wiki_node",
                space_id=doc.metadata.space_id,
                parent_node_token=doc.metadata.parent_node_token,
            )
        store[key] = replace(doc, content=content, metadata=new_meta)
        self.write_calls.append({"method": "update_document", "uri": doc_uri})

    def delete_document(
        self,
        doc_uri: str,
        approval_token: str | None,
        idempotency_key: str,
        expected_version: str | None,
    ) -> None:
        self._check("delete_document", doc_uri=doc_uri)
        located = self._locate(doc_uri)
        if located is None:
            raise LookupError(doc_uri)
        store, key = located
        del store[key]
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
        docs = list(self.docs.values()) + list(self.wiki_nodes.values())
        return [d.metadata for d in docs[:limit]]

    def search(self, query: str, mode: str, top_k: int, timeout: float) -> list[SearchResult]:
        self._check("search", query=query, mode=mode, top_k=top_k)
        out = []
        # §7.2: a single search covers wiki nodes and flat docs by default.
        items = list(self.docs.items()) + list(self.wiki_nodes.items())
        for i, (uri, doc) in enumerate(items[:top_k], start=1):
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
                    node_type=doc.metadata.node_type,
                    space_id=doc.metadata.space_id,
                    parent_node_token=doc.metadata.parent_node_token,
                )
            )
        return out
