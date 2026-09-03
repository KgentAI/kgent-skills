"""Canonical URI parsing and formatting (§3.6).

Canonical URIs take the form ``kgent://<backend>/<native-id>`` and are the only
identifiers allowed to cross adapter boundaries. Bare native IDs are rejected
with a hint, never guessed.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from kgent.errors import ConfigError

_SCHEME = "kgent"


def parse_uri(s: str) -> tuple[str, str]:
    """Parse a canonical ``kgent://`` URI into ``(backend, native_id)``.

    Rejects bare native IDs, scheme-less strings, non-``kgent`` schemes, empty
    backends or native-ids, extra path segments, and any query/fragment (a
    canonical URI carries no extra components, so anything beyond the two
    segments is malformed rather than silently dropped).

    Raises:
        ConfigError: if ``s`` is not a well-formed canonical URI.
    """
    parts = urlsplit(s)
    if parts.scheme != _SCHEME:
        raise ConfigError(
            f"expected a canonical kgent:// URI, got {s!r}; "
            "bare native IDs are not accepted — use kgent://<backend>/<id>"
        )
    backend = parts.netloc
    if not backend:
        raise ConfigError(f"canonical URI {s!r} is missing a backend")
    if parts.query or parts.fragment:
        raise ConfigError(f"canonical URI {s!r} must not carry a query or fragment")
    path = parts.path
    if not path.startswith("/") or "/" in path[1:]:
        raise ConfigError(f"canonical URI {s!r} must contain exactly one path segment")
    native_id = path[1:]
    if not native_id:
        raise ConfigError(f"canonical URI {s!r} is missing a native id")
    return backend, native_id


def format_uri(backend: str, native_id: str) -> str:
    """Format ``(backend, native_id)`` as a canonical ``kgent://`` URI."""
    return f"{_SCHEME}://{backend}/{native_id}"
