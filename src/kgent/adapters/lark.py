"""Lark / Feishu adapter (§1.3): §3.1 capabilities over ``lark-cli`` (§8.5).

The router names this backend's adapter ``lark-doc`` (the platform skill)
when its declared capabilities satisfy the operation, else ``lark-cli``
(§1.5, S59) — that preference lives at **resolve level**
(:mod:`kgent.router.resolve`), not here. :class:`LarkAdapter` is always
constructed with ``cmd=["lark-cli"]``; there is no separate skill
invocation yet, so an injected skill-invoker can arrive later without
touching resolve. Canonical URIs: ``kgent://lark/<id>`` (§3.6).

**Node-type fidelity** (§7.2; spec 2026-09-02-search-node-type-wiki-fidelity):
``node_type`` comes only from server-side facts — the ``docs +search`` hit's
``result_meta.url`` path segment (``/wiki/`` vs ``/docx/``, the exact paths
native citations render) or its ``entity_type``; never from token shape
(§3.6/N23). ``docs +fetch`` carries no type fact, so reads probe ``wiki
+node-get`` (success → ``wiki_node`` + position, ``131005 not_found`` → flat
doc, any other failure → the historical ``"doc"`` default). Should search/read
ever be delegated to a platform skill instead, that skill's results must carry
the same fields — ``node_type``/``space_id``/``parent_node_token``, absent
meaning ``"doc"`` — so fidelity survives the delegation boundary.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any
from urllib.parse import urlparse

from kgent.adapters.cli_adapter import CliCapabilityAdapter, run_cli
from kgent.errors import AdapterError, AdapterTimeoutError, SubprocessError
from kgent.types import Document, DocumentMetadata, SearchResult

__all__ = ["LarkAdapter"]

#: Wiki search-hit enrichment (space position): at most this many
#: ``wiki +node-get`` probes per search, in rank order.
_WIKI_ENRICH_CAP = 8

#: Wall-clock budget for the enrichment probes of one search. ``fanout``
#: cancels the whole backend past ``search_seconds`` (S33) — probes must never
#: push a search over that budget, so they stop early and leave the position
#: fields unset instead.
_WIKI_ENRICH_BUDGET_SECONDS = 4.0

#: Per-probe subprocess cap.
_WIKI_PROBE_TIMEOUT_SECONDS = 8.0

#: Skip a probe when less than this much budget remains (a doomed call is
#: worse than an unset field).
_WIKI_PROBE_MIN_SECONDS = 0.5


def _strip_highlights(raw: str) -> str:
    """Remove the search-service highlight tags from a title/snippet."""
    return raw.replace("<h>", "").replace("</h>", "").replace("<hb>", "").replace("</hb>", "")


def _node_type_from_hit(item: dict[str, Any]) -> str:
    """Server-fact node type for one ``docs +search`` hit: ``doc``|``wiki_node``.

    The ``result_meta.url`` path segment is primary — ``/wiki/`` vs ``/docx/``
    are exactly the paths native citations render, so the URL is the rendering
    truth (N23); ``entity_type`` is the fallback when the URL is missing.
    Anything else (bitables, sheets, missing fields) stays ``"doc"`` — never
    guessed from the token, never a vocabulary the rest of kgent doesn't know.
    """
    meta = item.get("result_meta")
    url = meta.get("url") if isinstance(meta, dict) else None
    if isinstance(url, str) and url:
        segments = urlparse(url).path.split("/")
        if len(segments) > 1:
            if segments[1] == "wiki":
                return "wiki_node"
            if segments[1] in ("docx", "doc"):
                return "doc"
    if item.get("entity_type") == "WIKI":
        return "wiki_node"
    return "doc"


def _position_fields(info: dict[str, Any]) -> tuple[str | None, str | None]:
    """``(space_id, parent_node_token)`` from a ``wiki +node-get`` ``data`` dict.

    The service returns ``""`` for a root node's parent — surfaced as ``None``
    (§7.2 position fields are unset at the root, matching the write path).
    """
    space_id = str(info["space_id"]) if info.get("space_id") else None
    parent = info.get("parent_node_token")
    return space_id, (str(parent) if parent else None)


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

    def _wiki_node_info(self, native_id: str, timeout: float | None = None) -> dict[str, Any] | None:
        """Probe ``wiki +node-get``; the node ``data`` dict, or ``None``.

        A ``131005 not_found`` is the definitive flat-doc negative; a timeout,
        spawn failure or any other error also yields ``None`` — callers degrade
        to the historical defaults instead of failing the search/read this
        probe decorates. Run via :func:`run_cli` directly (not :meth:`_run`)
        because failure is an *expected outcome* here, not an adapter error.
        """
        argv = self.cmd + ["wiki", "+node-get", "--node-token", native_id, "--as", "user", "--json"]
        self._check_argv(argv)
        try:
            result = run_cli(argv, timeout=timeout if timeout and timeout > 0 else self.timeout)
        except (AdapterTimeoutError, SubprocessError):
            return None
        if result.returncode != 0:
            return None
        try:
            payload = json.loads(result.stdout)
        except ValueError:
            return None
        data = payload.get("data") if isinstance(payload, dict) else None
        return data if isinstance(data, dict) else None

    def _wiki_positions(
        self, wiki_tokens: list[str], *, started: float
    ) -> dict[str, dict[str, Any]]:
        """Bounded position probes for wiki search hits (rank order).

        Hard-bounded because ``fanout`` cancels the whole backend past
        ``search_seconds`` (S33): the probes stop at
        :data:`_WIKI_ENRICH_CAP` calls or :data:`_WIKI_ENRICH_BUDGET_SECONDS`
        of wall clock, whichever comes first — over-budget hits keep their
        ``node_type`` and simply carry no position fields.
        """
        positions: dict[str, dict[str, Any]] = {}
        deadline = started + _WIKI_ENRICH_BUDGET_SECONDS
        for token in wiki_tokens:
            if len(positions) >= _WIKI_ENRICH_CAP:
                break
            remaining = deadline - time.monotonic()
            if remaining < _WIKI_PROBE_MIN_SECONDS:
                break
            info = self._wiki_node_info(
                token, timeout=min(_WIKI_PROBE_TIMEOUT_SECONDS, remaining)
            )
            if info is not None:
                positions[token] = info
        return positions

    def read_document(self, doc_uri: str) -> Document:
        """Read a Lark document using ``docs +fetch``.

        ``docs +fetch`` carries no node-type fact, so the token is probed with
        one ``wiki +node-get`` call: success → ``wiki_node`` with its space
        position; ``131005 not_found`` (or any probe failure) → ``"doc"`` with
        unset position — the pre-fidelity behavior, never an exception.
        """
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
        node_type, space_id, parent_node_token = "doc", None, None
        info = self._wiki_node_info(native_id)
        if info is not None:
            node_type = "wiki_node"
            space_id, parent_node_token = _position_fields(info)
        meta = DocumentMetadata(
            doc_uri=doc_uri,
            title=title,
            backend=self.name,
            version=version,
            node_type=node_type,
            space_id=space_id,
            parent_node_token=parent_node_token,
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
        """Search Lark docs using ``docs +search``.

        ``node_type`` is read from each hit's server-side facts (see
        :func:`_node_type_from_hit`) at zero extra cost; wiki hits are then
        probed — bounded by :meth:`_wiki_positions` — for their space position,
        so §7.2 results carry ``space_id``/``parent_node_token`` like the write
        path already records. Fields land on both the result and its metadata
        (mirrors :class:`~kgent.adapters.base.Adapter` consumers reading either).
        """
        started = time.monotonic()
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
        # Response structure: {"ok": true, "data": {"results": [...]}}
        data = payload.get("data") or {}
        docs = data.get("results") or []
        parsed: list[tuple[str, str, str, int, str | None, str]] = []
        wiki_tokens: list[str] = []
        for item in docs:
            result_meta = item.get("result_meta") or {}
            doc_token = str(result_meta.get("token", ""))
            if not doc_token:
                continue
            uri = self._canonical(doc_token)
            # title_highlighted contains HTML tags, strip them
            title = _strip_highlights(str(item.get("title_highlighted", "")))
            raw_rank = item.get("rank", 0)
            try:
                rank = int(raw_rank)  # CLI payload is unvalidated input
            except (TypeError, ValueError):
                rank = 0
            snippet_raw = item.get("summary_highlighted")
            snippet = (
                _strip_highlights(str(snippet_raw)) if snippet_raw is not None else None
            )
            node_type = _node_type_from_hit(item)
            if node_type == "wiki_node":
                wiki_tokens.append(doc_token)
            parsed.append((doc_token, uri, title, rank, snippet, node_type))

        positions = self._wiki_positions(wiki_tokens, started=started)

        results: list[SearchResult] = []
        for doc_token, uri, title, rank, snippet, node_type in parsed:
            info = positions.get(doc_token) or {}
            space_id, parent_node_token = _position_fields(info)
            meta = DocumentMetadata(
                doc_uri=uri,
                title=title,
                backend=self.name,
                node_type=node_type,
                space_id=space_id,
                parent_node_token=parent_node_token,
            )
            results.append(
                SearchResult(
                    doc_uri=uri,
                    metadata=meta,
                    rank=rank,
                    snippet=snippet,
                    mode_used="keyword",
                    node_type=node_type,
                    space_id=space_id,
                    parent_node_token=parent_node_token,
                )
            )
        return results[:top_k]
