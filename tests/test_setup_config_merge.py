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
