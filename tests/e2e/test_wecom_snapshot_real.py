"""B5/B8 真机：wecom 探针文档 undo 计划 → 快照写回闭环。

ADR 0004/0005 的 wecom 侧真机验收载体：kgent 台账 begin/end → ``kgent undo``
只产补偿计划（mechanism=snapshot-restore、history_hint=None、
integration_skill=wecom-integration——wecom 无平台 history，快照写回是唯一
选项），执行归 wecom-integration skill——本测试扮演该 skill：把
``plan.plan.snapshot``（begin ``--snapshot-content`` 落盘的写前全文 A）经
``doc contents overwrite`` 的 file_path 通道写回并读回断言还原（B5）。
另以多段中文 + emoji 内容的写入/读回全量保真压 first-block 事故回归
（B8/FM7），以写后第三方编辑验证写后快照比对拒绝（FM2-wecom），以无写后
快照证据的 op 验证 FM3 内容比对拒绝（fail closed 兜底）。

**journal 纪律（控制器裁决，覆盖 brief 定稿前的 version 轴设计）**：Task 1
真机定谳 wecom **无 version 轴**（``doc contents get`` 响应不下发 ``version``
键，PROBE-NOTES 顶部定谳）→ begin 只带 ``--snapshot-content <写前全文 A>``
（**无 --revision-before**）、end 必带 ``--snapshot-after <写后全文 B>``
（写后读回取得，无 ``--revision-after``）。undo 的新鲜度证据就是这对快照：
FM2-wecom 比对 B 与当前内容、FM3（无 B 时）比对 A。

**快照 byte 透明（Task 6 真机定谳，2026-09-09）**：wecom-cli 读回 content
恒带尾部 ``\\r`` + padding（repr ``'AAA-CONTENT\\r        '``，连续读稳定；
Task 1 fixture 同形）。台账快照文件落盘/读回若经文本模式 newline 翻译，
CR 会被折成 LF，FM2-wecom/FM3 比对对一切真机内容恒拒——本文件的首轮真机
运行正是一个 undo 恒拒现场，落成 ``tests/test_undo_ledger.py`` 的
``test_compensation_plan_snapshot_round_trip_cr_transparent`` 装甲与
ledger 的 ``newline=""`` 往返修复（同分支先行 commit）。本文件的快照读回
断言一律 byte 透明（``open(newline="")`` / ``read_bytes``），与 ledger 同纪。

**B5 还原断言的形态锚（真机定谳）**：把快照 A 原样写回后，读回**不等于** A
的逐字回声——平台内容管线会把 A 尾部的 ``\\r`` + padding 重排（真机实测：
``'AAA-CONTENT\\r        '`` 写回 → 读回 ``'AAA-CONTENT        \\r        '``）。
B5 的还原判据因此钉在载荷级：A 的载荷在场、被 undo 的写（B）不在场；两侧
repr 全量打印进运行日志（wecom-integration skill Undo 节第 6 步「逐字一致…
形态可比」的字节级回声在真机不成立，是 skill 文档级的待修项，见 Task 6 报告）。

**B8 换行保真的形态锚（真机定谳）**：源文件里的 ``\\n`` 读回是 ``\\r``（段落/
换行在平台内容管线统一为 CR：``\\n\\n`` → ``\\r\\r``、段内 ``\\n`` → ``\\r``），
文字 needle（含 emoji VS16、中文标点）原样保真——断言按真机形态钉，不按源
文件形态硬编码。

**凭据门**：wecom-cli 未装或 ``wecom-cli auth show --status`` 非
``authorized`` 时整文件 skip（bot-only 身份，auth init 需维护者本人扫码）。
该门只探 CLI 身份，**不替代 kgent 后端门**：``~/.kgent/config.yaml`` 的
``backends.wecom.enabled: true``（wecom-integration skill 的 The Gate）是
本文件的**前置**——``kgent undo`` 计划的 ``integration_skill:
wecom-integration`` 正来自该 backend 接线，缺它时计划不再路由到 wecom 腿
（相关断言失败，而非 skip）。
命令拼写真值：``tests/fixtures/wecom-cli/PROBE-NOTES.md``；payload 键位
live/schema 分级：同目录 ``FIXTURES-NOTE.md``。

与 Phase 2 e2e 纪法的真机修正/契约（沿用 test_dingtalk_undo_real.py）：
1. ``kgent`` 经 ``sys.executable -m kgent``（或 ``KGENT_BIN``）解析——PATH 上
   是旧安装，必须打仓库源码。
2. kgent 的 ``--json`` 放叶子子命令末尾（argparse 子解析器独立 namespace）。
3. ``wecom-cli`` 在 Windows 解析 ``wecom-cli.cmd``（npm 三 shim；
   ``shell=False`` 不自动补 .cmd）。``--json`` 是 wecom-cli 的**输入体**旗标，
   不承担输出格式——输出默认 JSON（PROBE-NOTES §1.1 live 定谳）。
4. 内容通道：多行/含 CJK 一律 ``file_path``（cwd 相对，Fs 沙箱）——
   ``overwrite`` 的 JSON 体 ``content`` XOR ``file_path``；台账快照在
   ``~/.kgent/journal/snapshots/``，写回前必须先拷进 cwd。
5. **teardown 无删除命令**：wecom 平台无文档删除 API（PROBE-NOTES §1.1
   help+schema 定谳）→ rename 隔离（``kgent-phase3-probe-DELETE-ME-`` 前缀）
   + session 末重试 + leftover 点名（docid + URL + 人工清理 runbook）。
6. 异步：``doc import`` 的建档与 overwrite 的读回可见性都可能滞后 →
   有界轮询（lark/dws 版 ``_poll_content`` 同款）。
7. **确认门**：PROBE-NOTES §1.2/§1.3 真值单里 wecom-cli 没有任何
   confirmation=user_required 语义的命令（无 ``-y``/opt-in 旗标族——与 dws
   的 ``doc +update`` 不同），故无 WECOM_PROBE_CONFIRM 变体；``--dry-run``
   是唯一的事前演练通道，不承担确认语义。
8. ``kgent undo`` 对 rejected 计划 exit 1（CLI 契约：``0 if status == "ok"
   else 1``）——FM2/FM3 腿的 undo 调用按「rc ∈ {0, 1} 且 stdout 是 JSON」
   解析，rc 语义交给 status 断言，不由 subprocess 层代劳。
9. **两级平台限流（Task 6 真机定谳）**：分钟级机器人 MCP 调用频率限制
   （errcode 850005，退避可穿）与**当日**「通过机器人获取文档内容」配额
   （errcode 640459，等不回——立即 fail fast 并点名，见
   :class:`WecomDailyQuotaExhausted`）。配额日内重跑本文件必红；待配额日切
   后重跑（凭据门不受影响，testbody 无需改动）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.real]

#: 仓库无 pytest marker 注册表：``e2e``/``real`` 直接打标，靠 skipif 做真机门。

# ---------------------------------------------------------------------------
# 可调常量区 —— wecom-cli 命令真值（PROBE-NOTES；真值漂移只改本区）
# ---------------------------------------------------------------------------

PROBE_TITLE = "kgent-phase3-probe-临时"
#: B8 用独立标题：人工清理时能与 B5 探针区分。
PROBE_TITLE_B8 = "kgent-phase3-probe-完整性"
#: create 腿用独立标题：补偿 = rename 隔离，人工清理时与 update 腿探针区分。
PROBE_TITLE_CREATE = "kgent-phase3-probe-create"
#: teardown 隔离前缀（平台无删除命令——模块 docstring 修正 5）。
DELETE_ME_PREFIX = "kgent-phase3-probe-DELETE-ME-"

CONTENT_A = "AAA-CONTENT"
CONTENT_B = "BBB-CONTENT"
CONTENT_C = "CCC-CONTENT"
#: B8：多段中文 + emoji + 中文标点——first-block 事故回归装甲（FM7）
CONTENT_B8 = (
    "# Phase 3 完整性探针\n\n"
    "第一段中文内容，包含「中文标点」。\n\n"
    "第二段含 emoji ❤️🎉 与多行\n换行内容。\n"
)

#: 探针生命周期命令（PROBE-NOTES §1.2 [schema 实测] + §2 live 键位对账）
CMD_DOC_IMPORT = ("doc", "import")  # --json {"doc_type","file_name","file_path"}
CMD_CONTENTS_GET = ("doc", "contents", "get")  # --json {"docid"}（content_type 缺省 markdown）
CMD_CONTENTS_OVERWRITE = (
    "doc",
    "contents",
    "overwrite",
)  # --json {"docid","content_type","file_path"}
CMD_NAMES_UPDATE = ("doc", "names", "update")  # --json {"docid","new_name"}（teardown 隔离）

DOC_TYPE_DOC = "doc"  # import 的 doc_type 枚举 doc|sheet|smartsheet（不含 smartpage）
CONTENT_TYPE_TEXT = "text"  # overwrite 的 content_type（补偿写回用纯文本，skill Write 节同款）

#: 有界轮询预算（import 异步建档 / overwrite 读回可见性——修正 6）。
#: import 轮询 24 轮：全套 suite 连跑时平台的导入转换管线有明显排队
#: （Task 6 首轮全套真机实测：import 成功但 12 轮内正文不可见），24 轮
#: （含节流 ≈3 分钟）骑穿常规排队窗。
_IMPORT_POLL_ROUNDS = 24
_IMPORT_POLL_INTERVAL_SECONDS = 5
_READBACK_POLL_ROUNDS = 8
_READBACK_POLL_INTERVAL_SECONDS = 2

WECOM_TIMEOUT_SECONDS = 120
KGENT_TIMEOUT_SECONDS = 120

#: 限流（errcode 850005「超过机器人MCP接口调用频率限制」，Task 6 真机实测）
#: 的退避序列：前三次照 wecom-integration skill Known Limitations 的自设
#: 退避（1s/2s/4s 指数退避、最多 3 次）；其后 15/30/60s 深退避——限流窗是
#: 整租户 MCP 配额窗（Task 6 全套 suite 连跑真机触发过分钟级持续限流），
#: 短梯骑不穿。每次重试打印审计行（显式，不静默缩量）。
RETRYABLE_ERRCODES = frozenset({850005})
#: 当日「通过机器人获取文档内容」配额耗尽（Task 6 真机定谳，§报告）——
#: 不可重试、不可轮询穿，:class:`WecomDailyQuotaExhausted` 立即失败。
DAILY_QUOTA_ERRCODE = 640459
_BACKOFF_SECONDS = (1.0, 2.0, 4.0, 15.0, 30.0, 60.0)
#: 调用间匀速间隔：一轮五测试 ~55 次调用，背靠背连发真机触发过 850005
#: （失败现场见 Task 6 报告）——匀速节流 + 退避双保险。
_WECOM_CALL_PACING_SECONDS = 2.0

#: teardown 隔离失败的探针 docid（session 末重试 + 人工清理提示）
_leftover_probes: list[str] = []
#: 已隔离成功的探针 docid（``_teardown`` 幂等短路）
_quarantined_probes: set[str] = set()


# ---------------------------------------------------------------------------
# 进程封装
# ---------------------------------------------------------------------------


def _utf8_stdio() -> None:
    """CJK/emoji evidence 打印在 Windows 控制台缺省编码下会炸——统一 UTF-8。

    探针 evidence 含 CJK/emoji/快照 repr，cp1252/cp936 控制台下 ``print``
    直接 :exc:`UnicodeEncodeError`，会把一次本来成功的真机运行打断（真机
    rehearsal 实际发生过——B8 repr 打印炸在 cp1252）。``errors="replace"``
    兜底保证打印本身绝不抛。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


