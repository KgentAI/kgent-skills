"""CLI transport + CLI-capability adapter for backend adapters (§8.5).

Backend CLIs are invoked with argv arrays only — **never** a shell string
(S40, FM10). User-supplied strings travel as discrete arguments; argument
shape is validated before exec (N12). Timeouts normalize to
:class:`AdapterTimeoutError` and spawn failures to :class:`SubprocessError`
(§8.1). Backend DSLs are built with :func:`kgent.adapters.base.escape_query` —
raw user query interpolation is forbidden (S41).

:class:`CliCapabilityAdapter` (Task 7.2) is the shared §3.1 capability
implementation for CLI-backed backends (lark/dingtalk/wecom): it delegates
every capability call to the backend CLI via :func:`run_cli` under the wire
protocol v1 and translates canonical URIs ↔ native IDs only at the boundary
(§3.6) — native IDs never cross the adapter boundary.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from typing import Any, NamedTuple

from kgent.adapters.base import Adapter, _validate_argv
from kgent.errors import AdapterError, AdapterTimeoutError, SubprocessError
from kgent.types import Document, DocumentMetadata, FilterSpec, SearchResult
from kgent.uri import format_uri, parse_uri

__all__ = ["CliCapabilityAdapter", "SubprocessResult", "run_cli"]


class SubprocessResult(NamedTuple):
    """Normalized subprocess outcome: exit status + captured streams."""

    returncode: int
    stdout: str
    stderr: str


def run_cli(
    argv: list[str],
    timeout: float,
    *,
    env: dict[str, str] | None = None,
) -> SubprocessResult:
    """Run a backend CLI via an argv array with a hard timeout (§8.5).

    - ``shell=False`` is explicit: argv is never joined into a shell string
      (S40); metacharacters in user data stay inert.
    - ``timeout`` bounds the whole subprocess; :class:`AdapterTimeoutError`
      on expiry.
    - ``env=None`` inherits the parent environment; a provided ``env`` is
      passed verbatim to the subprocess.
    - Spawn failures (missing executable, etc.) raise :class:`SubprocessError`.
    """
    _validate_argv(argv)
    if timeout <= 0:
        raise ValueError(f"timeout must be positive, got {timeout}")
    try:
        proc = subprocess.run(
            argv,
            timeout=timeout,
            capture_output=True,
            text=True,
            shell=False,
            check=False,
            env=env,
            encoding="utf-8",
        )
    except subprocess.TimeoutExpired as exc:
        raise AdapterTimeoutError(f"adapter CLI timed out after {timeout:.1f}s") from exc
    except OSError as exc:
        raise SubprocessError(f"failed to start adapter CLI: {exc}") from exc
    return SubprocessResult(proc.returncode, proc.stdout, proc.stderr)


# ---------------------------------------------------------------------------
# CliCapabilityAdapter — §3.1 capabilities over an external CLI (Task 7.2)
# ---------------------------------------------------------------------------


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp from CLI JSON; ``None`` when absent/unparseable."""
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _optional_node_fields(payload: dict[str, Any]) -> tuple[str, str | None, str | None]:
    """Read the optional §7.2 node fields from a wire-v1 payload.

    Backends whose CLI contract carries ``node_type``/``space_id``/
    ``parent_node_token`` get wiki fidelity for free; payloads without them
    keep the historical defaults (``"doc"``, unset position). Values outside
    the §7.2 vocabulary are ignored rather than trusted — CLI output is
    unvalidated input (N12), and an unknown type must never leak into
    ``native_url``'s two-path rendering.
    """
    node_type = payload.get("node_type")
    if node_type not in ("doc", "wiki_node"):
        node_type = "doc"
    space_id = payload.get("space_id")
    parent = payload.get("parent_node_token")
    return (
        str(node_type),
        str(space_id) if space_id else None,
        str(parent) if parent else None,
    )


