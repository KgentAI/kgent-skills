"""Fidelity classes + lossy-conversion warnings (§6.9, S49, S50; N11, P1).

The canonical interchange format is Markdown body + ``DocumentMetadata``
sidecar (:mod:`kgent.types`, §3.8). Adapters convert native ↔ canonical at
the boundary; the conversion is **declared** per adapter per direction, and
loss is never silent (N11):

- :data:`FIDELITY_REGISTRY` declares ``lossless | lossy`` per direction.
  An adapter/direction with no declaration is treated as **lossless** (documented
  default), but the *declared* set drives warnings.
- :func:`to_canonical` / :func:`from_canonical` translate known native
  elements that have no Markdown equivalent into explicit
  ``[unsupported: <name>]`` placeholders and report them as *degraded
  elements* — content is never invented and never silently dropped. The
  placeholder itself survives the write content so the user sees it in the
  proposal diff (§6.9).
- :func:`lossy_warning_snippet` builds the proposal warning ("3 elements
  have no Markdown equivalent: vote block, diagram, comment thread"); the
  confirmation gate for a lossy write is the caller's responsibility (S49).

Only elements an adapter **declares** as degraded are converted into
placeholders: a ``[native: foo]`` marker whose name is not in the declared
degraded set passes through untouched rather than being fabricated into an
``[unsupported: ...]`` claim. On lossless directions the conversion is the
identity function with an empty degraded list (P1 round-trip).
"""

from __future__ import annotations

import re
from typing import Literal, TypedDict

__all__ = [
    "FIDELITY_REGISTRY",
    "Direction",
    "FidelityClass",
    "FidelityDecl",
    "declare_lossy",
    "declared_lossy",
    "from_canonical",
    "is_lossy",
    "lossy_warning_snippet",
    "to_canonical",
]

FidelityClass = Literal["lossless", "lossy"]

#: Conversion directions relative to the canonical format (§6.9).
Direction = Literal["native_to_canonical", "canonical_to_native"]

class FidelityDecl(TypedDict):
    """Fidelity declaration for one adapter + direction (§6.9)."""

    fidelity: FidelityClass
    #: Human-readable names of elements that degrade on this direction
    #: (e.g. ``"vote block"``, ``"diagram"``, ``"comment thread"``).
    degraded_elements: list[str]


#: Native marker directive: ``[native: <name>]``.
_NATIVE_MARKER = re.compile(r"\[native:\s*([^\]]+?)\s*\]")
#: Canonical placeholder for an element with no Markdown equivalent.
_UNSUPPORTED_PLACEHOLDER = re.compile(r"\[unsupported:\s*([^\]]+?)\s*\]")

_LARK_DEGRADED = ["vote block", "diagram", "comment thread"]


def _lossless() -> FidelityDecl:
    return {"fidelity": "lossless", "degraded_elements": []}


def _lossy(elements: list[str]) -> FidelityDecl:
    return {"fidelity": "lossy", "degraded_elements": list(elements)}


#: Per-adapter, per-direction fidelity declarations. Directions not present
#: (or adapters not present at all) default to lossless.
FIDELITY_REGISTRY: dict[str, dict[Direction, FidelityDecl]] = {
    # Lark docs can carry embeds/votes/comment threads with no Markdown
    # equivalent -> both directions declared lossy (§6.9, S49).
    "lark": {
        "native_to_canonical": _lossy(_LARK_DEGRADED),
        "canonical_to_native": _lossy(_LARK_DEGRADED),
    },
    # DingTalk / WeCom treat Markdown as their native body format, so the
    # canonical body converts losslessly in both directions.
    "dingtalk": {
        "native_to_canonical": _lossless(),
        "canonical_to_native": _lossless(),
    },
    "wecom": {
        "native_to_canonical": _lossless(),
        "canonical_to_native": _lossless(),
    },
}


