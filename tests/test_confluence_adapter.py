"""ConfluenceAdapter tests (spec 2026-09-22, A3) — read lanes + wiki capability.

Fake ``run_cli`` serves the REQUIRED acli wire contract by subcommand and
records argv (dingtalk test pattern). Payload shapes are contract anchors:
the A1 probe reconciles them against live acli truth before any e2e claim
(ADR 0015) — when live keys drift, only the module-level ``_extract_*`` /
argv builders in ``kgent/adapters/confluence.py`` change.

Write lanes are NOT wired (dingtalk/wecom precedent, ADR 0004): everything
write-shaped must raise ``NotImplementedError`` — confluence writes live in
the confluence-integration skill.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from kgent.adapters import confluence as cf_mod
from kgent.adapters.cli_adapter import SubprocessResult
from kgent.adapters.confluence import ConfluenceAdapter, build_cql
from kgent.adapters.fidelity import is_lossy
from kgent.errors import AdapterError
from kgent.types import DocumentMetadata

PAGE_ID = "4718153"
SEARCH_PAYLOAD = json.dumps(
    {
        "results": [
            {
                "id": PAGE_ID,
                "title": "Auth design",
                "snippet": "token exchange flow",
                "spaceId": "1101",
                "spaceKey": "ENG",
            }
        ]
    }
)
PAGE_PAYLOAD = json.dumps(
    {
        "id": PAGE_ID,
        "title": "Auth design",
        "version": 3,
        "spaceId": "1101",
        "spaceKey": "ENG",
        "updatedAt": "2026-09-21T10:00:00Z",
        "bodyStorage": "<p>hello &amp; world</p>",
    }
)
SPACES_PAYLOAD = json.dumps({"results": [{"id": "1101", "key": "ENG", "name": "Engineering"}]})


class _FakeAcli:
    """Stand-in for ``run_cli``: serves the confluence wire contract, records argv."""

    def __init__(self, page_payload: str = PAGE_PAYLOAD) -> None:
        self.calls: list[list[str]] = []
        self.page_payload = page_payload

    def __call__(self, argv: list[str], timeout: float, *, env=None) -> SubprocessResult:
        self.calls.append(list(argv))
        rest = argv[1:-1]  # strip "acli" prefix and trailing "--json"
        if rest[:2] == ["search", "--cql"]:
            return self._ok(SEARCH_PAYLOAD)
        if rest[:2] == ["page", "get"]:
            return self._ok(self.page_payload)
        if rest[:1] == ["space"] and "--name" in rest:
            return self._ok(json.dumps({"id": "2202", "key": "NEW"}))
        if rest[:2] == ["space", "list"]:
            return self._ok(SPACES_PAYLOAD)
        if rest[:2] == ["page", "create"]:
            return self._ok(json.dumps({"id": "5252", "version": 1}))
        return SubprocessResult(2, "", json.dumps({"error": f"unexpected argv: {argv}"}))

    def _ok(self, payload: str) -> SubprocessResult:
        return SubprocessResult(0, payload, "")


@pytest.fixture()
def fake(monkeypatch: pytest.MonkeyPatch) -> _FakeAcli:
    inst = _FakeAcli()
    monkeypatch.setattr(cf_mod, "run_cli", inst)
    return inst


def _adapter(**kw: Any) -> ConfluenceAdapter:
    return ConfluenceAdapter(cmd=["acli"], **kw)


# ---- capability declaration -------------------------------------------------


def test_capabilities_declare_read_only_storage_and_wiki_block():
    caps = _adapter().capabilities
    assert caps["document_storage"]["supported"] is True
    features = caps["document_storage"]["features"]
    assert "read" in features
    for not_wired in ("create", "update", "delete", "archive", "unarchive"):
        assert not_wired not in features
    assert caps["document_search"]["features"]["search_by_keywords"] is True
    assert caps["document_search"]["features"].get("search_by_semantics") is not True
    assert caps["wiki"]["supported"] is True
    assert set(caps["wiki"]["features"]) == {"spaces_list", "spaces_create", "node_create"}
    assert caps["approval_flow"]["supported"] is False


# ---- search lane ------------------------------------------------------------


def test_search_maps_hits_to_canonical_results(fake: _FakeAcli):
    results = _adapter().search_by_keywords("token exchange", top_k=5)
    assert len(results) == 1
    hit = results[0]
    assert hit.doc_uri == f"kgent://confluence/{PAGE_ID}"
    assert hit.metadata.backend == "confluence"
    assert hit.metadata.space_id == "1101"
    assert hit.node_type == "doc"
    assert hit.snippet == "token exchange flow"


def test_search_argv_carries_cql_and_limit(fake: _FakeAcli):
    _adapter().search_by_keywords("token", top_k=7)
    rest = fake.calls[0][1:-1]
    assert rest[0] == "search" and "--cql" in rest and "--limit" in rest
    assert rest[rest.index("--limit") + 1] == "7"


def test_search_allowlist_scopes_cql(fake: _FakeAcli):
    _adapter(spaces=["ENG", "HR"]).search_by_keywords("token", top_k=5)
    cql = fake.calls[0][fake.calls[0].index("--cql") + 1]
    assert 'space in ("ENG", "HR")' in cql


# ---- read lane ----------------------------------------------------------------


def test_read_converts_storage_xhtml_to_markdown(fake: _FakeAcli):
    doc = _adapter().read_document(f"kgent://confluence/{PAGE_ID}")
    assert doc.content == "hello & world"
    assert doc.title == "Auth design"
    assert doc.metadata.version == "3"
    assert doc.metadata.space_id == "1101"


def test_native_id_rejects_non_numeric_page_ids():
    with pytest.raises(AdapterError, match="numeric"):
        _adapter()._native_id("kgent://confluence/not-a-page")


def test_native_id_rejects_foreign_backend_uris():
    with pytest.raises(AdapterError, match="does not match"):
        _adapter()._native_id("kgent://lark/doc1")


# ---- write lanes stay unwired --------------------------------------------------


def test_write_lanes_raise_not_implemented(fake: _FakeAcli):
    meta = DocumentMetadata(
        doc_uri=f"kgent://confluence/{PAGE_ID}", title="t", backend="confluence"
    )
    adapter = _adapter()
    with pytest.raises(NotImplementedError):
        adapter.create_document("t", "c", meta)
    with pytest.raises(NotImplementedError):
        adapter.update_document(f"kgent://confluence/{PAGE_ID}", "c", meta, None, "idem", "1")
    with pytest.raises(NotImplementedError):
        adapter.delete_document(f"kgent://confluence/{PAGE_ID}", None, "idem", "1")
    with pytest.raises(NotImplementedError):
        adapter.archive_document(f"kgent://confluence/{PAGE_ID}", None, "idem")
    with pytest.raises(NotImplementedError):
        adapter.unarchive_document(f"kgent://confluence/{PAGE_ID}", None, "idem")
    assert fake.calls == []  # nothing reached the transport


def test_semantic_and_hybrid_search_unwired():
    with pytest.raises(NotImplementedError):
        _adapter().search_by_semantics("q")
    with pytest.raises(NotImplementedError):
        _adapter().search_hybrid("q")
    with pytest.raises(NotImplementedError):
        _adapter().list_documents(None, 10)


# ---- contract fallbacks + malformed-payload error paths ---------------------


def test_extract_version_nested_v2_shape_and_flat_fallback():
    assert cf_mod._extract_version({"version": {"number": 7}}) == "7"  # v2 nested (live shape)
    assert cf_mod._extract_version({"version": 7}) == "7"  # flat fallback
    assert cf_mod._extract_version({}) == ""  # absent


def test_extract_body_storage_nested_chain_and_absence():
    nested = {"body": {"storage": {"value": "<p>x</p>"}}}
    assert cf_mod._extract_body_storage(nested) == "<p>x</p>"
    assert cf_mod._extract_body_storage({"bodyStorage": "<p>y</p>"}) == "<p>y</p>"
    assert cf_mod._extract_body_storage({}) == ""


def test_run_malformed_json_stdout_raises(fake: _FakeAcli, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        cf_mod, "run_cli", lambda argv, timeout, **kw: SubprocessResult(0, "not json", "")
    )
    with pytest.raises(AdapterError, match="malformed JSON"):
        _adapter().read_document(f"kgent://confluence/{PAGE_ID}")


def test_run_non_object_json_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        cf_mod, "run_cli", lambda argv, timeout, **kw: SubprocessResult(0, "[1,2]", "")
    )
    with pytest.raises(AdapterError, match="non-object JSON"):
        _adapter().read_document(f"kgent://confluence/{PAGE_ID}")


def test_run_error_key_on_exit_zero_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        cf_mod, "run_cli", lambda argv, timeout, **kw: SubprocessResult(0, '{"error": "boom"}', "")
    )
    with pytest.raises(AdapterError, match="boom"):
        _adapter().read_document(f"kgent://confluence/{PAGE_ID}")


def test_run_nonzero_exit_normalizes_to_adapter_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        cf_mod, "run_cli", lambda argv, timeout, **kw: SubprocessResult(3, "", '{"error": "nope"}')
    )
    with pytest.raises(AdapterError):
        _adapter().read_document(f"kgent://confluence/{PAGE_ID}")


def test_search_skips_non_dict_and_idless_hits(monkeypatch: pytest.MonkeyPatch):
    payload = json.dumps(
        {"results": ["junk", {"title": "no id"}, {"id": PAGE_ID, "title": "ok", "spaceId": "1"}]}
    )
    monkeypatch.setattr(
        cf_mod, "run_cli", lambda argv, timeout, **kw: SubprocessResult(0, payload, "")
    )
    results = _adapter().search_by_keywords("q")
    assert [r.doc_uri for r in results] == [f"kgent://confluence/{PAGE_ID}"]


def test_list_wiki_spaces_skips_non_dict_and_idless(monkeypatch: pytest.MonkeyPatch):
    payload = json.dumps(
        {"results": ["junk", {"name": "no id"}, {"id": 9, "name": "ok", "key": "K"}]}
    )
    monkeypatch.setattr(
        cf_mod, "run_cli", lambda argv, timeout, **kw: SubprocessResult(0, payload, "")
    )
    assert _adapter().list_wiki_spaces() == [{"space_id": "9", "name": "ok", "key": "K"}]


def test_create_wiki_space_without_id_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        cf_mod, "run_cli", lambda argv, timeout, **kw: SubprocessResult(0, "{}", "")
    )
    with pytest.raises(AdapterError, match="no id"):
        _adapter().create_wiki_space("X")


def test_create_wiki_node_without_id_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        cf_mod, "run_cli", lambda argv, timeout, **kw: SubprocessResult(0, "{}", "")
    )
    meta = DocumentMetadata(doc_uri="", title="t", backend="confluence")
    with pytest.raises(AdapterError, match="no id"):
        _adapter().create_wiki_node("t", "# body", meta, space_id="ENG", parent_node_token=None)


def test_create_wiki_node_with_parent_passes_parent_flag(fake: _FakeAcli):
    meta = DocumentMetadata(doc_uri="", title="t", backend="confluence")
    _adapter().create_wiki_node("t", "# body", meta, space_id="ENG", parent_node_token="4718153")
    rest = fake.calls[0][1:-1]
    assert rest[rest.index("--parent") + 1] == "4718153"


# ---- wiki capability ------------------------------------------------------------


def test_list_wiki_spaces_maps_keys(fake: _FakeAcli):
    spaces = _adapter().list_wiki_spaces()
    assert spaces == [{"space_id": "1101", "name": "Engineering", "key": "ENG"}]


def test_create_wiki_space_returns_space_id(fake: _FakeAcli):
    assert _adapter().create_wiki_space("New Space") == "2202"


def test_create_wiki_node_returns_canonical_uri(fake: _FakeAcli):
    meta = DocumentMetadata(doc_uri="", title="t", backend="confluence")
    uri = _adapter().create_wiki_node("t", "# body", meta, space_id="ENG", parent_node_token=None)
    assert uri == "kgent://confluence/5252"


# ---- fidelity declarations (ADR 0016) -------------------------------------------


def test_fidelity_declares_both_directions_lossy():
    assert is_lossy("confluence", "native_to_canonical")
    assert is_lossy("confluence", "canonical_to_native")


# ---- CQL escaping (negative constraint, hypothesis) -----------------------------


@st.composite
def _hostile_queries(draw):
    specials = st.sampled_from(
        [
            '"',
            "\\",
            "+",
            "-",
            "&",
            "|",
            "!",
            "(",
            ")",
            "{",
            "}",
            "[",
            "]",
            "^",
            "~",
            "*",
            "?",
            ":",
            "/",
            " ",
            "'",
        ]
    )
    body = st.text(
        st.characters(blacklist_characters='"\\', blacklist_categories=("Cs",)),
        min_size=0,
        max_size=30,
    )
    return "".join(draw(st.lists(specials, min_size=0, max_size=6)) for _ in range(0)) + draw(body)


class TestCqlComposition:
    def test_simple_query_shape(self):
        cql = build_cql("token exchange")
        assert cql == 'type=page AND text ~ "token exchange"'

    def test_allowlist_adds_space_clause(self):
        cql = build_cql("q", spaces=["ENG", "HR"])
        assert cql == 'type=page AND space in ("ENG", "HR") AND text ~ "q"'

    def test_quotes_escaped(self):
        cql = build_cql('say "hello"')
        assert '\\"' in cql
        assert cql.count('"') % 2 == 0

    def test_space_keys_escaped_too(self):
        cql = build_cql("q", spaces=['EV"IL'])
        assert '\\"' in cql

    @given(query=_hostile_queries())
    def test_hostile_query_never_breaks_cql_structure(self, query: str):
        cql = build_cql(query)
        # the text term stays a single balanced double-quoted literal
        tail = cql.split('text ~ "', 1)[1]
        assert tail.endswith('"')
        inner = tail[:-1]
        assert '"' not in inner.replace('\\"', "")

    @given(
        key=st.text(
            st.characters(blacklist_characters='"\\', blacklist_categories=("Cs",)),
            min_size=1,
            max_size=10,
        )
    )
    def test_hostile_space_key_stays_inside_quotes(self, key: str):
        cql = build_cql("q", spaces=[key])
        segment = cql.split('space in ("', 1)[1]
        first_key = segment.split('"', 1)[0]
        assert "\\" + '"' not in first_key or first_key.endswith("\\")
        assert key.replace('"', "") in first_key.replace('\\"', "")
