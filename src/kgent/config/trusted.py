"""Project-directory trust records (``~/.kgent/trusted.json``, §2.3).

Trust is recorded by hashing the resolved absolute directory path (SHA-256)
into a JSON map ``{hash: path}``. The file is written 0600 inside a 0700
directory so trust records cannot be read or forged by other local users.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

__all__ = ["is_trusted", "reset_trusted", "trust_directory"]


def _hash_directory(path: Path) -> str:
    """SHA-256 hex digest of the resolved absolute directory path."""
    resolved = str(path.resolve())
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()


def _read_records(trusted_path: Path) -> dict[str, str]:
    """Load ``trusted.json`` as ``{hash: path}``, tolerating a missing/corrupt file."""
    if not trusted_path.exists():
        return {}
    try:
        data = json.loads(trusted_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items()}


def _write_records(trusted_path: Path, records: dict[str, str]) -> None:
    parent = trusted_path.parent
    created = not parent.exists()
    parent.mkdir(parents=True, exist_ok=True)
    if created:
        os.chmod(parent, 0o700)
    trusted_path.write_text(json.dumps(records, indent=2, sort_keys=True), encoding="utf-8")
    os.chmod(trusted_path, 0o600)


def trust_directory(path: Path, trusted_path: Path) -> None:
    """Record ``path`` as trusted in ``trusted_path`` (idempotent)."""
    records = _read_records(trusted_path)
    records[_hash_directory(path)] = str(path.resolve())
    _write_records(trusted_path, records)


def is_trusted(path: Path, trusted_path: Path) -> bool:
    """Return whether ``path`` has a trust record in ``trusted_path``."""
    return _hash_directory(path) in _read_records(trusted_path)


def reset_trusted(trusted_path: Path) -> None:
    """Remove the trust record file, if present (test helper)."""
    if trusted_path.exists():
        trusted_path.unlink()
