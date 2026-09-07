"""全流一致性（gauntlet layer C）：按文档化流程在真实平台走一遍完整生命周期。

Test A 的固化版（2026-09-06 skill-e2e）：route → journal begin（占位 URI +
快照）→ lark-integration 委派写入（**stdin 与 @file 两条内容通道都测**）→
journal end --doc-uri 回填 → 读回比对 → undo 补偿计划（target=真实 URI、
新鲜度 ok）→ create 补偿（删除）→ audit 台账可见回填。

与既有 test_lark_undo_real.py 的分工：那一条深测 undo/history 段；本条深测
**编排全链 + 两条写入通道 + audit 读视图**。跑在 **PATH 安装件**上（与
artifact-smoke 互补：这里是行为，那里是表面）。

真机凭据缺失 / 安装件缺席 → skip。``lark-cli`` 在 Windows 用 ``.cmd`` 解析
（shutil.which 尊重 PATHEXT）；内容走 stdin 管道与 @file 相对路径——都不过
argv，绕开 cmd 包装层的转码问题（ADR 0004 根因通道）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.real]

PROBE_TITLE = "kgent-phase1-flow-conformance-探针"
PROBE_CONTENT = (
    "# Phase 1 全流一致性探针\n\n"
    "第一段中文内容。\n\n"
    "第二段含 emoji ❤️ 与「中文标点」。\n"
)


def _which(name: str) -> str | None:
    resolved = shutil.which(name)
    if resolved is None and Path.home().joinpath(".local/bin", name).exists():
        resolved = str(Path.home() / ".local/bin" / name)
    return resolved


KGENT = _which("kgent")
LARK = _which("lark-cli") or shutil.which("lark-cli.cmd")

pytestmark += [
    pytest.mark.skipif(KGENT is None, reason="无安装件 kgent"),
    pytest.mark.skipif(LARK is None, reason="无 lark-cli"),
]


def _run(cmd: list[str], *, stdin: str | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        shell=False,
        check=False,
        cwd=str(cwd) if cwd else None,
    )


def _kgent_json(*args: str) -> tuple[int, dict]:
    result = _run([KGENT, *args, "--json"])
    assert result.returncode == 0, f"kgent {args} failed: {result.stdout}{result.stderr}"
    return result.returncode, json.loads(result.stdout)


def _lark_json(*args: str, stdin: str | None = None, cwd: Path | None = None) -> dict:
    result = _run([LARK, *args, "--as", "user", "--json"], stdin=stdin, cwd=cwd)
    assert result.returncode == 0, f"lark-cli {args} failed: {result.stdout}{result.stderr}"
    payload = json.loads(result.stdout)
    assert payload.get("ok") is True, payload
    return payload


def _lark_content(doc: str) -> tuple[str, int]:
    payload = _lark_json("docs", "+fetch", "--doc", doc)
    document = payload["data"]["document"]
    return document["content"], int(document["revision_id"])


def test_documented_flow_end_to_end(tmp_path: Path) -> None:
    # 1. route（只读裁决）
    code, routed = _kgent_json("route", "--dry-run", "--content", PROBE_CONTENT, "--backends", "lark")
    assert code == 0 and routed["allowed_backends"] == ["lark"]

    # 2. journal begin：create 用占位 URI + 内容快照（C1 流程）
    code, begun = _kgent_json(
        "journal", "begin", "--operation", "create", "--backend", "lark",
        "--doc-uri", "kgent://lark/planned-flow-conformance",
        "--snapshot-content", PROBE_CONTENT,
    )
    op_id = begun["entry"]["op_id"]

    # 3a. 写入通道一：stdin 管道（多行 UTF-8）
    created = _lark_json(
        "docs", "+create", "--title", PROBE_TITLE, "--content", "-",
        "--doc-format", "markdown", stdin=PROBE_CONTENT,
    )
    doc = created["data"]["document"]["document_id"]
    real_uri = f"kgent://lark/{doc}"
    try:
        # 3b. 写入通道二：@file 相对路径（在 lark-cli 的 cwd 内）
        content_file = tmp_path / "probe-update.md"
        content_file.write_text(
            "# Phase 1 全流一致性探针\n\n第一段中文内容。\n\n"
            "第二段含 emoji ❤️ 与「中文标点」。\n\n追加的第三段（@file 通道写入）。\n",
            encoding="utf-8",
        )
        _lark_json(
            "docs", "+update", "--doc", doc, "--command", "overwrite",
            "--content", "@probe-update.md", "--doc-format", "markdown",
            cwd=tmp_path,
        )
        _, revision_after = _lark_content(doc)

        # 4. journal end：C1 回填真实 URI + 写后 revision
        code, ended = _kgent_json(
            "journal", "end", "--op-id", op_id, "--status", "ok",
            "--revision-after", str(revision_after), "--doc-uri", real_uri,
        )
        assert ended["entry"]["doc_uri"] == real_uri

        # 5. 读回比对：两通道内容拼合后全量在场
        content, _ = _lark_content(doc)
        for fragment in ("第一段中文内容", "❤️", "追加的第三段（@file 通道写入）"):
            assert fragment in content, f"读回缺段：{fragment}"

        # 6. undo 补偿计划：target=回填的真实 URI（C1 优先级）、新鲜度 ok
        code, plan = _kgent_json("undo", op_id)
        assert plan["status"] == "ok"
        assert plan["integration_skill"] == "lark-integration"
        assert plan["plan"]["target"] == real_uri
        assert int(plan["plan"]["revision_current"]) == revision_after
    finally:
        # 7. create 补偿（删除），失败则把 token 打出来供人工清理
        removed = _run(
            [LARK, "drive", "+delete", "--file-token", doc, "--type", "docx", "--yes", "--json"]
        )
        if removed.returncode != 0:
            print(f"TEARDOWN FAILED — probe doc token: {doc}")

    # 8. audit 台账读视图：op 可见、target 已回填、状态 ok
    code, audit = _kgent_json("audit")
    by_op = {r["op_id"]: r for r in audit.get("ledger", [])}
    assert by_op[op_id]["status"] == "ok"
    assert by_op[op_id]["target"] == real_uri
