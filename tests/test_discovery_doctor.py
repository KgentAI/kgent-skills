"""Doctor + discovery tests.

Task 2.3 owns the ``kgent doctor`` section (S54); Task 3.3 adds discovery
tests to this file later. Keep the two sections clearly separated.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# kgent doctor (§2.6, S54)
# ---------------------------------------------------------------------------


def test_s54_doctor_validates_config(tmp_home):
    from kgent.config.validate import doctor

    # Doctor flags invalid trust_zone values in backend specs (S54).
    (tmp_home / "config.yaml").write_text(
        "version: 1\nbackends:\n  lark:\n    type: skill\n    trust_zone: hostile\n"
    )
    findings, code = doctor(tmp_home)
    assert code == 1
    assert any("trust_zone" in f for f in findings)


def test_s54_doctor_healthy(tmp_home):
    from kgent.config.validate import doctor

    (tmp_home / "config.yaml").write_text("version: 1\nbackends: {}\n")
    findings, code = doctor(tmp_home)
    assert code == 0 and findings == []


def test_doctor_missing_config_is_healthy(tmp_home):
    from kgent.config.validate import doctor

    findings, code = doctor(tmp_home)
    assert code == 0 and findings == []


def test_validate_config_rejects_unknown_sensitivity_tier():
    from kgent.config.schema import Config
    from kgent.config.validate import validate_config

    cfg = Config(
        version=1,
        defaults={},
        backends={},
        sensitivity_floors={"meeting_notes": "topsecret"},
    )
    findings = validate_config(cfg)
    assert any("sensitivity_floors.meeting_notes" in f for f in findings)


def test_validate_config_rejects_nested_fallback():
    from kgent.config.schema import Config
    from kgent.config.validate import validate_config

    cfg = Config(
        version=1,
        defaults={},
        backends={
            "lark": {
                "enabled": True,
                "type": "skill",
                "skill_name": "lark-doc",
                "trust_zone": "internal",
                "capabilities": {
                    "document_search": {
                        "features": {"fallback": {"search_by_semantics": "search_by_keywords"}}
                    }
                },
            }
        },
    )
    findings = validate_config(cfg)
    assert any("fallback" in f and "features.fallback" in f for f in findings)


# ---------------------------------------------------------------------------
# kgent config migrate (§2.6)
# ---------------------------------------------------------------------------


def test_migrate_config_version_1_is_noop(tmp_home):
    from kgent.config.migrate import migrate_config

    path = tmp_home / "config.yaml"
    path.write_text("version: 1\nbackends: {}\n")
    migrate_config(path)
    assert path.read_text() == "version: 1\nbackends: {}\n"
    assert list(tmp_home.glob("config.yaml.bak-*")) == []


def test_migrate_config_unknown_version_backs_up_first(tmp_home):
    from kgent.config.migrate import migrate_config

    path = tmp_home / "config.yaml"
    path.write_text("version: 2\nbackends: {}\n")
    migrate_config(path)
    backups = list(tmp_home.glob("config.yaml.bak-*"))
    assert len(backups) == 1
    assert backups[0].read_text() == "version: 2\nbackends: {}\n"
    assert path.read_text() == "version: 2\nbackends: {}\n"


# ---------------------------------------------------------------------------
# Read-only discovery + setup (§2.2, S42, S53, N12)
# ---------------------------------------------------------------------------


def test_s42_discovery_is_read_only(test_world, tmp_home):
    from kgent.capabilities.detect import discover

    report = discover(tmp_home, env={"PATH": "/nonexistent", "HOME": str(tmp_home)})
    assert isinstance(report.backends, dict)
    total_writes = sum(len(b.write_calls) for b in test_world["backends"].values())
    assert total_writes == 0


def test_s53_setup_does_not_prompt_for_auth(tmp_home, monkeypatch):
    from kgent.capabilities.detect import setup

    monkeypatch.setenv("PATH", "/nonexistent")
    report, code = setup(tmp_home)
    assert code == 0
    assert all(b.get("auth") == "deferred" for b in report.backends.values())


def test_s42_discover_skill_manifest_populates_capabilities_read_only(tmp_home):
    import json

    from kgent.capabilities.detect import discover

    skill_dir = tmp_home / ".claude" / "skills" / "lark-doc"
    skill_dir.mkdir(parents=True)
    (skill_dir / "manifest.json").write_text(
        json.dumps(
            {
                "name": "lark-doc",
                "version": "1.2.3",
                "auth": "deferred",
                "capabilities": {
                    "document_storage": {
                        "supported": True,
                        "features": ["create", "read", "update", "delete", "list"],
                    },
                    "document_search": {
                        "supported": True,
                        "features": {
                            "search_by_keywords": True,
                            "search_by_semantics": True,
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    def tree() -> set[str]:
        return {str(p.relative_to(tmp_home)) for p in tmp_home.rglob("*")}

    before = tree()
    report = discover(tmp_home, env={"PATH": "/nonexistent", "HOME": str(tmp_home)})
    assert tree() == before  # S42: strictly read-only, no new files

    lark = report.backends["lark"]
    assert lark["auth"] == "deferred"
    assert lark["found_via"] == "skill"
    assert lark["adapter_name"] == "lark-doc"
    assert lark["version"] == "1.2.3"
    assert lark["capabilities"]["document_storage"]["supported"] is True
    assert lark["capabilities"]["document_search"]["features"]["search_by_semantics"] is True
    assert "unverified" not in lark


def test_n12_discovery_ignores_prose_manifest(tmp_home):
    from kgent.capabilities.detect import discover

    skill_dir = tmp_home / ".claude" / "skills" / "lark-doc"
    skill_dir.mkdir(parents=True)
    (skill_dir / "manifest.json").write_text(
        "<html><body>lark-doc can search documents and store them</body></html>",
        encoding="utf-8",
    )
    report = discover(tmp_home, env={"PATH": "/nonexistent", "HOME": str(tmp_home)})
    lark = report.backends["lark"]
    assert lark["auth"] == "deferred"
    assert lark["found_via"] == "skill"
    assert lark["capabilities"] == {}
    assert "capabilities" in lark["unverified"]


# ---------------------------------------------------------------------------
# Install gate discovery (spec 2026-09-19-install-gate-design.md, D1-D6):
# doctor reports enabled PLATFORM backends whose <backend>-integration skill
# is not installed in any known agent skills dir (hub + mirrors, relative to
# the USER home — the kgent home is ~/.kgent, so user home = home.parent).
# Read-only and fail-closed: an unreadable probe location reads as NOT
# installed. local-fs is exempt (no gate, always installed by the installer).
# ---------------------------------------------------------------------------

_LARK_ENABLED = (
    "version: 1\n"
    "defaults:\n"
    "  workspace_domain: example.test\n"
    "backends:\n"
    "  lark:\n"
    "    enabled: true\n"
    "    type: skill\n"
    "    skill_name: lark-integration\n"
    "    trust_zone: internal\n"
)


def _install_integration_skill(user_home, backend: str, subdir: str = ".agents/skills") -> None:
    skill = user_home / subdir / f"{backend}-integration"
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text("---\nname: probe\n---\nprobe", encoding="utf-8")


def test_d1_installed_integration_skill_is_healthy(tmp_home):
    from kgent.config.validate import doctor

    (tmp_home / "config.yaml").write_text(_LARK_ENABLED, encoding="utf-8")
    _install_integration_skill(tmp_home.parent, "lark")

    findings, code = doctor(tmp_home)

    assert code == 0, findings
    assert not any("lark-integration" in f for f in findings)


def test_d2_missing_integration_skill_is_a_finding(tmp_home):
    from kgent.config.validate import doctor

    (tmp_home / "config.yaml").write_text(_LARK_ENABLED, encoding="utf-8")

    findings, code = doctor(tmp_home)

    assert code == 1
    hits = [f for f in findings if "lark-integration" in f]
    assert hits, f"expected a lark-integration finding, got: {findings}"
    assert any("--sync" in f for f in hits), "the finding must point at the sync command"


def test_d3_any_known_skill_dir_counts(tmp_home):
    from kgent.config.validate import doctor

    (tmp_home / "config.yaml").write_text(_LARK_ENABLED, encoding="utf-8")
    _install_integration_skill(tmp_home.parent, "lark", subdir=".codebuddy/skills")

    findings, code = doctor(tmp_home)

    assert code == 0, findings


def test_d4_local_fs_is_exempt(tmp_home):
    from kgent.config.validate import doctor

    (tmp_home / "config.yaml").write_text(
        "version: 1\n"
        "backends:\n"
        "  local-fs:\n"
        "    enabled: true\n"
        "    type: skill\n"
        "    skill_name: local-fs-integration\n"
        "    trust_zone: internal\n",
        encoding="utf-8",
    )

    findings, code = doctor(tmp_home)

    # local-fs findings may exist (store root etc.) but the integration probe
    # must never flag local-fs — it has no install gate
    assert not any("local-fs-integration is not installed" in f for f in findings), findings


def test_d5_unreadable_probe_location_fails_closed(tmp_home):
    from kgent.config.validate import doctor

    (tmp_home / "config.yaml").write_text(_LARK_ENABLED, encoding="utf-8")
    # ~/.agents exists but is a FILE: probing under it raises - the probe must
    # read NOT installed (fail closed), never crash doctor
    (tmp_home.parent / ".agents").write_text("not a directory", encoding="utf-8")

    findings, code = doctor(tmp_home)

    assert code == 1
    assert any("lark-integration" in f for f in findings), findings


def test_d6_wecom_flagged_not_lark(tmp_home):
    from kgent.config.validate import doctor

    (tmp_home / "config.yaml").write_text(
        "version: 1\n"
        "defaults:\n"
        "  workspace_domain: example.test\n"
        "backends:\n"
        "  lark:\n"
        "    enabled: true\n"
        "    type: skill\n"
        "    skill_name: lark-integration\n"
        "    trust_zone: internal\n"
        "  wecom:\n"
        "    enabled: true\n"
        "    type: skill\n"
        "    skill_name: wecom-integration\n"
        "    trust_zone: external\n",
        encoding="utf-8",
    )
    _install_integration_skill(tmp_home.parent, "lark")

    findings, code = doctor(tmp_home)

    assert code == 1
    assert any("wecom-integration" in f for f in findings), findings
    assert not any("lark-integration is not installed" in f for f in findings), findings


def test_d7_disabled_platform_backend_is_not_probed(tmp_home):
    from kgent.config.validate import doctor

    (tmp_home / "config.yaml").write_text(
        "version: 1\n"
        "defaults:\n"
        "  workspace_domain: example.test\n"
        "backends:\n"
        "  lark:\n"
        "    enabled: true\n"
        "    type: skill\n"
        "    skill_name: lark-integration\n"
        "    trust_zone: internal\n"
        "  dingtalk:\n"
        "    enabled: false\n"
        "    type: skill\n"
        "    skill_name: dingtalk-integration\n"
        "    trust_zone: external\n",
        encoding="utf-8",
    )
    _install_integration_skill(tmp_home.parent, "lark")
    # dingtalk is DISABLED: no probe, no finding, even though its skill is absent
    findings, code = doctor(tmp_home)

    assert code == 0, findings
    assert not any("dingtalk-integration" in f for f in findings), findings


# ---------------------------------------------------------------------------
# Install gate discoverability (spec B7/B8): setup epilogue + lane prose.
# ---------------------------------------------------------------------------


def test_e1_setup_prints_sync_epilogue(tmp_home, monkeypatch, capsys):
    """`kgent setup` ends with a hint that ties enabled backends to --sync."""
    import argparse

    from kgent.cli import _cmd_setup

    monkeypatch.setenv("PATH", "/nonexistent")
    code = _cmd_setup(argparse.Namespace(json=False))
    out = capsys.readouterr().out

    assert code == 0
    assert "--sync" in out, f"setup epilogue must mention --sync, got: {out}"


def test_e2_lane_skills_carry_the_doctor_hint():
    """Each lane skill's degrade guidance names `kgent doctor` and --sync."""
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    for lane in ("query-knowledge", "ingest-knowledge", "wiki-setup"):
        text = (repo / "skills" / lane / "SKILL.md").read_text(encoding="utf-8")
        assert "kgent doctor" in text, f"{lane} must point at kgent doctor"
        assert "install-skills.sh --sync" in text, f"{lane} must point at the sync command"
