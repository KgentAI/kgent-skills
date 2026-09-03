"""Result aggregation: dedupe, near-dup clustering, staleness, conflicts (§7.2, §6.5, §8.6).

This is the aggregation core of the search path. After bounded fan-out (7.1)
and before RRF ranking (7.3), results are merged and deduplicated here:

- **Identical copies (S37)**: results with the same non-``None``
  ``content_fingerprint`` collapse to ONE result; later copies append their
  ``doc_uri`` to the kept result's ``also_available_in``. Callers build the
  "Update all N copies (identical content)" option from the kept uri + the
  ``also_available_in`` list (one op id, per-backend reporting).
- **Same ``doc_uri`` duplicates**: keep the first occurrence. ``also_available_in``
  lists *other* locations, so a document is never listed as available in itself.
- **Near-duplicates (S38, N8)**: results with *different* fingerprints but
  similar normalized titles (``difflib.SequenceMatcher.ratio() >= 0.8``) are
  grouped into :class:`NearDupCluster` members. They are NEVER auto-merged or
  deleted — clustering is display/proposal machinery. Clustered results also
  remain on the merged stream (nothing is dropped) and are grouped in
  ``clusters`` for the "search shows them as a cluster" surface (S38).

- **Snippet overlap (S56)** (:func:`snippet_overlap`) flags copy-pasted
  sections between results; a cluster whose members share an overlapping
  snippet is flagged via ``NearDupCluster.overlapping`` (computed lazily).
  Overlapping pairs are never auto-merged.
- **Conflict detection (S55)** (:func:`detect_conflicts`) is the deterministic
  fallback: diverged near-duplicates (same title, different fingerprints,
  overlapping snippets) and stale-vs-live contradictions surface a
  :class:`Conflict` with a RECOMMENDED strategy from
  ``conflict_resolution.strategies`` (default ``["link", …]``). Detection +
  recommendation only — no resolution action ever executes here (S55, §5.6).

- **Read-path staleness (§8.6, S35/S36)**: :func:`verify_results` re-reads
  every result on its backend and demotes failures onto the result via the
  ``access`` field (``stale`` / ``denied``), never dropping them; the idmap at
  ``<KGENT_HOME|~/.kgent>/idmap.json`` records stale URIs (0600 file under a
  0700 home, S43). :func:`assess_staleness` computes which backends exceed the
  20% bulk-staleness threshold and returns them for cache invalidation (the
  caller invalidates; this module only computes + warns).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path
from typing import Any

from kgent.errors import ConfigError
from kgent.types import SearchResult
from kgent.uri import parse_uri

__all__ = [
    "DEFAULT_CONFLICT_STRATEGIES",
    "Conflict",
    "IdMap",
    "NearDupCluster",
    "assess_staleness",
    "classify_read_failure",
    "cluster_title",
    "cluster_uris",
    "detect_conflicts",
    "has_conflicts",
    "merge_and_deduplicate",
    "resolve_home",
    "snippet_overlap",
    "verify_results",
]

#: Default ``conflict_resolution.strategies`` (Appendix C) — mirrors the config
#: default so callers without a loaded :class:`~kgent.config.schema.Config` can
#: pass the same order. Detection picks the FIRST strategy of the list.
DEFAULT_CONFLICT_STRATEGIES: list[str] = ["link", "comment", "archive", "correct"]

#: Near-duplicate boundary: normalized-title ``SequenceMatcher.ratio()`` (§6.5).
_NEAR_DUP_TITLE_RATIO = 0.8

#: The exact actionable message for permission failures (§8.6).
_PERMISSION_MESSAGE = "permission denied on {uri} — request access on the platform"


def resolve_home() -> Path:
    """Local-state home: ``$KGENT_HOME`` when set, else ``~/.kgent``.

    Same resolution as the journal (``kgent.router.journal``) and audit log —
    duplicated here to avoid an import cycle (journal pulls in policy).
    """
    return Path(os.environ.get("KGENT_HOME", str(Path.home() / ".kgent")))


def _norm_text(s: str) -> str:
    """Lowercase + collapse/trim whitespace (mirrors the per-field normalize in
    :mod:`kgent.fingerprint`, kept local to avoid relying on its private API)."""
    return " ".join(s.lower().split())


# ---------------------------------------------------------------------------
# Idmap — staleness registry
# ---------------------------------------------------------------------------


class IdMap:
    """Staleness registry at ``<home>/idmap.json`` (§3.6, §8.6; S35).

    Map shape: ``{"uri": {"fingerprint": str | None, "stale": bool}}``. Written
    ``0600`` under a ``0700`` ``~/.kgent`` (S43 directory-wide protection, same
    as the journal). ``fingerprint`` records the last known content
    fingerprint when one was observed; ``stale`` is set by
    :func:`classify_read_failure` for ``not_found`` reads.
    """

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        if path is None:
            path = resolve_home() / "idmap.json"
        self.path = Path(path)
        self.entries: dict[str, dict[str, str | bool | None]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            raw = {}
        if not isinstance(raw, dict):
            return
        for uri, record in raw.items():
            if isinstance(record, dict):
                self.entries[str(uri)] = {
                    "fingerprint": record.get("fingerprint"),
                    "stale": bool(record.get("stale", False)),
                }

    def _ensure_permissions(self) -> None:
        """Create/tighten the home 0700 and the idmap file 0600 (S43)."""
        home = self.path.parent
        os.makedirs(home, mode=0o700, exist_ok=True)
        os.chmod(home, 0o700)
        if not self.path.exists():
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            os.close(fd)
        os.chmod(self.path, 0o600)

    def save(self) -> None:
        """Persist the registry to disk (0600)."""
        self._ensure_permissions()
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self.entries, fh, ensure_ascii=False, indent=2, sort_keys=True)

    def get(self, uri: str) -> dict[str, str | bool | None] | None:
        """The record for ``uri``, or ``None`` when unknown."""
        return self.entries.get(uri)

    def set(
        self,
        uri: str,
        *,
        fingerprint: str | None = None,
        stale: bool = False,
    ) -> None:
        """Upsert ``uri``'s record and persist."""
        self.entries[uri] = {"fingerprint": fingerprint, "stale": stale}
        self.save()

    def mark_stale(self, uri: str) -> None:
        """Mark ``uri`` stale (preserving any known fingerprint) and persist."""
        existing = self.entries.get(uri, {"fingerprint": None})
        self.entries[uri] = {"fingerprint": existing.get("fingerprint"), "stale": True}
        self.save()


