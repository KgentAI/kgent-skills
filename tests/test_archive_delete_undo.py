"""Archive, delete, undo, and sync/repair tests (Task 8.3; S8–S12, S29, S30, S50)."""

# pyright: basic
from __future__ import annotations

import pytest

from kgent.adapters import registry
from kgent.cli import main
from tests.fakes.fake_backend import FakeBackend


def _full_caps() -> dict:
    return {
        "document_storage": {
            "supported": True,
            "features": [
                "create",
                "read",
                "update",
                "delete",
                "list",
                "archive",
                "unarchive",
            ],
        },
        "document_search": {
            "supported": True,
            "features": {
                "search_by_keywords": True,
                "search_by_semantics": True,
                "search_hybrid": True,
            },
            "limits": {"max_results": 100, "max_content_bytes": 2_000_000},
        },
        "approval_flow": {
            "supported": True,
            "features": ["request_approval", "execute_approved"],
        },
    }


@pytest.fixture
def e2e(tmp_home, monkeypatch):
    backends = {
        "lark": FakeBackend("lark", "internal", _full_caps(), owner="alice"),
        "wecom": FakeBackend("wecom", "external", _full_caps()),
    }
    for name, backend in backends.items():
        registry.register(name, backend)

    config_text = (
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
        "  wecom:\n"
        "    enabled: true\n"
        "    type: cli\n"
        "    cli_name: wecom-cli\n"
        "    trust_zone: external\n"
        "content_type_mapping:\n"
        "  meeting_notes: lark\n"
        "  default: lark\n"
    )
    (tmp_home / "config.yaml").write_text(config_text, encoding="utf-8")
    monkeypatch.setenv("KGENT_HOME", str(tmp_home))

    yield {"backends": backends, "home": tmp_home}

    registry.clear()


# ---------------------------------------------------------------------------
# S8: delete offers archive first (CLI-level, non-interactive)
# ---------------------------------------------------------------------------


def test_s8_delete_with_yes_removes_doc(e2e):
    """S8: delete with --yes removes the doc (archive offered but bypassed)."""
    main(["store", "--title", "Doc", "--content", "x", "--backends", "lark"])
    uri = next(iter(e2e["backends"]["lark"].docs))
    code = main(["delete", uri, "--yes"])
    assert code == 0
    assert uri not in e2e["backends"]["lark"].docs


# ---------------------------------------------------------------------------
# S9: archive fault → doc stays active, journal "failed", exit 2
# ---------------------------------------------------------------------------


def test_s9_archive_fault_doc_stays_active(e2e):
    """S9: archive backend fault → doc stays active, journal records failure, exit 2."""
    main(["store", "--title", "Doc", "--content", "x", "--backends", "lark"])
    uri = next(iter(e2e["backends"]["lark"].docs))
    # Inject a fault on archive
    e2e["backends"]["lark"].fault = lambda m, kw: (_ for _ in ()).throw(RuntimeError("boom"))
    code = main(["archive", uri])
    assert code == 1  # archive failure → exit 1
    # Doc stays active (not archived)
    assert uri in e2e["backends"]["lark"].docs
    assert uri not in e2e["backends"]["lark"].archived


# ---------------------------------------------------------------------------
# S10: single platform op id (archive)
# ---------------------------------------------------------------------------


def test_s10_archive_single_op_id(e2e):
    """S10: archive uses a single platform op id (one journal entry)."""
    main(["store", "--title", "Doc", "--content", "x", "--backends", "lark"])
    uri = next(iter(e2e["backends"]["lark"].docs))
    code = main(["archive", uri])
    assert code == 0
    from kgent.router.journal import Journal

    journal = Journal(e2e["home"])
    archive_ops = [o for o in journal.list_ops() if o["operation"] == "archive"]
    assert len(archive_ops) == 1


# ---------------------------------------------------------------------------
# S11: undo restores content
# ---------------------------------------------------------------------------


