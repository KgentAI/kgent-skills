"""dn_brief_check — structural assert for decision-navigator 决策简报 (B5/B6/B7).

Spec: specs/2026-09-11-decision-navigator-design.md
Grammar (must stay in lockstep with skills/decision-navigator/SKILL.md):

    node line : "- " ID " [" STATE "]" free-text? (依[:：] dep (sep dep)*)?
    ID        : "N" digits
    STATE     : 用户已给 | 引用来源 | 假设 | 依前未解
    引用来源  : "[引用来源|" https-url "]"   (native URLs only — kgent:// banned)
    mermaid   : one fenced block, first line `flowchart TD`, bare N1 --> N2 edges

Exit codes: 0 clean, 1 violations, 2 usage/IO/internal (fail closed).
"""

from __future__ import annotations

import argparse
import re
import sys

STATES = ("用户已给", "引用来源", "假设", "依前未解")
CITED = "引用来源"
DEFAULT_MAX_PASSES = 3

NODE_LINE_RE = re.compile(r"^-\s+(N\d+)\s+\[([^\]]*)\]\s*(.*)$")
DEP_TAIL_RE = re.compile(r"依[:：]\s*(.+)\s*$")
DEP_ID_RE = re.compile(r"N\d+")
URL_RE = re.compile(r"^https?://\S+$")

MERMAID_FENCE_RE = re.compile(r"```mermaid[ \t]*\r?\n(.*?)```", re.S)
FLOWCHART_RE = re.compile(r"^flowchart TD$")
NODE_DEF_RE = re.compile(r"^N\d+(?:\[\"[^\"]*\"\])?$")
EDGE_RE = re.compile(r"^(N\d+)-->(N\d+)$")
CONVERGED_RE = re.compile(r"第\s*(\d+)\s*轮收敛")
EXTENDED_RE = re.compile(r"延长\s*(\d+)\s*轮")


def _violations_node_list(text: str) -> tuple[list[str], dict[str, list[str]], set[str]]:
    """Parse node lines → (violations, deps per id, all ids)."""
    problems: list[str] = []
    deps: dict[str, list[str]] = {}
    ids: set[str] = set()
    for lineno, raw in enumerate(text.splitlines(), 1):
        match = NODE_LINE_RE.match(raw.strip())
        if not match:
            continue
        nid, bracket, rest = match.groups()
        if nid in ids:
            problems.append(f"L{lineno}: 节点 {nid} 重复定义")
            continue
        ids.add(nid)
        state, sep, url = bracket.partition("|")
        if state not in STATES:
            problems.append(f"L{lineno}: 节点 {nid} 未知状态「{bracket}」")
        elif state == CITED:
            if not sep or not URL_RE.match(url):
                problems.append(f"L{lineno}: 节点 {nid} 引用来源缺原生 URL（[引用来源|https://…]）")
        elif sep:
            problems.append(f"L{lineno}: 节点 {nid} 非 {CITED} 状态的括号不得带「|…」")
        tail = DEP_TAIL_RE.search(rest)
        dep_ids = DEP_ID_RE.findall(tail.group(1)) if tail else []
        deps[nid] = dep_ids
    if not ids:
        problems.append("节点表为空：未找到任何 `- N<k> [状态] …` 行")
    for nid, dep_ids in deps.items():
        for dep in dep_ids:
            if dep not in ids:
                problems.append(f"节点 {nid} 依:{dep} 引用未定义节点")
    return problems, deps, ids


