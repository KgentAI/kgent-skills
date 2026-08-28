"""Optimistic concurrency (§3.9, F2 S5–S7).

F2 invariant: updates never clobber external edits. A proposal recorded at
version ``v17`` that meets a platform-side ``v19`` aborts with a
:class:`VersionConflict` (exit 4), the journal records ``status ==
"conflict"``, and a fresh proposal based on a re-read document is offered.
Backends without revision tokens (the no-token path) fall back to
``updated_at`` comparison and the proposal carries the exact warning
``"no hard concurrency protection on <backend>"``.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from kgent.errors import VersionConflict
from kgent.router.concurrency import check_version, no_token_warning
from kgent.router.policy import execute_confirmed
from kgent.types import Document, DocumentMetadata, WriteProposal
from tests.fakes.fake_backend import FakeBackend
from tests.fakes.inmemory_journal import InMemoryJournal

_URI = "kgent://lark/docA"


def _prop(uri: str = _URI, *, backend: str = "lark", **kw: object) -> WriteProposal:
    """Update proposal builder (defaults: lark, no-token-free fields)."""
    base: dict[str, object] = {
        "operation": "update",
        "targets": [(backend, uri)],
        "title": "Retros parity",
        "content": "Updated retro notes.",
        "content_type": None,
        "sensitivity": "internal",
        "approval_required": False,
        "provenance": {},
        "degraded": [],
        "warnings": [],
        "snapshot_note": "",
        "expected_version": None,
        "expected_updated_at": None,
    }
    base.update(kw)
    return WriteProposal(**base)  # type: ignore[arg-type]


def _seed(
    backend: FakeBackend,
    uri: str,
    version: str,
    *,
    updated_at: datetime | None = None,
    content: str = "original content",
) -> None:
    """Place a document directly (a *platform-side* read shape)."""
    backend.docs[uri] = Document(
        doc_uri=uri,
        title="Retros parity",
        content=content,
        metadata=DocumentMetadata(
            doc_uri=uri,
            title="Retros parity",
            backend=backend.name,
            version=version,
            updated_at=updated_at,
        ),
    )


# ---------------------------------------------------------------------------
# check_version — pure guard (§3.9)
# ---------------------------------------------------------------------------


def test_check_version_token_match_passes():
    check_version("v17", "v17", None, None, _URI)  # no raise


def test_check_version_token_mismatch_raises():
    with pytest.raises(VersionConflict) as ei:
        check_version("v17", "v19", None, None, _URI)
    assert "expected v17, found v19" in str(ei.value)


def test_check_version_token_but_backend_has_none_raises():
    with pytest.raises(VersionConflict):
        check_version("v17", None, None, None, _URI)


def test_check_version_no_token_updated_at_equal_passes():
    t0 = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)
    check_version(None, None, t0, t0, "kgent://dingtalk/d1")  # no raise


def test_check_version_no_token_updated_at_mismatch_raises():
    t0 = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)
    with pytest.raises(VersionConflict):
        check_version(None, None, t0, t0 + timedelta(minutes=5), "kgent://dingtalk/d1")


def test_no_token_warning_exact_string():
    assert no_token_warning("dingtalk") == "no hard concurrency protection on dingtalk"


# ---------------------------------------------------------------------------
# S5 — update with the current version succeeds (exit 0, status ok)
# ---------------------------------------------------------------------------


def test_s5_update_with_current_version_succeeds(test_world):
    lark: FakeBackend = test_world["backends"]["lark"]
    journal = InMemoryJournal()
    lark.version_counter = 17  # platform at v17 → the write lands at v18
    _seed(lark, _URI, "v17")
    op = execute_confirmed(
        _prop(expected_version="v17"),
        "interactive-yes",
        backends=test_world["backends"],
        journal=journal,
    )
    assert op.exit_code == 0
    assert op.journal_entry["status"] == "ok"
    assert op.error is None
    assert op.fresh_proposal is None
    # the write landed on the current version and bumped it
    assert lark.docs[_URI].content == "Updated retro notes."
    assert lark.docs[_URI].metadata.version == "v18"
    assert journal.latest["status"] == "ok"


# ---------------------------------------------------------------------------
# S6 — stale proposal (v17) vs platform v19 → conflict, exit 4, fresh proposal
# ---------------------------------------------------------------------------


def test_s6_stale_version_aborts_with_conflict(test_world):
    lark: FakeBackend = test_world["backends"]["lark"]
    journal = InMemoryJournal()
    _seed(lark, _URI, "v17")
    prop = _prop(expected_version="v17")
    # a concurrent session bumps the platform to v19 before our confirm lands
    doc = lark.docs[_URI]
    lark.docs[_URI] = replace(doc, metadata=replace(doc.metadata, version="v19"))

    op = execute_confirmed(
        prop,
        "interactive-yes",
        backends=test_world["backends"],
        journal=journal,
    )

    # zero new content written — the doc is untouched (v19, old body)
    assert lark.docs[_URI].content == "original content"
    assert lark.docs[_URI].metadata.version == "v19"
    assert [c["method"] for c in lark.write_calls if c["method"] == "update_document"] == []

    # conflict surfaced with the exact VersionConflict message (not a generic error)
    assert "expected v17, found v19" in (op.error or "")

    # journaled as a conflict at exit 4, confirmation still recorded (N1)
    assert op.exit_code == 4
    assert op.journal_entry["status"] == "conflict"
    assert journal.latest["status"] == "conflict"
    assert journal.latest["confirmation"] == "interactive-yes"
    assert len(journal.entries) == 1

    # a fresh proposal based on the re-read is offered, user's edit preserved
    assert op.fresh_proposal is not None
    assert op.fresh_proposal.expected_version == "v19"
    assert op.fresh_proposal.content == "Updated retro notes."


# ---------------------------------------------------------------------------
# S7 — no revision token → updated_at fallback + warning
# ---------------------------------------------------------------------------


def test_s7_no_token_falls_back_to_updated_at(test_world):
    dingtalk: FakeBackend = test_world["backends"]["dingtalk"]
    journal = InMemoryJournal()
    uri = "kgent://dingtalk/d1"
    t0 = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)
    _seed(dingtalk, uri, "v1", updated_at=t0)

    prop = _prop(
        uri=uri,
        backend="dingtalk",
        expected_version=None,
        expected_updated_at=t0,
        warnings=[no_token_warning("dingtalk")],
    )
    # the built proposal must carry the exact no-token warning (S7)
    assert prop.warnings == ["no hard concurrency protection on dingtalk"]

    # a concurrent platform edit bumps updated_at before our confirm lands
    doc = dingtalk.docs[uri]
    dingtalk.docs[uri] = replace(
        doc,
        metadata=replace(doc.metadata, version="v2", updated_at=t0 + timedelta(minutes=5)),
    )

    op = execute_confirmed(
        prop,
        "interactive-yes",
        backends=test_world["backends"],
        journal=journal,
    )

    # updated_at comparison aborts the write: nothing lands
    assert op.exit_code == 4
    assert op.journal_entry["status"] == "conflict"
    assert op.error is not None
    assert dingtalk.docs[uri].content == "original content"
    assert dingtalk.docs[uri].metadata.version == "v2"
    assert [c["method"] for c in dingtalk.write_calls if c["method"] == "update_document"] == []

    # fresh proposal re-pinned to the re-read state
    assert op.fresh_proposal is not None
    assert op.fresh_proposal.expected_version == "v2"
