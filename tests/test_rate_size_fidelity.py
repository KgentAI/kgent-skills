"""Oversize preflight (§3.7, S48): content rejected before any proposal.

Preflight runs against EVERY target BEFORE proposals are built — a violation
must name the backend, the actual size, the declared limit, and the backends
that would accept the content (alternatives). The write path rejects with exit
code 3 (``PolicyError``).
"""

from __future__ import annotations

import pytest

from kgent.errors import PolicyError
from kgent.router.preflight import preflight_size, reject_preflight
from tests.conftest import _full_caps, _kw_caps
from tests.fakes.fake_backend import FakeBackend


def _backend(name: str, caps: dict[str, object]) -> FakeBackend:
    return FakeBackend(name, "internal" if name == "lark" else "external", caps)


def test_s48_oversize_preflight_flags_offending_backends_with_alternatives():
    """Content 2.5 MB vs lark 2 MB: lark flagged; wecom (bigger limit) is the alternative."""
    lark_caps = _full_caps()  # max_content_bytes = 2_000_000
    wecom_caps = _full_caps()
    wecom_caps["document_search"]["limits"]["max_content_bytes"] = 5_000_000
    targets = [
        _backend("lark", lark_caps),
        _backend("dingtalk", _kw_caps()),  # kw caps: NO max_content_bytes -> no limit
        _backend("wecom", wecom_caps),
    ]

    violations = preflight_size(b"x" * 2_500_000, targets)

    assert len(violations) == 1
    msg = violations[0]
    assert "lark" in msg
    assert "2500000" in msg  # actual size
    assert "2000000" in msg  # declared limit
    assert "wecom" in msg  # alternative backend that accepts the content


def test_s48_all_backends_over_limit_names_each_violation():
    """lark (2 MB) and dingtalk (50 KB) both exceeded: two messages, each names alternatives."""
    lark_caps = _full_caps()  # 2_000_000
    dingtalk_caps = _kw_caps()
    dingtalk_caps["document_search"]["limits"] = {"max_results": 50, "max_content_bytes": 50_000}
    wecom_caps = _full_caps()
    wecom_caps["document_search"]["limits"]["max_content_bytes"] = 5_000_000

    violations = preflight_size(
        b"x" * 2_500_000,
        [
            _backend(n, c)
            for n, c in (
                ("lark", lark_caps),
                ("dingtalk", dingtalk_caps),
                ("wecom", wecom_caps),
            )
        ],
    )

    assert len(violations) == 2
    lark_msg = next(v for v in violations if "lark" in v)
    dingtalk_msg = next(v for v in violations if "dingtalk" in v)
    assert "50000" in dingtalk_msg and "2500000" in dingtalk_msg
    # both name the same alternative (only wecom can take 2.5 MB)
    assert lark_msg.count("wecom") == 1 and dingtalk_msg.count("wecom") == 1


def test_s48_str_content_measured_in_utf8_bytes():
    """Multi-byte chars: '€' is 3 bytes — 700_000 chars cross the 2 MB byte limit."""
    assert len("€".encode()) == 3
    lark_caps = _full_caps()  # 2_000_000 bytes
    violations = preflight_size("€" * 700_000, [_backend("lark", lark_caps)])
    assert len(violations) == 1
    assert "2100000" in violations[0]


def test_s48_within_all_limits_no_violations():
    empty = preflight_size(b"small", [_backend("lark", _full_caps())])
    assert empty == []


def test_s48_unicode_str_short_of_byte_limit_passes():
    lark_caps = _full_caps()
    lark_caps["document_search"]["limits"]["max_content_bytes"] = 10
    violations = preflight_size("é", [_backend("lark", lark_caps)])  # 2 bytes <= 10
    assert violations == []


def test_s48_rejection_is_exit_3_before_any_proposal():
    """The write path rejects with PolicyError (exit code 3) when violations exist."""
    violations = preflight_size(b"x" * 2_500_000, [_backend("lark", _full_caps())])
    assert violations

    with pytest.raises(PolicyError) as excinfo:
        reject_preflight(violations)
    assert excinfo.value.exit_code == 3
    assert "lark" in str(excinfo.value)
