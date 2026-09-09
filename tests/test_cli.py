"""CLI exit-code and --json tests (§12; Task 8.1).

Each test drives ``kgent.cli.main(argv)`` in-process against fake backends
registered in the adapter registry, with an isolated ``KGENT_HOME``. The real
router/policy/journal/audit code paths are exercised — only the platform
boundary is faked (acceptance §6).
"""

# pyright: basic
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from kgent.adapters import registry
from kgent.cli import main
from kgent.config.trusted import is_trusted
from tests.fakes.fake_backend import FakeBackend

# ---------------------------------------------------------------------------
# e2e fixture (shared with later e2e tests — Task 9.4)
# ---------------------------------------------------------------------------


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
            "features": ["request_approval", "check_status", "execute_approved"],
        },
    }


@pytest.fixture
def e2e(tmp_home, monkeypatch):
    """Register fake backends in the adapter registry + write config.yaml.

    Returns the ``test_world`` dict so tests can inspect backend state.
    """
    backends = {
        "lark": FakeBackend("lark", "internal", _full_caps(), owner="alice"),
        "dingtalk": FakeBackend("dingtalk", "external", _full_caps()),
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
        "  workspace_domain: test.larksuite.com\n"
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
        "  meeting_notes: lark\n"
        "  team_wiki: lark\n"
        "  external_docs: dingtalk\n"
        "  default: lark\n"
    )
    (tmp_home / "config.yaml").write_text(config_text, encoding="utf-8")
    monkeypatch.setenv("KGENT_HOME", str(tmp_home))

    yield {"backends": backends, "home": tmp_home}

    registry.clear()


# ---------------------------------------------------------------------------
# Task 8.1 — CLI exit codes + --json
# ---------------------------------------------------------------------------


def test_cli_create_exit_0(e2e):
    code = main(["create", "--title", "Onboarding", "--content", "Welcome", "--backends", "lark"])
    assert code == 0
    assert e2e["backends"]["lark"].docs


def test_cli_search_exit_0(e2e, capsys):
    main(["create", "--title", "Meeting Notes", "--content", "Q3 plan", "--backends", "lark"])
    code = main(["search", "--query", "Q3", "--backends", "lark", "--json"])
    assert code == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert "results" in payload
    assert payload["results"][0]["doc_uri"].startswith("kgent://lark/")


def test_cli_read_exit_0(e2e):
    main(["create", "--title", "Doc", "--content", "body", "--backends", "lark"])
    uri = next(iter(e2e["backends"]["lark"].docs))
    code = main(["read", uri])
    assert code == 0


def test_cli_update_exit_0(e2e):
    main(["create", "--title", "Doc", "--content", "old", "--backends", "lark"])
    uri = next(iter(e2e["backends"]["lark"].docs))
    code = main(["update", uri, "--content", "new"])
    assert code == 0
    assert e2e["backends"]["lark"].docs[uri].content == "new"


def test_cli_delete_exit_0(e2e):
    main(["create", "--title", "Doc", "--content", "x", "--backends", "lark"])
    uri = next(iter(e2e["backends"]["lark"].docs))
    code = main(["delete", uri])
    assert code == 0


def test_cli_archive_then_unarchive(e2e):
    main(["create", "--title", "Doc", "--content", "x", "--backends", "lark"])
    uri = next(iter(e2e["backends"]["lark"].docs))
    assert main(["archive", uri]) == 0
    assert uri in e2e["backends"]["lark"].archived
    assert main(["unarchive", uri]) == 0
    assert uri in e2e["backends"]["lark"].docs


def test_cli_undo_restores_content(e2e):
    main(["create", "--title", "Doc", "--content", "before", "--backends", "lark"])
    uri = next(iter(e2e["backends"]["lark"].docs))
    main(["update", uri, "--content", "after"])
    from kgent.router.journal import Journal

    journal = Journal(e2e["home"])
    op_id = next(o["op_id"] for o in journal.list_ops() if o["operation"] == "update")
    code = main(["undo", op_id])
    assert code == 0
    assert e2e["backends"]["lark"].docs[uri].content == "before"


