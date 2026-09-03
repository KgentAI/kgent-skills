"""Bounded fan-out, per-backend timeouts, partial footer (§7.1; S33).

Assumes no pytest-asyncio dependency: async functions are driven via
stdlib ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kgent.search.aggregate import assess_staleness, classify_read_failure, verify_results
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


# -- Staleness + verification (§8.6; S35, S36) ---------------------------------


def _hit_result(uri: str, backend: str, *, snippet: str | None = None) -> SearchResult:
    """Minimal SearchResult for staleness verification tests."""
    meta = DocumentMetadata(doc_uri=uri, title=f"{backend} {uri}", backend=backend)
    return SearchResult(doc_uri=uri, metadata=meta, rank=1, snippet=snippet, access="ok")


def _read_idmap(tmp_home) -> dict:
    idmap_file = Path(tmp_home) / "idmap.json"
    assert idmap_file.exists(), "idmap.json should have been written"
    return json.loads(idmap_file.read_text(encoding="utf-8"))


def test_s35_deleted_uri_flagged_stale_still_present_idmap(tmp_home):
    """S35: a result whose URI was deleted externally → access == "stale"
    (visibly flagged, demoted), still present in the verified list (never
    dropped), and the URI is marked stale in idmap.json."""
    backend = FakeBackend("lark", "internal", {})
    gone = _hit_result("kgent://lark/docGone", "lark", snippet="was here")

    verified, failures = verify_results([gone], {"lark": backend})

    assert len(verified) == 1  # never dropped
    assert verified[0].access == "stale"
    assert len(failures) == 1
    assert failures[0]["kind"] == "not_found"
    assert failures[0]["uri"] == gone.doc_uri

    idmap = _read_idmap(tmp_home)
    assert idmap[gone.doc_uri]["stale"] is True
    # fingerprint slot exists and is None (nothing recorded for an unknown doc)
    assert idmap[gone.doc_uri]["fingerprint"] is None


def test_s35_ok_result_untouched_no_idmap(tmp_home):
    """A live result keeps access == "ok", records no failure, and writes no
    idmap (no staleness to record)."""
    backend = FakeBackend("lark", "internal", {})
    uri = "kgent://lark/docLive"
    backend.docs[uri] = Document(
        doc_uri=uri,
        title="Live",
        content="body",
        metadata=DocumentMetadata(doc_uri=uri, title="Live", backend="lark"),
    )
    live = _hit_result(uri, "lark", snippet="body")

    verified, failures = verify_results([live], {"lark": backend})

    assert [r.access for r in verified] == ["ok"]
    assert failures == []
    assert not (Path(tmp_home) / "idmap.json").exists()


def test_verify_permission_denied_demoted_not_stale(tmp_home):
    """permission_denied → access == "denied", failure carries the actionable
    message, and the URI is NOT marked stale in idmap."""

    def deny(method, kwargs):
        if method == "read_document":
            raise PermissionError("no read access")

    backend = FakeBackend("dingtalk", "external", {}, fault=deny)
    denied = _hit_result("kgent://dingtalk/doc1", "dingtalk", snippet="s")

    verified, failures = verify_results([denied], {"dingtalk": backend})

    assert [r.access for r in verified] == ["denied"]
    assert len(failures) == 1
    assert failures[0]["kind"] == "permission_denied"
    assert "request access on the platform" in failures[0]["error"]
    assert not (Path(tmp_home) / "idmap.json").exists()  # never marked stale


def test_classify_read_failure_contract(tmp_home):
    """§8.6 classification: not_found → stale (idmap written); permission_denied
    → actionable message (no idmap write); other kinds → unknown-failure."""
    vanished = "kgent://lark/gone"
    assert classify_read_failure("not_found", vanished) == "stale"
    assert _read_idmap(tmp_home)[vanished]["stale"] is True

    secret = "kgent://wecom/token-doc"
    message = classify_read_failure("permission_denied", secret)
    assert message == f"permission denied on {secret} — request access on the platform"
    idmap = _read_idmap(tmp_home)
    assert secret not in idmap  # permission failures never mark stale

    assert classify_read_failure("timeout", "kgent://lark/x") == "unknown-failure"


def test_verify_backend_mapping_or_sequence(tmp_home):
    """verify_results accepts a name→backend mapping or an iterable of backends
    exposing .name."""
    backend = FakeBackend("lark", "internal", {})
    gone = _hit_result("kgent://lark/docGone", "lark")

    verified, _ = verify_results([gone], [backend])
    assert verified[0].access == "stale"


def test_s36_bulk_staleness_invalidates_backend(tmp_home):
    """S36: >20% of one backend's results fail verification → that backend is in
    the invalidate set and a warning names it (computed here; the capability
    cache owner invalidates)."""
    lark = FakeBackend("lark", "internal", {})
    dingtalk = FakeBackend("dingtalk", "external", {})
    # lark: all 3 docs live; dingtalk: 3 results but only doc1 still exists
    # → doc2/doc3 fail verification (2/3 ≈ 67% > 20%)
    lark_results = []
    for i in range(1, 4):
        uri = f"kgent://lark/doc{i}"
        lark.docs[uri] = Document(
            doc_uri=uri,
            title=f"lark {i}",
            content="body",
            metadata=DocumentMetadata(doc_uri=uri, title=f"lark {i}", backend="lark"),
        )
        lark_results.append(_hit_result(uri, "lark"))
    dingtalk.docs["kgent://dingtalk/doc1"] = Document(
        doc_uri="kgent://dingtalk/doc1",
        title="dingtalk 1",
        content="body",
        metadata=DocumentMetadata(
            doc_uri="kgent://dingtalk/doc1", title="dingtalk 1", backend="dingtalk"
        ),
    )
    ding_results = [
        _hit_result("kgent://dingtalk/doc1", "dingtalk"),
        _hit_result("kgent://dingtalk/doc2", "dingtalk"),  # deleted externally
        _hit_result("kgent://dingtalk/doc3", "dingtalk"),  # deleted externally
    ]

    verified, failures = verify_results(
        lark_results + ding_results, {"lark": lark, "dingtalk": dingtalk}
    )

    assert sum(1 for r in verified if r.access == "stale") == 2
    invalidate, warnings = assess_staleness(failures)

    assert invalidate == {"dingtalk"}  # 2/3 ≈ 67% > 20%
    assert any("dingtalk" in w for w in warnings)


def test_assess_staleness_threshold_strictly_above():
    """The rule is STRICTLY > warning_threshold: exactly 20% (1 of 5) does NOT
    invalidate; 2 of 5 (40%) does."""
    one_of_five = [
        {"uri": f"kgent://lark/{i}", "backend": "lark", "kind": "not_found", "total": 5}
        for i in range(1, 2)
    ]

    invalidate, warnings = assess_staleness(one_of_five, warning_threshold=0.2)
    assert invalidate == set()
    assert warnings == []

    two_of_five = one_of_five + [
        {"uri": "kgent://lark/6", "backend": "lark", "kind": "not_found", "total": 5}
    ]
    invalidate, warnings = assess_staleness(two_of_five, warning_threshold=0.2)
    assert invalidate == {"lark"}
    assert any("lark" in w for w in warnings)


def test_assess_staleness_mapping_shape_and_missing_total():
    """failures_per_backend may be a per-backend mapping; when a record carries
    no "total" the backend conservatively counts all its results as failed."""
    failures_per_backend = {
        "wecom": [{"uri": "kgent://wecom/a", "kind": "not_found"}],
        "lark": [{"uri": "kgent://lark/a", "kind": "not_found", "total": 10}],
    }

    invalidate, warnings = assess_staleness(failures_per_backend)

    assert invalidate == {"wecom"}  # conservative: 1/1
    assert "lark" not in invalidate  # 1/10 = 10% ≤ 20%
    assert any("wecom" in w for w in warnings)
