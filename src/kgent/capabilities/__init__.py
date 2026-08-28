"""Capability interfaces, declarations, cache, and effective intersection (§3.1–§3.5)."""

from kgent.capabilities.cache import CACHE_FILENAME, effective_capabilities, read_cache, write_cache
from kgent.capabilities.declaration import BUILTIN_FALLBACK, CapabilityDeclaration, resolve_mode
from kgent.capabilities.interface import ApprovalFlow, DocumentSearch, DocumentStorage

__all__ = [
    "BUILTIN_FALLBACK",
    "CACHE_FILENAME",
    "ApprovalFlow",
    "CapabilityDeclaration",
    "DocumentSearch",
    "DocumentStorage",
    "effective_capabilities",
    "read_cache",
    "resolve_mode",
    "write_cache",
]
