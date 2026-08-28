"""Backend adapters: capability contract base, CLI transport, and budgets (§1.2, §3.1, §8.1, §8.5).

Concrete adapters live in sibling modules (``lark``, ``dingtalk``, ``wecom`` —
Task 7.2) and override the §3.1 capability methods on :class:`Adapter`
(:mod:`kgent.adapters.base`); CLI-backed ones delegate to
:func:`kgent.adapters.cli_adapter.run_cli`. Adapter preference per §1.5
(skill > CLI) is resolved by the router.
"""

from kgent.adapters.base import Adapter, RetryBudget, escape_query
from kgent.adapters.cli_adapter import SubprocessResult, run_cli

__all__ = ["Adapter", "RetryBudget", "SubprocessResult", "escape_query", "run_cli"]
