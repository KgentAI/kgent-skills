"""Adapter conformance suite (§1.3, §3.1, §3.6, §6.9, §8.5; S65 spirit).

Each adapter (lark / dingtalk / wecom) implements the §3.1 capability
interface by delegating to its CLI via ``run_cli`` (argv arrays only, §8.5)
and translating canonical URIs ↔ native IDs only at the boundary (§3.6).
The fake CLI (``tests/fakes/fake_cli.py``) implements the wire protocol v1
and persists per-backend state to the JSON file it receives via ``--state``,
so every fresh ``run_cli`` subprocess round-trips the same document state.

S65 (adapter conformance): the tests parameterize over ALL THREE adapters
and assert identical behavior — a skill written against the capability
interface drives any backend the same way.

Error/concurrency boundary (documented): wire protocol v1 reports failures as
a nonzero exit + ``{"error": ...}`` on stderr → ``normalize_error`` →
:class:`AdapterError`. A version mismatch on update is one such failure, so
*adapters* surface the normalized ``AdapterError``; the router's
optimistic-concurrency path (which encodes ``VersionConflict`` for re-read +
fresh proposal, §3.9) runs against ``FakeBackend`` directly and is unaffected
by this boundary.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from kgent.adapters.dingtalk import DingTalkAdapter
from kgent.adapters.lark import LarkAdapter
from kgent.adapters.wecom import WeComAdapter
from kgent.errors import AdapterError, ConfigError
from kgent.types import DocumentMetadata

FAKE_CLI = Path(__file__).resolve().parent / "fakes" / "fake_cli.py"
STATE_FILE = "fake_state.json"

# (backend name, adapter class) — the conformance matrix (S65).
ADAPTERS = [
    pytest.param("lark", LarkAdapter, id="lark"),
    pytest.param("dingtalk", DingTalkAdapter, id="dingtalk"),
    pytest.param("wecom", WeComAdapter, id="wecom"),
]


def _adapter(tmp_path: Path, backend: str, adapter_cls: type) -> LarkAdapter:
    """Build an adapter wired to the fake CLI for ``backend`` with persistent state.

    ``cmd`` mirrors how a real integration would point the adapter at a CLI:
    invocation prefix = ``["lark-cli"]`` for production, the fake here.
    """
    cmd = [sys.executable, str(FAKE_CLI), "--state", str(tmp_path / STATE_FILE), backend]
    return adapter_cls(cmd=cmd, timeout=30)


def _state(tmp_path: Path) -> dict:
    return json.loads((tmp_path / STATE_FILE).read_text(encoding="utf-8"))


def _meta(backend: str, title: str) -> DocumentMetadata:
    return DocumentMetadata(doc_uri="", title=title, backend=backend)


# ---------------------------------------------------------------------------
# Conformance: ONE lifecycle, THREE backends, identical assertions (S65)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend,adapter_cls", ADAPTERS)
def test_conformance_full_lifecycle(tmp_path, backend, adapter_cls):
    """create → canonical uri; read roundtrip (content preserved); update;
    archive (archived flag in fake CLI state); unarchive; delete; keyword
    search returns the created doc — same behavior on every backend (S65)."""
    adapter = _adapter(tmp_path, backend, adapter_cls)
    title = f"{backend} retro notes"
    body = "markdown body\nwith a second line\nand `code`"

    uri = adapter.create_document(title, body, _meta(backend, title))
    assert uri == f"kgent://{backend}/doc1"  # canonical — not a native id
    native = uri.rsplit("/", 1)[1]

    doc = adapter.read_document(uri)
    assert doc.doc_uri == uri
    assert doc.title == title
    assert doc.content == body  # fidelity: canonical content as-is (§6.9)
    assert doc.metadata.backend == backend
    assert doc.metadata.version == "v1"  # revision token for OCC (§3.9)

    adapter.update_document(
        uri, "updated: " + body, doc.metadata, None, "idem-1", doc.metadata.version
    )
    doc2 = adapter.read_document(uri)
    assert doc2.content == "updated: " + body
    assert doc2.metadata.version == "v2"

    adapter.archive_document(uri, None, "idem-2")
    assert _state(tmp_path)[backend]["docs"][native]["archived"] is True

    adapter.unarchive_document(uri, None, "idem-3")
    assert _state(tmp_path)[backend]["docs"][native]["archived"] is False
    assert adapter.read_document(uri).content == "updated: " + body  # readable again

    hits = adapter.search_by_keywords("updated", top_k=10)
    assert uri in [h.doc_uri for h in hits]
    for hit in hits:
        assert hit.doc_uri.startswith("kgent://")
        assert hit.rank >= 1  # rank is 1-based (§3.8)
        assert hit.mode_used == "keyword"  # actual mode used

    adapter.delete_document(uri, None, "idem-4", None)
    with pytest.raises(AdapterError):
        adapter.read_document(uri)


@pytest.mark.parametrize("backend,adapter_cls", ADAPTERS)
def test_search_ranks_match_cli_rank_and_respect_top_k(tmp_path, backend, adapter_cls):
    """Search results carry the CLI's 1-based rank and honor top_k."""
    adapter = _adapter(tmp_path, backend, adapter_cls)
    for i in range(3):
        adapter.create_document(f"notes {i}", f"shared keyword body {i}", _meta(backend, "n"))

    hits = adapter.search_by_keywords("shared keyword", top_k=2)
    assert [h.rank for h in hits] == [1, 2]
    assert len(hits) == 2
    assert all(h.mode_used == "keyword" for h in hits)


