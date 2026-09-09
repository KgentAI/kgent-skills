"""B3/B5 计划生成：机制映射 + 新鲜度拒绝（FM2/FM3）+ create 计划。

ADR 0005：undo 对台账登记过的 op（``kind == "begin"``）只产补偿计划，执行归
integration skill；legacy 写 entry（``build_entry`` 形态）仍走既有 best-effort
``journal.undo``（B12 基线不变量）。``begin``/``end`` 两条 entry 在
``compensation_plan`` 里合并成一个 op 视图（``Journal.get`` 只返回最新一条）。
"""

# pyright: basic
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from kgent.adapters import registry
from kgent.cli import main
from kgent.router.journal import Journal
from kgent.router.ledger import LedgerError, begin, compensation_plan, end
from kgent.types import Document, DocumentMetadata
from tests.conftest import _full_caps
from tests.fakes.fake_backend import FakeBackend


def _doc(uri: str, version: int | str, content: str = "A") -> Document:
    """照 ``FakeBackend.create_document`` 的构造方式（Document + metadata sidecar）。

    直接种入固定 uri/version，绕过 ``_bump`` 的自增计数。
    """
    return Document(
        doc_uri=uri,
        title="Probe",
        content=content,
        metadata=DocumentMetadata(doc_uri=uri, title="Probe", backend="lark", version=version),
    )


def _set_version(fb: FakeBackend, uri: str, version: int | str) -> None:
    """``Document``/``DocumentMetadata`` 都是 frozen dataclass → 用 ``replace``。"""
    doc = fb.docs[uri]
    fb.docs[uri] = replace(doc, metadata=replace(doc.metadata, version=version))


def _set_content(fb: FakeBackend, uri: str, content: str) -> None:
    doc = fb.docs[uri]
    fb.docs[uri] = replace(doc, content=content)


# ---------------------------------------------------------------------------
# compensation_plan：update / 机制映射 / FM2 新鲜度
# ---------------------------------------------------------------------------


@pytest.fixture
def lark_backend(tmp_home):
    fb = FakeBackend(name="lark", trust_zone="internal", capabilities=_full_caps())
    fb.docs["kgent://lark/DOC1"] = _doc("kgent://lark/DOC1", 56)
    return fb


def test_plan_mechanism_history_revert(lark_backend, tmp_home):
    journal = Journal(tmp_home)
    entry = begin(
        journal,
        operation="update",
        backend="lark",
        target_uri="kgent://lark/DOC1",
        revision_before=50,
    )
    end(journal, entry["op_id"], status="ok", revision_after=56)
    plan = compensation_plan(entry["op_id"], backends={"lark": lark_backend}, journal=journal)
    assert plan["status"] == "ok"
    assert plan["operation"] == "undo"
    assert plan["mode"] == "plan"
    assert plan["op_id"] == entry["op_id"]
    assert plan["integration_skill"] == "lark-integration"
    assert plan["plan"]["mechanism"] == "history-revert"
    assert plan["plan"]["backend"] == "lark"
    assert plan["plan"]["target"] == "kgent://lark/DOC1"
    assert plan["plan"]["operation"] == "update"
    assert plan["plan"]["revision_before"] == 50
    assert plan["plan"]["revision_after"] == 56
    assert plan["plan"]["revision_current"] == 56
    assert plan["plan"]["snapshot"] is None
    # Task 10 的 Undo Compensation 流程第一步就吃这个提示
    assert (
        plan["plan"]["history_hint"] == "docs +history-list → history_version_id(revision_before)"
    )
    assert "reason" not in plan


def test_plan_rejected_when_edited_since(lark_backend, tmp_home):
    journal = Journal(tmp_home)
    entry = begin(
        journal,
        operation="update",
        backend="lark",
        target_uri="kgent://lark/DOC1",
        revision_before=50,
    )
    end(journal, entry["op_id"], status="ok", revision_after=56)
    _set_version(lark_backend, "kgent://lark/DOC1", 57)  # 他人并发编辑
    plan = compensation_plan(entry["op_id"], backends={"lark": lark_backend}, journal=journal)
    assert plan["status"] == "rejected"
    assert plan["mode"] == "plan"
    assert "57" in plan["reason"]
    assert "56" in plan["reason"]  # FM2: reason 指明两侧 revision


def test_plan_rejects_version_string_vs_int_mismatch(lark_backend, tmp_home):
    """Lark 的 version 是字符串 revision_id，台账里是 int → 统一字符串化比较。"""
    journal = Journal(tmp_home)
    entry = begin(
        journal,
        operation="update",
        backend="lark",
        target_uri="kgent://lark/DOC1",
        revision_before="50",
    )
    end(journal, entry["op_id"], status="ok", revision_after="56")
    _set_version(lark_backend, "kgent://lark/DOC1", 56)  # int 56 == str "56"
    plan = compensation_plan(entry["op_id"], backends={"lark": lark_backend}, journal=journal)
    assert plan["status"] == "ok"
    assert plan["plan"]["revision_current"] == 56


def test_plan_dingtalk_mechanism_version_revert(tmp_home):
    fb = FakeBackend(name="dingtalk", trust_zone="external", capabilities=_full_caps())
    fb.docs["kgent://dingtalk/D1"] = _doc("kgent://dingtalk/D1", 3)
    journal = Journal(tmp_home)
    entry = begin(
        journal,
        operation="update",
        backend="dingtalk",
        target_uri="kgent://dingtalk/D1",
        revision_before=2,
    )
    end(journal, entry["op_id"], status="ok", revision_after=3)
    plan = compensation_plan(entry["op_id"], backends={"dingtalk": fb}, journal=journal)
    assert plan["status"] == "ok"
    assert plan["plan"]["mechanism"] == "version-revert"
    assert plan["integration_skill"] == "dingtalk-integration"
    assert plan["plan"]["history_hint"] == "dws doc +version-list"


