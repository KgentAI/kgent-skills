"""WeCom adapter (§1.3): read lanes over ``wecom-cli`` (npm ``@wecom/cli``).

Deprecated (skills): 平台操作经 wecom-integration（ADR 0004）；CLI 面保留供
调试与 kgent hosted backend 车道。Phase 3 接真 wecom-cli 的**读**车道：

- :meth:`WeComAdapter.read_document` — ``doc contents get --json``；正文取
  内联 ``content``（真机短内容档，2026-09-08 live 捕获）。``version`` →
  ``metadata.version``：**真机定谳不下发该键**（PROBE-NOTES 顶部定谳，三次
  读数 text/markdown/ooxml 三档一致）→ 真机上恒 ``None``（无轴可报，不冒领）。
  ``kgent undo`` 的新鲜度走 journal end 的写后全文快照通道（FM2-wecom，
  Phase 3 Task 2）：ledger 比对 ``current.content`` 与 ``--snapshot-after``
  快照——本读车道就是那个 ``current`` 的数据源，version 轴不参与。
- :meth:`WeComAdapter.search_by_keywords` — ``doc search --json``；hit 的
  ``node_type`` 经 :func:`_node_type_from_hit`（判定梯见该函数——wecom 无
  wiki 域，§7.2 词表保真 = 不虚构 ``wiki_node``；sheet/smartsheet/smartpage
  的路由分流归 wecom-integration skill 的委派矩阵，消费 ``doc_type`` 字段与
  URL ``<type>`` 段，不经 node_type）。

写车道**不接**：create/update/delete 沿用 wire-v1 基类实现（未覆盖），一切
WeCom 写入经 wecom-integration skill（ADR 0004）——journal 台账（强制
--snapshot-content + 写后快照）与快照写回补偿都活在 skill 侧；CLI 写车道留给
kgent hosted backend 启用时再议（母 spec 非目标节）。真机事实补充：``doc``
域没有任何删除命令（PROBE-NOTES §1.1 help 实测），delete 的真实补偿是 rename
隔离，同样活在 skill 侧。

调用形态与 lark/dws 都不同（PROBE-NOTES §1.3 [help 实测]）：
``wecom-cli <service> <resource...> <method> --json '<JSON 参数>'``——
``--json`` 是**输入体**旗标（argv 携带 JSON 文本，``ensure_ascii=True`` 序列
化保证纯 ASCII，规避 cmd 包装层的多字节 argv 陷阱），非 wire-v1 的输出格式
尾标；正常输出默认即 JSON。错误契约（PROBE-NOTES §1.4 [live 实测]）：CLI 层
错误 envelope ``{"error":{"type","code","message"}}`` 走 exit 1（非零退出 →
``normalize_error``）；类型化响应体内 ``errcode``/``errmsg`` 族在**成功档**也
出现（``errcode: 0``）——所以退出 0 的负载还要过
:func:`_extract_error_code` 锚点（``errcode``/``code`` 双认）判错误档：退出
码为零不能替代业务证据。

Windows 解析：npm 全局安装的 wecom-cli 是 .cmd shim（PROBE-NOTES §5 实测三
shim 并存，``CreateProcess`` 打不开裸名——lark-cli.cmd/dws.cmd 同款教训）——
默认 ``wecom-cli.cmd``（win32）／``wecom-cli``（其余）。

**Payload 形状 provenance**：``contents get`` 的 ``errcode/content/url`` 与
search 零命中 envelope（``docs`` 族整族缺席）是 2026-09-08 live-captured
（``tests/fixtures/wecom-cli/FIXTURES-NOTE.md``）；hit 键位
（``docid/doc_name/doc_type/url/text_highlight``）与 ``name``/``version``/
``file_path`` 是 schema-only（纸面契约，真机未捕/已证缺席）。所有字段路径
集中在模块级 ``_extract_*`` 帮助函数：**键位对账锚点，payload 真值回填时只改
这里**（fixture 同步回填，按「键缺席即降级」写，不假设 schema 键全出现）。
"""

from __future__ import annotations

import json
import sys
from typing import Any

from kgent.adapters.cli_adapter import CliCapabilityAdapter, run_cli
from kgent.errors import AdapterError
from kgent.types import Document, DocumentMetadata, FilterSpec, SearchResult

__all__ = ["WeComAdapter"]

