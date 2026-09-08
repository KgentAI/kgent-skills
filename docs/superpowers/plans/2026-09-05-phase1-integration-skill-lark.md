# Phase 1（lark）Integration Skill 中心制 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 spec v3 的 Phase 1——台账（journal begin/end + 补偿计划）、route --dry-run、op_id 唯一性、lark-integration 升格为 Lark 唯一接口、三个 kgent skills 编排化、evals 与真机验收。

**Architecture:** kgent CLI 保留策略（route）与台账（ledger），不再对 lark 直接执行写补偿（产出计划，由 lark-integration 执行）；LarkAdapter search/read/write 标 deprecated 不删码。统一语言见 `CONTEXT.md`，决策见 `docs/adr/0004`、`docs/adr/0005`。

**Tech Stack:** Python 3.12（stdlib only：argparse/json/uuid/pathlib），pytest+mutmut+hypothesis+diff-cover（已在 `[dev]`），lark-cli（已装）。

**Spec:** `specs/2026-09-05-write-path-skill-delegation-design.md`（approved v3）

## Global Constraints

- 零新增依赖；新模块只用 stdlib
- 验收标准 B1–B12（spec「可执行验收标准」节）每条见到 RED→GREEN
- B12：现有测试套件零**新增**失败——先跑 baseline 并原样记录（含 `test_archive_delete_undo.py`）
- 不得修改任何既有测试的断言（anti-gaming 规则 1/2）
- `Journal` 既有行为（lenient load、0600/0700 权限、NDJSON、retention）不变；strict 只新增
- 新代码注释风格跟随仓库（中文/英文混排、模块 docstring 带 §/S 引用习惯）
- 每任务 GREEN 后 commit；mutant 恢复以 `git diff` 验证
- Windows（win32 + Git Bash）为本机目标环境

**Baseline（执行者第一步，未动任何代码前）：**

```bash
cd kgent-skills && python -m pytest tests -q 2>&1 | tail -5   # 记录原样输出
```

---

### Task 1: B1 — op_id 唯一性（事故回归）

**Files:**
- Modify: `src/kgent/router/policy.py:53-55`（`_next_op_id`）
- Modify: `src/kgent/router/journal.py`（`_undo_op_id`，同款撞号）
- Test: `tests/test_op_id.py`（Create）

**Interfaces:**
- Produces: `_next_op_id() -> str` 形如 `op-20260905-<8hex>`（同进程同秒两次不同）；`_undo_op_id(op_id) -> str` 同规则派生

- [ ] **Step 1: 写失败测试**

```python
# tests/test_op_id.py
"""B1: op_id 同秒唯一（2026-09-05 事故回归：op-20260905-01 全天撞号）。"""
from kgent.router.policy import _next_op_id


def test_same_second_two_ids_differ():
    a, b = _next_op_id(), _next_op_id()
    assert a != b


def test_format_keeps_op_prefix_and_date():
    import re
    oid = _next_op_id()
    assert re.fullmatch(r"op-\d{8}-[0-9a-f]{8}", oid), oid
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_op_id.py -v`
Expected: `test_same_second_two_ids_differ` FAIL（当前 `op-<date>-01`、`-02`——不同但**格式断言**会先失败？不会：`-02` 是两位序号非 8hex，格式测试 FAIL；同秒测试 PASS）。以格式断言为 RED。

- [ ] **Step 3: 最小实现**

```python
# policy.py 替换 _next_op_id
def _next_op_id() -> str:
    """Unique ``op-<yyyymmdd>-<8hex>`` id (B1: uuid suffix — 同秒/跨进程均唯一).

    历史格式 ``op-<yyyymmdd>-<seq>`` 按进程计数，跨进程同日必撞号
    （2026-09-05 事故：全天操作共用 ``op-20260905-01``，undo 必然错乱）。
    """
    return f"op-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"
```

`policy.py` 头部补 `import uuid`。`journal.py` 的 `_undo_op_id` 同样在派生串尾部加 `-{uuid.uuid4().hex[:8]}`（先读该函数现状再改，保持 `undo-` 前缀语义）。

- [ ] **Step 4: 跑测试确认通过 + 全套无新增失败**

Run: `python -m pytest tests/test_op_id.py -v && python -m pytest tests -q 2>&1 | tail -3`
Expected: 新测试 PASS；全套失败数 ≤ baseline。

- [ ] **Step 5: Commit**

