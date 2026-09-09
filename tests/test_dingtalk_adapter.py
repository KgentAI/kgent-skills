"""DingTalkAdapter 真值接线（B11 search 类型保真 + B6 undo 新鲜度读）。

fixture 沿用 tests/test_lark_node_type.py 的模式：payload 形状存
tests/fixtures/dws/，fake ``run_cli`` 按子命令分发——不 spawn 真实 dws。

**Provenance: live-captured 2026-09-09（dws v1.0.61 真机，B6/B8 兑现轮修复
半场）**——``doc-search.json``/``doc-fetch.json``/``doc-fetch-simple.json`` 等
全部按真机捕获原样回填（provenance 与锚点定谳见
``tests/fixtures/dws/FIXTURES-NOTE.md``；payload 全文见
``.superpowers/sdd/2026-09-08-phase3-wecom-integration/dingtalk-closure-report.md``
§3）。仅两支判型分支（知识库 ``workspaceId`` 容器事实、非文字文档
``docType: axls``）真机 search 未覆盖——用**内联合成 payload** 测（逐处标注
synthetic，documented-not-captured）。解析全部集中在
``kgent/adapters/dingtalk.py`` 的模块级 ``_extract_*`` 帮助函数（键位对账锚点）。

命令形状钉死在断言里（PROBE-NOTES §1 [help 实测] + live-captured 2026-09-09）：
搜索是 ``doc +search --query``（无 ``doc search``），fetch 用 ``--node`` 旗标
（无位置参数），格式旗标是 ``-f json``（非 wire-v1 的 ``--json`` 尾标）；
read_document 两枪——``--detail with-ids`` 取 revision（B6 新鲜度）+ 默认档取
markdown 正文（dws 无任何单档同时携带两者，真机定谳）。
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
FETCH_SIMPLE_PAYLOAD = (FIXTURES / "doc-fetch-simple.json").read_text(encoding="utf-8")

#: live-captured 真值（doc-search.json 三 hit / doc-fetch.json 的 content 块）。
FLAT_NODE_ID = "1R7q3QmWeeZZ1qwDS6dQPyDdWxkXOEP2"  # doc-fetch*.json 的探针本体
FLAT_TITLE = "kgent-phase2-probe-完整性"
FLAT_REVISION = "1"  # with-ids 档 content.revision（字符串，live-captured）
CONTENT_NEEDLE = "「中文标点」"  # 默认档 content.markdown（B8 保真原文）
PROBE_NODE_IDS = {
    "bva6QBXJwa11X3xYSLqj34DZWn4qY5Pr",
    FLAT_NODE_ID,
    "0eMKjyp813XXZ20efrnNgvOBVxAZB1Gv",
}
#: synthetic 判型分支的替身 ID（真机 search 未覆盖的两支，documented shape）
WIKI_NODE_ID = "wS6dGv2kJh9nMx4pLq8bTr"
SHEET_NODE_ID = "dE3fUy8sKa5mNo2iGt7cXw"


class _FakeDws:
    """Stand-in for ``run_cli``: serves fixtures by subcommand, records calls.

    fetch 按 ``--detail`` 分档（live-captured 纪法：with-ids 带 revision 无
    markdown，默认档带 markdown 无 revision——真 dws 的两档就长这样）。
    """

    def __init__(
        self,
        search_stdout: str = SEARCH_PAYLOAD,
        fetch_detail_stdout: str = FETCH_PAYLOAD,
        fetch_simple_stdout: str = FETCH_SIMPLE_PAYLOAD,
    ) -> None:
        self.search_stdout = search_stdout
        self.fetch_detail_stdout = fetch_detail_stdout
        self.fetch_simple_stdout = fetch_simple_stdout
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], timeout: float, **_kw: Any) -> SubprocessResult:
        self.calls.append(argv)
        if "+search" in argv:
            return SubprocessResult(0, self.search_stdout, "")
        if "+fetch" in argv:
            stdout = (
                self.fetch_detail_stdout if "--detail" in argv else self.fetch_simple_stdout
            )
            return SubprocessResult(0, stdout, "")
        raise AssertionError(f"unexpected argv: {argv}")


# ---------------------------------------------------------------------------
# read: dws doc +fetch —— revision → metadata.version（B6 undo 新鲜度数据源）
# ---------------------------------------------------------------------------


def test_read_document_carries_revision_as_version(monkeypatch):
    """``doc +fetch`` 两枪（live-captured 档位纪法）：``--detail with-ids`` 的
    ``content.revision`` 上 ``metadata.version``（B6）；默认档 ``content.markdown``
    上正文。argv 钉死 PROBE-NOTES §1 命令真值。"""
    fake = _FakeDws()
    monkeypatch.setattr(dws_mod, "run_cli", fake)
    doc = DingTalkAdapter(cmd=["fake-dws"]).read_document(f"kgent://dingtalk/{FLAT_NODE_ID}")

    assert fake.calls == [
        [
            "fake-dws",
            "doc",
            "+fetch",
            "--node",
            FLAT_NODE_ID,
            "--detail",
            "with-ids",
            "-f",
            "json",
        ],
        ["fake-dws", "doc", "+fetch", "--node", FLAT_NODE_ID, "-f", "json"],
    ]
    assert doc.doc_uri == f"kgent://dingtalk/{FLAT_NODE_ID}"
    assert doc.metadata.version == FLAT_REVISION
    assert doc.title == FLAT_TITLE
    assert CONTENT_NEEDLE in doc.content
    assert doc.metadata.backend == "dingtalk"


def test_read_document_never_serves_jsonml_as_content(monkeypatch):
    """with-ids 档正文键是 ``jsonml``（live-captured）：content 必须来自默认档的
    ``markdown``——JSONML 字符串混进 Document.content 就是保真事故（B8 的反面）。"""
    fake = _FakeDws()
    monkeypatch.setattr(dws_mod, "run_cli", fake)
    doc = DingTalkAdapter(cmd=["fake-dws"]).read_document(f"kgent://dingtalk/{FLAT_NODE_ID}")

    assert "jsonml" not in doc.content
    assert doc.content.startswith("# Phase 2 完整性探针")


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
        monkeypatch.setattr(dws_mod, "run_cli", _FakeDws(fetch_detail_stdout=stdout))
        with pytest.raises(AdapterError, match=needle):
            adapter.read_document(f"kgent://dingtalk/{FLAT_NODE_ID}")


def test_run_dws_rejects_exit0_ok_false_envelope(monkeypatch):
    """退出 0 不能替代业务证据——envelope ``ok: false`` 即失败（contracts.md）。"""
    payload = json.dumps({"ok": False, "status": "permission denied", "data": {}})
    monkeypatch.setattr(dws_mod, "run_cli", _FakeDws(fetch_detail_stdout=payload))
    with pytest.raises(AdapterError, match="reported failure on exit 0"):
        DingTalkAdapter(cmd=["fake-dws"]).read_document(f"kgent://dingtalk/{FLAT_NODE_ID}")


# ---------------------------------------------------------------------------
# search: dws doc +search —— hit node_type 只来自服务端事实（B11 保真）
# ---------------------------------------------------------------------------


def test_search_parses_live_captured_payload(monkeypatch):
    """live-captured `doc.list.v1` payload（``documents`` 容器、hit 键
    ``nodeId/name/docType/url``）：三条真机 hit 全解析，全为扁平 adoc → ``doc``；
    真机 hit 无 ``rank``/``snippet``——rank 落 0（未验证输入兜底）、snippet 落
    ``None``，不发明字段。"""
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
    assert len(hits) == 3, "真机 fixture 三条 hit 应全部解析"
    by_uri = {h.doc_uri: h for h in hits}
    assert set(by_uri) == {f"kgent://dingtalk/{nid}" for nid in PROBE_NODE_IDS}

    flat = by_uri[f"kgent://dingtalk/{FLAT_NODE_ID}"]
    assert flat.node_type == "doc"
    assert flat.metadata.title == FLAT_TITLE  # hit 键是 name（锚点 _extract_title 命中）
    assert flat.metadata.node_type == "doc"
    assert all(h.node_type == "doc" for h in hits)  # adoc 不在非文字词表
    assert all(h.mode_used == "keyword" for h in hits)
    assert [h.rank for h in hits] == [0, 0, 0]  # 真机无 rank 键 → 兜底 0
    assert all(h.snippet is None for h in hits)  # 真机无 snippet 键


def test_search_hit_type_field_non_doc_value_lands_doc(monkeypatch):
    """[synthetic, documented shape] 类型字段判型（无 URL 的 hit 走第二分支）：
    ``docType: axls`` 出 §7.2 词表 → ``doc``——绝不伪装成词表另一端（lark
    bitable hit 同款纪律）。类型字段缺失时落容器事实：只有 ``workspaceId`` 的
    hit → ``wiki_node``。真机 search 命中全为扁平 adoc，这两支待知识库/表格 hit
    真机补捕后按实测回填。"""
    payload = json.dumps(
        {
            "ok": True,
            "complete": True,
            "documents": [
                {"nodeId": SHEET_NODE_ID, "name": "sheet", "docType": "axls"},
                {"nodeId": WIKI_NODE_ID, "name": "wiki node", "workspaceId": "WS-1"},
            ],
        }
    )
    monkeypatch.setattr(dws_mod, "run_cli", _FakeDws(search_stdout=payload))
    hits = DingTalkAdapter(cmd=["fake-dws"]).search_by_keywords("probe")

    assert [h.node_type for h in hits] == ["doc", "wiki_node"]
    assert [h.metadata.node_type for h in hits] == ["doc", "wiki_node"]


def test_search_hits_container_legacy_items_still_served(monkeypatch):
    """``items`` 容器（documented-not-captured 时代构造键 / fake CLI 同款）保留为
    兜底候选：主键 ``documents`` 缺席时不静默空结果。"""
    payload = json.dumps(
        {
            "ok": True,
            "complete": True,
            "items": [{"nodeId": FLAT_NODE_ID, "name": "legacy", "docType": "adoc"}],
        }
    )
    monkeypatch.setattr(dws_mod, "run_cli", _FakeDws(search_stdout=payload))
    hits = DingTalkAdapter(cmd=["fake-dws"]).search_by_keywords("probe")

    assert [h.doc_uri for h in hits] == [f"kgent://dingtalk/{FLAT_NODE_ID}"]


def test_search_skips_non_dict_items_and_defaults_non_int_rank(monkeypatch):
    """非 dict 命中段跳过；rank 非 int 落 0（CLI payload 按未验证输入处理）。"""
    payload = json.dumps(
        {
            "ok": True,
            "complete": True,
            "documents": [
                "not-a-dict",
                {"nodeId": FLAT_NODE_ID, "name": "with id", "docType": "adoc", "rank": "high"},
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
            "documents": [
                {"name": "no id", "docType": "adoc"},
                {"nodeId": FLAT_NODE_ID, "name": "with id", "docType": "adoc"},
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
