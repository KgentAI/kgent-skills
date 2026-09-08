"""DingTalkAdapter 真值接线（B11 search 类型保真 + B6 undo 新鲜度读）。

fixture 沿用 tests/test_lark_node_type.py 的模式：payload 形状存
tests/fixtures/dws/，fake ``run_cli`` 按子命令分发——不 spawn 真实 dws。

**Provenance: documented shape from dws native-skill references; NOT
live-captured（credentials unavailable, 2026-09-08）**——维护者无钉钉账号，
payload 按 PROBE-NOTES 命令真值 + 原生 dingtalk-* skill 文档形状构造
（dingtalk-doc SKILL.md / contracts.md / doc-read.md、dingtalk-shared
url-patterns.md）。叶子键名是真机补捕前的对账锚点：解析全部集中在
``kgent/adapters/dingtalk.py`` 的模块级 ``_extract_*`` 帮助函数，补捕后
只改锚点与本目录 fixture。逐键 provenance 与文档冲突点见
``tests/fixtures/dws/FIXTURES-NOTE.md``。

命令形状钉死在断言里（PROBE-NOTES §1 [help 实测]）：搜索是 ``doc +search
--query``（无 ``doc search``），fetch 用 ``--node`` 旗标（无位置参数），
格式旗标是 ``-f json``（非 wire-v1 的 ``--json`` 尾标）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kgent.adapters import dingtalk as dws_mod
from kgent.adapters.cli_adapter import SubprocessResult
from kgent.adapters.dingtalk import DingTalkAdapter
from kgent.errors import AdapterError

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "dws"
SEARCH_PAYLOAD = (FIXTURES / "doc-search.json").read_text(encoding="utf-8")
FETCH_PAYLOAD = (FIXTURES / "doc-fetch.json").read_text(encoding="utf-8")

#: doc-fetch.json ``data`` 块的取值（测试期望值直接取 fixture 真值）。
FLAT_NODE_ID = "mXk4Qw7bZnVc2yPq8RtJeH"
FLAT_TITLE = "kgent-phase2-probe 使用手册"
FLAT_REVISION = "3"  # +expected-revision 的轴：文档编辑版本号（int → str）
CONTENT_NEEDLE = "probe body line for payload capture."
WIKI_NODE_ID = "wS6dGv2kJh9nMx4pLq8bTr"
SHEET_NODE_ID = "dE3fUy8sKa5mNo2iGt7cXw"


class _FakeDws:
    """Stand-in for ``run_cli``: serves fixtures by subcommand, records calls."""

    def __init__(
        self,
        search_stdout: str = SEARCH_PAYLOAD,
        fetch_stdout: str = FETCH_PAYLOAD,
    ) -> None:
        self.search_stdout = search_stdout
        self.fetch_stdout = fetch_stdout
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], timeout: float, **_kw: Any) -> SubprocessResult:
        self.calls.append(argv)
        if "+search" in argv:
            return SubprocessResult(0, self.search_stdout, "")
        if "+fetch" in argv:
            return SubprocessResult(0, self.fetch_stdout, "")
        raise AssertionError(f"unexpected argv: {argv}")


# ---------------------------------------------------------------------------
# read: dws doc +fetch —— revision → metadata.version（B6 undo 新鲜度数据源）
# ---------------------------------------------------------------------------


def test_read_document_carries_revision_as_version(monkeypatch):
    """``doc +fetch`` 的 revision 上 ``metadata.version``——``kgent undo``
    补偿计划的新鲜度数据源（B6）。argv 钉死 PROBE-NOTES §1 命令真值。"""
    fake = _FakeDws()
    monkeypatch.setattr(dws_mod, "run_cli", fake)
    doc = DingTalkAdapter(cmd=["fake-dws"]).read_document(f"kgent://dingtalk/{FLAT_NODE_ID}")

    assert fake.calls == [["fake-dws", "doc", "+fetch", "--node", FLAT_NODE_ID, "-f", "json"]]
    assert doc.doc_uri == f"kgent://dingtalk/{FLAT_NODE_ID}"
    assert doc.metadata.version == FLAT_REVISION
    assert doc.title == FLAT_TITLE
    assert CONTENT_NEEDLE in doc.content
    assert doc.metadata.backend == "dingtalk"


def test_read_fetch_failure_surfaces_normalized_adapter_error(monkeypatch):
    """Nonzero fetch exit → stderr-derived AdapterError（失败不静默吞掉）。"""

    def failing(argv: list[str], timeout: float, **_kw: Any) -> SubprocessResult:
        return SubprocessResult(1, "", json.dumps({"error": f"document not found: {FLAT_NODE_ID}"}))

    monkeypatch.setattr(dws_mod, "run_cli", failing)
    with pytest.raises(AdapterError, match="not found"):
        DingTalkAdapter(cmd=["fake-dws"]).read_document(f"kgent://dingtalk/{FLAT_NODE_ID}")


def test_run_dws_rejects_exit0_non_json_and_non_object_payloads(monkeypatch):
    """退出 0 但 stdout 非 JSON / 非 JSON 对象 → AdapterError（dws 的 ``-f
    json`` 契约：退出码不能替代可解析证据——错误不静默吞掉）。"""

    cases = [
        ("{not-json", "malformed JSON"),
        ("[1, 2]", "non-object JSON"),
    ]
    adapter = DingTalkAdapter(cmd=["fake-dws"])
    for stdout, needle in cases:
        monkeypatch.setattr(dws_mod, "run_cli", _FakeDws(fetch_stdout=stdout))
        with pytest.raises(AdapterError, match=needle):
            adapter.read_document(f"kgent://dingtalk/{FLAT_NODE_ID}")


def test_run_dws_rejects_exit0_ok_false_envelope(monkeypatch):
    """退出 0 不能替代业务证据——envelope ``ok: false`` 即失败（contracts.md）。"""
    payload = json.dumps({"ok": False, "status": "permission denied", "data": {}})
    monkeypatch.setattr(dws_mod, "run_cli", _FakeDws(fetch_stdout=payload))
    with pytest.raises(AdapterError, match="reported failure on exit 0"):
        DingTalkAdapter(cmd=["fake-dws"]).read_document(f"kgent://dingtalk/{FLAT_NODE_ID}")


# ---------------------------------------------------------------------------
# search: dws doc +search —— hit node_type 只来自服务端事实（B11 保真）
# ---------------------------------------------------------------------------


def test_search_hit_types_follow_server_facts(monkeypatch):
    """判型三步各有一枚 fixture hit：知识库容器事实 → wiki_node；
    扁平 adoc → doc；/spreadsheetv2/ 表格出 §7.2 词表 → doc（不伪装成
    词表另一端，lark bitable 同款）。"""
    fake = _FakeDws()
    monkeypatch.setattr(dws_mod, "run_cli", fake)
    hits = DingTalkAdapter(cmd=["fake-dws"]).search_by_keywords("kgent-phase2-probe")

    assert fake.calls == [
        [
            "fake-dws",
            "doc",
            "+search",
            "--query",
            "kgent-phase2-probe",
            "--limit",
            "10",
            "-f",
            "json",
        ]
    ]
    assert len(hits) == 3, "fixture 应三条 hit 全部解析"
    by_uri = {h.doc_uri: h for h in hits}
    assert set(by_uri) == {
        f"kgent://dingtalk/{FLAT_NODE_ID}",
        f"kgent://dingtalk/{WIKI_NODE_ID}",
        f"kgent://dingtalk/{SHEET_NODE_ID}",
    }

    flat = by_uri[f"kgent://dingtalk/{FLAT_NODE_ID}"]
    wiki = by_uri[f"kgent://dingtalk/{WIKI_NODE_ID}"]
    sheet = by_uri[f"kgent://dingtalk/{SHEET_NODE_ID}"]
    assert flat.node_type == "doc"
    assert wiki.node_type == "wiki_node"
    assert sheet.node_type == "doc"
    # rank 是 CLI 的 1-based 序（§3.8）；metadata 镜像 result 级字段（skills 读任一）
    assert [h.rank for h in hits] == [1, 2, 3]
    assert all(h.mode_used == "keyword" for h in hits)
    assert wiki.metadata.node_type == "wiki_node"
    assert CONTENT_NEEDLE in (flat.snippet or "")


def test_search_hit_type_field_non_doc_value_lands_doc(monkeypatch):
    """类型字段判型（无 URL 的 hit 走第二分支）：``axls`` 出 §7.2 词表 →
    ``doc``——绝不伪装成词表另一端（lark bitable hit 同款纪律）。类型字段
    缺失时落容器事实：只有 ``workspaceId`` 的 hit → ``wiki_node``。"""
    payload = json.dumps(
        {
            "ok": True,
            "complete": True,
            "items": [
                {"nodeId": SHEET_NODE_ID, "title": "sheet", "type": "axls"},
                {"nodeId": WIKI_NODE_ID, "title": "wiki node", "workspaceId": "WS-1"},
            ],
        }
    )
    monkeypatch.setattr(dws_mod, "run_cli", _FakeDws(search_stdout=payload))
    hits = DingTalkAdapter(cmd=["fake-dws"]).search_by_keywords("probe")

    assert [h.node_type for h in hits] == ["doc", "wiki_node"]
    assert [h.metadata.node_type for h in hits] == ["doc", "wiki_node"]


def test_search_skips_non_dict_items_and_defaults_non_int_rank(monkeypatch):
    """非 dict 命中段跳过；rank 非 int 落 0（CLI payload 按未验证输入处理）。"""
    payload = json.dumps(
        {
            "ok": True,
            "complete": True,
            "items": [
                "not-a-dict",
                {"nodeId": FLAT_NODE_ID, "title": "with id", "type": "adoc", "rank": "high"},
            ],
        }
    )
    monkeypatch.setattr(dws_mod, "run_cli", _FakeDws(search_stdout=payload))
    hits = DingTalkAdapter(cmd=["fake-dws"]).search_by_keywords("probe")

    assert [h.doc_uri for h in hits] == [f"kgent://dingtalk/{FLAT_NODE_ID}"]
    assert [h.rank for h in hits] == [0]


def test_search_hit_without_id_is_dropped(monkeypatch):
    """缺稳定 ID 的 hit 不进结果（contracts.md：目标至少保留 nodeId）。"""
    payload = json.dumps(
        {
            "ok": True,
            "complete": True,
            "items": [
                {"title": "no id", "type": "adoc"},
                {"nodeId": FLAT_NODE_ID, "title": "with id", "type": "adoc"},
            ],
        }
    )
    fake = _FakeDws(search_stdout=payload)
    monkeypatch.setattr(dws_mod, "run_cli", fake)
    hits = DingTalkAdapter(cmd=["fake-dws"]).search_by_keywords("probe")

    assert [h.doc_uri for h in hits] == [f"kgent://dingtalk/{FLAT_NODE_ID}"]


def test_search_respects_top_k_and_dws_limit_cap(monkeypatch):
    """top_k 透传为 ``--limit``；dws 文档上限 30（PROBE-NOTES §1.2）封顶。"""
    fake = _FakeDws()
    monkeypatch.setattr(dws_mod, "run_cli", fake)
    adapter = DingTalkAdapter(cmd=["fake-dws"])

    adapter.search_by_keywords("probe", top_k=2)
    assert fake.calls[-1][fake.calls[-1].index("--limit") + 1] == "2"

    adapter.search_by_keywords("probe", top_k=50)
    assert fake.calls[-1][fake.calls[-1].index("--limit") + 1] == "30"


# ---------------------------------------------------------------------------
# win32 解析：npm 全局 dws 是 .cmd shim，CreateProcess 打不开裸名（WinError 2，
# lark-cli.cmd 同款教训——PROBE-NOTES §5 三 shim 实测）
# ---------------------------------------------------------------------------


def test_win32_cmd_resolution(monkeypatch):
    monkeypatch.setattr(dws_mod.sys, "platform", "win32")
    assert DingTalkAdapter().cmd[0].endswith(".cmd")

    monkeypatch.setattr(dws_mod.sys, "platform", "linux")
    assert DingTalkAdapter().cmd == ["dws"]
