"""P-Review: Valid-verdict acceptance + enum closedness.

任何由合法执行方式 × 严重级 × 核对方式 × 限额内抽样渲染出的评审结论，
dn_review_check 必须放行（exit 0）；非法严重级注入必须拒绝（exit 1）。
解析器 fail-open 检测：正空间模糊测试，与 test_dn_review_check.py 的负控互补。
"""

import subprocess
import sys
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

CHECKER = Path(__file__).resolve().parents[2] / "tools" / "dn_review_check.py"

MODES = ["派发评审", "内联复查"]
SEVERITIES = ["致命", "可修", "轻微"]
METHODS = ["实证复核", "一致性核对"]
BAD_SEVERITIES = ["重大", "严重", "critical", "中等"]
MAX_SPOT_CHECKS = 3

UNEXEC_REASONS = ["宿主不支持子代理派发", "派发工具不可用"]
UNEXEC_IMPACTS = ["本轮呈报未经独立复核", "事实接地未执行"]


def _render_ground(parsed: int, total: int, findings: list[str]) -> str:
    body = f"- 已解析引用 {parsed}/{total}"
    if findings:
        body += "\n" + "\n".join(findings)
    else:
        body += "\n（无缺陷：未发现事实接地缺陷。）"
    return body


@st.composite
def _valid_verdicts(draw) -> str:
    mode = draw(st.sampled_from(MODES + ["评审未执行"]))
    if mode == "评审未执行":
        reason = draw(st.sampled_from(UNEXEC_REASONS))
        impact = draw(st.sampled_from(UNEXEC_IMPACTS))
        return f"【评审门 · 执行方式：评审未执行】\n- 未执行原因：{reason}；影响：{impact}\n"
    parsed = draw(st.integers(min_value=0, max_value=6))
    total = parsed + draw(st.integers(min_value=0, max_value=2))
    ground_findings: list[str] = []
    spot = 0
    for _ in range(draw(st.integers(min_value=0, max_value=5))):
        severity = draw(st.sampled_from(SEVERITIES))
        method = draw(st.sampled_from(METHODS))
        if method == "实证复核":
            if spot >= MAX_SPOT_CHECKS:
                method = "一致性核对"
            else:
                spot += 1
        ground_findings.append(
            f"- [{severity}][{method}] 定位{draw(st.integers(0, 9))}"
            f" — 缺陷{draw(st.integers(0, 9))} → 建议{draw(st.integers(0, 9))}"
        )
    logic_findings = [
        f"- [{draw(st.sampled_from(SEVERITIES))}] 定位{i} — 推理缺陷"
        for i in range(draw(st.integers(min_value=0, max_value=3)))
    ]
    logic_body = "\n".join(logic_findings) if logic_findings else "（无缺陷：未发现逻辑缺陷。）"
    return (
        f"【评审门 · 执行方式：{mode}】\n"
        f"## 事实接地\n"
        f"{_render_ground(parsed, total, ground_findings)}\n"
        f"## 逻辑审查\n"
        f"{logic_body}\n"
    )


def _run(tmp_path: Path, text: str, *args: str) -> subprocess.CompletedProcess:
    path = tmp_path / "verdict.md"
    path.write_text(text, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(CHECKER), *args, str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


@given(verdict=_valid_verdicts())
@settings(
    max_examples=50,
    derandomize=True,
    # 每个生成输入都整体覆写同一文件（house pattern，tests/properties/test_bound.py）；
    # deadline=None：黑盒 subprocess 起进程在 Windows 上墙钟抖动（同 test_idempotence）。
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_p_review_valid_verdict_always_passes(tmp_path, verdict: str):
    result = _run(tmp_path, verdict)
    assert result.returncode == 0, f"{verdict}\n---\n{result.stdout}{result.stderr}"


@given(verdict=_valid_verdicts(), bad=st.sampled_from(BAD_SEVERITIES))
@settings(
    max_examples=30,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_p_review_unknown_severity_always_rejected(tmp_path, verdict: str, bad: str):
    """向逻辑审查节注入非法严重级 → 恒 exit 1（枚举封闭，fail-open 检测）。"""
    mutated = verdict + f"- [{bad}] 定位 — 缺陷\n"
    result = _run(tmp_path, mutated)
    assert result.returncode == 1, f"{mutated}\n---\n{result.stdout}{result.stderr}"
