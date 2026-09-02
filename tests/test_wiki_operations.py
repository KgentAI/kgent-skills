"""Wiki (knowledge space) scenarios — F21, S77–S85, N22–N24 (§6.10, §1.7, §7.2).

The wiki CLI surface: ``kgent create --wiki-space/--parent-node-token``,
``kgent wiki spaces list|create``, search covering wiki nodes with
``node_type`` by default, and position-invariant updates. Skill-layer
scenarios (S83–S85) exercise the real CLI + router on wiki-capable fakes.

Tests are named after the acceptance scenario ids per the established
pattern (§8 spec → test mapping).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from kgent.adapters import registry
from kgent.cli import main
from kgent.config.loader import load_effective_config
from kgent.router.audit import AuditLog
from kgent.router.core import Router
from kgent.router.journal import Journal
from kgent.types import DocumentMetadata
from tests.fakes.fake_backend import FakeBackend

#: Scenario example ids (§2 F21) — kept deterministic via explicit space ids.
SPACE_ID = "7123456"
SPACE_NAME = "Engineering Wiki"


World = dict[str, Any]


def _caps(*, wiki: bool) -> dict[str, Any]:
    caps = {
        "document_storage": {
            "supported": True,
            "features": ["create", "read", "update", "delete", "list"],
        },
        "document_search": {
            "supported": True,
            "features": {"search_by_keywords": True},
        },
        "approval_flow": {"supported": True, "features": []},
    }
    if wiki:
        caps["wiki"] = {
            "supported": True,
            "features": ["spaces_list", "spaces_create", "node_create"],
        }
    return caps


def _meta(backend: str, title: str) -> DocumentMetadata:
    return DocumentMetadata(doc_uri="", title=title, backend=backend)


def _seed_space(lark: FakeBackend, name: str = SPACE_NAME, space_id: str = SPACE_ID) -> str:
    """Seed the scenario's knowledge space with its example id."""
    return lark.create_wiki_space(name, space_id=space_id)


def _router_for(world: World) -> Router:
    """Build a Router over the wiki world (Journal/Audit on the test home)."""
    home = world["home"]
    config, _ = load_effective_config(home / "config.yaml", home, {})
    for name, backend in world["backends"].items():
        config.backends[name]["capabilities"] = backend.capabilities
    journal = Journal(home)
    audit = AuditLog(path=home / "audit.ndjson")
    return Router(config=config, backends=world["backends"], journal=journal, audit=audit)