#: ``doc search`` body 的 ``limit`` 上限（PROBE-NOTES §1.2 [schema 实测]
#: ``limit`` ≤ 100）。更大 top_k 由 skill 车道翻页（``next_cursor``）解决。
_WECOM_SEARCH_LIMIT_MAX = 100


def _extract_document(payload: dict[str, Any]) -> dict[str, Any]:
    """``doc contents get`` 的目标块。锚点。

    FIXTURES-NOTE 冲突点 1 已 live 定谳：正常档是**顶层字段、无 ``data``
    包裹**（``errcode`` + 数据键直接在顶层）。保留本函数作为唯一取块点——
    envelope 形状若再漂移，只改这里。
    """
    return payload


def _extract_hits(payload: dict[str, Any]) -> list[Any]:
    """``doc search`` 命中列表（schema 契约容器键 ``docs[]``）。锚点。

    零命中 live 真值：``docs``/``docs_count``/``has_more``/``next_cursor``
    **整族缺席**（只剩 ``{"errcode":0,"errmsg":"ok"}``）——键缺席即降级为空
    列表，不假设 ``docs: []`` 必在。
    """
    docs = payload.get("docs")
    return docs if isinstance(docs, list) else []


def _extract_docid(item: dict[str, Any]) -> str:
    """稳定文档 ID（schema 契约 ``docid``；CLI 侧唯一稳定身份）。锚点。

    **URL token（``w3_`` 前缀）≠ API docid**（PROBE-NOTES §1.5 实测两串不同）
    ——身份只取 ``docid``，绝不从 ``url`` 提取；无 ``docid`` 的 hit 返回空串
    （调用方跳过：无稳定 ID 不进结果）。
    """
    value = item.get("docid")
    return str(value) if isinstance(value, str) and value else ""


def _extract_title(item: dict[str, Any]) -> str:
    """文档名：search hit 用 ``doc_name``，contents get 用 schema 的
    ``name``（真机实测缺席 → 空串，标题以 search hit 为准）。锚点。"""
    for key in ("doc_name", "name"):
        value = item.get(key)
        if value is not None:
            return str(value)
    return ""


def _extract_content(data: dict[str, Any]) -> str | None:
    """正文（真机短内容档内联 ``content``；缺席 → ``None``）。锚点。"""
    value = data.get("content")
    return str(value) if value is not None else None


def _extract_version(data: dict[str, Any]) -> str | None:
    """文档 ``version``（schema 契约 uint32；字符串化为 kgent 统一 version
    语义）。锚点。

    **真机定谳：响应不下发该键**（PROBE-NOTES 顶部定谳）→ 真机上恒 ``None``
    ——wecom undo 的新鲜度**不消费这个轴**（走 Task 2 写后全文快照通道）。保留
    锚点只为两件事：服务端将来真下发时一处回填；S65 一致性矩阵的 fake 方言
    让 wire-v1 的版本递增经本读车道可观测（dws ``revision`` 同款先例）。
    """
    value = data.get("version")
    return str(value) if value is not None else None


def _extract_snippet(item: dict[str, Any]) -> str | None:
    """hit 摘要：schema 契约 ``text_highlight`` 是 **string[]**（非 string）
    ——逐段拼接；容错 string 形态（payload 按未验证输入处理）。锚点。"""
    value = item.get("text_highlight")
    if isinstance(value, str):
        return value or None
    if isinstance(value, list):
        parts = [str(part) for part in value if part]
        return "\n".join(parts) if parts else None
    return None


def _extract_hit_url(item: dict[str, Any]) -> str | None:
    """hit 的原生 URL（schema 契约 ``url``，真机 ``contents get`` 同键实测在
    场）。锚点。"""
    value = item.get("url")
    return str(value) if isinstance(value, str) and value else None


def _extract_hit_type(item: dict[str, Any]) -> str | None:
    """hit 的产品类型字段（schema 契约 ``doc_type``：``doc|sheet|smartsheet|
    smartpage``，server fact）。锚点。"""
    value = item.get("doc_type")
    return str(value) if isinstance(value, str) and value else None


