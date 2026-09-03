"""Sensitivity tier + zone rule tests (§2.5, S13–S16)."""

import pytest

from kgent.errors import PolicyError
from kgent.router.sensitivity import (
    analyze_sensitivity,
    enforce_floor,
    enforce_zone,
    warn_query_leakage,
)


def test_s13_confidential_to_external_rejected():
    with pytest.raises(
        PolicyError,
        match="tier 'confidential' cannot be written to external-zone backend 'dingtalk'",
    ):
        enforce_zone("confidential", "external", "dingtalk")


def test_s14_uncertain_raises_to_higher():
    tier, _conf, prov = analyze_sensitivity("x", confidence=0.4)  # between internal & confidential
    assert tier == "confidential" and "uncertain, raised" in prov


def test_s15_floor_applied():
    tier, note = enforce_floor("internal", "meeting_notes", {"meeting_notes": "confidential"})
    assert tier == "confidential" and "floor applied: meeting_notes" in note


def test_s16_query_leak_warning_once():
    session = set()
    assert warn_query_leakage([("lark", "internal"), ("dingtalk", "external")], session) != []
    assert warn_query_leakage([("lark", "internal"), ("dingtalk", "external")], session) == []


def test_companion_zone_and_leak_safe_paths():
    # confidential → internal zone is the only allowed destination: no raise.
    enforce_zone("confidential", "internal", "lark")
    # all-internal targets → no leak warning.
    session = set()
    assert warn_query_leakage([("lark", "internal"), ("wecom", "internal")], session) == []
