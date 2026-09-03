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

from typing import Any

__all__ = ["merge_backends"]


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
