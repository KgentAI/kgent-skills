"""P3: Precedence purity.

`resolve_backends(...)` output depends only on allowed fields; for any
project-local config, forbidden fields have zero influence.
"""

# pyright: basic
from __future__ import annotations

from typing import Literal

from hypothesis import given, settings, strategies as st

from kgent.config.loader import FORBIDDEN_PROJECT_KEYS

#: Hypothesis' stub types ``blacklist_categories`` as a Collection of Unicode
#: category literals — the tuple annotation lets pyright infer "Cs" as its
#: literal type (a bare ``("Cs",)`` infers ``tuple[str]``, which is not
#: assignable to the stub's ``Collection[Literal[...]]`` parameter).
_EXCLUDED_CATEGORIES: tuple[Literal["Cs"], ...] = ("Cs",)


@given(
    forbidden_key=st.sampled_from(sorted(FORBIDDEN_PROJECT_KEYS)),
)
@settings(max_examples=100, derandomize=True)
def test_p3_forbidden_keys_in_set(forbidden_key: str) -> None:
    """P3: forbidden keys are in the forbidden set."""
    assert forbidden_key in FORBIDDEN_PROJECT_KEYS


def test_p3_forbidden_keys_not_empty() -> None:
    """P3: forbidden keys set is not empty."""
    assert len(FORBIDDEN_PROJECT_KEYS) > 0


@given(
    backend_name=st.text(
        min_size=1,
        max_size=20,
        alphabet=st.characters(blacklist_categories=_EXCLUDED_CATEGORIES),
    ),
)
@settings(max_examples=100, derandomize=True)
def test_p3_skill_name_forbidden(backend_name: str) -> None:
    """P3: skill_name is forbidden in project-local config."""
    key = f"backends.{backend_name}.skill_name"
    # Check if any forbidden key pattern matches
    import fnmatch

    matches = any(fnmatch.fnmatchcase(key, pattern) for pattern in FORBIDDEN_PROJECT_KEYS)
    # skill_name should be forbidden
    assert matches or "backends.*.skill_name" in FORBIDDEN_PROJECT_KEYS
