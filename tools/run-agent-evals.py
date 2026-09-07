#!/usr/bin/env python3
"""Agent evals runner（gauntlet layer E，release gate——不入 per-commit gauntlet）。

在 headless Claude（``claude -p``）里带着本仓 skills 真实执行 evals JSON 的
prompt，抓 transcript 后做**启发式**评分（后置命令/URL/流程词命中；LLM-judge
是后续项）。**注意：执行即真实写平台**——eval prompt 是真实用户请求，agent
会创建/更新真实文档。

用法：
    python tools/run-agent-evals.py                       # dry：打印将执行的计划
    python tools/run-agent-evals.py --execute             # 真跑（写真实平台！）
    python tools/run-agent-evals.py --execute --ids 1,2   # 只跑指定 id
    python tools/run-agent-evals.py --execute --skill knowledge-storage

输出：evals/transcripts/<skill>/eval-<id>.md + evals/transcripts/report.md
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EVALS = REPO / "evals" / "skills"
TRANSCRIPTS = REPO / "evals" / "transcripts"


def load_evals(skill: str | None, ids: set[int] | None) -> list[tuple[str, dict]]:
    picked: list[tuple[str, dict]] = []
    for path in sorted(EVALS.glob("*-evals.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        name = data.get("skill_name", path.stem.replace("-evals", ""))
        if skill and name != skill:
            continue
        for entry in data.get("evals", []):
            if ids and int(entry["id"]) not in ids:
                continue
            picked.append((f"{name}/{entry['id']}", entry))
    return picked


def heuristic_grade(expectations: list[str], transcript: str) -> tuple[int, list[str]]:
    """启发式评分：抽 expectation 中的反引号命令/URL 词面，命中即计。

    已知局限（诚实声明）：prose 断言的语义判别需要 LLM-judge；当前评分
    只认词面证据，假阳/假阴都可能——报告按条列出命中证据供人工复核。
    """
    passed, misses = 0, []
    for exp in expectations:
        needles = re.findall(r"`([^`]+)`", exp)
        tokens = [n for n in needles if not re.fullmatch(r"\d+", n)]
        if not tokens:
            tokens = re.findall(r"https?://\S+|lark-integration|journal begin|journal end", exp)
        hit = all(t.lower() in transcript.lower() for t in tokens) if tokens else False
        if hit:
            passed += 1
        else:
            misses.append(exp)
    return passed, misses


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skill", help="只跑某个 skill 的 evals")
    ap.add_argument("--ids", help="逗号分隔的 eval id，如 1,2")
    ap.add_argument("--execute", action="store_true", help="真跑（headless claude，写真实平台）")
    ap.add_argument("--timeout", type=int, default=900, help="单条 eval 超时秒数")
    args = ap.parse_args()

    ids = {int(x) for x in args.ids.split(",")} if args.ids else None
    picked = load_evals(args.skill, ids)
    if not picked:
        print("no evals matched")
        return 1

    if not args.execute:
        print(f"DRY — would execute {len(picked)} evals via headless claude (real platform writes!):")
        for key, entry in picked:
            print(f"  {key}: {entry['prompt'][:80]}...")
        print("re-run with --execute to actually run them")
        return 0

    if shutil_which("claude") is None:
        print("claude CLI not found on PATH")
        return 1

    TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
    report: list[str] = ["# Agent evals report\n"]
    total_pass = 0
    for key, entry in picked:
        print(f"running {key} ...", flush=True)
        result = subprocess.run(
            ["claude", "-p", entry["prompt"], "--output-format", "text"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=args.timeout,
            cwd=str(REPO),
        )
        transcript = result.stdout or result.stderr
        passed, misses = heuristic_grade(entry.get("expectations", []), transcript)
        total = len(entry.get("expectations", []))
        total_pass += passed
        tpath = TRANSCRIPTS / key.replace("/", "-")
        tpath.with_suffix(".md").write_text(
            f"# eval {key}\n\n## prompt\n\n{entry['prompt']}\n\n## transcript\n\n{transcript}\n",
            encoding="utf-8",
        )
        line = f"**{key}**: {passed}/{total} assertions hit"
        if misses:
            line += " — misses:\n" + "\n".join(f"  - {m}" for m in misses)
        report.append(line + "\n")
        print(f"  {passed}/{total}")

    (TRANSCRIPTS / "report.md").write_text("\n".join(report), encoding="utf-8")
    print(f"\ndone — {total_pass} assertion hits total; report: {TRANSCRIPTS / 'report.md'}")
    print("heuristic grading only — human review of transcripts required before signing off")
    return 0


def shutil_which(name: str) -> str | None:
    import shutil

    return shutil.which(name)


if __name__ == "__main__":
    sys.exit(main())
