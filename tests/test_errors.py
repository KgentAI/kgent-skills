import pytest

from kgent.errors import (
    ApprovalBindingMismatch,
    ApprovalRequired,
    ConfigError,
    PartialFailure,
    PolicyError,
    VersionConflict,
)


@pytest.mark.parametrize(
    "cls,code",
    [
        (ConfigError, 1),
        (VersionConflict, 4),
        (PolicyError, 3),
        (ApprovalRequired, 3),
        (ApprovalBindingMismatch, 3),
        (PartialFailure, 2),
    ],
)
def test_exit_codes(cls, code):
    assert cls().exit_code == code


def test_version_conflict_message():
    err = VersionConflict("kgent://lark/docA", "v17", "v19")
    assert "expected v17" in str(err) and "found v19" in str(err)
