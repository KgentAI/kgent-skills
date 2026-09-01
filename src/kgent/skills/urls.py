"""Skill-layer native URL presentation (§1.7, S73–S76, S85, N20/N23).

Canonical ``kgent://`` URIs are internal only — skills MUST convert them to
native platform URLs when presenting results to users (N20). The URL path
must MATCH the node type (N23): a wiki node rendered with a ``/docx/`` path
(or a doc with ``/wiki/``) is a broken link.

- **Lark docs**: ``https://<workspace_domain>/docx/<token>``
- **Lark wiki nodes**: ``https://<workspace_domain>/wiki/<node_token>``
- **DingTalk**: ``https://<workspace_domain>/document/<id>``
- **WeCom**: ``https://<workspace_domain>/docs/<id>``

``node_type`` (``"doc"`` | ``"wiki_node"``) is read from the search result /
read metadata (§7.2) — never inferred by parsing the token (§3.6).
"""

from __future__ import annotations

from kgent.uri import parse_uri

__all__ = ["native_url"]

_LARK_PATH = {"doc": "docx", "wiki_node": "wiki"}


def native_url(doc_uri: str, workspace_domain: str, *, node_type: str = "doc") -> str:
    """Render ``doc_uri`` as a native platform URL honoring the node type (§1.7).

    ``workspace_domain`` comes from ``defaults.workspace_domain`` in
    ``~/.kgent/config.yaml``; when it is not configured, skills prompt the
    user to set it (S75). A wiki node always renders under ``/wiki/`` and a
    flat doc under ``/docx/`` — the path is chosen by ``node_type``, never by
    token shape (N23).
    """
    backend, native_id = parse_uri(doc_uri)
    if backend == "lark":
        path = _LARK_PATH.get(node_type, "docx")
        return f"https://{workspace_domain}/{path}/{native_id}"
    if backend == "dingtalk":
        return f"https://{workspace_domain}/document/{native_id}"
    if backend == "wecom":
        return f"https://{workspace_domain}/docs/{native_id}"
    # Unknown backend: fall back to a plain domain link with the native id.
    return f"https://{workspace_domain}/{native_id}"
