#!/usr/bin/env python3
"""Agent evals runner（gauntlet layer E，release gate——不入 per-commit gauntlet）。

在 headless Claude（``claude -p``）里带着本仓 skills 真实执行 evals JSON 的
prompt，抓 transcript 后做**启发式**评分（后置命令/URL/流程词命中；LLM-judge
是后续项）。**注意：执行即真实写平台**——eval prompt 是真实用户请求，agent
会创建/更新真实文档。

skill 流是两阶段的：proposal → **用户批准** → 执行（SKILL.md 硬性要求写前
批准）。headless 没有真人，runner 默认扮演批准者：proposal 之后自动发最多
两轮批准回复（``--no-followup`` 关闭）。

用法：
    python tools/run-agent-evals.py                       # dry：打印将执行的计划
    python tools/run-agent-evals.py --execute             # 真跑（写真实平台！）
    python tools/run-agent-evals.py --execute --ids 1,2   # 只跑指定 id
    python tools/run-agent-evals.py --execute --limit 5   # 分块（配合 resume 续跑）

输出：evals/transcripts/<skill>-<id>.md + evals/transcripts/report.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EVALS = REPO / "evals" / "skills"
TRANSCRIPTS = REPO / "evals" / "transcripts"

# Windows 控制台常为 cp1252——中文 dry 输出直接炸（2026-09-07 实测）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

APPROVALS = ("Approved — proceed.", "Yes — proceed with your default choice.")


def load_evals(skill: str | None, ids: set[int] | None, file_stem: str | None = None) -> list[tuple[str, dict]]:
    picked: list[tuple[str, dict]] = []
    for path in sorted(EVALS.glob("*-evals.json")):
        if file_stem and path.stem != file_stem:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        name = data.get("skill_name", path.stem.replace("-evals", ""))
        if skill and name != skill:
            continue
        for entry in data.get("evals", []):
            if ids and int(entry["id"]) not in ids:
                continue
            key = f"{path.stem.replace('-evals', '')}-{entry['id']}"  # 文件级唯一——skill_name 会撞车（2026-09-07 实测）
            picked.append((key, entry))
    return picked


def eval_file_stems() -> list[str]:
    """所有 eval 文件的 stem——并行编排的分区单位（每文件一个 worker 组）。"""
    return sorted(p.stem for p in EVALS.glob("*-evals.json"))


def heuristic_grade(expectations: list[str], transcript: str) -> tuple[int, list[str]]:
    """启发式评分：抽 expectation 中的反引号命令/URL 词面，命中即计。

    已知局限（诚实声明）：prose 断言的语义判别需要 LLM-judge；当前评分
    只认词面证据，假阳/假阴都可能——报告按条列出未命中项供人工复核。
    """
    passed, misses, manual = 0, [], 0
    lower = transcript.lower()
    for exp in expectations:
        needles = [n for n in re.findall(r"`([^`]+)`", exp) if not re.fullmatch(r"\d+", n)]
        if not needles:
            needles = re.findall(r"https?://\S+|lark-integration|journal begin|journal end", exp)
        if not needles:
            manual += 1  # 无词面证据可查的 prose 断言——0 分是评分盲区，交人工复核
            continue
        if all(n.lower() in lower for n in needles):
            passed += 1
        else:
            misses.append(exp)
    return passed, misses, manual


def run_parallel(args: argparse.Namespace) -> int:
    """按 eval 文件分组并行派 worker（每文件一组，写域天然不相交的概率最高）。

    并发安全前提（2026-09-07 实测确立）：
    - ``~/.kgent/journal/journal.ndjson`` 是逐 worker 追加的共享文件——不同
      worker 组应避免同时写同一 target；只读组（QA）与创建组（wiki-setup）
      可安全并行。
    - 报告按 pid 分文件（``report-<pid>.md``），跑完由本函数合并。
    - 子 worker 带 resume：transcript 已存在即跳过，重复派发幂等。
    """
    stems = eval_file_stems()
    if args.file:
        stems = [s for s in stems if s == args.file]
    children: list[tuple[str, subprocess.Popen[bytes]]] = []
    for stem in stems:
        log = (TRANSCRIPTS / f"worker-{stem}.log").open("w", encoding="utf-8")
        argv = [sys.executable, __file__, "--execute", "--file", stem,
                "--timeout", str(args.timeout)]
        if not args.followup:
            argv.append("--no-followup")
        children.append((stem, subprocess.Popen(argv, stdout=log, stderr=log)))  # noqa: S603
        log.close()
        print(f"worker {stem} -> {log.name}")
    failed: list[str] = []
    for stem, proc in children:
        rc = proc.wait()
        if rc != 0:
            failed.append(f"{stem} (exit {rc})")
        print(f"worker {stem} finished rc={rc}")

    merged = ["# Agent evals report (merged)\n"]
    for rp in sorted(TRANSCRIPTS.glob("report-*.md")):
        merged.append(rp.read_text(encoding="utf-8"))
        merged.append("\n")
    (TRANSCRIPTS / "report.md").write_text("\n".join(merged), encoding="utf-8")
    print(f"merged report: {TRANSCRIPTS / 'report.md'}")
    if failed:
        print(f"FAILED workers: {', '.join(failed)}")
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skill", help="只跑某个 skill 的 evals（按 skill_name 匹配）")
    ap.add_argument("--file", help="只跑某个 eval 文件（按文件 stem 匹配；并行 worker 用）")
    ap.add_argument("--parallel", type=int, default=0,
                    help="按 eval 文件分组并行跑 N 个 worker（--execute 专用；报告自动合并）")
    ap.add_argument("--ids", help="逗号分隔的 eval id，如 1,2")
    ap.add_argument("--execute", action="store_true", help="真跑（headless claude，写真实平台）")
    ap.add_argument("--limit", type=int, default=0, help="本次最多跑 N 条（0=不限）；配 resume 分块跑")
    ap.add_argument("--force", action="store_true", help="已有 transcript 也重跑")
    ap.add_argument("--no-followup", dest="followup", action="store_false",
                    help="关闭自动批准轮（默认开）")
    ap.add_argument("--timeout", type=int, default=900, help="单条 eval/单轮 超时秒数")
    args = ap.parse_args()

    if args.parallel and args.execute:
        return run_parallel(args)

    ids = {int(x) for x in args.ids.split(",")} if args.ids else None
    picked = load_evals(args.skill, ids, args.file)
    if not picked:
        print("no evals matched")
        return 1

    if not args.execute:
        print(f"DRY — would execute {len(picked)} evals via headless claude (real platform writes!):")
        for key, entry in picked:
            print(f"  {key}: {entry['prompt'][:80]}...")
        print("re-run with --execute to actually run them")
        return 0

    if shutil.which("claude") is None:
        print("claude CLI not found on PATH")
        return 1

    TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
    report: list[str] = ["# Agent evals report\n"]
    total_pass = 0
    ran = 0
    for key, entry in picked:
        tpath = (TRANSCRIPTS / key.replace("/", "-")).with_suffix(".md")
        if tpath.exists() and not args.force:
            print(f"skip {key} (transcript exists)")
            continue
        if args.limit and ran >= args.limit:
            print(f"stopping: --limit {args.limit} reached (resume by re-running)")
            break
        ran += 1
        print(f"running {key} ...", flush=True)

        def claude(prompt: str, *, cont: bool = False) -> str:
            argv = ["claude", "-p", prompt, "--output-format", "text"]
            if cont:
                argv.append("--continue")
            # eval 要真实执行 skill 流：只放行 kgent/lark-cli 与本地文件工具
            argv += ["--allowedTools", "Bash(kgent:*)", "Bash(lark-cli:*)",
                     "Bash(dir:*)", "Read", "Write", "Edit"]
            done = subprocess.run(
                argv, capture_output=True, text=True, encoding="utf-8",
                timeout=args.timeout, cwd=str(REPO),
            )
            return done.stdout or done.stderr

        parts = [claude(entry["prompt"])]
        if args.followup:
            for approval in APPROVALS:
                parts.append(f"[user]: {approval}")
                parts.append(claude(approval, cont=True))
        transcript = "\n\n".join(parts)

        passed, misses, manual = heuristic_grade(entry.get("expectations", []), transcript)
        total = len(entry.get("expectations", []))
        total_pass += passed
        tpath.write_text(
            f"# eval {key}\n\n## prompt\n\n{entry['prompt']}\n\n"
            f"## transcript\n\n{transcript}\n",
            encoding="utf-8",
        )
        line = f"**{key}**: {passed}/{total} assertions hit (manual review: {manual})"
        if misses:
            line += " — misses:\n" + "\n".join(f"  - {m}" for m in misses)
        report.append(line + "\n")
        print(f"  {passed}/{total}")

    (TRANSCRIPTS / "report.md").write_text("\n".join(report), encoding="utf-8")
    print(f"\ndone — {total_pass} assertion hits total; report: {TRANSCRIPTS / 'report.md'}")
    print("heuristic grading only — human review of transcripts required before signing off")
    return 0


if __name__ == "__main__":
    sys.exit(main())
