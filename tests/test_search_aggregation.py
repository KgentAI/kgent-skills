"""Bounded fan-out, per-backend timeouts, partial footer (§7.1; S33).

Assumes no pytest-asyncio dependency: async functions are driven via
stdlib ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable

from kgent.search.fanout import build_footer, exit_code_for_failures, fanout
from kgent.types import Document, DocumentMetadata
from tests.fakes.fake_backend import FakeBackend


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

    successes, failures = asyncio.run(
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

    successes, failures = asyncio.run(
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

    successes, failures = asyncio.run(
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
