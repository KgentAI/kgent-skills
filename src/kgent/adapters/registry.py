"""Backend-adapter registry: name → adapter lookup (§1.5, Task 9.4).

The router and CLI resolve backend names to concrete adapter instances via this
module-level registry. Tests register fake backends; production wires real
adapters at startup. ``clear()`` is provided for test isolation.
"""

from __future__ import annotations

from typing import Any

from kgent.errors import ConfigError

__all__ = ["clear", "get", "register", "registered_names"]

_REGISTRY: dict[str, Any] = {}


def register(name: str, adapter: Any) -> None:
    """Register ``adapter`` under ``name`` (overwrites any prior registration)."""
    _REGISTRY[str(name)] = adapter


def get(name: str) -> Any:
    """Return the adapter registered under ``name``.

    Raises :class:`~kgent.errors.ConfigError` when no adapter is registered
    for ``name`` — the CLI maps this to exit 1.
    """
    adapter = _REGISTRY.get(str(name))
    if adapter is None:
        raise ConfigError(f"no adapter registered for backend {name!r}")
    return adapter


def registered_names() -> list[str]:
    """Return the sorted list of registered backend names (diagnostic)."""
    return sorted(_REGISTRY)


def clear() -> None:
    """Remove every registration (test isolation)."""
    _REGISTRY.clear()
