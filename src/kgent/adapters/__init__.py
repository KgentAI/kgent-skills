"""Backend adapters: capability contract base, CLI transport, and budgets (§1.2, §3.1, §8.1, §8.5).

CLI-backed concrete adapters (:class:`~kgent.adapters.lark.LarkAdapter`,
:class:`~kgent.adapters.dingtalk.DingTalkAdapter`,
:class:`~kgent.adapters.wecom.WeComAdapter` — Task 7.2) implement the §3.1
capability methods by delegating to ``lark-cli``/``dingtalk-cli``/``wecom-cli``
via :func:`kgent.adapters.cli_adapter.run_cli` under the wire protocol v1
(:class:`~kgent.adapters.cli_adapter.CliCapabilityAdapter`), translating
canonical URIs ↔ native IDs only at the boundary (§3.6). Adapter preference
per §1.5 (skill > CLI) is resolved by the router — ``lark-doc`` is a
resolve-level label, not a separate invocation.
"""

from kgent.adapters.base import Adapter, RetryBudget, escape_query
from kgent.adapters.cli_adapter import CliCapabilityAdapter, SubprocessResult, run_cli
from kgent.adapters.dingtalk import DingTalkAdapter
from kgent.adapters.lark import LarkAdapter
from kgent.adapters.wecom import WeComAdapter

__all__ = [
    "Adapter",
    "RetryBudget",
    "SubprocessResult",
    "escape_query",
    "run_cli",
    "CliCapabilityAdapter",
    "LarkAdapter",
    "DingTalkAdapter",
    "WeComAdapter",
]