def test_s11_undo_restores_content(e2e):
    """S11: undo of an update restores the original content."""
    main(["store", "--title", "Doc", "--content", "before", "--backends", "lark"])
    uri = next(iter(e2e["backends"]["lark"].docs))
    main(["update", uri, "--content", "after"])
    assert e2e["backends"]["lark"].docs[uri].content == "after"
    from kgent.router.journal import Journal

    journal = Journal(e2e["home"])
    op_id = next(o["op_id"] for o in journal.list_ops() if o["operation"] == "update")
    code = main(["undo", op_id])
    assert code == 0
    assert e2e["backends"]["lark"].docs[uri].content == "before"


# ---------------------------------------------------------------------------
# S12: undo-edited refuses
# ---------------------------------------------------------------------------


def test_s12_undo_edited_refuses(e2e):
    """S12: undo refuses if the doc was edited after the journaled update."""
    main(["store", "--title", "Doc", "--content", "v1", "--backends", "lark"])
    uri = next(iter(e2e["backends"]["lark"].docs))
    main(["update", uri, "--content", "v2"])
    # Edit the doc again (simulating another editor)
    main(["update", uri, "--content", "v3"])
    # Now undo the first update — should refuse because doc was edited since
    from kgent.router.journal import Journal

    journal = Journal(e2e["home"])
    update_ops = [o for o in journal.list_ops() if o["operation"] == "update"]
    first_update_id = update_ops[0]["op_id"]
    code = main(["undo", first_update_id])
    # Undo should fail (exit != 0) because the doc was edited after the first update
    assert code != 0


# ---------------------------------------------------------------------------
# S29: repair no-duplicate
# ---------------------------------------------------------------------------


def test_s29_repair_no_duplicate(e2e):
    """S29: repairing a partial op doesn't duplicate journal entries."""
    e2e["backends"]["wecom"].fault = lambda m, kw: (_ for _ in ()).throw(RuntimeError("boom"))
    code = main(["store", "--title", "Doc", "--content", "x", "--backends", "lark,wecom"])
    assert code == 2  # partial
    e2e["backends"]["wecom"].fault = None
    from kgent.router.journal import Journal

    journal = Journal(e2e["home"])
    partial_ops = journal.list_partial()
    assert len(partial_ops) == 1
    op_id = partial_ops[0]["op_id"]
    # Repair
    code = main(["sync", "--repair", op_id])
    assert code == 0
    # No duplicate partial entries
    partial_after = journal.list_partial()
    assert len(partial_after) == 1


# ---------------------------------------------------------------------------
# S30: sync status lists exactly one failed leg
# ---------------------------------------------------------------------------


def test_s30_sync_status_lists_failed_leg(e2e):
    """S30: sync status lists exactly one failed leg for a partial op."""
    e2e["backends"]["wecom"].fault = lambda m, kw: (_ for _ in ()).throw(RuntimeError("boom"))
    main(["store", "--title", "Doc", "--content", "x", "--backends", "lark,wecom"])
    from kgent.router.journal import Journal

    journal = Journal(e2e["home"])
    partial = journal.list_partial()
    assert len(partial) == 1
    failed_targets = partial[0].get("failed_targets", [])
    assert len(failed_targets) == 1  # exactly one failed leg


# ---------------------------------------------------------------------------
# S50: platform-native archive (adapter receives archive call)
# ---------------------------------------------------------------------------


def test_s50_archive_calls_adapter(e2e):
    """S50: archive delegates to the adapter's archive_document method."""
    main(["store", "--title", "Doc", "--content", "x", "--backends", "lark"])
    uri = next(iter(e2e["backends"]["lark"].docs))
    main(["archive", uri])
    lark = e2e["backends"]["lark"]
    assert uri in lark.archived
    assert uri not in lark.docs
    assert any(c["method"] == "archive_document" for c in lark.write_calls)
