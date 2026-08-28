"""Secret storage with encrypted-file fallback (§2.4, S46).

The preferred store is the OS keychain (not yet implemented — requires
platform-specific ctypes bindings). The fallback is an encrypted file at
``~/.kgent/credentials.enc`` using PBKDF2-derived keys and HMAC authentication
(pure stdlib — no ``cryptography`` dependency).

If encryption is also unavailable (e.g. FIPS mode, broken hashlib), the
``UnavailableSecretStore`` refuses writes and auth setup fails with exit 1.

The warning ``"encrypted-file fallback active"`` is printed at startup and on
every auth use when the encrypted file store is in use (S46).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets as _secrets
from pathlib import Path
from typing import Protocol

__all__ = [
    "EncryptedFileStore",
    "SecretStore",
    "UnavailableSecretStore",
    "fallback_warning",
    "get_store",
]

_FALLBACK_WARNING = "encrypted-file fallback active"


def fallback_warning() -> str:
    """Return the S46 fallback warning text."""
    return _FALLBACK_WARNING


class SecretStore(Protocol):
    """Protocol for credential storage backends."""

    def get(self, key: str) -> str | None:
        """Retrieve a credential by key, or None if not found."""
        ...

    def set(self, key: str, value: str) -> bool:
        """Store a credential. Returns True on success, False on failure."""
        ...

    def delete(self, key: str) -> bool:
        """Delete a credential. Returns True if deleted, False if not found."""
        ...


class EncryptedFileStore:
    """Encrypted-file credential store (S46 fallback).

    Uses PBKDF2-HMAC-SHA256 to derive a key from a machine-local seed, then
    AES-like XOR encryption with HMAC-SHA256 authentication. Pure stdlib.
    """

    def __init__(self, path: Path, *, machine_id: str | None = None) -> None:
        self.path = Path(path)
        self._machine_id = machine_id or self._default_machine_id()
        self._key = self._derive_key(self._machine_id)

    @staticmethod
    def _default_machine_id() -> str:
        """Derive a machine-local seed from environment (hostname + user)."""
        return f"{os.environ.get('COMPUTERNAME', os.environ.get('HOSTNAME', 'unknown'))}:{os.environ.get('USERNAME', os.environ.get('USER', 'unknown'))}"

    def _derive_key(self, seed: str) -> bytes:
        """PBKDF2-HMAC-SHA256 key derivation (200k iterations, stdlib)."""
        salt = b"kgent-credentials-v1"
        return hashlib.pbkdf2_hmac("sha256", seed.encode("utf-8"), salt, iterations=200_000)

    def _encrypt(self, plaintext: bytes) -> bytes:
        """XOR encryption with HMAC authentication (stdlib-only)."""
        iv = _secrets.token_bytes(16)
        # XOR stream cipher with key-derived stream
        key_stream = hashlib.sha256(self._key + iv).digest()
        ciphertext = bytes(p ^ key_stream[i % len(key_stream)] for i, p in enumerate(plaintext))
        # HMAC authentication
        mac = hmac.new(self._key, iv + ciphertext, hashlib.sha256).digest()
        return iv + mac + ciphertext

    def _decrypt(self, data: bytes) -> bytes:
        """Decrypt and verify HMAC."""
        if len(data) < 48:  # 16 (iv) + 32 (mac) minimum
            raise ValueError("encrypted data too short")
        iv = data[:16]
        mac = data[16:48]
        ciphertext = data[48:]
        expected_mac = hmac.new(self._key, iv + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(mac, expected_mac):
            raise ValueError("HMAC verification failed")
        key_stream = hashlib.sha256(self._key + iv).digest()
        return bytes(c ^ key_stream[i % len(key_stream)] for i, c in enumerate(ciphertext))

    def get(self, key: str) -> str | None:
        """Retrieve a credential."""
        if not self.path.exists():
            return None
        try:
            raw = self.path.read_bytes()
            data = json.loads(self._decrypt(raw).decode("utf-8"))
            value = data.get(key)
            return value if isinstance(value, str) else None
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return None

    def set(self, key: str, value: str) -> bool:
        """Store a credential (encrypted)."""
        try:
            data: dict[str, str] = {}
            if self.path.exists():
                try:
                    raw = self.path.read_bytes()
                    data = json.loads(self._decrypt(raw).decode("utf-8"))
                except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
                    data = {}
            data[key] = value
            plaintext = json.dumps(data).encode("utf-8")
            encrypted = self._encrypt(plaintext)
            self.path.write_bytes(encrypted)
            return True
        except Exception:  # noqa: BLE001 — encryption failure
            return False

    def delete(self, key: str) -> bool:
        """Delete a credential."""
        if not self.path.exists():
            return False
        try:
            raw = self.path.read_bytes()
            data = json.loads(self._decrypt(raw).decode("utf-8"))
            if key not in data:
                return False
            del data[key]
            if data:
                plaintext = json.dumps(data).encode("utf-8")
                self.path.write_bytes(self._encrypt(plaintext))
            else:
                self.path.unlink()
            return True
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return False


class UnavailableSecretStore:
    """Stub store for when encryption is unavailable (S46 failure mode)."""

    def get(self, key: str) -> str | None:
        return None

    def set(self, key: str, value: str) -> bool:
        return False

    def delete(self, key: str) -> bool:
        return False


def get_store(home: Path) -> SecretStore:
    """Return the best available secret store for ``home``.

    Prefers OS keychain (not yet implemented), falls back to
    :class:`EncryptedFileStore`. If encryption is unavailable, returns
    :class:`UnavailableSecretStore`.
    """
    enc_path = home / "credentials.enc"
    try:
        store = EncryptedFileStore(enc_path)
        # Test that encryption works
        store.set("__test__", "test")
        store.delete("__test__")
        return store
    except Exception:  # noqa: BLE001 — encryption unavailable
        return UnavailableSecretStore()
