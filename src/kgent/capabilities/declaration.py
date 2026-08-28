"""Capability declaration + uniform fallback resolution (§3.2, §3.3)."""

from __future__ import annotations

from dataclasses import dataclass, field

# Built-in fallback chain for search modes: config `fallback` entries are
# consulted first; if none is defined for an unsupported mode, this chain
# applies (§3.3).
BUILTIN_FALLBACK: dict[str, str] = {"hybrid": "semantic", "semantic": "keyword"}

# Short search-mode aliases used by the built-in chain, mapped to the full
# feature names a backend declares in `features` (§3.2).
_SEARCH_MODE_ALIASES: dict[str, str] = {
    "keyword": "search_by_keywords",
    "semantic": "search_by_semantics",
    "hybrid": "search_hybrid",
}


@dataclass(frozen=True, slots=True)
class CapabilityDeclaration:
    """Declared capability surface of an adapter (§3.2).

    ``features`` maps full mode names (e.g. ``search_by_keywords``) to a
    boolean or a list of supported backends; ``fallback`` is always a sibling
    of ``features``, never nested inside it.
    """

    features: dict[str, bool | list[str]] = field(default_factory=dict)
    fallback: dict[str, str] = field(default_factory=dict)
    limits: dict[str, object] = field(default_factory=dict)
    defaults: dict[str, object] = field(default_factory=dict)

    def supports(self, mode: str) -> bool:
        """Whether ``mode`` is natively supported (§3.2).

        Accepts both full mode names (``search_by_keywords``) and the short
        aliases used by the built-in fallback chain (``keyword``).
        """
        if bool(self.features.get(mode, False)):
            return True
        canonical = _SEARCH_MODE_ALIASES.get(mode)
        return canonical is not None and bool(self.features.get(canonical, False))


def resolve_mode(decl: CapabilityDeclaration, requested: str) -> str | None:
    """Resolve ``requested`` to a supported mode via the §3.3 uniform fallback.

    Config fallbacks (``decl.fallback``) take precedence over the built-in
    chain (``BUILTIN_FALLBACK``); returns the requested mode unchanged when it
    is already supported, or ``None`` when no supported mode can be reached
    (including fallback cycles).
    """
    mode = requested
    seen: set[str] = set()
    while not decl.supports(mode):
        if mode in seen:
            return None
        seen.add(mode)
        next_mode: str | None = decl.fallback.get(mode) or BUILTIN_FALLBACK.get(mode)
        if next_mode is None:
            return None
        mode = next_mode
    return mode