def test_cli_audit_writes(e2e):
    main(["create", "--title", "Doc", "--content", "x", "--backends", "lark"])
    code = main(["audit", "--op", "write", "--json"])
    assert code == 0
    audit_text = (e2e["home"] / "audit.ndjson").read_text(encoding="utf-8").strip()
    assert audit_text


def test_cli_doctor_healthy(e2e):
    code = main(["doctor"])
    assert code == 0


def test_cli_config_validate(e2e):
    code = main(["config", "validate"])
    assert code == 0


def test_cli_config_show_effective_json(e2e, capsys):
    code = main(["config", "show-effective", "--json"])
    assert code == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert "version" in payload


def test_cli_setup_read_only(e2e, monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    code = main(["setup"])
    assert code == 0


def test_cli_auth_status(e2e):
    code = main(["auth", "status"])
    assert code == 0


def test_cli_trust_then_project_config(e2e, tmp_home, tmp_path):
    proj = tmp_path / "D"
    proj.mkdir()
    (proj / ".kgent-config.yaml").write_text(
        "version: 1\ncontent_type_mapping:\n  meeting_notes: dingtalk\n",
        encoding="utf-8",
    )
    code = main(["trust", str(proj)])
    assert code == 0
    assert is_trusted(proj, tmp_home / "trusted.json")


def test_cli_store_exit_0(e2e):
    code = main(["store", "--title", "Notes", "--content", "hello", "--backends", "lark"])
    assert code == 0


def test_cli_store_update_first(e2e):
    main(["store", "--title", "API Guidelines", "--content", "v1", "--backends", "lark"])
    main(["store", "--title", "API Guidelines", "--content", "v2", "--backends", "lark"])
    lark = e2e["backends"]["lark"]
    assert lark.write_calls[-1]["method"] == "update_document"
    assert next(iter(lark.docs.values())).content == "v2"


def test_cli_store_yes_audited_with_confirmation(e2e):
    """S4: --yes write is audited with confirmation "--yes"."""
    code = main(["store", "--title", "Doc", "--content", "body", "--backends", "lark", "--yes"])
    assert code == 0
    from kgent.router.journal import Journal

    journal = Journal(e2e["home"])
    ops = journal.list_ops()
    assert ops, "expected at least one journal entry"
    assert ops[-1]["confirmation"] == "--yes"


def test_cli_store_dry_run_no_write_no_journal(e2e):
    """--dry-run: no write, no journal entry."""
    code = main(
        [
            "store",
            "--title",
            "Doc",
            "--content",
            "body",
            "--backends",
            "lark",
            "--dry-run",
        ]
    )
    assert code == 0
    assert not e2e["backends"]["lark"].docs, "--dry-run must not write"
    from kgent.router.journal import Journal

    journal = Journal(e2e["home"])
    assert journal.list_ops() == [], "--dry-run must not journal"


def test_cli_store_op_id_reuse(e2e):
    """--op-id reuses the caller-supplied op_id in the journal entry."""
    code = main(
        [
            "store",
            "--title",
            "Doc",
            "--content",
            "body",
            "--backends",
            "lark",
            "--op-id",
            "op-custom-42",
        ]
    )
    assert code == 0
    from kgent.router.journal import Journal

    journal = Journal(e2e["home"])
    ops = journal.list_ops()
    assert ops, "expected at least one journal entry"
    assert ops[-1]["op_id"] == "op-custom-42"


def test_cli_sync_repair_partial_fanout(e2e):
    e2e["backends"]["wecom"].fault = lambda m, kw: (_ for _ in ()).throw(RuntimeError("boom"))
    code = main(
        [
            "store",
            "--title",
            "Doc",
            "--content",
            "x",
            "--backends",
            "lark,wecom",
        ]
    )
    assert code == 2  # partial
    e2e["backends"]["wecom"].fault = None
    from kgent.router.journal import Journal

    journal = Journal(e2e["home"])
    op_id = journal.list_partial()[0]["op_id"]
    code = main(["sync", "--repair", op_id])
    assert code == 0


def test_cli_version_conflict_exit_4(e2e):
    """Simulate a version conflict via the concurrency check (S6, exit 4)."""
    main(["create", "--title", "Doc", "--content", "v1", "--backends", "lark"])
    uri = next(iter(e2e["backends"]["lark"].docs))
    # A real update bumps the doc version to v2
    main(["update", uri, "--content", "v1.5"])
    # Now an update with a stale expected_version should conflict (exit 4)
    code = main(["update", uri, "--content", "v2", "--expected-version", "v1"])
    assert code == 4


def test_cli_json_output_schema_versioned(e2e, capsys):
    main(["create", "--title", "Doc", "--content", "body", "--backends", "lark"])
    main(["search", "--query", "body", "--backends", "lark", "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload.get("schema_version") == 1


def test_cli_unknown_command_exit_1(capsys):
    code = main(["nonexistent-command"])
    assert code == 1


def test_cli_help_exit_0(capsys):
    # tools/install-skills.sh's pipefail'd health check greps `kgent --help`;
    # argparse raises SystemExit(0) for help, which main() must not turn into 1.
    code = main(["--help"])
    assert code == 0
    assert "wiki" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Task 3 — `kgent journal begin/end` (B2; ledger ADR 0005)
# ---------------------------------------------------------------------------


def _last_op_id(tmp_home) -> str:
    """Read the last line of the ledger and return its ``op_id``."""
    lines = [
        line
        for line in (tmp_home / "journal" / "journal.ndjson")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert lines, "expected at least one ledger entry"
    return json.loads(lines[-1])["op_id"]


def test_journal_begin_end_cli(tmp_home, capsys):
    # Ledger commands depend only on KGENT_HOME (no configured backends, no
    # config.yaml — Ruling on Task 3): tmp_home alone is enough. Note: every
    # main() call in this file puts `--json` after the subcommand — argparse
    # subparser defaults would override a leading `--json` (repo-wide).
    code = main(
        [
            "journal",
            "begin",
            "--operation",
            "update",
            "--backend",
            "lark",
            "--doc-uri",
            "kgent://lark/ABC",
            "--revision-before",
            "50",
            "--json",
        ]
    )
    assert code == 0
    begin_payload = json.loads(capsys.readouterr().out)
    assert begin_payload["schema_version"] == 1
    op_id = _last_op_id(tmp_home)
    assert begin_payload["entry"]["op_id"] == op_id

    code = main(
        ["journal", "end", "--op-id", op_id, "--status", "ok", "--revision-after", "56", "--json"]
    )
    assert code == 0
    end_payload = json.loads(capsys.readouterr().out)
    assert end_payload["operation"] == "journal-end"

    lines = (tmp_home / "journal" / "journal.ndjson").read_text(encoding="utf-8").splitlines()
    begin_entry = json.loads(lines[0])
    end_entry = json.loads(lines[1])
    assert begin_entry["kind"] == "begin"
    assert begin_entry["operation"] == "update"
    assert begin_entry["backend"] == "lark"
    assert begin_entry["target"] == "kgent://lark/ABC"
    assert begin_entry["revision_before"] == 50
    assert end_entry["op_id"] == op_id
    assert end_entry["kind"] == "end"
    assert end_entry["status"] == "ok"
    assert end_entry["revision_after"] == 56


def test_journal_begin_snapshot_content_writes_snapshot(tmp_home):
    code = main(
        [
            "journal",
            "begin",
            "--operation",
            "delete",
            "--backend",
            "wecom",
            "--doc-uri",
            "kgent://wecom/XYZ",
            "--snapshot-content",
            "body to restore",
            "--json",
        ]
    )
    assert code == 0
    from kgent.router.journal import Journal

    entry = Journal(tmp_home).entries[0]
    assert entry["snapshot"], "begin with --snapshot-content must record the snapshot path"
    assert (tmp_home / "journal" / "snapshots" / f"{entry['op_id']}.txt").read_text(
        encoding="utf-8"
    ) == "body to restore"


def test_journal_end_unknown_id_fails(tmp_home, capsys):
    code = main(
        [
            "journal",
            "end",
            "--op-id",
            "op-20260905-00000000",
            "--status",
            "ok",
            "--json",
        ]
    )
    assert code != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "failed"
    assert "op-20260905-00000000" in payload["error"]


def test_journal_end_snapshot_after_flag(tmp_home, capsys):
    """CLI：``journal end --snapshot-after`` 把写后全文原样透传并落 ``<op_id>.after.txt``。

    透传是字符串、不做 int 化（写后快照是内容全文，不是 revision——payload 刻意
    带数字与空白，``int()`` 化会当场 ValueError）；entry 的 ``snapshot_after`` 记
    文件路径，begin entry 不受影响（append-only）。
    """
    code = main(
        [
            "journal",
            "begin",
            "--operation",
            "update",
            "--backend",
            "wecom",
            "--doc-uri",
            "kgent://wecom/ABC",
            "--revision-before",
            "3",
            "--json",
        ]
    )
    assert code == 0
    op_id = json.loads(capsys.readouterr().out)["entry"]["op_id"]

    payload_text = "第 2 版全文\nsecond line\n"
    code = main(
        [
            "journal",
            "end",
            "--op-id",
            op_id,
            "--status",
            "ok",
            "--snapshot-after",
            payload_text,
            "--json",
        ]
    )
    assert code == 0
    end_payload = json.loads(capsys.readouterr().out)
    after_path = end_payload["entry"]["snapshot_after"]
    assert after_path.endswith(".after.txt")
    assert Path(after_path).read_text(encoding="utf-8") == payload_text

    from kgent.router.journal import Journal

    entries = {e["kind"]: e for e in Journal(tmp_home).entries if e["op_id"] == op_id}
    assert entries["end"]["snapshot_after"] == after_path
    assert "snapshot_after" not in entries["begin"]


# ---------------------------------------------------------------------------
# Fix round 1 — journal 的文本模式输出契约（非 --json 路径）
# ---------------------------------------------------------------------------


def test_journal_begin_text_output(tmp_home, capsys):
    """文本模式 begin → ``begin <op_id>``（scripts/终端的人读契约）。"""
    code = main(
        [
            "journal",
            "begin",
            "--operation",
            "update",
            "--backend",
            "lark",
            "--doc-uri",
            "kgent://lark/ABC",
            "--revision-before",
            "50",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert out.startswith("begin op-")
    assert out.strip() == f"begin {_last_op_id(tmp_home)}"


def test_journal_end_text_output(tmp_home, capsys):
    """文本模式 end → ``end <op_id> <status>``。"""
    main(
        [
            "journal",
            "begin",
            "--operation",
            "update",
            "--backend",
            "lark",
            "--doc-uri",
            "kgent://lark/ABC",
        ]
    )
    capsys.readouterr()
    op_id = _last_op_id(tmp_home)

    code = main(["journal", "end", "--op-id", op_id, "--status", "ok", "--revision-after", "56"])
    assert code == 0
    assert capsys.readouterr().out.strip() == f"end {op_id} ok"


def test_journal_end_unknown_id_text_output(tmp_home, capsys):
    """文本模式 end 撞未知 op id → 退出 1 并点名原因（JSON 路径的镜像）。"""
    code = main(["journal", "end", "--op-id", "op-20260905-00000000", "--status", "ok"])
    assert code == 1
    text = capsys.readouterr().out
    assert text.startswith("journal end failed:")
    assert "op-20260905-00000000" in text


# ---------------------------------------------------------------------------
# Fix round 1 — 防御分支的契约（经公共 CLI 路径不可达，直接测函数契约）
# ---------------------------------------------------------------------------


def test_journal_dispatch_without_handler_fails_closed(capsys):
    """``journal`` 子命令没有 handler → 退出 1 并说明原因。

    经 ``main()`` 不可达：argparse 对 ``journal`` 子解析器是 ``required=True``，
    缺子命令在解析期就退出（exit 2 → main 映射为 1）。这一分支防的是将来新增
    ``journal <sub>`` 子解析器时忘了 ``set_defaults(func=…)``——此时宁要一个
    明确的失败，也不要 ``None()`` 崩溃或静默成功。
    """
    from kgent.cli import _cmd_journal

    namespace = argparse.Namespace(command="journal", journal_cmd=None, json=False)
    code = _cmd_journal(namespace)
    assert code == 1
    assert capsys.readouterr().out.strip() == "unknown journal command"
