"""dn_brief_check 行为矩阵（B5/B6/B7 结构断言器，spec 2026-09-11）。

黑盒 subprocess 契约测试：exit 0 = 干净，1 = 违规，2 = 用法/IO/内部错误
（fail closed）。负控逐条目睹失败（old-coder RED），突变层依赖本文件杀突变体。
"""

import subprocess
import sys
from pathlib import Path

import pytest

CHECKER = Path(__file__).resolve().parents[1] / "tools" / "dn_brief_check.py"

MERMAID_CLEAN = """```mermaid
flowchart TD
    N1["预算上限"]
    N2["供应商报价"]
    N3["上线窗口"]
    N1 --> N2
    N1 --> N3
```"""

NODES_CLEAN = """- N1 [用户已给] 预算上限 50 万
- N2 [引用来源|https://example.larksuite.com/docx/abc] 现供应商报价 依:N1
- N3 [假设] Q4 上线为硬约束 依:N1"""

CONVERGED = "第2轮收敛：本轮零新增、零重开、零新增引用解算。"


def _brief(
    mermaid: str = MERMAID_CLEAN,
    nodes: str = NODES_CLEAN,
    convergence: str = CONVERGED,
    extra: str = "",
) -> str:
    return f"""# 决策简报：客服系统续约 vs 迁移

## 决策分解

{mermaid}

{nodes}

## 收敛申报

{convergence}

## 评价准则
（略）{extra}
"""


