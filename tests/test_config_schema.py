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
