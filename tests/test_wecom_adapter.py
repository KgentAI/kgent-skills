"""WeComAdapter 真值接线（B11-wecom search 类型保真 + B5/FM3 undo 新鲜度读）。

fixture 沿用 tests/test_dingtalk_adapter.py 的模式：payload 形状存
tests/fixtures/wecom-cli/（Phase 3 Task 1 + Task 4），fake ``run_cli`` 按
argv **元素**分发——不 spawn 真实 wecom-cli。

**Provenance 分级（逐键见 tests/fixtures/wecom-cli/FIXTURES-NOTE.md）**：

- ``doc-contents-get.json``（V2 读数 ``errcode/content/url``）与
  ``doc-search.json``（零命中 envelope ``{"errcode":0,"errmsg":"ok"}``）是
  2026-09-08 live-captured；
- ``doc-search-hit.json`` 是 schema 契约构造（``OaDocSearchDocInfo``——观测窗
  内 search 从未返回过 hit，命中档真机未捕），值取 Task 1 探针文档的
  docid/url/doc_name 保持可追溯，高亮数组钉死 string[] 形状。

叶子键名是真值回填前的对账锚点：解析全部集中在 ``kgent/adapters/wecom.py``
的模块级 ``_extract_*``，补捕后只改锚点与本目录 fixture。

定谳（PROBE-NOTES 顶部，2026-09-08 三读数一致）：``doc contents get`` 真机
**不下发 ``version`` 键** → ``metadata.version`` 恒 ``None``（无轴可报，不
冒领）；wecom undo 新鲜度走 Task 2 的写后全文快照通道（journal end
``--snapshot-after``，ledger.py 比对 ``current.content``——本读车道是那个
``current`` 的数据源），不走 version 轴。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kgent.adapters import wecom as wecom_mod
from kgent.adapters.cli_adapter import SubprocessResult
from kgent.adapters.wecom import WeComAdapter
from kgent.errors import AdapterError

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "wecom-cli"
GET_PAYLOAD = (FIXTURES / "doc-contents-get.json").read_text(encoding="utf-8")
SEARCH_ZERO_HIT_PAYLOAD = (FIXTURES / "doc-search.json").read_text(encoding="utf-8")
SEARCH_HIT_PAYLOAD = (FIXTURES / "doc-search-hit.json").read_text(encoding="utf-8")

#: Task 1 探针文档的 **API docid**（PROBE-NOTES §4 leftover 点名）——fixture
#: ``url`` 里的 ``w3_`` token 是另一个身份，两者不得互充。
DOC_ID = "dcT9VUpdeMfQPcGiRxwoyVd731mp_zPtLqUxQjN4P8Zs2xq5lviDrKt1sdrN2aofj1Hrz6preKBccku08mgwFU5g"
URL_TOKEN = "w3_ABoAF3hLAPsCN1iJVRLGxRXGQ502e_a"
WECOM_URL = (
    "https://doc.weixin.qq.com/doc/w3_ABoAF3hLAPsCN1iJVRLGxRXGQ502e_a"
    "?scode=AJoAggckACE0bENQUyABoAF3hLAPs"
)
HIT_TITLE = "kgent-phase3-probe-临时"  # doc-search-hit.json 的 doc_name
#: doc-contents-get.json 正文 needle（V2 = append 后读数，尾部 \r + 空格是
#: CLI 真实输出形态，原样保留）。
CONTENT_HEAD = "AAA-CONTENT"
CONTENT_TAIL = "BBB-APPEND"


class _FakeWecom:
    """按 argv 元素分发 fixture 的 run_cli 替身；记录调用。

    Phase 2 Ruling 教训：不用 ``" search " in joined`` 子串分发（对 ``+search``
    形态永不命中）——wecom 的子命令是空格分词的多元素路径
    （``["doc", "search", ...]`` / ``["doc", "contents", "get", ...]``），
    按元素精确匹配。
    """

    def __init__(
        self,
        search_stdout: str = SEARCH_HIT_PAYLOAD,
        get_stdout: str = GET_PAYLOAD,
    ) -> None:
        self.search_stdout = search_stdout
        self.get_stdout = get_stdout
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], timeout: float, **_kw: Any) -> SubprocessResult:
        self.calls.append(argv)
        if "search" in argv:
            return SubprocessResult(0, self.search_stdout, "")
        if "contents" in argv:
            return SubprocessResult(0, self.get_stdout, "")
        raise AssertionError(f"unexpected argv: {argv}")


# ---------------------------------------------------------------------------
# read: wecom-cli doc contents get —— content 是 undo 写后快照比对的 current
# ---------------------------------------------------------------------------


def test_read_document_carries_content_without_version_axis(monkeypatch):
    """live fixture（V2 读数）：content 内联返回；``version`` 键真机不下发 →
    ``metadata.version`` 是 ``None``（无轴可报，不冒领）。argv 钉死 PROBE-NOTES
    §1.2 命令真值：``doc contents get --json <body>``（``--json`` 是输入体
    旗标，body 是 JSON 文本非 argv 对）。"""
    fake = _FakeWecom()
    monkeypatch.setattr(wecom_mod, "run_cli", fake)
    doc = WeComAdapter(cmd=["fake-wecom"]).read_document(f"kgent://wecom/{DOC_ID}")

    assert fake.calls == [
        [
            "fake-wecom",
            "doc",
            "contents",
            "get",
            "--json",
            json.dumps({"docid": DOC_ID}),  # ensure_ascii=True，纯 ASCII argv
        ]
    ]
    assert doc.doc_uri == f"kgent://wecom/{DOC_ID}"
    assert doc.metadata.backend == "wecom"
    assert CONTENT_HEAD in doc.content
    assert CONTENT_TAIL in doc.content
    assert doc.metadata.version is None  # 定谳：键整族缺席，undo 走快照通道
    assert doc.metadata.node_type == "doc"
    # URL token ≠ API docid：身份只用 API docid，w3_ token 不冒充。
    assert doc.doc_uri != f"kgent://wecom/{URL_TOKEN}"


def test_read_document_without_inline_content_fails_closed(monkeypatch):
    """正文键缺席 → AdapterError（fail closed）。长内容落盘 ``file_path`` 的
    相对/绝对语义与 Fs 沙箱边界未定谳（FIXTURES-NOTE 冲突点 4：真值样本落地前
    不消费该键）——宁可显式失败，不猜路径读盘。"""
    payload = json.dumps({"errcode": 0, "url": WECOM_URL})
    monkeypatch.setattr(wecom_mod, "run_cli", _FakeWecom(get_stdout=payload))
    with pytest.raises(AdapterError, match="content"):
        WeComAdapter(cmd=["fake-wecom"]).read_document(f"kgent://wecom/{DOC_ID}")


# ---------------------------------------------------------------------------
# search: wecom-cli doc search —— B11-wecom 类型保真 + API docid 身份
# ---------------------------------------------------------------------------


def test_search_hit_maps_api_docid_and_doc_type_server_fact(monkeypatch):
    """命中档（schema 契约构造，见 FIXTURES-NOTE）：doc_uri 只用 schema 契约
    的 ``docid``；``node_type`` 取 ``doc_type`` server fact（词表内直落）。"""
    fake = _FakeWecom()
    monkeypatch.setattr(wecom_mod, "run_cli", fake)
    hits = WeComAdapter(cmd=["fake-wecom"]).search_by_keywords("kgent-phase3-probe")

    assert fake.calls == [
        [
            "fake-wecom",
            "doc",
            "search",
            "--json",
            json.dumps(
                {
                    "keywords": ["kgent-phase3-probe"],
                    "search_scope": "title_content",
                    "limit": 10,
                }
            ),
        ]
    ]
    assert len(hits) == 1, "fixture 应恰好一条 hit"
    hit = hits[0]
    assert hit.doc_uri == f"kgent://wecom/{DOC_ID}"
    assert hit.doc_uri != f"kgent://wecom/{URL_TOKEN}"  # URL token ≠ API docid
    assert hit.metadata.title == HIT_TITLE
    assert hit.node_type == "doc"  # doc_type server fact
    assert hit.metadata.node_type == "doc"
    # text_highlight 是 string[]（PROBE-NOTES §2.2）→ 逐段拼接为 snippet
    assert hit.snippet == "AAA-CONTENT\nBBB-APPEND"
    assert hit.mode_used == "keyword"
    assert hit.rank == 0  # 真机 hit 无 rank 字段 → 缺席降级 0


def test_search_non_doc_products_land_doc(monkeypatch):
    """``doc_type`` 出 §7.2 词表（sheet/smartsheet/smartpage）→ 落 ``doc``，
    绝不虚构词表另一端 ``wiki_node``（wecom 无 wiki 域；lark bitable /
    dingtalk 非文字产品同款纪律）。分流归 wecom-integration skill 委派矩阵，
    不经 node_type。"""
    payload = json.dumps(
        {
            "errcode": 0,
            "errmsg": "ok",
            "docs": [
                {
                    "docid": "id-sheet",
                    "doc_name": "s",
                    "doc_type": "sheet",
                    "url": "https://doc.weixin.qq.com/sheet/w3_abc",
                },
                {"docid": "id-smartsheet", "doc_name": "m", "doc_type": "smartsheet"},
                {"docid": "id-smartpage", "doc_name": "p", "doc_type": "smartpage"},
            ],
        }
    )
    monkeypatch.setattr(wecom_mod, "run_cli", _FakeWecom(search_stdout=payload))
    hits = WeComAdapter(cmd=["fake-wecom"]).search_by_keywords("probe")

    assert [h.doc_uri for h in hits] == [
        "kgent://wecom/id-sheet",
        "kgent://wecom/id-smartsheet",
        "kgent://wecom/id-smartpage",
    ]
    assert [h.node_type for h in hits] == ["doc", "doc", "doc"]
    assert [h.metadata.node_type for h in hits] == ["doc", "doc", "doc"]


def test_search_type_falls_back_to_url_segment_then_default(monkeypatch):
    """``doc_type`` 缺席 → URL ``<type>`` 段兜底（实测值 ``doc``，PROBE-NOTES
    §3）；两事实皆缺 → 其余 ``doc``。token 形状（``w3_`` 前缀）不判型（N23）。"""
    payload = json.dumps(
        {
            "errcode": 0,
            "errmsg": "ok",
            "docs": [
                {"docid": "id-url", "doc_name": "u", "url": WECOM_URL},
                {"docid": "id-bare", "doc_name": "b"},
            ],
        }
    )
    monkeypatch.setattr(wecom_mod, "run_cli", _FakeWecom(search_stdout=payload))
    hits = WeComAdapter(cmd=["fake-wecom"]).search_by_keywords("probe")

    assert [h.node_type for h in hits] == ["doc", "doc"]


def test_search_zero_hit_envelope_without_docs_family_yields_empty(monkeypatch):
    """零命中 live 真值：``{"errcode":0,"errmsg":"ok"}``——``docs`` 族整族
    缺席（探针词/通用词六连发一致）。解析必须容忍键缺席：空结果 ≠
    ``docs: []``，且 ``errcode: 0`` 不得误判成错误档。"""
    monkeypatch.setattr(wecom_mod, "run_cli", _FakeWecom(search_stdout=SEARCH_ZERO_HIT_PAYLOAD))
    assert WeComAdapter(cmd=["fake-wecom"]).search_by_keywords("文档") == []


def test_search_skips_hits_without_docid_and_tolerates_rank_shapes(monkeypatch):
    """缺稳定 ID（``docid``）的 hit 不进结果；``rank`` 非数值/缺席落 0（CLI
    payload 按未验证输入处理——真机 hit 无 rank 字段）。"""
    payload = json.dumps(
        {
            "errcode": 0,
            "errmsg": "ok",
            "docs": [
                {"doc_name": "no id", "doc_type": "doc"},
                {"docid": "id-rank", "doc_name": "r", "rank": 2},
                {"docid": "id-badrank", "doc_name": "x", "rank": "high"},
                "not-a-dict",
            ],
        }
    )
    monkeypatch.setattr(wecom_mod, "run_cli", _FakeWecom(search_stdout=payload))
    hits = WeComAdapter(cmd=["fake-wecom"]).search_by_keywords("probe")

    assert [h.doc_uri for h in hits] == ["kgent://wecom/id-rank", "kgent://wecom/id-badrank"]
    assert [h.rank for h in hits] == [2, 0]


def test_search_respects_top_k_and_schema_limit_cap(monkeypatch):
    """top_k 透传为 body 的 ``limit``；schema 上限 100（PROBE-NOTES §1.2
    [schema 实测]）封顶。"""
    fake = _FakeWecom()
    monkeypatch.setattr(wecom_mod, "run_cli", fake)
    adapter = WeComAdapter(cmd=["fake-wecom"])

    adapter.search_by_keywords("probe", top_k=2)
    body = json.loads(fake.calls[-1][fake.calls[-1].index("--json") + 1])
    assert body["limit"] == 2

    adapter.search_by_keywords("probe", top_k=500)
    body = json.loads(fake.calls[-1][fake.calls[-1].index("--json") + 1])
    assert body["limit"] == 100


# ---------------------------------------------------------------------------
# 错误契约（PROBE-NOTES §1.4）：退出码 0/1/2 + 结构化错误，不静默成功
# ---------------------------------------------------------------------------


def test_exit0_malformed_json_raises(monkeypatch):
    monkeypatch.setattr(
        wecom_mod,
        "run_cli",
        lambda argv, timeout, **kw: SubprocessResult(0, "not json", ""),
    )
    with pytest.raises(AdapterError, match="malformed JSON"):
        WeComAdapter(cmd=["fake-wecom"]).read_document("kgent://wecom/X")


def test_exit0_error_envelope_raises(monkeypatch):
    """退出 0 但负载是错误档（``errcode`` 893xxx 族）→ AdapterError，不静默
    成功——退出码为零不能替代业务证据。"""
    monkeypatch.setattr(
        wecom_mod,
        "run_cli",
        lambda argv, timeout, **kw: SubprocessResult(
            0, '{"errcode": 893001, "errmsg": "doc not found"}', ""
        ),
    )
    with pytest.raises(AdapterError, match="893001"):
        WeComAdapter(cmd=["fake-wecom"]).read_document("kgent://wecom/X")


def test_exit0_cli_error_envelope_raises(monkeypatch):
    """CLI 层错误 envelope（真机走 exit 1，PROBE-NOTES §1.4；exit-0 出现即
    容错档）→ AdapterError。"""
    payload = json.dumps(
        {
            "error": {
                "type": "UnknownError",
                "code": 893999,
                "message": "AuthError: 该请求需要授权 [code=893201]",
            }
        }
    )
    monkeypatch.setattr(
        wecom_mod,
        "run_cli",
        lambda argv, timeout, **kw: SubprocessResult(0, payload, ""),
    )
    with pytest.raises(AdapterError, match="reported error on exit 0"):
        WeComAdapter(cmd=["fake-wecom"]).search_by_keywords("probe")


def test_nonzero_exit_raises(monkeypatch):
    monkeypatch.setattr(
        wecom_mod,
        "run_cli",
        lambda argv, timeout, **kw: SubprocessResult(2, "", "boom"),
    )
    with pytest.raises(AdapterError, match="exit code"):
        WeComAdapter(cmd=["fake-wecom"]).read_document("kgent://wecom/X")


# ---------------------------------------------------------------------------
# win32 解析：npm 全局 wecom-cli 是 .cmd shim，CreateProcess 打不开裸名
# （WinError 2，lark-cli.cmd/dws.cmd 同款教训——PROBE-NOTES §5 三 shim 实测）
# ---------------------------------------------------------------------------


def test_win32_cmd_resolution(monkeypatch):
    monkeypatch.setattr(wecom_mod.sys, "platform", "win32")
    assert WeComAdapter().cmd[0].endswith(".cmd")

    monkeypatch.setattr(wecom_mod.sys, "platform", "linux")
    assert WeComAdapter().cmd == ["wecom-cli"]
