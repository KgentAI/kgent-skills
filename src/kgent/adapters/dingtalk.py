"""DingTalk adapter (§1.3): read lanes over ``dws`` (npm ``dingtalk-workspace-cli``).

Deprecated (skills): 平台操作经 dingtalk-integration（ADR 0004）；CLI 面保留供
调试与 kgent hosted backend 车道。Phase 2 接真 dws 的**读**车道：

- :meth:`DingTalkAdapter.read_document` — ``doc +fetch --node <id>``；
  ``revision`` → ``metadata.version``，是 ``kgent undo`` 补偿计划期的新鲜度
  数据源（B6 依赖当前 revision）。
- :meth:`DingTalkAdapter.search_by_keywords` — ``doc +search --query``；
  hit 的 ``node_type`` 只从服务端事实判定（:func:`_node_type_from_hit`，B11
  search 类型保真）。

写车道**不接**：create/update/delete 沿用 wire-v1 基类实现（未覆盖），一切
DingTalk 写入经 dingtalk-integration skill（ADR 0004）——journal 台账、
revision 条件写（``--expected-revision``）与 version-revert 补偿都活在 skill
侧；CLI 写车道留给 kgent hosted backend 启用时再议（母 spec 非目标节）。

Windows 解析：npm 全局安装的 dws 是 .cmd shim，``CreateProcess``（``shell=False``）
打不开裸名（WinError 2，lark-cli.cmd 同款教训；PROBE-NOTES §5 实测三 shim 并存）——
默认 ``dws.cmd``（win32）／``dws``（其余）。

**Payload 形状 provenance**：无真机捕获（credentials unavailable, 2026-09-08，
维护者裁决）——外层/容器键来自原生 dingtalk-* skill 文档（doc.operation.v1
envelope、分页 `complete/hasMore`、目标 `nodeId`/URL），叶子键名是文档语义名
的构造值。所有字段路径集中在模块级 ``_extract_*`` 帮助函数：**键位对账锚点，
payload 真值回填时只改这里**（fixture 同步回填，见
``tests/fixtures/dws/FIXTURES-NOTE.md`` 的逐键 provenance 与文档冲突点）。
"""

from __future__ import annotations

import json
import sys
from typing import Any
from urllib.parse import urlparse

from kgent.adapters.cli_adapter import CliCapabilityAdapter, run_cli
from kgent.errors import AdapterError
from kgent.types import Document, DocumentMetadata, FilterSpec, SearchResult

__all__ = ["DingTalkAdapter"]

#: ``doc +search --limit`` 的文档上限（PROBE-NOTES §1.2 [help 实测]：默认 10、
#: 最大 30）；更大 top_k 分页解决，读车道不追加 ``--page-all``（全量翻页是
#: skill 车道的语义，fanout 超时预算 S33 由调用方持有）。
_DWS_SEARCH_LIMIT_MAX = 30


def _extract_hits(payload: dict[str, Any]) -> list[Any]:
    """``doc +search`` 命中列表。键位对账锚点：payload 真值回填时只改这里。

    documented shape：doc.operation.v1 外层（dingtalk-doc contracts.md）下命中
    在 ``items[]``——外层 ``complete/count/failures`` 有 SKILL.md 实证，容器键名
    本身是 PROBE-NOTES §2 PENDING 项（FIXTURES-NOTE 冲突点 2）。
    """
    items = payload.get("items")
    return items if isinstance(items, list) else []


def _extract_document(payload: dict[str, Any]) -> dict[str, Any]:
    """``doc +fetch`` 的目标块（``data``，doc-create.md 同款 envelope）。锚点同上。"""
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def _extract_native_id(item: dict[str, Any]) -> str:
    """hit/目标块的稳定文档 ID（contracts.md：目标至少保留 ``nodeId``）。锚点同上。"""
    value = item.get("nodeId")
    return str(value) if value else ""


def _extract_title(item: dict[str, Any]) -> str:
    """文档名称（contracts.md：名称/标题不是稳定身份，仅作展示）。锚点同上。

    fetch ``data`` 与 search hit 共用 ``title`` 键。
    """
    value = item.get("title")
    return str(value) if value is not None else ""


