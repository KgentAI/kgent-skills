"""Write-proposal + confirmation gate (§5.6, S1–S4, N1).

The N1-critical invariant: no write without a recorded confirmation that
matches the executed targets — the router never performs a write leg that was
not confirmed, and the journal entry records exactly the uris actually
executed.
"""

from __future__ import annotations

import pytest

from kgent.errors import PolicyError
from kgent.router.audit import AuditLog
from kgent.router.journal import Journal
from kgent.router.policy import confirm, execute_confirmed
from kgent.types import WriteProposal
from tests.fakes.fake_backend import FakeBackend


def _prop(**kw: object) -> WriteProposal:
    base: dict[str, object] = {
        "operation": "create",
        "targets": [("lark", None)],
        "title": "Retros 2026-08",
        "content": "Retro meeting notes.",
        "content_type": None,
        "sensitivity": "internal",
        "approval_required": False,
        "provenance": {},
        "degraded": [],
        "warnings": [],
        "snapshot_note": "",
    }
    base.update(kw)
    return WriteProposal(**base)  # type: ignore[arg-type]


def test_s1_interactive_confirm_then_write(test_world):
    backend: FakeBackend = test_world["backends"]["lark"]
    journal = Journal()
    audit = AuditLog()
    prop = _prop()
    conf = confirm(prop, "interactive", answer="yes")
    assert conf == "interactive-yes"
    # router executes create on lark and journals the confirmation
    op = execute_confirmed(
        prop, conf, backends=test_world["backends"], journal=journal, audit=audit
    )
    assert len(backend.write_calls) == 1
    assert op.journal_entry["confirmation"] == "interactive-yes"
    assert journal.latest == op.journal_entry


def test_s2_no_confirmation_no_write(test_world):
    prop = _prop()
    for answer in ("no", "timeout", "eof"):
        assert confirm(prop, "interactive", answer=answer) == "rejected"
    # a rejected confirmation must never touch a backend or journal
    assert test_world["backends"]["lark"].write_calls == []


def test_s3_yes_without_backends_does_not_bypass():
    prop = _prop()
    conf = confirm(prop, "--yes", explicit_backends=False)
    assert conf == "rejected"
    # warning containing "--yes requires explicit --backends" is surfaced
    assert any("--yes requires explicit --backends" in w for w in prop.warnings)


def test_s4_yes_with_explicit_backends_but_empty_content_rejects():
    prop = _prop(content="")
    conf = confirm(prop, "--yes", explicit_backends=True)
    assert conf == "rejected"
    # the content-empty guard is a separate rejection reason but must still
    # surface the required warning substring
    assert any("--yes requires explicit --backends" in w for w in prop.warnings)


def test_s4_yes_with_explicit_backends_and_content(test_world):
    backend: FakeBackend = test_world["backends"]["lark"]
    journal = Journal()
    audit = AuditLog()
    prop = _prop()
    conf = confirm(prop, "--yes", explicit_backends=True)
    assert conf == "--yes"
    op = execute_confirmed(
        prop, conf, backends=test_world["backends"], journal=journal, audit=audit
    )
    assert len(backend.write_calls) == 1
    assert op.journal_entry["confirmation"] == "--yes"
    assert journal.latest["confirmation"] == "--yes"


def test_n1_executed_targets_equal_journaled(test_world):
    backend: FakeBackend = test_world["backends"]["lark"]
    journal = Journal()
    audit = AuditLog()
    prop = _prop()
    op = execute_confirmed(
        prop,
        "interactive-yes",
        backends=test_world["backends"],
        journal=journal,
        audit=audit,
    )
    uris = [c["uri"] for c in backend.write_calls]
    assert op.journal_entry["targets"] == uris
    assert journal.latest["targets"] == uris


def test_n4_zones_enforced_before_any_write(test_world):
    """A confidential write to an external-zone backend must do ZERO writes (N4).

    Zone checks run for ALL targets before the first write, so an earlier
    in-zone target is not touched when a later target violates the zone rule.
    """
    journal = Journal()
    audit = AuditLog()
    prop = _prop(
        targets=[("lark", None), ("dingtalk", None)],
        sensitivity="confidential",
    )
    with pytest.raises(PolicyError):
        execute_confirmed(
            prop,
            "interactive-yes",
            backends=test_world["backends"],
            journal=journal,
            audit=audit,
        )
    assert test_world["backends"]["lark"].write_calls == []
    assert test_world["backends"]["dingtalk"].write_calls == []
    assert journal.entries == []


