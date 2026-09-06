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
