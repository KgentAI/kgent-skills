"""Routing: backend resolution + structured routing intent (§1.5, §4.1–§4.3).

``resolve_backends`` returns the ordered list of backend names to route an
operation to, following the precedence chain (first match wins):

1. Explicit selection (``selection`` / ``--backends``, §4.2 grammar).
2. Smart rules (first matching rule wins; only when ``routing_mode == "smart"``).
3. Content-type mapping (when configured mode, or smart rules matched nothing).
4. ``defaults.default_backends``.

§4.2 selection grammar: ``all`` (alias of ``all_enabled``), ``all_enabled``
(enabled backends with the required capability), ``all_configured`` (the
steps 2–4 result for this operation), or an explicit ``name[,name]*`` list
(unknown name raises :class:`~kgent.errors.ConfigError`).

When selection is omitted, writes default to ``all_configured`` and searches
default to ``all_enabled``; ``read`` is single-document and out of scope here
(resolves to the explicit document backend when available, else ``[]``).

``resolve_intent`` wraps the chain in a structured :class:`RoutingIntent`
(§1.5): each resolved backend is paired with its adapter (platform skill
preferred over CLI over MCP — S59) and the operations' capability needs, and
write intents carry policy-gate descriptors for the agent loop. The router
never executes writes; it returns intent only (S58).
"""

from __future__ import annotations

from typing import Any

from kgent.config.schema import Config
from kgent.errors import ConfigError
from kgent.types import BackendResolution, PolicyGate, RoutingIntent, WriteProposal
from kgent.uri import parse_uri

__all__ = ["resolve_backends", "resolve_intent"]

# Operations that default to "all_configured" (steps 2–4) when no selection
# is given. Search defaults to "all_enabled". Read is out of scope.
_WRITE_DEFAULT_OPS = frozenset({"create", "update", "delete", "archive", "unarchive", "store"})

# Single-document operations: the document's own backend (from its URI, §3.6)
# wins over routing when no explicit selection is given (§1.5).
_SINGLE_DOC_OPS = frozenset({"read", "update", "delete", "archive", "unarchive"})

# Document-storage feature each storage operation requires; None means any
# storage-capable backend suffices.
_STORAGE_FEATURE: dict[str, str | None] = {
    "create": None,
    "update": None,
    "store": None,
    "delete": "delete",
    "archive": "archive",
    "unarchive": "unarchive",
}


def capabilities_needed(operation: str) -> list[str]:
    """Capability keys required for ``operation`` (§1.5 ``capabilities_needed``).

    Shared by :func:`resolve_backends` (capability gating for ``all_enabled``
    and smart-rule backends) and :func:`resolve_intent` (adapter preference,
    S59), so both use one capability-need calculator.

    Group-level keys (``document_storage``, ``document_search``) gate on the
    group's ``supported`` flag; feature-level keys (``document_storage.delete``,
    ``document_storage.archive``, ``document_storage.unarchive``) additionally
    gate on membership in the storage feature list.
    """
    if operation == "search":
        return ["document_search"]
    if operation not in _STORAGE_FEATURE:
        return []
    feature = _STORAGE_FEATURE[operation]
    if feature is None:
        return ["document_storage"]
    return ["document_storage", f"document_storage.{feature}"]


