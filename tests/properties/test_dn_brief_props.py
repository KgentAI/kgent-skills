"""P8: Valid-brief acceptance.

任何由合法 DAG + 状态指派渲染出的决策简报，dn_brief_check 必须放行（exit 0）。
解析器 fail-open 检测：正空间模糊测试，与 test_dn_brief_check.py 的负控互补。
"""

import subprocess
import sys
from pathlib import Path

from hypothesis import HealthCheck, given, settings, strategies as st

CHECKER = Path(__file__).resolve().parents[2] / "tools" / "dn_brief_check.py"

STATES = ["用户已给", "引用来源", "假设", "依前未解"]


def _render(ids: list[str], deps: dict[str, list[str]], states: dict[str, str],
            convergence: str) -> str:
    mermaid_lines = ["```mermaid", "flowchart TD"]
    for nid in ids:
        mermaid_lines.append(f'    {nid}["节点{nid}"]')
    # deps[nid] = "nid 依 谁"；边方向 = 依赖喂向依赖方 → dep --> nid
    for nid in ids:
        for dep in deps[nid]:
            mermaid_lines.append(f"    {dep} --> {nid}")
    mermaid_lines.append("```")
    node_lines = []
    for nid in ids:
        if states[nid] == "引用来源":
            node_lines.append(
                f"- {nid} [引用来源|https://example.larksuite.com/docx/{nid.lower()}]"
                f" 内容{nid} 依:{','.join(deps[nid])}"
                if deps[nid]
                else f"- {nid} [引用来源|https://example.larksuite.com/docx/{nid.lower()}]"
                f" 内容{nid}"
            )
        else:
            node_lines.append(
                f"- {nid} [{states[nid]}] 内容{nid} 依:{','.join(deps[nid])}"
                if deps[nid]
                else f"- {nid} [{states[nid]}] 内容{nid}"
            )
    return (
        "# 决策简报\n\n## 决策分解\n\n"
        + "\n".join(mermaid_lines)
        + "\n\n"
        + "\n".join(node_lines)
        + "\n\n## 收敛申报\n\n"
        + convergence
        + "\n"
    )


@st.composite
def _valid_briefs(draw):
    n = draw(st.integers(min_value=1, max_value=10))
    ids = [f"N{i}" for i in range(1, n + 1)]
    deps: dict[str, list[str]] = {nid: [] for nid in ids}
    for i, nid in enumerate(ids):
        # 只允许指向更早的节点 → 必然无环
        earlier = ids[:i]
        if earlier:
            deps[nid] = draw(st.sets(st.sampled_from(earlier), max_size=len(earlier)))
    states = {nid: draw(st.sampled_from(STATES)) for nid in ids}
    convergence = draw(
        st.sampled_from([
            "第1轮收敛：零新增。",
            "第3轮收敛：零新增、零重开。",
            "3轮达限，余下开放节点按假设处理。",
            "第3轮达限，经用户批准延长3轮；第5轮收敛。",
        ])
    )
    return _render(ids, deps, states, convergence)


@given(brief=_valid_briefs())
@settings(
    max_examples=50,
    derandomize=True,
    # 每个生成输入都整体覆写同一文件（house pattern，tests/properties/test_bound.py）
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_p8_valid_brief_always_passes(tmp_path, brief: str):
    path = tmp_path / "brief.md"
    path.write_text(brief, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(CHECKER), str(path)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, f"{brief}\n---\n{result.stdout}{result.stderr}"