def classify_read_failure(
    kind: str,
    uri: str,
    idmap_path: str | os.PathLike[str] | None = None,
) -> str:
    """Classify a read-path failure (§8.6; S35).

    - ``"not_found"`` → mark ``uri`` stale in the idmap and return ``"stale"``
      (the URI is excluded from update-first candidates until rediscovered).
    - ``"permission_denied"`` → return the actionable message
      ``"permission denied on <uri> — request access on the platform"``
      (does NOT touch the idmap — the doc may still be live).
    - any other kind → ``"unknown-failure"`` (nothing recorded).
    """
    if kind == "not_found":
        IdMap(idmap_path).mark_stale(uri)
        return "stale"
    if kind == "permission_denied":
        return _PERMISSION_MESSAGE.format(uri=uri)
    return "unknown-failure"


# ---------------------------------------------------------------------------
# Dedupe + near-duplicate clustering (§7.2, §6.5; S37, S38)
# ---------------------------------------------------------------------------


@dataclass
class NearDupCluster:
    """Group of near-duplicate search results (§6.5; S38).

    Members carry their own metadata — per-member provenance needs nothing
    extra. Members are NEVER auto-merged or deleted (N8); merging is always a
    confirmed user action.
    """

    members: list[SearchResult] = field(default_factory=list)
    _overlap_cache: bool | None = field(default=None, init=False, repr=False)

    @property
    def overlapping(self) -> bool:
        """True when any pair of members shares an overlapping snippet (S56).

        Computed lazily on first access and cached.
        """
        if self._overlap_cache is None:
            self._overlap_cache = any(
                snippet_overlap(a, b) for a, b in combinations(self.members, 2)
            )
        return self._overlap_cache


def cluster_title(cluster: NearDupCluster) -> str:
    """Display title for a cluster: the FIRST member's title (§7.2)."""
    return cluster.members[0].metadata.title if cluster.members else ""


def cluster_uris(cluster: NearDupCluster) -> list[str]:
    """Member ``doc_uri``s in member order — the URIs proposals act on (§7.2)."""
    return [member.doc_uri for member in cluster.members]


def _title_similar(a: SearchResult, b: SearchResult) -> bool:
    """Near-duplicate test: normalized-title ``SequenceMatcher.ratio() >= 0.8``."""
    return (
        SequenceMatcher(None, _norm_text(a.metadata.title), _norm_text(b.metadata.title)).ratio()
        >= _NEAR_DUP_TITLE_RATIO
    )


