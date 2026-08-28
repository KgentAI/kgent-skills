"""Multi-backend search: bounded fan-out (§7.1; S33) + RRF ranking (§7.3; S34)."""

from kgent.search.fanout import build_footer, exit_code_for_failures, fanout
from kgent.search.rank import rank_and_truncate, rrf

__all__ = ["build_footer", "exit_code_for_failures", "fanout", "rank_and_truncate", "rrf"]
