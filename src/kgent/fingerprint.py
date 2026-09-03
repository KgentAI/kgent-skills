"""Content fingerprints (§6.5, P7).

``content_fingerprint`` is a deterministic sha256 hex digest of a normalized
(title, content) pair.  Identical content produces identical fingerprints
across all backends, which powers the idmap, cross-backend dedupe, and
``also_available_in``.
"""

from __future__ import annotations

import hashlib
import re

__all__ = ["content_fingerprint", "fingerprints_equal", "normalize"]

# \\x1f is the title/content field separator.  Python's Unicode-aware \\s would
# match it as whitespace (C0 control), collapsing the field boundary away and
# making e.g. normalize("a", "b") == normalize("a b", "").  So collapse and
# strip each field separately, then join: this keeps the boundary intact while
# making both title and content fully whitespace-insensitive.
_WHITESPACE_RUN = re.compile(r"\s+")


def _norm_field(s: str) -> str:
    return _WHITESPACE_RUN.sub(" ", s).strip()


def normalize(title: str, content: str) -> str:
    """Deterministic, whitespace-normalized form of ``(title, content)``.

    Each field is lowercased, every whitespace run is collapsed to a single
    space, and leading/trailing whitespace is stripped; the fields are then
    joined with the unit separator ``\\x1f`` so the field boundary cannot be
    forged by content whitespace.
    """
    return f"{_norm_field(title.lower())}\x1f{_norm_field(content.lower())}"


def content_fingerprint(title: str, content: str) -> str:
    """sha256 hex digest of the normalized ``(title, content)`` pair."""
    return hashlib.sha256(normalize(title, content).encode("utf-8")).hexdigest()


def fingerprints_equal(fp1: str | None, fp2: str | None) -> bool:
    """True when both fingerprints are equal, or both are absent."""
    return fp1 == fp2