_utf8_stdio()


def _kgent() -> list[str]:
    """仓库源码的 kgent 调用形态（修正 1）。"""
    override = os.environ.get("KGENT_BIN")
    if override:
        return [override]
    return [sys.executable, "-m", "kgent"]


def _wecom_cmd() -> list[str]:
    """wecom-cli 的可执行形态：Windows 上解析 ``wecom-cli.cmd``（修正 3）。

    与 :class:`kgent.adapters.wecom.WeComAdapter` 同一规则；``shutil.which``
    返回完整路径（规避无扩展名 sh shim 的 bash 语义误用）。
    """
    override = os.environ.get("WECOM_CLI_BIN")
    if override:
        return [override]
    resolved = shutil.which("wecom-cli.cmd") if sys.platform == "win32" else None
    if resolved is None:
        resolved = shutil.which("wecom-cli")
    return [resolved] if resolved else ["wecom-cli"]


def _error_code_of(payload: dict[str, Any] | None) -> int | None:
    """响应里的错误档 code（``errcode``/``code``/CLI 层 ``error.code`` 三认）。"""
    if not isinstance(payload, dict):
        return None
    for key in ("errcode", "code"):
        value = payload.get(key)
        if isinstance(value, int) and value != 0:
            return value
    err = payload.get("error")
    if isinstance(err, dict) and isinstance(err.get("code"), int):
        return err["code"]
    return None


