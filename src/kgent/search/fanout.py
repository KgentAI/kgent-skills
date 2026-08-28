"""Bounded multi-backend search fan-out with per-backend timeouts (§7.1; S33).

Backends are fanned out concurrently, bounded by a :class:`asyncio.Semaphore`
(config ``concurrency.max_parallel_backends``, default 4). Each backend call
runs under ``asyncio.wait_for`` so a slow/hung backend degrades to a recorded
timeout instead of blocking the whole search (S33).

Backend contract: each target exposes ``.name``, ``.trust_zone``, and a sync
or async ``.search(query, mode=..., top_k=..., timeout=...)`` method returning
``list[SearchResult]``. Sync methods (e.g. the test ``FakeBackend``) are
bridged through ``asyncio.to_thread`` so the event loop stays responsive.

Ordering to the caller is deferred to RRF (Task 6.3) — this module returns
successes in whichever order they completed under :func:`asyncio.gather`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any, Protocol

from kgent.types import SearchResult

__all__ = ["build_footer", "exit_code_for_failures", "fanout", "truncate"]


class SearchBackend(Protocol):
    """Minimal backend surface required for search fan-out (§7.1)."""

    name: str
    trust_zone: str
    capabilities: dict[str, Any]

    def search(self, query: str, mode: str, top_k: int, timeout: float) -> list[SearchResult]: ...


async def fanout(
    targets: Sequence[SearchBackend],
    query: str,
    mode: str,
    top_k: int,
    timeout: float,
    concurrency: int,
) -> tuple[list[SearchResult], list[dict[str, Any]], dict[str, dict[str, int | bool]]]:
    """Fan ``query`` out to every backend, bounded by ``concurrency``.

    Returns ``(successes, failures, clamps)``. A backend that raises is recorded
    as a failure with ``timed_out=False``; a backend still running after
    ``timeout`` seconds is cancelled and recorded with ``timed_out=True`` (S33:
    visible in the result footer, never silently dropped). Results from the
    remaining backends are always returned.

    ``clamps`` records, per backend, the fetch-k applied: ``{"requested": top_k,
    "fetch": min(top_k, backend limit), "clamped": fetch < requested}``
    (§3.7). Backends declaring no ``document_search.limits.max_results`` are not
    clamped (requested == fetch, clamped=False). Stored OUTSIDE ``SearchResult``
    so the ranking step (RRF, Task 6.3) knows each backend's true coverage.
    """
    if concurrency < 1:
        raise ValueError("concurrency must be >= 1")
    semaphore = asyncio.Semaphore(concurrency)

    def clamp_fetch(backend: SearchBackend) -> tuple[int, int, bool]:
        """Per-backend fetch-k: min(top_k, declared max_results) (§3.7)."""
        search = (backend.capabilities or {}).get("document_search")
        limits = search.get("limits") if isinstance(search, dict) else None
        limit = limits.get("max_results") if isinstance(limits, dict) else None
        if limit is None:
            return top_k, top_k, False
        fetch = min(top_k, int(limit))
        return top_k, fetch, fetch < top_k

    clamps: dict[str, dict[str, int | bool]] = {}

    async def call_one(
        backend: SearchBackend,
    ) -> tuple[str, list[SearchResult] | BaseException]:
        async with semaphore:
            try:
                results = await asyncio.wait_for(
                    asyncio.to_thread(
                        backend.search,
                        query,
                        mode=mode,
                        top_k=clamps[backend.name]["fetch"],
                        timeout=timeout,
                    ),
                    timeout=timeout,
                )
            except BaseException as exc:  # noqa: BLE001 — classified per-backend below
                return backend.name, exc
            return backend.name, results

    for backend in targets:
        requested, fetch, clamped = clamp_fetch(backend)
        clamps[backend.name] = {"requested": requested, "fetch": fetch, "clamped": clamped}

    outcomes = await asyncio.gather(
        *(call_one(backend) for backend in targets), return_exceptions=True
    )

    successes: list[SearchResult] = []
    failures: list[dict[str, Any]] = []
    for outcome in outcomes:
        if isinstance(outcome, BaseException):
            # Unexpected error inside call_one itself (e.g. semaphore setup).
            name, exc = "", outcome
            timed_out = isinstance(exc, TimeoutError)
            failures.append(
                {"backend": name, "error": _describe(exc, timeout), "timed_out": timed_out}
            )
            continue
        name, payload = outcome
        if isinstance(payload, BaseException):
            timed_out = isinstance(payload, TimeoutError)
            failures.append(
                {"backend": name, "error": _describe(payload, timeout), "timed_out": timed_out}
            )
        else:
            successes.extend(payload)
    return successes, failures, clamps


def truncate(results: Sequence[SearchResult], top_k: int) -> list[SearchResult]:
    """Slice an already-ranked result list to the top ``top_k`` (S31).

    Contract: the caller hands in a fully ranked (fused) list — truncation to
    the global ``--top-k`` total happens AFTER fusion, never per backend. Order
    is preserved, ``top_k=0`` yields ``[]``, and lists already within budget
    are returned unchanged (a copy).
    """
    if top_k < 0:
        raise ValueError("top_k must be >= 0")
    return list(results[:top_k])


def _describe(exc: BaseException, timeout: float) -> str:
    if isinstance(exc, TimeoutError):
        return f"timed out after {timeout}s"
    detail = str(exc) or exc.__class__.__name__
    return f"{exc.__class__.__name__}: {detail}"


def build_footer(failures: Sequence[dict[str, Any]]) -> str:
    """Build the result footer summarising backend failures/timeouts (§8.2, S33).

    Produces exactly ``"1 backend timed out"`` for a single timed-out backend
    (plural ``"N backends timed out"`` for N > 1); non-timeout failures are
    reported the same way ("N backends failed"). Returns ``""`` when there is
    nothing to report.
    """
    timed = sum(1 for f in failures if f["timed_out"])
    failed = len(failures) - timed
    parts: list[str] = []
    if timed == 1:
        parts.append("1 backend timed out")
    elif timed > 1:
        parts.append(f"{timed} backends timed out")
    if failed == 1:
        parts.append("1 backend failed")
    elif failed > 1:
        parts.append(f"{failed} backends failed")
    return ", ".join(parts)


def exit_code_for_failures(failures: Sequence[dict[str, Any]]) -> int:
    """Exit-code mapping for the CLI: 2 when any backend failed or timed out, else 0 (S33)."""
    return 2 if failures else 0
