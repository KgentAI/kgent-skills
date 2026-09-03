"""``kgent setup`` config.yaml write policy: merge, back up, never clobber.

Rerun semantics (spec specs/2026-09-02-setup-config-overwrite.md): ``setup``
is repeatable. When ``config.yaml`` already exists it is merged, not replaced:

- backend entries the user already has keep their keys verbatim (notably
  ``enabled: true``); only keys absent from the entry are filled in from this
  discovery report (shallow, top-level only);
- newly discovered backends are appended with ``enabled: false``;
- configured-but-undiscovered backends are kept, as are non-mapping entries;
- every non-backend section (``defaults:``, ``content_type_mapping:``, ...) is
  preserved as parsed.

Two safety rails: an unparseable existing config aborts with
:class:`~kgent.errors.ConfigError` *before* any write (never truncate what we
cannot read back), and any rewrite of an existing file first writes a
timestamped ``config.yaml.bak-<ts>`` copy (same convention as
:mod:`kgent.config.migrate`). Values survive merging; comments do not — the
backup retains the original bytes.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

from kgent.config import _yaml
from kgent.errors import ConfigError

__all__ = ["merge_backends", "write_setup_config"]

_PLAIN_RE = re.compile(r"^[A-Za-z0-9_./-]+$")
_RESERVED_SCALARS = frozenset({"true", "false", "null", "~"})


def write_setup_config(home: Path, backends: dict[str, dict[str, Any]]) -> None:
    """Write ``<home>/config.yaml`` for ``kgent setup`` (merge-on-rerun).

    ``backends`` is a discovery report's backend mapping (as produced by
    :func:`kgent.capabilities.detect.discover`). With no existing config this
    generates the standard all-disabled config; otherwise it parses, merges
    (see the module docstring), backs up the original, and rewrites. An
    unparseable existing config raises :class:`ConfigError` and leaves the
    file untouched.
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
        section = existing.get("backends")
        doc["backends"] = merge_backends(
            section if isinstance(section, dict) else {}, backends
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


def merge_backends(
    existing: dict[str, Any], discovered: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Merge a discovery report into the config's ``backends`` section.

    Existing entries win: kept verbatim (shallow, top-level only) and padded
    with report-derived keys they lack. New backends are appended
    all-disabled.
    """
    result: dict[str, Any] = {}
    for name in sorted(set(existing) | set(discovered)):
        current = existing.get(name)
        report_entry = discovered.get(name)
        if report_entry is None:
            result[name] = current  # configured but not discovered: keep verbatim
        elif current is None:
            result[name] = _config_entry(report_entry)
        elif not isinstance(current, dict):
            result[name] = current  # non-mapping user entry: keep verbatim
        else:
            entry = _config_entry(report_entry)
            entry.update(current)  # user keys win; report fills the gaps
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
    """Emit a bare scalar only when it would parse back as the same string."""
    if (
        _PLAIN_RE.match(value)
        and value.lower() not in _RESERVED_SCALARS
        and _yaml._parse_scalar(value) == value  # noqa: SLF001 — sibling module, single source of truth
    ):
        return value
    if "'" not in value:
        return f"'{value}'"
    return f'"{value}"'
