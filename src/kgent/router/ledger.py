"""台账（ADR 0005）：op 生命周期 begin/end + 补偿计划。

一个逻辑操作一条 begin；end 落最终状态。快照明文落盘是已知限制
（spec FM5）：目录 0700、文件 0600、不入库。补偿执行归 integration skill，
kgent 只产计划（ADR 0004）。
"""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from kgent.errors import KgentError

if TYPE_CHECKING:
    from kgent.router.journal import Journal

__all__ = [
    "INTEGRATION_SKILL_BACKENDS",
    "MECHANISM_BY_BACKEND",
    "LedgerError",
    "begin",
    "end",
]

#: 平台 → undo 补偿机制（wecom 无平台 history → 快照写回是唯一选项）
MECHANISM_BY_BACKEND: dict[str, str] = {
    "lark": "history-revert",
    "dingtalk": "version-revert",
    "wecom": "snapshot-restore",
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
        "op_id": op_id, "kind": "begin", "ts": _now(),
        "operation": operation, "backend": backend, "target": target_uri,
        "revision_before": revision_before,
    }
    if content is not None:
        path = _snapshot_path(journal, op_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        # FM5: 快照目录也收紧到 0700（mkdir 的默认 mode 不够紧；mkdir 已存在时
        # 顺带把既有目录一并收紧，与 Journal._ensure_permissions 同哲学）。
        # POSIX only；Windows 上为无害 no-op。
        os.chmod(path.parent, 0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.chmod(path, 0o600)
        entry["snapshot"] = str(path)
    journal.append(entry)
    return entry


def end(
    journal: Journal,
    op_id: str,
    *,
    status: str,
    revision_after: str | int | None = None,
) -> dict[str, Any]:
    """落账。begin 不存在 → :class:`LedgerError`（fail closed）。"""
    if journal.get(op_id) is None:
        raise LedgerError(f"unknown ledger op id: {op_id!r}")
    entry: dict[str, Any] = {
        "op_id": op_id, "kind": "end", "ts": _now(), "status": status,
    }
    if revision_after is not None:
        entry["revision_after"] = revision_after
    journal.append(entry)
    return entry
