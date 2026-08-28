"""Router facade: bundles config + backends + journal + audit + session (§1.4).

The ``Router`` is the single entry point the CLI (and skills) use to resolve
routing intents and execute writes. It delegates to ``resolve.py`` for intent
resolution and ``policy.py`` for write execution, so the policy/journal/audit
invariants are enforced in one place.

The ``backends`` dict maps backend names to adapter instances (real adapters
in production, fakes in tests). The CLI wires real adapters via the adapter
registry (Task 9.4); tests register fakes directly.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from kgent.config.schema import Config
from kgent.router.audit import AuditLog
from kgent.router.journal import Journal
from kgent.router.policy import OpResult, execute_confirmed
from kgent.router.resolve import resolve_intent
from kgent.search.fanout import fanout
from kgent.types import RoutingIntent, SearchResult, WriteProposal

__all__ = ["Router"]


@dataclass
class Router:
    """Single facade for routing + execution (§1.4).

    ``config`` carries the fully-defaulted, validated configuration.
    ``backends`` maps backend names to write-capable adapter instances.
    ``journal`` and ``audit`` are the append-only local records. ``session``
    is the per-invocation set used by one-shot warnings (e.g. S16 query-leak).
    """

    config: Config
    backends: dict[str, Any]
    journal: Journal
    audit: AuditLog
    session: set[str] = field(default_factory=set)

    def resolve_intent(
        self,
        operation: str,
        *,
        doc_uri: str | None = None,
        query: str | None = None,
        selection: str | None = None,
        content_type: str | None = None,
        proposal: WriteProposal | None = None,
    ) -> RoutingIntent:
        """Resolve a :class:`RoutingIntent` for ``operation`` (§1.5, S58)."""
        return resolve_intent(
            self.config,
            operation,
            doc_uri=doc_uri,
            query=query,
            selection=selection,
            content_type=content_type,
            proposal=proposal,
        )

    def execute(
        self,
        proposal: WriteProposal,
        *,
        confirmation: str,
        approval_tokens: dict[str, str] | None = None,
    ) -> OpResult:
        """Execute a confirmed write and journal/audit the result (§5.6, S1–S4)."""
        return execute_confirmed(
            proposal,
            confirmation,
            backends=self.backends,
            journal=self.journal,
            audit=self.audit,
            approval_tokens=approval_tokens,
        )

    async def search(
        self,
        query: str,
        *,
        mode: str = "keyword",
        top_k: int = 10,
        selection: str | None = None,
    ) -> tuple[list[SearchResult], list[dict[str, Any]], dict[str, dict[str, Any]]]:
        """Fan a search query out to the resolved backends (§7.1, S33).

        Returns ``(successes, failures, clamps)`` from
        :func:`~kgent.search.fanout.fanout`. Timeouts and per-backend failures
        are captured; remaining results are always returned.
        """
        intent = self.resolve_intent("search", query=query, selection=selection)
        targets = [self.backends[t.backend] for t in intent.targets if t.backend in self.backends]
        timeouts = self.config.defaults.get("timeouts") or {}
        if not isinstance(timeouts, dict):
            timeouts = {}
        search_seconds = int(timeouts.get("search_seconds", 10))
        concurrency_cfg = self.config.defaults.get("concurrency") or {}
        if not isinstance(concurrency_cfg, dict):
            concurrency_cfg = {}
        max_parallel = int(concurrency_cfg.get("max_parallel_backends", 4))
        return await fanout(
            targets,
            query,
            mode=mode,
            top_k=top_k,
            timeout=float(search_seconds),
            concurrency=max_parallel,
        )

    def search_sync(
        self,
        query: str,
        *,
        mode: str = "keyword",
        top_k: int = 10,
        selection: str | None = None,
    ) -> tuple[list[SearchResult], list[dict[str, Any]], dict[str, dict[str, Any]]]:
        """Synchronous wrapper around :meth:`search` for CLI use."""
        return asyncio.run(
            self.search(query, mode=mode, top_k=top_k, selection=selection)
        )
