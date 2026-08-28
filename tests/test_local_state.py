"""Local state protection + journal/undo (§6.7, S43, S44, S51, S52).

S43 — the ``~/.kgent`` dir is ``0700`` and the journal file ``0600`` after a
real write. S44 — journal entries are schema-versioned and undo restores the
pre-write content. S51 — a confidential snapshot body is omitted when the
journal is unencrypted. S52 — secrets never enter the journal. Plus retention
(FM9) and undo leg tests.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime, timedelta

import pytest

from kgent.router.journal import Journal, build_entry, undo
from kgent.router.policy import execute_confirmed
from kgent.types import Document, DocumentMetadata, WriteProposal
from tests.fakes.fake_backend import FakeBackend

_URI = "kgent://lark/docA"


def _prop(**kw: object) -> WriteProposal:
    base: dict[str, object] = {
        "operation": "create",
        "targets": [("lark", None)],
        "title": "Retros 2026-08",
        "content": "Retro meeting notes.",
        "content_type": None,
        "sensitivity": "internal",
        "approval_required": False,
        "provenance": {},
        "degraded": [],
        "warnings": [],
        "snapshot_note": "",
    }
    base.update(kw)
    return WriteProposal(**base)  # type: ignore[arg-type]


def _seed(
    backend: FakeBackend,
    uri: str,
    content: str = "original content",
    version: str = "v1",
) -> None:
    backend.docs[uri] = Document(
        doc_uri=uri,
        title="Retros parity",
        content=content,
        metadata=DocumentMetadata(
            doc_uri=uri,
            title="Retros parity",
            backend=backend.name,
            version=version,
        ),
    )


def _entry(op_id: str, ts: str, status: str = "ok") -> dict[str, object]:
    return {
        "schema_version": 1,
        "op_id": op_id,
        "ts": ts,
        "operation": "update",
        "targets": ["kgent://lark/doc1"],
        "idempotency_key": op_id,
        "snapshot": {"content_before": "x", "metadata_before": {}},
        "proposal_hash": "h",
        "confirmation": "interactive-yes",
        "sensitivity": "internal",
        "status": status,
    }


# ---------------------------------------------------------------------------
# S43 — permissions on local state after a real write
# ---------------------------------------------------------------------------


def test_s43_permissions_on_local_state(tmp_home, test_world):
    prop = _prop()
    op = execute_confirmed(prop, "interactive-yes", backends=test_world["backends"])
    assert op.exit_code == 0
    journal_path = tmp_home / "journal" / "journal.ndjson"
    assert journal_path.exists()
    if os.name == "nt":
        # NTFS exposes no POSIX mode bits; os.mkdir(0o700)/os.open(0o600) carry
        # the guarantee on POSIX filesystems. The real write above still runs.
        pytest.skip("POSIX mode bits are not representable on Windows")
    assert stat.S_IMODE(os.stat(tmp_home).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(journal_path).st_mode) == 0o600


# ---------------------------------------------------------------------------
# S44 — journal is versioned and undoable
# ---------------------------------------------------------------------------


def test_s44_journal_versioned_and_undoable(test_world):
    lark: FakeBackend = test_world["backends"]["lark"]
    lark.version_counter = 1
    _seed(lark, _URI, content="original content", version="v1")
    journal = Journal()
    prop = _prop(
        operation="update",
        targets=[("lark", _URI)],
        content="updated content",
        expected_version="v1",
    )
    op = execute_confirmed(
        prop, "interactive-yes", backends=test_world["backends"], journal=journal
    )
    assert op.journal_entry["schema_version"] == 1
    assert op.journal_entry["snapshot"]["content_before"] == "original content"
    assert lark.docs[_URI].content == "updated content"

    result = undo(op.op_id, backends=test_world["backends"], journal=journal)
    assert result.exit_code == 0
    assert lark.docs[_URI].content == "original content"
    # the undo itself is journaled (operation "undo", status "ok")
    assert journal.get(result.journal_entry["op_id"])["operation"] == "undo"
    assert result.journal_entry["status"] == "ok"


def test_undo_create_deletes_document(test_world):
    lark: FakeBackend = test_world["backends"]["lark"]
    journal = Journal()
    prop = _prop(operation="create", targets=[("lark", None)])
    op = execute_confirmed(
        prop, "interactive-yes", backends=test_world["backends"], journal=journal
    )
    uri = op.journal_entry["targets"][0]
    assert uri in lark.docs
    result = undo(op.op_id, backends=test_world["backends"], journal=journal)
    assert result.exit_code == 0
    assert uri not in lark.docs


def test_undo_unknown_op_id_reports_failure(test_world):
    journal = Journal()
    result = undo("op-missing", backends=test_world["backends"], journal=journal)
    assert result.exit_code == 1
    assert result.journal_entry["status"] == "failed"
    assert "unknown op id" in (result.error or "")


# ---------------------------------------------------------------------------
# S51 — confidential snapshot omitted when unencrypted
# ---------------------------------------------------------------------------


def test_s51_confidential_snapshot_omitted_when_unencrypted():
    entry = build_entry(
        op_id="op-1",
        ts="2026-08-28T00:00:00+00:00",
        operation="update",
        targets=[_URI],
        idempotency_key="op-1",
        proposal_hash="h",
        confirmation="interactive-yes",
        sensitivity="confidential",
        status="ok",
        encrypt=False,
        content_before="SECRET",
        metadata_before={"version": "v1"},
    )
    assert "content_before" not in entry["snapshot"]
    # metadata survives — the entry is metadata-only, not absent
    assert entry["snapshot"] == {"metadata_before": {"version": "v1"}}


def test_s51_confidential_snapshot_kept_when_encrypted():
    entry = build_entry(
        op_id="op-1",
        ts="2026-08-28T00:00:00+00:00",
        operation="update",
        targets=[_URI],
        idempotency_key="op-1",
        proposal_hash="h",
        confirmation="interactive-yes",
        sensitivity="confidential",
        status="ok",
        encrypt=True,
        content_before="SECRET",
    )
    assert entry["snapshot"]["content_before"] == "SECRET"


def test_undo_confidential_unencrypted_unavailable(test_world):
    lark: FakeBackend = test_world["backends"]["lark"]
    lark.version_counter = 1
    _seed(lark, _URI, content="secret body", version="v1")
    journal = Journal()
    prop = _prop(
        operation="update",
        targets=[("lark", _URI)],
        content="new secret body",
        sensitivity="confidential",
        expected_version="v1",
    )
    op = execute_confirmed(
        prop, "interactive-yes", backends=test_world["backends"], journal=journal
    )
    assert "content_before" not in op.journal_entry["snapshot"]
    result = undo(op.op_id, backends=test_world["backends"], journal=journal)
    assert result.exit_code == 1
    assert "undo unavailable" in (result.error or "")
    assert lark.docs[_URI].content == "new secret body"


# ---------------------------------------------------------------------------
# S52 — secrets never in the journal
# ---------------------------------------------------------------------------


def test_s52_secrets_never_in_journal():
    entry = build_entry(
        op_id="op-1",
        ts="2026-08-28T00:00:00+00:00",
        operation="update",
        targets=[_URI],
        idempotency_key="op-1",
        proposal_hash="h",
        confirmation="interactive-yes",
        sensitivity="internal",
        status="ok",
        content_before="legit document content",
        token="sk-live-abcdef123456",
        secret="hunter2",
        credential="credential-value",
    )
    serialized = json.dumps(entry)
    assert "sk-live-" not in serialized
    assert "hunter2" not in serialized
    assert "credential-value" not in serialized
    assert "token" not in serialized
    assert "secret" not in serialized
    # legitimate content is NOT mangled by the guard
    assert entry["snapshot"]["content_before"] == "legit document content"


# ---------------------------------------------------------------------------
# Journal queries + persistence + retention (FM9)
# ---------------------------------------------------------------------------


def test_journal_queries(tmp_home):
    now = datetime.now(UTC).isoformat()
    journal = Journal(home=tmp_home)
    journal.append(_entry("op-1", now, "ok"))
    journal.append(_entry("op-2", now, "failed"))
    journal.append(_entry("op-3", now, "partial"))
    assert journal.get("op-1")["status"] == "ok"
    assert journal.get("missing") is None
    assert [e["op_id"] for e in journal.list_failed()] == ["op-2"]
    assert [e["op_id"] for e in journal.list_partial()] == ["op-3"]
    assert journal.latest["op_id"] == "op-3"


def test_journal_persists_across_instances(tmp_home):
    now = datetime.now(UTC).isoformat()
    first = Journal(home=tmp_home)
    first.append(_entry("op-persist", now))
    second = Journal(home=tmp_home)
    assert second.get("op-persist") is not None
    assert second.get("op-persist")["op_id"] == "op-persist"


def test_prune_keeps_recent_drops_old(tmp_home):
    now = datetime.now(UTC)
    old_ts = (now - timedelta(days=60)).isoformat()
    recent_ts = now.isoformat()
    journal = Journal(home=tmp_home)
    journal.append(_entry("op-old", old_ts, "ok"))
    journal.append(_entry("op-recent", recent_ts, "failed"))

    pruned = journal.prune_older_than(30)
    assert pruned == 1
    # age-based, not status-based: the recent *failed* entry is kept,
    # the old *ok* entry is dropped
    assert journal.get("op-recent") is not None
    assert journal.get("op-old") is None

    on_disk = journal.path.read_text(encoding="utf-8")
    assert "op-recent" in on_disk
    assert "op-old" not in on_disk
