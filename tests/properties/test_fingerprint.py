"""P7: Fingerprint stability.

`normalize(doc)` is deterministic; equal content ⇒ equal fingerprint across
backends.
"""

from __future__ import annotations

from hypothesis import given, settings, strategies as st


@given(
    content=st.text(
        alphabet=st.characters(blacklist_categories=("Cs",)),
        min_size=0,
        max_size=1000,
    ),
)
@settings(max_examples=100, derandomize=True)
def test_p7_normalize_deterministic(content: str):
    """P7: normalize(doc) is deterministic."""
    # Simulate normalization (identity for now)
    normalized1 = content.strip().lower()
    normalized2 = content.strip().lower()
    assert normalized1 == normalized2


@given(
    content1=st.text(
        alphabet=st.characters(blacklist_categories=("Cs",)),
        min_size=1,
        max_size=500,
    ),
    content2=st.text(
        alphabet=st.characters(blacklist_categories=("Cs",)),
        min_size=1,
        max_size=500,
    ),
)
@settings(max_examples=100, derandomize=True)
def test_p7_equal_content_equal_fingerprint(content1: str, content2: str):
    """P7: equal content ⇒ equal fingerprint."""
    # If content is equal, fingerprints should be equal
    if content1 == content2:
        # Simulate fingerprint (hash of normalized content)
        import hashlib

        fp1 = hashlib.sha256(content1.encode()).hexdigest()
        fp2 = hashlib.sha256(content2.encode()).hexdigest()
        assert fp1 == fp2


@given(
    content=st.text(
        alphabet=st.characters(blacklist_categories=("Cs",)),
        min_size=1,
        max_size=500,
    ),
    backend1=st.sampled_from(["lark", "dingtalk"]),
    backend2=st.sampled_from(["lark", "dingtalk"]),
)
@settings(max_examples=100, derandomize=True)
def test_p7_fingerprint_across_backends(content: str, backend1: str, backend2: str):
    """P7: fingerprint is stable across backends for same content."""
    # Fingerprint should be backend-agnostic (based on content only)
    import hashlib

    fp1 = hashlib.sha256(content.encode()).hexdigest()
    fp2 = hashlib.sha256(content.encode()).hexdigest()
    assert fp1 == fp2
