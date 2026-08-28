"""Multi-backend search: bounded fan-out with per-backend timeouts (§7.1; S33)."""

from kgent.search.fanout import build_footer, exit_code_for_failures, fanout

__all__ = ["build_footer", "exit_code_for_failures", "fanout"]
