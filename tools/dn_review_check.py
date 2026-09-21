"""dn_review_check — structural assert for decision-navigator 评审结论 (R1/R3/R4/R5/R6).

Spec: specs/2026-09-20-decision-navigator-review-gate-design.md
ADR: docs/adr/0014-decision-navigator-review-gate.md
Grammar (must stay in lockstep with skills/decision-navigator/SKILL.md):

    header       : 【评审门 · 执行方式：(派发评审|内联复查|评审未执行)】
    sections     : ## 事实接地 then ## 逻辑审查 — exact order, each exactly once
    citations    : "- 已解析引用 n/m"（n ≤ m，恰一行）— 新增引用必须逐条申报解析
    finding      : "- [" (致命|可修|轻微) "]" free-text
                   事实接地 findings 另需 "[实证复核|一致性核对]"；逻辑审查 findings 不得带
    spot cap     : 实证复核 per verdict ≤ --max-spot-checks (default 3)
    评审未执行   : header + 恰一行 "- 未执行原因：…；影响：…"；两节必须缺席，
                   其余 "- " 行一律违规（申报形态不得夹带伪装的复核内容）

Exit codes: 0 clean, 1 violations, 2 usage/IO/internal (fail closed).
"""

from __future__ import annotations

import argparse
import re
import sys

MODES = ("派发评审", "内联复查", "评审未执行")
SEVERITIES = ("致命", "可修", "轻微")
METHODS = ("实证复核", "一致性核对")
SPOT = "实证复核"
DEFAULT_MAX_SPOT_CHECKS = 3

GROUND_HEADING = "## 事实接地"
LOGIC_HEADING = "## 逻辑审查"

HEADER_RE = re.compile(r"^【评审门 · 执行方式：([^】]*)】$")
CITE_RE = re.compile(r"^已解析引用\s*(\d+)\s*/\s*(\d+)\s*(（[^）]*）)?$")
FINDING_RE = re.compile(r"^-\s*\[([^\]]+)\](?:\[([^\]]+)\])?\s*(.*)$")
UNEXEC_RE = re.compile(r"^未执行原因：\S.*；影响：\S.*$")


