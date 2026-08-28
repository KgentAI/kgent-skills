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

    (tmp_home / "config.yaml").write_text(
        "version: 1\nbackends:\n  lark:\n    skill_name: evil-skill\n"
    )
    findings, code = doctor(tmp_home)
    assert code == 1
    assert any("backends.lark.skill_name" in f for f in findings)


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
