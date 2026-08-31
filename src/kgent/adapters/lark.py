"""Lark / Feishu adapter (§1.3): §3.1 capabilities over ``lark-cli`` (§8.5).

The router names this backend's adapter ``lark-doc`` (the platform skill)
when its declared capabilities satisfy the operation, else ``lark-cli``
(§1.5, S59) — that preference lives at **resolve level**
(:mod:`kgent.router.resolve`), not here. :class:`LarkAdapter` is always
constructed with ``cmd=["lark-cli"]``; there is no separate skill
invocation yet, so an injected skill-invoker can arrive later without
touching resolve. Canonical URIs: ``kgent://lark/<id>`` (§3.6).
"""

from __future__ import annotations

import sys
from typing import Any

from kgent.adapters.cli_adapter import CliCapabilityAdapter
from kgent.errors import AdapterError
from kgent.types import Document, DocumentMetadata, SearchResult

__all__ = ["LarkAdapter"]


class LarkAdapter(CliCapabilityAdapter):
    """Lark/Feishu documents adapter — wire protocol over ``lark-cli``.

    Maps kgent operations to lark-cli commands:
    - create → docs +create --title <t> --content <c> --doc-format markdown
    - read → docs +fetch --doc <token>
    - update → docs +update --doc <token> --command overwrite --content <c> --doc-format markdown
    - delete → drive +delete --file-token <token> --type docx --yes
    - search → docs +search --query <q>
    """

    def __init__(self, cmd: list[str] | None = None, timeout: float = 30.0) -> None:
        # On Windows, use lark-cli.cmd for subprocess compatibility
        if cmd is None:
            cmd = ["lark-cli.cmd" if sys.platform == "win32" else "lark-cli"]
        super().__init__(cmd, "lark", timeout)

    def create_document(self, title: str, content: str, metadata: DocumentMetadata) -> str:
        """Create a Lark document using ``docs +create``."""
        # Use markdown format for simplicity
        payload = self._run([
            "docs", "+create",
            "--title", title,
            "--content", content,
            "--doc-format", "markdown",
            "--as", "user",
            "--json",
        ])
        # Response structure: {"ok": true, "data": {"document": {"document_id": "...", ...}}}
        data = payload.get("data") or {}
        document = data.get("document") or {}
        doc_token = (
            document.get("document_id")
            or document.get("token")
            or payload.get("token")
            or payload.get("document_id")
            or payload.get("id")
        )
        if not doc_token:
            raise AdapterError(f"lark-cli docs +create returned no document token: {payload}")
        return self._canonical(str(doc_token))

    def read_document(self, doc_uri: str) -> Document:
        """Read a Lark document using ``docs +fetch``."""
        native_id = self._native_id(doc_uri)
        payload = self._run([
            "docs", "+fetch",
            "--doc", native_id,
            "--doc-format", "markdown",
            "--as", "user",
            "--json",
        ])
        # Response structure: {"ok": true, "data": {"document": {"content": "...", "document_id": "...", "revision_id": ...}}}
        data = payload.get("data") or {}
        document = data.get("document") or {}
        # Content is markdown with # title as first line
        content = str(document.get("content", ""))
        title = ""
        # Extract title from markdown heading or DocxXML <title> tag
        if content.startswith("# "):
            # Markdown format: # Title\n\nContent
            lines = content.split("\n", 1)
            title = lines[0][2:].strip()
            content = lines[1].strip() if len(lines) > 1 else ""
        elif content.startswith("<title>") and "</title>" in content:
            # DocxXML format: <title>Title</title><p>Content</p>
            title_end = content.index("</title>")
            title = content[7:title_end]
            content = content[title_end + 9:].strip()
        version = str(document.get("revision_id")) if document.get("revision_id") else None
        meta = DocumentMetadata(
            doc_uri=doc_uri,
            title=title,
            backend=self.name,
            version=version,
        )
        return Document(doc_uri=doc_uri, title=title, content=content, metadata=meta)

    def update_document(
        self,
        doc_uri: str,
        content: str,
        metadata: DocumentMetadata,
        approval_token: str | None,
        idempotency_key: str,
        expected_version: str | None,
    ) -> None:
        """Update a Lark document using ``docs +update --command overwrite``."""
        native_id = self._native_id(doc_uri)
        args = [
            "docs", "+update",
            "--doc", native_id,
            "--command", "overwrite",
            "--content", content,
            "--doc-format", "markdown",
            "--as", "user",
            "--json",
        ]
        if expected_version is not None:
            args += ["--revision-id", expected_version]
        self._run(args)

    def delete_document(
        self,
        doc_uri: str,
        approval_token: str | None,
        idempotency_key: str,
        expected_version: str | None,
    ) -> None:
        """Delete a Lark document using ``drive +delete``."""
        native_id = self._native_id(doc_uri)
        self._run([
            "drive", "+delete",
            "--file-token", native_id,
            "--type", "docx",
            "--as", "user",
            "--yes",
            "--json",
        ])

    def search_by_keywords(
        self,
        query: str,
        filters: Any = None,
        top_k: int = 10,
        fields: list[str] | None = None,
    ) -> list[SearchResult]:
        """Search Lark docs using ``docs +search``."""
        payload = self._run([
            "docs", "+search",
            "--query", query,
            "--page-size", str(min(top_k, 20)),  # lark-cli max is 20
            "--as", "user",
            "--json",
        ])
        results: list[SearchResult] = []
        # Response structure: {"ok": true, "data": {"results": [...]}}
        data = payload.get("data") or {}
        docs = data.get("results") or []
        for item in docs:
            result_meta = item.get("result_meta") or {}
            doc_token = str(result_meta.get("token", ""))
            if not doc_token:
                continue
            uri = self._canonical(doc_token)
            # title_highlighted contains HTML tags, strip them
            title_raw = str(item.get("title_highlighted", ""))
            title = title_raw.replace("<h>", "").replace("</h>", "").replace("<hb>", "").replace("</hb>", "")
            rank = int(item.get("rank", 0))
            snippet_raw = item.get("summary_highlighted")
            snippet = None
            if snippet_raw is not None:
                snippet = str(snippet_raw).replace("<h>", "").replace("</h>", "").replace("<hb>", "").replace("</hb>", "")
            results.append(
                SearchResult(
                    doc_uri=uri,
                    metadata=DocumentMetadata(doc_uri=uri, title=title, backend=self.name),
                    rank=rank,
                    snippet=snippet,
                    mode_used="keyword",
                )
            )
        return results[:top_k]