def test_plan_unknown_backend_rejected(tmp_home):
    """没有补偿机制的后端 → fail closed 拒绝，不产可执行计划。"""
    fb = FakeBackend(name="gdoc", trust_zone="internal", capabilities=_full_caps())
    fb.docs["kgent://gdoc/G1"] = _doc("kgent://gdoc/G1", 1)
    journal = Journal(tmp_home)
    entry = begin(
        journal, operation="update", backend="gdoc", target_uri="kgent://gdoc/G1", revision_before=1
    )
    plan = compensation_plan(entry["op_id"], backends={"gdoc": fb}, journal=journal)
    assert plan["status"] == "rejected"
    assert plan["plan"]["mechanism"] is None


# ---------------------------------------------------------------------------
# B4 计划层：create → 补偿是删除
# ---------------------------------------------------------------------------


def test_plan_create_delete(tmp_home):
    fb = FakeBackend(name="lark", trust_zone="internal", capabilities=_full_caps())
    fb.docs["kgent://lark/NEW1"] = _doc("kgent://lark/NEW1", 1)
    journal = Journal(tmp_home)
    entry = begin(
        journal,
        operation="create",
        backend="lark",
        target_uri="kgent://lark/NEW1",
        revision_before=None,
    )
    end(journal, entry["op_id"], status="ok")
    plan = compensation_plan(entry["op_id"], backends={"lark": fb}, journal=journal)
    assert plan["status"] == "ok"
    assert plan["plan"]["operation"] == "create"
    assert plan["plan"]["mechanism"] == "history-revert"
    # create 补偿走删除，不查平台 history → 提示为空
    assert plan["plan"]["history_hint"] is None


def test_plan_create_already_deleted_is_still_ok(tmp_home):
    """B4：已删除 → 幂等成功，计划仍为 ok（revision_current 缺席）。"""
    journal = Journal(tmp_home)
    entry = begin(
        journal,
        operation="create",
        backend="lark",
        target_uri="kgent://lark/GONE",
        revision_before=None,
    )
    end(journal, entry["op_id"], status="ok")
    plan = compensation_plan(
        entry["op_id"],
        backends={
            "lark": FakeBackend(name="lark", trust_zone="internal", capabilities=_full_caps())
        },
        journal=journal,
    )
    assert plan["status"] == "ok"
    assert plan["plan"]["revision_current"] is None


# ---------------------------------------------------------------------------
# FM3：无 revision_after 的 entry → 快照内容比对（wecom 路径）
# ---------------------------------------------------------------------------


@pytest.fixture
def wecom_backend(tmp_home):
    fb = FakeBackend(name="wecom", trust_zone="external", capabilities=_full_caps())
    fb.docs["kgent://wecom/W1"] = _doc("kgent://wecom/W1", 8, content="A")
    return fb


def test_plan_wecom_snapshot_restore_ok(wecom_backend, tmp_home):
    journal = Journal(tmp_home)
    entry = begin(
        journal,
        operation="update",
        backend="wecom",
        target_uri="kgent://wecom/W1",
        revision_before=7,
        content="A",
    )
    end(journal, entry["op_id"], status="ok")  # 无 revision_after → 快照比对
    plan = compensation_plan(entry["op_id"], backends={"wecom": wecom_backend}, journal=journal)
    assert plan["status"] == "ok"
    assert plan["plan"]["mechanism"] == "snapshot-restore"
    assert plan["plan"]["snapshot"] == entry["snapshot"]
    assert plan["plan"]["revision_after"] is None
    assert plan["plan"]["history_hint"] is None  # wecom 无平台 history
    assert plan["integration_skill"] == "wecom-integration"


def test_plan_wecom_rejected_when_content_changed_since(wecom_backend, tmp_home):
    """FM3：快照之后内容被第三方改过 → 拒绝，reason 指明当前 revision。"""
    journal = Journal(tmp_home)
    entry = begin(
        journal,
        operation="update",
        backend="wecom",
        target_uri="kgent://wecom/W1",
        revision_before=7,
        content="A",
    )
    end(journal, entry["op_id"], status="ok")
    _set_content(wecom_backend, "kgent://wecom/W1", "C")
    plan = compensation_plan(entry["op_id"], backends={"wecom": wecom_backend}, journal=journal)
    assert plan["status"] == "rejected"
    assert "8" in plan["reason"]  # 当前 revision 指明在 reason 里


def test_plan_update_without_revision_or_snapshot_rejected(tmp_home):
    """既无 revision_after 也无快照 → 无新鲜度证据，拒绝盲回滚（FM2 哲学）。"""
    fb = FakeBackend(name="lark", trust_zone="internal", capabilities=_full_caps())
    fb.docs["kgent://lark/DOC1"] = _doc("kgent://lark/DOC1", 56)
    journal = Journal(tmp_home)
    entry = begin(
        journal,
        operation="update",
        backend="lark",
        target_uri="kgent://lark/DOC1",
        revision_before=50,
    )
    end(journal, entry["op_id"], status="ok")
    plan = compensation_plan(entry["op_id"], backends={"lark": fb}, journal=journal)
    assert plan["status"] == "rejected"


# ---------------------------------------------------------------------------
# legacy 写 entry（build_entry 形态）也要认——CLI 分流依赖这一前提
# ---------------------------------------------------------------------------


