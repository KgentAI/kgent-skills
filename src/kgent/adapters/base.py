"""Backend adapter base: capability contract, transport helpers, and budgets (§1.2, §3.1, §8.1, §8.5).

Concrete adapters (Task 7.2: lark/dingtalk/wecom) override the capability
methods their backend declares (§3.1 capability protocols live in
``capabilities.interface``; this base carries the shared cross-cutting
helpers every adapter needs):

- :meth:`Adapter.invoke` — capability dispatch by name.
- :meth:`Adapter.normalize_error` — CLI exit status → ``KgentError``.
- :meth:`Adapter._check_argv` — argument-shape validation before exec (N12, §8.5).
- :func:`escape_query` — backend filter-DSL escaping; raw user query strings are
  never interpolated unescaped (S41, §8.5).
- :class:`RetryBudget` — transient retries (3 attempts, exponential backoff)
  are budgeted separately from rate-limit queueing, which never counts against
  the transient budget and is bounded by the operation timeout (S47, N13, §8.1).
"""

from __future__ import annotations

from abc import ABC
from collections.abc import Sequence
from typing import Any

from kgent.errors import AdapterError, KgentError

__all__ = ["Adapter", "RetryBudget", "escape_query", "normalize_error_to_kgent"]


# ---------------------------------------------------------------------------
# Argument-shape validation (N12, §8.5)
# ---------------------------------------------------------------------------


def _validate_argv(argv: Sequence[object]) -> None:
    """Reject argv arrays containing anything but strings, before exec (N12)."""
    if not isinstance(argv, (list, tuple)):
        raise AdapterError(f"argv must be a list of strings, got {type(argv).__name__}")
    for i, arg in enumerate(argv):
        if not isinstance(arg, str):
            raise AdapterError(f"argv[{i}] must be str, got {type(arg).__name__}")


# ---------------------------------------------------------------------------
# Query-language escaping (§8.5, S41)
# ---------------------------------------------------------------------------

#: Backslash-escaped character sets per backend DSL dialect. ``generic`` is the
#: safe default and must *always* ensure the raw string never appears escaped —
#: unknown dialects degrade to it rather than risk raw interpolation.
_DSL_ESCAPE_CHARS: dict[str, frozenset[str]] = {
    "generic": frozenset({"\\", '"', "'", "%", "*"}),
    "lark": frozenset({"\\", '"'}),
    "sql": frozenset({"\\", "'", "%", "_"}),
}


def escape_query(query: str, dsl: str = "generic") -> str:
    """Escape ``query`` for a backend filter DSL (S41).

    Every dangerous character is backslash-escaped; backslash itself is
    escaped first so a user-supplied ``\\`` can never neutralize our escapes.
    The result differs from the raw string wherever the raw string contained
    any escapable character — adapter requests are built from escaped queries
    only, never from raw user strings (§8.5).
    """
    chars = _DSL_ESCAPE_CHARS.get(dsl, _DSL_ESCAPE_CHARS["generic"])
    parts: list[str] = []
    for ch in query:
        if ch in chars:
            parts.append("\\" + ch)
        else:
            parts.append(ch)
    return "".join(parts)


# ---------------------------------------------------------------------------
# Error normalization (§8.1, §8.2)
# ---------------------------------------------------------------------------


def normalize_error_to_kgent(returncode: int, stderr: str) -> KgentError:
    """Map a backend CLI exit to a ``KgentError`` (nonzero → ``AdapterError``).

    The message is stderr-derived (§8.2: failures are surfaced, never dropped)
    with a bounded excerpt so hostile stderr cannot bloat logs.
    """
    if returncode == 0:
        raise ValueError(f"normalize_error called for successful exit ({returncode})")
    message = f"adapter CLI failed with exit code {returncode}"
    tail = stderr.strip() if stderr else ""
    if tail:
        if len(tail) > 512:
            tail = tail[:512] + "…"
        message += f": {tail}"
    return AdapterError(message)


# ---------------------------------------------------------------------------
# Adapter ABC (§1.2, §3.1, §8.5)
# ---------------------------------------------------------------------------