def test_rejected_confirmation_never_executes(test_world):
    backend: FakeBackend = test_world["backends"]["lark"]
    journal = Journal()
    audit = AuditLog()
    prop = _prop()
    with pytest.raises(PolicyError):
        execute_confirmed(
            prop,
            "rejected",
            backends=test_world["backends"],
            journal=journal,
            audit=audit,
        )
    assert backend.write_calls == []
    assert journal.entries == []


# ---------------------------------------------------------------------------
# I4（final review）：写路径 trust_zone 与 route 同源——config，不是 adapter 属性
# ---------------------------------------------------------------------------


def test_n4_real_adapter_without_zone_attr_falls_closed_external(tmp_home):
    """真实 LarkAdapter（无 ``trust_zone`` 属性）+ confidential → 按外部拒，不炸。

    写路径曾直接读 ``backends[name].trust_zone``：FakeBackend 有该字段把缺陷
    整个掩蔽，真实 adapter 首跑即 ``AttributeError``。修复后无 map 的直调走
    legacy 属性读，属性缺失时 fail-closed 落到 ``external``（同 route 的底）。
    构造真实 adapter 是零网络的（只存 cmd/name/timeout）；zone 检查先于任何
    adapter 调用，本用例也不会触发子进程。
    """
    from kgent.adapters.lark import LarkAdapter

    journal = Journal(tmp_home)
    audit = AuditLog(path=tmp_home / "audit.ndjson")
    prop = _prop(sensitivity="confidential")
    with pytest.raises(PolicyError, match="external-zone backend 'lark'"):
        execute_confirmed(
            prop,
            "interactive-yes",
            backends={"lark": LarkAdapter()},
            journal=journal,
            audit=audit,
        )
    assert journal.entries == []


def test_n4_zone_map_missing_name_falls_closed_external(tmp_home):
    """config 派生的 zone map 里没有该 backend → 落 external 拒绝（map 的底）。"""
    journal = Journal(tmp_home)
    audit = AuditLog(path=tmp_home / "audit.ndjson")
    prop = _prop(sensitivity="confidential")
    with pytest.raises(PolicyError, match="external-zone backend 'lark'"):
        execute_confirmed(
            prop,
            "interactive-yes",
            backends=_internal_backends(),
            journal=journal,
            audit=audit,
            trust_zones={"other": "internal"},  # lark 缺席 → external
        )


def _internal_backends() -> dict:
    return {"lark": FakeBackend("lark", "internal", {})}


def test_n4_router_wires_zone_map_from_config(tmp_home, capsys):
    """Router.execute 把 config 派生的 zone map 接进写门（与 route 同源，I4）。

    config.yaml 不写 trust_zone → schema 默认 external：confidential 写经真实
    LarkAdapter 也被 exit 3 拒绝——zone 来自 config，而不是 adapter 属性；
    把 trust_zone 写成 internal 后同一 tier 放行，证明 source of truth 是配置。
    """
    import json

    from kgent.adapters import registry
    from kgent.adapters.lark import LarkAdapter
    from kgent.cli import main

    registry.register("lark", LarkAdapter())
    (tmp_home / "config.yaml").write_text(
        "version: 1\n"
        "defaults:\n"
        "  routing_mode: configured\n"
        "  default_backends: [lark]\n"
        "  approval_ttl_hours: 24\n"
        "backends:\n"
        "  lark:\n"
        "    enabled: true\n"
        "    type: skill\n"
        "    skill_name: lark-doc\n",
        encoding="utf-8",
    )
    argv = [
        "create",
        "--title",
        "Secrets",
        "--content",
        "acquisition plan",
        "--sensitivity",
        "confidential",
        "--backends",
        "lark",
        "--json",
    ]
    try:
        code = main(argv)
        out = json.loads(capsys.readouterr().out)
        assert code == 3  # zone 拒（policy-rejected），不是 AttributeError 崩溃
        assert "external-zone backend 'lark'" in out["error"]

        # 同一 adapter，config 翻成 internal → 放行（写入会真的发生，
        # 但 zone 检查后 FakeBackend 才会被调用——这里换回 fake 验证放行面）
        registry.register("lark", FakeBackend("lark", "internal", {}))
        (tmp_home / "config.yaml").write_text(
            "version: 1\n"
            "defaults:\n"
            "  routing_mode: configured\n"
            "  default_backends: [lark]\n"
            "  approval_ttl_hours: 24\n"
            "backends:\n"
            "  lark:\n"
            "    enabled: true\n"
            "    type: skill\n"
            "    skill_name: lark-doc\n"
            "    trust_zone: internal\n",
            encoding="utf-8",
        )
        code = main(argv)
        assert code == 0
    finally:
        registry.clear()
