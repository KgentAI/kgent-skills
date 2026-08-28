"""Knowledge-storage skill (§5.1–§5.3, §6.1–§6.5, S60–S64).

Orchestrates context gathering, update-first search, proposal building with
provenance, and returns a :class:`WriteProposal` for the caller to confirm
and execute via the Router.
"""

from __future__ import annotations

from typing import Any

from kgent.router.core import Router
from kgent.types import WriteProposal

__all__ = ["store_workflow"]


def store_workflow(
    user_request: str,
    context: dict[str, Any],
    router: Router,
) -> WriteProposal:
    """Build a write proposal from ``user_request`` + ``context`` (S60–S64).

    1. Gather context: conversation, preferences, existing docs (S60).
    2. Search for matching docs (update-first, S61).
    3. Build proposal with provenance (S60, S63).
    4. Return the proposal — caller confirms + executes via Router (S64).

    Backend-agnostic (S65): uses Router primitives only.
    """
    conversation = context.get("conversation", "")
    preferences = context.get("preferences", {})
    target_backend = preferences.get("target_backend") or _default_backend(router)

    # Extract title from user request (simple heuristic)
    title = _extract_title(user_request)

    # Update-first: search for matching docs (S61)
    match_uris: list[str] = []
    for backend_name, backend in router.backends.items():
        for uri, doc in backend.docs.items():
            if doc.title and title and _title_matches(doc.title, title):
                match_uris.append(uri)

    # Determine operation and targets
    if match_uris:
        operation = "update"
        # Pick the first match (or let caller choose via S62)
        primary_uri = match_uris[0]
        backend_name = _backend_from_uri(primary_uri)
        targets: list[tuple[str, str | None]] = [(backend_name, primary_uri)]
        intent = "update"
    else:
        operation = "create"
        targets = [(target_backend, None)]
        intent = "create"

    # Build provenance (S60)
    provenance: dict[str, str] = {
        "intent": intent,
        "target": target_backend,
    }
    if conversation:
        provenance["conversation"] = conversation
    if preferences:
        provenance["preferences"] = str(preferences)

    return WriteProposal(
        operation=operation,
        targets=targets,
        title=title,
        content=user_request,
        provenance=provenance,
        match_uris=match_uris,
    )


def _default_backend(router: Router) -> str:
    """Return the first enabled backend from config."""
    defaults = router.config.defaults
    default_backends = defaults.get("default_backends", [])
    if isinstance(default_backends, list) and default_backends:
        return str(default_backends[0])
    # Fallback: first backend in config
    for name in router.config.backends:
        return str(name)
    return "lark"


def _extract_title(request: str) -> str:
    """Extract a title from the user request (simple heuristic)."""
    # Look for quoted strings or "save X" patterns
    if "'" in request:
        start = request.index("'") + 1
        end = request.index("'", start)
        return request[start:end]
    if '"' in request:
        start = request.index('"') + 1
        end = request.index('"', start)
        return request[start:end]
    # Fallback: first few words
    words = request.split()[:5]
    return " ".join(words) if words else request


def _title_matches(doc_title: str, request_title: str) -> bool:
    """Check if ``doc_title`` matches ``request_title`` (case-insensitive)."""
    return doc_title.lower() in request_title.lower() or request_title.lower() in doc_title.lower()


def _backend_from_uri(uri: str) -> str:
    """Extract backend name from a kgent:// URI."""
    if uri.startswith("kgent://"):
        parts = uri[8:].split("/")
        return parts[0]
    return "lark"
