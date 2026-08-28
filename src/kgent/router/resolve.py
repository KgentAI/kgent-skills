"""Backend resolution — single precedence chain (§4.1–§4.3).

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
"""

from __future__ import annotations

from typing import Any

from kgent.config.schema import Config
from kgent.errors import ConfigError

__all__ = ["resolve_backends"]

# Operations that default to "all_configured" (steps 2–4) when no selection
# is given. Search defaults to "all_enabled". Read is out of scope.
_WRITE_DEFAULT_OPS = frozenset({"create", "update", "delete", "archive", "unarchive", "store"})

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


def resolve_backends(
    config: Config,
    *,
    selection: str | None,
    operation: str,
    content_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> list[str]:
    """Resolve the ordered backend names for ``operation`` under §4.1."""
    if selection is not None:
        return _resolve_selection(config, selection, operation, content_type, metadata)
    if operation == "read":
        doc_backend = _read_doc_backend(metadata)
        return [doc_backend] if doc_backend else []
    if operation == "search":
        return _all_enabled(config, operation)
    return _resolve_chain(config, operation, content_type, metadata)


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
        return _resolve_chain(config, operation, content_type, metadata)

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
) -> list[str]:
    mode = str(config.defaults.get("routing_mode", "configured"))

    # Step 2: smart rules (first match wins).
    if mode == "smart":
        smart = _match_smart_rules(config, operation, content_type, metadata)
        if smart is not None:
            return smart

    # Step 3: content-type mapping (configured mode, or smart didn't match).
    if mode in ("configured", "smart"):
        mapped = _mapped_backend(config, content_type)
        if mapped is not None:
            return [mapped]

    # Step 4: defaults.default_backends.
    return _as_list(config.defaults.get("default_backends"))


def _all_enabled(config: Config, operation: str) -> list[str]:
    return [
        name
        for name, backend in config.backends.items()
        if backend.get("enabled") and _has_operation_capability(backend, operation)
    ]


def _has_operation_capability(backend: dict[str, Any], operation: str) -> bool:
    caps = backend.get("capabilities") or {}
    if operation == "search":
        search = caps.get("document_search")
        return bool(search.get("supported")) if isinstance(search, dict) else False
    storage = caps.get("document_storage")
    if not isinstance(storage, dict) or not storage.get("supported"):
        return False
    feature = _STORAGE_FEATURE.get(operation)
    if feature is None:
        return True
    features = storage.get("features")
    if isinstance(features, list):
        return feature in features
    return False


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
