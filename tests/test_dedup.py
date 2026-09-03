"""Dedupe + near-duplicate clustering (§7.2, §6.5; S37, S38).

S37 — fingerprint-identical copies collapse to ONE result with
``also_available_in`` listing the other copies (callers build "Update all N
copies (identical content)" from the kept uri + ``also_available_in``).
S38 — near-duplicates (different fingerprint, similar title) are grouped into
a :class:`NearDupCluster`, never auto-merged or deleted (N8). Same doc_uri
duplicates are deduped keeping the first.
"""

from __future__ import annotations

from kgent.fingerprint import content_fingerprint
from kgent.search.aggregate import (
    cluster_title,
    cluster_uris,
    merge_and_deduplicate,
)
from kgent.types import DocumentMetadata, SearchResult


def _result(
    uri: str,
    title: str,
    *,
    content: str | None = None,
    fp: str | None = None,
    snippet: str | None = None,
    backend: str | None = None,
) -> SearchResult:
    """Build a SearchResult, deriving the fingerprint from (title, content) when
    no explicit ``fp`` is given but content is."""
    backend = backend or uri.split("//")[1].split("/")[0]
    if fp is None and content is not None:
        fp = content_fingerprint(title, content)
    meta = DocumentMetadata(doc_uri=uri, title=title, backend=backend, content_fingerprint=fp)
    return SearchResult(doc_uri=uri, metadata=meta, rank=1, snippet=snippet, access="ok")


def test_s37_identical_fingerprints_collapse_to_one_result():
    """S37: identical fingerprint on lark + dingtalk → ONE merged result whose
    also_available_in names the other copy (the "Update all 2 copies" option)."""
    lark = _result(
        "kgent://lark/doc1", "Retros 2026-08", content="Retro notes v3.", snippet="start"
    )
    dingtalk = _result(
        "kgent://dingtalk/doc1", "Retros 2026-08", content="Retro notes v3.", snippet="start"
    )
    assert lark.metadata.content_fingerprint == dingtalk.metadata.content_fingerprint

    merged, clusters = merge_and_deduplicate([lark, dingtalk])

    assert len(merged) == 1
    assert merged[0].doc_uri == lark.doc_uri  # first result keeps
    assert merged[0].also_available_in == [dingtalk.doc_uri]  # the OTHER copy's uri
    assert clusters == []


def test_s37_three_copies_all_listed_in_order():
    """S37: three fingerprint-identical copies → one result, both other uris in
    also_available_in, encounter order preserved."""
    first = _result("kgent://lark/doc1", "Policies", content="same body", snippet="s")
    second = _result("kgent://dingtalk/doc1", "Policies", content="same body", snippet="s")
    third = _result("kgent://wecom/doc1", "Policies", content="same body", snippet="s")

    merged, clusters = merge_and_deduplicate([first, second, third])

    assert len(merged) == 1
    assert merged[0].also_available_in == [second.doc_uri, third.doc_uri]
    assert clusters == []


def test_s38_near_duplicates_grouped_never_merged_or_deleted():
    """S38: different fingerprints, similar titles → ONE cluster with 2 members;
    both results still surface (no auto-merge into one entry, none deleted)."""
    a = _result(
        "kgent://lark/docA",
        "Onboarding Policy 2026",
        fp="fp-aaaa",
        snippet="must complete onboarding within 30 days",
    )
    b = _result(
        "kgent://dingtalk/docB",
        "Onboarding Policy 2026 (draft)",
        fp="fp-bbbb",
        snippet="must complete onboarding within 30 days; exceptions apply",
    )

    merged, clusters = merge_and_deduplicate([a, b])

    assert len(clusters) == 1
    assert cluster_title(clusters[0]) == a.metadata.title  # first member's title
    assert sorted(cluster_uris(clusters[0])) == sorted([a.doc_uri, b.doc_uri])
    members = clusters[0].members
    assert len(members) == 2
    # nobody deleted: both appear on the merged stream as SEPARATE entries
    assert [r.doc_uri for r in merged] == [a.doc_uri, b.doc_uri]
    # never auto-merged: still two distinct entries, each with its own metadata
    assert merged[0] is not merged[1]
    assert merged[0].metadata.content_fingerprint != merged[1].metadata.content_fingerprint


def test_near_dup_threshold_below_08_not_clustered():
    """Titles must be similar (SequenceMatcher >= 0.8); a low-similarity pair is
    not clustered."""
    a = _result("kgent://lark/a", "Q3 Financial Review", fp="fp-a", snippet="s")
    b = _result("kgent://dingtalk/b", "Q3 Earnings Summary", fp="fp-b", snippet="s")

    merged, clusters = merge_and_deduplicate([a, b])

    assert clusters == []
    assert len(merged) == 2


def test_same_doc_uri_duplicate_deduped_keeps_first():
    """Same doc_uri returned twice (e.g. duplicate backend list) → keep the
    first; the doc is not listed as "also available in" itself."""
    first = _result("kgent://lark/doc1", "Same doc", content="body", snippet="s")
    second = _result("kgent://lark/doc1", "Same doc", content="body", snippet="s")

    merged, clusters = merge_and_deduplicate([first, second])

    assert len(merged) == 1
    assert merged[0].doc_uri == first.doc_uri
    assert merged[0].metadata.content_fingerprint == first.metadata.content_fingerprint
    assert merged[0].also_available_in == []
    assert clusters == []


def test_same_doc_uri_different_fingerprint_deduped():
    """Same doc_uri even with a different content fingerprint is still a
    duplicate (one document), never clustered with itself."""
    first = _result("kgent://lark/doc1", "Doc", fp="fp-old", snippet="s")
    second = _result("kgent://lark/doc1", "Doc updated", fp="fp-new", snippet="s")

    merged, clusters = merge_and_deduplicate([first, second])

    assert len(merged) == 1
    assert merged[0] is first  # first occurrence wins
    assert clusters == []


def test_duplicate_uri_and_identical_fingerprint_collapse_once():
    """A result that is BOTH a same-uri duplicate and fingerprint-identical:
    the kept result lists each other copy exactly once."""
    a = _result("kgent://lark/doc1", "Synced", content="shared body", snippet="s")
    b = _result("kgent://dingtalk/doc1", "Synced", content="shared body", snippet="s")
    duplicate = _result("kgent://lark/doc1", "Synced", content="shared body", snippet="s")

    merged, clusters = merge_and_deduplicate([a, b, duplicate])

    assert len(merged) == 1
    assert merged[0].doc_uri == a.doc_uri
    assert merged[0].also_available_in == [b.doc_uri]
    assert clusters == []
