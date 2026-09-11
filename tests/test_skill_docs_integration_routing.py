# tests/test_skill_docs_integration_routing.py
"""B9: 平台操作必须经 integration skill——skills 文档静态检查（ADR 0004）。"""
import re
from pathlib import Path

SKILLS = ["ingest-knowledge", "query-knowledge", "wiki-setup"]
DIRECT = re.compile(
    r"kgent (search|read|update|create|store|wiki)[^\n]*--backends?\s+(lark|dingtalk|wecom)",
    re.IGNORECASE,
)
INTEGRATION_REF = re.compile(r"\b(lark|dingtalk|wecom)-integration\b")

def test_no_direct_platform_cli_calls_in_skills():
    for name in SKILLS:
        text = (Path("skills") / name / "SKILL.md").read_text(encoding="utf-8")
        assert not DIRECT.search(text), f"{name} 仍直调平台后端"

def test_skills_route_platform_ops_via_integration_skill():
    for name in SKILLS:
        text = (Path("skills") / name / "SKILL.md").read_text(encoding="utf-8")
        assert INTEGRATION_REF.search(text), f"{name} 缺 <platform>-integration 路由说明"
