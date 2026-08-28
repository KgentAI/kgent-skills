"""Reciprocal rank fusion across per-backend ranked lists (§7.3; S34).

Backend-native relevance scores are not comparable across engines, so fusion
uses rank positions only: each occurrence contributes ``1 / (k + rank)``
(``rank`` is the 1-based ``SearchResult.rank`` field, per list) and the
contributions are summed per ``doc_uri``. ``score_native`` is NEVER compared
across backends (S34) — :func:`rrf` does not even read it.

The returned list is fully ranked with ties broken, but NOT truncated: the
global ``--top-k`` total (S31) is applied by the caller afterwards via
:func:`kgent.search.fanout.truncate` or the convenience wrapper
:func:`rank_and_truncate`.

Tiebreakers apply only when fused scores are equal — the sort key is
lexicographic ``(-score, recency, priority, doc_uri)``, so any score
difference dominates. In order:

1. **Recency** — newer ``metadata.updated_at`` ranks first within the band;
   a missing timestamp ranks as oldest (last).
2. **Backend priority** — from the ``priority`` argument (config
   ``backends[name]["priority"]``; lower number = higher priority, missing or
   ``None`` treated as max → last).
3. **``doc_uri``** ascending — deterministic, stable final ordering.

Duplicate-backend guard: two input lists whose results share
``metadata.backend`` are concatenated before scoring. Because ``rank`` is the
1-based per-list position, RRF over the concatenated results is identical to
scoring each list separately, so the duplicate label can neither mis-fuse nor
crash. The guard exists to keep the name-keyed metadata produced by fanout
(Task 6.2, ``failures``/``clamps`` keyed by backend name) consistent.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence

from kgent.search.fanout import truncate
from kgent.types import SearchResult

__all__ = ["rank_and_truncate", "rrf"]

PrioritySource = Mapping[str, int | None] | Callable[[str], int | None]
"""Accepted shapes for the ``priority`` argument: mapping or callable."""

_INF = float("inf")


def rrf(
    ranked_lists: Sequence[Sequence[SearchResult]],
    *,
    k: int = 60,
    priority: PrioritySource | None = None,
) -> list[SearchResult]:
    """Fuse per-backend ranked result lists into one ranked list (§7.3).

    Each list is in rank order and every :class:`SearchResult` carries its
    1-based ``rank``. A document found in several lists accumulates a
    contribution ``1 / (k + rank)`` per list (duplicate-backend lists are
    concatenated first — same scores). Ties are broken per the module
    docstring. Results are returned unchanged (their frozen ``rank`` fields
    are the backends' own, not rewritten). Not truncated.
    """
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")

    scores: dict[str, float] = defaultdict(float)
    first: dict[str, SearchResult] = {}  # first-seen result per doc_uri (tiebreak basis)
    for ranked in ranked_lists:
        for result in ranked:
            uri = result.doc_uri
            scores[uri] += 1.0 / (k + result.rank)
            if uri not in first:
                first[uri] = result

    def sort_key(uri: str) -> tuple[float, float, float, str]:
        result = first[uri]
        updated = result.metadata.updated_at
        # newer updated_at -> more negative -> sorts first; None -> +inf -> last
        recency: float = _INF if updated is None else -updated.timestamp()
        value = _priority_value(priority, result.metadata.backend)
        # lower number = higher priority -> smaller -> first; None -> +inf -> last
        backend_priority: float = _INF if value is None else float(value)
        return (-scores[uri], recency, backend_priority, uri)

    return [first[uri] for uri in sorted(scores, key=sort_key)]


def rank_and_truncate(
    ranked_lists: Sequence[Sequence[SearchResult]],
    top_k: int,
    *,
    k: int = 60,
    priority: PrioritySource | None = None,
    clamps: Mapping[str, Mapping[str, int | bool]] | None = None,
) -> list[SearchResult]:
    """Convenience: fuse with :func:`rrf`, then slice to the global total.

    ``top_k`` is a total across backends (S31): truncation happens AFTER
    fusion, exactly once (``top_k < 0`` raises via :func:`truncate`).

    ``clamps`` is the 3rd return element of
    :func:`kgent.search.fanout.fanout` (Task 6.2) — per-backend
    ``{"requested", "fetch", "clamped"}``. When a backend was clamped
    (``clamped=True``), its list beyond ``fetch`` was truncated server-side,
    so the list handed to RRF simply contains what was fetched: RRF scores
    what is present and needs no adjustment. A clamped backend is only
    under-represented at the tail of its own list (its head ranks are
    unaffected), and the final total is still enforced by the slice here.
    """
    return truncate(rrf(ranked_lists, k=k, priority=priority), top_k)


def _priority_value(source: PrioritySource | None, backend: str) -> int | None:
    """Resolve the tiebreak priority for ``backend`` (``None`` = unset → max)."""
    if source is None:
        return None
    if callable(source):
        return source(backend)
    if isinstance(source, Mapping):
        return source.get(backend)
    raise TypeError(f"priority must be a mapping or callable, got {type(source).__name__}")
