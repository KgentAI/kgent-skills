"""Multi-backend search: bounded fan-out (§7.1; S33), RRF ranking (§7.3; S34),
and aggregation — dedupe, near-dup clustering, staleness, conflicts (§7.2, §6.5, §8.6; S35–S38, S55, S56)."""

from kgent.search.aggregate import (
    DEFAULT_CONFLICT_STRATEGIES,
    Conflict,
    IdMap,
    NearDupCluster,
    assess_staleness,
    classify_read_failure,
    cluster_title,
    cluster_uris,
    detect_conflicts,
    has_conflicts,
    merge_and_deduplicate,
    resolve_home,
    snippet_overlap,
    verify_results,
)
from kgent.search.fanout import build_footer, exit_code_for_failures, fanout
from kgent.search.rank import rank_and_truncate, rrf

__all__ = [
    "DEFAULT_CONFLICT_STRATEGIES",
    "Conflict",
    "IdMap",
    "NearDupCluster",
    "assess_staleness",
    "build_footer",
    "classify_read_failure",
    "cluster_title",
    "cluster_uris",
    "detect_conflicts",
    "exit_code_for_failures",
    "fanout",
    "has_conflicts",
    "merge_and_deduplicate",
    "rank_and_truncate",
    "resolve_home",
    "rrf",
    "snippet_overlap",
    "verify_results",
]
