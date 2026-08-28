"""Conflict detection + snippet overlap (§7.5, §6.5; S55, S56).

S56 — two documents sharing a copy-pasted section are flagged "overlapping
content" via :func:`snippet_overlap`, never auto-merged. S55 — a diverged
near-duplicate pair (same title, different fingerprints, overlapping
snippets) surfaces a :class:`Conflict` whose recommended strategy comes from
the configured ``conflict_resolution.strategies`` list; no resolution action
executes. Also covers the stale-vs-live deterministic rule (§8.6) and
:func:`has_conflicts`. 6.5 will extend this file with query-decomposition
tests.
"""

from __future__ import annotations

from kgent.search.aggregate import (
    DEFAULT_CONFLICT_STRATEGIES,
    Conflict,
    detect_conflicts,
    has_conflicts,
    merge_and_deduplicate,
    snippet_overlap,
)
from kgent.types import DocumentMetadata, SearchResult


def _result(
    uri: str,
    title: str,
    *,
    fp: str | None = None,
    snippet: str | None = None,
    access: str = "ok",
) -> SearchResult:
    meta = DocumentMetadata(
        doc_uri=uri,
        title=title,
        backend=uri.split("//")[1].split("/")[0],
        content_fingerprint=fp,
    )
    return SearchResult(doc_uri=uri, metadata=meta, rank=1, snippet=snippet, access=access)


def test_s56_shared_snippet_flagged_overlapping_not_merged():
    """S56: two docs share a copy-pasted section but differ elsewhere → snippet
    overlap True; they are never auto-merged into one result."""
    a = _result(
        "kgent://lark/docA",
        "Q3 Financial Review",
        fp="fp-a",
        snippet="Quarterly revenue grew 12% to $4.2B this quarter.",
    )
    b = _result(
        "kgent://dingtalk/docB",
        "Q3 Earnings Summary",
        fp="fp-b",
        snippet="Quarterly revenue grew 12% to $4.2B this quarter. Guidance raised.",
    )

    assert snippet_overlap(a, b) is True

    merged, _ = merge_and_deduplicate([a, b])
    assert len(merged) == 2  # never auto-merged
    assert {r.doc_uri for r in merged} == {a.doc_uri, b.doc_uri}


def test_snippet_overlap_disjoint_snippets_false():
    a = _result("kgent://lark/a", "T", fp="fp-a", snippet="completely different words here")
    b = _result("kgent://dingtalk/b", "T", fp="fp-b", snippet="totally unrelated text there")
    assert snippet_overlap(a, b) is False


def test_snippet_overlap_missing_snippets_false():
    none_a = _result("kgent://lark/a", "T", fp="fp-a")
    none_b = _result("kgent://dingtalk/b", "T", fp="fp-b", snippet="any")
    assert snippet_overlap(none_a, none_b) is False
    assert snippet_overlap(none_a, none_a) is False


def test_snippet_overlap_respects_threshold():
    a = _result("kgent://lark/a", "T", fp="fp-a", snippet="the quick brown fox jumps over")
    b = _result(
        "kgent://dingtalk/b", "T", fp="fp-b", snippet="the quick brown fox jumps over the lazy dog"
    )
    # ratio of common prefix is well above 0.6 and below 1.0
    assert snippet_overlap(a, b) is True
    assert snippet_overlap(a, b, threshold=0.99) is False


def test_cluster_overlapping_flag_lazy():
    """NearDupCluster.overlapping is computed lazily from member snippets (S56)."""
    a = _result(
        "kgent://lark/a",
        "Onboarding Policy 2026",
        fp="fp-a",
        snippet="must complete onboarding within 30 days",
    )
    b = _result(
        "kgent://dingtalk/b",
        "Onboarding Policy 2026 v2",
        fp="fp-b",
        snippet="must complete onboarding within 30 days. exceptions apply",
    )
    c = _result(
        "kgent://wecom/c",
        "Onboarding Policy 2026 (mirror)",
        fp="fp-c",
        snippet="totally unrelated snippet",
    )

    merged, clusters = merge_and_deduplicate([a, b, c])
    # never dropped: every member still surfaces on the merged stream
    assert {r.doc_uri for r in merged} == {a.doc_uri, b.doc_uri, c.doc_uri}
    assert len(clusters) == 1
    assert clusters[0].overlapping is True  # a+b share the snippet, c doesn't
    # lazily cached: repeated access is stable
    assert clusters[0].overlapping is True


