"""``kgent setup`` config write-policy tests (spec 2026-09-02-setup-config-overwrite).

All tests inject discovery-report backend dicts directly — no real probing.
"""

from __future__ import annotations

import pytest

from kgent.capabilities.setup_config import merge_backends
from kgent.errors import ConfigError

SKILL_ENTRY = {
    "auth": "deferred",
    "capabilities": {},
    "found_via": "skill",
    "adapter_name": "lark-doc",
}
CLI_ENTRY = {
    "auth": "deferred",
    "capabilities": {},
    "found_via": "cli",
    "adapter_name": "dingtalk-cli",
}


def test_merge_appends_new_backends_disabled():
    merged = merge_backends({}, {"lark": SKILL_ENTRY})
    assert merged["lark"] == {
        "enabled": False,
        "type": "skill",
        "skill_name": "lark-doc",
        "trust_zone": "external",
    }


def test_merge_preserves_user_enabled_and_fills_missing_keys():
    merged = merge_backends({"lark": {"enabled": True}}, {"lark": SKILL_ENTRY})
    assert merged["lark"]["enabled"] is True
    assert merged["lark"]["type"] == "skill"
    assert merged["lark"]["skill_name"] == "lark-doc"
    assert merged["lark"]["trust_zone"] == "external"


def test_merge_user_keys_win_over_report():
    merged = merge_backends(
        {"lark": {"enabled": True, "skill_name": "my-lark"}}, {"lark": SKILL_ENTRY}
    )
    assert merged["lark"]["skill_name"] == "my-lark"
    assert merged["lark"]["enabled"] is True


def test_merge_keeps_undiscovered_backends():
    existing = {"wecom": {"enabled": True, "type": "cli"}}
    assert merge_backends(existing, {}) == existing


def test_merge_keeps_non_mapping_entry_verbatim():
    merged = merge_backends({"lark": "hand-written"}, {"lark": SKILL_ENTRY})
    assert merged["lark"] == "hand-written"


def test_merge_does_not_mutate_inputs():
    existing = {"lark": {"enabled": True}}
    merge_backends(existing, {"lark": SKILL_ENTRY})
    assert existing == {"lark": {"enabled": True}}


EXPECTED_FRESH = (
    "version: 1\n"
    "backends:\n"
    "  dingtalk:\n"
    "    enabled: false\n"
    "    type: cli\n"
    "    cli_name: dingtalk-cli\n"
    "    trust_zone: external\n"
    "  lark:\n"
    "    enabled: false\n"
    "    type: skill\n"
    "    skill_name: lark-doc\n"
    "    trust_zone: external\n"
)

EXISTING_USER_CONFIG = (
    "version: 1\n"
    "defaults:\n"
    "  workspace_domain: acme.example.com\n"
    "  timeouts:\n"
    "    search_seconds: 10\n"
    "backends:\n"
    "  lark:\n"
    "    enabled: true\n"
    "    type: skill\n"
    "    skill_name: lark-doc\n"
    "    trust_zone: external\n"
)


def test_write_fresh_home_matches_generated_format(tmp_path):
    from kgent.capabilities.setup_config import write_setup_config

    home = tmp_path / "h"
    write_setup_config(home, {"lark": SKILL_ENTRY, "dingtalk": CLI_ENTRY})
    assert (home / "config.yaml").read_text(encoding="utf-8") == EXPECTED_FRESH


def test_write_fresh_empty_report_matches_generated_format(tmp_path):
    from kgent.capabilities.setup_config import write_setup_config

    home = tmp_path / "h"
    write_setup_config(home, {})
    assert (home / "config.yaml").read_text(encoding="utf-8") == "version: 1\nbackends: {}\n"


def test_write_preserves_enabled_and_defaults_on_rerun(tmp_path):
    from kgent.capabilities.setup_config import write_setup_config
    from kgent.config import _yaml

    home = tmp_path / "h"
    home.mkdir()
    (home / "config.yaml").write_text(EXISTING_USER_CONFIG, encoding="utf-8")
    write_setup_config(home, {"lark": SKILL_ENTRY, "dingtalk": CLI_ENTRY})
    raw = _yaml.parse((home / "config.yaml").read_text(encoding="utf-8"))
    assert raw["backends"]["lark"]["enabled"] is True
    assert raw["defaults"]["workspace_domain"] == "acme.example.com"
    assert raw["defaults"]["timeouts"]["search_seconds"] == 10
    assert raw["backends"]["dingtalk"] == {
        "enabled": False,
        "type": "cli",
        "cli_name": "dingtalk-cli",
        "trust_zone": "external",
    }


def test_write_refuses_unparseable_config_without_touching_it(tmp_path):
    from kgent.capabilities.setup_config import write_setup_config

    home = tmp_path / "h"
    home.mkdir()
    path = home / "config.yaml"
    broken = "version: 1\n\ttab-indented: yes\n"
    path.write_text(broken, encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        write_setup_config(home, {"lark": SKILL_ENTRY})
    assert "kgent setup" in str(excinfo.value)
    assert path.read_text(encoding="utf-8") == broken
    assert list(home.glob("config.yaml.bak-*")) == []


def test_write_refuses_non_mapping_config(tmp_path):
    from kgent.capabilities.setup_config import write_setup_config

    home = tmp_path / "h"
    home.mkdir()
    path = home / "config.yaml"
    path.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        write_setup_config(home, {"lark": SKILL_ENTRY})
    assert path.read_text(encoding="utf-8") == "- just\n- a list\n"


def test_write_backs_up_existing_config_before_rewrite(tmp_path):
    from kgent.capabilities.setup_config import write_setup_config

    home = tmp_path / "h"
    home.mkdir()
    (home / "config.yaml").write_text(EXISTING_USER_CONFIG, encoding="utf-8")
    write_setup_config(home, {"lark": SKILL_ENTRY})
    backups = list(home.glob("config.yaml.bak-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == EXISTING_USER_CONFIG


def test_write_roundtrips_lists_and_scalars(tmp_path):
    from kgent.capabilities.setup_config import write_setup_config
    from kgent.config import _yaml

    home = tmp_path / "h"
    home.mkdir()
    (home / "config.yaml").write_text(
        "version: 1\n"
        "defaults:\n"
        "  default_backends: [lark, wecom]\n"
        "  empty: {}\n"
        "  note: '123'\n",
        encoding="utf-8",
    )
    write_setup_config(home, {})
    raw = _yaml.parse((home / "config.yaml").read_text(encoding="utf-8"))
    assert raw["defaults"]["default_backends"] == ["lark", "wecom"]
    assert raw["defaults"]["empty"] == {}
    assert raw["defaults"]["note"] == "123"