def _extract_error_code(payload: dict[str, Any]) -> int | None:
    """错误档的 code（893000–893299 兜底 893999；envelope 键 ``errcode``/
    ``code`` 双认——FIXTURES-NOTE 冲突点 3 的类型化响应体一侧）。锚点。

    成功档也带 ``errcode: 0``（live 实测）→ 只把非零 int 当错误。
    """
    for key in ("errcode", "code"):
        value = payload.get(key)
        if isinstance(value, int) and value != 0:
            return value
    return None


def _node_type_from_hit(item: dict[str, Any]) -> str:
    """Server-fact 节点类型，值域只有 ``doc``|``wiki_node``（§7.2 词表）。

    判定梯（每级只消费服务端事实，不从 token 形状推断——N23 纪律；wecom 无
    wiki/knowledge-space 概念，词表另一端 ``wiki_node`` 不存在）：

    1. hit 的 ``doc_type`` 字段（schema 契约，server fact）优先——``doc`` 是
       词表内值直落；``sheet``/``smartsheet``/``smartpage`` 出词表 → 落
       ``doc``，绝不虚构词表另一端（lark bitable / dingtalk 非文字产品同款
       纪律）。
    2. ``doc_type`` 缺席 → URL ``<type>`` 路径段兜底——实测值 ``doc``
       （PROBE-NOTES §3），其余三型 PENDING；wecom URL 无 wiki 域 → ``doc``。
    3. 其余（两事实皆缺）→ ``doc``。

    三级在当前 §7.2 词表约束下同落 ``doc``：判型梯在这里展开是为了让每一级
    的服务端事实有唯一消费点（skill 委派矩阵消费同一对锚点
    :func:`_extract_hit_type`/:func:`_extract_hit_url`），将来词表或 wecom
    产品面变化时只改对应级。
    """
    if _extract_hit_type(item) is not None:
        return "doc"
    if _extract_hit_url(item) is not None:
        return "doc"
    return "doc"


