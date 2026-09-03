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