def merge_and_deduplicate(
    results: Sequence[SearchResult],
) -> tuple[list[SearchResult], list[NearDupCluster]]:
    """Merge results and deduplicate (§7.2; S37, S38).

    Order of the input list is preserved for the merged stream. Rules:

    1. **Identical fingerprint** (``metadata.content_fingerprint`` non-``None``)
       → collapse: the FIRST result keeps; each later copy appends its
       ``doc_uri`` to the kept result's ``also_available_in`` (S37 → ONE
       option; callers build "Update all N copies (identical content)" from
       the kept uri + `also_available_in`).
    2. **Same ``doc_uri``** → keep the first; nothing is appended
       (``also_available_in`` lists *other* locations, never the doc itself).
    3. **Near-duplicates** (different fingerprints, normalized-title similarity
       ``>= 0.8``) → grouped into a :class:`NearDupCluster`; NEVER auto-merged
       or deleted (S38/N8). Clustered results remain on the merged stream AND
       appear as cluster members — nothing is dropped from ranking/display.

    Returns ``(merged, clusters)`` — the clusters are the second return so
    callers surface the "shown grouped" representation (S38).
    """
    groups: dict[str, str] = {}  # uri -> leader (first-surviving) uri
    kept: dict[str, SearchResult] = {}  # leader uri -> current result
    fp_first: dict[str, str] = {}  # content_fingerprint -> leader uri
    order: list[str] = []  # leader uris in first-encounter order

    for result in results:
        uri = result.doc_uri
        if uri in groups:
            # Same doc_uri duplicate → keep the first; also_available_in never
            # names the document itself.
            continue
        fp = result.metadata.content_fingerprint
        if fp is not None and fp in fp_first:
            # Fingerprint-identical copy (S37): fold under the first result;
            # every replace() rewrites the leader entry, so aliases never go stale.
            leader = fp_first[fp]
            groups[uri] = leader
            current = kept[leader]
            kept[leader] = replace(current, also_available_in=current.also_available_in + [uri])
            continue
        groups[uri] = uri
        kept[uri] = result
        order.append(uri)
        if fp is not None:
            fp_first[fp] = uri

    # One distinct result per surviving doc; kept[leader] already carries the
    # final also_available_in. The MERGED stream is exactly these results —
    # clustered or not, nothing is dropped from ranking/display.
    survivors = [kept[leader] for leader in order]
    index = {result.doc_uri: i for i, result in enumerate(survivors)}

    merged = list(survivors)
    clusters: list[NearDupCluster] = []
    assigned: set[str] = set()  # doc_uris already in a cluster

    for result in survivors:
        if result.doc_uri in assigned:
            continue
        match = next(
            (cluster for cluster in clusters if _title_similar(result, cluster.members[0])),
            None,
        )
        if match is not None:
            match.members.append(result)
            assigned.add(result.doc_uri)
            continue
        partner = next(
            (
                m
                for m in survivors
                if m.doc_uri not in assigned and m is not result and _title_similar(result, m)
            ),
            None,
        )
        if partner is not None:
            # Cluster members keep input (encounter) order; members[0] is the
            # earliest survivor, i.e. cluster_title() returns the first title.
            members = sorted([partner, result], key=lambda m: index[m.doc_uri])
            clusters.append(NearDupCluster(members=members))
            assigned.add(partner.doc_uri)
            assigned.add(result.doc_uri)

    return merged, clusters


# ---------------------------------------------------------------------------
# Snippet overlap + conflict detection (§6.5, §7.5; S55, S56)
# ---------------------------------------------------------------------------


def snippet_overlap(a: SearchResult, b: SearchResult, threshold: float = 0.6) -> bool:
    """True when the normalized snippets of ``a`` and ``b`` match at
    ``threshold`` (§6.5; S56 "overlapping content").

    Snippets are lowercased and whitespace-collapsed before comparison with
    ``difflib.SequenceMatcher.ratio()``. Missing or empty snippets never
    overlap. Snippet matches are ALWAYS flagged, never auto-merged.
    """
    if a.snippet is None or b.snippet is None:
        return False
    na, nb = _norm_text(a.snippet), _norm_text(b.snippet)
    if not na or not nb:
        return False
    return SequenceMatcher(None, na, nb).ratio() >= threshold