def test_plan_accepts_legacy_write_entry(tmp_home):
    """legacy 写 entry：无 kind、backend 靠 targets[0] parse_uri、version_after 在快照里。"""
    fb = FakeBackend(name="lark", trust_zone="internal", capabilities=_full_caps())
    fb.docs["kgent://lark/DOC1"] = _doc("kgent://lark/DOC1", 5)
    journal = Journal(tmp_home)
    legacy = {
        "schema_version": 1,
        "op_id": "op-20260905-legacy01",
        "ts": "2026-09-05T00:00:00+00:00",
        "operation": "update",
        "targets": ["kgent://lark/DOC1"],
        "idempotency_key": "op-20260905-legacy01",
        "snapshot": {"content_before": "A", "version_after": "5"},
        "proposal_hash": "",
        "confirmation": "--yes",
        "sensitivity": "internal",
        "status": "ok",
    }
    journal.append(legacy)
    plan = compensation_plan(legacy["op_id"], backends={"lark": fb}, journal=journal)
    assert plan["status"] == "ok"
    assert plan["plan"]["backend"] == "lark"  # 来自 parse_uri，不是 entry["backend"]
    assert plan["plan"]["operation"] == "update"
    assert plan["plan"]["revision_after"] == "5"
    assert plan["plan"]["revision_current"] == 5


def test_plan_unknown_op_id_raises(tmp_home):
    """未知 op_id → LedgerError（fail closed，与 ``end()`` 同约定）。"""
    journal = Journal(tmp_home)
    with pytest.raises(LedgerError):
        compensation_plan("op-20260905-nothing", backends={}, journal=journal)


# ---------------------------------------------------------------------------
# CLI 分流：台账 op → 计划；legacy 写 entry → 既有 journal_undo（B12）
# ---------------------------------------------------------------------------


CONFIG_TEXT = (
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
    "  gdoc:\n"
    "    enabled: true\n"
    "    type: cli\n"
    "    cli_name: gdoc-cli\n"
    "    trust_zone: internal\n"
    "content_type_mapping:\n"
    "  default: lark\n"
)


@pytest.fixture
def undo_world(tmp_home):
    """lark（integration 后端）+ gdoc（非 integration）注册进 registry + config.yaml。"""
    lark = FakeBackend(name="lark", trust_zone="internal", capabilities=_full_caps())
    gdoc = FakeBackend(name="gdoc", trust_zone="internal", capabilities=_full_caps())
    registry.register("lark", lark)
    registry.register("gdoc", gdoc)
    (tmp_home / "config.yaml").write_text(CONFIG_TEXT, encoding="utf-8")
    yield {"lark": lark, "gdoc": gdoc, "home": tmp_home}
    registry.clear()


