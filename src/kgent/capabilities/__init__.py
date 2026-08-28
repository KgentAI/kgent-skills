"""Capability interfaces, declarations, cache, and effective intersection (§3.1–§3.5)."""

from kgent.capabilities.cache import CACHE_FILENAME, effective_capabilities, read_cache, write_cache
from kgent.capabilities.declaration import BUILTIN_FALLBACK, CapabilityDeclaration, resolve_mode
from kgent.capabilities.detect import DiscoveryReport, discover, setup
from kgent.capabilities.interface import ApprovalFlow, DocumentSearch, DocumentStorage

__all__ = [
    "BUILTIN_FALLBACK",
    "CACHE_FILENAME",
    "ApprovalFlow",
    "CapabilityDeclaration",
    "DiscoveryReport",
    "DocumentSearch",
    "DocumentStorage",
    "discover",
    "effective_capabilities",
    "read_cache",
    "resolve_mode",
    "setup",
    "write_cache",
]
