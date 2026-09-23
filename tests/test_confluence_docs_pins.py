"""Docs pins: skills/confluence-integration/SKILL.md keeps carrying the confluence rules.

**Behavioral assurance lives at the agent-evals release gate, not here** (the
local-fs pins docstring precedent). What CAN be asserted hermetically is that
the skill prose keeps carrying: the transport ladder, the journal/CAS write
discipline, the CQL escaping rule, the format-bridge lossy disclosure, the
allowlist narrowing semantics, the native-URL citation rule, the undo
compensation semantics, and the platform-side known limitations.
"""

# pyright: basic
from __future__ import annotations

from pathlib import Path

SKILL_PATH = Path(__file__).resolve().parents[1] / "skills" / "confluence-integration" / "SKILL.md"


def _skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def test_skill_documents_gate_and_transport_ladder() -> None:
    text = _skill_text()
    assert "backends.confluence.enabled: true" in text, "gate phrase missing"
    assert "acli" in text and "MCP" in text, "ladder legs missing"
    assert "优雅禁用" in text, "graceful-disable ladder leg missing"


def test_skill_documents_credentials_rule() -> None:
    text = _skill_text()
    assert "凭据" in text, "credential rule missing"
    assert "不出现在" in text or "不得出现" in text, "credential non-disclosure missing"


def test_skill_documents_journal_write_discipline() -> None:
    text = _skill_text()
    assert "journal begin" in text and "journal end" in text, "ledger pairing missing"
    assert "--revision-before" in text and "--revision-after" in text, "revision fields missing"
    assert "读回校验" in text or "读回" in text, "read-back verification missing"


def test_skill_documents_version_cas() -> None:
    text = _skill_text()
    assert "version" in text, "version axis missing"
    assert "+ 1" in text or "+1" in text, "version+1 conditional write missing"
    assert "409" in text, "conflict-status refusal missing"


def test_skill_documents_cql_escaping() -> None:
    text = _skill_text()
    assert "CQL" in text, "CQL missing"
    assert "转义" in text, "escaping rule missing"


def test_skill_documents_format_bridge() -> None:
    text = _skill_text()
    assert "kgent formats to-markdown" in text, "read-direction converter command missing"
    assert "kgent formats to-storage-xhtml" in text, "write-direction converter command missing"
    assert "桥外" in text, "bridge-external loss disclosure missing"
    assert "快照" in text, "pre-write snapshot as recovery path missing"


def test_skill_documents_allowlist_narrowing_semantics() -> None:
    text = _skill_text()
    assert "收窄" in text, "narrowing semantics missing"
    assert "保密边界" in text or "不是保密" in text, "not-a-secrecy-boundary warning missing"


def test_skill_documents_native_url_rule() -> None:
    text = _skill_text()
    assert "kgent://" in text and "永不" in text, "no-kgent-URI-to-users rule missing"
    assert "viewpage.action" in text or "/wiki/spaces/" in text, "URL shapes missing"
    assert "site" in text, "site config reference missing"


def test_skill_documents_undo_compensation() -> None:
    text = _text_or_fail()
    assert "version-revert" in text, "mechanism name missing"
    assert "新版本" in text, "rewrite-as-new-version disclosure missing"
    assert "回收站" in text, "trash semantics missing"
    assert "rejected" in text, "plan-rejection stop rule missing"


def test_skill_documents_known_limitations() -> None:
    text = _text_or_fail()
    for phrase in ("blog", "whiteboard", "database", "附件", "archive", "purge"):
        assert phrase in text, f"known-limitation phrase {phrase!r} missing"
    assert "宏" in text, "macro limitation missing"


def _text_or_fail() -> str:
    try:
        return _skill_text()
    except FileNotFoundError as exc:  # pragma: no cover - pin failure path
        raise AssertionError("skills/confluence-integration/SKILL.md is missing") from exc
