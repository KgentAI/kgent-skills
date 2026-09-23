"""Confluence adapter (spec 2026-09-22): read lanes + wiki capability over official ``acli``.

Deprecated (skills): 平台操作经 confluence-integration（ADR 0004 同规）；CLI 面
保留供调试与 kgent hosted backend 车道。**读车道 + wiki 块**（dingtalk/wecom
先例 + lark wiki 先例，spec 决策表）：

- :meth:`ConfluenceAdapter.search_by_keywords` — CQL 检索（``text ~`` 全文，
  allowlist 经 ``space in (...)`` 子句注入，:func:`build_cql` 负责转义）；
  仅 keywords 模式——Confluence Cloud 无语义端点，semantics/hybrid 不支持。
- :meth:`ConfluenceAdapter.read_document` — 页面读取（``version.number`` 是
  台账 revision 数据源）；正文 ``body.storage`` 经格式桥
  （:mod:`kgent.formats`，ADR 0016）转 markdown——全 repo 唯一转换实现，
  skill 与 adapter 共用，禁止第二套。
- wiki 块 — spaces list/create、page node create（``kgent wiki …`` 车道）。

**写车道不接**（create/update/delete document 一律 ``NotImplementedError``）：
一切 Confluence 写入经 confluence-integration skill——journal 台账、
``version.number`` CAS、version-revert 补偿都活在 skill 侧。backend 整体不
声明 archive/unarchive（Confluence 无页面级 archive API）。

**A1 探针锚点**：acli 的 Confluence 面宽度未经本机实证（ADR 0015 后果条款）。
命令形状与 payload 键位全部集中在模块级 ``_cmd_*`` argv 构造器与
``_extract_*`` 帮助函数——``tools/confluence-probe.sh`` 对账出 live 真值漂移
时**只改这里**。测试 fake（tests/test_confluence_adapter.py）按同一契约回填。

Windows 解析：acli 是原生二进制（非 npm .cmd shim），``CreateProcess`` 的
``.exe`` 自动补全可用，默认 ``["acli"]`` 即可（lark-cli.cmd 教训不适用）。
"""

from __future__ import annotations

import sys
from typing import Any

from kgent.adapters.cli_adapter import CliCapabilityAdapter, run_cli
from kgent.errors import AdapterError
from kgent.formats import storage_to_markdown
from kgent.types import Document, DocumentMetadata, SearchResult

__all__ = ["ConfluenceAdapter", "build_cql"]


# ---------------------------------------------------------------------------
# CQL composition (negative constraint: query text never breaks out of quotes)
# ---------------------------------------------------------------------------


