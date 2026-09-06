"""B2: 台账生命周期 + FM1 finally + FM5 权限 + FM8 strict 读。"""
import json
import os
import stat

import pytest

from kgent.router.journal import Journal
from kgent.router.ledger import (
    INTEGRATION_SKILL_BACKENDS,
    MECHANISM_BY_BACKEND,
    LedgerError,
    begin,
    end,
)


@pytest.fixture
def journal(tmp_home):
    return Journal(tmp_home)


def test_begin_then_end_lifecycle(journal):
    entry = begin(journal, operation="update", backend="lark",
                  target_uri="kgent://lark/ABC", revision_before=50, content="A")
    assert entry["kind"] == "begin" and entry["revision_before"] == 50
    got = journal.get(entry["op_id"])
    assert got is not None and got["kind"] == "begin"
    done = end(journal, entry["op_id"], status="ok", revision_after=56)
    assert done["kind"] == "end" and done["status"] == "ok"


def test_end_without_begin_raises(journal):
    with pytest.raises(LedgerError):
        end(journal, "op-20260905-deadbeef", status="ok")


def test_end_twice_raises(journal):
    """对已 end 的 op_id 再 end → LedgerError（T2 审查 ruling：kind 校验收紧）。"""
    entry = begin(journal, operation="update", backend="lark",
                  target_uri="kgent://lark/ABC", revision_before=1)
    end(journal, entry["op_id"], status="ok", revision_after=2)
    with pytest.raises(LedgerError):
        end(journal, entry["op_id"], status="ok")


def test_same_second_begins_unique_ids(journal):
    a = begin(journal, operation="update", backend="lark",
              target_uri="kgent://lark/ABC", revision_before=1)
    b = begin(journal, operation="update", backend="lark",
              target_uri="kgent://lark/ABC", revision_before=1)
    assert a["op_id"] != b["op_id"]


def test_begin_op_id_matches_global_format(journal):
    """op_id 全局格式 ``op-<yyyymmdd>-<8hex>``（与 policy._next_op_id 一致）。"""
    entry = begin(journal, operation="update", backend="lark",
                  target_uri="kgent://lark/ABC", revision_before=1)
    assert entry["op_id"].startswith("op-")
    date, suffix = entry["op_id"][3:].split("-", 1)
    assert len(date) == 8 and date.isdigit()
    assert len(suffix) == 8 and all(c in "0123456789abcdef" for c in suffix)


def test_begin_writes_snapshot_file_0600(journal, tmp_home):
    """快照文件存在 + 内容逐字一致（FM5，全平台）；mode 断言见 ``test_begin_snapshot_file_0600_dir_0700``。"""
    entry = begin(journal, operation="update", backend="wecom",
                  target_uri="kgent://wecom/X", revision_before=3, content="秘密快照")
    snap = tmp_home / "journal" / "snapshots" / f"{entry['op_id']}.txt"
    assert snap.exists()
    assert snap.read_text(encoding="utf-8") == "秘密快照"


def test_begin_writes_snapshot_content_verbatim(journal, tmp_home):
    """快照内容逐字落盘（含换行/中文）；Windows 也断言存在 + 内容一致（FM5）。"""
    payload = "第一行\nsecond line\twith tabs\n"
    entry = begin(journal, operation="update", backend="wecom",
                  target_uri="kgent://wecom/X", revision_before=3, content=payload)
    snap = tmp_home / "journal" / "snapshots" / f"{entry['op_id']}.txt"
    assert snap.exists()
    assert snap.read_text(encoding="utf-8") == payload


def test_begin_without_content_writes_no_snapshot(journal, tmp_home):
    entry = begin(journal, operation="update", backend="lark",
                  target_uri="kgent://lark/ABC", revision_before=1)
    assert "snapshot" not in entry
    assert not (tmp_home / "journal" / "snapshots").exists()


def test_end_records_revision_after_only_when_given(journal):
    entry = begin(journal, operation="update", backend="lark",
                  target_uri="kgent://lark/ABC", revision_before=1)
    done = end(journal, entry["op_id"], status="failed")
    assert done["kind"] == "end" and done["status"] == "failed"
    assert "revision_after" not in done


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are not representable on Windows")
def test_begin_snapshot_file_0600_dir_0700(journal, tmp_home):
    """快照文件 0600 + 所在 snapshots 目录 0700（FM5）；POSIX 上才可断言 mode 位。

    Windows 侧由 ``test_begin_writes_snapshot_file_0600`` 断言存在 + 内容一致。
    """
    entry = begin(journal, operation="update", backend="wecom",
                  target_uri="kgent://wecom/X", revision_before=3, content="秘密快照")
    snap = tmp_home / "journal" / "snapshots" / f"{entry['op_id']}.txt"
    assert stat.S_IMODE(snap.stat().st_mode) == 0o600
    assert stat.S_IMODE(snap.parent.stat().st_mode) == 0o700


