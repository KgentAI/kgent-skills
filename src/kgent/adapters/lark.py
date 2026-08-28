"""Lark / Feishu adapter (§1.3): §3.1 capabilities over ``lark-cli`` (§8.5).

The router names this backend's adapter ``lark-doc`` (the platform skill)
when its declared capabilities satisfy the operation, else ``lark-cli``
(§1.5, S59) — that preference lives at **resolve level**
(:mod:`kgent.router.resolve`), not here. :class:`LarkAdapter` is always
constructed with ``cmd=[\"lark-cli\"]``; there is no separate skill
invocation yet, so an injected skill-invoker can arrive later without
touching resolve. Canonical URIs: ``kgent://lark/<id>`` (§3.6).
"""

from __future__ import annotations

from kgent.adapters.cli_adapter import CliCapabilityAdapter

__all__ = ["LarkAdapter"]


class LarkAdapter(CliCapabilityAdapter):
    """Lark/Feishu documents adapter — wire protocol v1 over ``lark-cli``."""

    def __init__(self, cmd: list[str] | None = None, timeout: float = 30.0) -> None:
        super().__init__(cmd if cmd is not None else ["lark-cli"], "lark", timeout)