class Adapter(ABC):
    """Backend adapter base: §3.1 capability stubs + shared transport helpers.

    Subclasses (Task 7.2) implement the capability methods their backend
    declares; unimplemented ones raise :class:`NotImplementedError` here.
    ``Adapter`` is an ``ABC`` marker so adapters share dispatch, error
    normalization, and argv-shape validation from one place — the structural
    capability contract itself lives in ``capabilities.interface``.
    """

    #: Adapter name, e.g. ``"lark-cli"`` (§1.5).
    name: str = ""

    # ---- §3.1 capability method stubs (overridden by concrete adapters) ----

    def create_document(self, title: str, content: str, metadata: Any) -> str:
        raise NotImplementedError("create_document")

    def read_document(self, doc_uri: str) -> Any:
        raise NotImplementedError("read_document")

    def update_document(
        self,
        doc_uri: str,
        content: str,
        metadata: Any,
        approval_token: str | None,
        idempotency_key: str,
        expected_version: str | None,
    ) -> None:
        raise NotImplementedError("update_document")

    def delete_document(
        self,
        doc_uri: str,
        approval_token: str | None,
        idempotency_key: str,
        expected_version: str | None,
    ) -> None:
        raise NotImplementedError("delete_document")

    def archive_document(
        self, doc_uri: str, approval_token: str | None, idempotency_key: str
    ) -> None:
        raise NotImplementedError("archive_document")

    def unarchive_document(
        self, doc_uri: str, approval_token: str | None, idempotency_key: str
    ) -> None:
        raise NotImplementedError("unarchive_document")

    def list_documents(self, filters: Any, limit: int) -> list[Any]:
        raise NotImplementedError("list_documents")

    def search_by_keywords(
        self,
        query: str,
        filters: Any = None,
        top_k: int = 10,
        fields: list[str] | None = None,
    ) -> list[Any]:
        raise NotImplementedError("search_by_keywords")

    def search_by_semantics(
        self,
        query: str,
        filters: Any = None,
        top_k: int = 10,
        similarity_threshold: float | None = None,
    ) -> list[Any]:
        raise NotImplementedError("search_by_semantics")

    def search_hybrid(
        self,
        query: str,
        filters: Any = None,
        top_k: int = 10,
        keyword_weight: float = 0.3,
        semantic_weight: float = 0.7,
        similarity_threshold: float | None = None,
    ) -> list[Any]:
        raise NotImplementedError("search_hybrid")

    def request_approval(self, doc_uri: str, approvers: list[str], operation: str) -> str:
        raise NotImplementedError("request_approval")

    def check_approval(self, approval_id: str) -> Any:
        raise NotImplementedError("check_approval")

    def execute_approved(self, doc_uri: str, approval_id: str) -> None:
        raise NotImplementedError("execute_approved")

    # ---- shared transport helpers ----

    def invoke(self, method: str, **kwargs: Any) -> Any:
        """Dispatch a capability call by name (§1.5 routing intent → adapter)."""
        fn = getattr(self, method, None)
        if fn is None or not callable(fn):
            raise AdapterError(f"adapter {self.name!r} has no capability {method!r}")
        return fn(**kwargs)

    def normalize_error(self, returncode: int, stderr: str) -> KgentError:
        """Normalize a CLI exit/stream pair to a ``KgentError`` (§8.1, §8.2)."""
        return normalize_error_to_kgent(returncode, stderr)

    @staticmethod
    def _check_argv(argv: list[str]) -> None:
        """N12: validate argument shape before exec (§8.5)."""
        _validate_argv(argv)


# ---------------------------------------------------------------------------
# RetryBudget (§8.1; S47, N13)
# ---------------------------------------------------------------------------


class RetryBudget:
    """Bounded-retry + rate-limit-queue accounting for adapter calls (§8.1).

    Transient failures (network, 5xx) are retried up to ``retries`` attempts
    with exponential backoff (:meth:`backoff_delay`). ``429 Retry-After``
    responses are *queued*, not retried: queueing accumulates toward the
    operation timeout and **never** counts against the transient-attempt
    budget (S47, N13). When queueing would exceed the operation timeout,
    :meth:`on_rate_limit` returns ``False`` and the caller surfaces a
    rate-limit-named failure.
    """

    def __init__(self, retries: int = 3, backoff_base: float = 0.25) -> None:
        self.retries = retries
        self.backoff_base = backoff_base
        self.transient_attempts = 0
        self.rate_limit_queued = 0.0

    def on_transient_error(self) -> bool:
        """Book a transient retry; ``False`` once the budget is exhausted."""
        if self.transient_attempts >= self.retries:
            return False
        self.transient_attempts += 1
        return True

    def on_rate_limit(self, retry_after: float, operation_timeout: float) -> bool:
        """Queue a rate-limited request; ``False`` if queueing would exceed the timeout.

        Returns ``True`` and books ``retry_after`` seconds of queueing when the
        total queued time stays within ``operation_timeout``; returns ``False``
        (leaving the counters untouched) when the request cannot be queued —
        the caller then surfaces a failure named after the rate limit (S47).
        """
        if self.rate_limit_queued + retry_after > operation_timeout:
            return False
        self.rate_limit_queued += retry_after
        return True

    def backoff_delay(self) -> float:
        """Exponential backoff for the *next* transient retry (deterministic)."""
        if self.transient_attempts == 0:
            return 0.0
        return self.backoff_base * float(2 ** (self.transient_attempts - 1))