class WecomDailyQuotaExhausted(AssertionError):
    """当日文档内容读取配额耗尽（errcode 640459，Task 6 真机定谳）。

    响应形状：CLI 层 ``{"error":{"code":640459,"message":"当前用户通过机器人
    获取文档内容已超过当日最大次数限制 (callid: …)"}}``（exit 1）。这是
    **环境级阻断**——退避与轮询都无意义（当日配额不因等待恢复），立即失败
    并点名，比慢速烧完轮询预算可诊断得多。恢复只能等配额日切。
    """


def _retryable_error(payload: dict[str, Any] | None) -> bool:
    """限流档（:data:`RETRYABLE_ERRCODES`）→ 可退避重试；其余失败一律如实上抛。"""
    return _error_code_of(payload) in RETRYABLE_ERRCODES


def _call_failed(
    proc: subprocess.CompletedProcess[str] | None,
    payload: dict[str, Any] | None,
    failure: Exception | None,
) -> bool:
    """一次调用的失败判定：spawn 异常 / 非零退出 / 非 JSON / 非 dict / 错误档
    code（``errcode``/``code`` 非 0 int；CLI 层 ``error`` envelope 走 exit 1，
    被 rc 判据覆盖）。"""
    if failure is not None or proc is None or payload is None:
        return True
    if proc.returncode != 0:
        return True
    return any(isinstance(payload.get(k), int) and payload[k] != 0 for k in ("errcode", "code"))


def _wecom(
    *args: str,
    cwd: Path | None = None,
    check: bool = True,
    timeout: int = WECOM_TIMEOUT_SECONDS,
) -> dict[str, Any] | None:
    """跑一条 wecom-cli 命令并解析 JSON 输出（输出默认 JSON——PROBE-NOTES §1.1）。

    ``check=True`` → 失败抛 AssertionError（带 stdout/stderr 尾部，真机排障
    用）；``check=False``（轮询/探测）→ 失败打印并返回 ``None``。``cwd`` 锚定
    file_path 的 Fs 沙箱语义。stdin=DEVNULL：任何等待输入都立即 EOF。

    **每日配额（640459）不受 check 影响，直接抛
    :class:`WecomDailyQuotaExhausted`**——环境级阻断，check=False 的轮询 caller
    也不得慢速烧完轮询预算（teardown 的调用方在 except/finally 里仍会跑）。

    调用间匀速节流（:data:`_WECOM_CALL_PACING_SECONDS`）+ 限流档退避重试
    （:data:`_BACKOFF_SECONDS`，每次重试打印审计行）——一轮五测试 ~55 次
    背靠背调用真机触发过 850005（首跑 FM2 现场见 Task 6 报告）；重试纪律
    即 wecom-integration skill Known Limitations 的自设退避（限流/超时可
    重试，spawn 失败不可重试）。
    """
    argv = [*_wecom_cmd(), *args]
    proc: subprocess.CompletedProcess[str] | None = None
    payload: dict[str, Any] | None = None
    failure: Exception | None = None
    for attempt in range(len(_BACKOFF_SECONDS) + 1):
        if _WECOM_CALL_PACING_SECONDS:
            time.sleep(_WECOM_CALL_PACING_SECONDS)
        failure = None
        payload = None
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(cwd) if cwd is not None else None,
                timeout=timeout,
                check=False,
                stdin=subprocess.DEVNULL,
            )
        except OSError as exc:  # spawn 失败不可重试
            proc, failure = None, exc
        except subprocess.SubprocessError as exc:  # 超时属可重试档（skill：限流/超时）
            proc, failure = None, exc
        else:
            try:
                decoded = json.loads(proc.stdout)
                payload = decoded if isinstance(decoded, dict) else None
            except ValueError:
                payload = None
        if not _call_failed(proc, payload, failure):
            return payload
        if _error_code_of(payload) == DAILY_QUOTA_ERRCODE:
            raise WecomDailyQuotaExhausted(
                f"wecom-cli {' '.join(args)} hit the daily content-read quota "
                f"({DAILY_QUOTA_ERRCODE}) — waiting cannot restore it; re-run after "
                f"the quota day rolls over. stdout={proc.stdout[-400:] if proc else ''}"
            )
        if attempt < len(_BACKOFF_SECONDS) and (
            isinstance(failure, subprocess.TimeoutExpired) or _retryable_error(payload)
        ):
            delay = _BACKOFF_SECONDS[attempt]
            print(
                f"[wecom backoff] {' '.join(args)} hit a retryable error "
                f"(errcode={_error_code_of(payload)}, "
                f"failure={type(failure).__name__ if failure else None}) — "
                f"retry {attempt + 1}/{len(_BACKOFF_SECONDS)} in {delay:.0f}s"
            )
            time.sleep(delay)
            continue
        break
    if check:
        if proc is None:
            raise AssertionError(
                f"wecom-cli {' '.join(args)} could not run: {failure}"
            ) from failure
        assert not _call_failed(proc, payload, failure), (
            f"wecom-cli {' '.join(args)} failed:\n"
            f"  rc={proc.returncode}\n"
            f"  failure={failure!r}\n"
            f"  stdout={proc.stdout[-800:]}\n"
            f"  stderr={proc.stderr[-800:]}"
        )
        return payload
    if proc is None:
        print(f"wecom-cli {' '.join(args)} could not run: {failure}")
        return None
    print(
        f"wecom-cli {' '.join(args)} failed (rc={proc.returncode}): "
        f"stdout={proc.stdout[-400:]!r} stderr={proc.stderr[-400:]!r}"
    )
    return None


