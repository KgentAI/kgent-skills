"""Config precedence + trust model tests (Task 2.2, §2.3)."""

import pytest

from kgent.config.loader import FORBIDDEN_PROJECT_KEYS, load_effective_config
from kgent.errors import ConfigError


def test_s17_untrusted_project_config_ignored(tmp_home, tmp_path):
    proj = tmp_path / "D"
    proj.mkdir()
    (proj / ".kgent-config.yaml").write_text(
        "version: 1\ndefaults:\n  default_backends: [dingtalk]\n"
    )
    global_path = tmp_home / "config.yaml"
    global_path.write_text("version: 1\ndefaults:\n  default_backends: [lark]\n")
    cfg, warnings = load_effective_config(global_path, proj, {})
    assert cfg.defaults["default_backends"] == ["lark"]
    assert any(".kgent-config.yaml (untrusted directory)" in w for w in warnings)


def test_s18_forbidden_key_rejected_by_name(tmp_home, tmp_path):
    assert "backends.lark.skill_name" in FORBIDDEN_PROJECT_KEYS
    # trusted dir with forbidden key
    proj = tmp_path / "D"
    proj.mkdir()
    (proj / ".kgent-config.yaml").write_text(
        "version: 1\nbackends:\n  lark:\n    skill_name: evil-skill\n"
    )
    # trust the directory first (via trusted.py API)
    from kgent.config.trusted import is_trusted, trust_directory  # noqa: F401

    trust_directory(proj, tmp_home / "trusted.json")
    with pytest.raises(ConfigError, match="backends.lark.skill_name"):
        load_effective_config(tmp_home / "config.yaml", proj, {})


def test_s19_trusted_routing_overrides_work(tmp_home, tmp_path):
    proj = tmp_path / "D"
    proj.mkdir()
    (proj / ".kgent-config.yaml").write_text(
        "version: 1\ncontent_type_mapping:\n  meeting_notes: dingtalk\n"
    )
    from kgent.config.trusted import trust_directory

    trust_directory(proj, tmp_home / "trusted.json")
    (tmp_home / "config.yaml").write_text("version: 1\ndefaults:\n  default_backends: [lark]\n")
    cfg, _ = load_effective_config(tmp_home / "config.yaml", proj, {})
    assert cfg.content_type_mapping["meeting_notes"] == "dingtalk"


def test_content_type_mapping_unknown_backend_rejected(tmp_home, tmp_path):
    """§2.3: project content_type_mapping must target declared backends."""
    proj = tmp_path / "D"
    proj.mkdir()
    (proj / ".kgent-config.yaml").write_text(
        "version: 1\ncontent_type_mapping:\n  meeting_notes: dingtalk\n"
    )
    from kgent.config.trusted import trust_directory

    trust_directory(proj, tmp_home / "trusted.json")
    (tmp_home / "config.yaml").write_text(
        "version: 1\nbackends:\n  lark:\n    type: skill\n    skill_name: lark-doc\n"
    )
    with pytest.raises(ConfigError, match="unknown backend"):
        load_effective_config(tmp_home / "config.yaml", proj, {})


def test_cli_overrides_win(tmp_home, tmp_path):
    """§2.3 precedence: CLI flags beat global config."""
    (tmp_home / "config.yaml").write_text("version: 1\ndefaults:\n  default_backends: [lark]\n")
    cfg, _ = load_effective_config(
        tmp_home / "config.yaml", tmp_path, {"defaults": {"default_backends": ["wecom"]}}
    )
    assert cfg.defaults["default_backends"] == ["wecom"]
