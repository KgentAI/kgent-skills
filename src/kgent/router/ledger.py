"""台账（ADR 0005）：op 生命周期 begin/end + 补偿计划。

一个逻辑操作一条 begin；end 落最终状态。快照明文落盘是已知限制
（spec FM5）：目录 0700、文件 0600、不入库。补偿执行归 integration skill，
kgent 只产计划（ADR 0004）。

``compensation_plan``（B3/B5）依台账产出 undo 补偿计划：机制映射 +
新鲜度检查——文档在写后被并发编辑（revision 不符，FM2）或内容偏离快照
（FM3）→ 计划为 rejected，绝不规划一次盲回滚。
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from kgent.errors import KgentError
from kgent.uri import parse_uri

if TYPE_CHECKING:
    from kgent.router.journal import Journal

__all__ = [
    "HISTORY_HINT_BY_BACKEND",
    "INTEGRATION_SKILL_BACKENDS",
    "MECHANISM_BY_BACKEND",
    "LedgerError",
    "begin",
    "compensation_plan",
    "end",
]

#: 平台 → undo 补偿机制（wecom 无平台 history → 快照写回是唯一选项）
MECHANISM_BY_BACKEND: dict[str, str] = {
    "lark": "history-revert",
    "dingtalk": "version-revert",
    "wecom": "snapshot-restore",
}

#: 平台 → 定位补偿版本的 history 查询提示（integration skill 吃这个字段）。
#: wecom 无平台 history（快照写回）→ 不在表内，计划里为 ``None``。
HISTORY_HINT_BY_BACKEND: dict[str, str] = {
    "lark": "docs +history-list → history_version_id(revision_before)",
    "dingtalk": "dws doc +version-list",
}

#: 拥有 integration skill 的后端：undo 对它们只产计划、不直接执行
INTEGRATION_SKILL_BACKENDS = frozenset(MECHANISM_BY_BACKEND)


class LedgerError(KgentError):
    """台账操作错误（end 无 begin 等）。"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_op_id() -> str:
    """``op-<yyyymmdd>-<8hex>``（B1：uuid 后缀，与 policy._next_op_id 同格式）。

    同秒/跨进程均唯一——2026-09-05 事故（按序号计数同日撞号）的回归防线。
    """
    return f"op-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"


def _snapshot_path(journal: Journal, op_id: str) -> Path:
    return journal.journal_dir / "snapshots" / f"{op_id}.txt"


