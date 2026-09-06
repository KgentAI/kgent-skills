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
    entry = begin(journal, operation="update", backend="lark",
                  target_uri="kgent://lark/DOC1", revision_before=50)
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
    assert plan["plan"]["history_hint"] == "docs +history-list → history_version_id(revision_before)"
    assert "reason" not in plan


def test_plan_rejected_when_edited_since(lark_backend, tmp_home):
    journal = Journal(tmp_home)
    entry = begin(journal, operation="update", backend="lark",
                  target_uri="kgent://lark/DOC1", revision_before=50)
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
    entry = begin(journal, operation="update", backend="lark",
                  target_uri="kgent://lark/DOC1", revision_before="50")
    end(journal, entry["op_id"], status="ok", revision_after="56")
    _set_version(lark_backend, "kgent://lark/DOC1", 56)  # int 56 == str "56"
    plan = compensation_plan(entry["op_id"], backends={"lark": lark_backend}, journal=journal)
    assert plan["status"] == "ok"
    assert plan["plan"]["revision_current"] == 56


def test_plan_dingtalk_mechanism_version_revert(tmp_home):
    fb = FakeBackend(name="dingtalk", trust_zone="external", capabilities=_full_caps())
    fb.docs["kgent://dingtalk/D1"] = _doc("kgent://dingtalk/D1", 3)
    journal = Journal(tmp_home)
    entry = begin(journal, operation="update", backend="dingtalk",
                  target_uri="kgent://dingtalk/D1", revision_before=2)
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
    entry = begin(journal, operation="update", backend="gdoc",
                  target_uri="kgent://gdoc/G1", revision_before=1)
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
    entry = begin(journal, operation="create", backend="lark",
                  target_uri="kgent://lark/NEW1", revision_before=None)
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
    entry = begin(journal, operation="create", backend="lark",
                  target_uri="kgent://lark/GONE", revision_before=None)
    end(journal, entry["op_id"], status="ok")
    plan = compensation_plan(entry["op_id"], backends={"lark": FakeBackend(
        name="lark", trust_zone="internal", capabilities=_full_caps())}, journal=journal)
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
    entry = begin(journal, operation="update", backend="wecom",
                  target_uri="kgent://wecom/W1", revision_before=7, content="A")
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
    entry = begin(journal, operation="update", backend="wecom",
                  target_uri="kgent://wecom/W1", revision_before=7, content="A")
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
    entry = begin(journal, operation="update", backend="lark",
                  target_uri="kgent://lark/DOC1", revision_before=50)
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
    entry = begin(journal, operation="update", backend="lark",
                  target_uri="kgent://lark/DOC1", revision_before=50)
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
    entry = begin(journal, operation="update", backend="lark",
                  target_uri="kgent://lark/DOC1", revision_before=50)
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
    entry = begin(journal, operation="update", backend="lark",
                  target_uri="kgent://lark/DOC1", revision_before=50)
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
