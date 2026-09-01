"""Knowledge-storage skill (§5.1–§5.3, §6.1–§6.5, S60–S64; wiki: S83–S84).

Orchestrates context gathering, update-first search, proposal building with
provenance, and returns a :class:`WriteProposal` for the caller to confirm
and execute via the Router.

Wiki nodes (§6.10) are first-class targets: update-first search covers wiki
nodes and flat docs (a wiki match is updated in place as a wiki node, N24),
and when the resolved target is a knowledge space the proposal carries
``wiki_space`` + a ``parent_node_token`` obtained ONLY from search or space
listing — never guessed (S83/N22). When nothing determines wiki-vs-doc, the
skill asks the user (S84) and records the decision in provenance.
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
    2. Search for matching docs/blog/wiki nodes (update-first, S61; wiki S83).
    3. Resolve the target type (wiki-vs-doc) — asking when undetermined (S84).
    4. Build the proposal with provenance; wiki creates resolve space + a
       fitting parent from space listing (S83 — never guessed tokens).
    5. Return the proposal — caller confirms + executes via Router (S64).
    """
    conversation = context.get("conversation", "")
    preferences = context.get("preferences", {})
    explicit_input = context.get("explicit_input", "")
    request_lower = f"{user_request} {explicit_input}".lower()

    # Resolution priority (S67): explicit input > preferences > defaults
    target_backend: str
    target_source: str
    explicit_backend = (
        _extract_backend_from_input(explicit_input, router) if explicit_input else None
    )
    if explicit_backend is not None:
        target_backend = explicit_backend
        target_source = "explicit user input"
    elif preferences.get("target_backend"):
        target_backend = preferences["target_backend"]
        target_source = "preferences"
    else:
        target_backend = _default_backend(router)
        target_source = "config default"

    title = _extract_title(user_request)

    # Update-first: search for matching docs (covers wiki nodes by default)
    match_uris, match_type = _search_matches(router, title)

    # Resolve wiki-vs-doc (S84): explicit mention > match type > preference >
    # user choice (asked) > config default.
    target_type: str
    target_type_source: str
    if _mentions_knowledge_space(request_lower):
        target_type = "wiki"
        target_type_source = "explicit user input"
    elif match_type is not None:
        target_type = match_type
        target_type_source = "match"
    elif preferences.get("target_type") in ("wiki", "doc"):
        target_type = preferences["target_type"]
        target_type_source = "preferences"
    elif context.get("target_type") in ("wiki", "doc"):
        # S84: the skill asked and the caller recorded the user's choice.
        target_type = context["target_type"]
        target_type_source = str(context.get("target_type_source", "user choice"))
    else:
        target_type = "doc"
        target_type_source = "config default"

    provenance: dict[str, str] = {
        "intent": "update" if match_uris else "create",
        "target": target_backend,
        "target_source": target_source,
        "target_type": target_type,
        "target_type_source": target_type_source,
    }
    if conversation:
        provenance["conversation"] = conversation
    if preferences:
        provenance["preferences"] = str(preferences)
    if explicit_input:
        provenance["explicit_input"] = explicit_input

    if match_uris:
        # Update the first match in place (a wiki match stays a wiki node —
        # hierarchy position is invariant under update, N24).
        primary_uri = match_uris[0]
        backend_name = _backend_from_uri(primary_uri)
        return WriteProposal(
            operation="update",
            targets=[(backend_name, primary_uri)],
            title=title,
            content=user_request,
            provenance=provenance,
            match_uris=match_uris,
        )

    # Create. Wiki creates resolve space + a parent whose token is validated
    # against the space listing (S83 — never guessed, N22).
    wiki_space = context.get("wiki_space")
    parent_token: str | None = context.get("parent_node_token")
    if target_type == "wiki":
        if wiki_space is None:
            wiki_space = _resolve_space(router, target_backend, provenance)
        if wiki_space is not None:
            parent_token = _resolve_parent(
                router,
                target_backend,
                str(wiki_space),
                context_parent=parent_token,
                provenance=provenance,
            )
    return WriteProposal(
        operation="create",
        targets=[(target_backend, None)],
        title=title,
        content=user_request,
        provenance=provenance,
        match_uris=match_uris,
        wiki_space=str(wiki_space) if wiki_space is not None else None,
        parent_node_token=parent_token,
    )