def _write_snapshot_file(journal: Journal, op_id: str, content: str, suffix: str) -> str:
    """0600 快照文件（FM5：目录 0700、文件 0600；POSIX-only 收紧，Windows 无害 no-op）。

    begin（写前快照 ``.txt``）与 end（写后快照 ``.after.txt``，Phase 3 Task 2
    维护者签核方案 A）共用一条落盘纪律：mkdir 的默认 mode 不够紧，已存在时
    顺带把既有目录一并收紧，与 Journal._ensure_permissions 同哲学。

    ``newline=""``（byte 透明落盘，Phase 3 Task 6 真机定谳）：wecom-cli 读回
    content 恒带尾部 ``\\r`` + padding，文本模式缺省会把 ``\\n`` 翻成
    ``os.linesep``——快照字节一旦被翻译，读回就不再是调用方传入的那串，
    FM2-wecom/FM3 的逐字比对会误拒（配对读见 :func:`_snapshot_file_content`）。
    """
    path = _snapshot_path(journal, op_id).with_suffix(suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
        fh.write(content)
    os.chmod(path, 0o600)
    return str(path)


def begin(
    journal: Journal,
    *,
    operation: str,
    backend: str,
    target_uri: str,
    revision_before: str | int | None,
    content: str | None = None,
) -> dict[str, Any]:
    """登记一个逻辑写操作；content 非空时写 0600 快照文件（FM3/ADR 0005）。"""
    op_id = _new_op_id()
    entry: dict[str, Any] = {
        "op_id": op_id,
        "kind": "begin",
        "ts": _now(),
        "operation": operation,
        "backend": backend,
        "target": target_uri,
        "revision_before": revision_before,
    }
    if content is not None:
        entry["snapshot"] = _write_snapshot_file(journal, op_id, content, ".txt")
    journal.append(entry)
    return entry


def end(
    journal: Journal,
    op_id: str,
    *,
    status: str,
    revision_after: str | int | None = None,
    doc_uri: str | None = None,
    snapshot_after: str | None = None,
) -> dict[str, Any]:
    """落账。begin 不存在、或该 op 已 end 过 → :class:`LedgerError`（fail closed）。

    ``Journal.get`` 返回该 op_id 的**最新** entry，所以已 end 的 op 在这里
    看到的就是它的 end entry（``kind == "end"``）——二次 end 是调用方状态机
    bug，拒绝而不是追加第二条 end。

    ``doc_uri``（可选）：create 腿的回填通道。begin 时只有 planned 占位
    ``kgent://`` URI；写入成功拿到真实 token 后，由 end entry 记真实目标——
    ``compensation_plan`` 取 target 时它优先于 begin 的占位（append-only
    不变：只是 end entry 多一个字段，历史 entry 不改写）。

    ``snapshot_after``（可选，Phase 3 Task 2 维护者签核方案 A）：写后全文快照，
    落 ``snapshots/<op_id>.after.txt``（0600，FM5 同 begin），entry 增
    ``snapshot_after`` 字段记文件路径。wecom ``doc contents get`` 不回 version
    （真机探针证实）→ 写后快照是这类无平台 revision 后端的 undo 新鲜度证据；
    ``compensation_plan`` 只在 ``revision_after`` 缺席且非 create 腿时用它。
    """
    latest = journal.get(op_id)
    if latest is None:
        raise LedgerError(f"unknown ledger op id: {op_id!r}")
    if latest.get("kind") == "end":
        raise LedgerError(f"ledger op already ended: {op_id!r}")
    entry: dict[str, Any] = {
        "op_id": op_id,
        "kind": "end",
        "ts": _now(),
        "status": status,
    }
    if revision_after is not None:
        entry["revision_after"] = revision_after
    if doc_uri:
        entry["doc_uri"] = doc_uri
    if snapshot_after is not None:
        entry["snapshot_after"] = _write_snapshot_file(journal, op_id, snapshot_after, ".after.txt")
    journal.append(entry)
    return entry


# ---------------------------------------------------------------------------
# 补偿计划（B3/B5；ADR 0005：undo 对台账 op 只产计划，执行归 integration skill）
# ---------------------------------------------------------------------------


def _same_revision(a: Any, b: Any) -> bool:
    """revision 相等比较（字符串化）。

    Lark 的 ``metadata.version`` 是字符串 revision_id，台账/CLI 里常是 int；
    统一字符串化避免 "56" vs 56 这种表示差异造成假拒绝。
    """
    return str(a) == str(b)


def _ledger_record(
    journal: Journal, op_id: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """``(begin, end | None)``：同一 op_id 的两条台账 entry 合并成一个 op 视图。"""
    begin_entry: dict[str, Any] | None = None
    end_entry: dict[str, Any] | None = None
    for entry in journal.entries:
        if entry.get("op_id") != op_id:
            continue
        kind = entry.get("kind")
        if kind == "begin":
            begin_entry = entry
        elif kind == "end":
            end_entry = entry
    return begin_entry, end_entry


def _target_of(entry: dict[str, Any]) -> str | None:
    """op 的目标 uri：台账 begin 的 ``target``，legacy 写 entry 的 ``targets[0]``。"""
    target = entry.get("target")
    if isinstance(target, str) and target:
        return target
    targets = [t for t in (entry.get("targets") or []) if isinstance(t, str)]
    return targets[0] if targets else None


def _backend_of(entry: dict[str, Any], target: str | None) -> str | None:
    """backend 名：entry 显式 ``backend`` 优先，否则 ``parse_uri(target)``。

    ``parse_uri`` 的用法与 ``journal.undo`` 的既有路径一致。
    """
    backend = entry.get("backend")
    if isinstance(backend, str) and backend:
        return backend
    if target:
        try:
            backend_name, _ = parse_uri(target)
        except KgentError:
            return None
        return backend_name
    return None


def _version_after_from_snapshot(snapshot: dict[str, Any], target: str | None) -> Any:
    """legacy 写 entry 的 ``version_after``（journal._version_after_by_uri 语义）。"""
    inner = snapshot.get("targets")
    if isinstance(inner, dict):
        leg = inner.get(target) if target is not None else None
        if isinstance(leg, dict):
            return leg.get("version_after")
        return None
    if "version_after" in snapshot:
        return snapshot.get("version_after")
    return None


def _content_before_from_snapshot(snapshot: dict[str, Any], target: str | None) -> str | None:
    """legacy 写 entry 的 ``content_before``（journal._content_before_by_uri 语义）。"""
    inner = snapshot.get("targets")
    if isinstance(inner, dict):
        leg = inner.get(target) if target is not None else None
        if isinstance(leg, dict):
            cb = leg.get("content_before")
            return cb if isinstance(cb, str) else None
        return None
    cb = snapshot.get("content_before")
    return cb if isinstance(cb, str) else None


def _snapshot_file_content(path_str: Any) -> str | None:
    """台账 begin 的内容快照文件（FM3/ADR 0005），缺失/不可读 → ``None``。

    ``newline=""``（byte 透明读回，Phase 3 Task 6 真机定谳）：universal
    newlines 会把 ``\\r`` 折成 ``\\n``——wecom-cli 读回 content 恒带尾部
    ``\\r``，翻译过的读回与 ``current.content`` 恒不等，FM2-wecom/FM3 逐字
    比对会对一切真机内容误拒（配对写见 :func:`_write_snapshot_file`；
    装甲用例 ``test_compensation_plan_snapshot_round_trip_cr_transparent``）。
    """
    if not (isinstance(path_str, str) and path_str):
        return None
    try:
        with open(path_str, "r", encoding="utf-8", newline="") as fh:
            return fh.read()
    except OSError:
        return None


def compensation_plan(
    op_id: str,
    *,
    backends: dict[str, Any],
    journal: Journal,
) -> dict[str, Any]:
    """为 ``op_id`` 产出 undo 补偿计划（B3/B5；不执行任何写操作）。

    台账 op（``kind == "begin"`` 的 begin/end 两条 entry）与 legacy 写 entry
    （``build_entry`` 形态）都认；``Journal.get`` 只回最新一条，所以这里直接
    扫 entries 合并出 op 视图。op 的 target 取 end entry 的 ``doc_uri``（create
    腿回填的真实 URI，C1）优先，无回填时用 begin 的 target（兼容旧式 entry）。

    新鲜度（ADR 0005，FM2/FM3）——有证据才允许规划，且证据不符即拒绝：

    - 台账 end 的 ``revision_after``（或 legacy 快照里的 ``version_after``）
      与当前文档 revision 不符 → ``rejected``，reason 指明两侧 revision（FM2）。
    - 无 revision 记录的 update → end 的写后快照文件（``snapshot_after``，
      Phase 3 Task 2）与当前内容比对，不一致 → ``rejected``（FM2-wecom）。
    - 写后快照也没有的旧 entry → 台账内容快照文件（或 legacy 快照的
      ``content_before``）与当前内容比对，不一致 → ``rejected``（FM3）。
    - 两类证据都没有的 update → ``rejected``（拒绝盲回滚）。
    - ``create`` 补偿是删除（B4）：文档已不在 → 幂等成功，仍 ``ok``。

    未知 op_id → :class:`LedgerError`（与 ``end()`` 同约定）。
    """
    begin_entry, end_entry = _ledger_record(journal, op_id)
    if begin_entry is None:
        # legacy 写 entry：没有 begin/kind，本体就是那条写记录。
        legacy = journal.get(op_id)
        if legacy is None:
            raise LedgerError(f"unknown ledger op id: {op_id!r}")
        begin_entry, end_entry = legacy, None

    operation = str(begin_entry.get("operation", "")) or None
    # target 优先级（C1）：同 op_id 的 end entry 的 ``doc_uri``（create 腿写入
    # 成功后回填的真实 URI）> begin entry 的 target（create 腿是 planned 占位；
    # 旧式无回填 entry 兼容——update 腿两者本就一致）。
    end_doc_uri = (end_entry or {}).get("doc_uri")
    target = (
        end_doc_uri if isinstance(end_doc_uri, str) and end_doc_uri else _target_of(begin_entry)
    )
    backend = _backend_of(begin_entry, target)
    mechanism = MECHANISM_BY_BACKEND.get(backend) if backend else None

    snapshot_field = begin_entry.get("snapshot")
    snap_path = snapshot_field if isinstance(snapshot_field, str) else None
    snap_dict = snapshot_field if isinstance(snapshot_field, dict) else {}
    # 写后快照（Phase 3 Task 2）：同 op_id 的 end entry 记的写后全文文件路径。
    end_snapshot_after = (end_entry or {}).get("snapshot_after")
    snap_after_path = end_snapshot_after if isinstance(end_snapshot_after, str) else None

    revision_before = begin_entry.get("revision_before")
    revision_after: Any = (end_entry or {}).get("revision_after")
    if revision_after is None and snap_dict:
        revision_after = _version_after_from_snapshot(snap_dict, target)

    # 读当前文档（只读；读不到不抛——它是新鲜度判断的输入，不是失败）。
    current: Any = None
    read_error: str | None = None
    backend_obj = backends.get(backend) if backend else None
    if backend_obj is not None and target:
        try:
            current = backend_obj.read_document(str(target))
        except Exception as exc:  # noqa: BLE001 — 文档缺失/后端故障都进新鲜度判定
            read_error = f"{exc}"
    revision_current = current.metadata.version if current is not None else None

    reason: str | None = None
    if mechanism is None:
        reason = f"no compensation mechanism for backend {backend!r}"
    elif revision_after is not None:
        if current is None:
            if operation != "create":
                reason = (
                    f"document {target} is gone; cannot verify freshness against "
                    f"revision {revision_after}" + (f" ({read_error})" if read_error else "")
                )
            # create + 已删除 → B4 幂等成功，不拒绝
        elif not _same_revision(revision_current, revision_after):
            reason = (
                f"document edited since the journaled write: expected revision "
                f"{revision_after}, current {revision_current}"
            )
    elif snap_after_path is not None and operation != "create":
        # FM2-wecom（Phase 3 Task 2）：平台不给 revision 的后端（wecom）→
        # 用 end 的写后全文快照比对。快照不可读必须 fail closed——退回 begin
        # 快照兜底会把「证据丢了」误判成「内容没变」，正是盲回滚的入口。
        after_content = _snapshot_file_content(snap_after_path)
        if after_content is None:
            reason = (
                "cannot verify freshness: post-write snapshot file is unreadable; "
                "refusing to plan a blind restore"
            )
        elif current is None:
            reason = (
                f"document {target} is gone; post-write snapshot freshness cannot be "
                "verified" + (f" ({read_error})" if read_error else "")
            )
        elif str(current.content) != after_content:
            reason = (
                "document content changed since the journaled write (post-write "
                f"snapshot no longer matches); current revision {revision_current}"
            )
    elif operation != "create":
        # FM3：无 revision_after 的旧 entry → 快照内容比对（wecom 路径）。
        before = _snapshot_file_content(snap_path)
        if before is None and snap_dict:
            before = _content_before_from_snapshot(snap_dict, target)
        if before is None:
            reason = (
                "cannot verify freshness: no revision_after recorded and no "
                "snapshot content available; refusing to plan a blind revert"
            )
        elif current is None:
            reason = f"document {target} is gone; snapshot freshness cannot be verified" + (
                f" ({read_error})" if read_error else ""
            )
        elif str(current.content) != before:
            reason = (
                "document content changed since the journaled write (snapshot no "
                f"longer matches); current revision {revision_current}"
            )

    plan: dict[str, Any] = {
        "backend": backend,
        "target": str(target) if target else None,
        "mechanism": mechanism,
        "operation": operation,
        "revision_before": revision_before,
        "revision_after": revision_after,
        "revision_current": revision_current,
        "snapshot": snap_path,
        # 写后快照文件（Phase 3 Task 2）；无 revision 证据的 update 才拿它当新鲜度证据。
        "snapshot_after": snap_after_path,
        # create 补偿走删除，不查平台 history → 提示留空。
        "history_hint": (
            None if operation == "create" else HISTORY_HINT_BY_BACKEND.get(backend or "")
        ),
    }
    result: dict[str, Any] = {
        "operation": "undo",
        "op_id": op_id,
        "mode": "plan",
        "status": "rejected" if reason else "ok",
        "integration_skill": f"{backend}-integration" if backend else None,
        "plan": plan,
    }
    if reason:
        result["reason"] = reason
    return result
