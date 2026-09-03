"""Optimistic concurrency guards (§3.9, F2 S5–S7).

Pure helpers behind the "updates never clobber external edits" invariant.
There are two comparison modes:

* *Token path* — the proposal recorded a revision token at read time
  (``expected_version`` is not ``None``): any difference from the current
  revision is a :class:`VersionConflict`.
* *No-token path* — the backend exposes no revision token
  (``expected_version`` is ``None``, design §3.9.4): fall back to
  ``updated_at`` comparison; a difference between the read-time and current
  timestamps is a :class:`VersionConflict`.

The router-level wiring (conflict → journal ``status: conflict``, exit 4,
fresh proposal from a re-read) lives in ``kgent.router.policy``.
"""

from __future__ import annotations

from datetime import datetime

from kgent.errors import VersionConflict

__all__ = ["check_version", "no_token_warning"]


def check_version(
    expected_version: str | None,
    current_version: str | None,
    expected_updated_at: datetime | None,
    current_updated_at: datetime | None,
    doc_uri: str,
) -> None:
    """Raise :class:`VersionConflict` on an optimistic-concurrency mismatch.

    Token path (``expected_version`` is not ``None``): mismatch vs
    ``current_version`` → conflict; match → pass. No-token path
    (``expected_version`` is ``None``): compare ``expected_updated_at`` vs
    ``current_updated_at``; mismatch → conflict; equal → pass.
    """
    if expected_version is not None:
        if expected_version != current_version:
            raise VersionConflict(doc_uri, expected_version, current_version or "")
        return
    if expected_updated_at != current_updated_at:
        raise VersionConflict(
            doc_uri,
            _iso(expected_updated_at),
            _iso(current_updated_at),
        )


def no_token_warning(backend: str) -> str:
    """Exact warning a no-token backend's proposal must carry (S7)."""
    return f"no hard concurrency protection on {backend}"


def _iso(ts: datetime | None) -> str:
    return ts.isoformat() if ts is not None else ""