class WeComAdapter(CliCapabilityAdapter):
    """WeCom documents adapter — read lanes over ``wecom-cli``, writes via skill.

    读车道接真 wecom-cli（``doc contents get`` / ``doc search``，见模块
    docstring）；create/update/delete/archive/check_version 等**不接**——沿用
    wire-v1 基类实现仅用于测试替身与 hosted backend 车道，一切真实写入经
    wecom-integration skill（ADR 0004）。
    """

    def __init__(self, cmd: list[str] | None = None, timeout: float = 30.0) -> None:
        # On Windows, use wecom-cli.cmd for subprocess compatibility (npm shim)
        if cmd is None:
            cmd = ["wecom-cli.cmd" if sys.platform == "win32" else "wecom-cli"]
        super().__init__(cmd, "wecom", timeout)

    def _run_wecom(self, service_args: list[str], body: dict[str, Any]) -> dict[str, Any]:
        """Run ``self.cmd + service_args + ["--json", <body>]``, decode one JSON object.

        ``--json`` 是输入体旗标（模块 docstring）：body 经 ``ensure_ascii=True``
        序列化为纯 ASCII argv 元素（cmd 包装层对多字节 argv 的 first-block 教训；
        docid/limit 等值本就 ASCII，中文关键词也走 ``\\uXXXX`` 转义）。错误规范
        化与 wire-v1 :meth:`CliCapabilityAdapter._run` 对齐：非零退出 →
        ``normalize_error``；退出 0 但非 JSON／非对象／错误档（:func:
        `_extract_error_code` 或 CLI 层 ``error`` envelope）→ :class:`AdapterError`
        ——退出码为零不能替代业务证据（dws contracts 同款）。速率退避不在此层
        （skill 车道纪律，见 wecom-integration SKILL.md）。
        """
        argv = self.cmd + service_args + ["--json", json.dumps(body, ensure_ascii=True)]
        self._check_argv(argv)
        result = run_cli(argv, timeout=self.timeout)
        if result.returncode != 0:
            raise self.normalize_error(result.returncode, result.stderr)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AdapterError(
                f"adapter {self.name!r}: CLI exited 0 with malformed JSON stdout: "
                f"{result.stdout[:200]!r}"
            ) from exc
        if not isinstance(payload, dict):
            raise AdapterError(
                f"adapter {self.name!r}: CLI exited 0 with non-object JSON: {result.stdout[:200]!r}"
            )
        code = _extract_error_code(payload)
        if code is not None:
            raise AdapterError(
                f"adapter {self.name!r}: CLI reported error on exit 0 "
                f"(code {code}): {payload.get('errmsg') or payload.get('message') or payload}"
            )
        if payload.get("error"):
            # CLI 层错误 envelope 真机走 exit 1（PROBE-NOTES §1.4）；exit 0
            # 出现该键是容错档，与基类 _run 的同款检查对齐。
            raise AdapterError(
                f"adapter {self.name!r}: CLI reported error on exit 0: {payload['error']}"
            )
        return payload

    def read_document(self, doc_uri: str) -> Document:
        """Deprecated (skills): 平台操作经 wecom-integration（ADR 0004）；CLI 面保留供调试与 kgent hosted backend 车道。

        Read via ``wecom-cli doc contents get --json {"docid": <id>}``。正文取
        内联 ``content``；``version`` → ``metadata.version``（真机定谳不下发 →
        ``None``，``kgent undo`` 补偿计划落 Task 2 写后全文快照比对路径，
        ledger.py 消费本方法返回的 ``content``）。

        长内容落盘 ``file_path`` 的相对/绝对语义与 Fs 沙箱边界未定谳
        （FIXTURES-NOTE 冲突点 4）——真值样本落地前**不消费该键**：正文键缺席
        即 fail closed（显式 :class:`AdapterError`），不猜路径读盘。
        """
        native_id = self._native_id(doc_uri)
        payload = self._run_wecom(["doc", "contents", "get"], {"docid": native_id})
        data = _extract_document(payload)
        title = _extract_title(data)
        content = _extract_content(data)
        if content is None:
            raise AdapterError(
                f"adapter {self.name!r}: contents get returned no inline content "
                f"(long-content file_path semantics are not consumed until a live "
                f"sample lands — FIXTURES-NOTE 冲突点 4): "
                f"{json.dumps(payload, ensure_ascii=False)[:200]!r}"
            )
        meta = DocumentMetadata(
            doc_uri=doc_uri,
            title=title,
            backend=self.name,
            version=_extract_version(data),
            node_type=_node_type_from_hit(data),
        )
        return Document(doc_uri=doc_uri, title=title, content=content, metadata=meta)

    def search_by_keywords(
        self,
        query: str,
        filters: FilterSpec | None = None,
        top_k: int = 10,
        fields: list[str] | None = None,
    ) -> list[SearchResult]:
        """Deprecated (skills): 平台操作经 wecom-integration（ADR 0004）；CLI 面保留供调试与 kgent hosted backend 车道。

        Search via ``wecom-cli doc search --json {"keywords": [<q>], ...}``
        （PROBE-NOTES §1.2 探针实测的调用形状；``search_scope`` 固定
        ``title_content``——schema 默认档）；hit 类型经
        :func:`_node_type_from_hit`（B11-wecom 保真，见该函数判定梯）。
        ``limit`` 封顶 :data:`_WECOM_SEARCH_LIMIT_MAX`（schema ≤100）；零命中
        容忍 ``docs`` 族整族缺席（live 真值）。``filters``/``fields`` 本车道
        未消费（``doc_types``/``creator_userids``/``cursor`` 等旗标归 skill
        车道按需展开）。
        """
        limit = min(top_k, _WECOM_SEARCH_LIMIT_MAX)
        payload = self._run_wecom(
            ["doc", "search"],
            {"keywords": [query], "search_scope": "title_content", "limit": limit},
        )
        results: list[SearchResult] = []
        for item in _extract_hits(payload):
            if not isinstance(item, dict):
                continue
            native_id = _extract_docid(item)
            if not native_id:
                continue  # 无稳定 ID 的 hit 不进结果（docid 是唯一稳定身份）
            uri = self._canonical(native_id)
            title = _extract_title(item)
            snippet = _extract_snippet(item)
            node_type = _node_type_from_hit(item)
            try:
                rank = int(item.get("rank", 0))  # 真机 hit 无 rank 字段 → 0
            except (TypeError, ValueError):
                rank = 0
            meta = DocumentMetadata(
                doc_uri=uri,
                title=title,
                backend=self.name,
                node_type=node_type,
            )
            results.append(
                SearchResult(
                    doc_uri=uri,
                    metadata=meta,
                    rank=rank,
                    snippet=snippet,
                    mode_used="keyword",
                    node_type=node_type,
                )
            )
        return results[:top_k]
