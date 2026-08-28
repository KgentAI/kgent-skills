from __future__ import annotations

import pytest

from kgent.config.schema import Config
from tests.fakes.fake_backend import FakeBackend


@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    home = tmp_path / ".kgent"
    home.mkdir()
    monkeypatch.setenv("KGENT_HOME", str(home))
    return home


def _full_caps() -> dict:
    return {
        "document_storage": {
            "supported": True,
            "features": ["create", "read", "update", "delete", "list", "archive", "unarchive"],
        },
        "document_search": {
            "supported": True,
            "features": {
                "search_by_keywords": True,
                "search_by_semantics": True,
                "search_hybrid": True,
            },
            "limits": {"max_results": 100, "max_content_bytes": 2_000_000},
        },
        "approval_flow": {
            "supported": True,
            "features": ["request_approval", "check_status", "execute_approved"],
        },
    }


def _kw_caps() -> dict:
    caps = _full_caps()
    caps["document_search"]["features"] = {
        "search_by_keywords": True,
        "search_by_semantics": False,
        "search_hybrid": False,
    }
    caps["approval_flow"]["supported"] = False
    caps["document_search"]["limits"] = {"max_results": 50}
    return caps


@pytest.fixture
def test_world(tmp_home):
    """Standard test world (acceptance §2): lark internal full; dingtalk/wecom external keyword-only."""
    backends = {
        "lark": FakeBackend("lark", "internal", _full_caps(), owner="alice"),
        "dingtalk": FakeBackend("dingtalk", "external", _kw_caps()),
        "wecom": FakeBackend("wecom", "external", _kw_caps()),
    }
    config = Config(
        version=1,
        defaults={
            "routing_mode": "configured",
            "default_backends": ["lark"],
            "approval_ttl_hours": 24,
            "timeouts": {"search_seconds": 10, "write_seconds": 30},
            "concurrency": {"max_parallel_backends": 4},
        },
        backends={
            "lark": {
                "enabled": True,
                "type": "skill",
                "skill_name": "lark-doc",
                "trust_zone": "internal",
            },
            "dingtalk": {
                "enabled": True,
                "type": "cli",
                "cli_name": "dingtalk-cli",
                "trust_zone": "external",
            },
            "wecom": {
                "enabled": True,
                "type": "cli",
                "cli_name": "wecom-cli",
                "trust_zone": "external",
            },
        },
        content_type_mapping={
            "meeting_notes": "lark",
            "team_wiki": "lark",
            "external_docs": "dingtalk",
            "default": "lark",
        },
    )
    return {"backends": backends, "config": config, "user": "alice"}
