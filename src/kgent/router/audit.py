"""Append-only audit log + query redaction (§8.4, S45/S52).

The audit log is the router's local, append-only record of every operation
(writes now; searches/reads when the router wires them): one JSON object per
line (NDJSON) at ``<home>/audit.ndjson``, ``home`` being ``KGENT_HOME`` when
set else ``~/.kgent`` — the same resolution the journal uses. The file is
created ``0600`` and its directory ``0700`` on every append (S43 parity with
the journal), so a pre-existing file or directory with looser permissions is
tightened.

**Query redaction (S45, §8.4).** ``redact_queries`` defaults to ``True``:
a ``query`` body is never written as-is — ``append`` stores
``"query": "<redacted>"`` and sets ``"redacted_query": true`` instead, so the
raw query text cannot reach the file. ``audit.redact_queries: false`` is an
opt-in (the constant :data:`AUDIT_REDACT_QUERY_WARNING` documents the risk;
the CLI surfaces it in Task 8.x).

**Secrets never enter the audit log (S52).** ``append`` serializes *only* the
fixed §8.4 schema fields — any other key (``token=…``, ``secret=…``,
``credential=…``) is dropped before it can reach the file, mirroring
``journal.build_entry``. ``schema_version: 1`` and ``outcome: "ok"`` are
defaulted so every line carries them for forward migration and inspection.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

__all__ = ["AUDIT_REDACT_QUERY_WARNING", "REDACTED", "AuditLog"]

#: Marker written in place of a query body when redaction is enabled (§8.4).
REDACTED = "<redacted>"

#: Warning text for the ``audit.redact_queries: false`` opt-out. The object
#: flag lives here (Task 5.5); the CLI surfaces this warning in Task 8.x.
AUDIT_REDACT_QUERY_WARNING = (
    "audit.redact_queries is disabled: search queries will be written to audit.ndjson in plaintext"
)

#: The fixed §8.4 audit schema — the only keys ``append`` ever serializes.
#: Everything else passed in an entry is dropped (S52), and ``query`` is the
#: one field the writer mangles in place (S45).
_AUDIT_FIELDS = (
    "schema_version",
    "ts",
    "op_id",
    "actor",
    "action",
    "operation",
    "targets",
    "routing_decision",
    "confirmation",
    "approval_id",
    "sensitivity",
    "outcome",
    "redacted_query",
    "query",
)


class AuditLog:
    """Append-only NDJSON audit log at ``<home>/audit.ndjson`` (§8.4).

    ``path`` defaults to ``<KGENT_HOME|~/.kgent>/audit.ndjson``. ``append``
    shapes each entry to the fixed §8.4 schema (dropping unknown keys, S52),
    redacts the query body when ``redact_queries`` is ``True`` (S45), and
    defaults ``schema_version: 1`` / ``outcome: "ok"``. The file on disk is
    the durable source of truth; there is no in-memory index to drift from it.
    """

    def __init__(self, path: Path | None = None, *, redact_queries: bool = True) -> None:
        if path is None:
            home = os.environ.get("KGENT_HOME", str(Path.home() / ".kgent"))
            path = Path(home) / "audit.ndjson"
        self.path = Path(path)
        self.redact_queries = redact_queries

    def redact_query(self, query: str) -> str:
        """Return the query body as it may be written (S45).

        ``redact_queries=True`` (default) → ``"<redacted>"``; the opt-in
        ``False`` returns ``query`` unchanged (see :data:`AUDIT_REDACT_QUERY_WARNING`).
        """
        return REDACTED if self.redact_queries else query

    # -- persistence -----------------------------------------------------

    def _ensure_permissions(self) -> None:
        """Create/tighten the home directory 0700 and the audit file 0600 (S43)."""
        os.makedirs(self.path.parent, mode=0o700, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        if not self.path.exists():
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            os.close(fd)
        os.chmod(self.path, 0o600)

    def _shape_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Fit ``entry`` to the fixed §8.4 schema before writing (S52/S45).

        Only :data:`_AUDIT_FIELDS` are ever serialized — ``token=…``,
        ``secret=…``, ``credential=…`` passed by a caller are dropped before
        they can reach the file. A ``query`` body is redacted in place:
        ``redact_queries=True`` writes ``query: "<redacted>"`` and sets
        ``redacted_query: true``; when opted out the body is stored as-is.
        """
        shaped: dict[str, Any] = {}
        for key in _AUDIT_FIELDS:
            if key not in entry:
                continue
            value = entry[key]
            if key == "query":
                shaped["query"] = self.redact_query(str(value))
                if self.redact_queries:
                    shaped["redacted_query"] = True
            else:
                shaped[key] = value
        shaped.setdefault("schema_version", 1)
        shaped.setdefault("outcome", "ok")
        return shaped

    def append(self, entry: dict[str, Any]) -> None:
        """Append one audit entry (one NDJSON line), shaped to the §8.4 schema."""
        shaped = self._shape_entry(entry)
        self._ensure_permissions()
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(shaped, ensure_ascii=False) + "\n")
