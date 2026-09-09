"""B6/B8 真机：dingtalk 探针文档 undo 计划 → dws version-revert 闭环。

ADR 0004/0005 的 dingtalk 侧真机验收载体：kgent 台账 begin/end → ``kgent undo``
只产补偿计划（mechanism=version-revert、integration_skill=dingtalk-integration），
执行归 dingtalk-integration skill——本测试扮演该 skill，按 ``history_hint`` 用
``dws doc +version-list`` 定位写前 version、``doc +version-revert`` 完成补偿并读回
断言还原（B6），另以多段中文 + emoji 内容的写入/读回全量保真压 first-block 事故
回归（B8/FM7），并以写后并发编辑验证计划期拒绝（FM2）。

**本环境现状（维护者裁决，2026-09-08）**：无可用钉钉账号——dws 未装或
``dws auth status -f json`` 报 ``authenticated: false`` 时整文件 skip（凭据门），
本文件是凭据就绪后的真机执行载体。命令拼写真值：
``tests/fixtures/dws/PROBE-NOTES.md``；payload 键位 PENDING 项：同目录
``FIXTURES-NOTE.md``。凭据就绪后的前置：``~/.kgent/config.yaml`` 里
``backends.dingtalk.enabled: true``（dingtalk-integration skill 的 The Gate）——
undo 计划期的新鲜度读（FM2）经 :class:`kgent.adapters.dingtalk.DingTalkAdapter`
走这条门。

与 brief 逐字稿的真机修正/契约（沿用 lark 版 task-11-report 的纪法）：
1. ``kgent`` 经 ``sys.executable -m kgent``（或 ``KGENT_BIN``）解析——PATH 上的
   ``kgent`` 是旧安装（artifact-smoke 层职责），必须打仓库源码。
2. ``--json`` 放在叶子子命令末尾——argparse 子解析器在独立 namespace 解析后覆盖
   父 namespace，顶层或夹中间的 ``--json`` 会被叶子默认值 ``False`` 静默覆盖。
3. ``dws`` 在 Windows 上解析 ``dws.cmd``（``shutil.which`` 尊重 PATHEXT；npm 全局
   装出 ``dws``/``dws.cmd``/``dws.ps1`` 三 shim，PROBE-NOTES §5——``shell=False``
   不自动补 .cmd，lark-cli.cmd 同款教训）。
4. **确认门**：``doc +update``／``doc +version-revert``／``drive +delete`` 都是
   ``confirmation=user_required``（PROBE-NOTES §1.2；dws help 原文「Do not use
   --yes until the user explicitly confirms this operation」）→ 缺省**禁 -y**。
   dws 二进制自述：非交互环境（Agent/CI，stdin 非 TTY）写命令不带 ``--yes`` 会被
   CLI 直接阻断、不落交互提示——真机验收因此必须是有人的运行：操作者对回滚/删除
   明示同意后设 ``DWS_PROBE_CONFIRM=yes`` 再跑（该设置即本探针的用户确认记录，
   每次带 -y 的调用都会打印审计说明）。
5. payload 键位**live-captured 2026-09-09**（兑现轮首跑 3/3 failed 定谳 + 修复轮
   回填；closure report §3 全文、``tests/fixtures/dws/FIXTURES-NOTE.md`` 锚点表）：
   fetch 目标块是顶层 ``content``（``doc.content.v1``，外层无 ``data``），
   ``revision`` 只在 ``--detail with-ids`` 档（**字符串**，``"1"``）且该档正文键是
   ``jsonml`` 非 ``markdown``；version-list 条目**无 revision 字段**；create 响应
   （``doc.operation.v1``）全块无 revision。解析集中在 ``_extract_*`` 锚点，
   取不到就打印原 payload 供再定谳（不按占位假设硬编码）。
6. 双轴纪律：``revision`` = 编辑号（台账 begin/end、``--expected-revision`` 条件写）；
   ``version`` = 历史快照号（``+version-list``/``+version-revert``）——不混用；
   两轴的映射走 ``+fetch --version N --detail with-ids`` 读 ``content.revision``
   （真机实测 1:1：``--version 0 → "0"``、``1 → "1"``）。
7. undo 补偿与 revert 读回都是异步平台操作 → 有界轮询（lark 版 ``_poll_content``
   同款；version 建点也可能异步稀疏 → ``_wait_version_point``）。
8. teardown：doc 域**无删除命令**——探针删除走 drive 域
   ``drive +delete --node <DOC_ID>``（进回收站，可恢复）。删除句柄 live-captured
   定谳：**就是 DOC_ID 本体**（``drive +info`` 的 ``data.fileId``、
   ``drive +find-file`` 的 ``files[].dentryId`` 均等于 DOC_ID）；``drive +info``
   的 ``data.dentryId`` 是 12 位内部号，``drive +delete`` 拒收——兑现轮 teardown
   三连败的根因。``drive +info`` 只作句柄可用性早验（report §7.3 的 fail-fast），
   解析失败不阻塞删除（句柄兜底直用 DOC_ID）；仍失败 session 末重试 + 点名
   （lark 版 ``_leftover_tokens``/``_retry_leftovers`` 同构）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.real]

#: 仓库无 pytest marker 注册表（pyproject 无 ``markers`` 配置）：``e2e``/``real``
#: 直接打标，仅作筛选契约，靠 skipif 做真机门。

# ---------------------------------------------------------------------------
# 可调常量区 —— dws 命令真值（PROBE-NOTES §1 [help 实测]）；真值漂移只改本区
# ---------------------------------------------------------------------------

PROBE_TITLE = "kgent-phase2-probe-临时"
#: B8 用独立标题：同名前缀纪律不变，人工清理时能与 B6 探针区分。
PROBE_TITLE_B8 = "kgent-phase2-probe-完整性"

CONTENT_A = "AAA-CONTENT"
CONTENT_B = "BBB-CONTENT"
CONTENT_C = "CCC-CONTENT"
#: B8：多段中文 + emoji + 中文标点——first-block 事故回归装甲（FM7）
CONTENT_B8 = (
    "# Phase 2 完整性探针\n\n"
    "第一段中文内容，包含「中文标点」。\n\n"
    "第二段含 emoji ❤️🎉 与多行\n换行内容。\n"
)

#: 探针生命周期命令（PROBE-NOTES §1.2/§1.3：固定用「+」组合入口，原生入口只作逃生舱）
CMD_CREATE = ("doc", "+create")  # --name <标题> --content @<相对文件> --doc-format markdown
CMD_FETCH = ("doc", "+fetch")  # --node <DOC_ID>
CMD_UPDATE = (
    "doc",
    "+update",
)  # --node --command overwrite --doc-format jsonml --content @<相对文件> --expected-revision <rev>
CMD_VERSION_LIST = ("doc", "+version-list")  # --node <DOC_ID>
CMD_VERSION_REVERT = ("doc", "+version-revert")  # --node <DOC_ID> --version <N>
CMD_DRIVE_INFO = ("drive", "+info")  # --node <节点 ID>（两域 ID 解析探针）
CMD_DRIVE_DELETE = ("drive", "+delete")  # --node <dentryUuid>（teardown，进回收站）
CMD_DRIVE_FIND_FILE = ("drive", "+find-file")  # --query <名称关键词>（人工清理定位）

FLAG_NODE = "--node"
FLAG_NAME = "--name"
FLAG_CONTENT = "--content"
FLAG_DOC_FORMAT = "--doc-format"
DOC_FORMAT_MARKDOWN = "markdown"
DOC_FORMAT_JSONML = "jsonml"
FLAG_COMMAND = "--command"
UPDATE_OVERWRITE = "overwrite"
UPDATE_APPEND = "append"
#: 条件写旗标——服务端原子契约**仅 overwrite + jsonml 组合生效**（PROBE-NOTES §1.1）
FLAG_EXPECTED_REVISION = "--expected-revision"
FLAG_VERSION = "--version"  # 版本轴（≠ revision 轴，修正 6）
FLAG_QUERY = "--query"
#: fetch 保真度档位（PROBE-NOTES §1.2：``simple|with-ids|full``）。live-captured
#: （2026-09-09，closure report §3.1/§3.2）：默认档（simple）正文键 ``markdown``
#: 但**无 revision**；``with-ids`` 档带 ``content.revision``（字符串）但正文键是
#: ``jsonml``——没有任何单档同时携带两者，所以取 revision 的 fetch 一律带本档。
FLAG_DETAIL = "--detail"
DETAIL_WITH_IDS = "with-ids"

#: dws 格式旗标（PROBE-NOTES §1.4：``-f/--format json``，默认即 json，显式传为契约自明）
DWS_FORMAT_FLAGS = ("-f", "json")

#: confirmation=user_required 的命令（修正 4）：缺省禁 -y，操作者 opt-in 才放行
CONFIRM_ENV = "DWS_PROBE_CONFIRM"
_CONFIRM_REQUIRED_COMMANDS = frozenset({CMD_UPDATE, CMD_VERSION_REVERT, CMD_DRIVE_DELETE})

#: 有界轮询预算（version 建点 / revert 读回异步——修正 7）
_VERSION_POLL_ROUNDS = 12
_VERSION_POLL_INTERVAL_SECONDS = 5
_READBACK_POLL_ROUNDS = 6
_READBACK_POLL_INTERVAL_SECONDS = 2

#: with-ids 读的瞬态服务端超时重试（live-captured 2026-09-09 复跑现场：
#: create 后立刻读 JSONML 档撞 HSFTimeOutException/3000ms——读幂等，重试安全）
_TRANSIENT_READ_RETRIES = 2
_TRANSIENT_READ_BACKOFF_SECONDS = 2

DWS_TIMEOUT_SECONDS = 120
KGENT_TIMEOUT_SECONDS = 120

#: teardown 删除失败的探针 DOC_ID（供 session 末重试 + 人工清理提示）
_leftover_probes: list[str] = []
#: 已成功删除的探针 DOC_ID（``_teardown`` 幂等短路，见其 docstring）
_cleaned_probes: set[str] = set()


# ---------------------------------------------------------------------------
# 进程封装
# ---------------------------------------------------------------------------


def _utf8_stdio() -> None:
    """探针 evidence 打印含 CJK/emoji/payload 原文，Windows 控制台缺省编码
    （cp1252/cp936）下 ``print`` 直接 :exc:`UnicodeEncodeError`——会把一次本来
    成功的真机运行打断（lark 版 prints 全 ASCII 的同一教训的另一面）。统一把
    stdio 收敛到 UTF-8，``errors="replace"`` 兜底保证打印本身绝不抛。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):  # 已关闭/非文本流：打印走 replace 兜底即可
            pass