class CliCapabilityAdapter(Adapter):
    """§3.1 capability implementation delegating to an external CLI via :func:`run_cli`.

    Constructor: ``CliCapabilityAdapter(cmd, name, timeout)`` — ``cmd`` is the
    CLI invocation prefix as an argv array (e.g. ``["lark-cli"]``, or the fake
    ``["python", "fake_cli.py", "--state", "<file>", "lark"]`` in tests);
    ``name`` is the backend name forming the canonical-URI ``<backend>``
    segment (§3.6); ``timeout`` bounds every subprocess (§8.1).

    **Wire protocol v1** (real CLIs will be wrapped to this contract later):
    every call is ``<subcommand> <args> --json``, stdout is one JSON object:

    - ``documents create --title <t> --content <c>`` → ``{"id": <native-id>}``
    - ``documents read <native-id>`` → ``{"id", "title", "content",
      "updated_at", "version"}``
    - ``documents update <native-id> --content <c> [--version <rev>]`` →
      ``{"ok": true}``
    - ``documents delete|archive|unarchive <native-id>`` → ``{"ok": true}``
    - ``search --query <q> --keyword --top-k <n>`` →
      ``{"results": [{"id", "title", "snippet", "rank"}]}``
    - ``version`` → exit 0.

    **Errors**: nonzero exit with ``{"error": "<message>"}`` on stderr is
    normalized via :meth:`Adapter.normalize_error` → :class:`AdapterError`.
    In protocol v1 the adapter never raises a typed ``VersionConflict``: a
    stale ``--version`` surfaces as the normalized ``AdapterError``. The
    router's optimistic-concurrency path (which encodes ``VersionConflict``
    for re-read + fresh proposal, §3.9) runs against ``FakeBackend`` in unit
    tests and is unaffected. This boundary is documented in
    ``tests/test_adapters.py``.

    **URI ↔ native translation happens only here** (§3.6): callers hand in
    and receive canonical ``kgent://<backend>/<id>`` URIs; native IDs never
    cross the adapter boundary. URIs for other backends are rejected rather
    than forwarded to this backend's CLI. Queries travel as discrete argv
    elements (parameterization, S40) — no DSL string is composed, so
    :func:`kgent.adapters.base.escape_query` does not apply to v1 (it guards
    any future filter-DSL composition, S41).

    Approval/token/idempotency parameters are accepted for interface
    conformance but not yet carried by protocol v1 — approval flow is
    router-enforced (§3.4, §1.2). Semantic/hybrid search and listing are not
    part of protocol v1 and raise :class:`NotImplementedError` (the base
    signals unimplemented capabilities).
    """

    name: str = ""

    def __init__(self, cmd: list[str], name: str, timeout: float = 30.0) -> None:
        self.cmd = list(cmd)
        self.name = name
        self.timeout = timeout

    @property
    def capabilities(self) -> dict[str, Any]:
        """Declare §3.1 capabilities for this CLI-backed backend."""
        return {
            "document_storage": {
                "supported": True,
                "features": ["create", "read", "update", "delete", "archive", "unarchive", "list"],
            },
            "document_search": {
                "supported": True,
                "features": {"search_by_keywords": True},
            },
            "approval_flow": {
                "supported": True,
                "features": ["request_approval", "check_status", "execute_approved"],
            },
        }

    # ---- transport internals ---------------------------------------------

    def _run(self, args: list[str]) -> dict[str, Any]:
        """Run ``self.cmd + args + ["--json"]`` and decode the single JSON object.

        Nonzero exit → :meth:`Adapter.normalize_error` (stderr-derived
        message). Exit 0 whose JSON carries a truthy ``error`` key is also
        surfaced (failures are never swallowed when the CLI misbehaves);
        malformed stdout on exit 0 is an :class:`AdapterError`.
        """
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

    def _native_id(self, doc_uri: str) -> str:
        """Parse a canonical URI into this backend's native id (§3.6).

        Rejects URIs whose backend segment differs — another backend's URI
        must never reach this CLI.
        """
        backend, native_id = parse_uri(doc_uri)
        if backend != self.name:
            raise AdapterError(
                f"adapter {self.name!r} cannot operate on {doc_uri!r}: "
                f"URI backend {backend!r} does not match {self.name!r}"
            )
        return native_id

    def _canonical(self, native_id: str) -> str:
        return format_uri(self.name, native_id)

    # ---- §3.1 capability methods -----------------------------------------

    def create_document(self, title: str, content: str, metadata: DocumentMetadata) -> str:
        payload = self._run(["documents", "create", "--title", title, "--content", content])
        return self._canonical(str(payload["id"]))

    def read_document(self, doc_uri: str) -> Document:
        native_id = self._native_id(doc_uri)
        payload = self._run(["documents", "read", native_id])
        title = str(payload["title"])
        content = str(payload["content"])
        version = str(payload["version"]) if payload.get("version") is not None else None
        node_type, space_id, parent_node_token = _optional_node_fields(payload)
        meta = DocumentMetadata(
            doc_uri=doc_uri,
            title=title,
            backend=self.name,
            updated_at=_parse_timestamp(payload.get("updated_at")),
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
        """Update ``doc_uri``'s content; pass ``expected_version`` for OCC (§3.9).

        No-token OCC note (wire v1): when ``expected_version`` is ``None`` the
        CLI overwrites **unconditionally** — protocol v1 carries no
        ``updated_at`` precondition, so the ``updated_at`` guard that saves
        no-token backends (§3.9, S7 fallback) lives router/FakeBackend-side,
        not here. Protocol v1's update also sends content and ``--version``
        only — ``metadata.title`` is not pushed (documented; a real CLI
        wrapper would need a title leg).
        """
        native_id = self._native_id(doc_uri)
        args = ["documents", "update", native_id, "--content", content]
        if expected_version is not None:
            args += ["--version", expected_version]
        self._run(args)

    def delete_document(
        self,
        doc_uri: str,
        approval_token: str | None,
        idempotency_key: str,
        expected_version: str | None,
    ) -> None:
        self._run(["documents", "delete", self._native_id(doc_uri)])

    def archive_document(
        self, doc_uri: str, approval_token: str | None, idempotency_key: str
    ) -> None:
        self._run(["documents", "archive", self._native_id(doc_uri)])

    def unarchive_document(
        self, doc_uri: str, approval_token: str | None, idempotency_key: str
    ) -> None:
        self._run(["documents", "unarchive", self._native_id(doc_uri)])

    def search(
        self,
        query: str,
        *,
        mode: str = "keyword",
        top_k: int = 10,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> list[SearchResult]:
        """Dispatch search by mode (keyword/semantic/hybrid) to the right method."""
        if mode == "keyword":
            return self.search_by_keywords(query, top_k=top_k)
        elif mode == "semantic":
            return self.search_by_semantics(query, top_k=top_k)
        elif mode == "hybrid":
            return self.search_hybrid(query, top_k=top_k)
        else:
            raise AdapterError(f"unknown search mode: {mode!r}")

    def search_by_keywords(
        self,
        query: str,
        filters: FilterSpec | None = None,
        top_k: int = 10,
        fields: list[str] | None = None,
    ) -> list[SearchResult]:
        payload = self._run(["search", "--query", query, "--keyword", "--top-k", str(top_k)])
        results: list[SearchResult] = []
        for item in payload.get("results") or []:
            uri = self._canonical(str(item["id"]))
            title = str(item.get("title", ""))
            rank = int(item.get("rank", 0))
            snippet_value = item.get("snippet")
            node_type, space_id, parent_node_token = _optional_node_fields(item)
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
                    snippet=str(snippet_value) if snippet_value is not None else None,
                    mode_used="keyword",
                    node_type=node_type,
                    space_id=space_id,
                    parent_node_token=parent_node_token,
                )
            )
        return results

    def check_version(self) -> str:
        """Run the protocol's ``version`` leg (exit 0) and return the version string."""
        payload = self._run(["version"])
        return str(payload.get("version", ""))