def _extract_content(data: dict[str, Any]) -> str:
    """Markdown 正文（``--detail simple`` 默认档；doc-read.md）。锚点同上。

    dws 的正文不内嵌文档名 H1（``+create`` 纪律：正文不重复同名一级标题），
    所以不做 lark 的 ``# title`` 剥离。
    """
    value = data.get("content")
    return str(value) if value is not None else ""


def _extract_revision(data: dict[str, Any]) -> str | None:
    """文档编辑版本号 ``revision``（≠ 历史版本号 ``version``——双轴，PROBE-NOTES
    §1.1 实测）。B6 undo 计划期新鲜度数据源。锚点同上。

    ``--expected-revision`` 是 int 轴，kgent 统一存字符串（§3.9 version 语义）；
    CLI 输出按未验证输入处理，非数值（如 fake 的 ``"v1"``）原样字符串化不抛。
    """
    value = data.get("revision")
    return str(value) if value is not None else None


def _extract_snippet(item: dict[str, Any]) -> str | None:
    """hit 摘要。锚点同上。"""
    value = item.get("snippet")
    return str(value) if value is not None else None


def _extract_hit_url(item: dict[str, Any]) -> str | None:
    """hit 的 canonical URL（contracts.md：服务返回时保留）。锚点同上。"""
    value = item.get("url")
    return str(value) if isinstance(value, str) and value else None


