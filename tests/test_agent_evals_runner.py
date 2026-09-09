# tests/test_agent_evals_runner.py
"""run-agent-evals.py 纯函数层：grader 兜底词 + fixture 一致性（T10 回归）。"""

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "run_agent_evals", str(REPO / "tools" / "run-agent-evals.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


runner = _load_runner()


def test_grader_accepts_dingtalk_integration_wording():
    passed, misses, manual = runner.heuristic_grade(
        [
            "For DingTalk targets the skill delegates execution via dingtalk-integration, not 'kgent update'"
        ],
        "transcript ... dingtalk-integration ... 遵循了委派",
    )
    assert passed == 1 and not misses and not manual


def test_every_eval_file_skill_name_matches_stem():
    for path in sorted((REPO / "evals" / "skills").glob("*-evals.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["skill_name"] == path.stem.replace("-evals", ""), path.name


def test_runner_allows_wecom_cli():
    """Phase 3 接线：allowedTools 必须放行 wecom-cli——wecom 腿的 eval 会真实
    调平台 CLI，缺放行 = 权限拒绝失败，失败形态不是断言未命中而是工具被拦，
    报告里看不出来龙去脉。源码文本级钉住（claude() 是嵌套函数，无纯函数面）。"""
    source = (REPO / "tools" / "run-agent-evals.py").read_text(encoding="utf-8")
    assert '"Bash(wecom-cli:*)"' in source


def test_grader_accepts_wecom_integration_wording():
    passed, misses, manual = runner.heuristic_grade(
        ["For WeCom targets the skill delegates execution via wecom-integration, not 'kgent update'"],
        "transcript ... wecom-integration ... 委派了",
    )
    assert passed == 1 and not misses and not manual