def resolve_backends(
    config: Config,
    *,
    selection: str | None,
    operation: str,
    content_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> list[str]:
    """Resolve the ordered backend names for ``operation`` under §4.1."""
    names, _ = _resolve_targets(config, selection, operation, content_type, metadata)
    return names


def _resolve_targets(
    config: Config,
    selection: str | None,
    operation: str,
    content_type: str | None,
    metadata: dict[str, Any] | None,
) -> tuple[list[str], str]:
    """Ordered backend names plus the precedence step that produced them.

    Both :func:`resolve_backends` (which drops the step) and
    :func:`resolve_intent` (which records it as provenance) share this, so
    provenance never duplicates the precedence logic.
    """
    if selection is not None:
        return _resolve_selection(config, selection, operation, content_type, metadata), "explicit"
    if operation == "read":
        doc_backend = _read_doc_backend(metadata)
        return ([doc_backend] if doc_backend else []), "doc_uri"
    if operation == "search":
        return _all_enabled(config, operation), "all_enabled"
    return _resolve_chain(config, operation, content_type, metadata)


def resolve_intent(
    config: Config,
    operation: str,
    *,
    doc_uri: str | None = None,
    query: str | None = None,
    selection: str | None = None,
    content_type: str | None = None,
    proposal: WriteProposal | None = None,
) -> RoutingIntent:
    """Build a structured :class:`RoutingIntent` for ``operation`` (§1.5).

    The router never executes writes — it returns targets (backend + adapter
    + capability needs), policy-gate descriptors, and provenance for the
    agent loop to consume (S58).

    Targets follow the §4.1 precedence chain via :func:`resolve_backends`;
    for single-document operations with ``doc_uri`` and no explicit
    ``selection``, the document's own backend (from the URI, §3.6) wins.

    Adapter preference (S59): a platform skill is named when the backend
    declares ``skill_name`` and its declared capabilities satisfy the
    operation's capability needs; otherwise the CLI (``cli_name``) or the MCP
    server (``mcp_url``) is named.
    """
    if selection is None and doc_uri is not None and operation in _SINGLE_DOC_OPS:
        backend, _ = parse_uri(doc_uri)
        names = [backend]
        targets_provenance = "doc_uri"
    else:
        names, targets_provenance = _resolve_targets(
            config, selection, operation, content_type, None
        )
    targets = [_resolve_adapter(config, name, operation) for name in names]
    return RoutingIntent(
        operation=operation,
        doc_uri=doc_uri,
        query=query,
        targets=targets,
        proposal=proposal,
        policy_gates=_policy_gates(config, operation, targets),
        provenance={"targets": targets_provenance},
    )


def _resolve_selection(
    config: Config,
    selection: str,
    operation: str,
    content_type: str | None,
    metadata: dict[str, Any] | None,
) -> list[str]:
    token = selection.strip().lower()
    if token == "all":
        token = "all_enabled"
    if token == "all_enabled":
        return _all_enabled(config, operation)
    if token == "all_configured":
        names, _ = _resolve_chain(config, operation, content_type, metadata)
        return names

    names = [n.strip() for n in selection.split(",") if n.strip()]
    if not names:
        raise ConfigError(f"empty backend selection {selection!r}")
    for name in names:
        if name not in config.backends:
            raise ConfigError(f"unknown backend in selection: {name!r}")
    return names


def _resolve_chain(
    config: Config,
    operation: str,
    content_type: str | None,
    metadata: dict[str, Any] | None = None,
) -> tuple[list[str], str]:
    """Steps 2–4 of the precedence chain, plus which step matched."""
    mode = str(config.defaults.get("routing_mode", "configured"))

    # Step 2: smart rules (first match wins).
    if mode == "smart":
        smart = _match_smart_rules(config, operation, content_type, metadata)
        if smart is not None:
            return smart, "smart"

    # Step 3: content-type mapping (configured mode, or smart didn't match).
    if mode in ("configured", "smart"):
        mapped = _mapped_backend(config, content_type)
        if mapped is not None:
            return [mapped], "content_type_mapping"

    # Step 4: defaults.default_backends.
    return _as_list(config.defaults.get("default_backends")), "defaults"


def _all_enabled(config: Config, operation: str) -> list[str]:
    return [
        name
        for name, backend in config.backends.items()
        if backend.get("enabled") and _has_operation_capability(backend, operation)
    ]


def _has_operation_capability(backend: dict[str, Any], operation: str) -> bool:
    caps = backend.get("capabilities") or {}
    return all(_capability_satisfied(caps, key) for key in capabilities_needed(operation))


def _capability_satisfied(caps: dict[str, Any], key: str) -> bool:
    """Whether declared ``caps`` satisfy one capability key (group or feature)."""
    group, sep, feature = key.partition(".")
    decl = caps.get(group)
    if not isinstance(decl, dict) or not decl.get("supported"):
        return False
    if not sep:
        return True
    features = decl.get("features")
    if isinstance(features, list):
        return feature in features
    if isinstance(features, dict):
        return bool(features.get(feature))
    return False


def _resolve_adapter(config: Config, backend: str, operation: str) -> BackendResolution:
    """Resolve the adapter to name for ``backend`` (§1.5, S59).

    Platform skill preferred over CLI over MCP; the skill is only chosen
    when its declared capabilities satisfy the operation's capability needs.
    N17: never name an adapter for a disabled or unconfigured backend — raise
    instead of producing an intent that names one.
    """
    spec = config.backends.get(backend)
    if spec is None:
        raise ConfigError(f"backend {backend!r} is not configured")
    if not spec.get("enabled"):
        raise ConfigError(f"backend {backend!r} is disabled")
    needed = capabilities_needed(operation)
    skill_name = spec.get("skill_name")
    if skill_name and _has_operation_capability(spec, operation):
        return BackendResolution(backend, "skill", str(skill_name), needed)
    cli_name = spec.get("cli_name")
    if cli_name:
        return BackendResolution(backend, "cli", str(cli_name), needed)
    mcp_url = spec.get("mcp_url")
    if mcp_url:
        return BackendResolution(backend, "mcp", str(mcp_url), needed)
    raise ConfigError(f"backend {backend!r} declares no adapter (skill_name/cli_name/mcp_url)")


def _policy_gates(
    config: Config,
    operation: str,
    targets: list[BackendResolution],
) -> list[PolicyGate]:
    """Policy-gate descriptors for a write intent (§1.5).

    Journal/audit/sensitivity gates apply to every write; an approval gate is
    added when any target backend declares ``approval_flow.supported``. These
    are descriptors only — Task 5.x replaces them with the real gates.
    """
    if operation not in _WRITE_DEFAULT_OPS:
        return []
    gates = [
        PolicyGate(name="journal"),
        PolicyGate(name="audit"),
        PolicyGate(name="sensitivity"),
    ]
    if any(_declares_approval_flow(config, t.backend) for t in targets):
        gates.append(PolicyGate(name="approval"))
    return gates


def _declares_approval_flow(config: Config, backend: str) -> bool:
    spec = config.backends.get(backend) or {}
    flow = spec.get("approval_flow")
    return isinstance(flow, dict) and bool(flow.get("supported"))


def _match_smart_rules(
    config: Config,
    operation: str,
    content_type: str | None,
    metadata: dict[str, Any] | None,
) -> list[str] | None:
    fallback: list[str] | None = None
    for rule in config.routing_rules:
        if "default" in rule and "match" not in rule:
            fallback = _as_list(rule.get("default"))
            continue
        if not _rule_matches(rule, operation, content_type, metadata):
            continue
        backends = rule.get("backends")
        if backends is not None:
            return _as_list(backends)
        # Matched rule declares no explicit backends: an archive + older_than
        # rule selects via archive-selection only; such rules are skipped for
        # store.
        if operation == "store":
            continue
        return []
    return fallback


def _rule_matches(
    rule: dict[str, Any],
    operation: str,
    content_type: str | None,
    metadata: dict[str, Any] | None,
) -> bool:
    match = rule.get("match") or {}
    op = match.get("operation")
    if op is not None and op != operation:
        return False
    ct = match.get("content_type")
    if ct is not None and ct != content_type:
        return False
    tags = match.get("tags")
    if tags:
        meta_tags = (metadata or {}).get("tags") or []
        if not isinstance(meta_tags, list):
            meta_tags = []
        if not set(tags).issubset({str(t) for t in meta_tags}):
            return False
    return not ("older_than" in match and operation != "archive")


def _mapped_backend(config: Config, content_type: str | None) -> str | None:
    mapping = config.content_type_mapping
    if content_type is not None:
        val = mapping.get(content_type)
        if val is not None:
            return val
    return mapping.get("default")


def _read_doc_backend(metadata: dict[str, Any] | None) -> str | None:
    if not metadata:
        return None
    backend = metadata.get("backend")
    return str(backend) if backend else None


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(x) for x in value]
    return [str(value)]
