"""WeCom adapter (§1.3): §3.1 capabilities over ``wecom-cli`` (§8.5).

WeCom is integrated via its official CLI (no platform skill in the initial
scope, §1.3), so the router names ``wecom-cli`` (§1.5, S59). Canonical
URIs: ``kgent://wecom/<id>`` (§3.6).
"""

from __future__ import annotations

from kgent.adapters.cli_adapter import CliCapabilityAdapter

__all__ = ["WeComAdapter"]


class WeComAdapter(CliCapabilityAdapter):
    """WeCom documents adapter — wire protocol v1 over ``wecom-cli``."""

    def __init__(self, cmd: list[str] | None = None, timeout: float = 30.0) -> None:
        super().__init__(cmd if cmd is not None else ["wecom-cli"], "wecom", timeout)
