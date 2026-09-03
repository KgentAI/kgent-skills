"""Lark adapter node-type fidelity (spec 2026-09-02-search-node-type-wiki-fidelity).

``kgent search`` / ``kgent read`` used to report ``node_type: "doc"`` for every
lark hit — even wiki (knowledge-space) nodes — so skills rendered
``/docx/<token>`` citation links that 404 (N23). The fix reads the node type
from server-side facts only (never token shape):

- ``docs +search`` hits carry ``result_meta.url`` (path segment ``/wiki/`` vs
  ``/docx/`` is the exact rendering fact) and ``entity_type`` (``WIKI``/``DOC``)
  — captured verbatim from the real service on 2026-09-02;
- ``docs +fetch`` carries NO type fact, so read probes ``wiki +node-get``:
  success → ``wiki_node`` + ``space_id``/``parent_node_token``, ``131005
  not_found`` → flat doc, any other failure → degrades to ``"doc"`` (the
  pre-fix behavior — never an exception).

Wiki search hits are enriched with one bounded ``wiki +node-get`` call each
(cap + wall-clock budget): ``fanout`` cancels the whole backend past
``search_seconds`` (S33), so enrichment must never push a search over budget.

Fixture-driven throughout — no real ``lark-cli`` subprocess is spawned.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from kgent.adapters import cli_adapter as cli_adapter_mod
from kgent.adapters import lark as lark_mod
from kgent.adapters.cli_adapter import SubprocessResult
from kgent.adapters.lark import LarkAdapter
from kgent.errors import AdapterTimeoutError

DOMAIN = "hjpiui0m07o0.jp.larksuite.com"
WIKI_TOKEN = "Lsu5wOin2iEDGYkJcExjjKpgpZd"
DOC_TOKEN = "Xg8sdBt8EocrGRxbGupjfIb4pph"
SPACE_ID = "7534610915493150753"


def _hit(token: str, *, entity: str, path: str | None = None, doc_type: str = "DOCX") -> dict[str, Any]:
    """One ``docs +search`` result item, shaped like the real payload."""
    meta: dict[str, Any] = {"token": token, "doc_types": doc_type}
    if path is not None:
        meta["url"] = f"https://{DOMAIN}/{path}"
    return {"entity_type": entity, "result_meta": meta, "title_highlighted": f"t<{token}>"}


def _search_payload(items: list[dict[str, Any]]) -> str:
    return json.dumps({"ok": True, "data": {"results": items}})


def _node_get_ok(
    token: str, space_id: str, parent: str = ""
) -> SubprocessResult:
    """Real ``wiki +node-get`` success shape (exit 0, JSON on stdout)."""
    return SubprocessResult(
        0,
        json.dumps(
            {
                "ok": True,
                "data": {
                    "node_token": token,
                    "obj_token": "DxBEdeYg5oKZvmxRbxWjkuTNpdf",
                    "obj_type": "docx",
                    "space_id": space_id,
                    "parent_node_token": parent,
                    "title": "部门新人入职",
                },
            }
        ),
        "",
    )


#: Real ``wiki +node-get`` failure shape for a non-wiki token: exit 1, the
#: error envelope on **stderr** (captured from the live CLI on 2026-09-02).
NODE_GET_NOT_FOUND = SubprocessResult(
    1,
    "",
    json.dumps(
        {
            "ok": False,
            "error": {"type": "api", "subtype": "not_found", "code": 131005, "message": "not found"},
        }
    ),
)


class _FakeLarkCli:
    """Stand-in for ``run_cli``: serves fixtures by subcommand, records calls."""

    def __init__(
        self,
        search_stdout: str,
        node_get: dict[str, SubprocessResult] | None = None,
        node_get_default: SubprocessResult = NODE_GET_NOT_FOUND,
        fetch_stdout: str = "",
    ) -> None:
        self.search_stdout = search_stdout
        self.node_get = node_get or {}
        self.node_get_default = node_get_default
        self.fetch_stdout = fetch_stdout
        self.search_calls = 0
        self.node_get_calls: list[str] = []

    def __call__(self, argv: list[str], timeout: float, **_kw: Any) -> SubprocessResult:
        if "+search" in argv:
            self.search_calls += 1
            return SubprocessResult(0, self.search_stdout, "")
        if "+fetch" in argv:
            return SubprocessResult(0, self.fetch_stdout, "")
        if "+node-get" in argv:
            token = argv[argv.index("--node-token") + 1]
            self.node_get_calls.append(token)
            return self.node_get.get(token, self.node_get_default)
        raise AssertionError(f"unexpected argv: {argv}")


def _patch(monkeypatch: pytest.MonkeyPatch, fake: _FakeLarkCli) -> None:
    """Intercept the subprocess at both import sites (lark + generic adapter)."""
    monkeypatch.setattr(cli_adapter_mod, "run_cli", fake, raising=False)
    monkeypatch.setattr(lark_mod, "run_cli", fake, raising=False)


# ---------------------------------------------------------------------------
# search: node_type from the search payload itself (zero extra calls)
# ---------------------------------------------------------------------------


WIKI_SEARCH = _search_payload(
    [
        _hit(WIKI_TOKEN, entity="WIKI", path=f"wiki/{WIKI_TOKEN}"),
        _hit(DOC_TOKEN, entity="DOC", path=f"docx/{DOC_TOKEN}"),
    ]
)


def test_search_wiki_hit_reports_wiki_node_with_space_position(monkeypatch):
    """A /wiki/ url hit → node_type wiki_node + enriched space_id; the empty
    parent_node_token of a root node surfaces as None (§7.2)."""
    fake = _FakeLarkCli(
        WIKI_SEARCH,
        node_get={WIKI_TOKEN: _node_get_ok(WIKI_TOKEN, SPACE_ID)},
    )
    _patch(monkeypatch, fake)
    hits = LarkAdapter(cmd=["fake-lark-cli"]).search_by_keywords("入职")

    wiki = next(h for h in hits if h.doc_uri.endswith(WIKI_TOKEN))
    assert wiki.node_type == "wiki_node"
    assert wiki.space_id == SPACE_ID
    assert wiki.parent_node_token is None  # root node: "" → None
    # metadata mirrors the result-level fields (skills read either)
    assert wiki.metadata.node_type == "wiki_node"
    assert wiki.metadata.space_id == SPACE_ID


def test_search_flat_doc_hit_reports_doc_and_skips_probe(monkeypatch):
    """A /docx/ url hit stays "doc", carries no space, and never costs a
    wiki +node-get call."""
    fake = _FakeLarkCli(WIKI_SEARCH)
    _patch(monkeypatch, fake)
    hits = LarkAdapter(cmd=["fake-lark-cli"]).search_by_keywords("入职")

    doc = next(h for h in hits if h.doc_uri.endswith(DOC_TOKEN))
    assert doc.node_type == "doc"
    assert doc.space_id is None
    assert doc.parent_node_token is None
    assert DOC_TOKEN not in fake.node_get_calls  # doc hits need no probe


def test_search_derives_type_from_entity_type_when_url_missing(monkeypatch):
    """Without result_meta.url, entity_type is the fallback fact."""
    payload = _search_payload(
        [_hit("w1", entity="WIKI"), _hit("d1", entity="DOC")]
    )
    fake = _FakeLarkCli(payload)
    _patch(monkeypatch, fake)
    hits = LarkAdapter(cmd=["fake-lark-cli"]).search_by_keywords("q")

    by_uri = {h.doc_uri.rsplit("/", 1)[-1]: h for h in hits}
    assert by_uri["w1"].node_type == "wiki_node"
    assert by_uri["d1"].node_type == "doc"


def test_search_url_fragment_and_query_are_ignored(monkeypatch):
    """Real /wiki/ urls carry block anchors and sheet ranges — only the path
    segment decides."""
    payload = _search_payload(
        [
            _hit("frag1", entity="WIKI", path="wiki/frag1#doxjpblLseTBxle2vyqB4t3xCnh"),
            _hit("sheet1", entity="WIKI", path="wiki/sheet1?sheet=8f137f&range=MzQ6MzQ="),
        ]
    )
    fake = _FakeLarkCli(payload)
    _patch(monkeypatch, fake)
    hits = LarkAdapter(cmd=["fake-lark-cli"]).search_by_keywords("q")

    assert all(h.node_type == "wiki_node" for h in hits)


def test_search_non_doc_entities_stay_doc(monkeypatch):
    """The vocabulary is only doc | wiki_node (§7.2): a bitable hit is neither
    — it stays "doc" rather than being misrendered as a wiki path."""
    payload = _search_payload([_hit("b1", entity="DOC", path="base/b1", doc_type="BITABLE")])
    fake = _FakeLarkCli(payload)
    _patch(monkeypatch, fake)
    hits = LarkAdapter(cmd=["fake-lark-cli"]).search_by_keywords("q")

    assert hits[0].node_type == "doc"


# ---------------------------------------------------------------------------
# search: bounded wiki enrichment (space_id) — fanout kills the whole backend
# past search_seconds (S33), so enrichment must stay inside a strict budget
# ---------------------------------------------------------------------------


def test_search_wiki_enrichment_failure_keeps_node_type(monkeypatch):
    """A failed probe never demotes node_type — only the position fields stay
    unset."""
    payload = _search_payload([_hit(WIKI_TOKEN, entity="WIKI", path=f"wiki/{WIKI_TOKEN}")])
    fake = _FakeLarkCli(payload)  # default probe response: 131005 not found
    _patch(monkeypatch, fake)
    hits = LarkAdapter(cmd=["fake-lark-cli"]).search_by_keywords("q")

    assert hits[0].node_type == "wiki_node"
    assert hits[0].space_id is None


def test_search_enrichment_is_capped(monkeypatch):
    """At most _WIKI_ENRICH_CAP probes run per search, in rank order."""
    tokens = [f"wiki{i:02d}" for i in range(12)]
    payload = _search_payload([_hit(t, entity="WIKI", path=f"wiki/{t}") for t in tokens])
    node_get = {t: _node_get_ok(t, f"sp{i}") for i, t in enumerate(tokens)}
    fake = _FakeLarkCli(payload, node_get=node_get)
    _patch(monkeypatch, fake)
    hits = LarkAdapter(cmd=["fake-lark-cli"]).search_by_keywords("q", top_k=12)

    assert len(fake.node_get_calls) == lark_mod._WIKI_ENRICH_CAP
    by_uri = {h.doc_uri.rsplit("/", 1)[-1]: h for h in hits}
    enriched = {t for t in tokens if by_uri[t].space_id is not None}
    assert enriched == set(tokens[: lark_mod._WIKI_ENRICH_CAP])  # first N win


def test_search_enrichment_budget_stops_all_probes(monkeypatch):
    """A zero budget skips every probe yet search still reports wiki_node."""
    monkeypatch.setattr(lark_mod, "_WIKI_ENRICH_BUDGET_SECONDS", 0.0, raising=False)
    payload = _search_payload([_hit(WIKI_TOKEN, entity="WIKI", path=f"wiki/{WIKI_TOKEN}")])
    fake = _FakeLarkCli(payload, node_get={WIKI_TOKEN: _node_get_ok(WIKI_TOKEN, SPACE_ID)})
    _patch(monkeypatch, fake)
    hits = LarkAdapter(cmd=["fake-lark-cli"]).search_by_keywords("q")

    assert fake.node_get_calls == []
    assert hits[0].node_type == "wiki_node"


# ---------------------------------------------------------------------------
# read: docs +fetch carries no type fact → probe wiki +node-get
# ---------------------------------------------------------------------------


def _fetch_stdout(title: str, body: str) -> str:
    return json.dumps(
        {"ok": True, "data": {"document": {"content": f"# {title}\n\n{body}", "document_id": "x", "revision_id": 7}}}
    )


def test_read_wiki_token_reports_wiki_node_with_space(monkeypatch):
    fake = _FakeLarkCli(
        "",
        node_get={WIKI_TOKEN: _node_get_ok(WIKI_TOKEN, SPACE_ID)},
        fetch_stdout=_fetch_stdout("部门新人入职", "body"),
    )
    _patch(monkeypatch, fake)
    adapter = LarkAdapter(cmd=["fake-lark-cli"])
    doc = adapter.read_document(f"kgent://lark/{WIKI_TOKEN}")

    assert doc.metadata.node_type == "wiki_node"
    assert doc.metadata.space_id == SPACE_ID
    assert doc.metadata.parent_node_token is None


def test_read_wiki_child_reports_parent_token(monkeypatch):
    fake = _FakeLarkCli(
        "",
        node_get={WIKI_TOKEN: _node_get_ok(WIKI_TOKEN, SPACE_ID, parent="wikiPARENT")},
        fetch_stdout=_fetch_stdout("部门新人入职", "body"),
    )
    _patch(monkeypatch, fake)
    doc = LarkAdapter(cmd=["fake-lark-cli"]).read_document(f"kgent://lark/{WIKI_TOKEN}")

    assert doc.metadata.parent_node_token == "wikiPARENT"


def test_read_flat_doc_stays_doc(monkeypatch):
    """131005 not_found is a definitive negative: the token is a flat docx."""
    fake = _FakeLarkCli("", fetch_stdout=_fetch_stdout("测试文档", "body"))
    _patch(monkeypatch, fake)
    doc = LarkAdapter(cmd=["fake-lark-cli"]).read_document(f"kgent://lark/{DOC_TOKEN}")

    assert doc.metadata.node_type == "doc"
    assert doc.metadata.space_id is None


def test_read_probe_timeout_degrades_to_doc(monkeypatch):
    """A hung probe degrades to the pre-fix behavior instead of failing the
    read (S33 spirit: degradation is visible in the field values, never an
    exception)."""
    def hung(argv: list[str], timeout: float, **_kw: Any) -> SubprocessResult:
        if "+node-get" in argv:
            raise AdapterTimeoutError("adapter CLI timed out")
        return SubprocessResult(0, _fetch_stdout("t", "b"), "")

    monkeypatch.setattr(cli_adapter_mod, "run_cli", hung, raising=False)
    monkeypatch.setattr(lark_mod, "run_cli", hung, raising=False)
    doc = LarkAdapter(cmd=["fake-lark-cli"]).read_document(f"kgent://lark/{WIKI_TOKEN}")

    assert doc.metadata.node_type == "doc"


# ---------------------------------------------------------------------------
# generic wire-v1 adapter: optional node fields parse when present (spec
# layer 2 — backends whose CLI contract grows the field keep working; ones
# without it stay "doc")
# ---------------------------------------------------------------------------


def _v1_adapter(monkeypatch, responses: dict[tuple[str, ...], str]) -> cli_adapter_mod.CliCapabilityAdapter:
    cmd = ["fake-cli"]

    def fake(argv: list[str], timeout: float, **_kw: Any) -> SubprocessResult:
        rest = [a for a in argv[len(cmd) :] if not a.startswith("-")]
        stdout = responses.get(tuple(rest[:2]))
        if stdout is None:
            raise AssertionError(f"unexpected argv: {argv}")
        return SubprocessResult(0, stdout, "")

    monkeypatch.setattr(cli_adapter_mod, "run_cli", fake, raising=False)
    return cli_adapter_mod.CliCapabilityAdapter(cmd=cmd, name="lark")


def test_v1_search_parses_optional_node_fields(monkeypatch):
    stdout = json.dumps(
        {
            "results": [
                {"id": "w1", "title": "wiki", "rank": 1, "node_type": "wiki_node", "space_id": "s1", "parent_node_token": "p1"},
                {"id": "d1", "title": "doc", "rank": 2},
            ]
        }
    )
    adapter = _v1_adapter(monkeypatch, {("search", "q"): stdout})
    hits = adapter.search_by_keywords("q")

    wiki, doc = hits[0], hits[1]
    assert wiki.node_type == "wiki_node"
    assert wiki.space_id == "s1"
    assert wiki.parent_node_token == "p1"
    assert wiki.metadata.node_type == "wiki_node"
    assert doc.node_type == "doc"
    assert doc.space_id is None


def test_v1_garbage_node_type_falls_back_to_doc(monkeypatch):
    stdout = json.dumps({"results": [{"id": "x", "title": "t", "rank": 1, "node_type": "bitable"}]})
    adapter = _v1_adapter(monkeypatch, {("search", "q"): stdout})
    hits = adapter.search_by_keywords("q")

    assert hits[0].node_type == "doc"


def test_v1_read_parses_optional_node_fields(monkeypatch):
    stdout = json.dumps(
        {
            "id": "w1",
            "title": "wiki",
            "content": "body",
            "updated_at": None,
            "version": "v1",
            "node_type": "wiki_node",
            "space_id": "s1",
            "parent_node_token": "p1",
        }
    )
    adapter = _v1_adapter(monkeypatch, {("documents", "read"): stdout})
    doc = adapter.read_document("kgent://lark/w1")

    assert doc.metadata.node_type == "wiki_node"
    assert doc.metadata.space_id == "s1"
    assert doc.metadata.parent_node_token == "p1"


def test_v1_read_without_node_fields_stays_doc(monkeypatch):
    stdout = json.dumps({"id": "d1", "title": "doc", "content": "body", "version": "v1"})
    adapter = _v1_adapter(monkeypatch, {("documents", "read"): stdout})
    doc = adapter.read_document("kgent://lark/d1")

    assert doc.metadata.node_type == "doc"