# ---------------------------------------------------------------------------
# Version conflict → normalized AdapterError (never a silent clobber)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend,adapter_cls", ADAPTERS)
def test_version_conflict_surfaces_adapter_error_and_refuses_clobber(
    tmp_path, backend, adapter_cls
):
    """update with a stale --version → nonzero + stderr error → AdapterError.

    Boundary: adapters surface the normalized error; the optimistic-
    concurrency ``VersionConflict`` encoding lives in the router's FakeBackend
    unit tests (documented at module top).
    """
    adapter = _adapter(tmp_path, backend, adapter_cls)
    uri = adapter.create_document("t", "v1 content", _meta(backend, "t"))
    meta = _meta(backend, "t")
    adapter.update_document(uri, "new content", meta, None, "k1", "v1")
    with pytest.raises(AdapterError, match="version conflict"):
        adapter.update_document(uri, "clobber", meta, None, "k2", "v1")
    assert adapter.read_document(uri).content == "new content"  # clobber refused


# ---------------------------------------------------------------------------
# Error normalization: nonexistent URI → AdapterError with nonzero message
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend,adapter_cls", ADAPTERS)
def test_read_nonexistent_uri_surfaces_normalized_adapter_error(tmp_path, backend, adapter_cls):
    """Reading a valid canonical URI for an unknown native id → CLI exits
    nonzero → normalize_error → AdapterError with a message the caller sees."""
    adapter = _adapter(tmp_path, backend, adapter_cls)
    with pytest.raises(AdapterError, match="not found") as exc_info:
        adapter.read_document(f"kgent://{backend}/missing_doc_99")
    assert "exit code" in str(exc_info.value)  # normalized (stderr-derived)


# ---------------------------------------------------------------------------
# URI boundary (§3.6): native IDs NEVER cross the adapter boundary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend,adapter_cls", ADAPTERS)
def test_uri_boundary_all_crossing_identifiers_are_canonical(tmp_path, backend, adapter_cls):
    """create/read/search hand canonical kgent:// URIs only — the backend's
    native id (e.g. ``doc1``) never leaks to the caller."""
    adapter = _adapter(tmp_path, backend, adapter_cls)
    uri = adapter.create_document("boundary", "body", _meta(backend, "boundary"))
    assert uri.startswith(f"kgent://{backend}/")
    assert not uri.startswith(f"{backend}/")  # never a bare native path

    doc = adapter.read_document(uri)
    assert doc.doc_uri == uri
    assert doc.metadata.doc_uri == uri

    for hit in adapter.search_by_keywords("boundary", top_k=5):
        assert hit.doc_uri.startswith("kgent://")
        assert hit.metadata.doc_uri == hit.doc_uri


@pytest.mark.parametrize("backend,adapter_cls", ADAPTERS)
def test_uri_boundary_bare_native_id_rejected_before_cli(tmp_path, backend, adapter_cls):
    """parse_uri rejects bare native IDs (§3.6) — they never reach run_cli."""
    adapter = _adapter(tmp_path, backend, adapter_cls)
    with pytest.raises(ConfigError, match="bare native IDs"):
        adapter.read_document("doc1")


@pytest.mark.parametrize("backend,adapter_cls", ADAPTERS)
def test_uri_boundary_wrong_backend_uri_rejected(tmp_path, backend, adapter_cls):
    """An adapter never forwards another backend's URI to its own CLI."""
    adapter = _adapter(tmp_path, backend, adapter_cls)
    other = {"lark": "wecom", "dingtalk": "lark", "wecom": "dingtalk"}[backend]
    with pytest.raises(AdapterError, match="does not match"):
        adapter.read_document(f"kgent://{other}/doc1")


# ---------------------------------------------------------------------------
# CLI reachability: the wire protocol's ``version`` leg (exit 0)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend,adapter_cls", ADAPTERS)
def test_cli_reachable_via_version_leg(tmp_path, backend, adapter_cls):
    """The adapter's CLI invocation prefix is wired correctly."""
    adapter = _adapter(tmp_path, backend, adapter_cls)
    assert adapter.check_version() == "1.0.0"
