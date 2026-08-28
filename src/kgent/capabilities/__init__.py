"""Capability interfaces, declarations, and fallback resolution (§3.1–§3.3)."""

from kgent.capabilities.declaration import BUILTIN_FALLBACK, CapabilityDeclaration, resolve_mode
from kgent.capabilities.interface import ApprovalFlow, DocumentSearch, DocumentStorage

__all__ = [
    "BUILTIN_FALLBACK",
    "ApprovalFlow",
    "CapabilityDeclaration",
    "DocumentSearch",
    "DocumentStorage",
    "resolve_mode",
]
