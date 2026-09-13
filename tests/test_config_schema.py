"""Config schema + validation tests (Task 2.1, Appendix C)."""

import pytest

from kgent.config.schema import load_config_dict
from kgent.errors import ConfigError


def test_s20_unknown_top_level_key_rejected():
    with pytest.raises(ConfigError, match="hook_cmd"):
        load_config_dict({"version": 1, "hook_cmd": "evil"})


def test_s21_future_version_rejected_with_migrate_hint():
    with pytest.raises(ConfigError, match="kgent config migrate"):
        load_config_dict({"version": 2, "backends": {}})


def test_defaults_applied():
    cfg = load_config_dict({"version": 1, "backends": {}})
    assert cfg.defaults["routing_mode"] == "configured"
    assert cfg.audit["redact_queries"] is True
    assert cfg.journal["encrypt"] is False


def test_minimal_config_sections_defaulted():
    cfg = load_config_dict({"version": 1, "backends": {}})
    assert cfg.audit["redact_queries"] is True
    assert cfg.conflict_resolution["require_confirmation"] is True
    assert cfg.journal["encrypt"] is False


def test_routing_mode_invalid_rejected():
    with pytest.raises(ConfigError, match="routing_mode"):
        load_config_dict({"version": 1, "backends": {}, "defaults": {"routing_mode": "magic"}})


def test_backend_type_invalid_rejected():
    with pytest.raises(ConfigError, match=r"backends\.lark\.type"):
        load_config_dict({"version": 1, "backends": {"lark": {"type": "weird"}}})


def test_backend_trust_zone_invalid_rejected():
    with pytest.raises(ConfigError, match=r"backends\.lark\.trust_zone"):
        load_config_dict(
            {"version": 1, "backends": {"lark": {"type": "skill", "trust_zone": "north"}}}
        )


def test_search_seconds_nonpositive_rejected():
    with pytest.raises(ConfigError, match=r"timeouts\.search_seconds"):
        load_config_dict(
            {"version": 1, "backends": {}, "defaults": {"timeouts": {"search_seconds": 0}}}
        )


def test_max_parallel_backends_below_one_rejected():
    with pytest.raises(ConfigError, match=r"concurrency\.max_parallel_backends"):
        load_config_dict(
            {
                "version": 1,
                "backends": {},
                "defaults": {"concurrency": {"max_parallel_backends": 0}},
            }
        )


def test_local_fs_defaults_mode_git_backed_remote_none():
    cfg = load_config_dict({"version": 1, "backends": {"local-fs": {"type": "skill"}}})
    entry = cfg.backends["local-fs"]
    assert entry["mode"] == "git-backed"
    assert entry["remote"] is None


def test_mode_enum_rejects_auto_and_other_values():
    with pytest.raises(ConfigError, match=r"backends\.local-fs\.mode.*git-backed, snapshot"):
        load_config_dict({"version": 1, "backends": {"local-fs": {"type": "skill", "mode": "auto"}}})
    with pytest.raises(ConfigError, match=r"backends\.local-fs\.mode"):
        load_config_dict({"version": 1, "backends": {"local-fs": {"type": "skill", "mode": "git-synced"}}})


def test_mode_accepts_both_legal_values():
    for mode in ("git-backed", "snapshot"):
        cfg = load_config_dict({"version": 1, "backends": {"local-fs": {"type": "skill", "mode": mode}}})
        assert cfg.backends["local-fs"]["mode"] == mode


def test_remote_must_be_string_or_null():
    with pytest.raises(ConfigError, match=r"backends\.local-fs\.remote"):
        load_config_dict({"version": 1, "backends": {"local-fs": {"type": "skill", "remote": 42}}})
    cfg = load_config_dict(
        {
            "version": 1,
            "backends": {
                "local-fs": {
                    "type": "skill",
                    "remote": "https://git.example.com/team/store.git",
                }
            },
        }
    )
    assert cfg.backends["local-fs"]["remote"] == "https://git.example.com/team/store.git"


def test_existing_backends_unaffected_by_mode_remote_keys():
    cfg = load_config_dict(
        {"version": 1, "backends": {"lark": {"enabled": True, "type": "skill", "trust_zone": "internal"}}}
    )
    entry = cfg.backends["lark"]
    assert entry["mode"] == "git-backed"  # default present, harmless for platform backends
    assert entry["remote"] is None
    assert entry["trust_zone"] == "internal"
    assert entry["enabled"] is True
