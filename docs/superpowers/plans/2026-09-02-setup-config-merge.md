# `kgent setup` config merge-on-rerun Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `kgent setup` merge an existing `~/.kgent/config.yaml` instead of
silently overwriting it, refuse to touch an unparseable config, and write a
timestamped backup before any rewrite.

**Architecture:** New module `kgent.capabilities.setup_config` owns the whole
write policy (merge → dump → backup → atomic-ish rewrite); `detect.setup` just
hands it the discovery report's backend dict. One code path serves both
fresh generation and rerun: a generic YAML-subset emitter (`_dump`, the inverse
of `kgent.config._yaml.parse`) renders the merged document, and the
fresh-generation output is byte-identical to today's `_emit_config`.

**Tech Stack:** Python ≥3.11, stdlib only (project has zero runtime deps);
pytest, ruff (line-length 100), mypy `strict`.

**Spec:** `specs/2026-09-02-setup-config-overwrite.md`

## Global Constraints

- Discovery stays strictly read-only (§2.2/S42/N12) — this change touches only
  the write policy; no new probes. (Spec: 范围外)
- Never `O_TRUNC` a config that fails to parse — refuse with `ConfigError`
  naming the file and the next step (Spec acceptance 3).
- Write `config.yaml.bak-<ts>` before any rewrite of an existing config
  (Spec acceptance 4). Timestamp convention matches `kgent.config.migrate`:
  `int(time.time())`. Fresh creation writes no backup.
- Fresh-generation output unchanged byte-for-byte (Spec acceptance 1 regression).
- Merge rules (Spec 方案 A, shallow): backend entries keep the user's keys
  verbatim and gain only missing keys from the report; new backends appended
  with `enabled: false`; configured-but-undiscovered backends kept;
  non-mapping entries kept verbatim; every non-backend top-level section
  (`defaults:`, …) preserved as parsed.
