"""Confluence native URL + site config key tests (spec 2026-09-22, A2/A6 support).

Citations must be native Atlassian URLs, never ``kgent://`` (N20). With a
space key the pretty URL renders (empty slug — the server 301s to the slugged
form); without one the id-only ``viewpage.action`` form is used so a broken
link is never constructed from missing data.
"""

from __future__ import annotations

import pytest

from kgent.config.schema import load_config_dict
from kgent.errors import ConfigError
from kgent.skills.urls import native_url


class TestConfluenceNativeUrl:
    def test_pretty_url_with_space_key(self):
        url = native_url(
            "kgent://confluence/4718153",
            "org.atlassian.net",
            space_key="ENG",
        )
        assert url == "https://org.atlassian.net/wiki/spaces/ENG/pages/4718153/"

    def test_id_only_form_without_space_key(self):
        url = native_url("kgent://confluence/4718153", "org.atlassian.net")
        assert url == "https://org.atlassian.net/wiki/pages/viewpage.action?pageId=4718153"

    def test_node_type_kwarg_is_inert_for_confluence(self):
        url = native_url(
            "kgent://confluence/4718153",
            "org.atlassian.net",
            node_type="wiki_node",
            space_key="ENG",
        )
        assert url == "https://org.atlassian.net/wiki/spaces/ENG/pages/4718153/"


class TestSiteConfigKey:
    def test_site_defaults_none(self):
        cfg = load_config_dict(
            {
                "version": 1,
                "backends": {
                    "confluence": {
                        "type": "skill",
                        "skill_name": "confluence-integration",
                    }
                },
            }
        )
        assert cfg.backends["confluence"]["site"] is None

    def test_site_accepted(self):
        cfg = load_config_dict(
            {
                "version": 1,
                "backends": {"confluence": {"type": "skill", "site": "org.atlassian.net"}},
            }
        )
        assert cfg.backends["confluence"]["site"] == "org.atlassian.net"

    def test_site_non_string_rejected(self):
        with pytest.raises(ConfigError, match=r"backends\.confluence\.site"):
            load_config_dict(
                {
                    "version": 1,
                    "backends": {"confluence": {"type": "skill", "site": 42}},
                }
            )