def run_checker(tmp_path: Path, text: str, *args: str) -> subprocess.CompletedProcess:
    brief = tmp_path / "brief.md"
    brief.write_text(text, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(CHECKER), *args, str(brief)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


# ---------------------------------------------------------------- 正控（B 全体）


def test_positive_control_clean_brief_exit0(tmp_path):
    """合规简报 → exit 0。负控层的存在前提：先见到正控绿。"""
    result = run_checker(tmp_path, _brief())
    assert result.returncode == 0, result.stdout + result.stderr


def test_fullwidth_deps_accepted(tmp_path):
    """全角冒号/逗号的 依：N1，N2 同样接受。"""
    nodes = "- N1 [假设] A\n- N2 [假设] B\n- N3 [假设] C 依：N1，N2"
    mermaid = "```mermaid\nflowchart TD\n    N1 --> N3\n    N2 --> N3\n```"
    result = run_checker(tmp_path, _brief(mermaid=mermaid, nodes=nodes))
    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------- B5 节点状态


def test_missing_state_exit1(tmp_path):
    """节点缺状态括号 → 违规。"""
    nodes = "- N1 [用户已给] 预算上限\n- N2 现供应商报价"
    mermaid = "```mermaid\nflowchart TD\n    N1 --> N2\n```"
    result = run_checker(tmp_path, _brief(mermaid=mermaid, nodes=nodes))
    assert result.returncode == 1
    assert "N2" in result.stdout


def test_unknown_state_exit1(tmp_path):
    """状态词不在四种枚举内 → 违规。"""
    nodes = "- N1 [已解决] 预算上限"
    mermaid = "```mermaid\nflowchart TD\n    N1\n```"
    result = run_checker(tmp_path, _brief(mermaid=mermaid, nodes=nodes))
    assert result.returncode == 1
    assert "已解决" in result.stdout


def test_cited_state_without_url_exit1(tmp_path):
    """引用来源 不带 |url → 违规。"""
    nodes = "- N1 [引用来源] 现供应商报价"
    mermaid = "```mermaid\nflowchart TD\n    N1\n```"
    result = run_checker(tmp_path, _brief(mermaid=mermaid, nodes=nodes))
    assert result.returncode == 1


def test_cited_kgent_uri_exit1(tmp_path):
    """引用来源 带 kgent:// → 违规（N20/S74：只准原生 URL）。"""
    nodes = "- N1 [引用来源|kgent://lark/abc] 现供应商报价"
    mermaid = "```mermaid\nflowchart TD\n    N1\n```"
    result = run_checker(tmp_path, _brief(mermaid=mermaid, nodes=nodes))
    assert result.returncode == 1


def test_kgent_uri_anywhere_exit1(tmp_path):
    """简报任何位置出现 kgent:// → 违规。"""
    result = run_checker(tmp_path, _brief(extra="参见 kgent://lark/xyz"))
    assert result.returncode == 1
    assert "kgent://" in result.stdout


def test_noncited_state_with_url_suffix_exit1(tmp_path):
    """非 引用来源 状态的括号内带 |… → 违规（状态括号必须恰一形态）。"""
    nodes = "- N1 [假设|https://example.com/x] 预算上限"
    mermaid = "```mermaid\nflowchart TD\n    N1\n```"
    result = run_checker(tmp_path, _brief(mermaid=mermaid, nodes=nodes))
    assert result.returncode == 1


def test_duplicate_node_id_exit1(tmp_path):
    """节点 ID 重复 → 违规。"""
    nodes = "- N1 [假设] A\n- N1 [假设] B"
    mermaid = "```mermaid\nflowchart TD\n    N1\n```"
    result = run_checker(tmp_path, _brief(mermaid=mermaid, nodes=nodes))
    assert result.returncode == 1
    assert "重复" in result.stdout or "duplicate" in result.stdout.lower()


def test_dep_to_unknown_node_exit1(tmp_path):
    """依 引用到未定义节点 → 违规。"""
    nodes = "- N1 [假设] A 依:N9"
    mermaid = "```mermaid\nflowchart TD\n    N1\n```"
    result = run_checker(tmp_path, _brief(mermaid=mermaid, nodes=nodes))
    assert result.returncode == 1
    assert "N9" in result.stdout


def test_empty_node_list_exit1(tmp_path):
    """零节点（图在表不在）→ 违规。"""
    result = run_checker(tmp_path, _brief(nodes="（本轮无节点）"))
    assert result.returncode == 1


# ---------------------------------------------------------------- B6 图表交叉


def test_divergent_edge_mermaid_only_exit1(tmp_path):
    """mermaid 有边、节点表缺 依 → 违规（边集不等，mermaid 侧多出）。"""
    mermaid = "```mermaid\nflowchart TD\n    N1 --> N2\n```"
    nodes = "- N1 [假设] A\n- N2 [假设] B"
    result = run_checker(tmp_path, _brief(mermaid=mermaid, nodes=nodes))
    assert result.returncode == 1


def test_divergent_edge_list_only_exit1(tmp_path):
    """节点表有 依、mermaid 缺边 → 违规（边集不等，表侧多出）。"""
    mermaid = "```mermaid\nflowchart TD\n    N1\n    N2\n```"
    nodes = "- N1 [假设] A\n- N2 [假设] B 依:N1"
    result = run_checker(tmp_path, _brief(mermaid=mermaid, nodes=nodes))
    assert result.returncode == 1


def test_cyclic_graph_exit1(tmp_path):
    """环 N1→N2→N1 → 违规（子问题图必须是 DAG）。"""
    mermaid = "```mermaid\nflowchart TD\n    N1 --> N2\n    N2 --> N1\n```"
    nodes = "- N1 [假设] A 依:N2\n- N2 [假设] B 依:N1"
    result = run_checker(tmp_path, _brief(mermaid=mermaid, nodes=nodes))
    assert result.returncode == 1
    assert "环" in result.stdout or "cycle" in result.stdout.lower()


def test_mermaid_node_missing_from_list_exit1(tmp_path):
    """mermaid 节点不在节点表 → 违规（覆盖双向）。"""
    mermaid = "```mermaid\nflowchart TD\n    N1\n    N2\n```"
    nodes = "- N1 [假设] A"
    result = run_checker(tmp_path, _brief(mermaid=mermaid, nodes=nodes))
    assert result.returncode == 1
    assert "N2" in result.stdout


def test_list_node_missing_from_mermaid_exit1(tmp_path):
    """节点表节点不在 mermaid → 违规（覆盖双向）。"""
    mermaid = "```mermaid\nflowchart TD\n    N1\n```"
    nodes = "- N1 [假设] A\n- N5 [假设] E"
    result = run_checker(tmp_path, _brief(mermaid=mermaid, nodes=nodes))
    assert result.returncode == 1
    assert "N5" in result.stdout


def test_pseudo_mermaid_wrong_dialect_exit1(tmp_path):
    """方言限定裸 flowchart TD：graph LR → 违规。"""
    mermaid = "```mermaid\ngraph LR\n    N1 --> N2\n```"
    nodes = "- N1 [假设] A\n- N2 [假设] B 依:N1"
    result = run_checker(tmp_path, _brief(mermaid=mermaid, nodes=nodes))
    assert result.returncode == 1


def test_pseudo_mermaid_bad_edge_syntax_exit1(tmp_path):
    """非裸 --> 边形（虚线/粗线/带文字）→ 违规。"""
    mermaid = "```mermaid\nflowchart TD\n    N1 -.-> N2\n```"
    nodes = "- N1 [假设] A\n- N2 [假设] B 依:N1"
    result = run_checker(tmp_path, _brief(mermaid=mermaid, nodes=nodes))
    assert result.returncode == 1


def test_missing_mermaid_block_exit1(tmp_path):
    """整份简报无 mermaid 块 → 违规。"""
    result = run_checker(tmp_path, _brief(mermaid="（图略）"))
    assert result.returncode == 1


def test_two_mermaid_blocks_exit1(tmp_path):
    """两个 mermaid 块 → 违规（恰一）。"""
    brief = _brief() + "\n\n```mermaid\nflowchart TD\n    N1 --> N2\n```\n"
    result = run_checker(tmp_path, brief)
    assert result.returncode == 1


# ---------------------------------------------------------------- B7 收敛申报


def test_missing_convergence_exit1(tmp_path):
    """无收敛申报 → 违规。"""
    result = run_checker(tmp_path, _brief(convergence="（我们认为已经足够了）"))
    assert result.returncode == 1


def test_converged_over_cap_exit1(tmp_path):
    """第5轮收敛 超默认上限 3 且无达限/延长 → 违规。"""
    result = run_checker(tmp_path, _brief(convergence="第5轮收敛：零新增。"))
    assert result.returncode == 1


def test_extension_recorded_exit0(tmp_path):
    """达限 + 用户批准延长 + 第5轮收敛 → 合法（exit 0）。"""
    convergence = "第3轮达限，经用户批准延长3轮；第5轮收敛：零新增。"
    result = run_checker(tmp_path, _brief(convergence=convergence))
    assert result.returncode == 0, result.stdout + result.stderr


def test_cap_reached_assumption_path_exit0(tmp_path):
    """达限 + 余下按假设 → 合法（exit 0）。"""
    convergence = "3轮达限，未收敛；余下开放节点按假设处理。"
    result = run_checker(tmp_path, _brief(convergence=convergence))
    assert result.returncode == 0, result.stdout + result.stderr


def test_custom_max_passes_flag(tmp_path):
    """--max-passes 提高上限后 第5轮收敛 合法。"""
    result = run_checker(tmp_path, _brief(convergence="第5轮收敛：零新增。"), "--max-passes", "5")
    assert result.returncode == 0, result.stdout + result.stderr


def test_converged_over_extended_cap_exit1(tmp_path):
    """延长后仍超总上限（延长3 → 总 6，第7轮收敛）→ 违规。"""
    convergence = "第3轮达限，经用户批准延长3轮；第7轮收敛。"
    result = run_checker(tmp_path, _brief(convergence=convergence))
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


@pytest.mark.parametrize("encoding", ["utf-16"])
def test_undecodable_file_exit2(tmp_path, encoding):
    """UTF-16 内容按 UTF-8 读失败 → exit 2（解码失败不静默当空）。"""
    brief = tmp_path / "brief.md"
    brief.write_text("第2轮收敛", encoding=encoding)
    result = subprocess.run(
        [sys.executable, str(CHECKER), str(brief)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 2
