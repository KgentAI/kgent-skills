"""Oversize content preflight (§3.7, S48).

Before ANY proposal is built, the write path runs the pending content against
EVERY target backend's declared ``document_search.limits.max_content_bytes``.
Backends that do not declare a byte limit never violate (no assumption of an
arbitrary ceiling is made). Violations are reported per offending backend with
the actual size, the declared limit, and the backends that WOULD accept the
content (alternatives) — so the user can retry against a backend with headroom
instead of guessing. The write path must reject with exit code 3 (via
:func:`reject_preflight`, raising :class:`~kgent.errors.PolicyError`) before
displaying anything.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from kgent.errors import PolicyError

__all__ = ["preflight_size", "reject_preflight"]

# Backends that declare no limit are reported as alternatives: they accept any
# size by contract (the spec's defaulted ceiling is 1 GB / effectively unbounded).


class TargetWithLimits(Protocol):
    """Minimal target surface for oversize preflight (§3.7).

    ``capabilities`` mirrors the adapter declaration shape::

        capabilities["document_search"]["limits"]["max_content_bytes"] -> int | None
    """

    name: str
    capabilities: dict[str, Any]


def _max_content_bytes(target: TargetWithLimits) -> int | None:
    """Declared ``max_content_bytes`` for ``target``, or ``None`` when no limit is declared."""
    search = (target.capabilities or {}).get("document_search")
    if not isinstance(search, dict):
        return None
    limits = search.get("limits")
    if not isinstance(limits, dict):
        return None
    raw = limits.get("max_content_bytes")
    return int(raw) if raw is not None else None


def _size_of(content: bytes | str) -> int:
    """Byte length of ``content`` (UTF-8 for ``str``)."""
    return len(content) if isinstance(content, bytes) else len(content.encode("utf-8"))


def _fmt_bytes(n: int) -> str:
    """Human-readable byte size (e.g. ``"2.4 MiB"``)."""
    value = float(n)
    for unit in ("bytes", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.1f} {unit}" if unit != "bytes" else f"{n} bytes"
        value /= 1024
    return f"{n} bytes"  # pragma: no cover - unreachable


def preflight_size(
    content: bytes | str,
    targets_with_limits: Sequence[TargetWithLimits],
) -> list[str]:
    """Return per-target violation messages for oversized ``content`` (S48).

    A message is produced for every target whose declared
    ``max_content_bytes`` is smaller than the content's byte size. Each message
    names the offending backend, the actual size, the declared limit, and the
    backends that would accept the content (alternatives). Backends without a
    declared limit never violate and appear in the alternatives. Returns ``[]``
    when every target accepts the content.
    """
    size = _size_of(content)
    targets = list(targets_with_limits)
    limits = {t.name: _max_content_bytes(t) for t in targets}
    accepted = sorted(name for name, limit in limits.items() if limit is None or limit >= size)

    violations: list[str] = []
    for target in targets:
        limit = limits[target.name]
        if limit is None or size <= limit:
            continue
        alternatives = ", ".join(a for a in accepted if a != target.name) or "none"
        violations.append(
            f"content {size} bytes exceeds {target.name} max_content_bytes {limit} "
            f"({_fmt_bytes(limit)}); accepted by: {alternatives}"
        )
    return violations


def reject_preflight(violations: Sequence[str]) -> None:
    """Raise ``PolicyError`` (exit code 3) from ``violations`` — S48 rejection.

    The write path calls this after :func:`preflight_size` when violations are
    non-empty, BEFORE any proposal is shown. Exit code 3 via
    :class:`~kgent.errors.PolicyError`.
    """
    if violations:
        raise PolicyError("oversize preflight failed:\n" + "\n".join(violations))