def _cql_quote(value: str) -> str:
    """Quote one CQL string literal (double quotes, ``\\`` and ``"`` escaped)."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_cql(query: str, spaces: list[str] | None = None) -> str:
    """Build the search CQL: ``type=page [AND space in (...)] AND text ~ "q"``.

    The allowlist clause is code-injected from config (never string-spliced
    from untrusted input) and every literal passes :func:`_cql_quote`, so
    hostile query/space-key text cannot escape its quoted literal — the
    space-scoping cannot be diluted from the query side (spec Tier table).
    """
    parts = ["type=page"]
    if spaces:
        keys = ", ".join(_cql_quote(key) for key in spaces)
        parts.append(f"space in ({keys})")
    parts.append(f"text ~ {_cql_quote(query)}")
    return " AND ".join(parts)


# ---------------------------------------------------------------------------
# payload extraction anchors (A1 probe reconciliation points)
# ---------------------------------------------------------------------------


def _extract_results(payload: dict[str, Any]) -> list[Any]:
    hits = payload.get("results")
    return hits if isinstance(hits, list) else []


def _extract_native_id(item: dict[str, Any]) -> str:
    value = item.get("id")
    return str(value) if value is not None else ""


def _extract_version(payload: dict[str, Any]) -> str:
    """``version.number``（v2 端点嵌套）或平铺 ``version``（契约兜底候选）。"""
    version = payload.get("version")
    if isinstance(version, dict):
        number = version.get("number")
        return str(number) if number is not None else ""
    return str(version) if version is not None else ""


def _extract_body_storage(payload: dict[str, Any]) -> str:
    body = payload.get("bodyStorage")
    if isinstance(body, str):
        return body
    body = payload.get("body")
    if isinstance(body, dict):
        storage = body.get("storage")
        if isinstance(storage, dict):
            value = storage.get("value")
            return str(value) if value is not None else ""
    return ""


class ConfluenceAdapter(CliCapabilityAdapter):
    """Read lanes + wiki capability over the official Atlassian CLI (ADR 0015)."""

    def __init__(
        self,
        cmd: list[str] | None = None,
        timeout: float = 30.0,
        spaces: list[str] | None = None,
    ) -> None:
        if cmd is None:
            cmd = ["acli"]
        super().__init__(cmd, "confluence", timeout)
        self.spaces = list(spaces or [])

    def _run(self, args: list[str]) -> dict[str, Any]:
        """Wire-v1 ``_run`` with the transport resolved from *this* module.

        Module-level :func:`run_cli` (not ``cli_adapter``'s global) so tests
        patch one name (``kgent.adapters.confluence.run_cli``) — the dingtalk
        fixture pattern.
        """
        import json

        from kgent.errors import AdapterError

        argv = self.cmd + args + ["--json"]
        self._check_argv(argv)
        result = run_cli(argv, timeout=self.timeout)
        if result.returncode != 0:
            raise self.normalize_error(result.returncode, result.stderr)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AdapterError(
                f"adapter {self.name!r}: CLI exited 0 with malformed JSON stdout: "
                f"{result.stdout[:200]!r}"
            ) from exc
        if not isinstance(payload, dict):
            raise AdapterError(
                f"adapter {self.name!r}: CLI exited 0 with non-object JSON: {result.stdout[:200]!r}"
            )
        if payload.get("error"):
            raise AdapterError(
                f"adapter {self.name!r}: CLI reported error on exit 0: {payload['error']}"
            )
        return payload

    @property
    def capabilities(self) -> dict[str, Any]:
        """Read-only storage subset + keyword search + wiki block (spec 决策表)."""
        return {
            "document_storage": {
                "supported": True,
                "features": ["read", "list"],
            },
            "document_search": {
                "supported": True,
                "features": {"search_by_keywords": True},
            },
            "approval_flow": {
                "supported": False,
                "features": [],
            },
            "wiki": {
                "supported": True,
                "features": ["spaces_list", "spaces_create", "node_create"],
            },
        }

    # ---- URI boundary: native id is the numeric Confluence page id --------

    def _native_id(self, doc_uri: str) -> str:
        backend, native_id = self._parse(doc_uri)
        if backend != self.name:
            raise AdapterError(
                f"adapter {self.name!r} cannot operate on {doc_uri!r}: "
                f"URI backend {backend!r} does not match {self.name!r}"
            )
        if not native_id.isdigit():
            raise AdapterError(
                f"adapter {self.name!r}: confluence page id must be numeric, got {native_id!r}"
            )
        return native_id

    def _parse(self, doc_uri: str) -> tuple[str, str]:
        from kgent.uri import parse_uri

        return parse_uri(doc_uri)

    # ---- search lane ------------------------------------------------------

    def search_by_keywords(
        self,
        query: str,
        filters: Any = None,
        top_k: int = 10,
        fields: list[str] | None = None,
    ) -> list[SearchResult]:
        payload = self._run(_cmd_search(query, self.spaces, top_k))
        results: list[SearchResult] = []
        for item in _extract_results(payload):
            if not isinstance(item, dict):
                continue
            native = _extract_native_id(item)
            if not native:
                continue
            uri = self._canonical(native)
            space_id = item.get("spaceId")
            meta = DocumentMetadata(
                doc_uri=uri,
                title=str(item.get("title", "")),
                backend=self.name,
                node_type="doc",
                space_id=str(space_id) if space_id else None,
            )
            snippet = item.get("snippet")
            results.append(
                SearchResult(
                    doc_uri=uri,
                    metadata=meta,
                    rank=int(item.get("rank", 0)),
                    snippet=str(snippet) if snippet is not None else None,
                    mode_used="keyword",
                    node_type="doc",
                    space_id=str(space_id) if space_id else None,
                )
            )
        return results

    # ---- read lane --------------------------------------------------------

    def read_document(self, doc_uri: str) -> Document:
        native_id = self._native_id(doc_uri)
        payload = self._run(_cmd_page_get(native_id))
        title = str(payload.get("title", ""))
        # 格式桥 read 方向（ADR 0016）：body.storage → markdown，全 repo 唯一实现
        content = storage_to_markdown(_extract_body_storage(payload))
        space_id = payload.get("spaceId")
        meta = DocumentMetadata(
            doc_uri=doc_uri,
            title=title,
            backend=self.name,
            updated_at=self._ts(payload.get("updatedAt")),
            version=_extract_version(payload) or None,
            node_type="doc",
            space_id=str(space_id) if space_id else None,
        )
        return Document(doc_uri=doc_uri, title=title, content=content, metadata=meta)

    def _ts(self, value: Any) -> Any:
        from kgent.adapters.cli_adapter import _parse_timestamp

        return _parse_timestamp(value)

    # ---- wiki (knowledge space) capability --------------------------------

    def list_wiki_spaces(self) -> list[dict[str, str]]:
        payload = self._run(_cmd_space_list())
        spaces: list[dict[str, str]] = []
        for item in _extract_results(payload):
            if not isinstance(item, dict):
                continue
            sid = item.get("id")
            if sid is None:
                continue
            spaces.append(
                {
                    "space_id": str(sid),
                    "name": str(item.get("name", "")),
                    "key": str(item.get("key", "")),
                }
            )
        return spaces

    def create_wiki_space(self, name: str) -> str:
        payload = self._run(_cmd_space_create(name))
        sid = payload.get("id")
        if sid is None:
            raise AdapterError(f"acli space create returned no id: {payload}")
        return str(sid)

    def create_wiki_node(
        self,
        title: str,
        content: str,
        metadata: DocumentMetadata,
        space_id: str,
        parent_node_token: str | None,
    ) -> str:
        """Create a page under ``space_id`` (optionally under ``parent``).

        ``content`` is markdown → minimal storage XHTML via the format bridge
        (ADR 0016) — page creation is a wiki-lane write and still goes through
        the shared converter.
        """
        from kgent.formats import markdown_to_storage

        payload = self._run(
            _cmd_page_create(space_id, title, markdown_to_storage(content), parent_node_token)
        )
        native = _extract_native_id(payload)
        if not native:
            raise AdapterError(f"acli page create returned no id: {payload}")
        return self._canonical(native)

    # ---- write lanes: deliberately unwired (ADR 0004; spec 决策表) --------

    def create_document(self, title: str, content: str, metadata: DocumentMetadata) -> str:
        raise NotImplementedError(
            "confluence document writes go through confluence-integration (ADR 0004)"
        )

    def update_document(
        self,
        doc_uri: str,
        content: str,
        metadata: DocumentMetadata,
        approval_token: str | None,
        idempotency_key: str,
        expected_version: str | None,
    ) -> None:
        raise NotImplementedError(
            "confluence document writes go through confluence-integration (ADR 0004)"
        )

    def delete_document(
        self,
        doc_uri: str,
        approval_token: str | None,
        idempotency_key: str,
        expected_version: str | None,
    ) -> None:
        raise NotImplementedError(
            "confluence document writes go through confluence-integration (ADR 0004)"
        )

    def archive_document(
        self, doc_uri: str, approval_token: str | None, idempotency_key: str
    ) -> None:
        raise NotImplementedError("confluence has no page-level archive API (spec 2026-09-22)")

    def unarchive_document(
        self, doc_uri: str, approval_token: str | None, idempotency_key: str
    ) -> None:
        raise NotImplementedError("confluence has no page-level archive API (spec 2026-09-22)")

    def list_documents(self, filters: Any, limit: int) -> list[Any]:
        raise NotImplementedError("list_documents")

    def search_by_semantics(
        self,
        query: str,
        filters: Any = None,
        top_k: int = 10,
        similarity_threshold: float | None = None,
    ) -> list[SearchResult]:
        raise NotImplementedError("confluence offers no semantic search endpoint")

    def search_hybrid(
        self,
        query: str,
        filters: Any = None,
        top_k: int = 10,
        keyword_weight: float = 0.3,
        semantic_weight: float = 0.7,
        similarity_threshold: float | None = None,
    ) -> list[SearchResult]:
        raise NotImplementedError("confluence offers no semantic search endpoint")


# ---------------------------------------------------------------------------
# argv builders (A1 probe reconciliation points — command shapes live here)
# ---------------------------------------------------------------------------


def _cmd_search(query: str, spaces: list[str] | None, top_k: int) -> list[str]:
    return ["search", "--cql", build_cql(query, spaces), "--limit", str(top_k)]


def _cmd_page_get(page_id: str) -> list[str]:
    return ["page", "get", "--id", page_id, "--body-format", "storage"]


def _cmd_space_list() -> list[str]:
    return ["space", "list", "--limit", "250"]


def _cmd_space_create(name: str) -> list[str]:
    return ["space", "create", "--name", name]


def _cmd_page_create(
    space_key: str, title: str, body_storage: str, parent_id: str | None
) -> list[str]:
    args = ["page", "create", "--space", space_key, "--title", title, "--content", body_storage]
    if parent_id is not None:
        args += ["--parent", parent_id]
    return args


#: win32 note: acli ships a native binary; CreateProcess resolves ``acli.exe``
#: from PATH without a ``.cmd`` suffix (unlike the npm-shim platform CLIs).
if sys.platform == "win32":  # pragma: no cover - documentation anchor
    pass
