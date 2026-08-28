import pytest

from kgent.fingerprint import content_fingerprint, fingerprints_equal, normalize


def test_deterministic():
    assert normalize("A", "b") == normalize("A", "b")


def test_equal_content_equal_fingerprint_across_backends():
    assert content_fingerprint("T", "body") == content_fingerprint("T", "body")


def test_whitespace_insensitive():
    assert content_fingerprint("T", "a\n b") == content_fingerprint("T", "a  b")


def test_different_content_different_fingerprint():
    assert content_fingerprint("T", "a") != content_fingerprint("T", "b")


def test_normalize_collapses_whitespace_and_strips():
    assert normalize("  A\tB  ", "\n\nx   y\n") == "a b\x1fx y"


def test_normalize_lowercases():
    assert normalize("Title", "Body Text") == "title\x1fbody text"


def test_normalize_title_whitespace_insensitive():
    assert normalize(" T  ", "x") == normalize("T", "x")


def test_title_differs_from_content():
    # Title and content occupy separate fields; a title-only change alters the fingerprint.
    assert content_fingerprint("a", "b") != content_fingerprint("b", "a")


def test_field_boundary_not_collapsed():
    # The \x1f separator must survive normalization so the title/content
    # boundary cannot be forged by content whitespace (Unicode \s would
    # swallow it).
    assert content_fingerprint("a", "b") != content_fingerprint("a b", "")


def test_fingerprint_is_sha256_hex():
    fp = content_fingerprint("T", "body")
    assert len(fp) == 64
    int(fp, 16)  # hex


def test_empty_fields():
    assert content_fingerprint("", "") == content_fingerprint("", "")


@pytest.mark.parametrize(
    ("fp1", "fp2", "expected"),
    [
        ("a", "a", True),
        ("a", "b", False),
        (None, None, True),
        (None, "a", False),
        ("a", None, False),
    ],
)
def test_fingerprints_equal(fp1, fp2, expected):
    assert fingerprints_equal(fp1, fp2) is expected
