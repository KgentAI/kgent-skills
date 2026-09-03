"""``kgent config set-workspace-domain`` tests (auto-discover + surgical write).

Covers the 2026-09-02 learning: the workspace domain is discoverable from a
``lark-cli drive +search`` probe (``result_meta.url`` host) when
``defaults.workspace_domain`` is absent from ``~/.kgent/config.yaml`` — and
the write must touch only that one key (never rewrite the whole file).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from kgent.cli import main
from kgent.config import workspace_domain as wd
from kgent.config.schema import load_config_dict
from kgent.errors import ConfigError


# ---------------------------------------------------------------------------
# 1. probe result parsing (pure function, fixture-driven — no real lark-cli)
# ---------------------------------------------------------------------------


def _search_payload(url: str | None) -> dict[str, Any]:
    results = [] if url is None else [{"result_meta": {"url": url, "token": "tok"}}]
    return {"ok": True, "data": {"results": results, "has_more": False}}


def test_extract_domain_takes_host_from_first_result_url():
    payload = _search_payload("https://hjpiui0m07o0.jp.larksuite.com/wiki/TokEn")
    assert wd.extract_domain(payload) == "hjpiui0m07o0.jp.larksuite.com"


def test_extract_domain_skips_placeholder_and_uses_next_hit():
    payload: dict[str, Any] = {
        "ok": True,
        "data": {
            "results": [
                {"result_meta": {"url": "https://www.larksuite.com/docx/TokEn"}},
                {"result_meta": {"url": "https://real.example.larksuite.com/wiki/TokEn"}},
            ]
        },
    }
    assert wd.extract_domain(payload) == "real.example.larksuite.com"


def test_extract_domain_no_results_is_none():
    assert wd.extract_domain(_search_payload(None)) is None
    assert wd.extract_domain({"ok": False}) is None


# ---------------------------------------------------------------------------
# 2. domain validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "hjpiui0m07o0.jp.larksuite.com",
        "mycompany.feishu.cn",
        "acme.larksuite.com",
    ],
)
def test_validate_domain_accepts_real_hosts(host):
    assert wd.validate_domain(host) == host


@pytest.mark.parametrize(
    "bad",
    [
        "www.larksuite.com",  # generic placeholder, not a tenant
        "https://acme.larksuite.com",  # scheme
        "acme.larksuite.com/wiki/x",  # path
        "no-dot",
        "",
        "under_score.larksuite.com",
    ],
)
def test_validate_domain_rejects_placeholder_and_malformed(bad):
    with pytest.raises(ConfigError):
        wd.validate_domain(bad)


# ---------------------------------------------------------------------------
# 3. surgical config write — only `defaults.workspace_domain` changes
# ---------------------------------------------------------------------------


def test_set_adds_key_under_existing_defaults_and_preserves_rest(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(
        "version: 1\n"
        "defaults:\n"
        "  routing_mode: configured\n"
        "  timeouts:\n"
        "    search_seconds: 10\n"
        "backends:\n"
        "  lark:\n"
        "    enabled: true\n"
        "    type: skill\n"
        "    skill_name: lark-approval\n",
        encoding="utf-8",
    )
    old, new = wd.set_workspace_domain(config, "acme.jp.larksuite.com")
    assert old is None and new == "acme.jp.larksuite.com"

    text = config.read_text(encoding="utf-8")
    assert "workspace_domain: acme.jp.larksuite.com" in text
    assert "enabled: true" in text  # user's hand edit survives
    raw: dict[str, Any] = _yaml_parse(config)
    assert raw["defaults"]["routing_mode"] == "configured"
    assert raw["defaults"]["timeouts"]["search_seconds"] == 10
    assert raw["backends"]["lark"]["enabled"] is True


def test_set_replaces_existing_value(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(
        "version: 1\ndefaults:\n  workspace_domain: old.example.com\n",
        encoding="utf-8",
    )
    old, new = wd.set_workspace_domain(config, "new.example.com")
    assert old == "old.example.com" and new == "new.example.com"
    raw = _yaml_parse(config)
    assert raw["defaults"]["workspace_domain"] == "new.example.com"


def test_set_appends_defaults_block_when_missing(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("version: 1\nbackends: {}\n", encoding="utf-8")
    wd.set_workspace_domain(config, "acme.larksuite.com")
    raw = _yaml_parse(config)
    assert raw["defaults"]["workspace_domain"] == "acme.larksuite.com"
    assert raw["backends"] == {}


def test_set_refuses_to_touch_unparseable_config(tmp_path):
    config = tmp_path / "config.yaml"
    original = "version: 1\nbackends:\n\tlark: bad tab\n"
    config.write_text(original, encoding="utf-8")
    with pytest.raises(ConfigError):
        wd.set_workspace_domain(config, "acme.larksuite.com")
    assert config.read_text(encoding="utf-8") == original  # unchanged


def _yaml_parse(config):  # local helper keeps tests terse
    from kgent.config import _yaml

    return _yaml.parse(config.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 3b. probe execution — resolves the executable before spawning (Windows shims)
# ---------------------------------------------------------------------------


def test_probe_uses_resolved_executable_and_parses_payload(monkeypatch):
    from kgent.adapters.cli_adapter import SubprocessResult

    captured: dict[str, list[str]] = {}

    def fake_run_cli(argv, timeout, **_kw):
        captured["argv"] = argv
        return SubprocessResult(
            0, json.dumps(_search_payload("https://probed.example.com/wiki/x")), ""
        )

    monkeypatch.setattr(wd, "run_cli", fake_run_cli)
    result = wd.probe_workspace_domain(resolve=lambda name: "C:/fake/lark-cli.CMD")
    assert result.domain == "probed.example.com"
    assert captured["argv"][0] == "C:/fake/lark-cli.CMD"


def test_probe_missing_cli_reports_not_found(monkeypatch):
    monkeypatch.setattr(wd, "run_cli", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("spawned")))
    result = wd.probe_workspace_domain(resolve=lambda _name: None)
    assert result.domain is None
    assert "not found" in result.detail


# ---------------------------------------------------------------------------
# 4. auto-discover flow (probe injected — no subprocess in unit tests)
# ---------------------------------------------------------------------------


class _FakeProbe:
    def __init__(self, result: wd.ProbeResult) -> None:
        self.result = result
        self.calls = 0

    def __call__(self) -> wd.ProbeResult:
        self.calls += 1
        return self.result


def test_discover_writes_probed_domain(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("version: 1\nbackends:\n  lark:\n    enabled: true\n", encoding="utf-8")
    probe = _FakeProbe(wd.ProbeResult(domain="probed.larksuite.com", detail=""))
    old, new = wd.discover_and_set(config, probe)
    assert old is None and new == "probed.larksuite.com"
    assert probe.calls == 1


def test_discover_without_results_raises_with_domain_hint(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("version: 1\n", encoding="utf-8")
    probe = _FakeProbe(wd.ProbeResult(domain=None, detail="no results"))
    with pytest.raises(ConfigError, match="--domain"):
        wd.discover_and_set(config, probe)


def test_discover_placeholder_result_rejected(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("version: 1\n", encoding="utf-8")
    probe = _FakeProbe(wd.ProbeResult(domain="www.larksuite.com", detail=""))
    with pytest.raises(ConfigError, match="--domain"):
        wd.discover_and_set(config, probe)
    assert "workspace_domain" not in config.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 5. validate/doctor finding — missing domain on an enabled lark backend
# ---------------------------------------------------------------------------


def _config_with(**kwargs: Any):
    raw: dict[str, Any] = {"version": 1, "backends": kwargs.get("backends", {})}
    if "defaults" in kwargs:
        raw["defaults"] = kwargs["defaults"]
    return load_config_dict(raw)


def test_validate_flags_missing_workspace_domain_for_enabled_lark():
    cfg = _config_with(backends={"lark": {"enabled": True, "type": "skill"}})
    findings = _validate_findings(cfg)
    assert any("set-workspace-domain" in f for f in findings)


def test_validate_quiet_when_domain_set():
    cfg = _config_with(
        backends={"lark": {"enabled": True, "type": "skill"}},
        defaults={"workspace_domain": "acme.larksuite.com"},
    )
    assert not any("workspace_domain" in f for f in _validate_findings(cfg))


def test_validate_quiet_when_lark_disabled_or_absent():
    disabled = _config_with(backends={"lark": {"enabled": False, "type": "skill"}})
    assert not any("workspace_domain" in f for f in _validate_findings(disabled))
    absent = _config_with()
    assert not any("workspace_domain" in f for f in _validate_findings(absent))


def _validate_findings(cfg):
    from kgent.config.validate import validate_config

    return validate_config(cfg)


# ---------------------------------------------------------------------------
# 6. CLI end-to-end (explicit --domain path; no subprocess)
# ---------------------------------------------------------------------------


def test_cli_set_workspace_domain_explicit(tmp_home, capsys):
    (tmp_home / "config.yaml").write_text(
        "version: 1\nbackends:\n  lark:\n    enabled: true\n", encoding="utf-8"
    )
    rc = main(
        ["config", "set-workspace-domain", "--domain", "acme.jp.larksuite.com", "--json"]
    )
    assert rc == 0
    raw = json.loads(capsys.readouterr().out)
    assert raw["ok"] is True
    assert raw["workspace_domain"] == "acme.jp.larksuite.com"
    assert raw["previous"] is None


def test_cli_set_workspace_domain_rejects_bad_domain(tmp_home, capsys):
    (tmp_home / "config.yaml").write_text("version: 1\n", encoding="utf-8")
    rc = main(
        ["config", "set-workspace-domain", "--domain", "www.larksuite.com", "--json"]
    )
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False


def test_cli_set_workspace_domain_missing_config_is_clean_error(tmp_home, capsys):
    rc = main(
        ["config", "set-workspace-domain", "--domain", "acme.larksuite.com", "--json"]
    )
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "not found" in payload["error"]
