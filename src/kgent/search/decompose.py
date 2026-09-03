"""Compound-query decomposition (§7.4; S57).

The router NEVER reasons (§1.4): it ships a deterministic fallback that
returns the query unchanged. LLM-assisted decomposition is an INJECTED
callable owned by the skill layer — the router only ever validates and
applies what it is given, and never invents a decomposition.

The skill layer consumes the returned :class:`DecompositionResult`, runs the
sub-queries in parallel (each under the §7.1 timeout budget), and returns the
results grouped by sub-query with provenance — no cross-sub-query fusion, so
the skill can answer each part and cite its sources (§7.4). This module is
only the decomposition step; fan-out lives in
:mod:`kgent.search.fanout` and ranking in :mod:`kgent.search.rank`.

Contract of :func:`decompose_query`:

- ``decomposer`` provided → it is called with the query; its result becomes
  ``sub_queries`` after ORDER-PRESERVING dedupe and dropping of empty strings.
  ``decomposed`` is ``True`` exactly when more than one distinct non-empty
  sub-query remains.
- ``decomposer`` is ``None`` → the deterministic fallback:
  ``(sub_queries=[query], decomposed=False)``. The original query is the only
  ground truth; nothing is ever fabricated, and a simple query is searched
  as-is (§7.4 "decomposition happens only for genuinely compound queries").
- An injected decomposer yielding nothing usable (e.g. only empty strings)
  degrades to the same passthrough — never an empty decomposition.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

__all__ = ["DecompositionResult", "decompose_query"]


@dataclass
class DecompositionResult:
    """Outcome of a query-decomposition attempt (§7.4; S57).

    ``sub_queries`` are ordered (first-encounter order after dedupe) and
    never empty as a whole. ``decomposed`` is ``True`` exactly when more than
    one distinct sub-query remains — the flag the caller uses to decide
    whether parallel fan-out is warranted.
    """

    sub_queries: list[str]
    decomposed: bool


def _clean_sub_queries(raw: Sequence[str]) -> list[str]:
    """Order-preserving dedupe + drop of empty sub-queries.

    Empty means the string is empty or whitespace-only. Dedupe is on the
    EXACT string the decomposer returned — sub-queries are forwarded verbatim
    to search, so no normalization that could change search behavior.
    """
    cleaned: list[str] = []
    seen: set[str] = set()
    for sub in raw:
        if not isinstance(sub, str):
            raise TypeError(f"decomposer must return list[str], got element {type(sub).__name__}")
        if not sub.strip():
            continue
        if sub in seen:
            continue
        seen.add(sub)
        cleaned.append(sub)
    return cleaned


def decompose_query(
    query: str,
    *,
    decomposer: Callable[[str], list[str]] | None = None,
) -> DecompositionResult:
    """Decompose ``query`` into sub-queries (§7.4; S57).

    With an injected ``decomposer`` (the skill layer's LLM-assisted
    decomposition), its result is cleaned — empties dropped, duplicates
    removed preserving first-encounter order — and ``decomposed`` is
    ``True`` iff more than one sub-query remains.

    With ``decomposer=None`` (or a decomposer yielding nothing usable), the
    DETERMINISTIC fallback returns ``(sub_queries=[query], decomposed=False)``.
    The router never fabricates sub-queries and never invents a decomposition.
    """
    if decomposer is None:
        return DecompositionResult(sub_queries=[query], decomposed=False)

    raw = decomposer(query)
    if not isinstance(raw, list):
        raise TypeError(f"decomposer must return list[str], got {type(raw).__name__}")
    cleaned = _clean_sub_queries(raw)
    if not cleaned:
        # Nothing usable from the injected decomposer → deterministic
        # passthrough. The original query is the only ground truth.
        return DecompositionResult(sub_queries=[query], decomposed=False)

    return DecompositionResult(sub_queries=cleaned, decomposed=len(cleaned) > 1)
