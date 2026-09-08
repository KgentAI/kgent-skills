"""B3/B4 真机：lark 探针文档 undo 计划 → lark-integration history-revert。

真机验收（ADR 0004/0005 的闭环）：kgent 台账 begin/end → ``kgent undo`` 只产
补偿计划（mechanism=history-revert，integration_skill=lark-integration），
执行归 lark-integration skill——本测试扮演该 skill，按 ``history_hint`` 用
``lark-cli docs +history-list/+history-revert`` 完成补偿，并读回内容断言还原。

探针文档标题带 ``kgent-phase1-probe``；``finally`` 必删，删除失败时把
token 打出来供人工清理。真机凭据缺失（lark-cli user 身份不可用）→ skip。

与 brief 逐字稿的真机修正（详见 task-11-report EVIDENCE）：
1. ``kgent`` 经 ``sys.executable -m kgent`` 解析——PATH 上的 ``kgent`` 是一份
   旧安装（无 ``journal``/``route`` 子命令），必须打仓库源码。
2. ``--json`` 必须放在叶子子命令上（本测试放整条命令末尾）——argparse
   子解析器在独立 namespace 里解析后再覆盖父 namespace，顶层 ``--json``、
   或夹在 ``journal --json begin`` 中间的 ``--json``，都会被叶子解析器的
   默认值 ``False`` 静默覆盖（输出退回 text，``json.loads`` 直接崩）。
3. revision 取真实值——Lark 新文档首 revision 是 3（不是 1），history 索引
   按 ``revision_id`` 稀疏建点；且台账 end 必须带 ``--revision-after``，
   否则 freshness 走 FM3 快照比对，写后内容已变 → 计划 rejected。
4. ``lark-cli`` 在 Windows 上以 ``lark-cli.cmd`` 调起（同
   :class:`kgent.adapters.lark.LarkAdapter`）——裸名是 node 的无扩展名 shim，
   ``CreateProcess`` 打不开（WinError 2）；这正是 ADR 0004 的批处理包装根因。
5. history 建点**异步且稀疏**：create 后要等写前 revision 的精确建点再写
   （真机 >60s），否则 revert 落到更早的空文档点；读回断言是最终把关。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.real]

#: 仓库无 pytest marker 注册表（pyproject 无 ``markers`` 配置）：``e2e``/``real``
#: 直接打标，仅作筛选契约，靠 skipif 做真机门。

PROBE_TITLE = "kgent-phase1-probe-临时"

#: Lark history 快照点是**异步**且稀疏的：create 之后该 revision 不一定已有
#: 建点（真机实测 >10s），有界轮询精确命中；轮询耗尽则回退到
#: ``revision_id <= revision_before`` 的最新建点（内容是否真还原由读回断言
#: 把关——回退点早于写入内容时测试按失败处理）。
_HISTORY_POLL_ROUNDS = 12
_HISTORY_POLL_INTERVAL_SECONDS = 5

#: teardown 删除失败的探针 token（供 session 末重试 + 人工清理提示）。
_leftover_tokens: list[str] = []


def _kgent() -> list[str]:
    """仓库源码的 kgent 调用形态（见模块 docstring 修正 1）。"""
    override = os.environ.get("KGENT_BIN")
    if override:
        return [override]
    return [sys.executable, "-m", "kgent"]


def _lark_cmd() -> list[str]:
    """lark-cli 的可执行形态：Windows 上原生 subprocess 只认 ``lark-cli.cmd``。

    与 :class:`kgent.adapters.lark.LarkAdapter` 同一解析——裸 ``lark-cli`` 在
    Windows 上是 node 的无扩展名 shim，``CreateProcess`` 打不开（WinError 2），
    正是 ADR 0004 的批处理包装根因。
    """
    override = os.environ.get("LARK_CLI_BIN")
    if override:
        return [override]
    if sys.platform == "win32" and shutil.which("lark-cli.cmd"):
        return ["lark-cli.cmd"]
    return ["lark-cli"]


def _lark_user_available() -> bool:
    """lark-cli 已装且 user 身份可用（本地 token 检查，无网络副作用）。"""
    try:
        out = subprocess.run(
            [*_lark_cmd(), "auth", "status", "--json"],
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
    user = (payload.get("identities") or {}).get("user") or {}
    return bool(user.get("available"))


pytestmark.append(
    pytest.mark.skipif(
        not _lark_user_available(),
        reason="real-machine probe: lark-cli user identity unavailable",
    )
)


def _cli(*args: str) -> dict:
    out = subprocess.run(
        [*_lark_cmd(), *args, "--as", "user", "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=120,
    )
    return json.loads(out.stdout)


def _kgent_json(command: str, *rest: str) -> dict:
    """``--json`` 放在整条子命令路径的**末尾**（见模块 docstring 修正 2）。

    ``journal begin`` 是两级子解析器：``--json`` 夹在中间会落到上一层
    ``journal`` 解析器，叶子 ``begin`` 在独立 namespace 里重新取默认值
    ``False`` 并覆盖回来——只有紧跟叶子子命令（或干脆放最后）才生效。
    """
    out = subprocess.run(
        [*_kgent(), command, *rest, "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=120,
    )
    return json.loads(out.stdout)


def _delete_probe(token: str) -> bool:
    out = subprocess.run(
        [*_lark_cmd(), "drive", "+delete", "--file-token", token, "--type", "docx", "--yes"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,  # teardown：失败由调用方点名 token，不抛
    )
    return out.returncode == 0


def test_undo_plan_and_history_revert():
    doc = _cli(
        "docs",
        "+create",
        "--title",
        PROBE_TITLE,
        "--content",
        "AAA-CONTENT",
        "--doc-format",
        "markdown",
    )
    created = doc["data"]["document"]
    token = created["document_id"]
    revision_before = int(created["revision_id"])
    try:
        # Lark history 快照点异步建（真机 >60s 才出现）：先等写前 revision 的
        # 精确建点，否则 revert 只能回到更早的空文档点（真机实测 →
        # ``<title></title>``）。integration 侧同样依赖这个前置。
        _wait_history_point(token, revision_before)
        begin = _kgent_json(
            "journal",
            "begin",
            "--operation",
            "update",
            "--backend",
            "lark",
            "--doc-uri",
            f"kgent://lark/{token}",
            "--revision-before",
            str(revision_before),
            "--snapshot-content",
            "AAA-CONTENT",
        )
        op_id = begin["entry"]["op_id"]
        updated = _cli(
            "docs",
            "+update",
            "--doc",
            token,
            "--command",
            "overwrite",
            "--content",
            "BBB-CONTENT",
            "--doc-format",
            "markdown",
        )
        revision_after = int(updated["data"]["document"]["revision_id"])
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

        plan_json = _kgent_json("undo", op_id)
        assert plan_json["status"] == "ok"
        assert plan_json["mode"] == "plan"
        assert plan_json["integration_skill"] == "lark-integration"
        assert plan_json["plan"]["mechanism"] == "history-revert"
        assert int(plan_json["plan"]["revision_before"]) == revision_before

        target = _history_target(token, revision_before)
        reverted = _cli(
            "docs",
            "+history-revert",
            "--doc",
            token,
            "--history-version-id",
            target,
        )
        assert reverted["data"]["status"] == "done"
        content = _poll_content(token, "AAA-CONTENT")
        assert "AAA-CONTENT" in json.dumps(content, ensure_ascii=False)
        # B3 evidence: revision 读数（create → update → revert 后）供验收记录。
        print(
            "[kgent-phase1-probe] revision_before="
            f"{revision_before} revision_after={revision_after} "
            f"history_version_id={target} final={content['data']['document']['revision_id']}"
        )
    finally:
        if not _delete_probe(token):
            _leftover_tokens.append(token)
            print(
                f"TEARDOWN FAILED: probe token {token} still exists — delete manually: "
                f"lark-cli drive +delete --file-token {token} --type docx --yes"
            )


def _history_entries(token: str) -> list[tuple[int, str]]:
    """``+history-list`` → ``(revision_id, history_version_id)`` 升序表。"""
    history = _cli("docs", "+history-list", "--doc", token)
    entries = [
        (int(e["revision_id"]), str(e["history_version_id"])) for e in history["data"]["entries"]
    ]
    return sorted(entries)


def _wait_history_point(token: str, revision: int) -> str:
    """写前 revision 的精确 history 建点（有界等待，超时按失败处理）。

    Lark 的建点是稀疏快照（真机：revision 1/3/5 → 1024/2048/3072）且**异步**
    出现；没有它，update 后的 revert 只能落到更早的点。
    """
    last: list[tuple[int, str]] = []
    for _ in range(_HISTORY_POLL_ROUNDS):
        last = _history_entries(token)
        for rev, version in last:
            if rev == revision:
                return version
        time.sleep(_HISTORY_POLL_INTERVAL_SECONDS)
    raise AssertionError(
        f"lark history never checkpointed revision {revision} within "
        f"{_HISTORY_POLL_ROUNDS * _HISTORY_POLL_INTERVAL_SECONDS}s; saw {last}"
    )


def _history_target(token: str, revision_before: int) -> str:
    """写前快照的 ``history_version_id``（``history_hint`` 的 integration 侧实现）。

    精确命中优先；万一写前建点又被平台回收，退到 ``<= revision_before`` 的
    最新点——是否真还原由读回断言把关。
    """
    for rev, version in reversed(_history_entries(token)):
        if rev <= revision_before:
            return version
    raise AssertionError(f"lark history has no snapshot at or before revision {revision_before}")


def _poll_content(token: str, needle: str) -> dict:
    """revert 是异步任务：轮询读回内容直到包含补偿前内容（或轮询耗尽）。"""
    last: dict = {}
    for _ in range(6):
        last = _cli("docs", "+fetch", "--doc", token)
        if needle in json.dumps(last, ensure_ascii=False):
            return last
        time.sleep(2)
    return last


@pytest.fixture(scope="session", autouse=True)
def _retry_leftovers():
    """session 末对 teardown 失败的探针 token 再删一次，仍失败则点名。"""
    yield
    for token in list(_leftover_tokens):
        if _delete_probe(token):
            _leftover_tokens.remove(token)
            print(f"probe token {token} deleted on retry")
    for token in _leftover_tokens:
        print(
            f"LEFTOVER PROBE DOC: {token} — delete manually: "
            f"lark-cli drive +delete --file-token {token} --type docx --yes"
        )