@dataclass
class Conflict:
    """A detected contradiction between search results (§7.5; S55).

    ``kind`` is the deterministic rule that fired (``"diverged-copy"`` /
    ``"stale-conflict"``). ``strategy`` is a RECOMMENDATION only — no
    resolution action executes without a confirmed user proposal (§5.6).
    ``detail`` is a deterministic, human-readable explanation.
    """

    uris: list[str]
    kind: str
    strategy: str
    detail: str


def detect_conflicts(
    results: Sequence[SearchResult],
    clusters: Sequence[NearDupCluster],
    strategies: Sequence[str] | None = None,
) -> list[Conflict]:
    """Deterministic fallback conflict detection (§7.5; S55).

    LLM-driven semantic conflict detection is the skill layer's job; this is
    the structural, deterministic baseline. Two rules:

    1. **diverged-copy**: members of a near-dup cluster sharing the SAME
       normalized title, DIFFERENT content fingerprints, and an overlapping
       snippet (S56) — copies that have diverged. Strategy = the FIRST
       configured strategy (callers pass
       ``Config.conflict_resolution["strategies"]``; when ``None``, the
       fallback is ``["link"]``).
    2. **stale-conflict** (§8.6): a ``doc_uri`` appearing both with
       ``access == "stale"`` and ``access == "ok"`` — a stale copy
       contradicting the live one. Strategy = ``"correct"``.

    Detection + recommendation only — nothing is executed here.
    """
    resolved = list(strategies) if strategies else ["link"]

    conflicts: list[Conflict] = []

    for cluster in clusters:
        for a, b in combinations(cluster.members, 2):
            fp_a, fp_b = a.metadata.content_fingerprint, b.metadata.content_fingerprint
            if fp_a == fp_b:  # identical (or both-absent) fingerprints: not a divergence pair
                continue
            if _norm_text(a.metadata.title) != _norm_text(b.metadata.title):
                continue
            if not snippet_overlap(a, b):
                continue
            conflicts.append(
                Conflict(
                    uris=[a.doc_uri, b.doc_uri],
                    kind="diverged-copy",
                    strategy=resolved[0],
                    detail=(
                        f"copies of {a.metadata.title!r} share a title but their content has "
                        f"diverged: {a.doc_uri} vs {b.doc_uri}"
                    ),
                )
            )

    live_and_stale: dict[str, list[str]] = {}
    for result in results:
        if result.access in ("stale", "ok"):
            live_and_stale.setdefault(result.doc_uri, []).append(result.access)

    for uri in sorted(live_and_stale):
        accesses = set(live_and_stale[uri])
        if accesses == {"stale", "ok"}:
            conflicts.append(
                Conflict(
                    uris=[uri],
                    kind="stale-conflict",
                    strategy="correct",
                    detail=f"stale copy of {uri} contradicts the live result — reconcile via 'correct'",
                )
            )

    return conflicts


def has_conflicts(conflicts: Sequence[Conflict]) -> bool:
    """True when any conflict was reported — callers map this to exit codes (S55)."""
    return bool(conflicts)


# ---------------------------------------------------------------------------
# Read-path verification + bulk staleness (§8.6; S35, S36)
# ---------------------------------------------------------------------------


def _backend_index(backends: Mapping[str, Any] | Iterable[Any]) -> dict[str, Any]:
    """Normalize the ``backends`` argument to a name → backend mapping."""
    if isinstance(backends, Mapping):
        return dict(backends)
    return {getattr(backend, "name", ""): backend for backend in backends}


def _backend_from_uri(uri: str) -> str:
    """Fallback backend name from a canonical ``kgent://<backend>/<id>`` uri."""
    try:
        name, _ = parse_uri(uri)
    except ConfigError:
        return ""
    return name


