"""dn_review_check 行为矩阵（评审结论结构断言器，R3/R4/R5/R6/R10，spec 2026-09-20）。

黑盒 subprocess 契约测试：exit 0 = 干净，1 = 违规，2 = 用法/IO/内部错误
（fail closed）。负控逐条目睹失败（old-coder RED），突变层依赖本文件杀突变体。
文法与 skills/decision-navigator/SKILL.md「评审结论格式」节逐字对齐（ADR 0014）。
"""

import subprocess
import sys
from pathlib import Path

import pytest

CHECKER = Path(__file__).resolve().parents[1] / "tools" / "dn_review_check.py"

CLEAN_DISPATCH = """【评审门 · 执行方式：派发评审】
## 事实接地
- 已解析引用 3/3
- [轻微][一致性核对] §5 排序 — 迁移成本表述过强 → 建议弱化为「估计」
## 逻辑审查
（无缺陷：未发现逻辑缺陷。）
"""

CLEAN_INLINE = CLEAN_DISPATCH.replace("派发评审", "内联复查")

CLEAN_NO_FINDINGS = """【评审门 · 执行方式：内联复查】
## 事实接地
- 已解析引用 2/2
（无缺陷：未发现事实接地缺陷。已解析引用 2/2；实证复核 0/≤3。）
## 逻辑审查
（无缺陷：未发现逻辑缺陷。）
"""

# 实证复核恰在上限 3（R6/FM-R8 的边界正控）
CLEAN_AT_CAP = """【评审门 · 执行方式：派发评审】
## 事实接地
- 已解析引用 4/4
- [致命][实证复核] §5 方案A 成本分项 — 源文无此数 → 撤回或降为假设
- [可修][实证复核] §3 Q2 报价 — 源文口径为含税 → 修正口径
- [轻微][实证复核] §4 权重 0.3 — 源文支持偏弱 → 补引用
- [轻微][一致性核对] §5 排序 — 表述过强 → 弱化
## 逻辑审查
- [可修] §5 结论 — 绕过未解节点 Q4 直接断言迁移可行 → 先声明假设
"""

UNEXECUTED = """【评审门 · 执行方式：评审未执行】
- 未执行原因：宿主不支持子代理派发且内联通道不可用；影响：本轮呈报未经独立复核
"""


