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

    @property
    def capabilities(self) -> dict[str, Any]:
        """Declare §3.1 capabilities incl. the wiki (knowledge space) block (§6.10).

        Lark is the only initial-scope backend with a knowledge-space product;
        the ``wiki`` block gates ``--wiki-space`` / ``kgent wiki spaces …``
        (S79: backends without it reject wiki flags before any write).
        """
        caps = super().capabilities
        caps["wiki"] = {
            "supported": True,
            "features": ["spaces_list", "spaces_create", "node_create"],
        }
        return caps

    # ---- §6.10 wiki (knowledge space) operations -------------------------

    def list_wiki_spaces(self) -> list[dict[str, str]]:
        """List wiki (knowledge) spaces via ``wiki +space-list`` (§6.10, S82)."""
        payload = self._run(["wiki", "+space-list", "--as", "user"])
        # Response structure: {"ok": true, "data": {...items}} — normalize any
        # container shape (items list keyed ``items``/``spaces``/itself).
        data = payload.get("data") or {}
        raw: Any = data.get("items", data.get("spaces", [])) if isinstance(data, dict) else data
        if isinstance(raw, dict):
            raw = [raw]
        spaces: list[dict[str, str]] = []
        if not isinstance(raw, list):
            return spaces
        for item in raw:
            if not isinstance(item, dict):
                continue
            sid = item.get("space_id") or item.get("id")
            name = item.get("name") or item.get("space_name") or ""
            if sid is None:
                continue
            spaces.append({"space_id": str(sid), "name": str(name)})
        return spaces

    def create_wiki_space(self, name: str) -> str:
        """Create a wiki (knowledge) space via ``wiki +space-create`` (S82)."""
        payload = self._run(["wiki", "+space-create", "--name", name, "--as", "user"])
        data = payload.get("data") or {}
        space = data.get("space") if isinstance(data, dict) else None
        sid = (
            (space.get("space_id") if isinstance(space, dict) else None)
            or (data.get("space_id") if isinstance(data, dict) else None)
            or payload.get("space_id")
        )
        if not sid:
            raise AdapterError(f"lark-cli wiki +space-create returned no space_id: {payload}")
        return str(sid)

    def create_wiki_node(
        self,
        title: str,
        content: str,
        metadata: DocumentMetadata,
        space_id: str,
        parent_node_token: str | None,
    ) -> str:
        """Create a wiki node via ``wiki +node-create`` (§6.10, S77/S78).

        ``--space-id`` routes the node into the knowledge space;
        ``--parent-node-token`` (when given) places it under an existing node
        (omitted → space root, S78).
        """
        args = ["wiki", "+node-create", "--space-id", space_id]
        if parent_node_token is not None:
            args += ["--parent-node-token", parent_node_token]
        args += ["--title", title, "--content", content, "--as", "user"]
        payload = self._run(args)
        # Response structure: {"ok": true, "data": {"node": {"node_token": ...}, ...}}
        data = payload.get("data") or {}
        node = data.get("node") if isinstance(data, dict) else None
        node_token = (
            (node.get("node_token") if isinstance(node, dict) else None)
            or (data.get("node_token") if isinstance(data, dict) else None)
            or payload.get("node_token")
        )
        if not node_token:
            raise AdapterError(f"lark-cli wiki +node-create returned no node_token: {payload}")
        return self._canonical(str(node_token))

    def create_document(self, title: str, content: str, metadata: DocumentMetadata) -> str:
        """Create a Lark document using ``docs +create``."""
        # Use markdown format for simplicity
        payload = self._run(
            [
                "docs",
                "+create",
                "--title",
                title,
                "--content",
                content,
                "--doc-format",
                "markdown",
                "--as",
                "user",
                "--json",
            ]
        )
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
        payload = self._run(
            [
                "docs",
                "+fetch",
                "--doc",
                native_id,
                "--doc-format",
                "markdown",
                "--as",
                "user",
                "--json",
            ]
        )
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
            content = content[title_end + 9 :].strip()
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
            "docs",
            "+update",
            "--doc",
            native_id,
            "--command",
            "overwrite",
            "--content",
            content,
            "--doc-format",
            "markdown",
            "--as",
            "user",
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
        self._run(
            [
                "drive",
                "+delete",
                "--file-token",
                native_id,
                "--type",
                "docx",
                "--as",
                "user",
                "--yes",
                "--json",
            ]
        )

    def search_by_keywords(
        self,
        query: str,
        filters: Any = None,
        top_k: int = 10,
        fields: list[str] | None = None,
    ) -> list[SearchResult]:
        """Search Lark docs using ``docs +search``."""
        payload = self._run(
            [
                "docs",
                "+search",
                "--query",
                query,
                "--page-size",
                str(min(top_k, 20)),  # lark-cli max is 20
                "--as",
                "user",
                "--json",
            ]
        )
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
            title = (
                title_raw.replace("<h>", "")
                .replace("</h>", "")
                .replace("<hb>", "")
                .replace("</hb>", "")
            )
            raw_rank = item.get("rank", 0)
            try:
                rank = int(raw_rank)  # CLI payload is unvalidated input
            except (TypeError, ValueError):
                rank = 0
            snippet_raw = item.get("summary_highlighted")
            snippet = None
            if snippet_raw is not None:
                snippet = (
                    str(snippet_raw)
                    .replace("<h>", "")
                    .replace("</h>", "")
                    .replace("<hb>", "")
                    .replace("</hb>", "")
                )
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