- No prompts; `setup()` still returns `(report, 0)` on success; refusal raises
  `ConfigError` (exit 1 via the CLI's `KgentError` handler, `cli.py:1091`).
- Tests are hermetic: `tmp_path`/`tmp_home` fixtures with injected backend
  dicts — no real environment discovery (Spec acceptance 5).
- Known trade-off (document in module docstring + PR): merging preserves all
  values but not comments (parse → re-dump); the backup retains original bytes.

## Design decision: doctor finding skipped

The spec's recommendation mentions an optional `kgent doctor` finding for
`config.yaml.bak-*` (仅提示，不强求). It is **skipped**: `doctor`'s contract
maps any finding to exit 1 (`validate.py:134`), and after this change every
setup rerun leaves a backup — the finding would make doctor permanently
"unhealthy" for anyone who reran setup once. Revisit only if doctor grows a
non-failing "info" severity.

---

### Task 1: `merge_backends` — pure merge layer

**Files:**
- Create: `src/kgent/capabilities/setup_config.py`
- Test: `tests/test_setup_config_merge.py` (new)

**Interfaces:**
- Consumes: nothing (pure function).
- Produces: `merge_backends(existing: dict[str, Any], discovered: dict[str, dict[str, Any]]) -> dict[str, Any]`
  — used by Task 3's `write_setup_config`. `existing`/`discovered` are the
  `backends` sections (config side / discovery-report side).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_setup_config_merge.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_setup_config_merge.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'kgent.capabilities.setup_config'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/kgent/capabilities/setup_config.py
"""``kgent setup`` config.yaml write policy: merge, back up, never clobber.

Rerun semantics (spec specs/2026-09-02-setup-config-overwrite.md): ``setup``
is repeatable. When ``config.yaml`` already exists it is merged, not replaced:

- backend entries the user already has keep their keys verbatim (notably
  ``enabled: true``); only keys absent from the entry are filled in from this
  discovery report (shallow, top-level only);
- newly discovered backends are appended with ``enabled: false``;
- configured-but-undiscovered backends are kept, as are non-mapping entries;
- every non-backend section (``defaults:``, ``content_type_mapping:``, …) is
  preserved as parsed.

Two safety rails: an unparseable existing config aborts with
:class:`~kgent.errors.ConfigError` *before* any write (never truncate what we
cannot read back), and any rewrite of an existing file first writes a
timestamped ``config.yaml.bak-<ts>`` copy (same convention as
:mod:`kgent.config.migrate`). Values survive merging; comments do not — the
backup retains the original bytes.
"""

from __future__ import annotations

from typing import Any

__all__ = ["merge_backends"]


def merge_backends(
    existing: dict[str, Any], discovered: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Merge a discovery report into the config's ``backends`` section.

    Existing entries win: kept verbatim (shallow, top-level only) and padded
    with report-derived keys they lack. New backends are appended all-disabled.
    """
    result: dict[str, Any] = {}
    for name in sorted(set(existing) | set(discovered)):
        current = existing.get(name)
        report_entry = discovered.get(name)
        if not isinstance(current, dict) or report_entry is None:
            result[name] = current
            continue
        entry = _config_entry(report_entry)
        entry.update(current)
        result[name] = entry
    return result


def _config_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Convert a discovery entry to its config.yaml shape (all-disabled)."""
    via = entry.get("found_via")
    btype = "mcp" if via == "mcp" else "cli" if via == "cli" else "skill"
    cfg: dict[str, Any] = {"enabled": False, "type": btype}
    if btype in ("skill", "cli") and entry.get("adapter_name"):
        key = "skill_name" if btype == "skill" else "cli_name"
        cfg[key] = str(entry["adapter_name"])
    elif btype == "mcp" and entry.get("mcp_url"):
        cfg["mcp_url"] = str(entry["mcp_url"])
    cfg["trust_zone"] = "external"
    return cfg
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_setup_config_merge.py -v`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add src/kgent/capabilities/setup_config.py tests/test_setup_config_merge.py
git commit -m "feat: add merge_backends for setup config rerun policy"
```

---

### Task 2: `write_setup_config` — fresh path, merge path, refusal, backup

**Files:**
- Modify: `src/kgent/capabilities/setup_config.py`
- Test: `tests/test_setup_config_merge.py`

**Interfaces:**
- Consumes: `merge_backends` (Task 1); `kgent.config._yaml.parse`;
  `kgent.errors.ConfigError`.
- Produces: `write_setup_config(home: Path, backends: dict[str, dict[str, Any]]) -> None`
  — Task 3 wires this into `detect.setup`. Also produces the private
  `_dump(doc: dict[str, Any]) -> str` YAML-subset emitter.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_setup_config_merge.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_setup_config_merge.py -v`
Expected: new tests FAIL with `ImportError: cannot import name 'write_setup_config'`

- [ ] **Step 3: Write minimal implementation**

Replace the whole of `setup_config.py` with the Task 1 content **plus**:

```python
import os
import time
from pathlib import Path

from kgent.config import _yaml
from kgent.errors import ConfigError

__all__ = ["merge_backends", "write_setup_config"]


def write_setup_config(home: Path, backends: dict[str, dict[str, Any]]) -> None:
    """Write ``<home>/config.yaml`` for ``kgent setup`` (merge-on-rerun).

    ``backends`` is a discovery report's backend mapping
    (:func:`kgent.capabilities.detect.discover`). No existing config: generate
    the standard all-disabled one. Existing config: parse, merge, back up,
    rewrite. Unparseable existing config: raise :class:`ConfigError`, leave
    the file untouched.
    """
    home = Path(home)
    created = not home.exists()
    home.mkdir(parents=True, exist_ok=True)
    if created:
        os.chmod(home, 0o700)
    path = home / "config.yaml"

    if not path.exists():
        doc: dict[str, Any] = {"version": 1, "backends": merge_backends({}, backends)}
        text = _dump(doc)
    else:
        existing_text = path.read_text(encoding="utf-8")
        existing = _parse_existing(existing_text)
        doc = dict(existing)
        doc["version"] = existing.get("version", 1)
        doc["backends"] = merge_backends(
            section if isinstance(section := existing.get("backends"), dict) else {},
            backends,
        )
        text = _dump(doc)  # may raise — always before backup/rewrite
        _backup(path, existing_text)

    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, 0o600)


def _parse_existing(text: str) -> dict[str, Any]:
    """Parse the existing config; refuse (never truncate) on failure."""
    try:
        raw = _yaml.parse(text)
    except ConfigError as exc:
        raise ConfigError(
            f"refusing to overwrite config.yaml: it does not parse ({exc}); "
            "fix or remove the file, then rerun 'kgent setup'"
        ) from exc
    if not isinstance(raw, dict):
        raise ConfigError(
            "refusing to overwrite config.yaml: it is not a mapping; "
            "fix or remove the file, then rerun 'kgent setup'"
        )
    section = raw.get("backends")
    if section is not None and not isinstance(section, dict):
        raise ConfigError(
            "refusing to overwrite config.yaml: 'backends' is not a mapping; "
            "fix or remove the file, then rerun 'kgent setup'"
        )
    return raw


def _backup(path: Path, text: str) -> Path:
    backup = path.with_name(f"{path.name}.bak-{int(time.time())}")
    backup.write_text(text, encoding="utf-8")
    os.chmod(backup, 0o600)
    return backup


# ---------------------------------------------------------------------------
# YAML-subset emitter — the inverse of kgent.config._yaml.parse
# ---------------------------------------------------------------------------


def _dump(doc: dict[str, Any]) -> str:
    return "\n".join(_emit_mapping(doc, 0)) + "\n"


def _emit_mapping(mapping: dict[str, Any], depth: int) -> list[str]:
    pad = "  " * depth
    lines: list[str] = []
    for key, value in mapping.items():
        name = _emit_str(str(key))
        if isinstance(value, dict) and not value:
            lines.append(f"{pad}{name}: {{}}")
        elif isinstance(value, dict):
            lines.append(f"{pad}{name}:")
            lines.extend(_emit_mapping(value, depth + 1))
        elif isinstance(value, list) and not value:
            lines.append(f"{pad}{name}: []")
        elif isinstance(value, list):
            lines.append(f"{pad}{name}:")
            lines.extend(_emit_list(value, depth + 1))
        else:
            lines.append(f"{pad}{name}: {_emit_scalar(value)}")
    return lines


def _emit_list(items: list[Any], depth: int) -> list[str]:
    pad = "  " * depth
    lines: list[str] = []
    for item in items:
        if isinstance(item, dict) and item:
            body = _emit_mapping(item, depth + 1)
            lines.append(f"{pad}- {body[0][len(pad) + 2 :]}")
            lines.extend(body[1:])
        elif isinstance(item, list):
            raise ConfigError(
                "config.yaml contains a list nested in a list; "
                "kgent setup cannot re-emit it — edit the file manually"
            )
        else:
            lines.append(f"{pad}- {_emit_scalar(item)}")
    return lines


def _emit_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return str(value)
    return _emit_str(str(value))


def _emit_str(value: str) -> str:
    """Emit a bare scalar only when it parses back as the same string."""
    if (
        _PLAIN_RE.match(value)
        and value.lower() not in _RESERVED_SCALARS
        and _yaml._parse_scalar(value) == value  # noqa: SLF001 — sibling module, single source of truth
    ):
        return value
    return _scalar(value)


def _scalar(value: str) -> str:
    if _PLAIN_RE.match(value) and value.lower() not in _RESERVED_SCALARS:
        return value
    if "'" not in value:
        return f"'{value}'"
    return f'"{value}"'


_PLAIN_RE = re.compile(r"^[A-Za-z0-9_./-]+$")
_RESERVED_SCALARS = frozenset({"true", "false", "null", "~"})
```

(`import re` at top; `_dump` is deliberately fail-closed — anything it cannot
re-emit raises *before* the backup-and-truncate step, so the original file is
never lost.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_setup_config_merge.py -v`
Expected: 13 PASS

- [ ] **Step 5: Commit**

```bash
git add src/kgent/capabilities/setup_config.py tests/test_setup_config_merge.py
git commit -m "feat: setup writes merged config with backup, refuses broken config"
```

---

### Task 3: Wire into `detect.setup`, define rerun semantics in docstrings

**Files:**
- Modify: `src/kgent/capabilities/detect.py` (remove `_write_config`
  `detect.py:317-327`, `_emit_config` `detect.py:330-349`, `_backend_type`
  `detect.py:352-358`, `_scalar` `detect.py:361-366`, `_PLAIN_RE`/`_RESERVED_SCALARS`
  `detect.py:64-65`; update module docstring + `setup()` docstring)
- Test: `tests/test_setup_config_merge.py`

**Interfaces:**
- Consumes: `write_setup_config` (Task 2).
- Produces: `setup(home)` unchanged signature `(report, 0)`; on broken config
  now raises `ConfigError` (CLI maps to exit 1, `cli.py:1091`).

- [ ] **Step 1: Write the failing e2e test (real `setup()` path)**

Append to `tests/test_setup_config_merge.py`:

```python
def test_setup_rerun_preserves_enabled_and_defaults(tmp_home, monkeypatch):
    """Acceptance 2 end-to-end through discover() + write path."""
    import json

    from kgent.capabilities.detect import setup

    (tmp_home / "config.yaml").write_text(EXISTING_USER_CONFIG, encoding="utf-8")
    skill_dir = tmp_home / ".claude" / "skills" / "lark-doc"
    skill_dir.mkdir(parents=True)
    (skill_dir / "manifest.json").write_text(
        json.dumps({"name": "lark-doc", "version": "1.0.0"}), encoding="utf-8"
    )
    monkeypatch.setenv("HOME", str(tmp_home))
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.delenv("APPDATA", raising=False)

    report, code = setup(tmp_home)
    assert code == 0
    assert "lark" in report.backends
    raw = _yaml.parse((tmp_home / "config.yaml").read_text(encoding="utf-8"))
    assert raw["backends"]["lark"]["enabled"] is True
    assert raw["defaults"]["workspace_domain"] == "acme.example.com"
```

(`_yaml` import is already added in Task 2's tests; add `json` locally as shown.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_setup_config_merge.py::test_setup_rerun_preserves_enabled_and_defaults -v`
Expected: FAIL — current `setup()` overwrites, `raw["backends"]["lark"]["enabled"]` is `False` and `defaults` is gone.

- [ ] **Step 3: Rewire `detect.py`**

In `src/kgent/capabilities/detect.py`:

1. Replace the module docstring's final paragraph with:

```python
"""... (keep everything above)

``setup`` runs discovery against ``os.environ`` and writes ``config.yaml``
plus the capability cache via :func:`kgent.capabilities.cache.write_cache`,
without prompting. Rerun semantics: an existing ``config.yaml`` is merged,
never clobbered — user keys (``enabled``, ``defaults``, …) survive, newly
discovered backends are appended disabled, an unparseable config aborts the
run untouched, and a timestamped ``config.yaml.bak-<ts>`` backup is written
before any rewrite (see :mod:`kgent.capabilities.setup_config`).
"""
```

2. Swap the import and the call:

```python
from kgent.capabilities.setup_config import write_setup_config
```

```python
def setup(home: Path) -> tuple[DiscoveryReport, int]:
    """Run discovery, then write merged ``config.yaml`` + cache (§2.2).

    Never prompts. Returns ``(report, 0)``; each detected backend reports
    ``auth: "deferred"``. Reruns merge into any existing ``config.yaml``
    (see :mod:`kgent.capabilities.setup_config`); an unparseable existing
    config raises :class:`~kgent.errors.ConfigError` and writes nothing.
    """
    home_path = Path(home)
    report = discover(home_path, os.environ)
    write_setup_config(home_path, report.backends)
    ...
```

3. Delete `_write_config`, `_emit_config`, `_backend_type`, `_scalar`,
   `_PLAIN_RE`, `_RESERVED_SCALARS` and the now-unused section comment
   `# config.yaml generation (§2.2 step 4)` header content (keep the file's
   remaining sections intact).

- [ ] **Step 4: Run the test to verify it passes, then the full suite**

Run: `uv run pytest tests/test_setup_config_merge.py tests/test_discovery_doctor.py tests/test_cli.py tests/test_capabilities.py -v`
Expected: PASS (existing `test_s53_setup_does_not_prompt_for_auth` and
`test_cli_setup_read_only` exercise the fresh path and must stay green)

Run: `uv run pytest`
Expected: full suite PASS

- [ ] **Step 5: Lint + types**

Run: `uv run ruff check . && uv run ruff format --check src/kgent/capabilities/setup_config.py tests/test_setup_config_merge.py`
Run: `uv run mypy src/kgent`
Expected: clean. If mypy flags `_yaml._parse_scalar` (private access), keep
the `# noqa` reasoning or inline a local `re`-based bare-safety check — decide
by whichever reads better; behavior is covered by
`test_write_roundtrips_lists_and_scalars`.

- [ ] **Step 6: Commit**

```bash
git add src/kgent/capabilities/detect.py tests/test_setup_config_merge.py
git commit -m "fix: kgent setup merges existing config.yaml instead of overwriting"
```

---

### Task 4: Spec acceptance sweep + PR

**Files:**
- Modify: none (verification only)

- [ ] **Step 1: Walk the spec's five acceptance criteria against tests**

1. Empty dir → full config: `test_write_fresh_home_matches_generated_format`,
   `test_cli_setup_read_only`.
2. `enabled: true` + `defaults.workspace_domain` preserved, new backend
   appended disabled: `test_write_preserves_enabled_and_defaults_on_rerun`,
   `test_setup_rerun_preserves_enabled_and_defaults`.
3. Broken config → no overwrite + guidance:
   `test_write_refuses_unparseable_config_without_touching_it`,
   `test_write_refuses_non_mapping_config`.
4. `config.yaml.bak-<ts>` before rewrite:
   `test_write_backs_up_existing_config_before_rewrite`.
5. Hermetic injected-report tests: the whole new file.

- [ ] **Step 2: Final verification**

Run: `uv run pytest && uv run ruff check . && uv run mypy src/kgent`
Expected: all green.

- [ ] **Step 3: Push and open PR**

```bash
git push -u origin fix/setup-config-overwrite
gh pr create --title "fix: kgent setup merges config.yaml instead of overwriting" --body-file <body>
```

PR body: link the spec `specs/2026-09-02-setup-config-overwrite.md`, map each
acceptance criterion to its test, and record the two documented decisions
(doctor finding skipped + rationale; comment loss on merge, original bytes in
backup).