def _extract_hit_type(item: dict[str, Any]) -> str | None:
    """hit 的类型字段：``type``，别名 ``extension``（dingtalk-wiki
    wiki-node-ops：两者互为规范化别名；dingtalk-shared：路由依据是
    ``extension``）。锚点同上。"""
    for key in ("type", "extension"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _extract_workspace_id(item: dict[str, Any]) -> str | None:
    """知识库（workspace）容器事实——wiki-node-ops 的节点容器字段族。锚点同上。"""
    value = item.get("workspaceId")
    return str(value) if value else None


#: 文档化的非文字文档产品值（dingtalk-shared url-patterns 探测映射 + wiki
#: node-create ``--type`` 枚举）：命中这些值说明 hit 不是在线文字文档——§7.2
#: 词表只有 ``doc``|``wiki_node``，落回 ``doc``，绝不伪装成词表另一端（lark
#: bitable hit 同款纪律）。
_NON_DOC_TYPES = frozenset(
    {"axls", "able", "appt", "adraw", "amind", "folder", "xlsx", "xls", "xlsm", "csv"}
)


def _node_type_from_hit(item: dict[str, Any]) -> str:
    """Server-fact 节点类型，值域只有 ``doc``|``wiki_node``（§7.2 词表）。

    判定顺序（每步只消费服务端事实，不从 token 形状推断——N23 纪律）：

    1. URL 路径段——仅 dingtalk-shared url-patterns 文档化的事实形状：
       ``/document/``（``document/{edit|preview}``、``/i/document/``）只承载
       文档 → ``doc``；``/spreadsheetv2/`` 只承载电子表格 → 出词表，落 ``doc``。
       ``/i/nodes/`` 文档明确「不编码类型」（文档/表格/多维表/文件/文件夹共用
       同一形状）→ **不判定**；``/i/p/`` 分享短链不可作内容入口 → 不判定。
    2. 类型字段（:func:`_extract_hit_type`）：``adoc`` 以外的文档化产品值
       （:data:`_NON_DOC_TYPES`）→ 非文字文档，落 ``doc``。
    3. 知识库容器事实（:func:`_extract_workspace_id`）→ ``wiki_node``——B11
       保真落点：知识库内文档 ≠ 文档空间扁平文档（知识库 URL 形状
       [PENDING-凭据]，路径段判不出，容器事实兜底）。
    4. 其余一律 ``doc``。

    与 dingtalk-integration skill（Search 节）同一条规则的两处落点：hit 自带
    事实不足且类型影响路由时，skill 车道按 dingtalk-shared 的 URL 类型预检升级
    （``drive info --node`` 看 ``extension``）；adapter 读车道不做额外探针
    （零成本保真——只消费 hit 自带字段）。
    """
    url = _extract_hit_url(item)
    if url is not None:
        path = urlparse(url).path
        if "/document/" in path or "/spreadsheetv2/" in path:
            return "doc"
    hit_type = _extract_hit_type(item)
    if hit_type is not None and hit_type.lower() in _NON_DOC_TYPES:
        return "doc"
    if _extract_workspace_id(item) is not None:
        return "wiki_node"
    return "doc"


class DingTalkAdapter(CliCapabilityAdapter):
    """DingTalk documents adapter — read lanes over ``dws``, writes via skill.

    读车道接真 dws（``doc +fetch`` / ``doc +search``，见模块 docstring）；
    create/update/delete/archive/check_version 等**不接** dws——沿用 wire-v1
    基类实现仅用于测试替身与 hosted backend 车道，一切真实写入经
    dingtalk-integration skill（ADR 0004）。
    """

    def __init__(self, cmd: list[str] | None = None, timeout: float = 30.0) -> None:
        # On Windows, use dws.cmd for subprocess compatibility (npm shim)
        if cmd is None:
            cmd = ["dws.cmd" if sys.platform == "win32" else "dws"]
        super().__init__(cmd, "dingtalk", timeout)

    def _run_dws(self, args: list[str]) -> dict[str, Any]:
        """Run ``self.cmd + args + ["-f", "json"]`` and decode one JSON object.

        dws 的格式旗标是 ``-f/--format json``（默认即 json，显式传入只为契约
        自明；PROBE-NOTES §1.4 [help 实测]），不是 wire-v1 的 ``--json`` 尾标——
        所以这层不走基类 :meth:`CliCapabilityAdapter._run`，错误规范化
        （``normalize_error``／malformed JSON → :class:`AdapterError`）与之对齐。
        """
        argv = self.cmd + args + ["-f", "json"]
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
        if payload.get("ok") is False:
            # contracts.md：退出码为零不能替代业务证据——envelope ok=false 即失败。
            raise AdapterError(
                f"adapter {self.name!r}: CLI reported failure on exit 0: "
                f"{payload.get('status') or payload.get('error') or payload}"
            )
        return payload

    def read_document(self, doc_uri: str) -> Document:
        """Deprecated (skills): 平台操作经 dingtalk-integration（ADR 0004）；CLI 面保留供调试与 kgent hosted backend 车道。

        Read via ``dws doc +fetch --node <id>``（PROBE-NOTES §1.1 [help 实测]：
        fetch 无位置参数，``--node`` 旗标；``+`` 组合入口 §1.3）。``revision``
        → ``metadata.version``——``kgent undo`` 补偿计划期新鲜度数据源（B6）。

        节点类型沿用 :func:`_node_type_from_hit` 消费 fetch 响应自带的
        URL/类型/容器事实（fetch 不再做 lark 式 ``wiki +node-get`` 探针——dws
        读响应即带类型事实）。
        """
        native_id = self._native_id(doc_uri)
        payload = self._run_dws(["doc", "+fetch", "--node", native_id])
        data = _extract_document(payload)
        title = _extract_title(data)
        content = _extract_content(data)
        meta = DocumentMetadata(
            doc_uri=doc_uri,
            title=title,
            backend=self.name,
            version=_extract_revision(data),
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
        """Deprecated (skills): 平台操作经 dingtalk-integration（ADR 0004）；CLI 面保留供调试与 kgent hosted backend 车道。

        Search via ``dws doc +search --query <q> --limit <n>``；hit 类型经
        :func:`_node_type_from_hit`（B11）。``--limit`` 封顶
        :data:`_DWS_SEARCH_LIMIT_MAX`（文档上限 30）；``filters``/``fields``
        本车道未消费（doc +search 无对应旗标——词法对账见 PROBE-NOTES §1.2）。
        """
        limit = min(top_k, _DWS_SEARCH_LIMIT_MAX)
        payload = self._run_dws(["doc", "+search", "--query", query, "--limit", str(limit)])
        results: list[SearchResult] = []
        for item in _extract_hits(payload):
            if not isinstance(item, dict):
                continue
            native_id = _extract_native_id(item)
            if not native_id:
                continue  # 无稳定 ID 的 hit 不进结果（contracts.md 目标契约）
            uri = self._canonical(native_id)
            title = _extract_title(item)
            try:
                rank = int(item.get("rank", 0))  # CLI payload is unvalidated input
            except (TypeError, ValueError):
                rank = 0
            snippet = _extract_snippet(item)
            node_type = _node_type_from_hit(item)
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