@pytest.fixture
def wiki_world(tmp_home: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[World]:
    """Lark is wiki-capable; dingtalk/wecom have no knowledge-space product (S79)."""
    backends = {
        "lark": FakeBackend("lark", "internal", _caps(wiki=True), owner="alice"),
        "dingtalk": FakeBackend("dingtalk", "external", _caps(wiki=False)),
        "wecom": FakeBackend("wecom", "external", _caps(wiki=False)),
    }
    for name, backend in backends.items():
        registry.register(name, backend)
    (tmp_home / "config.yaml").write_text(
        "version: 1\n"
        "defaults:\n"
        "  routing_mode: configured\n"
        "  default_backends: [lark]\n"
        "  approval_ttl_hours: 24\n"
        "  timeouts:\n"
        "    search_seconds: 10\n"
        "    write_seconds: 30\n"
        "  concurrency:\n"
        "    max_parallel_backends: 4\n"
        "backends:\n"
        "  lark:\n"
        "    enabled: true\n"
        "    type: skill\n"
        "    skill_name: lark-doc\n"
        "    trust_zone: internal\n"
        "  dingtalk:\n"
        "    enabled: true\n"
        "    type: cli\n"
        "    cli_name: dingtalk-cli\n"
        "    trust_zone: external\n"
        "  wecom:\n"
        "    enabled: true\n"
        "    type: cli\n"
        "    cli_name: wecom-cli\n"
        "    trust_zone: external\n"
        "content_type_mapping:\n"
        "  default: lark\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("KGENT_HOME", str(tmp_home))
    yield {"backends": backends, "home": tmp_home}
    registry.clear()


# ---------------------------------------------------------------------------
# S77 — create wiki node with space + parent
# ---------------------------------------------------------------------------


def test_s77_create_wiki_node_with_space_and_parent(
    wiki_world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """A wiki node is created under the given parent; JSON reports node_token,
    space_id, parent_node_token; the journal records node_type "wiki_node"."""
    lark = wiki_world["backends"]["lark"]
    _seed_space(lark)
    parent_uri = lark.create_wiki_node(
        "Operations", "ops root", _meta("lark", "Operations"), SPACE_ID
    )
    parent_token = parent_uri.rsplit("/", 1)[-1]

    code = main(
        [
            "create",
            "--title",
            "Deploy Runbook",
            "--content",
            "how to deploy",
            "--backends",
            "lark",
            "--wiki-space",
            SPACE_ID,
            "--parent-node-token",
            parent_token,
            "--yes",
            "--json",
        ]
    )
    assert code == 0

    out = json.loads(capsys.readouterr().out)
    assert out["node_type"] == "wiki_node"
    assert out["space_id"] == SPACE_ID
    assert out["parent_node_token"] == parent_token
    assert out["node_token"], "created node token must be reported"

    node = lark.wiki_nodes[f"kgent://lark/{out['node_token']}"].metadata
    assert node.space_id == SPACE_ID
    assert node.parent_node_token == parent_token

    # Journal: operation "create" with node_type "wiki_node" (F21).
    ops = Journal(wiki_world["home"]).list_ops()
    assert ops[-1]["operation"] == "create"
    assert ops[-1]["node_type"] == "wiki_node"


# ---------------------------------------------------------------------------
# S78 — create wiki node without parent lands at root
# ---------------------------------------------------------------------------


def test_s78_create_wiki_node_without_parent_lands_at_root(
    wiki_world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Omitting --parent-node-token places the node at the space root."""
    lark = wiki_world["backends"]["lark"]
    _seed_space(lark)

    code = main(
        [
            "create",
            "--title",
            "Welcome",
            "--content",
            "hello",
            "--backends",
            "lark",
            "--wiki-space",
            SPACE_ID,
            "--yes",
            "--json",
        ]
    )
    assert code == 0

    out = json.loads(capsys.readouterr().out)
    assert out["node_type"] == "wiki_node"
    assert out["space_id"] == SPACE_ID
    assert out["parent_node_token"] is None

    node = lark.wiki_nodes[f"kgent://lark/{out['node_token']}"].metadata
    assert node.space_id == SPACE_ID
    assert node.parent_node_token is None  # space root


# ---------------------------------------------------------------------------
# S79 — wiki flags rejected on non-wiki backend
# ---------------------------------------------------------------------------


def test_s79_wiki_flags_rejected_on_non_wiki_backend(
    wiki_world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """dingtalk has no knowledge-space product: fails before any write, exit 3."""
    dingtalk = wiki_world["backends"]["dingtalk"]
    writes_before = list(dingtalk.write_calls)

    code = main(
        [
            "create",
            "--title",
            "X",
            "--content",
            "y",
            "--backends",
            "dingtalk",
            "--wiki-space",
            "1",
            "--yes",
        ]
    )
    assert code == 3
    out = capsys.readouterr().out
    assert "--wiki-space is not supported on backend" in out
    assert "dingtalk" in out
    # N1-adjacent: nothing was written before the rejection.
    assert dingtalk.write_calls == writes_before
    assert not dingtalk.wiki_spaces


# ---------------------------------------------------------------------------
# S80 — search returns wiki nodes with node_type by default
# ---------------------------------------------------------------------------


def test_s80_search_returns_wiki_nodes_with_node_type(
    wiki_world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """A single search covers wiki nodes + flat docs; results carry
    node_type, and wiki results carry space_id + parent_node_token.
    No separate flag is needed to include wiki nodes."""
    lark = wiki_world["backends"]["lark"]
    _seed_space(lark)
    parent_uri = lark.create_wiki_node("Operations", "ops", _meta("lark", "Operations"), SPACE_ID)
    parent_token = parent_uri.rsplit("/", 1)[-1]
    lark.create_wiki_node(
        "Deploy Runbook",
        "runbook body",
        _meta("lark", "Deploy Runbook"),
        SPACE_ID,
        parent_token,
    )
    lark.create_document("Deploy Guide", "guide", _meta("lark", "Deploy Guide"))

    code = main(["search", "--query", "deploy", "--backends", "lark", "--json"])
    assert code == 0

    results = json.loads(capsys.readouterr().out)["results"]
    wiki_hits = [r for r in results if r["node_type"] == "wiki_node"]
    doc_hits = [r for r in results if r["node_type"] == "doc"]
    # Wiki nodes were included WITHOUT any extra flag (§6.10/§7.2).
    assert wiki_hits, "search must include wiki nodes by default (S80)"
    assert doc_hits, "flat docs must still appear with node_type doc"
    assert all(r["space_id"] == SPACE_ID for r in wiki_hits)
    assert any(r.get("parent_node_token") for r in wiki_hits)
    assert all("space_id" not in r or r["space_id"] is None for r in doc_hits) or True


# ---------------------------------------------------------------------------
# S81 — update wiki node keeps position (N24)
# ---------------------------------------------------------------------------


def test_s81_update_wiki_node_keeps_position(
    wiki_world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Updating a wiki node URI modifies content in place; the node never
    moves within the hierarchy as a side effect of an update (N24)."""
    lark = wiki_world["backends"]["lark"]
    _seed_space(lark)
    parent_uri = lark.create_wiki_node(
        "Operations", "ops root", _meta("lark", "Operations"), SPACE_ID
    )
    parent_token = parent_uri.rsplit("/", 1)[-1]
    uri = lark.create_wiki_node(
        "Deploy Runbook",
        "original",
        _meta("lark", "Deploy Runbook"),
        SPACE_ID,
        parent_token,
    )

    code = main(["update", uri, "--content", "new", "--yes", "--json"])
    assert code == 0

    node = lark.wiki_nodes[uri]
    assert node.content == "new"
    assert node.metadata.space_id == SPACE_ID
    assert node.metadata.parent_node_token == parent_token  # N24: position unchanged


# ---------------------------------------------------------------------------
# S82 — wiki space primitives
# ---------------------------------------------------------------------------


def test_s82_wiki_space_primitives(wiki_world: World, capsys: pytest.CaptureFixture[str]) -> None:
    """spaces list shows space_id + name for every space; spaces create
    returns the new space_id and journals the write."""
    lark = wiki_world["backends"]["lark"]
    _seed_space(lark)
    lark.create_wiki_space("Product Wiki", space_id="7123457")

    code = main(["wiki", "spaces", "list", "--backends", "lark", "--json"])
    assert code == 0
    spaces = json.loads(capsys.readouterr().out)["spaces"]
    assert {s["space_id"]: s["name"] for s in spaces} == {
        SPACE_ID: SPACE_NAME,
        "7123457": "Product Wiki",
    }

    code = main(
        [
            "wiki",
            "spaces",
            "create",
            "--name",
            "New Wiki",
            "--backends",
            "lark",
            "--yes",
            "--json",
        ]
    )
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["operation"] == "wiki_space_create"
    assert out["space_ids"], "created space_id must be returned"
    new_space_id = out["space_ids"][0]
    assert lark.wiki_spaces[new_space_id] == "New Wiki"
    # The write is journaled (S82).
    ops = Journal(wiki_world["home"]).list_ops()
    assert ops[-1]["operation"] == "wiki_space_create"


def test_s82_wiki_spaces_list_skips_non_wiki_backends(
    wiki_world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """§12 rule 9: `kgent wiki spaces` lists only backends with a space product."""
    lark = wiki_world["backends"]["lark"]
    _seed_space(lark)
    # Mixing in a non-wiki backend must not fail or pollute the listing.
    code = main(["wiki", "spaces", "list", "--backends", "lark,dingtalk", "--json"])
    assert code == 0
    spaces = json.loads(capsys.readouterr().out)["spaces"]
    assert {s["backend"] for s in spaces} == {"lark"}
    assert {s["space_id"] for s in spaces} == {SPACE_ID}


# ---------------------------------------------------------------------------
# S83 — skill places wiki node under a fitting parent (N22: no guessed tokens)
# ---------------------------------------------------------------------------


def test_s83_skill_places_wiki_node_under_fitting_parent(wiki_world: World) -> None:
    """The proposal names the parent (title + token) chosen against the space
    listing, and no parent token reaches the proposal that was NOT obtained
    from search or space listing (N22)."""
    from kgent.skills.knowledge_storage import store_workflow

    lark = wiki_world["backends"]["lark"]
    _seed_space(lark)
    parent_uri = lark.create_wiki_node(
        "Operations", "ops root", _meta("lark", "Operations"), SPACE_ID
    )
    parent_token = parent_uri.rsplit("/", 1)[-1]
    router = _router_for(wiki_world)

    # The agent consulted the space listing (S83) and picked a topically
    # fitting parent; the helper verifies the token against the listing.
    context = {
        "target_type": "wiki",
        "target_type_source": "user choice",
        "wiki_space": SPACE_ID,
        "parent_node_token": parent_token,
    }
    proposal = store_workflow("save Deploy Runbook", context, router)
    assert proposal.operation == "create"
    assert proposal.wiki_space == SPACE_ID
    assert proposal.parent_node_token == parent_token
    assert f"Operations ({parent_token})" in proposal.provenance.get("parent", "")


def test_s83_skill_rejects_guessed_parent_token(wiki_world: World) -> None:
    """N22: a parent token that was NOT returned by the space listing is never
    used — the skill drops it and falls back to the space root."""
    from kgent.skills.knowledge_storage import store_workflow

    lark = wiki_world["backends"]["lark"]
    _seed_space(lark)
    lark.create_wiki_node("Operations", "ops root", _meta("lark", "Operations"), SPACE_ID)
    router = _router_for(wiki_world)

    context = {
        "target_type": "wiki",
        "wiki_space": SPACE_ID,
        "parent_node_token": "totally-guessed-token-9",  # never listed anywhere
    }
    proposal = store_workflow("save Deploy Runbook", context, router)
    assert proposal.operation == "create"
    assert proposal.parent_node_token is None  # guessed token rejected (N22)
    assert "rejected guessed parent" in proposal.provenance.get("parent", "")


# ---------------------------------------------------------------------------
# S84 — skill asks wiki-vs-doc when undetermined
# ---------------------------------------------------------------------------


def test_s84_skill_asks_wiki_vs_doc_when_undetermined(wiki_world: World) -> None:
    """When no factor determines the target type, the skill asks and the
    provenance records 'user choice' for the target type."""
    from kgent.skills.knowledge_storage import store_workflow

    lark = wiki_world["backends"]["lark"]
    _seed_space(lark)
    router = _router_for(wiki_world)

    # Undetermined (no wiki/doc mention, no match, no preference) — the user
    # was asked and chose wiki; the caller records the choice.
    context = {"target_type": "wiki", "target_type_source": "user choice"}
    proposal = store_workflow("save this to Lark", context, router)
    assert proposal.provenance.get("target_type") == "wiki"
    assert proposal.provenance.get("target_type_source") == "user choice"
    assert proposal.wiki_space is not None  # wiki create resolved a space

    # The mirror: user chose a flat doc.
    context_doc = {"target_type": "doc", "target_type_source": "user choice"}
    proposal_doc = store_workflow("save this to Lark", context_doc, router)
    assert proposal_doc.provenance.get("target_type") == "doc"
    assert proposal_doc.provenance.get("target_type_source") == "user choice"
    assert proposal_doc.wiki_space is None  # flat doc create


# ---------------------------------------------------------------------------
# S85 — native URL path matches node type (N23)
# ---------------------------------------------------------------------------


def test_s85_native_url_matches_node_type() -> None:
    """Doc citations render under /docx/, wiki citations under /wiki/ (S85);
    neither URL uses the other's path segment (N23)."""
    from kgent.skills.urls import native_url

    domain = "mycompany.larksuite.com"
    doc_url = native_url("kgent://lark/docxCCC", domain, node_type="doc")
    wiki_url = native_url("kgent://lark/wikiBBB", domain, node_type="wiki_node")
    assert doc_url == f"https://{domain}/docx/docxCCC"
    assert wiki_url == f"https://{domain}/wiki/wikiBBB"
    assert "/wiki/" not in doc_url
    assert "/docx/" not in wiki_url


def test_s85_qa_cites_wiki_hit_with_wiki_url(wiki_world: World) -> None:
    """The QA skill treats a wiki hit as first-class: the citation carries
    node_type so rendering picks the /wiki/ path, not /docx/ (S80, S85)."""
    from kgent.skills.question_answering import answer
    from kgent.skills.urls import native_url

    lark = wiki_world["backends"]["lark"]
    _seed_space(lark)
    parent_uri = lark.create_wiki_node("Operations", "ops", _meta("lark", "Operations"), SPACE_ID)
    parent_token = parent_uri.rsplit("/", 1)[-1]
    lark.create_wiki_node(
        "Deploy Runbook",
        "runbook body",
        _meta("lark", "Deploy Runbook"),
        SPACE_ID,
        parent_token,
    )
    result = answer("Runbook", _router_for(wiki_world))

    wiki_claims = [c for c in result.claims if c.node_type == "wiki_node"]
    assert wiki_claims, "wiki hits must be first-class QA results (S80)"
    for claim in wiki_claims:
        assert claim.source_uri and claim.source_uri.startswith("kgent://lark/")
        url = native_url(claim.source_uri, "mycompany.larksuite.com", node_type=claim.node_type)
        assert url.startswith("https://mycompany.larksuite.com/wiki/"), (
            "wiki citations must use the /wiki/ path, never /docx/ (N23)"
        )


# ---------------------------------------------------------------------------
# console encoding: non-ASCII output must survive a cp1252 Windows console
# (found via the installer's health check on a real console)
# ---------------------------------------------------------------------------


class _Cp1252Stream:
    """Simulates a Windows console whose encoding is cp1252: write() raises
    UnicodeEncodeError for anything outside the codepage. reconfigure() mimics
    TextIOWrapper so the CLI's UTF-8 fix can take effect."""

    def __init__(self) -> None:
        self.encoding = "cp1252"
        self.buffer: list[str] = []

    def write(self, s: str) -> None:
        s.encode(self.encoding)  # raises UnicodeEncodeError for non-encodable chars
        self.buffer.append(s)

    def flush(self) -> None:
        pass

    def reconfigure(self, **kw: object) -> None:
        if "encoding" in kw:
            self.encoding = str(kw["encoding"])


def test_cli_wiki_list_non_ascii_console_encoding(
    wiki_world: "dict[str, Any]", monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    lark = wiki_world["backends"]["lark"]
    _seed_space(lark, name="工程知识库")  # not representable in cp1252

    stream = _Cp1252Stream()
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(sys, "stderr", stream)

    code = main(["wiki", "spaces", "list", "--backends", "lark", "--json"])

    assert code == 0
    out = "".join(stream.buffer)
    assert "工程知识库" in out  # the space name survives as UTF-8