```bash
git add src/kgent/router/policy.py src/kgent/router/journal.py tests/test_op_id.py
git commit -m "fix: op_id 加 uuid 后缀，消除同日撞号（B1/事故回归）"
```

---

### Task 2: B2 — ledger 模块（begin/end + 快照 + strict 读）

**Files:**
- Create: `src/kgent/router/ledger.py`
- Modify: `src/kgent/router/journal.py`（`Journal.__init__` 加 `strict_load` 参数；`_load` 按之报错）
- Test: `tests/test_ledger.py`（Create）

**Interfaces:**
- Consumes: `Journal`（`append`/`get`/`entries`）、`KGENT_HOME`
- Produces:
  - `MECHANISM_BY_BACKEND = {"lark": "history-revert", "dingtalk": "version-revert", "wecom": "snapshot-restore"}`
  - `INTEGRATION_SKILL_BACKENDS = {"lark", "dingtalk", "wecom"}`
  - `begin(journal, *, operation, backend, target_uri, revision_before, content=None) -> dict`（entry 含 8hex `op_id`、`kind:"begin"`、快照文件路径；返回 entry）
  - `end(journal, op_id, *, status, revision_after=None) -> dict`（`kind:"end"`；对无 begin 的 op_id 抛 `LedgerError`）
  - `compensation_plan(journal, op_id, *, backends) -> dict`（B3/B5/B6 的计划；详见 Task 4）
  - `LedgerError(KgentError)`；`Journal(..., strict_load=True)` 下坏行抛 `JournalCorruptError`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_ledger.py
"""B2: 台账生命周期 + FM1 finally + FM5 权限 + FM8 strict 读。"""
import json
import stat
import pytest
from kgent.router.journal import Journal
from kgent.router.ledger import (
    LedgerError, begin, end, MECHANISM_BY_BACKEND, INTEGRATION_SKILL_BACKENDS,
)


@pytest.fixture
def journal(tmp_home):
    return Journal(tmp_home)


def test_begin_then_end_lifecycle(journal):
    entry = begin(journal, operation="update", backend="lark",
                  target_uri="kgent://lark/ABC", revision_before=50, content="A")
    assert entry["kind"] == "begin" and entry["revision_before"] == 50
    got = journal.get(entry["op_id"])
    assert got is not None and got["kind"] == "begin"
    done = end(journal, entry["op_id"], status="ok", revision_after=56)
    assert done["kind"] == "end" and done["status"] == "ok"


def test_end_without_begin_raises(journal):
    with pytest.raises(LedgerError):
        end(journal, "op-20260905-deadbeef", status="ok")


def test_same_second_begins_unique_ids(journal):
    a = begin(journal, operation="update", backend="lark",
              target_uri="kgent://lark/ABC", revision_before=1)
    b = begin(journal, operation="update", backend="lark",
              target_uri="kgent://lark/ABC", revision_before=1)
    assert a["op_id"] != b["op_id"]


def test_begin_writes_snapshot_file_0600(journal, tmp_home):
    entry = begin(journal, operation="update", backend="wecom",
                  target_uri="kgent://wecom/X", revision_before=3, content="秘密快照")
    snap = tmp_home / "journal" / "snapshots" / f"{entry['op_id']}.txt"
    assert snap.read_text(encoding="utf-8") == "秘密快照"
    assert stat.S_IMODE(snap.stat().st_mode) == 0o600