def _mentions_knowledge_space(text: str) -> bool:
    """Wiki intent markers: 'wiki', 'knowledge space', '知识库' (S84)."""
    return any(marker in text for marker in ("wiki", "knowledge space", "知识库"))


def _search_matches(router: Router, title: str) -> tuple[list[str], str | None]:
    """Update-first match search — flat docs AND wiki nodes (§6.10, S83).

    Returns ``(match_uris, match_type)`` where ``match_type`` is the first
    match's ``node_type`` (``"doc"`` | ``"wiki_node"``) — an update follows
    the match's type so a wiki match updates as a wiki node, in place (N24).
    """
    match_uris: list[str] = []
    match_type: str | None = None
    for backend_name, backend in router.backends.items():
        try:
            search = getattr(backend, "search", None)
            if callable(search):
                results: Any = search(title, mode="keyword", top_k=10, timeout=10.0)
            else:
                results = list(getattr(backend, "docs", {}).values())
            for result in results:
                meta = getattr(result, "metadata", result)
                doc_title = getattr(meta, "title", None)
                if doc_title and title and _title_matches(str(doc_title), title):
                    uri = getattr(result, "doc_uri", "")
                    if uri:
                        match_uris.append(uri)
                        if match_type is None:
                            match_type = getattr(result, "node_type", None) or getattr(
                                meta, "node_type", "doc"
                            )
        except Exception:  # noqa: BLE001 — per-backend search is best-effort
            continue
    return match_uris, str(match_type) if match_type is not None else None


def _resolve_space(router: Router, backend_name: str, provenance: dict[str, str]) -> str | None:
    """Resolve the target knowledge space from a listing — never guessed (S83).

    Uses the space the caller already resolved (``wiki_space`` context) or
    lists spaces and picks the single one; several → the caller asks which.
    """
    backend = router.backends.get(backend_name)
    if backend is None:
        return None
    try:
        listed = backend.list_wiki_spaces()
    except Exception:  # noqa: BLE001 — listing is best-effort
        return None
    if not listed:
        provenance["space"] = "create_required"  # caller creates via kgent wiki spaces create
        return None
    if len(listed) == 1:
        provenance["space"] = "only space"
        return str(listed[0].get("space_id"))
    provenance["space"] = "multiple — user asked"
    return None


def _resolve_parent(
    router: Router,
    backend_name: str,
    space_id: str,
    *,
    context_parent: str | None,
    provenance: dict[str, str],
) -> str | None:
    """Resolve the parent node for a wiki create (S83/N22).

    The caller (agent) proposes a parent based on topical fit against the
    space listing — recorded in ``context_parent``. The token is ONLY used
    when it appears in the space listing (search or space listing is the sole
    source of parent tokens); a token absent from the listing is a guessed
    placement and is dropped (N22), falling back to the space root.
    """
    listing = _list_nodes(router, backend_name, space_id)
    if context_parent is None:
        provenance["parent"] = "root (no parent chosen)"
        return None
    for meta in listing:
        if _node_token(meta) == context_parent:
            title = getattr(meta, "title", "") or ""
            provenance["parent"] = f"{title} ({context_parent})" if title else f"({context_parent})"
            return context_parent
    provenance["parent"] = f"rejected guessed parent token {context_parent} — root"
    return None


def _list_nodes(router: Router, backend_name: str, space_id: str) -> list[Any]:
    """Best-effort full listing of a space's top-level nodes (§6.10)."""
    backend = router.backends.get(backend_name)
    if backend is None or not hasattr(backend, "list_wiki_nodes"):
        return []
    try:
        listed = list(backend.list_wiki_nodes(space_id))
    except Exception:  # noqa: BLE001 — listing is best-effort
        return []
    return listed


def _node_token(meta: Any) -> str:
    uri = getattr(meta, "doc_uri", "") or ""
    return str(uri.rsplit("/", 1)[-1]) if uri else ""


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


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


def _extract_backend_from_input(text: str, router: Router) -> str | None:
    """Extract a backend name from explicit user input (e.g., 'store to dingtalk')."""
    text_lower = text.lower()
    for backend_name in router.backends:
        if backend_name.lower() in text_lower:
            return backend_name
    return None


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
