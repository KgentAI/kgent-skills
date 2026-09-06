"""Sensitivity tiers and zone rules (§2.5, S13–S16).

Content and backends both carry trust labels; the router enforces the
combination. Tiers are ordered ``public < internal < confidential``; the
router hard-rejects a ``confidential`` write to an ``external``-zone backend
(never silently reroutes), enforces per-content_type floors as minimums, and
warns once per session when a search query is fanned out to ``external``
backends (query leakage).

Sensitivity assignment itself is best-effort classification (§6.3): the
:func:`analyze_sensitivity` here is a deterministic stub that defaults to
``internal`` and fails safe on low confidence. Real (LLM-assisted)
classification is injected later by the skill layer — this module only
establishes the tier ladder and the fallback semantics, and ``content`` is
kept in the signature so the injected classifier can use it without changing
call sites.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kgent.errors import PolicyError

if TYPE_CHECKING:
    from kgent.config.schema import Config

__all__ = [
    "TIER_ORDER",
    "analyze_sensitivity",
    "backend_trust_zone",
    "enforce_floor",
    "enforce_zone",
    "warn_query_leakage",
]

#: Ordered sensitivity tiers; higher rank = more sensitive (§2.5).
TIER_ORDER: dict[str, int] = {"public": 0, "internal": 1, "confidential": 2}

#: Rank → tier lookup shared by raising and floor comparisons.
_TIERS_BY_RANK: tuple[str, ...] = tuple(sorted(TIER_ORDER, key=TIER_ORDER.__getitem__))

_UNCERTAINTY_THRESHOLD = 0.5
_UNCERTAIN_PROVENANCE = "classifier: uncertain, raised"
_DEFAULT_TIER = "internal"

#: Marker used in the caller's per-session set so the leakage warning fires
#: exactly once per session (S16). The session set may hold other markers.
_LEAK_WARNED = "query_leakage_warned"


def analyze_sensitivity(content: str, confidence: float) -> tuple[str, float, str]:
    """Assign a sensitivity tier (best-effort, fails safe).

    Deterministic stub: ``content`` is unused (real classification is
    LLM-assist injected later by the skill layer) and the base tier defaults
    to ``internal``. When ``confidence < 0.5`` the tier is raised to the next
    higher one and the provenance records ``"classifier: uncertain, raised"``
    (S14) — uncertainty resolves to the higher tier, never the lower one
    (fail-safe, §2.5 rule 4). The top tier cannot be raised further.

    Returns ``(tier, confidence, provenance)``.
    """
    tier = _DEFAULT_TIER
    provenance = "deterministic stub: defaulted to internal (LLM classifier injected later)"
    if confidence < _UNCERTAINTY_THRESHOLD:
        rank = TIER_ORDER[tier]
        if rank < len(TIER_ORDER) - 1:
            tier = _TIERS_BY_RANK[rank + 1]
        provenance = _UNCERTAIN_PROVENANCE
    return tier, confidence, provenance


def enforce_floor(tier: str, content_type: str, floors: dict[str, str]) -> tuple[str, str]:
    """Enforce a per-content_type sensitivity floor as a minimum (S15, §2.5).

    When ``floors[content_type]`` ranks higher than ``tier``, the returned
    tier is raised to the floor and the note records the applied floor
    (``"floor applied: <content_type> ≥ <floor>"``). Otherwise the tier is
    returned unchanged with an empty note.

    Returns ``(tier, note)``.
    """
    floor = floors.get(content_type)
    if floor is not None and TIER_ORDER[floor] > TIER_ORDER[tier]:
        return floor, f"floor applied: {content_type} ≥ {floor}"
    return tier, ""


def backend_trust_zone(config: Config, backend_name: str) -> str:
    """Trust zone for ``backend_name``, read from config — the zone's source.

    Adapters do not carry the label: the real CLI-backed adapters
    (:class:`~kgent.adapters.lark.LarkAdapter` and siblings) expose no
    ``trust_zone``, so reading it off the adapter object crashes on a real
    config (only test fakes have the field). ``config/schema.py`` defaults +
    validates ``backends.<name>.trust_zone`` (``external`` unless stated) and
    ``kgent setup`` writes it, so config is where route and the write gate
    must read the zone from — one shared helper, no second source. Anything
    unexpected falls closed to the schema default ``external``.
    """
    spec = config.backends.get(backend_name)
    if not isinstance(spec, dict):
        return "external"
    zone = spec.get("trust_zone")
    return zone if isinstance(zone, str) else "external"


def enforce_zone(
    tier: str,
    backend_zone: str,
    backend_name: str,
    *,
    fallback_chain: bool = False,
) -> None:
    """Enforce write-destination zone rules for ``tier`` (§2.5 rule 1).

    ``confidential`` content may only be written to ``internal``-zone
    backends; any other destination is hard-rejected with a
    :class:`~kgent.errors.PolicyError` naming the exact tier and backend
    (S13, N4). The rule applies to fallback targets too — ``fallback_chain``
    marks a fallback-destination write so callers can report context; it does
    not relax the check.
    """
    if tier == "confidential" and backend_zone != "internal":
        context = "fallback target " if fallback_chain else ""
        raise PolicyError(
            f"tier 'confidential' cannot be written to {context}external-zone backend '{backend_name}'"
        )


def warn_query_leakage(targets: list[tuple[str, str]], session: set[str]) -> list[str]:
    """Warn once per session when a query fans out to ``external`` backends.

    ``targets`` is a list of ``(backend, trust_zone)`` tuples. When any
    target is in the ``external`` zone, returns a warning naming those
    backends; the marker is recorded in ``session`` so the warning fires at
    most once per session (S16). No external targets returns ``[]`` and
    leaves the session unmarked.

    The warning is advisory only — fan-out still executes with the explicit
    ``--backends`` selection; ``confidential`` content remains blocked by
    :func:`enforce_zone` regardless.
    """
    if _LEAK_WARNED in session:
        return []
    externals = [backend for backend, zone in targets if zone == "external"]
    if not externals:
        return []
    session.add(_LEAK_WARNED)
    return [f"query sent to external-zone backend(s): {', '.join(externals)}"]