def _section_bodies(lines: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Split lines → (before-ground, ground body, logic body); heading counts reported via len."""
    ground_idx = [i for i, ln in enumerate(lines) if ln.strip() == GROUND_HEADING]
    logic_idx = [i for i, ln in enumerate(lines) if ln.strip() == LOGIC_HEADING]
    ground_body: list[str] = []
    logic_body: list[str] = []
    if len(ground_idx) == 1 and len(logic_idx) == 1:
        g_idx, l_idx = ground_idx[0], logic_idx[0]
        if g_idx < l_idx:
            ground_body = lines[g_idx + 1 : l_idx]
            logic_body = lines[l_idx + 1 :]
        else:
            logic_body = lines[l_idx + 1 : g_idx]
            ground_body = lines[g_idx + 1 :]
    elif len(ground_idx) == 1:
        ground_body = lines[ground_idx[0] + 1 :]
    elif len(logic_idx) == 1:
        logic_body = lines[logic_idx[0] + 1 :]
    return lines, ground_body, logic_body


def _check_ground_body(body: list[str], problems: list[str]) -> int:
    """事实接地 节体：恰一行引用解析申报 + 发现形/散文行；返回 实证复核 计数。"""
    spot = 0
    cite_seen = 0
    found_any = False
    for raw in body:
        line = raw.strip()
        if not line or line.startswith("（"):
            continue
        if line.startswith("- "):
            found_any = True
            if CITE_RE.match(line[2:].strip()):
                cite_seen += 1
                match = CITE_RE.match(line[2:].strip())
                resolved, total = int(match.group(1)), int(match.group(2))
                if resolved > total:
                    problems.append(f"已解析引用 {resolved}/{total}：解析数不得大于引用总数")
                continue
            match = FINDING_RE.match(line)
            if not match:
                problems.append(
                    f"事实接地节残缺行「{line}」（只准引用解析申报或 [严重级][核对方式] 发现）"
                )
                continue
            severity, method = match.group(1), match.group(2)
            if severity not in SEVERITIES:
                problems.append(f"严重级「{severity}」不在枚举（致命/可修/轻微）")
            if method is None:
                problems.append(f"事实接地发现缺核对方式「{line}」（[实证复核] 或 [一致性核对]）")
            elif method not in METHODS:
                problems.append(f"核对方式「{method}」不在枚举（实证复核/一致性核对）")
            if method == SPOT:
                spot += 1
    if not found_any or cite_seen == 0:
        problems.append("事实接地节缺「- 已解析引用 n/m」行：新增引用必须逐条申报解析（恰一行）")
    elif cite_seen > 1:
        problems.append(f"已解析引用申报出现 {cite_seen} 次（须恰一行）")
    return spot


def _check_logic_body(body: list[str], problems: list[str]) -> None:
    """逻辑审查 节体：发现形（无核对方式）或散文行，节体不得为空。"""
    found_any = False
    for raw in body:
        line = raw.strip()
        if not line:
            continue
        found_any = True
        if not line.startswith("- "):
            continue
        match = FINDING_RE.match(line)
        if not match:
            problems.append(f"逻辑审查节残缺行「{line}」（只准 [严重级] 发现）")
            continue
        severity, method = match.group(1), match.group(2)
        if severity not in SEVERITIES:
            problems.append(f"严重级「{severity}」不在枚举（致命/可修/轻微）")
        if method is not None:
            problems.append(f"逻辑审查发现不得带核对方式「{line}」（核对方式只属事实接地条目）")
    if not found_any:
        problems.append("逻辑审查节为空：至少一行发现或「（无缺陷：未发现逻辑缺陷。）」")


def check(text: str, max_spot_checks: int = DEFAULT_MAX_SPOT_CHECKS) -> list[str]:
    """Return all violations of the review-verdict structural contract (R1/R3/R4/R5/R6)."""
    problems: list[str] = []
    lines = text.splitlines()

    headers = [
        (i, HEADER_RE.match(ln.strip()))
        for i, ln in enumerate(lines)
        if HEADER_RE.match(ln.strip())
    ]
    if not headers:
        problems.append("缺评审门头（【评审门 · 执行方式：派发评审|内联复查|评审未执行】）")
    elif len(headers) > 1:
        problems.append(f"评审门头出现 {len(headers)} 次（一次 gate 恰一份结论）")
    mode: str | None = None
    header_idx = -1
    if len(headers) == 1:
        header_idx, match = headers[0]
        mode = match.group(1)
        if mode not in MODES:
            problems.append(f"执行方式「{mode}」不在枚举（派发评审/内联复查/评审未执行）")
            mode = None

    _, ground_body, logic_body = _section_bodies(lines)
    ground_n = sum(1 for ln in lines if ln.strip() == GROUND_HEADING)
    logic_n = sum(1 for ln in lines if ln.strip() == LOGIC_HEADING)

    if mode == "评审未执行":
        # 申报形态：两节必须缺席；恰一行 未执行原因 申报；其余 "- " 行一律违规
        if ground_n or logic_n:
            problems.append("执行方式=评审未执行 不得携带 事实接地/逻辑审查 节（单行申报替代两节）")
        declarations = 0
        for raw in lines:
            line = raw.strip()
            if line.startswith("- "):
                if UNEXEC_RE.match(line[2:].strip()):
                    declarations += 1
                else:
                    problems.append(f"评审未执行形态夹带非申报行「{line}」")
        if declarations != 1:
            problems.append(
                "评审未执行须恰一行「- 未执行原因：…；影响：…」申报（诚实申报优先于假装通过）"
            )
        return problems

    # 常规形态（派发评审 / 内联复查 / 或头缺失时的兜底检查）
    if ground_n == 0:
        problems.append(f"缺 {GROUND_HEADING} 节")
    elif ground_n > 1:
        problems.append(f"{GROUND_HEADING} 节出现 {ground_n} 次（须恰一）")
    if logic_n == 0:
        problems.append(f"缺 {LOGIC_HEADING} 节")
    elif logic_n > 1:
        problems.append(f"{LOGIC_HEADING} 节出现 {logic_n} 次（须恰一）")
    if ground_n == 1 and logic_n == 1:
        g_idx = next(i for i, ln in enumerate(lines) if ln.strip() == GROUND_HEADING)
        l_idx = next(i for i, ln in enumerate(lines) if ln.strip() == LOGIC_HEADING)
        if g_idx > l_idx:
            problems.append("节序错误：事实接地 必须在 逻辑审查 之前")
        if header_idx != -1 and header_idx > g_idx:
            problems.append("评审门头必须位于两节之前")
    spot = _check_ground_body(ground_body, problems)
    if spot > max_spot_checks:
        problems.append(
            f"实证复核 {spot} 条超上限 {max_spot_checks}（每 gate 抽样上限，--max-spot-checks 可调）"
        )
    _check_logic_body(logic_body, problems)
    return problems


def main(argv: list[str] | None = None) -> int:
    # Violation text is Chinese; Windows pipes default to cp1252/charmap and
    # crash on print (the .cmd-wrapper UTF-8 lesson, spec 2026-09-05 §根因).
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="dn_review_check",
        description="decision-navigator 评审结论结构断言（R1/R3/R4/R5/R6；ADR 0014）",
    )
    parser.add_argument("verdict", help="评审结论文本文件路径")
    parser.add_argument(
        "--max-spot-checks",
        type=int,
        default=DEFAULT_MAX_SPOT_CHECKS,
        help=f"每份结论 实证复核 抽样上限（默认 {DEFAULT_MAX_SPOT_CHECKS}）",
    )
    args = parser.parse_args(argv)
    try:
        with open(args.verdict, encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        print(f"dn_review_check: 无法读取 {args.verdict}: {exc}", file=sys.stderr)
        return 2
    try:
        problems = check(text, args.max_spot_checks)
    except Exception as exc:  # noqa: BLE001 — fail closed on any internal error
        print(f"dn_review_check: 内部错误（fail closed）: {exc!r}", file=sys.stderr)
        return 2
    for problem in problems:
        print(f"VIOLATION: {problem}")
    print(f"dn_review_check: {len(problems)} violation(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
