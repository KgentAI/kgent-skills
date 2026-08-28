"""Question-answering skill (§7.4, S68, N11).

Every factual claim in an answer carries a source citation (``doc_uri``) from
a search result. Claims without a source are marked as ``supported=False`` —
never fabricated (N11).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from kgent.router.core import Router

__all__ = ["Answer", "Claim", "answer"]


@dataclass(frozen=True, slots=True)
class Claim:
    """A single factual claim in a QA answer."""

    text: str
    source_uri: str | None = None
    supported: bool = True


@dataclass(frozen=True, slots=True)
class Answer:
    """Aggregated answer with source citations."""

    question: str
    claims: list[Claim] = field(default_factory=list)
    summary: str = ""


def answer(question: str, router: Router, *, top_k: int = 5) -> Answer:
    """Answer ``question`` using search results as citations (S68).

    Every factual claim in the returned :class:`Answer` carries a ``source_uri``
    from a search result. Claims without a source are marked ``supported=False``
    (N11 — never fabricated).
    """
    # Fan-out search across backends
    try:
        successes, _failures, _clamps = router.search_sync(question, top_k=top_k)
    except Exception:  # noqa: BLE001 — search failure degrades gracefully
        successes = []

    claims: list[Claim] = []
    for result in successes:
        # Each search result becomes a grounded claim
        claims.append(Claim(
            text=result.snippet or result.metadata.title or "",
            source_uri=result.doc_uri,
            supported=True,
        ))

    # If no results, produce a single unsupported claim
    if not claims:
        claims.append(Claim(
            text=f"No information found for: {question}",
            source_uri=None,
            supported=False,
        ))

    summary = " ".join(c.text for c in claims if c.supported) if claims else ""
    return Answer(question=question, claims=claims, summary=summary)
