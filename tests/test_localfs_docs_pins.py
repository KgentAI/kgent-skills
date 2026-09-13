"""Docs pins: skills/local-fs-integration/SKILL.md keeps carrying the local-fs safety rules.

**Behavioral assurance lives at the agent-evals release gate, not here (controller
ruling, final review).** The URI refusal rules (absolute paths, `..` segments),
the version-CAS refusal, and the tmp+mv write discipline are *agent-execution*
rules: kgent ships them as skill prose, an agent executes them with raw shell
primitives, and the CLI has no local-fs adapter to assert against structurally
(ADR 0004/0006). Per ADR 0006 that discipline is enforced at the agent-evals
release gate. What CAN be asserted hermetically — fast, no artifact, no store —
is that the skill prose keeps carrying the rules: these pins fail when an edit
removes the documented rules from SKILL.md.
"""

# pyright: basic
from __future__ import annotations

from pathlib import Path

SKILL_PATH = Path(__file__).resolve().parents[1] / "skills" / "local-fs-integration" / "SKILL.md"


def _skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def test_skill_documents_uri_refusal_rules() -> None:
    """URI 拒绝规则必须在文档里：绝对路径与含 `..` 段的 id 一律拒绝（永不逃出 root）。"""
    text = _skill_text()
    assert "绝对路径" in text, "absolute-path rejection phrase missing from SKILL.md"
    assert "`..`" in text, "`..`-segment rejection phrase missing from SKILL.md"
    assert "一律拒绝" in text, "refusal wording missing from SKILL.md"
    assert "URI 永不逃出 root" in text, "containment promise missing from SKILL.md"


def test_skill_documents_body_hash_convention() -> None:
    """body-hash 口径必须在文档里：hash 只覆盖正文（第二个 --- 行之后的全部字节）。"""
    text = _skill_text()
    assert "`hash` 只覆盖" in text, "body-only hash scope missing from SKILL.md"
    assert "第二个 `---` 行之后的全部字节" in text, (
        "body-hash extraction convention line missing from SKILL.md"
    )