def test_s55_diverged_near_dup_surfaces_conflict_with_configured_strategy():
    """S55: same title, different fingerprints, overlapping snippets →
    diverged-copy conflict whose strategy is the FIRST configured strategy."""
    strategies = ["link", "comment", "archive", "correct"]
    a = _result(
        "kgent://lark/docA",
        "Team Roster 2026",
        fp="fp-a",
        snippet="Owner: alice. Members: bob, carol.",
    )
    b = _result(
        "kgent://dingtalk/docB",
        "Team Roster 2026",
        fp="fp-b",
        snippet="Owner: alice. Members: bob, carol, dave.",
    )

    merged, clusters = merge_and_deduplicate([a, b])
    conflicts = detect_conflicts(merged, clusters, strategies=strategies)

    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert isinstance(conflict, Conflict)
    assert conflict.kind == "diverged-copy"
    assert conflict.strategy == strategies[0]
    assert sorted(conflict.uris) == sorted([a.doc_uri, b.doc_uri])
    assert a.doc_uri in conflict.detail and b.doc_uri in conflict.detail
    assert has_conflicts(conflicts) is True


def test_detect_conflicts_default_strategies_and_defaults():
    """No strategies passed → the config-default order is used, strategy is the
    first entry; DEFAULT_CONFLICT_STRATEGIES mirrors the config default."""
    assert DEFAULT_CONFLICT_STRATEGIES == ["link", "comment", "archive", "correct"]
    a = _result(
        "kgent://lark/docA",
        "Team Roster 2026",
        fp="fp-a",
        snippet="Owner: alice. Members: bob, carol.",
    )
    b = _result(
        "kgent://dingtalk/docB",
        "Team Roster 2026",
        fp="fp-b",
        snippet="Owner: alice. Members: bob, carol, dave.",
    )

    merged, clusters = merge_and_deduplicate([a, b])
    conflicts = detect_conflicts(merged, clusters)  # strategies=None

    assert len(conflicts) == 1
    assert conflicts[0].strategy == "link"


def test_stale_vs_live_same_uri_is_conflict():
    """§8.6: a stale result whose uri also appears live → stale-conflict with
    strategy "correct" (deterministic fallback detection)."""
    live = _result(
        "kgent://lark/doc1",
        "Policy",
        fp="fp-live",
        snippet="current policy",
        access="ok",
    )
    stale = _result(
        "kgent://lark/doc1",
        "Policy",
        fp="fp-live",
        snippet="current policy",
        access="stale",
    )

    conflicts = detect_conflicts([live, stale], [])

    assert len(conflicts) == 1
    assert conflicts[0].kind == "stale-conflict"
    assert conflicts[0].strategy == "correct"
    assert conflicts[0].uris == [live.doc_uri]
    assert has_conflicts(conflicts) is True


def test_no_conflict_when_snippets_disjoint():
    """Same title + different fingerprints but NO snippet overlap → not a
    diverged-copy; no conflict surfaces."""
    a = _result(
        "kgent://lark/a", "Sprint Notes", fp="fp-a", snippet="quarterly revenue grew twelve percent"
    )
    b = _result(
        "kgent://dingtalk/b",
        "Sprint Notes",
        fp="fp-b",
        snippet="new hire onboarding checklist attached",
    )

    merged, clusters = merge_and_deduplicate([a, b])
    conflicts = detect_conflicts(merged, clusters)

    assert conflicts == []
    assert has_conflicts(conflicts) is False


def test_has_conflicts_empty_is_false():
    assert has_conflicts([]) is False
