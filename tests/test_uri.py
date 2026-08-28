import pytest

from kgent.errors import ConfigError
from kgent.uri import format_uri, parse_uri


def test_roundtrip():
    assert parse_uri("kgent://lark/docxABC123") == ("lark", "docxABC123")
    assert format_uri("lark", "docxABC123") == "kgent://lark/docxABC123"


@pytest.mark.parametrize(
    "bad",
    [
        "docxABC123",  # bare native id, no scheme
        "",  # scheme-less / empty
        "kgent://lark",  # missing native id
        "kgent://lark/",  # empty native id
        "kgent:///x",  # empty backend
        "http://x/y",  # non-kgent scheme
        "kgent://lark/a/b",  # extra path segment
    ],
)
def test_rejects_noncanonical(bad):
    with pytest.raises(ConfigError):
        parse_uri(bad)
