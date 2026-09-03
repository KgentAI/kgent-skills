# pyright: basic
import pytest

from kgent.errors import ConfigError
from kgent.uri import format_uri, parse_uri


def test_roundtrip() -> None:
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
        "kgent://lark/doc?x=1",  # query (must be rejected — mutation-found gap)
        "kgent://lark/doc#frag",  # fragment
        "kgent://lark/doc?x=1#f",  # query + fragment
    ],
)
def test_rejects_noncanonical(bad: str) -> None:
    with pytest.raises(ConfigError):
        parse_uri(bad)