def _violations_mermaid(text: str) -> tuple[list[str], set[str], set[str]]:
    """Parse the (exactly one) mermaid block → (violations, edge set, node ids)."""
    problems: list[str] = []
    blocks = MERMAID_FENCE_RE.findall(text)
    if len(blocks) != 1:
        return [f"mermaid 块数量必须恰一，实得 {len(blocks)}"], set(), set()
    edges: set[tuple[str, str]] = set()
    nodes: set[str] = set()
    seen_header = False
    for lineno, raw in enumerate(blocks[0].splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("%%"):
            continue
        if not seen_header:
            if not FLOWCHART_RE.match(line):
                return [f"mermaid 首行必须是裸「flowchart TD」，实得「{line}」"], set(), set()
            seen_header = True
            continue
        compact = re.sub(r"\s+", "", line)
        edge = EDGE_RE.match(compact)
        if edge:
            edges.add((edge.group(1), edge.group(2)))
            nodes.update(edge.groups())
            continue
        if NODE_DEF_RE.match(compact):
            nodes.add(re.match(r"^N\d+", compact).group(0))
            continue
        problems.append(f"mermaid L{lineno}: 非裸方言的行「{line}」（只准 N1[\"标签\"] 与 N1 --> N2）")
    if not seen_header:
        problems.append("mermaid 块为空：缺 flowchart TD 头")
    return problems, edges, nodes


def _has_cycle(edges: set[tuple[str, str]]) -> str | None:
    """Return a cycle path string if the edge set is not a DAG."""
    out: dict[str, list[str]] = {}
    for src, dst in edges:
        out.setdefault(src, []).append(dst)
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> str | None:
        state[node] = 1
        stack.append(node)
        for nxt in out.get(node, []):
            if state.get(nxt, 0) == 1:
                return " -> ".join([*stack[stack.index(nxt):], nxt])
            if state.get(nxt, 0) == 0 and (found := visit(nxt)):
                return found
        state[node] = 2
        stack.pop()
        return None

    for start in sorted(out):
        if state.get(start, 0) == 0 and (found := visit(start)):
            return found
    return None


def _violations_convergence(text: str, max_passes: int) -> list[str]:
    problems: list[str] = []
    has_dalimited = "达限" in text
    has_extension = "延长" in text
    has_assumption_fallback = "余下按假设" in text or "按假设处理" in text
    converged = [int(m.group(1)) for m in CONVERGED_RE.finditer(text)]
    if converged:
        cap = max_passes
        if has_dalimited and has_extension:
            ext = EXTENDED_RE.search(text)
            cap = max_passes + (int(ext.group(1)) if ext else max_passes)
        over = [n for n in converged if n > cap]
        if over:
            problems.append(
                f"收敛轮次 {over} 超上限（硬上限 {max_passes}，"
                f"批准延长后 {cap}）：须记录达限 + 用户批准延长"
            )
    elif has_dalimited and (has_extension or has_assumption_fallback):
        pass  # 达限 + 延长/按假设：合法的未收敛出口
    else:
        problems.append("缺收敛申报：「第N轮收敛」或「达限 +（延长|余下按假设）」")
    return problems


def check(text: str, max_passes: int = DEFAULT_MAX_PASSES) -> list[str]:
    """Return all violations of the B5/B6/B7 structural contract."""
    problems: list[str] = []
    if "kgent://" in text:
        problems.append("简报出现 kgent:// ——引用只准原生平台 URL（B5/N20）")
    list_problems, deps, list_ids = _violations_node_list(text)
    problems += list_problems
    mermaid_problems, edges, mermaid_ids = _violations_mermaid(text)
    problems += mermaid_problems

    # Mermaid edge `N1 --> N2` and node-list `N2 … 依:N1` both mean "N2 depends
    # on N1" (dependency feeds dependent), so the list tuple is (dep, src).
    list_edges = {(dep, src) for src, dep_ids in deps.items() for dep in dep_ids}
    mermaid_only = edges - list_edges
    list_only = list_edges - edges
    for src, dst in sorted(mermaid_only):
        problems.append(f"mermaid 有边 {src}-->{dst} 而节点表缺对应 依（图表分叉）")
    for src, dst in sorted(list_only):
        problems.append(f"节点表有 依:{dst}（{src}）而 mermaid 缺边（图表分叉）")
    for nid in sorted(mermaid_ids - list_ids):
        problems.append(f"mermaid 节点 {nid} 不在节点表（覆盖缺口）")
    for nid in sorted(list_ids - mermaid_ids):
        problems.append(f"节点表节点 {nid} 不在 mermaid 图中（覆盖缺口）")

    if cycle := _has_cycle(edges):
        problems.append(f"子问题图存在环：{cycle}（必须是 DAG）")
    problems += _violations_convergence(text, max_passes)
    return problems


def main(argv: list[str] | None = None) -> int:
    # Violation text is Chinese; Windows pipes default to cp1252/charmap and
    # crash on print (the .cmd-wrapper UTF-8 lesson, spec 2026-09-05 §根因).
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="dn_brief_check",
        description="decision-navigator 决策简报结构断言（B5/B6/B7）",
    )
    parser.add_argument("brief", help="简报 markdown 文件路径")
    parser.add_argument(
        "--max-passes", type=int, default=DEFAULT_MAX_PASSES,
        help=f"检索循环硬上限（默认 {DEFAULT_MAX_PASSES}）",
    )
    args = parser.parse_args(argv)
    try:
        with open(args.brief, encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        print(f"dn_brief_check: 无法读取 {args.brief}: {exc}", file=sys.stderr)
        return 2
    try:
        problems = check(text, args.max_passes)
    except Exception as exc:  # noqa: BLE001 — fail closed on any internal error
        print(f"dn_brief_check: 内部错误（fail closed）: {exc!r}", file=sys.stderr)
        return 2
    for problem in problems:
        print(f"VIOLATION: {problem}")
    print(f"dn_brief_check: {len(problems)} violation(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
