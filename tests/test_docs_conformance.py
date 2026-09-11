"""文档可执行一致性（gauntlet layer D）。

skill 文档里的每条 CLI 示例必须**当下真实可解析**：子命令存在、 cited 旗标
在该子命令的 ``--help`` 里。杀 "文档与 CLI 行为漂移" 类（2026-09-06：
skill 指引 ``route --dry-run`` 而 CLI 不认该旗标，agent 照文档执行即 exit 2）。

解析级验证：``<sub> --help`` 能跑 + 每个旗标出现在 help 文本里；**不真执行**
写入。占位符（``<op_id>``、``<token>``）剥除后代入哨兵，不参与校验。
"""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"
DOC_FILES = [
    SKILLS_DIR / "ingest-knowledge" / "SKILL.md",
    SKILLS_DIR / "query-knowledge" / "SKILL.md",
    SKILLS_DIR / "wiki-setup" / "SKILL.md",
    SKILLS_DIR / "decision-navigator" / "SKILL.md",
    SKILLS_DIR / "lark-integration" / "SKILL.md",
    SKILLS_DIR / "dingtalk-integration" / "SKILL.md",
    SKILLS_DIR / "wecom-integration" / "SKILL.md",
]

_LINE = re.compile(r"^\s*(?:[-*]\s+|>\s*|\$\s+)?((?:kgent|lark-cli|dws|wecom-cli)\b.+)")

requires_artifact = pytest.mark.skipif(
    shutil.which("kgent") is None or shutil.which("lark-cli") is None,
    reason="kgent / lark-cli 未安装（文档一致性需要真实 CLI 的 --help）",
)


_SPAN = re.compile(r"`((?:kgent|lark-cli|dws|wecom-cli)\b[^`]+)`")


def _extract_examples(path: Path) -> list[str]:
    """抽候选命令：行首命令行（含 ``\\`` 续行）+ 行内反引号 span；管道段截断。"""
    examples: list[str] = []
    pending: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = pending[-1] + raw.lstrip() if pending else raw
        if line.rstrip().endswith("\\"):
            stripped = line.rstrip()[:-1].rstrip()
            match = _LINE.match(stripped) if not pending else re.match(r"\s*(.+)", stripped)
            if match:
                pending.append(match.group(1))
            continue
        pending.clear()
        match = _LINE.match(line)
        if match:
            examples.append(match.group(1).split("|")[0].strip())
        examples.extend(m.split("|")[0].strip() for m in _SPAN.findall(line))
    return [e for e in examples if e]


def _tokenize(example: str) -> list[str]:
    """剥占位符后代入哨兵，再 shlex 切词；哨兵 token 剔除。"""
    placeholdered = re.sub(r"<[^<>\s]+>", "XPLACEHOLDERX", example)
    return [
        tok
        for tok in shlex.split(placeholdered, posix=True)
        if tok != "XPLACEHOLDERX" and not tok.startswith("@")
    ]


def _deepest_help(binary: str, tokens: list[str]) -> tuple[list[str], str]:
    """找 tokens 的最长可用子命令前缀，返回（前缀, 其 --help 文本）。"""
    help_text = ""
    used = 0
    for depth in range(len(tokens), 0, -1):
        probe = [binary, *tokens[:depth], "--help"]
        result = subprocess.run(
            probe, capture_output=True, text=True, encoding="utf-8", shell=False, check=False
        )
        if result.returncode == 0:
            help_text = result.stdout + result.stderr
            used = depth
            break
    if used == 0:
        pytest.fail(f"无法解析子命令前缀：{' '.join(tokens)}")
    return tokens[:used], help_text


@requires_artifact
@pytest.mark.parametrize("doc", DOC_FILES, ids=lambda p: p.parent.name)
def test_documented_cli_examples_parse(doc: Path) -> None:
    kgent_bin = shutil.which("kgent")
    lark_bin = shutil.which("lark-cli")
    dws_bin = shutil.which("dws")
    wecom_bin = shutil.which("wecom-cli")
    assert kgent_bin is not None and lark_bin is not None
    # dws/wecom-cli 不进 requires_artifact 的 skipif：缺席时 lark/kgent 用例照跑，而
    # 对应 integration 用例在这里显式 fail（Task 1 之后应常驻），不静默 skip。
    if doc.parent.name == "dingtalk-integration":
        assert dws_bin is not None, "Task 1 之后 dws 应常驻"
    if doc.parent.name == "wecom-integration":
        assert wecom_bin is not None, "Task 1 之后 wecom-cli 应常驻"
    checked = 0
    for example in _extract_examples(doc):
        tokens = _tokenize(example)
        if not tokens:
            continue
        if tokens[0] == "kgent":
            binary = kgent_bin
        elif tokens[0] == "lark-cli":
            binary = lark_bin
        elif tokens[0] == "dws":
            binary = dws_bin
        elif tokens[0] == "wecom-cli":
            binary = wecom_bin
        else:
            continue  # 非命令提及（如 ``kgent://`` URI span），非一致性声明
        rest = tokens[1:]
        if not rest:
            continue  # 纯概念提及（binary + 占位符），非一致性声明
        prefix, help_text = _deepest_help(binary, rest)
        flags = [t for t in rest[len(prefix):] if t.startswith("--") and t != "--help"]
        for flag in flags:
            assert flag in help_text, (
                f"{doc.parent.name}: 示例旗标 {flag} 不被 {' '.join(prefix)} 接受\n示例: {example}"
            )
        checked += 1
    assert checked >= 1, f"{doc.parent.name}: 抽取到 {checked} 条示例，疑似抽取器失效"
