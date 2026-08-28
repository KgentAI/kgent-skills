"""Repair idempotency tests (Task 8.3; S29, S30)."""

from __future__ import annotations

import pytest

from kgent.adapters import registry
from kgent.cli import main
from kgent.router.repair import sync_repair, sync_status
from tests.fakes.fake_backend import FakeBackend


def _full_caps() -> dict:
    return {
        "document_storage": {
            "supported": True,
            "features": ["create", "read", "update", "delete", "list"],
        },
        "document_search": {"supported": True, "features": {}},
        "approval_flow": {"supported": True, "features": []},
    }


@pytest.fixture
def env(tmp_home, monkeypatch):
    backends = {
        "lark": FakeBackend("lark", "internal", _full_caps()),
        "wecom": FakeBackend("wecom", "external", _full_caps()),
    }
    for name, b in backends.items():
        registry.register(name, b)
    (tmp_home / "config.yaml").write_text(
        "version: 1\ndefaults:\n  routing_mode: configured\n"
        "  default_backends: [lark]\n  approval_ttl_hours: 24\n"
        "  timeouts:\n    search_seconds: 10\n    write_seconds: 30\n"
        "  concurrency:\n    max_parallel_backends: 4\n"
        "backends:\n"
        "  lark:\n    enabled: true\n    type: skill\n"
        "    skill_name: lark-doc\n    trust_zone: internal\n"
        "  wecom:\n    enabled: true\n    type: cli\n"
        "    cli_name: wecom-cli\n    trust_zone: external\n"
        "content_type_mapping:\n  default: lark\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("KGENT_HOME", str(tmp_home))
    yield {"backends": backends, "home": tmp_home}
    registry.clear()


def test_sync_status_returns_failed_legs(env):
    """sync_status reports the failed targets from a partial journal entry."""
    env["backends"]["wecom"].fault = lambda m, kw: (_ for _ in ()).throw(RuntimeError("boom"))
    main(["store", "--title", "Doc", "--content", "x", "--backends", "lark,wecom"])
    from kgent.router.journal import Journal
    journal = Journal(env["home"])
    statuses = sync_status(journal)
    assert len(statuses) == 1
    assert statuses[0]["failed_targets"]


def test_sync_repair_is_idempotent(env):
    """S29: repairing twice doesn't duplicate writes or journal entries."""
    env["backends"]["wecom"].fault = lambda m, kw: (_ for _ in ()).throw(RuntimeError("boom"))
    main(["store", "--title", "Doc", "--content", "x", "--backends", "lark,wecom"])
    env["backends"]["wecom"].fault = None
    from kgent.router.journal import Journal
    journal = Journal(env["home"])
    op_id = journal.list_partial()[0]["op_id"]
    # First repair
    result1 = sync_repair(op_id, journal=journal, backends=env["backends"])
    assert result1.exit_code == 0
    wecom_writes_after_first = len(env["backends"]["wecom"].write_calls)
    # Second repair — should be a no-op (idempotent)
    result2 = sync_repair(op_id, journal=journal, backends=env["backends"])
    assert result2.exit_code == 0
    wecom_writes_after_second = len(env["backends"]["wecom"].write_calls)
    assert wecom_writes_after_second == wecom_writes_after_first


def test_sync_repair_unknown_op(env):
    """Repairing an unknown op_id returns exit 1."""
    from kgent.router.journal import Journal
    journal = Journal(env["home"])
    result = sync_repair("op-nonexistent", journal=journal, backends=env["backends"])
    assert result.exit_code == 1
