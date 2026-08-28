"""Bounded fan-out, per-backend timeouts, partial footer (§7.1; S33).

Assumes no pytest-asyncio dependency: async functions are driven via
stdlib ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from kgent.search.fanout import build_footer, exit_code_for_failures, fanout, truncate
from kgent.search.rank import rank_and_truncate, rrf
from kgent.types import Document, DocumentMetadata, SearchResult
from tests.conftest import _full_caps, _kw_caps
from tests.fakes.fake_backend import FakeBackend


def _populate(backend: FakeBackend, docs: int) -> None:
    for i in range(1, docs + 1):
        uri = f"kgent://{backend.name}/doc{i}"
        meta = DocumentMetadata(doc_uri=uri, title=f"{backend.name} doc {i}", backend=backend.name)
        backend.docs[uri] = Document(
            doc_uri=uri, title=meta.title, content=f"body {i}", metadata=meta
        )


def _backend(
    name: str, *, fault: Callable[[str, dict], None] | None = None, docs: int = 2
) -> FakeBackend:
    backend = FakeBackend(name, "internal", {}, fault=fault)
    for i in range(1, docs + 1):
        uri = f"kgent://{name}/doc{i}"
        title = f"{name} doc {i}"
        meta = DocumentMetadata(doc_uri=uri, title=title, backend=name)
        backend.docs[uri] = Document(doc_uri=uri, title=title, content=f"body {i}", metadata=meta)
    return backend


def test_s33_timeout_is_visible_partial():
    """S33: a hanging backend degrades; remaining results + footer + exit 2."""
    search_seconds = 0.1

    def hang(method, kwargs):
        time.sleep(search_seconds * 10)

    lark = _backend("lark")
    dingtalk = _backend("dingtalk", fault=hang)
    wecom = _backend("wecom")

    successes, failures, _ = asyncio.run(
        fanout(
            targets=[lark, dingtalk, wecom],
            query="retro",
            mode="hybrid",
            top_k=5,
            timeout=search_seconds,
            concurrency=4,
        )
    )

    names = {r.metadata.backend for r in successes}
    assert {"lark", "wecom"} <= names
    assert "dingtalk" not in names
    assert [f["backend"] for f in failures] == ["dingtalk"]
    assert failures[0]["timed_out"] is True
    assert "error" in failures[0]
    assert build_footer(failures) == "1 backend timed out"
    assert exit_code_for_failures(failures) == 2


def test_fanout_records_backend_error_as_non_timeout():
    def explode(method, kwargs):
        raise RuntimeError("search exploded")

    lark = _backend("lark")
    dingtalk = _backend("dingtalk", fault=explode)
    wecom = _backend("wecom")

    successes, failures, _ = asyncio.run(
        fanout(
            targets=[lark, dingtalk, wecom],
            query="retro",
            mode="hybrid",
            top_k=5,
            timeout=1.0,
            concurrency=4,
        )
    )

    assert {r.metadata.backend for r in successes} == {"lark", "wecom"}
    assert [f["backend"] for f in failures] == ["dingtalk"]
    assert failures[0]["timed_out"] is False
    assert "exploded" in failures[0]["error"]
    assert build_footer(failures) == "1 backend failed"


def test_fanout_bounded_concurrency():
    """Semaphore(1) serializes backends — never more than one in flight."""
    lock = threading.Lock()
    state = {"active": 0, "max_active": 0}

    def track(method, kwargs):
        with lock:
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
        time.sleep(0.05)
        with lock:
            state["active"] -= 1

    backends = [_backend(n, fault=track) for n in ("lark", "dingtalk", "wecom")]

    successes, failures, _ = asyncio.run(
        fanout(
            targets=backends,
            query="q",
            mode="keywords",
            top_k=5,
            timeout=1.0,
            concurrency=1,
        )
    )

    assert failures == []
    assert len(successes) == 6  # 2 docs from each of 3 backends
    assert state["max_active"] == 1


def test_footer_plural_and_exit_codes():
    assert build_footer([]) == ""
    assert (
        build_footer(
            [
                {"backend": "a", "error": "x", "timed_out": True},
                {"backend": "b", "error": "y", "timed_out": True},
            ]
        )
        == "2 backends timed out"
    )
    assert (
        build_footer(
            [
                {"backend": "a", "error": "boom", "timed_out": False},
                {"backend": "b", "error": "boom2", "timed_out": False},
            ]
        )
        == "2 backends failed"
    )
    assert (
        build_footer(
            [
                {"backend": "a", "error": "x", "timed_out": True},
                {"backend": "b", "error": "boom", "timed_out": False},
            ]
        )
        == "1 backend timed out, 1 backend failed"
    )
    assert exit_code_for_failures([{"backend": "a", "error": "boom", "timed_out": False}]) == 2
    assert exit_code_for_failures([]) == 0


def _hit(
    uri: str,
    backend: str,
    *,
    rank: int = 1,
    updated_at: datetime | None = None,
    score_native: float | None = None,
) -> SearchResult:
    """Build a minimal frozen SearchResult with the fields RRF reads."""
    meta = DocumentMetadata(
        doc_uri=uri, title=f"{backend} {uri}", backend=backend, updated_at=updated_at
    )
    return SearchResult(doc_uri=uri, metadata=meta, rank=rank, score_native=score_native)


def test_s34_rrf_ranks_by_position_not_score():
    """S34: rank 1 with a weak native score outranks rank 5 with a strong one."""
    doc_x = _hit("kgent://alpha/docX", "alpha", rank=5, score_native=0.99)
    doc_y = _hit("kgent://beta/docY", "beta", rank=1, score_native=0.40)
    fused = rrf([[doc_x], [doc_y]])
    assert [r.doc_uri for r in fused] == [doc_y.doc_uri, doc_x.doc_uri]


def test_rrf_tiebreak_recency_newer_updated_at_first():
    older = _hit("kgent://alpha/old", "alpha", rank=1, updated_at=datetime(2024, 1, 1, tzinfo=UTC))
    newer = _hit("kgent://beta/new", "beta", rank=1, updated_at=datetime(2025, 1, 1, tzinfo=UTC))
    assert [r.doc_uri for r in rrf([[older], [newer]])] == [newer.doc_uri, older.doc_uri]
    # a missing updated_at ranks as oldest inside the same score band
    missing = _hit("kgent://gamma/unknown", "gamma", rank=1)
    assert [r.doc_uri for r in rrf([[older], [newer], [missing]])] == [
        newer.doc_uri,
        older.doc_uri,
        missing.doc_uri,
    ]


def test_rrf_tiebreak_backend_priority_lower_number_first():
    ts = datetime(2025, 1, 1, tzinfo=UTC)
    alpha = _hit("kgent://alpha/a", "alpha", rank=1, updated_at=ts)
    beta = _hit("kgent://beta/b", "beta", rank=1, updated_at=ts)
    assert [r.doc_uri for r in rrf([[alpha], [beta]], priority={"alpha": 1, "beta": 2})] == [
        alpha.doc_uri,
        beta.doc_uri,
    ]
    # callable priority sources are accepted
    assert [
        r.doc_uri for r in rrf([[alpha], [beta]], priority=lambda name: 2 if name == "alpha" else 1)
    ] == [beta.doc_uri, alpha.doc_uri]
    # missing/None priority is treated as max -> ranks last in the band
    gamma = _hit("kgent://gamma/c", "gamma", rank=1, updated_at=ts)
    assert [
        r.doc_uri for r in rrf([[alpha], [beta], [gamma]], priority={"alpha": 1, "beta": 2})
    ] == [
        alpha.doc_uri,
        beta.doc_uri,
        gamma.doc_uri,
    ]


def test_rank_and_truncate_exact_top_k_total():
    """S31: top_k is a total — rank_and_truncate returns EXACTLY top_k after fusion."""
    ts = datetime(2025, 1, 1, tzinfo=UTC)
    a = _hit("kgent://alpha/a", "alpha", rank=1, updated_at=ts)
    b = _hit("kgent://alpha/b", "alpha", rank=2, updated_at=ts)
    c = _hit("kgent://beta/c", "beta", rank=1, updated_at=datetime(2025, 2, 1, tzinfo=UTC))
    clamps = {
        "alpha": {"requested": 5, "fetch": 2, "clamped": False},
        "beta": {"requested": 5, "fetch": 5, "clamped": False},
    }
    top = rank_and_truncate([[a, b], [c]], top_k=1, clamps=clamps)
    assert [r.doc_uri for r in top] == [c.doc_uri]


def test_rrf_duplicate_backend_lists_not_crashing():
    """Guard: two lists labeled the same backend are concatenated, never crash."""
    a = _hit("kgent://alpha/a", "alpha", rank=1, updated_at=datetime(2025, 1, 1, tzinfo=UTC))
    b = _hit("kgent://alpha/b", "alpha", rank=1, updated_at=datetime(2025, 1, 2, tzinfo=UTC))
    fused = rrf([[a], [b]])
    # both rank-1 bands tie at 1/61; recency breaks it; nothing crashes
    assert [r.doc_uri for r in fused] == [b.doc_uri, a.doc_uri]


def test_s31_truncate_enforces_top_k_total():
    """S31: 3 backends x <=10 results each, top_k=10 -> EXACTLY 10 merged.

    6.2 stage: `truncate` slices an already-ranked list; the RRF step (6.3)
    applies it after fusion — here we assert the contract directly.
    """
    ranked: list[SearchResult] = []
    for name in ("lark", "dingtalk", "wecom"):
        for i in range(1, 11):  # 10 docs per backend
            uri = f"kgent://{name}/doc{i}"
            meta = DocumentMetadata(doc_uri=uri, title=f"{name} doc {i}", backend=name)
            ranked.append(SearchResult(doc_uri=uri, metadata=meta, rank=len(ranked) + 1))

    assert len(ranked) == 30
    top = truncate(ranked, 10)
    assert len(top) == 10
    assert [r.doc_uri for r in top] == [r.doc_uri for r in ranked[:10]]  # order preserved
    assert truncate(ranked, 100) == ranked  # within budget -> unchanged
    assert truncate(ranked, 0) == []
    assert truncate([], 5) == []
    with pytest.raises(ValueError):
        truncate(ranked, -1)


def test_s32_per_backend_clamp_with_limits():
    """S32: lark max_results=200, dingtalk max_results=50, top_k=100.

    dingtalk must be fetched with 50 (clamped) and the clamp recorded in the
    clamps metadata; lark is unclamped at 100.
    """
    lark_caps = _full_caps()
    lark_caps["document_search"]["limits"] = {"max_results": 200, "max_content_bytes": 2_000_000}
    lark = FakeBackend("lark", "internal", lark_caps)
    _populate(lark, 200)

    no_limit_caps = _full_caps()
    no_limit_caps["document_search"].pop("limits")
    wecom = FakeBackend("wecom", "external", no_limit_caps)
    _populate(wecom, 10)

    seen: dict[str, int] = {}

    def track(name: str):
        def _fault(method: str, kwargs: dict) -> None:
            if method == "search":
                seen[name] = int(kwargs["top_k"])

        return _fault

    dingtalk = FakeBackend("dingtalk", "external", _kw_caps(), fault=track("dingtalk"))
    _populate(dingtalk, 60)
    lark.fault = track("lark")
    wecom.fault = track("wecom")

    successes, failures, clamps = asyncio.run(
        fanout(
            targets=[lark, dingtalk, wecom],
            query="retro",
            mode="hybrid",
            top_k=100,
            timeout=1.0,
            concurrency=4,
        )
    )

    assert failures == []
    assert clamps["lark"] == {"requested": 100, "fetch": 100, "clamped": False}
    assert clamps["dingtalk"] == {"requested": 100, "fetch": 50, "clamped": True}
    assert clamps["wecom"] == {
        "requested": 100,
        "fetch": 100,
        "clamped": False,
    }  # no limit -> no clamp
    # actual per-backend fetch as observed by the backends themselves
    assert seen["lark"] == 100
    assert seen["dingtalk"] == 50
    assert seen["wecom"] == 100
    # coverage fidelity: dingtalk contributes at most its clamped fetch
    assert sum(1 for r in successes if r.metadata.backend == "dingtalk") == 50
    assert sum(1 for r in successes if r.metadata.backend == "lark") == 100