_utf8_stdio()


def _kgent() -> list[str]:
    """仓库源码的 kgent 调用形态（模块 docstring 修正 1）。"""
    override = os.environ.get("KGENT_BIN")
    if override:
        return [override]
    return [sys.executable, "-m", "kgent"]


def _dws_cmd() -> list[str]:
    """dws 的可执行形态：Windows 上解析 ``dws.cmd``（模块 docstring 修正 3）。

    与 :class:`kgent.adapters.dingtalk.DingTalkAdapter` 同一规则；``shutil.which``
    返回完整路径（顺带规避 PATH 上无扩展名 sh shim 的 bash 语义误用）。
    """
    override = os.environ.get("DWS_BIN")
    if override:
        return [override]
    resolved = shutil.which("dws.cmd") if sys.platform == "win32" else None
    if resolved is None:
        resolved = shutil.which("dws")
    return [resolved] if resolved else ["dws"]


def _confirmation_flags() -> tuple[str, ...]:
    """confirmation=user_required 命令的 ``-y`` 通道（缺省禁用，修正 4）。"""
    if os.environ.get(CONFIRM_ENV, "").strip().lower() == "yes":
        return ("-y",)
    return ()


def _dws(
    *args: str,
    cwd: Path | None = None,
    check: bool = True,
    timeout: int = DWS_TIMEOUT_SECONDS,
    error_payload: bool = False,
) -> dict[str, Any] | None:
    """跑一条 dws 命令并解析 JSON envelope（``-f json`` 收尾，PROBE-NOTES §1.4）。

    ``args`` 不含格式/确认旗标——两者集中在这层：``-f json`` 统一收尾；
    confirmation=user_required 命令的 ``-y`` 只在操作者显式 opt-in
    （:data:`CONFIRM_ENV`）时追加，追加时打印一行审计说明。

    ``check=True``（默认）：非零退出、非 JSON 或 envelope ``ok=False`` →
    AssertionError（带 stdout/stderr 尾部，真机排障用）。``check=False``
    （teardown/探测）：失败打印并返回 ``None``，由调用方点名。
    ``error_payload=True``（配合 ``check=False``）：失败时进一步解析错误
    envelope（rc=1 的错误 JSON 实测整份在 **stderr**——``doc +update`` 的
    ``doc_write_verification_failed`` 现场 live-captured 2026-09-09）返回给
    调用方分类；解析不出仍返回 ``None``。
    ``cwd`` 锚定 ``@file`` 的工作目录相对语义（PROBE-NOTES §4）。
    """
    confirm = _confirmation_flags() if args[:2] in _CONFIRM_REQUIRED_COMMANDS else ()
    argv = [*_dws_cmd(), *args, *confirm, *DWS_FORMAT_FLAGS]
    if confirm:
        print(
            f"[dws confirmation] {CONFIRM_ENV}=yes (operator consent) -> -y for: {' '.join(argv)}"
        )
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(cwd) if cwd is not None else None,
            timeout=timeout,
            check=False,
            stdin=subprocess.DEVNULL,  # 确认门：任何等待输入都立即 EOF，不挂起
        )
    except (OSError, subprocess.SubprocessError) as exc:
        if check:
            raise AssertionError(f"dws {' '.join(args)} could not run: {exc}") from exc
        print(f"dws {' '.join(args)} could not run: {exc}")
        return None
    payload: dict[str, Any] | None = None
    try:
        decoded = json.loads(proc.stdout)
        payload = decoded if isinstance(decoded, dict) else None
    except ValueError:
        payload = None
    failed = proc.returncode != 0 or payload is None or payload.get("ok") is False
    if check:
        assert not failed, (
            f"dws {' '.join(args)} failed:\n"
            f"  rc={proc.returncode}\n"
            f"  stdout={proc.stdout[-800:]}\n"
            f"  stderr={proc.stderr[-800:]}"
        )
        return payload
    if failed:
        print(
            f"dws {' '.join(args)} failed (rc={proc.returncode}): "
            f"stdout={proc.stdout[-400:]!r} stderr={proc.stderr[-400:]!r}"
        )
        if error_payload:
            for text in (proc.stderr, proc.stdout):
                try:
                    decoded = json.loads(text)
                except ValueError:
                    continue
                if isinstance(decoded, dict):
                    return decoded
        return None
    return payload