def declare_lossy(adapter_name: str, direction: Direction, elements: list[str]) -> list[str]:
    """Register (or override) a **lossy** declaration for ``adapter_name``.

    Primarily a test hook for constructing/overriding declarations directly;
    returns the degraded-elements list. Callers that need a non-lossy
    declaration can write to :data:`FIDELITY_REGISTRY` directly.
    """
    decl = _lossy(elements)
    FIDELITY_REGISTRY.setdefault(adapter_name, {})[direction] = decl
    return decl["degraded_elements"]


def declared_lossy(adapter_name: str, direction: Direction) -> FidelityDecl | None:
    """The declaration for ``adapter_name`` + ``direction``, or ``None``.

    Returns ``None`` both when the adapter/direction is undeclared and when a
    declaration is explicitly **lossless** — either way the effective behavior
    is lossless (documented default).
    """
    decl = FIDELITY_REGISTRY.get(adapter_name, {}).get(direction)
    if decl is None or decl["fidelity"] != "lossy":
        return None
    return decl


def is_lossy(adapter_name: str, direction: Direction) -> bool:
    """Whether the adapter declares this direction lossy (default False)."""
    return declared_lossy(adapter_name, direction) is not None


def _convert_declared(
    content: str,
    marker: re.Pattern[str],
    declared: list[str],
) -> tuple[str, list[str]]:
    """Rewrite declared-native markers into placeholders, reporting each hit.

    Only names present in ``declared`` (the adapter's declared degraded
    elements) are rewritten; anything else passes through byte-for-byte.
    """
    degraded: list[str] = []
    out: list[str] = []
    pos = 0
    names: set[str] = set(declared)
    for match in marker.finditer(content):
        out.append(content[pos : match.start()])
        name = match.group(1).strip()
        if name in names:
            out.append(f"[unsupported: {name}]")
            degraded.append(name)
        else:
            out.append(match.group(0))
        pos = match.end()
    out.append(content[pos:])
    return "".join(out), degraded


def to_canonical(native_content: str, adapter_name: str) -> tuple[str, list[str]]:
    """Convert native content → canonical Markdown for ``adapter_name``.

    Returns ``(canonical_md, degraded_elements_found)``. On a lossy
    ``native_to_canonical`` direction, known native markers (e.g.
    ``[native: vote block]``) become explicit ``[unsupported: <name>]``
    placeholders and are recorded (N11). On a lossless direction the native
    content IS the canonical body — identity with an empty degraded list
    (P1 round-trip). Unknown content always passes through unchanged.
    """
    decl = FIDELITY_REGISTRY.get(adapter_name, {}).get("native_to_canonical")
    if decl is None or decl["fidelity"] != "lossy":
        return native_content, []
    return _convert_declared(native_content, _NATIVE_MARKER, decl["degraded_elements"])


def from_canonical(canonical_md: str, adapter_name: str) -> tuple[str, list[str]]:
    """Convert canonical Markdown → native content for ``adapter_name``.

    Mirror of :func:`to_canonical` for the outward direction. Every
    ``[unsupported: <name>]`` placeholder already in the canonical body is an
    element with no Markdown equivalent, so on a lossy
    ``canonical_to_native`` destination it is reported as degraded — and the
    placeholder text itself is retained (never silently dropped, N11).
    Lossless destinations pass through with an empty degraded list.
    """
    decl = FIDELITY_REGISTRY.get(adapter_name, {}).get("canonical_to_native")
    if decl is None or decl["fidelity"] != "lossy":
        return canonical_md, []
    degraded = [m.group(1).strip() for m in _UNSUPPORTED_PLACEHOLDER.finditer(canonical_md)]
    return canonical_md, degraded


def lossy_warning_snippet(elements: list[str]) -> str:
    """Proposal-warning text for degraded elements, e.g.:

    ``"3 elements have no Markdown equivalent: vote block, diagram, comment
    thread"``. Returns ``""`` when nothing degrades. Requiring the user's
    confirmation is the caller's job (S49).
    """
    if not elements:
        return ""
    names = ", ".join(elements)
    if len(elements) == 1:
        return f"1 element has no Markdown equivalent: {names}"
    return f"{len(elements)} elements have no Markdown equivalent: {names}"