def test_undo_cli_ledger_op_outputs_plan(undo_world, capsys):
    fb = undo_world["lark"]
    fb.docs["kgent://lark/DOC1"] = _doc("kgent://lark/DOC1", 56)
    journal = Journal(undo_world["home"])
    entry = begin(
        journal,
        operation="update",
        backend="lark",
        target_uri="kgent://lark/DOC1",
        revision_before=50,
    )
    end(journal, entry["op_id"], status="ok", revision_after=56)

    code = main(["undo", entry["op_id"], "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["mode"] == "plan"
    assert out["status"] == "ok"
    assert out["plan"]["mechanism"] == "history-revert"
    # 只产计划：不真的改写文档
    assert fb.write_calls == []
    assert fb.docs["kgent://lark/DOC1"].content == "A"


def test_undo_cli_ledger_op_rejected_exits_1(undo_world, capsys):
    fb = undo_world["lark"]
    fb.docs["kgent://lark/DOC1"] = _doc("kgent://lark/DOC1", 56)
    journal = Journal(undo_world["home"])
    entry = begin(
        journal,
        operation="update",
        backend="lark",
        target_uri="kgent://lark/DOC1",
        revision_before=50,
    )
    end(journal, entry["op_id"], status="ok", revision_after=56)
    _set_version(fb, "kgent://lark/DOC1", 57)

    code = main(["undo", entry["op_id"], "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 1
    assert out["status"] == "rejected"
    assert "57" in out["reason"]


def test_undo_cli_ledger_op_text_output(undo_world, capsys):
    fb = undo_world["lark"]
    fb.docs["kgent://lark/DOC1"] = _doc("kgent://lark/DOC1", 56)
    journal = Journal(undo_world["home"])
    entry = begin(
        journal,
        operation="update",
        backend="lark",
        target_uri="kgent://lark/DOC1",
        revision_before=50,
    )
    end(journal, entry["op_id"], status="ok", revision_after=56)

    code = main(["undo", entry["op_id"]])
    text = capsys.readouterr().out
    assert code == 0
    assert "ok" in text and "history-revert" in text and "lark-integration" in text


def test_undo_cli_legacy_lark_write_still_restores(undo_world, capsys):
    """B12：legacy 写 entry 即使在 integration 后端上也走既有 journal_undo。"""
    lark = undo_world["lark"]
    assert main(["create", "--title", "Doc", "--content", "before", "--backends", "lark"]) == 0
    uri = next(iter(lark.docs))
    assert main(["update", uri, "--content", "after"]) == 0
    journal = Journal(undo_world["home"])
    op_id = next(o["op_id"] for o in journal.list_ops() if o["operation"] == "update")

    code = main(["undo", op_id])
    assert code == 0
    assert lark.docs[uri].content == "before"  # 真的回滚了，不是只产计划
    assert capsys.readouterr().out == ""


def test_undo_cli_legacy_non_integration_backend_restores(undo_world):
    """非 integration 后端的 legacy 写 entry → 既有 undo 路径原样保留。"""
    gdoc = undo_world["gdoc"]
    assert main(["create", "--title", "Doc", "--content", "before", "--backends", "gdoc"]) == 0
    uri = next(iter(gdoc.docs))
    assert main(["update", uri, "--content", "after"]) == 0
    journal = Journal(undo_world["home"])
    op_id = next(o["op_id"] for o in journal.list_ops() if o["operation"] == "update")

    assert main(["undo", op_id]) == 0
    assert gdoc.docs[uri].content == "before"


def test_undo_cli_unknown_op_id_still_fails(undo_world):
    """未知 op_id 不进计划分支，沿用既有 undo 的失败语义（exit 1）。"""
    assert main(["undo", "op-20260905-missing0", "--json"]) == 1


# ---------------------------------------------------------------------------
# Fix round 1 — 变更行缺口：这些分支各自钉住一个真实契约（非摸行）
# ---------------------------------------------------------------------------


def test_plan_ignores_other_ops_entries(lark_backend, tmp_home):
    """多 op 台账：A 的计划只认 A 的 begin/end，B 的 begin/end 不串味。

    真实台账一天几十个 op 交错落盘；把 B 的 revision_after 记到 A 头上就是
    错误的新鲜度判定（要么误拒、要么误放行）。
    """
    lark_backend.docs["kgent://lark/DOC2"] = _doc("kgent://lark/DOC2", 10)
    journal = Journal(tmp_home)
    a = begin(
        journal,
        operation="update",
        backend="lark",
        target_uri="kgent://lark/DOC1",
        revision_before=50,
    )
    b = begin(
        journal,
        operation="update",
        backend="lark",
        target_uri="kgent://lark/DOC2",
        revision_before=9,
    )
    end(journal, b["op_id"], status="ok", revision_after=999)  # 故意穿插
    end(journal, a["op_id"], status="ok", revision_after=56)

    plan = compensation_plan(a["op_id"], backends={"lark": lark_backend}, journal=journal)
    assert plan["status"] == "ok"
    assert plan["plan"]["revision_after"] == 56  # 不是 B 的 999
    assert plan["plan"]["revision_before"] == 50
    assert plan["plan"]["target"] == "kgent://lark/DOC1"


def test_plan_legacy_entry_bad_target_uri_fails_closed(tmp_home):
    """legacy entry 的 target 不是 canonical URI → backend None → 拒绝。

    解析失败绝不能让计划落到「某个猜测的后端」上；fail closed 才守得住
    「绝不盲回滚」。
    """
    journal = Journal(tmp_home)
    journal.append(
        {
            "schema_version": 1,
            "op_id": "op-20260906-baduri01",
            "ts": "2026-09-06T00:00:00+00:00",
            "operation": "update",
            "targets": ["not-a-canonical-uri"],
            "idempotency_key": "op-20260906-baduri01",
            "snapshot": {"content_before": "A", "version_after": "5"},
            "confirmation": "--yes",
            "sensitivity": "internal",
            "status": "ok",
        }
    )
    plan = compensation_plan("op-20260906-baduri01", backends={}, journal=journal)
    assert plan["status"] == "rejected"
    assert plan["plan"]["backend"] is None
    assert plan["plan"]["mechanism"] is None
    assert "no compensation mechanism" in plan["reason"]


def test_plan_entry_without_target_or_backend_rejected(tmp_home):
    """既无 target 也无 backend 的 begin entry → 定位不到补偿对象，拒绝。

    entry 形态漂移（字段改名/丢失）时宁可拒绝，也不能规划一次无处落笔的补偿。
    """
    journal = Journal(tmp_home)
    journal.append(
        {
            "schema_version": 1,
            "op_id": "op-20260906-notarget01",
            "kind": "begin",
            "ts": "2026-09-06T00:00:00+00:00",
            "operation": "update",
        }
    )
    plan = compensation_plan("op-20260906-notarget01", backends={}, journal=journal)
    assert plan["status"] == "rejected"
    assert plan["plan"]["target"] is None
    assert plan["plan"]["mechanism"] is None
    assert "no compensation mechanism" in plan["reason"]


def test_plan_legacy_nested_snapshot_version_after(lark_backend, tmp_home):
    """多 target 快照形态（snapshot["targets"][uri]["version_after"]）也喂 FM2。

    journal 对多 target 写入就是用嵌套形态落盘的（journal._version_after_by_uri），
    这类 entry 的 freshness 必须同样比对 revision。
    """
    lark_backend.docs["kgent://lark/DOC1"] = _doc("kgent://lark/DOC1", 9)
    journal = Journal(tmp_home)
    journal.append(
        {
            "schema_version": 1,
            "op_id": "op-20260906-nestva01",
            "ts": "2026-09-06T00:00:00+00:00",
            "operation": "update",
            "targets": ["kgent://lark/DOC1"],
            "idempotency_key": "op-20260906-nestva01",
            "snapshot": {"targets": {"kgent://lark/DOC1": {"version_after": "9"}}},
            "confirmation": "--yes",
            "sensitivity": "internal",
            "status": "ok",
        }
    )
    plan = compensation_plan(
        "op-20260906-nestva01", backends={"lark": lark_backend}, journal=journal
    )
    assert plan["status"] == "ok"
    assert plan["plan"]["revision_after"] == "9"
    assert plan["plan"]["revision_current"] == 9


def test_plan_legacy_nested_snapshot_content_before(lark_backend, tmp_home):
    """嵌套形态只有 content_before（无 version_after）→ FM3 内容比对。"""
    lark_backend.docs["kgent://lark/DOC1"] = _doc("kgent://lark/DOC1", 9, content="A")
    journal = Journal(tmp_home)
    journal.append(
        {
            "schema_version": 1,
            "op_id": "op-20260906-nestcb01",
            "ts": "2026-09-06T00:00:00+00:00",
            "operation": "update",
            "targets": ["kgent://lark/DOC1"],
            "idempotency_key": "op-20260906-nestcb01",
            "snapshot": {"targets": {"kgent://lark/DOC1": {"content_before": "A"}}},
            "confirmation": "--yes",
            "sensitivity": "internal",
            "status": "ok",
        }
    )
    ok = compensation_plan("op-20260906-nestcb01", backends={"lark": lark_backend}, journal=journal)
    assert ok["status"] == "ok"

    _set_content(lark_backend, "kgent://lark/DOC1", "B")
    drifted = compensation_plan(
        "op-20260906-nestcb01", backends={"lark": lark_backend}, journal=journal
    )
    assert drifted["status"] == "rejected"
    assert "snapshot no longer matches" in drifted["reason"]


def test_plan_legacy_nested_snapshot_missing_target_rejected(tmp_home):
    """嵌套快照里没有该 target 的键 → 无内容证据，拒绝（不是 ok）。"""
    journal = Journal(tmp_home)
    journal.append(
        {
            "schema_version": 1,
            "op_id": "op-20260906-nestothers01",
            "ts": "2026-09-06T00:00:00+00:00",
            "operation": "update",
            "targets": ["kgent://lark/DOC1"],
            "idempotency_key": "op-20260906-nestothers01",
            "snapshot": {"targets": {"kgent://lark/OTHER": {"content_before": "A"}}},
            "confirmation": "--yes",
            "sensitivity": "internal",
            "status": "ok",
        }
    )
    plan = compensation_plan("op-20260906-nestothers01", backends={}, journal=journal)
    assert plan["status"] == "rejected"
    assert "no snapshot content available" in plan["reason"]


def test_plan_legacy_flat_snapshot_content_before(wecom_backend, tmp_home):
    """单 target 快照的扁平形态（snapshot["content_before"]）→ FM3 内容比对。

    journal.build_entry 对单 target 写入落的就是扁平形态——这是 legacy entry 的
    主形态，不是边角。
    """
    journal = Journal(tmp_home)
    journal.append(
        {
            "schema_version": 1,
            "op_id": "op-20260906-flatcb01",
            "ts": "2026-09-06T00:00:00+00:00",
            "operation": "update",
            "targets": ["kgent://wecom/W1"],
            "idempotency_key": "op-20260906-flatcb01",
            "snapshot": {"content_before": "A"},
            "confirmation": "--yes",
            "sensitivity": "internal",
            "status": "ok",
        }
    )
    ok = compensation_plan(
        "op-20260906-flatcb01", backends={"wecom": wecom_backend}, journal=journal
    )
    assert ok["status"] == "ok"
    assert ok["plan"]["mechanism"] == "snapshot-restore"

    _set_content(wecom_backend, "kgent://wecom/W1", "C")
    drifted = compensation_plan(
        "op-20260906-flatcb01", backends={"wecom": wecom_backend}, journal=journal
    )
    assert drifted["status"] == "rejected"


def test_plan_legacy_empty_snapshot_rejected(tmp_home):
    """空 snapshot dict：既无 version_after 也无 content_before → 拒绝盲回滚。"""
    journal = Journal(tmp_home)
    journal.append(
        {
            "schema_version": 1,
            "op_id": "op-20260906-emptysnap01",
            "ts": "2026-09-06T00:00:00+00:00",
            "operation": "update",
            "targets": ["kgent://lark/DOC1"],
            "idempotency_key": "op-20260906-emptysnap01",
            "snapshot": {},
            "confirmation": "--yes",
            "sensitivity": "internal",
            "status": "ok",
        }
    )
    plan = compensation_plan("op-20260906-emptysnap01", backends={}, journal=journal)
    assert plan["status"] == "rejected"
    assert "cannot verify freshness" in plan["reason"]


def test_plan_snapshot_file_lost_rejected(wecom_backend, tmp_home):
    """台账内容快照文件丢失（清理/搬运）→ 无新鲜度证据，拒绝盲回滚。

    FM5 快照是明文落盘的已知限制；它一旦不可读，plan 必须拒，而不是当它不存在。
    """
    journal = Journal(tmp_home)
    entry = begin(
        journal,
        operation="update",
        backend="wecom",
        target_uri="kgent://wecom/W1",
        revision_before=7,
        content="A",
    )
    end(journal, entry["op_id"], status="ok")  # 无 revision_after → 只能靠快照文件
    Path(entry["snapshot"]).unlink()

    plan = compensation_plan(entry["op_id"], backends={"wecom": wecom_backend}, journal=journal)
    assert plan["status"] == "rejected"
    assert "no snapshot content available" in plan["reason"]


def test_plan_create_already_deleted_is_idempotent_ok(tmp_home):
    """B4：create 的补偿是删除；文档已不在 → 幂等 ok（即使带着 revision 证据）。

    与「带 revision_after 的 update 撞上文档消失要拒绝」相对：create 撞上消失是
    期待结局，不是新鲜度疑点。
    """
    journal = Journal(tmp_home)
    entry = begin(
        journal,
        operation="create",
        backend="lark",
        target_uri="kgent://lark/GONE",
        revision_before=None,
    )
    end(journal, entry["op_id"], status="ok", revision_after=5)
    plan = compensation_plan(
        entry["op_id"],
        backends={
            "lark": FakeBackend(name="lark", trust_zone="internal", capabilities=_full_caps())
        },
        journal=journal,
    )
    assert plan["status"] == "ok"
    assert "reason" not in plan
    assert plan["plan"]["revision_current"] is None
    assert plan["plan"]["history_hint"] is None  # create 走删除，不查平台 history


def test_plan_document_gone_without_revision_evidence_rejected(wecom_backend, tmp_home):
    """FM3：文档被删后只剩快照内容可查 → 拒绝（既不 ok 也不崩）。"""
    journal = Journal(tmp_home)
    entry = begin(
        journal,
        operation="update",
        backend="wecom",
        target_uri="kgent://wecom/W1",
        revision_before=7,
        content="A",
    )
    end(journal, entry["op_id"], status="ok")
    gone = FakeBackend(name="wecom", trust_zone="external", capabilities=_full_caps())

    plan = compensation_plan(entry["op_id"], backends={"wecom": gone}, journal=journal)
    assert plan["status"] == "rejected"
    assert "is gone" in plan["reason"]


# ---------------------------------------------------------------------------
# Fix round 1 — CLI 分流兜底（cli._entry_backend_name 的 targets 兜底分支）
# 与文本模式 undo 的 rejected reason
# ---------------------------------------------------------------------------


def _begin_entry_targets_only(op_id: str, targets: list[str]) -> dict:
    """begin 形态但不带 backend 字段：backend 只能从 targets 兜底解析。"""
    return {
        "schema_version": 1,
        "op_id": op_id,
        "kind": "begin",
        "ts": "2026-09-06T00:00:00+00:00",
        "operation": "update",
        "targets": targets,
        "revision_before": 50,
    }


def test_undo_cli_begin_entry_with_targets_only_routes_to_plan(undo_world, capsys):
    """begin entry 只有 targets（无 backend 字段）→ 仍按 parse_uri 进计划分支。

    CLI 分流只看 backend 名；begin entry 若以 targets 记名，也应进计划分支，
    而不是落到会真改文档的 best-effort undo。
    """
    fb = undo_world["lark"]
    fb.docs["kgent://lark/DOC1"] = _doc("kgent://lark/DOC1", 56)
    journal = Journal(undo_world["home"])
    journal.append(_begin_entry_targets_only("op-20260906-tgtly01", ["kgent://lark/DOC1"]))
    end(journal, "op-20260906-tgtly01", status="ok", revision_after=56)

    code = main(["undo", "op-20260906-tgtly01", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["mode"] == "plan"
    assert out["plan"]["mechanism"] == "history-revert"
    assert fb.write_calls == []  # 只产计划，不动文档


def test_undo_cli_begin_entry_without_targets_falls_back(undo_world, capsys):
    """begin entry 的 targets 为空 → 进不了计划分支，既有 undo 报失败（exit 1）。

    没有可回滚 target 的 op 绝不能成功收场：退出码 1、无 restored、无副作用。
    （注：JSON 的 ``status`` 字段来自 ``OpResult.status`` 默认值 ``"ok"``——
    ``journal.undo`` 从不覆盖它，真实结果在 exit code 与 journal entry 里，
    这是既有行为，此处只钉退出码与无副作用。）
    """
    journal = Journal(undo_world["home"])
    journal.append(_begin_entry_targets_only("op-20260906-notgt01", []))

    code = main(["undo", "op-20260906-notgt01", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 1
    assert out["operation"] == "undo"
    assert out["error"] is None
    assert undo_world["lark"].write_calls == []  # 没有任何回滚动作发生


def test_undo_cli_begin_entry_with_unparseable_target_falls_back(undo_world, capsys):
    """begin entry 的 targets 解析不了 → 不进计划分支，best-effort undo 逐 target 报错。

    错误要点名 uri 并带上 canonical-URI 提示——这正是 parse_uri 的契约，而不是
    一个含糊的“undo 失败”。
    """
    journal = Journal(undo_world["home"])
    journal.append(_begin_entry_targets_only("op-20260906-badtgt01", ["not-a-uri"]))

    code = main(["undo", "op-20260906-badtgt01", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 1
    assert out["error"].startswith("not-a-uri:")
    assert "canonical kgent:// URI" in out["error"]
    assert undo_world["lark"].write_calls == []


def test_undo_cli_text_output_surfaces_rejection_reason(undo_world, capsys):
    """文本模式 undo 被拒 → 输出机制/集成 skill 与 reason（人读路径）。

    JSON 模式的 reason 已有断言；文本模式少这一行，维护者在终端上就只看到
    rejected 而不知道为什么。
    """
    fb = undo_world["lark"]
    fb.docs["kgent://lark/DOC1"] = _doc("kgent://lark/DOC1", 56)
    journal = Journal(undo_world["home"])
    entry = begin(
        journal,
        operation="update",
        backend="lark",
        target_uri="kgent://lark/DOC1",
        revision_before=50,
    )
    end(journal, entry["op_id"], status="ok", revision_after=56)
    _set_version(fb, "kgent://lark/DOC1", 57)

    code = main(["undo", entry["op_id"]])
    text = capsys.readouterr().out
    assert code == 1
    assert "rejected: history-revert via lark-integration" in text
    assert "reason:" in text
    assert "57" in text  # reason 里点明当前 revision


def test_plan_update_gone_with_revision_evidence_rejected(tmp_home):
    """FM2：带 revision_after 的 update 撞上文档已删 → 拒绝。

    与 create 相对：create 的补偿是删除，文档已不在是期待结局（幂等 ok）；
    update 的补偿是写回，文档没了就必须拒绝，不能当成“无证据”放过。
    """
    journal = Journal(tmp_home)
    entry = begin(
        journal,
        operation="update",
        backend="lark",
        target_uri="kgent://lark/DOC1",
        revision_before=50,
    )
    end(journal, entry["op_id"], status="ok", revision_after=56)
    plan = compensation_plan(
        entry["op_id"],
        backends={
            "lark": FakeBackend(name="lark", trust_zone="internal", capabilities=_full_caps())
        },
        journal=journal,
    )
    assert plan["status"] == "rejected"
    assert "is gone" in plan["reason"]
    assert "56" in plan["reason"]  # reason 点明台账里的 revision


# ---------------------------------------------------------------------------
# C1（final review）：create 腿的占位 URI 由 end --doc-uri 回填，计划指向真身
# ---------------------------------------------------------------------------


def test_plan_create_end_doc_uri_overrides_placeholder(tmp_home):
    """create begin 只登记了 planned 占位 → end 回填真实 URI → 计划指向真身。

    补偿（删除）必须落在真实创建出来的文档上——指向占位 token 的计划删不到
    任何东西却报成功，正是本 finding 的缺陷。
    """
    fb = FakeBackend(name="lark", trust_zone="internal", capabilities=_full_caps())
    fb.docs["kgent://lark/REAL123"] = _doc("kgent://lark/REAL123", 1)
    journal = Journal(tmp_home)
    entry = begin(
        journal,
        operation="create",
        backend="lark",
        target_uri="kgent://lark/planned",
        revision_before=None,
    )
    end(journal, entry["op_id"], status="ok", doc_uri="kgent://lark/REAL123")

    plan = compensation_plan(entry["op_id"], backends={"lark": fb}, journal=journal)
    assert plan["status"] == "ok"
    assert plan["plan"]["target"] == "kgent://lark/REAL123"  # 不是 begin 的占位
    # 新鲜度读的也是真身（current revision 来自真实文档）
    assert plan["plan"]["revision_current"] == 1


def test_plan_create_without_backfill_keeps_begin_target(tmp_home):
    """旧式 create（end 无回填）→ 计划仍用 begin 的 target（兼容，行为不变）。"""
    fb = FakeBackend(name="lark", trust_zone="internal", capabilities=_full_caps())
    fb.docs["kgent://lark/DOC1"] = _doc("kgent://lark/DOC1", 1)
    journal = Journal(tmp_home)
    entry = begin(
        journal,
        operation="create",
        backend="lark",
        target_uri="kgent://lark/DOC1",
        revision_before=None,
    )
    end(journal, entry["op_id"], status="ok")

    plan = compensation_plan(entry["op_id"], backends={"lark": fb}, journal=journal)
    assert plan["plan"]["target"] == "kgent://lark/DOC1"


def test_plan_update_end_doc_uri_also_wins(lark_backend, tmp_home):
    """update 腿 end 回填的 doc_uri 同样优先（重指向场景）；begin 的 backend 保留。"""
    lark_backend.docs["kgent://lark/MOVED"] = _doc("kgent://lark/MOVED", 7)
    journal = Journal(tmp_home)
    entry = begin(
        journal,
        operation="update",
        backend="lark",
        target_uri="kgent://lark/OLD",
        revision_before=6,
    )
    end(journal, entry["op_id"], status="ok", revision_after=7, doc_uri="kgent://lark/MOVED")

    plan = compensation_plan(entry["op_id"], backends={"lark": lark_backend}, journal=journal)
    assert plan["plan"]["target"] == "kgent://lark/MOVED"
    assert plan["plan"]["backend"] == "lark"  # backend 仍来自 begin entry
    assert plan["status"] == "ok"


def test_journal_end_cli_doc_uri_flag(tmp_home, capsys):
    """CLI：``journal end --doc-uri`` 落进 end entry（JSON 输出原样携带）。"""
    assert (
        main(
            [
                "journal",
                "begin",
                "--operation",
                "create",
                "--backend",
                "lark",
                "--doc-uri",
                "kgent://lark/planned",
            ]
        )
        == 0
    )
    op_id = next(o["op_id"] for o in Journal(tmp_home).entries if o.get("kind") == "begin")
    capsys.readouterr()  # 丢弃 begin 的文本输出，让 end 的 JSON 独占缓冲

    code = main(
        [
            "journal",
            "end",
            "--op-id",
            op_id,
            "--status",
            "ok",
            "--doc-uri",
            "kgent://lark/REAL9",
            "--json",
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["entry"]["doc_uri"] == "kgent://lark/REAL9"
    # 台账里 end entry 确实带 doc_uri，begin entry 不受影响（append-only）
    kinds = {e["kind"]: e for e in Journal(tmp_home).entries if e["op_id"] == op_id}
    assert kinds["end"]["doc_uri"] == "kgent://lark/REAL9"
    assert "doc_uri" not in kinds["begin"]


def test_undo_cli_create_with_backfilled_uri_plans_delete_of_real_doc(undo_world, capsys):
    """端到端：占位 begin → end --doc-uri 回填 → ``kgent undo`` 计划删真实文档。"""
    fb = undo_world["lark"]
    fb.docs["kgent://lark/REAL7"] = _doc("kgent://lark/REAL7", 2)
    journal = Journal(undo_world["home"])
    entry = begin(
        journal,
        operation="create",
        backend="lark",
        target_uri="kgent://lark/planned",
        revision_before=None,
    )
    end(journal, entry["op_id"], status="ok", doc_uri="kgent://lark/REAL7")

    code = main(["undo", entry["op_id"], "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["plan"]["target"] == "kgent://lark/REAL7"
    assert fb.write_calls == []  # 只产计划：删除归 lark-integration 执行


# ---------------------------------------------------------------------------
# Phase 3 Task 2 — 写后快照通道（wecom 真机证实无平台 version → 维护者签核
# 方案 A：end 记写后全文快照，undo 拿它做新鲜度证据；FM2-wecom 形状）
# ---------------------------------------------------------------------------


def test_compensation_plan_post_write_snapshot_ok(wecom_backend, tmp_home):
    """end 带 snapshot_after 且 current == 写后内容 → ok（B5 happy path 的新鲜度通道）。

    begin 快照（"A"）已被写本身作废——current 是写后的 "B"，只有写后快照
    通道放行；若误走 FM3 begin 快照比对会 rejected，这条用例就能分辨。
    """
    _set_content(wecom_backend, "kgent://wecom/W1", "B")  # 本次写本身
    journal = Journal(tmp_home)
    entry = begin(
        journal,
        operation="update",
        backend="wecom",
        target_uri="kgent://wecom/W1",
        revision_before=7,
        content="A",
    )
    end(journal, entry["op_id"], status="ok", snapshot_after="B")
    plan = compensation_plan(entry["op_id"], backends={"wecom": wecom_backend}, journal=journal)
    assert plan["status"] == "ok"
    assert "reason" not in plan
    assert plan["plan"]["mechanism"] == "snapshot-restore"
    assert plan["plan"]["snapshot_after"].endswith(".after.txt")


def test_compensation_plan_post_write_snapshot_third_party_edit_rejected(wecom_backend, tmp_home):
    """写后被第三方改过（current != 写后快照）→ rejected，reason 指写后快照（FM2-wecom）。"""
    journal = Journal(tmp_home)
    entry = begin(
        journal,
        operation="update",
        backend="wecom",
        target_uri="kgent://wecom/W1",
        revision_before=7,
        content="A",
    )
    end(journal, entry["op_id"], status="ok", snapshot_after="B")
    _set_content(wecom_backend, "kgent://wecom/W1", "C")  # 第三方并发编辑

    plan = compensation_plan(entry["op_id"], backends={"wecom": wecom_backend}, journal=journal)
    assert plan["status"] == "rejected"
    assert "post-write snapshot no longer matches" in plan["reason"]


def test_compensation_plan_snapshot_after_file_missing_fail_closed(wecom_backend, tmp_home):
    """写后快照文件不可读 → rejected（fail closed），绝不退回 begin 快照兜底盲放行。"""
    journal = Journal(tmp_home)
    entry = begin(
        journal,
        operation="update",
        backend="wecom",
        target_uri="kgent://wecom/W1",
        revision_before=7,
        content="A",
    )
    done = end(journal, entry["op_id"], status="ok", snapshot_after="B")
    Path(done["snapshot_after"]).unlink()  # current 仍是 "A"——退回 FM3 会误判 ok

    plan = compensation_plan(entry["op_id"], backends={"wecom": wecom_backend}, journal=journal)
    assert plan["status"] == "rejected"
    assert "post-write snapshot file is unreadable" in plan["reason"]


def test_compensation_plan_post_write_snapshot_document_gone_rejected(wecom_backend, tmp_home):
    """写后快照在、文档已删 → rejected（update 撞上消失不是幂等结局，B4 只属 create）。"""
    journal = Journal(tmp_home)
    entry = begin(
        journal,
        operation="update",
        backend="wecom",
        target_uri="kgent://wecom/W1",
        revision_before=7,
        content="A",
    )
    end(journal, entry["op_id"], status="ok", snapshot_after="B")
    gone = FakeBackend(name="wecom", trust_zone="external", capabilities=_full_caps())

    plan = compensation_plan(entry["op_id"], backends={"wecom": gone}, journal=journal)
    assert plan["status"] == "rejected"
    assert "post-write snapshot freshness cannot be verified" in plan["reason"]


def test_compensation_plan_revision_after_wins_over_snapshot_after(wecom_backend, tmp_home):
    """优先级：revision_after 存在 → 写后快照分支不生效（FM2 优先，内容漂移不管）。"""
    _set_content(wecom_backend, "kgent://wecom/W1", "B")  # 与写后快照 "STALE" 不符
    journal = Journal(tmp_home)
    entry = begin(
        journal,
        operation="update",
        backend="wecom",
        target_uri="kgent://wecom/W1",
        revision_before=7,
        content="A",
    )
    end(journal, entry["op_id"], status="ok", revision_after=8, snapshot_after="STALE")

    plan = compensation_plan(entry["op_id"], backends={"wecom": wecom_backend}, journal=journal)
    assert plan["status"] == "ok"  # revision 相符即放行；快照字段照记但不当证据
    assert "reason" not in plan
    assert plan["plan"]["snapshot_after"].endswith(".after.txt")


def test_compensation_plan_create_with_snapshot_after_skips_freshness(wecom_backend, tmp_home):
    """create 腿不做写后快照新鲜度（补偿是删除，走既有幂等分支）——内容漂移不拒。"""
    wecom_backend.docs["kgent://wecom/NEW1"] = _doc("kgent://wecom/NEW1", 1, content="B")
    journal = Journal(tmp_home)
    entry = begin(
        journal,
        operation="create",
        backend="wecom",
        target_uri="kgent://wecom/planned",
        revision_before=None,
    )
    end(journal, entry["op_id"], status="ok", snapshot_after="STALE")

    plan = compensation_plan(entry["op_id"], backends={"wecom": wecom_backend}, journal=journal)
    assert plan["status"] == "ok"
    assert "reason" not in plan
    assert plan["plan"]["operation"] == "create"
    assert plan["plan"]["snapshot_after"].endswith(".after.txt")
