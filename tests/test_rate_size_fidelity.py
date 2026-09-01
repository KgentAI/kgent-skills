"""Oversize preflight (§3.7, S48): content rejected before any proposal.

Preflight runs against EVERY target BEFORE proposals are built — a violation
must name the backend, the actual size, the declared limit, and the backends
that would accept the content (alternatives). The write path rejects with exit
code 3 (``PolicyError``).
"""

# pyright: basic
from __future__ import annotations

import pytest

from kgent.adapters.base import RetryBudget
from kgent.adapters.fidelity import (
    FIDELITY_REGISTRY,
    declare_lossy,
    declared_lossy,
    from_canonical,
    is_lossy,
    lossy_warning_snippet,
    to_canonical,
)
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


# ---------------------------------------------------------------------------
# S47 — rate-limit queueing is budgeted, NOT retried (N13, §8.1)
# ---------------------------------------------------------------------------


def test_s47_retry_after_queued_not_retried():
    """A 429 with Retry-After is queued; the transient budget stays untouched."""
    budget = RetryBudget(retries=3)
    assert budget.on_rate_limit(retry_after=1, operation_timeout=30) is True  # queues 1s
    assert budget.transient_attempts == 0  # NOT counted against the 3-attempt budget
    assert budget.rate_limit_queued == 1.0  # one second of queueing booked


def test_s47_rate_limit_queue_accumulates_and_fails_at_timeout():
    budget = RetryBudget(retries=3)
    assert budget.on_rate_limit(retry_after=10, operation_timeout=25) is True  # 10 queued
    assert budget.on_rate_limit(retry_after=10, operation_timeout=25) is True  # 20 queued
    # next one would exceed the operation timeout -> surfaced as failure, not queued
    assert budget.on_rate_limit(retry_after=10, operation_timeout=25) is False
    assert budget.rate_limit_queued == 20.0  # un-queued wait is not double-counted
    assert budget.transient_attempts == 0  # still never counted (N13)


def test_s47_transient_budget_exhausts_independently():
    budget = RetryBudget(retries=3)
    assert budget.on_transient_error() is True
    assert budget.on_transient_error() is True
    assert budget.on_transient_error() is True
    assert budget.transient_attempts == 3
    assert budget.on_transient_error() is False  # budget exhausted -> callers fail

    # rate-limit queueing still works after transient exhaustion, and vice-versa:
    # the two budgets never interact (S47, N13)
    assert budget.on_rate_limit(retry_after=1, operation_timeout=30) is True
    assert budget.rate_limit_queued == 1.0
    assert budget.transient_attempts == 3


def test_s47_transient_backoff_is_exponential():
    budget = RetryBudget(retries=5)
    assert budget.backoff_delay() == 0.0  # no retry yet -> no wait
    budget.on_transient_error()
    assert budget.backoff_delay() == pytest.approx(0.25)
    budget.on_transient_error()
    assert budget.backoff_delay() == pytest.approx(0.5)
    budget.on_transient_error()
    assert budget.backoff_delay() == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# S49 — lossy conversion is declared and warned, never silent (N11, §6.9)
# ---------------------------------------------------------------------------


def test_s49_registry_declares_lark_lossy_dir_and_degraded_elements():
    """§6.9/Context: lark declares both directions lossy with vote block etc."""
    decl = declared_lossy("lark", "native_to_canonical")
    assert decl is not None
    assert decl["fidelity"] == "lossy"
    assert decl["degraded_elements"] == ["vote block", "diagram", "comment thread"]
    # canonical -> native mirrors the same lossiness
    assert is_lossy("lark", "canonical_to_native")


def test_s49_declared_lossless_is_not_lossy_and_undeclared_defaults_lossless():
    # markdown is the native format on dingtalk/wecom -> declared lossless
    assert is_lossy("dingtalk", "native_to_canonical") is False
    assert is_lossy("dingtalk", "canonical_to_native") is False
    assert is_lossy("wecom", "native_to_canonical") is False
    # undeclared adapters default to lossless (documented)
    assert declared_lossy("nonesuch", "native_to_canonical") is None
    assert is_lossy("nonesuch", "native_to_canonical") is False


def test_s49_lark_vote_block_to_canonical_placeholder_and_warning():
    """S49: a Lark vote block degrades to an explicit placeholder, never a silent drop."""
    canonical, degraded = to_canonical("[native: vote block]", "lark")
    assert canonical == "[unsupported: vote block]"
    assert degraded == ["vote block"]
    # the proposal warning must list the element by name (confirmation is the caller's job)
    assert "vote block" in lossy_warning_snippet(degraded)


def test_s49_warning_snippet_plural_and_singular():
    assert (
        lossy_warning_snippet(["vote block", "diagram", "comment thread"])
        == "3 elements have no Markdown equivalent: vote block, diagram, comment thread"
    )
    assert (
        lossy_warning_snippet(["vote block"]) == "1 element has no Markdown equivalent: vote block"
    )
    assert lossy_warning_snippet([]) == ""


def test_s49_lossless_path_unchanged_no_degraded():
    """Lossless direction: native == canonical, empty degraded list (P1)."""
    text = "[native: vote block]\n\nplain prose"
    canonical, degraded = to_canonical(text, "dingtalk")  # declared lossless
    assert canonical == text
    assert degraded == []
    # undeclared adapter is treated as lossless too
    canonical2, degraded2 = to_canonical(text, "nonesuch")
    assert canonical2 == text and degraded2 == []


def test_s49_p1_roundtrip_lossless_preserves_content():
    """P1 seed: to_canonical(from_canonical(x)) == x on a lossless adapter."""
    doc = "# Title\n\nbody with [native: vote block] marker\n"
    canonical, _ = from_canonical(doc, "dingtalk")
    restored, _ = to_canonical(canonical, "dingtalk")
    assert restored == doc


def test_s49_from_canonical_notes_placeholders_on_lossy_destination():
    """Outward direction: placeholders are reported as degraded, never dropped."""
    canonical = "See [unsupported: vote block] and [unsupported: comment thread]"
    out, degraded = from_canonical(canonical, "lark")
    assert out == canonical  # placeholder text survives the write content (N11)
    assert degraded == ["vote block", "comment thread"]


def test_s49_from_canonical_lossless_destination_no_degraded():
    out, degraded = from_canonical("See [unsupported: vote block]", "dingtalk")
    assert out == "See [unsupported: vote block]"
    assert degraded == []


def test_s49_unknown_content_passes_through_unchanged():
    text = "# Plain markdown\n\n- bullets\n- more\n\nend."
    canonical, degraded = to_canonical(text, "lark")
    assert canonical == text
    assert degraded == []


def test_s49_undeclared_native_marker_not_fabricated_as_degraded():
    """Only elements the adapter DECLARES as degraded become placeholders (never fabricate)."""
    text = "text [native: inline image] more"
    canonical, degraded = to_canonical(text, "lark")
    assert canonical == text  # passthrough, not invented into an unsupported placeholder
    assert degraded == []


def test_s49_declare_lossy_helper_registers_and_returns_elements():
    """Test hook: construct/adjust declarations directly (Context: tests may override)."""
    elements = declare_lossy("covfefe", "native_to_canonical", ["vote block"])
    assert elements == ["vote block"]
    assert is_lossy("covfefe", "native_to_canonical") is True
    canonical, degraded = to_canonical("[native: vote block]", "covfefe")
    assert canonical == "[unsupported: vote block]"
    assert degraded == ["vote block"]
    del FIDELITY_REGISTRY["covfefe"]