def test_strict_load_raises_on_corrupt_line(tmp_home):
    jdir = tmp_home / "journal"
    jdir.mkdir(parents=True)
    (jdir / "journal.ndjson").write_text('{"op_id": "op-1"}\n{broken json\n', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        Journal(tmp_home, strict_load=True)


def test_mechanism_map_covers_integration_backends():
    assert set(MECHANISM_BY_BACKEND) == INTEGRATION_SKILL_BACKENDS
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_ledger.py -v`
Expected: FAIL（`ModuleNotFoundError: kgent.router.ledger`）

- [ ] **Step 3: 实现 ledger.py**

```python
# src/kgent/router/ledger.py
"""台账（ADR 0005）：op 生命周期 begin/end + 补偿计划。

一个逻辑操作一条 begin；end 落最终状态。快照明文落盘是已知限制
（spec FM5）：目录 0700、文件 0600、不入库。补偿执行归 integration skill，
kgent 只产计划（ADR 0004）。
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kgent.errors import KgentError

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
```

（文件头补 `import os`；`Journal` 从 `.journal` 导入。）

`journal.py` 的 `Journal.__init__` 加参：`def __init__(self, home=None, *, encrypt=False, retention_days=30, strict_load=False)`，`self.strict_load = strict_load`；`_load` 的 `except json.JSONDecodeError: continue` 改为：

```python
            except json.JSONDecodeError:
                if self.strict_load:
                    raise
                continue
```

- [ ] **Step 4: 跑测试确认通过 + 全套**

Run: `python -m pytest tests/test_ledger.py -v && python -m pytest tests -q 2>&1 | tail -3`
Expected: PASS；失败数 ≤ baseline。

- [ ] **Step 5: Commit**

```bash
git add src/kgent/router/ledger.py src/kgent/router/journal.py tests/test_ledger.py
git commit -m "feat: 台账 ledger begin/end + 快照 + strict 读（B2/FM1/FM5/FM8）"
```

---

### Task 3: B2 — CLI `kgent journal begin/end`

**Files:**
- Modify: `src/kgent/cli.py`（parser 注册 ~`p_undo` 附近；`_cmd_journal_begin`/`_cmd_journal_end`）
- Test: `tests/test_cli.py`（追加，不改既有断言）

**Interfaces:**
- Consumes: Task 2 的 `begin`/`end`；`_build_router()`（`router.backends`/`router.journal`）
- Produces: `kgent journal begin --operation update --backend lark --doc-uri U [--revision-before N] [--snapshot-content S]`、`kgent journal end --op-id X --status ok|failed [--revision-after N]`；JSON 输出 entry

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_cli.py` 末尾，跟随该文件既有 CLI 调用惯例——执行者先读文件头 3 个既有用例的调用方式照抄）

```python
def test_journal_begin_end_cli(tmp_home, monkeypatch):
    # 照 tests/test_cli.py 既有 main() 调用惯例；以下为断言核心
    from kgent.cli import main
    rc = main(["--json", "journal", "begin", "--operation", "update",
               "--backend", "lark", "--doc-uri", "kgent://lark/ABC",
               "--revision-before", "50"])
    assert rc == 0
    rc = main(["--json", "journal", "end", "--op-id", _last_op_id(tmp_home),
               "--status", "ok", "--revision-after", "56"])
    assert rc == 0


def test_journal_end_unknown_id_fails(tmp_home):
    from kgent.cli import main
    assert main(["--json", "journal", "end", "--op-id",
                 "op-20260905-00000000", "--status", "ok"]) != 0
```

（`_last_op_id` 为测试内 helper：读 `tmp_home/journal/journal.ndjson` 最后一行取 `op_id`。）

- [ ] **Step 2: 跑失败**（`kgent journal` 不存在 → FAIL）

- [ ] **Step 3: 实现**（cli.py，`p_undo` 注册块之后）

```python
    # journal（台账，ADR 0005）
    p_journal = sub.add_parser("journal", help="Ledger (op lifecycle)", parents=[common])
    journal_sub = p_journal.add_subparsers(dest="journal_cmd", required=True)
    p_begin = journal_sub.add_parser("begin", help="Register a logical write op")
    p_begin.add_argument("--operation", required=True, choices=["create", "update", "delete"])
    p_begin.add_argument("--backend", required=True)
    p_begin.add_argument("--doc-uri", dest="doc_uri", required=True)
    p_begin.add_argument("--revision-before", dest="revision_before", default=None)
    p_begin.add_argument("--snapshot-content", dest="snapshot_content", default=None)
    p_begin.set_defaults(func=_cmd_journal_begin)
    p_end = journal_sub.add_parser("end", help="Finalize a ledger op")
    p_end.add_argument("--op-id", dest="op_id", required=True)
    p_end.add_argument("--status", required=True, choices=["ok", "failed"])
    p_end.add_argument("--revision-after", dest="revision_after", default=None)
    p_end.set_defaults(func=_cmd_journal_end)
```

命令体：

```python
def _cmd_journal_begin(args: argparse.Namespace) -> int:
    from kgent.router.journal import Journal
    from kgent.router.ledger import begin
    revision = int(args.revision_before) if args.revision_before else None
    entry = begin(
        Journal(_home()),  # 台账只依赖 home，不需要已配置的 backends
        operation=args.operation, backend=args.backend,
        target_uri=args.doc_uri, revision_before=revision,
        content=args.snapshot_content,
    )
    if getattr(args, "json", False):
        _json_out({"operation": "journal-begin", "entry": entry})
    else:
        _text_out(f"begin {entry['op_id']}")
    return 0


def _cmd_journal_end(args: argparse.Namespace) -> int:
    from kgent.router.journal import Journal
    from kgent.router.ledger import LedgerError, end
    revision = int(args.revision_after) if args.revision_after else None
    try:
        entry = end(Journal(_home()), args.op_id,
                    status=args.status, revision_after=revision)
    except LedgerError as exc:
        if getattr(args, "json", False):
            _json_out({"operation": "journal-end", "status": "failed", "error": str(exc)})
        return 1
    if getattr(args, "json", False):
        _json_out({"operation": "journal-end", "entry": entry})
    return 0
```

- [ ] **Step 4: 跑通过 + 全套**；- [ ] **Step 5: Commit** `feat: kgent journal begin/end CLI（B2）`

---

### Task 4: B3/B5 — 补偿计划 + undo plan 模式

**Files:**
- Modify: `src/kgent/router/ledger.py`（`compensation_plan`）
- Modify: `src/kgent/cli.py`（`_cmd_undo` 分流）
- Test: `tests/test_undo_ledger.py`（Create）

**Interfaces:**
- Consumes: `Journal.get`（entry：`kind:"begin"`/写 entry 两类都要认）、`backends[name].read_document(uri).metadata.version`（FakeBackend 与 LarkAdapter 均满足）
- Produces:
  - `compensation_plan(op_id, *, backends, journal) -> dict`：

```python
{"operation": "undo", "op_id": ..., "mode": "plan", "status": "ok"|"rejected",
 "integration_skill": "lark-integration",
 "plan": {"backend": "lark", "target": ..., "mechanism": "history-revert",
          "operation": "update"|"create", "revision_before": ...,
          "revision_after": ..., "revision_current": ...,
          "snapshot": "<path>|null", "history_hint": "<平台 history 查询参数提示>|null"}}
```

  - 新鲜度：`revision_current != revision_after`（写 entry 的 `version_after`/end 的 `revision_after`）→ `status:"rejected"`，`reason` 指明两侧 revision（FM2）。无 `revision_after` 记录的旧 entry → 用快照内容比对（wecom 路径，FM3）。
  - `_cmd_undo`：op 的 backend ∈ `INTEGRATION_SKILL_BACKENDS` → JSON 输出 plan，`exit 0`（rejected 时 `exit 1`）；否则走既有 `journal_undo`（**B12：FakeBackend 测试路径不动**）

- [ ] **Step 1: 写失败测试**（用 `FakeBackend`，惯例照 `tests/test_archive_delete_undo.py` 头部 fixture）

```python
# tests/test_undo_ledger.py
"""B3/B5 计划生成：机制映射 + 新鲜度拒绝（FM2/FM3）+ create 计划。"""
import pytest
from kgent.router.journal import Journal, build_entry
from kgent.router.ledger import begin, compensation_plan, end
from tests.fakes.fake_backend import FakeBackend
from tests.conftest import _full_caps  # 若为私有则就地复制该 dict


@pytest.fixture
def lark_backend(tmp_home):
    fb = FakeBackend(name="lark", trust_zone="internal", capabilities=_full_caps())
    fb.docs["kgent://lark/DOC1"] = <按该文件既有方式构造 Document，version=56>
    return fb


def test_plan_mechanism_history_revert(lark_backend, tmp_home):
    journal = Journal(tmp_home)
    entry = begin(journal, operation="update", backend="lark",
                  target_uri="kgent://lark/DOC1", revision_before=50)
    end(journal, entry["op_id"], status="ok", revision_after=56)
    plan = compensation_plan(entry["op_id"], backends={"lark": lark_backend}, journal=journal)
    assert plan["status"] == "ok"
    assert plan["plan"]["mechanism"] == "history-revert"
    assert plan["plan"]["revision_current"] == 56


def test_plan_rejected_when_edited_since(lark_backend, tmp_home):
    journal = Journal(tmp_home)
    entry = begin(journal, operation="update", backend="lark",
                  target_uri="kgent://lark/DOC1", revision_before=50)
    end(journal, entry["op_id"], status="ok", revision_after=56)
    lark_backend.docs["kgent://lark/DOC1"].metadata.version = 57  # 他人并发编辑
    plan = compensation_plan(entry["op_id"], backends={"lark": lark_backend}, journal=journal)
    assert plan["status"] == "rejected" and "57" in plan["reason"]
```

（Document 构造行以 `test_archive_delete_undo.py` 的真实写法替换尖括号占位——执行者打开该文件照抄 fixture，**这是唯一的"参照既有文件"指令，其余全部自带**。）

- [ ] **Step 2: RED** → **Step 3: 实现** `compensation_plan`（journal.py 的 `undo()` 356-439 行是新鲜度检查的既有写法，照其 `_version_after_by_uri` 语义）→ **Step 4: `_cmd_undo` 分流**：

```python
def _cmd_undo(args: argparse.Namespace) -> int:
    router, _config = _build_router()
    op_id = args.op_id
    entry = router.journal.get(op_id)
    backend = _entry_backend_name(entry)  # 新 helper：entry["backend"] 或 targets[0] parse_uri
    from kgent.router.ledger import INTEGRATION_SKILL_BACKENDS, compensation_plan
    if backend in INTEGRATION_SKILL_BACKENDS:
        plan = compensation_plan(op_id, backends=router.backends, journal=router.journal)
        if getattr(args, "json", False):
            _json_out(plan)
        else:
            _text_out(f"{plan['status']}: {plan['plan']['mechanism']} via "
                      f"{plan['integration_skill']}")
        return 0 if plan["status"] == "ok" else 1
    result = journal_undo(
        op_id, backends=router.backends, journal=router.journal, audit=router.audit
    )
    ...  # 既有输出逻辑原样保留
```

- [ ] **Step 5: 全套 + 手工 mutant**（翻转新鲜度比较 `!=`→`==`，B 测试必须杀掉；恢复以 `git diff` 验证）→ **Step 6: Commit** `feat: undo 对 integration 后端产出补偿计划（B3/B5/FM2/FM3）`

---

### Task 5: B7 — `kgent route --dry-run`

**Files:**
- Modify: `src/kgent/cli.py`（parser + `_cmd_route`）
- Test: `tests/test_route_command.py`（Create）

**Interfaces:**
- Consumes: `analyze_sensitivity(content, confidence) -> (tier, confidence, provenance)`（sensitivity.py:46）、`enforce_zone(tier, backend_zone, backend_name)`（同文件 :84，PolicyError）、`router.backends[name].trust_zone`
- Produces: `kgent route --content X [--backends lark,wecom]` → `{"sensitivity": ..., "provenance": ..., "allowed_backends": [...], "rejected": [{"backend": ..., "reason": ...}]}`；全被拒 → exit 3

- [ ] **Step 1: 失败测试**（fake external 后端保持 zone 拒绝路径；三平台 internal 放行——B7）

```python
def test_route_allows_internal_for_confidential(tmp_home):
    rc, out = _run_route(["lark"], content="密: token-rotate-30d")     # helper 包 main()+capsys
    assert out["sensitivity"] in {"internal", "confidential"}
    assert out["allowed_backends"] == ["lark"]

def test_route_rejects_external_zone(tmp_home):
    rc, out = _run_route(["partner-x"], trust_zone="external", content="confidential material")
    assert out["allowed_backends"] == [] and rc == 3
```

- [ ] **Step 2-4: RED→实现→GREEN**

```python
def _cmd_route(args: argparse.Namespace) -> int:
    from kgent.router.sensitivity import analyze_sensitivity, enforce_zone
    router, _config = _build_router()
    tier, confidence, provenance = analyze_sensitivity(args.content, 0.9)
    names = (args.backends.split(",") if args.backends else list(router.backends))
    allowed, rejected = [], []
    for name in names:
        backend = router.backends[name]
        try:
            enforce_zone(tier, backend.trust_zone, name)
            allowed.append(name)
        except PolicyError as exc:
            rejected.append({"backend": name, "reason": str(exc)})
    payload = {"operation": "route", "dry_run": True, "sensitivity": tier,
               "provenance": provenance, "allowed_backends": allowed, "rejected": rejected}
    if getattr(args, "json", False):
        _json_out(payload)
    else:
        _text_out(f"{tier}: allowed={allowed} rejected={rejected}")
    if not allowed:
        return 3
    return 0
```

parser：`p_route = sub.add_parser("route", ...)`；`--content` required；`--backends` 可选。**Step 5: Commit** `feat: route --dry-run 只读裁决（B7/FM4）`

---

### Task 6: 三平台 trust_zone 默认 internal

**Files:**
- Modify: `src/kgent/capabilities/setup_config.py:141`（`cfg["trust_zone"] = "external"` 所在函数——按 backend 名分派）
- Test: `tests/test_setup_config.py`（追加断言；先读该文件既有用例惯例）

**Interfaces:**Produces: 检测名 `lark`/`dingtalk`/`wecom` → `internal`；其余未知后端维持 `external`（fail-safe，沿用 `_DEFAULT_TIER` 语义）

- [ ] 失败测试：setup 生成的 lark backend config `trust_zone == "internal"`（RED）
- [ ] 实现：

```python
_INTERNAL_BY_NAME = {"lark", "dingtalk", "wecom"}
cfg["trust_zone"] = "internal" if name in _INTERNAL_BY_NAME else "external"
```

（`name` 取该函数已解析的 backend 名；读 130-150 行上下文取真实变量名。）
- [ ] GREEN + 全套 + **追加用例**：用户现有 `~/.kgent/config.yaml` 迁移提示（doctor 对 lark=external 给 warning）——若 doctor 校验复杂则仅实现 setup 侧，用户侧配置由执行者跑 `kgent setup` 前提示维护者手工改（写入 commit message）
- [ ] Commit `fix: lark/dingtalk/wecom 默认 trust_zone internal（维护者裁决）`

---

### Task 7: LarkAdapter deprecation 标注

**Files:**
- Modify: `src/kgent/adapters/lark.py`（模块 docstring + `create_document`/`update_document`/`read_document`/`search_by_keywords` docstring 首行）
- Test: 无新测试（纯标注；B12 全套保障）

**Interfaces:** Produces: docstring 统一加一行 `Deprecated (skills): 平台操作经 lark-integration（ADR 0004）；CLI 面保留供调试与 kgent hosted backend 车道。`

- [ ] 逐个 docstring 加行 → `python -m pytest tests -q` 无新增失败 → `ruff check src/kgent/adapters/lark.py` → Commit `docs: LarkAdapter 标注 deprecated（ADR 0004）`

---

### Task 8: lark-integration SKILL.md 升格

**Files:**
- Modify: `skills/lark-integration/SKILL.md`

**Interfaces:** Produces: 四个新章节（原文如下，融入现有结构，标题层级对齐现有文件）

- [ ] **Step 1: 在现有 frontmatter 与「URL Construction」之间插入**

```markdown
## Search

`kgent` 的 search 对 Lark 内容一律改走本 skill（ADR 0004）。步骤：

1. 首选 `lark-cli docs +search --query "<kw>" --json`（doc + wiki 一次覆盖）；
   需要盘内文件时补 `lark-cli drive +search`。
2. 类型判定（沿用 2026-09-02 spec 规则）：每条 hit 先看 `result_meta.url`
   路径段——`/wiki/` → `wiki_node`，`/docx/` → `doc`；无 URL 时以
   `entity_type`（`WIKI`/`DOC`…）兜底；其余一律 `doc`，不从 token 推断。
3. 引用一律转原生 URL（见 URL Construction）；锚点/`?sheet=` 噪声剥去。
4. 命中数缩量（超时/失败）必须显式声明，不静默。
```

- [ ] **Step 2: 「Read Delegation Matrix」表头与引言改写**

```markdown
## Read Delegation Matrix

对 Lark 内容的一切读取经本 skill：docx（flat doc 与 wiki node）可直接
`lark-cli docs +fetch --doc <token>`（kgent read 已 deprecated for skills，
ADR 0004）；非 docx 类型按下表委派：
```

（表格保留原三行。）

- [ ] **Step 3: 「Write Delegation Matrix」引言改为**：对 Lark 内容的一切写入经本 skill 委派（docx → lark-doc `docs +create/+update`；wiki 节点 → lark-wiki/lark-doc；bitable/sheet/slides 不变）。**多行/含 CJK 内容优先 `--content @file`**。

- [ ] **Step 4: 文末新增**

```markdown
## Undo Compensation（ADR 0005）

Lark 的 undo 补偿机制是 `docs +history-revert`。流程：

1. `kgent undo <op_id> --json` 取补偿计划（`plan.mechanism == "history-revert"`；
   `status == "rejected"` 时停止——文档在写后有并发编辑，禁止回滚）。
2. `lark-cli docs +history-list --doc <token> --json` 定位
   `plan.plan.revision_before` 对应的 `history_version_id`。
3. `lark-cli docs +history-revert --doc <token> --history-version-id <id> --json`，
   轮询 `status: done`。
4. 读回校验：`lark-cli docs +fetch` 内容与 `plan.plan.snapshot`（存在时）一致。
```

- [ ] **Step 5: Commit** `docs: lark-integration 升格为 Lark 唯一接口（ADR 0004/0005）`

---

### Task 9: 三个 kgent skills 编排化 + B9 静态检查

**Files:**
- Modify: `skills/knowledge-storage/SKILL.md`、`skills/question-answering/SKILL.md`、`skills/wiki-setup/SKILL.md`
- Create: `tests/test_skill_docs_integration_routing.py`

**Interfaces:** Produces: B9 静态检查通过（对三份 SKILL.md 断言：**不存在**针对 `lark|dingtalk|wecom` 后端的 `kgent search|kgent read|kgent update|kgent create|kgent store` 直调指令；**存在**「经 <platform>-integration」字样）

- [ ] **Step 1: 先写失败测试**

```python
# tests/test_skill_docs_integration_routing.py
"""B9: 平台操作必须经 integration skill——skills 文档静态检查（ADR 0004）。"""
import re
from pathlib import Path

SKILLS = ["knowledge-storage", "question-answering", "wiki-setup"]
DIRECT = re.compile(
    r"kgent (search|read|update|create|store)[^\n]*--backends?\s+(lark|dingtalk|wecom)",
    re.IGNORECASE,
)

def test_no_direct_platform_cli_calls_in_skills():
    for name in SKILLS:
        text = (Path("skills") / name / "SKILL.md").read_text(encoding="utf-8")
        assert not DIRECT.search(text), f"{name} 仍直调平台后端"

def test_skills_route_platform_ops_via_integration_skill():
    for name in SKILLS:
        text = (Path("skills") / name / "SKILL.md").read_text(encoding="utf-8")
        assert "integration" in text, f"{name} 缺 integration 路由说明"
```

- [ ] **Step 2: RED** → **Step 3: 改三份 SKILL.md**（每份两处：① 检索/读取步骤句改为「Lark/DingTalk/WeCom 内容经 <platform>-integration 的 search/read 步骤；kgent hosted backend 用 kgent search/read（尚未实现）」② 写执行段改为「批准后：`kgent route --dry-run` → `kgent journal begin` → 经 <platform>-integration 执行写入 → `kgent journal end` → 读回校验 → 原生 URL + op_id 确认」；knowledge-storage 的示例命令块同步替换）→ **Step 4: GREEN + 全套** → **Step 5: Commit** `docs: 三 skills 编排化——平台操作经 integration skill（B9）`

---

### Task 10: evals 更新

**Files:**
- Modify: `evals/skills/knowledge-storage-evals.json`（expectations 追加三条，不改既有断言）
- Create: `evals/skills/platform-via-integration-evals.json`

**Interfaces:** Produces: eval 断言（grade_evals.py 的 DSL 兼容，字段照既有 shape：id/prompt/expected_output/files/expectations）

- [ ] knowledge-storage 每条 eval 的 `expectations` 追加：`"The skill runs 'kgent route --dry-run' before executing any write"`、`"The skill wraps the write with 'kgent journal begin' and 'kgent journal end'"`、`"For Lark targets the skill delegates execution via lark-integration, not 'kgent update'"`
- [ ] 新文件：

```json
{
  "skill_name": "knowledge-storage",
  "evals": [
    {
      "id": 1,
      "prompt": "Save this to the wiki: our onboarding now includes a first-year performance review.",
      "expected_output": "Route first, journal begin, delegate the Lark wiki write via lark-integration, journal end, verify by reading back, confirm with native URL.",
      "files": [],
      "expectations": [
        "The skill runs 'kgent route --dry-run' before executing",
        "The skill calls 'kgent journal begin' before the write",
        "The write is delegated via lark-integration (not 'kgent update')",
        "The skill calls 'kgent journal end' after the write",
        "The skill reads the document back and compares before confirming",
        "The confirmation includes a native https:// URL"
      ]
    }
  ]
}
```

- [ ] Commit `test(evals): route/journal/integration 纪律断言（B9）`

---

### Task 11: 真机验收（B3/B4）+ gauntlet + 收尾

**Files:**
- Create: `tests/e2e/test_lark_undo_real.py`（真机标记）
- Modify: `specs/2026-09-05-write-path-skill-delegation-design.md`（状态 → Phase 1 implemented 附验收记录）

**Interfaces:** Consumes: Task 3/4 的 CLI；lark-cli（已装、已 auth）

- [ ] **Step 1: 真机 undo 脚本**（pytest marker `e2e` + `real`；无凭据则 skip——lark 已有凭据应跑）

```python
# tests/e2e/test_lark_undo_real.py
"""B3/B4 真机：lark 探针文档 undo 计划 → lark-integration history-revert。"""
import json
import subprocess
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.real]


def _cli(*args: str) -> dict:
    out = subprocess.run(["lark-cli", *args, "--as", "user", "--json"],
                         capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(out.stdout)


def test_undo_plan_and_history_revert(tmp_path):
    title = "kgent-phase1-probe-临时"
    doc = _cli("docs", "+create", "--title", title, "--content", "AAA-CONTENT",
               "--doc-format", "markdown")
    token = doc["data"]["document"]["document_id"]
    try:
        begin = subprocess.run(
            ["kgent", "--json", "journal", "begin", "--operation", "update",
             "--backend", "lark", "--doc-uri", f"kgent://lark/{token}",
             "--revision-before", "1", "--snapshot-content", "AAA-CONTENT"],
            capture_output=True, text=True, encoding="utf-8", check=True)
        op_id = json.loads(begin.stdout)["entry"]["op_id"]
        _cli("docs", "+update", "--doc", token, "--command", "overwrite",
             "--content", "BBB-CONTENT", "--doc-format", "markdown")
        end = subprocess.run(
            ["kgent", "--json", "journal", "end", "--op-id", op_id,
             "--status", "ok"], capture_output=True, text=True, encoding="utf-8", check=True)
        assert json.loads(end.stdout)["entry"]["status"] == "ok"
        plan = subprocess.run(
            ["kgent", "--json", "undo", op_id],
            capture_output=True, text=True, encoding="utf-8", check=True)
        plan_json = json.loads(plan.stdout)
        assert plan_json["status"] == "ok"
        assert plan_json["plan"]["mechanism"] == "history-revert"
        history = _cli("docs", "+history-list", "--doc", token)
        versions = {e["revision_id"]: e["history_version_id"] for e in history["data"]["entries"]}
        target = versions[int(plan_json["plan"]["revision_before"])]
        _cli("docs", "+history-revert", "--doc", token, "--history-version-id", target)
        content = _cli("docs", "+fetch", "--doc", token)
        assert "AAA-CONTENT" in json.dumps(content, ensure_ascii=False)
    finally:
        subprocess.run(["lark-cli", "drive", "+delete", "--file-token", token,
                        "--type", "docx", "--yes"], capture_output=True)
```

- [ ] **Step 2: 跑真机** `python -m pytest tests/e2e/test_lark_undo_real.py -v` → PASS（revision 断言如与实际 history 结构不符，按真实 payload 修正**测试**并在 EVIDENCE 记录原因）
- [ ] **Step 3: gauntlet 全量**（`bash tools/gauntlet.sh`；无该入口则依次：`python -m pytest tests -q`（随机序）、`python -m mypy src/kgent`、`ruff check src/kgent tests`、`coverage run -m pytest tests && diff-cover coverage.xml`（变更行 100%）、`mutmut run`（新模块）或 `python tools/mutants.py` 手工 mutant——3-5 个真实 bug：翻转新鲜度比较、去掉 uuid 后缀、快照 0600→0644、end 缺 begin 不抛、plan 机制映射错位——逐一确认杀死）
- [ ] **Step 4: spec 状态 → implemented（Phase 1）+ 验收数字**；项目记忆 `kgent-update-first-block-bug` 改写为已修复（架构性绕开）+ 指向 ADR 0004
- [ ] **Step 5: Commit** `test(e2e): B3/B4 真机验收 + Phase 1 收尾` + push 前停下向维护者汇报 EVIDENCE

## Self-Review 记录

- 覆盖：B1(T1) B2(T2/T3) B3/B4(T4/T11) B5/B6(T4 计划层；真机=Phase 2/3) B7(T5) B8(T11 Step 内各 Phase) B9(T9/T10) B10(T2 strict 测试+T11 负控) B11(T8/T10；dingtalk/wecom 随 Phase) B12(每任务全套)——✓
- 占位符：T4 的 Document 构造、T9 的两处句式为**显式授权的"照抄既有文件"**（含文件名），非 TBD——✓
- 类型一致性：`begin/end/compensation_plan/INTEGRATION_SKILL_BACKENDS/MECHANISM_BY_BACKEND` 在 T2 定义、T3/T4/T9/T11 消费，签名一致——✓