def run_checker(tmp_path: Path, text: str, *args: str) -> subprocess.CompletedProcess:
    verdict = tmp_path / "verdict.md"
    verdict.write_text(text, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(CHECKER), *args, str(verdict)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


# ---------------------------------------------------------------- 正控（R3 全体）


@pytest.mark.parametrize(
    "verdict", [CLEAN_DISPATCH, CLEAN_INLINE, CLEAN_NO_FINDINGS, CLEAN_AT_CAP, UNEXECUTED]
)
def test_positive_control_clean_verdict_exit0(tmp_path, verdict: str):
    """合规评审结论（含执行方式三态与上限边界）→ exit 0。负控层的存在前提。"""
    result = run_checker(tmp_path, verdict)
    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------- 头部（执行方式）


def test_missing_header_exit1(tmp_path):
    """缺【评审门 · 执行方式：…】头 → 违规（执行方式不可省）。"""
    text = CLEAN_DISPATCH.splitlines(keepends=True)
    result = run_checker(tmp_path, "".join(text[1:]))
    assert result.returncode == 1
    assert "执行方式" in result.stdout


def test_unknown_execution_mode_exit1(tmp_path):
    """执行方式不在三态枚举内 → 违规（R1）。"""
    result = run_checker(tmp_path, CLEAN_DISPATCH.replace("派发评审", "自动审查"))
    assert result.returncode == 1
    assert "自动审查" in result.stdout


def test_duplicate_header_exit1(tmp_path):
    """两个评审门头 → 违规（一次 gate 恰一份结论）。"""
    result = run_checker(tmp_path, CLEAN_DISPATCH + CLEAN_DISPATCH)
    assert result.returncode == 1


# ---------------------------------------------------------------- 两节（R3）


def test_missing_grounding_section_exit1(tmp_path):
    """缺 事实接地 节 → 违规。"""
    text = CLEAN_DISPATCH.replace("## 事实接地\n- 已解析引用 3/3\n", "")
    result = run_checker(tmp_path, text)
    assert result.returncode == 1


def test_missing_logic_section_exit1(tmp_path):
    """缺 逻辑审查 节 → 违规。"""
    text = CLEAN_DISPATCH.rsplit("## 逻辑审查", 1)[0]
    result = run_checker(tmp_path, text)
    assert result.returncode == 1


def test_sections_out_of_order_exit1(tmp_path):
    """逻辑审查 在 事实接地 之前 → 违规（固定节序）。"""
    text = CLEAN_DISPATCH.replace("## 事实接地", "## 逻辑审查", 1).replace(
        "## 逻辑审查\n（无缺陷：未发现逻辑缺陷。）",
        "## 事实接地\n- 已解析引用 3/3\n（无缺陷：未发现逻辑缺陷。）",
        1,
    )
    result = run_checker(tmp_path, text)
    assert result.returncode == 1


def test_empty_logic_section_exit1(tmp_path):
    """逻辑审查 节体为空（连无缺陷行都没有）→ 违规。"""
    text = """【评审门 · 执行方式：内联复查】
## 事实接地
- 已解析引用 1/1
## 逻辑审查
"""
    result = run_checker(tmp_path, text)
    assert result.returncode == 1
    assert "逻辑审查" in result.stdout


# ---------------------------------------------------------------- 引用解析（R5）


def test_missing_resolved_citations_line_exit1(tmp_path):
    """事实接地 缺「已解析引用 n/m」行 → 违规（新增引用必须逐条申报解析）。"""
    text = CLEAN_DISPATCH.replace("- 已解析引用 3/3\n", "")
    result = run_checker(tmp_path, text)
    assert result.returncode == 1
    assert "已解析引用" in result.stdout


def test_resolved_exceeds_total_exit1(tmp_path):
    """已解析引用 5/3（解析数大于总数）→ 违规。"""
    text = CLEAN_DISPATCH.replace("已解析引用 3/3", "已解析引用 5/3")
    result = run_checker(tmp_path, text)
    assert result.returncode == 1


# ---------------------------------------------------------------- 发现分级（R4）


def test_unknown_severity_exit1(tmp_path):
    """严重级不在三态枚举内 → 违规。"""
    text = CLEAN_DISPATCH.replace("[轻微]", "[重大]")
    result = run_checker(tmp_path, text)
    assert result.returncode == 1
    assert "重大" in result.stdout


def test_grounding_finding_missing_method_exit1(tmp_path):
    """事实接地 发现缺核对方式 → 违规（事实条目必须标注 实证复核/一致性核对）。"""
    text = CLEAN_DISPATCH.replace("- [轻微][一致性核对]", "- [轻微]")
    result = run_checker(tmp_path, text)
    assert result.returncode == 1


def test_logic_finding_with_method_exit1(tmp_path):
    """逻辑审查 发现带核对方式 → 违规（核对方式只属事实接地条目）。"""
    text = CLEAN_DISPATCH.replace(
        "（无缺陷：未发现逻辑缺陷。）", "- [可修][实证复核] §5 结论 — 绕过未解节点"
    )
    result = run_checker(tmp_path, text)
    assert result.returncode == 1


def test_malformed_finding_line_exit1(tmp_path):
    """`- ` 起头但既非引用行亦非发现形 → 违规（残缺发现不得混入）。"""
    text = CLEAN_DISPATCH.replace("（无缺陷：未发现逻辑缺陷。）", "- 结论存疑，建议再看看")
    result = run_checker(tmp_path, text)
    assert result.returncode == 1


# ---------------------------------------------------------------- 抽样上限（R6）


def test_spot_checks_over_cap_exit1(tmp_path):
    """实证复核 4 条超默认上限 3 → 违规。"""
    over = CLEAN_AT_CAP.replace(
        "- [轻微][一致性核对] §5 排序 — 表述过强 → 弱化",
        "- [轻微][实证复核] §5 排序 — 表述过强 → 弱化",
    )
    result = run_checker(tmp_path, over)
    assert result.returncode == 1
    assert "实证复核" in result.stdout


def test_spot_checks_cap_flag_raises_limit(tmp_path):
    """--max-spot-checks 5 后同文合法（上限可调，契约不变）。"""
    over = CLEAN_AT_CAP.replace(
        "- [轻微][一致性核对] §5 排序 — 表述过强 → 弱化",
        "- [轻微][实证复核] §5 排序 — 表述过强 → 弱化",
    )
    result = run_checker(tmp_path, over, "--max-spot-checks", "5")
    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------- 未执行形态


def test_unexecuted_with_sections_exit1(tmp_path):
    """执行方式=评审未执行 却保留两节 → 违规（申报形态不得伪装成复核形态）。"""
    text = UNEXECUTED + CLEAN_DISPATCH.split("】", 1)[1]
    result = run_checker(tmp_path, text)
    assert result.returncode == 1


def test_unexecuted_missing_reason_exit1(tmp_path):
    """评审未执行 缺「未执行原因：…；影响：…」单行申报 → 违规（诚实申报优先）。"""
    result = run_checker(tmp_path, "【评审门 · 执行方式：评审未执行】\n（本轮跳过）\n")
    assert result.returncode == 1
    assert "未执行原因" in result.stdout


def test_normal_mode_missing_sections_already_covered(tmp_path):
    """普通执行方式但无两节（只报未执行原因）→ 违规。"""
    result = run_checker(
        tmp_path,
        "【评审门 · 执行方式：内联复查】\n- 未执行原因：宿主不支持；影响：未复核\n",
    )
    assert result.returncode == 1


# ---------------------------------------------------------------- fail closed


def test_unreadable_file_exit2(tmp_path):
    """输入文件不存在 → exit 2（不是 0，不是未捕获栈）。"""
    result = subprocess.run(
        [sys.executable, str(CHECKER), str(tmp_path / "nope.md")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 2


def test_directory_arg_exit2(tmp_path):
    """输入是目录 → exit 2（fail closed）。"""
    result = subprocess.run(
        [sys.executable, str(CHECKER), str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 2


def test_no_args_exit2():
    """零参数 → exit 2 用法错误。"""
    result = subprocess.run(
        [sys.executable, str(CHECKER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 2


def test_undecodable_file_exit2(tmp_path):
    """UTF-16 内容按 UTF-8 读失败 → exit 2（解码失败不静默当空）。"""
    verdict = tmp_path / "verdict.md"
    verdict.write_text("【评审门 · 执行方式：派发评审】", encoding="utf-16")
    result = subprocess.run(
        [sys.executable, str(CHECKER), str(verdict)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 2