def _kgent_json(command: str, *rest: str, ok_rc: tuple[int, ...] = (0,)) -> dict[str, Any]:
    """``--json`` 放在整条子命令路径的**末尾**（模块 docstring 修正 2）。

    ``ok_rc``：命令的退出码契约。``kgent undo`` 对 **rejected 计划按设计退 1**
    （``src/kgent/cli.py``：「return 0 if plan["status"] == "ok" else 1」；
    live-captured 2026-09-09 FM2 现场证实：rc=1 + stdout 全量 JSON 证据）——
    证据在 stdout，调用方用 ``ok_rc=(0, 1)`` 放行后按 JSON 断言 status。
    """
    out = subprocess.run(
        [*_kgent(), command, *rest, "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=KGENT_TIMEOUT_SECONDS,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    if out.returncode not in ok_rc:
        raise AssertionError(
            f"kgent {command} {' '.join(rest)} failed:\n"
            f"  rc={out.returncode}\n"
            f"  stdout={out.stdout[-800:]}\n"
            f"  stderr={out.stderr[-800:]}"
        )
    try:
        return json.loads(out.stdout)
    except ValueError as exc:
        raise AssertionError(
            f"kgent {command} {' '.join(rest)} printed non-JSON stdout: {out.stdout[:400]!r}"
        ) from exc


# ---------------------------------------------------------------------------
# payload 键位对账锚点（修正 5：候选键容错 + 取不到打印原 payload 供补捕定谳）
# ---------------------------------------------------------------------------


def _extract_data(payload: dict[str, Any]) -> dict[str, Any]:
    """doc.operation.v1 envelope 的目标块（``data``）。

    live-captured（2026-09-09，closure report §3 / fixtures ``drive-delete.json``
    同款）：create/update/delete 系命令走该 envelope，``data.nodeId`` 真机证实；
    **fetch 不走它**（``doc.content.v1`` 的目标是顶层 ``content``，见
    :func:`_extract_content_block`）。
    """
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def _extract_content_block(payload: dict[str, Any]) -> dict[str, Any]:
    """``doc +fetch``（``doc.content.v1`` envelope）的目标块。

    live-captured（2026-09-09，closure report §3.1）：fetch 外层是
    ``complete/content/contractVersion/status/target``——目标是**顶层 ``content``**，
    外层没有 ``data``（兑现轮 B8 断言死在 ``data.content`` 空串上的根因）。
    ``data`` 保留为 documented-not-captured 旧锚点兜底。
    """
    block = payload.get("content")
    if isinstance(block, dict):
        return block
    return _extract_data(payload)


def _fetch_detail(doc_id: str, *extra: str) -> dict[str, Any]:
    """``doc +fetch --node <id> --detail with-ids``——revision 唯一携带档。

    live-captured（2026-09-09）：默认 markdown 档无 revision；with-ids 档在
    ``content.revision``（字符串）。该档正文键是 ``jsonml`` 非 ``markdown``——
    **取正文不要走这里**（:func:`_extract_markdown` 只认默认档的 ``markdown``）。

    瞬态读超时有界重试（live-captured 2026-09-09 复跑现场）：with-ids 档要
    服务端现拼 JSONML，create 后立刻读可能撞**服务端 HSF 读超时**（rc=1
    ``business_error`` / ``server_error_code: internalError``，message 带
    ``HSFTimeOutException``、timeout 3000ms）——读车道幂等，重试安全；
    其余错误原样响亮失败。
    """
    args = [*CMD_FETCH, FLAG_NODE, doc_id, FLAG_DETAIL, DETAIL_WITH_IDS, *extra]
    payload: dict[str, Any] | None = None
    for attempt in range(_TRANSIENT_READ_RETRIES + 1):
        payload = _dws(*args, check=False, error_payload=True)
        error = (payload or {}).get("error") or {}
        transient = (
            str(error.get("reason", "")) == "business_error"
            and str(error.get("server_error_code", "")) == "internalError"
        )
        if not transient:
            break
        print(
            f"[kgent-phase2-probe] transient server timeout on with-ids fetch "
            f"(attempt {attempt + 1}/{_TRANSIENT_READ_RETRIES + 1}): "
            f"{str(error.get('message', ''))[:200]}"
        )
        time.sleep(_TRANSIENT_READ_BACKOFF_SECONDS)
    assert payload is not None and not payload.get("error"), (
        f"dws {' '.join(args)} failed:\n  payload={json.dumps(payload, ensure_ascii=False)[:800]}"
    )
    return payload


def _extract_doc_id(payload: dict[str, Any]) -> str:
    """``doc +create`` 响应里的 DOC_ID。live-captured 证实：``data.nodeId``
    （``doc.operation.v1``，2026-09-09 create 原文；响应全块无 revision）。

    四候选键全落空时探针**已被创建**但 id 解析不出——teardown 无法点名它，失败
    消息必须带按标题定位的人工清理路径（teardown 保证的唯一漏洞口）。
    """
    block = _extract_data(payload) or payload
    for key in ("nodeId", "id", "docId", "node_id"):
        value = block.get(key)
        if isinstance(value, str) and value:
            return value
    raise AssertionError(
        "doc +create response has no document id under known keys "
        "(nodeId/id/docId/node_id) — capture the payload and pin this anchor "
        f"(tests/fixtures/dws/FIXTURES-NOTE.md): {json.dumps(payload, ensure_ascii=False)[:800]}. "
        "MANUAL CLEANUP: the probe doc WAS created but its id is unknown — locate it "
        "by title: dws drive +find-file --query kgent-phase2-probe -f json (files[].dentryId "
        "= the 32-char DOC_ID), then dws drive +delete --node <DOC_ID> -f json"
    )


def _extract_revision(payload: dict[str, Any]) -> int | None:
    """revision（编辑号）读数。live-captured（2026-09-09，closure report §3.2）：
    只在 with-ids 档的 ``content.revision``（**字符串** ``"1"``）；create/update 的
    ``doc.operation.v1`` 响应真机全块无 revision（2026-09-09 create 原文）——
    两个块都扫（fetch 先），取不到返回 ``None`` 由调用方决定回退通道。"""
    for block in (_extract_content_block(payload), _extract_data(payload)):
        for key in ("revision", "revisionId", "rev"):
            value = block.get(key)
            if isinstance(value, (int, str)) and str(value).strip().lstrip("-").isdigit():
                return int(value)
    return None


def _extract_markdown(payload: dict[str, Any]) -> str:
    """正文读数：默认档的 ``content.markdown``（live-captured 2026-09-09，
    closure report §3.1——B8 键位漂移死点的正解锚点）。

    with-ids 档的正文键是 ``jsonml``（JSONML 字符串，非 markdown）——本锚点
    **不取它**，正文保真断言只认 ``markdown``。
    """
    block = _extract_content_block(payload)
    value = block.get("markdown")
    return str(value) if value is not None else ""


def _extract_version_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """``doc +version-list`` 的版本条目列表（live-captured 2026-09-09，closure
    report §3.3：外层 ``hasMore/success/versions``，容器键 ``versions`` 顶层）。"""
    block = _extract_data(payload) or payload
    for key in ("versions", "items", "list", "entries", "versionList"):
        value = block.get(key)
        if isinstance(value, list):
            return [entry for entry in value if isinstance(entry, dict)]
    return []


def _entry_version(entry: dict[str, Any]) -> int | None:
    """条目的 version（历史快照号轴，``--version`` 消费）读数。

    live-captured（2026-09-09）：条目只有 ``version``（int）+ ``createTime/``
    ``updateTime/type/userId``——**没有 revision 字段**（原 ``_entry_revision``
    候选键锚点在真 payload 上恒 None，结构性死锚，已删）；条目级 revision 匹配
    走 :func:`_version_revision` 的替代通道。
    """
    for key in ("version", "versionId", "versionNo", "id"):
        value = entry.get(key)
        if isinstance(value, (int, str)) and str(value).strip().lstrip("-").isdigit():
            return int(value)
    return None


# ---------------------------------------------------------------------------
# 探针内容 / 生命周期
# ---------------------------------------------------------------------------


def _write_markdown(tmp_dir: Path, name: str, text: str) -> str:
    """探针内容落临时文件（``@file`` 是**工作目录相对**——PROBE-NOTES §4）。

    显式 LF：Windows 默认会把 ``\\n`` 翻成 ``\\r\\n``，读回断言会被平台无关的
    换行差打断（B8 的换行保真断言会误报）。
    """
    path = tmp_dir / name
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return name


def _write_jsonml(tmp_dir: Path, name: str, text: str) -> str:
    """单段文本 → overwrite 用的最小 JSONML 文件。

    形状纪律（dingtalk-doc JSONML cookbook）：``root`` 单根、span(text)/span(leaf)
    三层文本、block uuid 显式、attrs 对象必在。``--expected-revision`` 只在
    ``overwrite + jsonml`` 通道生效，所以 B6 的写腿走这里。
    """
    doc: list[Any] = [
        "root",
        {},
        [
            "p",
            {"uuid": f"kgent-probe-{uuid.uuid4().hex[:12]}"},
            ["span", {"data-type": "text"}, ["span", {"data-type": "leaf"}, text]],
        ],
    ]
    path = tmp_dir / name
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8", newline="\n")
    return name


def _probe_delete_handle(doc_id: str) -> str:
    """teardown 删除句柄（live-captured 2026-09-09，closure report §3.5/§4.1）。

    真机定谳：删除句柄就是 **DOC_ID 本体**（32 位字母数字）——``drive +info``
    的 ``data.fileId``、``drive +find-file`` 的 ``files[].dentryId`` 都等于
    DOC_ID；``data.dentryId`` 是 **12 位内部号**，``drive +delete`` 拒收
    （「nodeId 格式不合法，非 URL 格式时 nodeId 须为 dentryUuid：32 位字母数字
    字符串」——兑现轮 teardown 三连败根因，候选键序选中它导致误删失败）。

    ``drive +info`` 在这里只作**句柄可用性早验**（report §7.3 的 fail-fast
    纪律）：打得通且 ``fileId`` 对得上就确认通道健康；打不通/键位漂移**不阻塞
    删除**——句柄兜底直用 DOC_ID（两域对应已定谳，无需再解析）。
    """
    payload = _dws(*CMD_DRIVE_INFO, FLAG_NODE, doc_id, check=False)
    if payload is None:
        print(
            f"[teardown] drive +info unreachable for {doc_id} - delete handle "
            "falls back to DOC_ID itself (live-verified handle)"
        )
        return doc_id
    block = _extract_data(payload) or payload
    for key in ("fileId", "dentryUuid"):
        value = block.get(key)
        if isinstance(value, str) and value:
            if value != doc_id:
                print(
                    f"[teardown] drive +info {key} {value} != DOC_ID {doc_id} - "
                    "using the resolved id as delete handle"
                )
            else:
                print(
                    f"[teardown] delete handle verified = DOC_ID itself "
                    f"(drive +info {key} matches, probe {doc_id})"
                )
            return value
    print(
        "drive +info payload had no delete handle under known keys (fileId/"
        "dentryUuid) - falling back to DOC_ID itself; capture and pin the anchor "
        "(tests/fixtures/dws/FIXTURES-NOTE.md): " + json.dumps(payload, ensure_ascii=False)[:800]
    )
    return doc_id


def _delete_probe(doc_id: str) -> bool:
    """teardown：探针文档进回收站（doc 域无删除命令——PROBE-NOTES §1.2 注）。

    删除句柄 = DOC_ID 本体（live-captured 2026-09-09，
    :func:`_probe_delete_handle` 早验）；12 位 ``dentryId`` 会被拒收。
    """
    handle = _probe_delete_handle(doc_id)
    return _dws(*CMD_DRIVE_DELETE, FLAG_NODE, handle, check=False) is not None


def _teardown(doc_id: str) -> None:
    """``finally`` 必删；失败把 DOC_ID 点名进输出 + session 末重试。

    幂等：``_journaled_update`` 在 doc_id 到手后自带一层 except-teardown（覆盖
    create→journal end 全前缀），调用方的 ``finally`` 会再调一次——已删成功就
    直接短路，避免把已删探针误报成 leftover。
    """
    if doc_id in _cleaned_probes:
        return
    if _delete_probe(doc_id):
        _cleaned_probes.add(doc_id)
        if doc_id in _leftover_probes:
            _leftover_probes.remove(doc_id)
        return
    if doc_id not in _leftover_probes:
        _leftover_probes.append(doc_id)
    print(
        f"TEARDOWN FAILED: probe doc {doc_id} still exists - delete manually via the "
        "drive domain (delete handle = the DOC_ID itself, live-verified): "
        "dws drive +delete --node <DOC_ID> -y -f json"
    )


def _conditional_overwrite(tmp_dir: Path, doc_id: str, revision_before: int, content: str) -> None:
    """B6 写腿：``doc +update --command overwrite --doc-format jsonml
    --expected-revision <rev>``——服务端原子条件写仅此组合生效（PROBE-NOTES
    §1.1；dingtalk-integration skill Write 节同款命令形状），内容经 ``@file``
    临时文件（不走 argv 内联）。

    **dws 已知行为（live-captured 2026-09-09，两个探针 + 两轮独立复现同一现场）**：
    该组合的 CLI 回读验证**结构性假阴性**——rc=1
    ``doc_write_verification_failed``（cause「回读结果未包含预期内容」、
    ``execution_started: true``、steps=``[update_document: success, verify:
    failed]``、``retryable: false``），而写实际已落（读回 markdown/revision/
    version 全部到位）；markdown 通道同场验证通过 → 是 jsonml 源文与 markdown
    读数的比对形状问题，不是写入或时序问题。

    处置按 dws 错误契约自证（原文「请先检查当前内容，不要直接重试写入」）：
    ``error_payload`` 分类 → 仅对 ``doc_write_verification_failed`` 放行 →
    有界轮询读回，写后内容出现即视为写成功；不出现才按真失败断言。CLI 侧
    修复后本助手自动走 rc=0 快路径，恢复逻辑保持为死代码。
    """
    rel_after = _write_jsonml(tmp_dir, "probe-after.jsonml", content)
    updated = _dws(
        *CMD_UPDATE,
        FLAG_NODE,
        doc_id,
        FLAG_COMMAND,
        UPDATE_OVERWRITE,
        FLAG_DOC_FORMAT,
        DOC_FORMAT_JSONML,
        FLAG_CONTENT,
        f"@{rel_after}",
        FLAG_EXPECTED_REVISION,
        str(revision_before),
        cwd=tmp_dir,
        check=False,
        error_payload=True,
    )
    if updated is not None and not updated.get("error"):
        return  # rc=0：CLI 自身 verify 通过（写 + 读回都证实）
    reason = str((updated or {}).get("error", {}).get("reason", ""))
    assert reason == "doc_write_verification_failed", (
        f"conditional write failed beyond the known verify false-negative "
        f"(reason={reason!r}): {json.dumps(updated, ensure_ascii=False)[:600]}"
    )
    landed = _poll_content(doc_id, content)
    rendered = json.dumps(landed, ensure_ascii=False)
    assert content in rendered, (
        f"conditional write reported doc_write_verification_failed and did NOT land "
        f"either (no {content!r} on readback within "
        f"{_READBACK_POLL_ROUNDS * _READBACK_POLL_INTERVAL_SECONDS}s): {rendered[:600]}"
    )
    print(
        "[kgent-phase2-probe] dws overwrite+jsonml verify false-negative "
        "(doc_write_verification_failed, write landed) - recovered via own readback"
    )


def _journaled_update(tmp_dir: Path) -> tuple[str, str, int, int]:
    """B6 公共前缀：建探针（A）→ journal begin → dws 条件写（B）→ journal end。

    返回 ``(doc_id, op_id, revision_before, revision_after)``。写通道是
    ``doc +update --command overwrite --doc-format jsonml --expected-revision``
    ——服务端原子条件写仅此组合生效（PROBE-NOTES §1.1；dingtalk-integration
    skill Write 节同款命令形状），内容经 ``@file`` 临时文件（不走 argv 内联）。

    teardown 保证覆盖 **create 之后的全部前缀**（revision 读取、
    ``revision_before is None`` 断言、journal begin/end、条件写）：doc_id 一到手
    就进 except-teardown——这里的任何失败若不删探针，调用方的 ``finally``
    根本拿不到 doc_id，探针就孤儿化了（live-captured 定谳：create 响应真机
    **全块无 revision**，fetch 回退必走）。
    """
    rel_before = _write_markdown(tmp_dir, "probe-before.md", CONTENT_A)
    created = _dws(
        *CMD_CREATE,
        FLAG_NAME,
        PROBE_TITLE,
        FLAG_CONTENT,
        f"@{rel_before}",
        FLAG_DOC_FORMAT,
        DOC_FORMAT_MARKDOWN,
        cwd=tmp_dir,
    )
    doc_id = _extract_doc_id(created)
    try:
        # 删除句柄早验（report §7.3 fail-fast）：teardown 通道不健康当场点名，
        # 不等 finally 才发现（print-only，不阻塞测试）。
        _probe_delete_handle(doc_id)
        revision_before = _extract_revision(created)
        channel = "create response"
        if revision_before is None:
            # create 响应真机全块无 revision（live-captured 2026-09-09）→ 回退
            # 读车道；revision 只在 with-ids 档（默认 markdown 档不带），取数
            # 通道打进 evidence。
            fetched = _fetch_detail(doc_id)
            revision_before = _extract_revision(fetched)
            channel = "doc +fetch --detail with-ids"
        assert revision_before is not None, (
            "no revision from create response or doc +fetch — 台账开账没有写前版本可记"
        )

        begin = _kgent_json(
            "journal",
            "begin",
            "--operation",
            "update",
            "--backend",
            "dingtalk",
            "--doc-uri",
            f"kgent://dingtalk/{doc_id}",
            "--revision-before",
            str(revision_before),
            "--snapshot-content",
            CONTENT_A,
        )
        op_id = begin["entry"]["op_id"]

        _conditional_overwrite(tmp_dir, doc_id, revision_before, CONTENT_B)
        # update 响应（doc.operation.v1）真机不携带 revision（live-captured
        # 2026-09-09，data 块只有 nodeId/verified）→ 写后版本从 with-ids 档读。
        revision_after = _extract_revision(_fetch_detail(doc_id))
        assert revision_after is not None, (
            "no revision after dws doc +update — 落账没有写后版本可记"
        )
        assert revision_after > revision_before, (
            f"revision did not advance on the journaled write: "
            f"before={revision_before} after={revision_after}"
        )

        end = _kgent_json(
            "journal",
            "end",
            "--op-id",
            op_id,
            "--status",
            "ok",
            "--revision-after",
            str(revision_after),
        )
        assert end["entry"]["status"] == "ok"
    except BaseException:
        # 断言/KeyboardInterrupt/SystemExit 一视同仁：探针不留给真机租户。
        _teardown(doc_id)
        raise
    print(
        f"[kgent-phase2-probe] revision_before={revision_before} (from {channel}) "
        f"revision_after={revision_after}"
    )
    return doc_id, op_id, revision_before, revision_after


# ---------------------------------------------------------------------------
# 异步等待（修正 7）
# ---------------------------------------------------------------------------


def _version_revision(doc_id: str, version: int) -> int | None:
    """历史版本的 revision 读数（revision→version 映射的替代通道）。

    live-captured（2026-09-09，closure report §3.2/§3.3）：version-list 条目
    **无 revision 字段**，条目级匹配在真机上结构性无法命中；替代通道是
    ``doc +fetch --version N --detail with-ids`` 读 ``content.revision``（真机
    验证可行、读车道、双轴 1:1：``--version 0 → "0"``、``1 → "1"``）。单版本
    读失败按 ``None`` 处理（轮询层重试，不中断整体等待）。
    """
    payload = _dws(
        *CMD_FETCH,
        FLAG_NODE,
        doc_id,
        FLAG_DETAIL,
        DETAIL_WITH_IDS,
        FLAG_VERSION,
        str(version),
        check=False,
    )
    if payload is None:
        return None
    return _extract_revision(payload)


def _wait_version_point(doc_id: str, revision_before: int) -> int:
    """写前 revision 对应的 version 号（integration 侧 ``history_hint`` 的实现）。

    live-captured 纪法（2026-09-09）：version-list 条目无 revision 字段 →
    revision 匹配经 :func:`_version_revision` 逐版本读；``(version → revision)``
    映射按版本缓存（快照不可变，重复读是浪费调用）。版本建点仍可能异步稀疏
    （lark history 修正 5 同款）→ 有界轮询，但只对**尚未映射**的新条目继续：
    当前快照集全部映射过后，新轮询只可能等到写后新版本（revision >
    revision_before），精确点不会再生——省掉剩余空轮。精确命中
    ``revision == revision_before`` 优先；耗尽后退到 ``revision <= revision_before``
    的最新点（是否真还原由读回断言把关）。
    """
    revision_cache: dict[int, int] = {}
    fallback: tuple[int, int] | None = None
    last_payload: dict[str, Any] = {}
    for _ in range(_VERSION_POLL_ROUNDS):
        payload = _dws(*CMD_VERSION_LIST, FLAG_NODE, doc_id)
        last_payload = payload
        pending = False
        for entry in _extract_version_entries(payload):
            version = _entry_version(entry)
            if version is None or version in revision_cache:
                continue
            pending = True
            revision = _version_revision(doc_id, version)
            if revision is None:
                continue
            revision_cache[version] = revision
            if revision == revision_before:
                return version
            if revision <= revision_before:
                candidate = (revision, version)
                fallback = candidate if fallback is None else max(fallback, candidate)
        if not pending:
            break
        time.sleep(_VERSION_POLL_INTERVAL_SECONDS)
    if fallback is not None:
        print(
            f"[kgent-phase2-probe] no exact version point for revision {revision_before}; "
            f"falling back to nearest older version {fallback[1]} (revision {fallback[0]})"
        )
        return fallback[1]
    raise AssertionError(
        f"dws version-list never produced a version at or before revision "
        f"{revision_before} within "
        f"{_VERSION_POLL_ROUNDS * _VERSION_POLL_INTERVAL_SECONDS}s; last payload: "
        f"{json.dumps(last_payload, ensure_ascii=False)[:1200]}"
    )


def _poll_content(doc_id: str, needle: str) -> dict[str, Any]:
    """version-revert 是异步任务：轮询读回直到包含补偿前内容（或轮询耗尽）。"""
    last: dict[str, Any] = {}
    for _ in range(_READBACK_POLL_ROUNDS):
        last = _dws(*CMD_FETCH, FLAG_NODE, doc_id)
        if needle in json.dumps(last, ensure_ascii=False):
            return last
        time.sleep(_READBACK_POLL_INTERVAL_SECONDS)
    return last


# ---------------------------------------------------------------------------
# 凭据门（模块级 skipif）
# ---------------------------------------------------------------------------


def _dws_identity_available() -> bool:
    """dws 已装且已登录（``dws auth status -f json`` → ``authenticated: true``）。

    解析**复用** :func:`_dws_cmd`（含 ``DWS_BIN`` override 与 win32 ``dws.cmd``
    规则）——门与探针看到的必须是同一个二进制，否则会出现「DWS_BIN 指向已认证
    二进制、PATH 上却无 dws → 探针能跑、门误 skip」的分裂。``_dws_cmd`` 解析
    落空时返回兜底裸名（cwd 相对路径必不存在）→ 未装，不起子进程（CI → skip）。
    非零退出、非 JSON、键缺失一律按「凭据不可用」处理（fail-closed）。
    """
    cmd = _dws_cmd()
    if not Path(cmd[0]).exists():
        return False
    try:
        out = subprocess.run(
            [*cmd, "auth", "status", "-f", "json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,  # 探测：非零退出也按「凭据不可用」处理
        )
    except (OSError, subprocess.SubprocessError):
        return False
    try:
        payload = json.loads(out.stdout)
    except ValueError:
        return False
    return isinstance(payload, dict) and bool(payload.get("authenticated"))


pytestmark.append(
    pytest.mark.skipif(
        not _dws_identity_available(),
        reason=("real-machine probe: dws identity unavailable (credentials blocked, 见 EVIDENCE)"),
    )
)


# ---------------------------------------------------------------------------
# B8 —— 多段中文 + emoji 完整性（first-block 事故回归装甲，FM7）
# ---------------------------------------------------------------------------


def test_b8_content_integrity(tmp_path):
    """B8：多段中文 + emoji + 中文标点经 ``@file`` 写入 → 读回全量保真。

    内容**不走 argv 内联**（多行/CJK 的 argv 内联正是 first-block 事故通道）；
    断言覆盖标题块、中文标点、emoji（含 VS16 变体选择符）与块内换行。
    """
    rel = _write_markdown(tmp_path, "probe-b8.md", CONTENT_B8)
    created = _dws(
        *CMD_CREATE,
        FLAG_NAME,
        PROBE_TITLE_B8,
        FLAG_CONTENT,
        f"@{rel}",
        FLAG_DOC_FORMAT,
        DOC_FORMAT_MARKDOWN,
        cwd=tmp_path,
    )
    doc_id = _extract_doc_id(created)
    try:
        _probe_delete_handle(doc_id)
        # 默认档（--detail simple）是 B8 的保真断言车道：正文键 content.markdown
        # （live-captured 2026-09-09——兑现轮死在 data.content 空串上的键位）。
        fetched = _dws(*CMD_FETCH, FLAG_NODE, doc_id)
        rendered = json.dumps(fetched, ensure_ascii=False)
        content = _extract_markdown(fetched)
        for needle in (
            "Phase 2 完整性探针",  # 标题块
            "第一段中文内容",  # 段一
            "「中文标点」",  # 中文标点
            "❤️🎉",  # emoji（VS16 变体选择符随 JSON 往返保留）
            "第二段含 emoji",  # 段二起始
        ):
            assert needle in rendered, f"B8 content lost {needle!r}; fetched={rendered[:600]}"
        # 换行保真只在正文上断言（JSON 序列化会把 \n 转义，rendered 上断不到）。
        # 失败消息同时带 content 与 rendered payload——键位再漂移时也能从消息里
        # 读出正文到底去了哪个字段。
        assert "❤️🎉" in content and "与多行\n换行内容" in content, (
            f"B8 content.markdown lost emoji/newline fidelity: content={content[:400]!r} "
            f"rendered={rendered[:600]}"
        )
        # revision 只在 with-ids 档（live-captured）——evidence 读数单独取。
        print(
            f"[kgent-phase2-probe] B8 revision={_extract_revision(_fetch_detail(doc_id))} "
            f"content_bytes={len(content.encode('utf-8'))}"
        )
    finally:
        _teardown(doc_id)


# ---------------------------------------------------------------------------
# B6 —— undo 计划 → dws version-revert 闭环
# ---------------------------------------------------------------------------


def test_b6_undo_plan_and_version_revert(tmp_path):
    """B6：undo 计划（version-revert）→ integration skill 腿执行 → 读回还原。"""
    doc_id, op_id, revision_before, revision_after = _journaled_update(tmp_path)
    try:
        plan_json = _kgent_json("undo", op_id)
        print("undo plan:", json.dumps(plan_json, ensure_ascii=False, indent=2))
        assert plan_json["status"] == "ok"
        assert plan_json["mode"] == "plan"
        assert plan_json["integration_skill"] == "dingtalk-integration"
        assert plan_json["plan"]["mechanism"] == "version-revert"
        assert plan_json["plan"]["history_hint"] == "dws doc +version-list"
        assert int(plan_json["plan"]["revision_before"]) == revision_before

        target_version = _wait_version_point(doc_id, revision_before)

        # TOCTOU 执行前复核（dingtalk-integration skill Undo 节步骤 3）：当前
        # revision == plan.plan.revision_current——绝不带着过期计划落 revert。
        current_revision = _extract_revision(_fetch_detail(doc_id))
        assert current_revision is not None, (
            "doc +fetch returned no revision for the TOCTOU recheck"
        )
        assert current_revision == int(plan_json["plan"]["revision_current"]), (
            f"TOCTOU drift: fetched revision {current_revision} != plan revision_current "
            f"{plan_json['plan']['revision_current']}"
        )

        reverted = _dws(*CMD_VERSION_REVERT, FLAG_NODE, doc_id, FLAG_VERSION, str(target_version))
        print(
            f"[kgent-phase2-probe] version-revert → version {target_version}: "
            f"{json.dumps(reverted, ensure_ascii=False)[:400]}"
        )

        content = _poll_content(doc_id, CONTENT_A)
        rendered = json.dumps(content, ensure_ascii=False)
        assert CONTENT_A in rendered, (
            f"version-revert did not restore {CONTENT_A!r} within "
            f"{_READBACK_POLL_ROUNDS * _READBACK_POLL_INTERVAL_SECONDS}s: {rendered[:600]}"
        )
        assert CONTENT_B not in rendered, "post-revert content still carries the undone write"
        # B6 evidence：revision 读数（create → update → revert 后）供验收记录。
        print(
            f"[kgent-phase2-probe] B6 revision_before={revision_before} "
            f"revision_after={revision_after} version={target_version} "
            f"final_revision={_extract_revision(content)}"
        )
    finally:
        _teardown(doc_id)


def test_b6_fm2_rejects_after_concurrent_edit(tmp_path):
    """FM2：journal end 之后第三方再写（并发编辑模拟）→ undo 计划 rejected。

    计划期拒绝 = 不产生可执行补偿：mode 仍是 plan、status=rejected、reason 带两侧
    revision——绝不规划一次盲回滚（ledger.compensation_plan 的 FM2 契约）。
    """
    doc_id, op_id, _revision_before, revision_after = _journaled_update(tmp_path)
    try:
        rel_concurrent = _write_markdown(tmp_path, "probe-concurrent.md", CONTENT_C)
        concurrent = _dws(
            *CMD_UPDATE,
            FLAG_NODE,
            doc_id,
            FLAG_COMMAND,
            UPDATE_APPEND,
            FLAG_DOC_FORMAT,
            DOC_FORMAT_MARKDOWN,
            FLAG_CONTENT,
            f"@{rel_concurrent}",
            cwd=tmp_path,
        )
        revision_concurrent = _extract_revision(concurrent)
        if revision_concurrent is None:
            revision_concurrent = _extract_revision(_fetch_detail(doc_id))
        assert revision_concurrent is not None, "concurrent write left no readable revision"
        assert revision_concurrent > revision_after, (
            f"concurrent write did not advance revision: after={revision_after} "
            f"concurrent={revision_concurrent}"
        )

        plan_json = _kgent_json("undo", op_id, ok_rc=(0, 1))
        print("undo plan (FM2):", json.dumps(plan_json, ensure_ascii=False, indent=2))
        assert plan_json["status"] == "rejected"
        assert plan_json["mode"] == "plan"
        reason = str(plan_json.get("reason", ""))
        assert f"expected revision {revision_after}" in reason, (
            f"reason lacks the journaled revision: {reason!r}"
        )
        assert f"current {revision_concurrent}" in reason, (
            f"reason lacks the current revision: {reason!r}"
        )
    finally:
        _teardown(doc_id)


@pytest.fixture(scope="session", autouse=True)
def _retry_leftovers():
    """session 末对 teardown 失败的探针再删一次，仍失败则点名人工清理命令。"""
    yield
    for doc_id in list(_leftover_probes):
        if _delete_probe(doc_id):
            _leftover_probes.remove(doc_id)
            print(f"probe doc {doc_id} deleted on retry")
    for doc_id in _leftover_probes:
        print(
            f"LEFTOVER PROBE DOC: {doc_id} — delete manually via the drive domain "
            f"(delete handle = the DOC_ID itself, live-verified): "
            f"dws {CMD_DRIVE_DELETE[0]} {CMD_DRIVE_DELETE[1]} --node {doc_id} -y -f json"
        )