def _wecom_json(
    service_args: tuple[str, ...], body: dict[str, Any], **kw: Any
) -> dict[str, Any] | None:
    """``--json`` 输入体形态的封装：argv = [*service_args, "--json", <body>]。

    body 经 ``ensure_ascii=True`` 序列化（纯 ASCII argv，规避 cmd 包装层的
    多字节 argv 陷阱——WeComAdapter._run_wecom 同款纪律）。
    """
    return _wecom(*service_args, "--json", json.dumps(body, ensure_ascii=True), **kw)


def _kgent_json(command: str, *rest: str) -> dict[str, Any]:
    """kgent 的 ``--json`` 放整条子命令路径末尾（修正 2）。"""
    out = subprocess.run(
        [*_kgent(), command, *rest, "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=KGENT_TIMEOUT_SECONDS,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    if out.returncode != 0:
        raise AssertionError(
            f"kgent {command} {' '.join(rest)} failed:\n"
            f"  rc={out.returncode}\n  stdout={out.stdout[-800:]}\n  stderr={out.stderr[-800:]}"
        )
    try:
        return json.loads(out.stdout)
    except ValueError as exc:
        raise AssertionError(
            f"kgent {command} printed non-JSON stdout: {out.stdout[:400]!r}"
        ) from exc


def _kgent_undo(op_id: str) -> dict[str, Any]:
    """``kgent undo <op_id> --json``：rejected 计划 exit 1 是 CLI 契约（修正 8）。

    rc ∈ {0, 1} 都按 stdout JSON 解析（rc 的语义交给调用方对 ``status`` 的
    断言）；其余 rc 或非 JSON stdout 按失败处理。
    """
    out = subprocess.run(
        [*_kgent(), "undo", op_id, "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=KGENT_TIMEOUT_SECONDS,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    assert out.returncode in (0, 1), (
        f"kgent undo {op_id} exited {out.returncode} (contract is 0=ok / 1=rejected):\n"
        f"  stdout={out.stdout[-800:]}\n  stderr={out.stderr[-800:]}"
    )
    try:
        return json.loads(out.stdout)
    except ValueError as exc:
        raise AssertionError(
            f"kgent undo {op_id} printed non-JSON stdout: {out.stdout[:400]!r}"
        ) from exc


# ---------------------------------------------------------------------------
# payload 键位对账锚点（候选键容错；取不到打印原 payload 供补捕定谳）
# ---------------------------------------------------------------------------


def _extract_docid(payload: dict[str, Any]) -> str:
    """import / search hit 响应里的 docid（live 键 ``docid``——PROBE-NOTES §2.3）。

    顶层无包裹 envelope（FIXTURES-NOTE 冲突点 1 live 定谳），保留 ``data``
    容错块应对 envelope 再漂移。**URL token ≠ API docid**（PROBE-NOTES §1.5）
    ——绝不从 url 提取。
    """
    block = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    for source in (block, payload):
        for key in ("docid", "docId", "id"):
            value = source.get(key)
            if isinstance(value, str) and value:
                return value
    raise AssertionError(
        "response has no docid under known keys (docid/docId/id) — capture the "
        "payload and pin the anchor (tests/fixtures/wecom-cli/FIXTURES-NOTE.md): "
        f"{json.dumps(payload, ensure_ascii=False)[:800]}"
    )


def _probe_url(payload: dict[str, Any]) -> str:
    """探针的原生 URL（响应 ``url``——scode 签名原样保留，供人工清理）。"""
    block = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    value = block.get("url") or payload.get("url")
    return str(value) if value else "<no url in response>"


def _extract_content(payload: dict[str, Any]) -> str:
    """``doc contents get`` 的正文（live 短内容档内联 ``content``）。

    长内容 ``file_path`` 落盘语义未定谳（FIXTURES-NOTE 冲突点 4）→ 不消费
    该键：``content`` 缺席即 fail（与 WeComAdapter.read_document 同纪律）。
    """
    block = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    value = block.get("content")
    if value is not None:
        return str(value)
    raise AssertionError(
        "contents get returned no inline content (long-content file_path "
        "semantics are not consumed until a live sample lands — FIXTURES-NOTE "
        f"冲突点 4): {json.dumps(payload, ensure_ascii=False)[:800]}"
    )


# ---------------------------------------------------------------------------
# 探针内容 / 生命周期
# ---------------------------------------------------------------------------


def _write_text(tmp_dir: Path, name: str, text: str) -> str:
    """内容落 cwd 相对文件（file_path 通道）。

    ``newline="\\n"``：写入零翻译——``\\n`` 原样落盘、快照里的 ``\\r`` 也不被
    动（byte 保真是 B8 换行 needle 与快照写回比对的前提）。
    """
    path = tmp_dir / name
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return name


def _read_file_verbatim(path: Path) -> str:
    """byte 透明读文件（``newline=""``）——与修复后的 ledger 快照读回同纪律。

    universal newlines 会把 ``\\r`` 折成 ``\\n``，快照比对就不再是对平台读回
    原串的比对（Task 6 真机定谳，见模块 docstring「快照 byte 透明」）。
    """
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _write_probe_docx(tmp_dir: Path, name: str, text: str) -> str:
    """最小 .docx（stdlib zipfile——零新依赖）供 ``doc import`` 建探针在线文档。

    wecomcli-doc 的 create 是两步流：本地生成 .docx → import 为在线文档
    （返回 docid/url）。最小 OOXML 三件套即导入为单段文档。
    """
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>" + escape(text) + "</w:t></w:r></w:p></w:body></w:document>"
    )
    path = tmp_dir / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document)
    return name


def _create_probe(tmp_path: Path, title: str, content: str) -> tuple[str, str]:
    """建探针在线文档（import 两步流）→ ``(docid, url)``；轮询到内容可见。

    import 的建档异步（修正 6）——轮询 ``doc contents get`` 直到正文出现
    （有界；``check=False``：文档未就绪的错误档也按「还没好」处理）。docid
    优先取 import 响应（live 键位）；取不到才走 search 兜底轮询——零命中
    envelope 是 live 常态（``docs`` 族整族缺席），兜底按「键缺席即降级」。
    """
    rel = _write_probe_docx(tmp_path, "probe.docx", content)
    imported = _wecom_json(
        CMD_DOC_IMPORT,
        {"doc_type": DOC_TYPE_DOC, "file_name": f"{title}.docx", "file_path": rel},
        cwd=tmp_path,
    )
    # import 响应的 docid 是首选锚点（live 真值：task_status/docid/url 直返）
    docid: str | None = None
    try:
        docid = _extract_docid(imported or {})
    except AssertionError:
        docid = None
    if docid:
        # docid 到手即打印（M-1）：平台无删除命令，后续任何一步失败都必须
        # 能凭这行输出定位/隔离探针，而不是让 docid 随断言一起丢。
        print(
            f"[kgent-phase3-probe] import accepted: title={title!r} "
            f"docid={docid} url={_probe_url(imported or {})}"
        )
    for _ in range(_IMPORT_POLL_ROUNDS):
        if docid:
            break
        found = _wecom_json(
            ("doc", "search"),
            {
                "keywords": ["kgent-phase3-probe"],
                "search_scope": "title_content",
                "limit": 10,
            },
            check=False,
        )
        docs = (found or {}).get("docs") or []
        for hit in docs:
            if isinstance(hit, dict) and title in str(hit.get("doc_name", "")):
                docid = _extract_docid(hit)
                break
        if not docid:
            time.sleep(_IMPORT_POLL_INTERVAL_SECONDS)
    assert docid, (
        f"probe doc {title!r} produced no docid (import payload and search "
        f"fallback both exhausted) within "
        f"{_IMPORT_POLL_ROUNDS * _IMPORT_POLL_INTERVAL_SECONDS}s: "
        f"{json.dumps(imported, ensure_ascii=False)[:600]}"
    )
    got: dict[str, Any] = {}
    try:
        for _ in range(_IMPORT_POLL_ROUNDS):
            got = _wecom_json(CMD_CONTENTS_GET, {"docid": docid}, cwd=tmp_path, check=False) or {}
            if "content" in got and content in _extract_content(got):
                return docid, _probe_url(got)
            time.sleep(_IMPORT_POLL_INTERVAL_SECONDS)
    except BaseException:
        # docid 已知后的任何失败（含 640459 配额阻断——rename 隔离是写操作，
        # 配额日仍可用）都要把已建的探针隔离，不留真机租户残留。本分支两次
        # 真机跑动在无此兜底时泄漏过探针（2026-09-09，M-1 修复现场）。
        _teardown(docid)
        raise
    raise AssertionError(
        f"imported probe content {content!r} not visible within "
        f"{_IMPORT_POLL_ROUNDS * _IMPORT_POLL_INTERVAL_SECONDS}s: "
        f"{json.dumps(got, ensure_ascii=False)[:600]}"
        # M-1：docid 已知时必随终局错误点名——探针不留给真机租户。
        + (
            f"\n  MANUAL CLEANUP (platform has no CLI delete): "
            f"wecom-cli doc names update --json "
            f'\'{{"docid":"{docid}","new_name":"{DELETE_ME_PREFIX}{docid}"}}\' '
            f"then delete probe {title!r} ({docid}) in the WeCom client"
        )
    )


def _quarantine_probe(docid: str) -> bool:
    """teardown：rename 隔离（平台无删除命令——模块 docstring 修正 5）。

    改名是写操作、不在内容读配额内——配额耗尽日 teardown 仍可用（真机
    实测：640459 当日 names update 照常 errcode:0）。
    """
    try:
        renamed = _wecom_json(
            CMD_NAMES_UPDATE,
            {"docid": docid, "new_name": f"{DELETE_ME_PREFIX}{docid}"},
            check=False,
        )
    except WecomDailyQuotaExhausted:
        return False
    return renamed is not None


def _teardown(docid: str) -> None:
    """``finally`` 必隔离；失败把 docid 点名 + session 末重试。

    幂等：create 腿的补偿本身就是一个 rename 隔离（成功后
    :func:`_mark_quarantined` 记账），调用方的 ``finally`` 会再调一次——
    已隔离就直接短路。
    """
    if docid in _quarantined_probes:
        return
    if _quarantine_probe(docid):
        _mark_quarantined(docid)
        return
    if docid not in _leftover_probes:
        _leftover_probes.append(docid)
    print(
        f"TEARDOWN FAILED: probe doc {docid} not quarantined - rename manually: "
        f"wecom-cli doc names update --json "
        f'\'{{"docid":"{docid}","new_name":"{DELETE_ME_PREFIX}{docid}"}}\', '
        "then delete it in the WeCom client (no CLI delete exists)"
    )


def _mark_quarantined(docid: str) -> None:
    """隔离成功的记账（幂等短路口 + leftover 摘除）。"""
    _quarantined_probes.add(docid)
    if docid in _leftover_probes:
        _leftover_probes.remove(docid)


def _read_content(docid: str, tmp_path: Path) -> str:
    """``doc contents get`` 正文（check=True：读失败按失败处理）。"""
    return _extract_content(_wecom_json(CMD_CONTENTS_GET, {"docid": docid}, cwd=tmp_path))


def _poll_content(docid: str, needle: str, cwd: Path) -> str:
    """overwrite 读回可见性可能滞后：轮询直到包含目标内容（或轮询耗尽）。

    耗尽时返回最后一次正文（调用方断言给出现场）。轮询内 ``check=False``：
    写后短暂窗口的读错误档按「还没可见」处理。
    """
    last = ""
    for _ in range(_READBACK_POLL_ROUNDS):
        got = _wecom_json(CMD_CONTENTS_GET, {"docid": docid}, cwd=cwd, check=False)
        if got is not None and "content" in got:
            last = _extract_content(got)
            if needle in last:
                return last
        time.sleep(_READBACK_POLL_INTERVAL_SECONDS)
    return last


def _journaled_overwrite(
    tmp_path: Path, *, record_post_snapshot: bool = True
) -> tuple[str, str, str, str]:
    """B5 公共前缀：建探针（A）→ 读回 A → journal begin（快照 A，无 revision）
    → overwrite（B，file_path 通道）→ 读回 B → journal end（写后快照 B）。

    返回 ``(docid, op_id, content_a, content_b)``——A/B 都是平台读回原串
    （含尾部 ``\\r`` + padding 的真机形态）。``record_post_snapshot=False``
    是 FM3 变体（end 不带写后快照——计划必走 FM3 begin 快照比对兜底）。
    teardown 保证覆盖 create 之后的全部前缀。
    """
    docid, _url = _create_probe(tmp_path, PROBE_TITLE, CONTENT_A)
    try:
        content_a = _read_content(docid, tmp_path)
        assert CONTENT_A in content_a, f"probe read-back lost the seed payload: {content_a!r}"

        begin = _kgent_json(
            "journal",
            "begin",
            "--operation",
            "update",
            "--backend",
            "wecom",
            "--doc-uri",
            f"kgent://wecom/{docid}",
            # wecom 无 version 轴（PROBE-NOTES 顶部定谳）→ 不带 --revision-before
            "--snapshot-content",
            content_a,
        )
        op_id = begin["entry"]["op_id"]
        assert begin["entry"]["snapshot"], "journal begin recorded no pre-write snapshot"

        rel = _write_text(tmp_path, "probe-after.md", f"{CONTENT_B}\n")
        _wecom_json(
            CMD_CONTENTS_OVERWRITE,
            {"docid": docid, "content_type": CONTENT_TYPE_TEXT, "file_path": rel},
            cwd=tmp_path,
        )
        content_b = _poll_content(docid, CONTENT_B, tmp_path)
        assert CONTENT_B in content_b, (
            f"post-write read-back never showed {CONTENT_B!r}: {content_b!r}"
        )

        end_args = ["journal", "end", "--op-id", op_id, "--status", "ok"]
        if record_post_snapshot:
            end_args += ["--snapshot-after", content_b]
        end = _kgent_json(*end_args)
        assert end["entry"]["status"] == "ok"
        if record_post_snapshot:
            assert end["entry"].get("snapshot_after"), "journal end recorded no post-write snapshot"
    except BaseException:
        # 断言/KeyboardInterrupt/SystemExit 一视同仁：探针不留给真机租户。
        _teardown(docid)
        raise
    print(
        f"[kgent-phase3-probe] op_id={op_id} docid={docid}\n"
        f"  A (pre-write read-back)  = {content_a!r}\n"
        f"  B (post-write read-back) = {content_b!r}"
    )
    return docid, op_id, content_a, content_b


# ---------------------------------------------------------------------------
# 凭据门（模块级 skipif）
# ---------------------------------------------------------------------------


def _wecom_identity_available() -> bool:
    """wecom-cli 已装且已授权（``auth show --status`` → 单行 ``authorized``）。

    解析复用 :func:`_wecom_cmd`（含 ``WECOM_CLI_BIN`` override 与 win32
    ``.cmd`` 规则）——门与探针看到的必须是同一个二进制。解析落空/非零退出/
    输出不是单行 ``authorized`` 一律按「凭据不可用」处理（fail-closed；
    wecomcli-shared 的 pre-flight 同语义：输出别的都算「未就绪」）。bot-only
    身份，auth init 需维护者本人扫码。本门**不查** ``~/.kgent/config.yaml``
    的 ``backends.wecom.enabled``——那不是凭据而是配置前置（模块 docstring
    「凭据门」节），本文件按 skill 车道直调 wecom-cli，undo 计划的路由断言
    会在配置缺席时失败而非 skip。
    """
    cmd = _wecom_cmd()
    if not Path(cmd[0]).exists():
        return False
    try:
        out = subprocess.run(
            [*cmd, "auth", "show", "--status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0 and out.stdout.strip() == "authorized"


pytestmark.append(
    pytest.mark.skipif(
        not _wecom_identity_available(),
        reason=(
            "real-machine probe: wecom-cli identity unavailable "
            "(wecom-cli missing or auth not authorized — credentials blocked)"
        ),
    )
)


# ---------------------------------------------------------------------------
# B8 —— 多段中文 + emoji 完整性（first-block 事故回归装甲，FM7）
# ---------------------------------------------------------------------------


def test_b8_content_integrity(tmp_path):
    """B8：多段中文 + emoji + 中文标点经 file_path 写入 → 读回全量保真。

    内容**不走 ``--json`` argv 内联**（多行/CJK 的 argv 内联正是 first-block
    事故通道）；断言覆盖标题块、中文标点、emoji（VS16 变体选择符）与换行。
    换行按真机形态钉（模块 docstring「B8 换行保真的形态锚」）：源 ``\\n``
    读回是 ``\\r``——断言的是「换行保真为平台换行符」，不是逐字回声。
    """
    docid, _url = _create_probe(tmp_path, PROBE_TITLE_B8, "seed")
    try:
        rel = _write_text(tmp_path, "probe-b8.md", CONTENT_B8)
        _wecom_json(
            CMD_CONTENTS_OVERWRITE,
            {"docid": docid, "content_type": CONTENT_TYPE_TEXT, "file_path": rel},
            cwd=tmp_path,
        )
        content = _poll_content(docid, "完整性探针", tmp_path)
        for needle in (
            "Phase 3 完整性探针",  # 标题块
            "第一段中文内容",  # 段一
            "「中文标点」",  # 中文标点
            "❤️🎉",  # emoji（VS16 变体选择符随 JSON 往返保留）
            "第二段含 emoji",  # 段二起始
            "与多行\r换行内容",  # 段内换行保真（源 \n → 平台 \r）
            "完整性探针\r\r第一段",  # 空行分段保真（源 \n\n → 平台 \r\r）
        ):
            assert needle in content, f"B8 content lost {needle!r}; fetched={content!r}"
        assert CONTENT_B not in content and "seed" not in content, (
            f"B8 read-back carries stale payload: {content!r}"
        )
        print(f"[kgent-phase3-probe] B8 content repr={content!r}")
        print(
            "[kgent-phase3-probe] B8 content_bytes="
            f"{len(content.encode('utf-8'))} source_bytes={len(CONTENT_B8.encode('utf-8'))}"
        )
    finally:
        _teardown(docid)


# ---------------------------------------------------------------------------
# B5 —— undo 计划 → 快照写回闭环
# ---------------------------------------------------------------------------


def test_b5_undo_plan_and_snapshot_restore(tmp_path):
    """B5：undo 计划（snapshot-restore）→ integration skill 腿写回 → 读回还原。

    计划断言（控制器裁决）：status=ok、mode=plan、integration_skill=
    wecom-integration、mechanism=snapshot-restore、history_hint=None（wecom
    无平台 history）、revision 轴恒 None（无 version 轴）、``snapshot``（A）
    与 ``snapshot_after``（B）路径非空且文件内容与读回逐字一致。
    """
    docid, op_id, content_a, content_b = _journaled_overwrite(tmp_path)
    try:
        plan_json = _kgent_undo(op_id)
        print("undo plan:", json.dumps(plan_json, ensure_ascii=False, indent=2))
        assert plan_json["status"] == "ok"
        assert plan_json["mode"] == "plan"
        assert plan_json["integration_skill"] == "wecom-integration"
        plan = plan_json["plan"]
        assert plan["mechanism"] == "snapshot-restore"
        assert plan["history_hint"] is None  # wecom 无平台 history
        assert plan["revision_before"] is None and plan["revision_after"] is None, (
            "wecom has no version axis — plan must not carry revision evidence"
        )
        assert plan["target"] == f"kgent://wecom/{docid}"

        snapshot_path = Path(plan["snapshot"])
        assert plan["snapshot"] and snapshot_path.is_file()
        assert _read_file_verbatim(snapshot_path) == content_a
        snapshot_after_path = Path(plan["snapshot_after"])
        assert plan["snapshot_after"] and snapshot_after_path.is_file()
        assert _read_file_verbatim(snapshot_after_path) == content_b

        # TOCTOU 执行前复核（wecom-integration skill Undo 节步骤 4）：当前读回
        # 必须仍 == 写后快照文件内容——绝不带着过期计划落写回。
        current = _read_content(docid, tmp_path)
        assert current == _read_file_verbatim(snapshot_after_path), (
            f"TOCTOU drift: current read-back {current!r} != snapshot_after "
            f"{_read_file_verbatim(snapshot_after_path)!r}"
        )

        # 快照在 ~/.kgent/journal/snapshots/（Fs 沙箱外）——先拷进 cwd 再写回。
        rel = _write_text(tmp_path, "snapshot-restore.md", content_a)
        _wecom_json(
            CMD_CONTENTS_OVERWRITE,
            {"docid": docid, "content_type": CONTENT_TYPE_TEXT, "file_path": rel},
            cwd=tmp_path,
        )
        restored = _poll_content(docid, CONTENT_A, tmp_path)
        # 还原判据钉在载荷级（模块 docstring「B5 还原断言的形态锚」）：A 的
        # 载荷在场、被 undo 的写不在场；两侧 repr 全量留证。
        assert CONTENT_A in restored, (
            f"snapshot-restore did not restore {CONTENT_A!r} within "
            f"{_READBACK_POLL_ROUNDS * _READBACK_POLL_INTERVAL_SECONDS}s: "
            f"{restored!r}"
        )
        assert CONTENT_B not in restored, (
            f"post-restore content still carries the undone write: {restored!r}"
        )
        print(
            f"[kgent-phase3-probe] B5 op_id={op_id} docid={docid}\n"
            f"  A (restored payload)   = {content_a!r}\n"
            f"  restored read-back     = {restored!r}\n"
            f"  byte-exact echo of A   = {restored == content_a} "
            "(platform re-renders the trailing CR+padding — see module docstring)"
        )
    finally:
        _teardown(docid)


def test_b5_fm2_rejects_after_concurrent_edit(tmp_path):
    """FM2-wecom：journal end 之后第三方再写 → 写后快照比对不符 → rejected。

    计划期拒绝 = 不产生可执行补偿：mode 仍是 plan、status=rejected、reason
    带 Task 2 定谳的锚点串——绝不规划一次盲回滚（ledger.compensation_plan
    的 FM2-wecom 契约）。
    """
    docid, op_id, _content_a, content_b = _journaled_overwrite(tmp_path)
    try:
        rel = _write_text(tmp_path, "probe-concurrent.md", f"{CONTENT_C}\n")
        _wecom_json(
            CMD_CONTENTS_OVERWRITE,
            {"docid": docid, "content_type": CONTENT_TYPE_TEXT, "file_path": rel},
            cwd=tmp_path,
        )
        content_c = _poll_content(docid, CONTENT_C, tmp_path)
        assert CONTENT_C in content_c, f"concurrent write never became visible: {content_c!r}"
        assert content_c != content_b, "concurrent write did not change the content"

        plan_json = _kgent_undo(op_id)
        print("undo plan (FM2):", json.dumps(plan_json, ensure_ascii=False, indent=2))
        assert plan_json["status"] == "rejected"
        assert plan_json["mode"] == "plan"
        assert plan_json["plan"]["mechanism"] == "snapshot-restore"
        reason = str(plan_json.get("reason", ""))
        assert "post-write snapshot no longer matches" in reason, (
            f"reason is not the FM2-wecom post-write-snapshot verdict: {reason!r}"
        )
    finally:
        _teardown(docid)


def test_b5_fm3_rejects_without_post_snapshot(tmp_path):
    """FM3：end 不带 ``--snapshot-after`` → begin 快照内容比对兜底 → rejected。

    这是 wecom 专属 fail-closed 兜底的活体锚（模块 docstring「journal 纪律」）：
    无写后快照的 update，undo 唯一的新鲜度证据是「当前内容 == 写前快照 A」——
    写已变更内容（B ≠ A）→ 不符 → rejected，绝不盲回滚。reason 必须是 FM3 的
    begin 快照判定串（``snapshot no longer matches``），而非 FM2-wecom 的
    写后快照串——这条区分钉死「兜底走的是哪条证据通道」。
    """
    docid, op_id, content_a, content_b = _journaled_overwrite(tmp_path, record_post_snapshot=False)
    try:
        assert content_a != content_b, "seed and post-write content must differ"
        plan_json = _kgent_undo(op_id)
        print("undo plan (FM3):", json.dumps(plan_json, ensure_ascii=False, indent=2))
        assert plan_json["status"] == "rejected"
        assert plan_json["mode"] == "plan"
        assert plan_json["plan"]["mechanism"] == "snapshot-restore"
        reason = str(plan_json.get("reason", ""))
        assert "snapshot no longer matches" in reason, (
            f"reason is not the FM3 content-comparison verdict: {reason!r}"
        )
        assert "post-write snapshot no longer matches" not in reason, (
            f"FM3 leg must not be judged by the post-write channel: {reason!r}"
        )
    finally:
        _teardown(docid)


def test_b5_create_leg_quarantine_compensation(tmp_path):
    """create 腿：占位 URI 开账 → import 建 → end 回填 → undo ok → rename 隔离。

    create 的补偿不是内容写回而是隔离（B4 同构；平台无删除命令 → rename 到
    ``DELETE-ME-`` 前缀 + 人工清理 runbook）。undo 的目标必须是 end 回填的
    真实 URI（C1：end.doc_uri 优先于 begin 占位）。end 仍带 ``--snapshot-after``
    <首读全文>（M-2：忠实彩排 skill Write 节创建流）——create 腿豁免新鲜度
    比对（ledger 对 create 不走快照通道），快照只是把证据记全，行为不变。
    """
    placeholder_uri = f"kgent://wecom/planned-{PROBE_TITLE_CREATE}"
    begin = _kgent_json(
        "journal",
        "begin",
        "--operation",
        "create",
        "--backend",
        "wecom",
        "--doc-uri",
        placeholder_uri,
        # 空串是合法快照（skill Write 节：create 腿补偿是隔离不是写回）
        "--snapshot-content",
        "",
    )
    op_id = begin["entry"]["op_id"]
    docid: str | None = None
    try:
        rel = _write_probe_docx(tmp_path, "probe-create.docx", CONTENT_A)
        imported = _wecom_json(
            CMD_DOC_IMPORT,
            {
                "doc_type": DOC_TYPE_DOC,
                "file_name": f"{PROBE_TITLE_CREATE}.docx",
                "file_path": rel,
            },
            cwd=tmp_path,
        )
        docid = _extract_docid(imported or {})
        # docid 到手即打印（M-1）：建档受理成功后任何一步失败，探针都凭这行
        # 输出可定位——平台无删除命令，docid 不能只活在断言消息里。
        print(
            f"[kgent-phase3-probe] import accepted: title={PROBE_TITLE_CREATE!r} "
            f"docid={docid} url={_probe_url(imported or {})}"
        )
        first_read = ""
        for _ in range(_IMPORT_POLL_ROUNDS):
            got = _wecom_json(CMD_CONTENTS_GET, {"docid": docid}, cwd=tmp_path, check=False)
            if got is not None and "content" in got:
                first_read = _extract_content(got)
                if CONTENT_A in first_read:
                    probe_url = _probe_url(got)
                    break
            time.sleep(_IMPORT_POLL_INTERVAL_SECONDS)
        else:
            raise AssertionError(
                f"create-leg probe content never became visible: "
                f"{json.dumps(got if got else {}, ensure_ascii=False)[:600]}"
                # M-1：终局错误点名 docid + 标题 + 人工清理指引。
                f"\n  MANUAL CLEANUP (platform has no CLI delete): "
                f"wecom-cli doc names update --json "
                f'\'{{"docid":"{docid}","new_name":"{DELETE_ME_PREFIX}{docid}"}}\' '
                f"then delete probe {PROBE_TITLE_CREATE!r} ({docid}) in the WeCom client"
            )

        end = _kgent_json(
            "journal",
            "end",
            "--op-id",
            op_id,
            "--status",
            "ok",
            "--doc-uri",
            f"kgent://wecom/{docid}",
            # M-2：忠实彩排 SKILL.md 创建流——end 带 --snapshot-after <首读全文>。
            # ledger 对 create 腿豁免新鲜度比对（补偿是隔离不是写回），行为不变；
            # 传了只是把证据记全（「传了 = 有证据」语义，与 skill Write 节同款）。
            "--snapshot-after",
            first_read,
        )
        assert end["entry"]["status"] == "ok"

        plan_json = _kgent_undo(op_id)
        print("undo plan (create):", json.dumps(plan_json, ensure_ascii=False, indent=2))
        assert plan_json["status"] == "ok"
        assert plan_json["mode"] == "plan"
        assert plan_json["integration_skill"] == "wecom-integration"
        plan = plan_json["plan"]
        assert plan["operation"] == "create"
        assert plan["mechanism"] == "snapshot-restore"
        assert plan["history_hint"] is None  # create 补偿走隔离，不查平台 history
        assert plan["target"] == f"kgent://wecom/{docid}", (
            f"undo must target the backfilled real URI, not the placeholder {placeholder_uri!r}"
        )

        # 按计划补偿 = rename 隔离（平台无删除命令——skill Undo 节步骤 7）。
        new_name = f"{DELETE_ME_PREFIX}{docid}"
        renamed = _wecom_json(
            CMD_NAMES_UPDATE, {"docid": docid, "new_name": new_name}, cwd=tmp_path
        )
        assert renamed is not None and renamed.get("errcode") == 0, (
            f"rename quarantine failed: {json.dumps(renamed, ensure_ascii=False)[:400]}"
        )
        _mark_quarantined(docid)
        print(
            f"[kgent-phase3-probe] create leg compensated: docid={docid} url={probe_url}\n"
            f"  renamed to {new_name!r} (platform has no delete — remove it in the "
            "WeCom client by the DELETE-ME prefix)"
        )
    except BaseException:
        if docid is not None:
            _teardown(docid)
        raise
    finally:
        # 占位开账后建档失败的兜底：docid 没拿到就没有可点名对象（import 失败
        # 的异常消息里已带 payload），拿到了就必隔离。
        if docid is not None:
            _teardown(docid)


@pytest.fixture(scope="session", autouse=True)
def _retry_leftovers():
    """session 末对隔离失败的探针再改名一次，仍失败则点名人工清理。"""
    yield
    for docid in list(_leftover_probes):
        if _quarantine_probe(docid):
            _leftover_probes.remove(docid)
            print(f"probe doc {docid} quarantined on retry")
    for docid in _leftover_probes:
        print(
            f"LEFTOVER PROBE DOC: {docid} — no CLI delete exists (platform fact); "
            f"rename it manually: wecom-cli doc names update --json "
            f'\'{{"docid":"{docid}","new_name":"{DELETE_ME_PREFIX}{docid}"}}\', '
            "then delete in the WeCom client and confirm in EVIDENCE"
        )