def test_strict_load_raises_on_corrupt_line(tmp_home):
    jdir = tmp_home / "journal"
    jdir.mkdir(parents=True)
    (jdir / "journal.ndjson").write_text('{"op_id": "op-1"}\n{broken json\n', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        Journal(tmp_home, strict_load=True)


def test_lenient_load_still_skips_corrupt_line(tmp_home):
    """默认 lenient（既有行为不变）：坏行跳过，好行照常入索引（FM8）。"""
    jdir = tmp_home / "journal"
    jdir.mkdir(parents=True)
    (jdir / "journal.ndjson").write_text('{"op_id": "op-1"}\n{broken json\n', encoding="utf-8")
    journal = Journal(tmp_home)
    assert journal.get("op-1") is not None
    assert len(journal.entries) == 1


def test_mechanism_map_covers_integration_backends():
    assert set(MECHANISM_BY_BACKEND) == INTEGRATION_SKILL_BACKENDS


# ---------------------------------------------------------------------------
# I3/I5（final review）：audit 是台账的读视图；台账读 fail closed（FM8）
# ---------------------------------------------------------------------------


def _write_corrupt_line(tmp_home) -> None:
    jdir = tmp_home / "journal"
    jdir.mkdir(parents=True, exist_ok=True)
    with (jdir / "journal.ndjson").open("a", encoding="utf-8") as fh:
        fh.write('{"op_id": "op-1"}\n{broken json\n')


def test_audit_reads_ledger_lifecycle_json(tmp_home, capsys):
    """audit 的 JSON 模式给结构化 ``ledger``：begin/end 生命周期 + dangling begin。"""
    from kgent.cli import main
    from kgent.router.ledger import begin, end

    journal = Journal(tmp_home)
    closed = begin(journal, operation="update", backend="lark",
                   target_uri="kgent://lark/ABC", revision_before=50)
    end(journal, closed["op_id"], status="ok", revision_after=56)
    dangling = begin(journal, operation="create", backend="lark",
                     target_uri="kgent://lark/planned", revision_before=None)

    code = main(["audit", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    by_op = {r["op_id"]: r for r in payload["ledger"]}
    assert by_op[closed["op_id"]]["status"] == "ok"
    assert by_op[closed["op_id"]]["end_ts"] is not None
    assert by_op[dangling["op_id"]]["status"] == "open"  # 有 begin 无 end
    assert by_op[dangling["op_id"]]["end_ts"] is None


def test_audit_text_output_ledger_lines(tmp_home, capsys):
    """文本模式：可读行 ``ledger <op_id> <operation> <backend> <target> <status>``；
    dangling begin 显式标注。"""
    from kgent.cli import main
    from kgent.router.ledger import begin, end

    journal = Journal(tmp_home)
    closed = begin(journal, operation="update", backend="lark",
                   target_uri="kgent://lark/ABC", revision_before=50)
    end(journal, closed["op_id"], status="ok", revision_after=56)
    dangling = begin(journal, operation="create", backend="lark",
                     target_uri="kgent://lark/planned", revision_before=None)

    code = main(["audit"])
    text = capsys.readouterr().out
    assert code == 0
    assert f"ledger {closed['op_id']} update lark kgent://lark/ABC ok" in text
    assert f"ledger {dangling['op_id']} create lark kgent://lark/planned open" in text
    assert "dangling begin" in text


def test_audit_ledger_end_without_begin_recorded(tmp_home, capsys):
    """end 无 begin（手改台账才会出现）→ 也照录，operation/target 缺席。"""
    from kgent.cli import main

    journal = Journal(tmp_home)
    journal.append({"op_id": "op-20260906-orphan1", "kind": "end",
                    "ts": "2026-09-06T00:00:00+00:00", "status": "ok"})

    code = main(["audit", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["ledger"] == [
        {
            "op_id": "op-20260906-orphan1",
            "operation": None,
            "backend": None,
            "target": None,
            "ts": None,
            "status": "ok",
            "end_ts": "2026-09-06T00:00:00+00:00",
        }
    ]


def test_audit_op_filter_applies_to_ledger(tmp_home, capsys):
    """``--op`` 过滤同时作用于台账视图（按 operation 字段）。"""
    from kgent.cli import main
    from kgent.router.ledger import begin

    journal = Journal(tmp_home)
    begin(journal, operation="create", backend="lark",
          target_uri="kgent://lark/A", revision_before=None)
    begin(journal, operation="update", backend="lark",
          target_uri="kgent://lark/B", revision_before=1)

    code = main(["audit", "--op", "create", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert [r["operation"] for r in payload["ledger"]] == ["create"]


def test_audit_empty_home_zero_exit(tmp_home, capsys):
    """无 audit.ndjson 也无台账 → 两侧空、exit 0（既有空态语义保留）。"""
    from kgent.cli import main

    assert main(["audit", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["entries"] == []
    assert payload["ledger"] == []

    assert main(["audit"]) == 0
    assert capsys.readouterr().out.strip() == "no audit log"


def test_audit_corrupt_ledger_fails_closed(tmp_home, capsys):
    """FM8：台账损坏行 → audit 硬失败 exit 1，不静默吞半本台账。"""
    from kgent.cli import main

    _write_corrupt_line(tmp_home)
    code = main(["audit", "--json"])
    out = capsys.readouterr().out
    assert code == 1
    assert "corrupt" in out


def test_undo_corrupt_ledger_fails_closed(tmp_home, capsys):
    """FM8：台账损坏行 → undo 在台账分流这步硬失败 exit 1（legacy 路径不再被走到）。"""
    from kgent.cli import main

    (tmp_home / "config.yaml").write_text(
        "version: 1\n"
        "defaults:\n"
        "  routing_mode: configured\n"
        "  default_backends: [lark]\n"
        "backends:\n"
        "  lark:\n"
        "    enabled: true\n"
        "    type: skill\n"
        "    skill_name: lark-doc\n"
        "    trust_zone: internal\n",
        encoding="utf-8",
    )
    _write_corrupt_line(tmp_home)
    code = main(["undo", "op-1", "--json"])
    out = capsys.readouterr().out
    assert code == 1
    assert "corrupt" in out


def test_end_records_doc_uri_only_when_given(journal):
    """``end(doc_uri=...)``：给了才落字段（C1 回填通道；不给不落，兼容旧形态）。"""
    entry = begin(journal, operation="create", backend="lark",
                  target_uri="kgent://lark/planned", revision_before=None)
    done = end(journal, entry["op_id"], status="ok", doc_uri="kgent://lark/REAL1")
    assert done["doc_uri"] == "kgent://lark/REAL1"
    plain = begin(journal, operation="create", backend="lark",
                  target_uri="kgent://lark/planned2", revision_before=None)
    done2 = end(journal, plain["op_id"], status="ok")
    assert "doc_uri" not in done2


def test_audit_skips_blank_lines_in_audit_ndjson(tmp_home, capsys):
    """audit.ndjson 里的空行跳过、好行照常解析（既有宽容语义不变）。"""
    from kgent.cli import main

    (tmp_home / "audit.ndjson").write_text(
        '\n{"op_id": "op-1", "operation": "create"}\n\n',
        encoding="utf-8",
    )
    code = main(["audit", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert [e["op_id"] for e in payload["entries"]] == ["op-1"]
    assert payload["ledger"] == []


def test_audit_skips_corrupt_line_in_audit_ndjson(tmp_home, capsys):
    """audit.ndjson 损坏行跳过（宽容面在 audit 文件侧保留；台账侧才是 strict）。"""
    from kgent.cli import main

    (tmp_home / "audit.ndjson").write_text(
        '{"op_id": "op-1", "operation": "create"}\n{broken json\n',
        encoding="utf-8",
    )
    code = main(["audit", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert [e["op_id"] for e in payload["entries"]] == ["op-1"]


def test_audit_ledger_entry_without_op_id_skipped(tmp_home, capsys):
    """台账 entry 没有 string op_id（形态漂移）→ 不进生命周期视图，不炸。"""
    from kgent.cli import main
    from kgent.router.ledger import begin

    journal = Journal(tmp_home)
    journal.append({"kind": "begin", "ts": "2026-09-06T00:00:00+00:00"})  # 无 op_id
    begin(journal, operation="update", backend="lark",
          target_uri="kgent://lark/ABC", revision_before=1)

    code = main(["audit", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert [r["target"] for r in payload["ledger"]] == ["kgent://lark/ABC"]
