"""Capability cache + effective-capability intersection (§3.5).

Runtime-detected capabilities are cached in ``~/.kgent/capabilities.cache.yaml``
with a per-backend ``detected_at`` timestamp. The file uses the same restricted
YAML subset as config files (see :mod:`kgent.config._yaml`): indent-based
mappings, inline ``[a, b]`` lists, and str/int/bool/None scalars.

:mod:`kgent.config._yaml` only *parses*; this module therefore carries a tiny
emitter (:func:`_emit`) that produces that same subset, so the cache round-trips
through the shared loader. Full YAML constructs (anchors, aliases, flow
mappings, block scalars) are deliberately out of scope for both sides.

Effective capability = intersection(cache-detected, config-declared): the
config may only *narrow* what detection found, never assert a capability the
backend does not provide. A config over-assertion is logged as a warning and
treated as unsupported.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from kgent.config import _yaml
from kgent.errors import ConfigError

__all__ = ["CACHE_FILENAME", "effective_capabilities", "read_cache", "write_cache"]

#: Cache file name inside the kgent home directory (§3.5).
CACHE_FILENAME = "capabilities.cache.yaml"

_logger = logging.getLogger("kgent.capabilities.cache")

#: Keys of a capability block that assert capability surface. When config
#: declares one of these for a capability detection does not cover, it is an
#: over-assertion (§3.5) rather than a scalar override (e.g. ``limits``).
_CAPABILITY_KEYS = frozenset({"supported", "features"})

#: Scalars that would parse as a non-string by the YAML-subset loader.
_RESERVED_SCALARS = frozenset({"true", "false", "null", "~"})
_PLAIN_RE = re.compile(r"^[A-Za-z0-9_./-]+$")


def effective_capabilities(detected: dict[str, Any], declared: dict[str, Any]) -> dict[str, Any]:
    """Intersect runtime-detected and config-declared capabilities (§3.5).

    The config may only *narrow* detection: a feature is effective when both
    sides support it. ``declared`` values default to ``True`` for anything
    detection found (pass-through), ``declared=False`` narrows a detected
    ``True``, and ``declared=True`` for an undetected feature stays unsupported
    — the over-assertion is logged as a warning. Non-capability scalars such
    as ``limits``/``defaults`` are config overrides when present.

    The result mirrors ``detected``'s structure; capabilities declared but not
    detected are over-assertions and omitted (treated as unsupported).
    """
    result: dict[str, Any] = {}
    for cap_name, det_value in detected.items():
        dec_value = declared.get(cap_name)
        if dec_value is None:
            result[cap_name] = det_value
        else:
            result[cap_name] = _intersect(det_value, dec_value, str(cap_name))
    for cap_name in declared:
        if cap_name not in detected:
            _logger.warning(
                "config declares capability %r that detection does not support; "
                "treating as unsupported",
                cap_name,
            )
    return result


def _intersect(det: Any, dec: Any, path: str) -> Any:
    """Recursive §3.5 intersection of one detected/declared value pair."""
    if dec is None:
        return det
    if isinstance(det, dict) and isinstance(dec, dict):
        merged: dict[str, Any] = {}
        for key, det_value in det.items():
            if key in dec:
                merged[key] = _intersect(det_value, dec[key], f"{path}.{key}")
            else:
                merged[key] = det_value
        for key, dec_value in dec.items():
            if key in det:
                continue
            if key in _CAPABILITY_KEYS:
                _logger.warning(
                    "config asserts %s.%s which detection does not support; "
                    "treating as unsupported",
                    path,
                    key,
                )
                merged[key] = (
                    False if key == "supported" else ([] if isinstance(dec_value, list) else {})
                )
            elif isinstance(dec_value, bool):
                _logger.warning(
                    "config asserts feature %s.%s which detection does not support; "
                    "treating as unsupported",
                    path,
                    key,
                )
                merged[key] = False
            else:
                merged[key] = dec_value
        return merged
    if isinstance(det, list) and isinstance(dec, list):
        dec_set = set(dec)
        for item in dec:
            if item not in det:
                _logger.warning(
                    "config asserts %s feature %r which detection does not support; "
                    "treating as unsupported",
                    path,
                    item,
                )
        return [item for item in det if item in dec_set]
    if isinstance(det, bool):
        if not isinstance(dec, bool):
            _logger.warning(
                "config declares %s with non-boolean value %r; treating as unsupported",
                path,
                dec,
            )
            return False
        if dec and not det:
            _logger.warning(
                "config asserts %s which detection does not support; treating as unsupported",
                path,
            )
        return det and dec
    if isinstance(dec, (dict, list, bool)):
        _logger.warning(
            "config shape for %s does not match detection; ignoring config override", path
        )
        return det
    return dec


def read_cache(home: Path | str) -> dict[str, Any]:
    """Load ``~/.kgent/capabilities.cache.yaml``; ``{}`` when absent.

    Raises :class:`ConfigError` when the file exists but is not a mapping.
    """
    path = Path(home) / CACHE_FILENAME
    if not path.exists():
        return {}
    parsed = _yaml.parse(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ConfigError("capability cache must be a mapping")
    return parsed


def write_cache(
    home: Path | str,
    caps_by_backend: dict[str, dict[str, Any]],
    detected_at: str,
) -> None:
    """Write ``caps_by_backend`` into the capability cache (§3.5).

    Each backend in ``caps_by_backend`` is stamped with ``detected_at``
    (ISO-8601); entries for backends not in this call are preserved with their
    own timestamps, so a per-backend refresh never clobbers sibling entries.
    The cache file is written 0600 inside a 0700 home directory.
    """
    home_path = Path(home)
    created = not home_path.exists()
    home_path.mkdir(parents=True, exist_ok=True)
    if created:
        os.chmod(home_path, 0o700)
    existing = read_cache(home_path)
    backends = dict(existing.get("backends", {})) if isinstance(existing, dict) else {}
    for name, caps in caps_by_backend.items():
        entry = dict(caps)
        entry["detected_at"] = detected_at
        backends[str(name)] = entry
    text = _emit({"backends": backends})
    path = home_path / CACHE_FILENAME
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, 0o600)


# ---------------------------------------------------------------------------
# Tiny emitter for the restricted YAML subset (round-trips via _yaml.parse).
# ---------------------------------------------------------------------------


def _emit(document: dict[str, Any]) -> str:
    return "\n".join(_emit_mapping(document, 0)) + "\n"


def _emit_mapping(mapping: dict[str, Any], indent: int) -> list[str]:
    lines: list[str] = []
    for key, value in mapping.items():
        lines.extend(_emit_kv(" " * indent, _serialize_key(key), value, indent + 2))
    return lines


def _emit_list(items: list[Any], indent: int) -> list[str]:
    lines: list[str] = []
    for item in items:
        if isinstance(item, dict):
            if not item:
                lines.append(f"{' ' * indent}- {{}}")
                continue
            for i, (key, value) in enumerate(item.items()):
                lead = "- " if i == 0 else "  "
                lines.extend(
                    _emit_kv(" " * (indent + 2) + lead, _serialize_key(key), value, indent + 4)
                )
        elif isinstance(item, list):
            if not item:
                lines.append(f"{' ' * indent}- []")
            else:
                lines.append(f"{' ' * indent}-")
                lines.extend(_emit_list(item, indent + 2))
        else:
            lines.append(f"{' ' * indent}- {_emit_scalar(item)}")
    return lines


def _emit_kv(prefix: str, key: str, value: Any, child_indent: int) -> list[str]:
    if isinstance(value, dict):
        if not value:
            return [f"{prefix}{key}: {{}}"]
        return [f"{prefix}{key}:", *_emit_mapping(value, child_indent)]
    if isinstance(value, list):
        if not value:
            return [f"{prefix}{key}: []"]
        if all(_is_scalar(item) for item in value):
            return [f"{prefix}{key}: [{', '.join(_emit_scalar(item) for item in value)}]"]
        return [f"{prefix}{key}:", *_emit_list(value, child_indent)]
    return [f"{prefix}{key}: {_emit_scalar(value)}"]


def _is_scalar(value: Any) -> bool:
    return not isinstance(value, (dict, list))


def _emit_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return _quote_if_needed(value)
    raise TypeError(f"cannot serialize {type(value).__name__} into capability cache")


def _serialize_key(key: Any) -> str:
    if not isinstance(key, str):
        key = str(key)
    return _quote_if_needed(key)


def _quote_if_needed(s: str) -> str:
    """Emit ``s`` plain when it round-trips as a string, else quote it.

    The subset loader strips quotes without unescaping, so quoted strings must
    not contain the quote character; cache keys/values are plain identifiers,
    timestamps, and scalars, which never need escaping.
    """
    if _PLAIN_RE.match(s) and s.lower() not in _RESERVED_SCALARS and not _parses_as_number(s):
        return s
    if "'" not in s:
        return f"'{s}'"
    return f'"{s}"'


def _parses_as_number(s: str) -> bool:
    try:
        int(s)
        return True
    except ValueError:
        pass
    try:
        float(s)
        return True
    except ValueError:
        return False