def verify_results(
    results: Sequence[SearchResult],
    backends: Mapping[str, Any] | Iterable[Any],
    *,
    idmap_path: str | os.PathLike[str] | None = None,
) -> tuple[list[SearchResult], list[dict[str, str | int]]]:
    """Re-read every result on its backend and demote failures (§8.6; S35).

    For each result, ``backends`` (a ``{name: backend}`` mapping or an iterable
    of backends exposing ``.name``) is probed with ``backend.read_document(uri)``:

    - ``LookupError`` (incl. ``KeyError``) → ``access="stale"``, the URI is
      marked stale in the idmap via :func:`classify_read_failure` (S35), and a
      ``not_found`` failure is recorded.
    - ``PermissionError`` → ``access="denied"`` (idmap untouched) and a
      ``permission_denied`` failure carries the actionable access-request
      message.
    - successful read → ``access="ok"`` unchanged.
    - any other exception → ``unknown-failure`` recorded; the result is left in
      place (it cannot be classified, but is never silently dropped).
    - backends missing from the registry (e.g. read-only adapters without a
      verifier) → ``unknown-failure`` recorded, result left in place.

    Results are NEVER dropped: failures are flagged on the result via the
    ``access`` field and reported in the returned ``failures`` list. Each
    failure record carries the backend's probed-result ``"total"`` so
    :func:`assess_staleness` can compute per-backend ratios.
    """
    index = _backend_index(backends)

    totals: dict[str, int] = {}
    for result in results:
        name = result.metadata.backend or _backend_from_uri(result.doc_uri)
        totals[name] = totals.get(name, 0) + 1

    verified: list[SearchResult] = []
    failures: list[dict[str, str | int]] = []

    for result in results:
        name = result.metadata.backend or _backend_from_uri(result.doc_uri)
        backend = index.get(name)
        if backend is None:
            failures.append(
                {
                    "uri": result.doc_uri,
                    "backend": name,
                    "kind": "unknown-failure",
                    "error": f"backend {name!r} not available for verification",
                    "total": totals.get(name, 1),
                }
            )
            verified.append(result)
            continue
        try:
            backend.read_document(result.doc_uri)
        except LookupError as exc:
            verified.append(replace(result, access="stale"))
            classify_read_failure("not_found", result.doc_uri, idmap_path)
            failures.append(
                {
                    "uri": result.doc_uri,
                    "backend": name,
                    "kind": "not_found",
                    "error": f"not found on {name}: {exc}",
                    "total": totals.get(name, 1),
                }
            )
            continue
        except PermissionError:
            verified.append(replace(result, access="denied"))
            message = classify_read_failure("permission_denied", result.doc_uri)
            failures.append(
                {
                    "uri": result.doc_uri,
                    "backend": name,
                    "kind": "permission_denied",
                    "error": message,
                    "total": totals.get(name, 1),
                }
            )
            continue
        except Exception as exc:  # noqa: BLE001 — probe failures are classified, never dropped
            failures.append(
                {
                    "uri": result.doc_uri,
                    "backend": name,
                    "kind": "unknown-failure",
                    "error": f"{exc.__class__.__name__}: {exc}",
                    "total": totals.get(name, 1),
                }
            )
            verified.append(result)
            continue
        verified.append(result)

    return verified, failures


def assess_staleness(
    failures_per_backend: Mapping[str, Sequence[Mapping[str, object]]]
    | Sequence[Mapping[str, object]],
    warning_threshold: float = 0.2,
) -> tuple[set[str], list[str]]:
    """Compute bulk staleness: a backend whose verification failure ratio is
    STRICTLY above ``warning_threshold`` (default 20%) is added to the returned
    ``invalidate`` set, with a warning naming it (§8.6; S36).

    The CALLER (the capability-cache owner, Task 3.x) performs the actual
    invalidation — this only computes + warns.

    ``failures_per_backend`` is either the flat failure list from
    :func:`verify_results` (each record carries ``"backend"`` and ``"total"`` =
    results probed for that backend) or a ``{backend: [records…]}`` mapping.
    When a backend's records carry no ``"total"``, the fraction defaults to
    ``len(records) / len(records)`` — conservative, so a failing backend is
    flagged rather than missed.
    """
    if warning_threshold < 0:
        raise ValueError("warning_threshold must be >= 0")

    if isinstance(failures_per_backend, Mapping):
        grouped: dict[str, list[Mapping[str, object]]] = {
            str(name): list(records) for name, records in failures_per_backend.items()
        }
    else:
        grouped = {}
        for record in failures_per_backend:
            grouped.setdefault(str(record.get("backend", "")), []).append(record)

    invalidate: set[str] = set()
    warnings: list[str] = []
    for backend in sorted(grouped):
        records = grouped[backend]
        failed = len(records)
        totals: list[int] = []
        for record in records:
            total = record.get("total")
            if isinstance(total, int):
                totals.append(total)
        total = totals[0] if totals else failed
        if total <= 0:
            continue
        if failed / total > warning_threshold:
            invalidate.add(backend)
            warnings.append(
                f"{backend}: {failed}/{total} results failed verification "
                f"(>{warning_threshold:.0%}) — refreshing capability cache"
            )
    return invalidate, warnings
