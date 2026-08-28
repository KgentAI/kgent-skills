"""Interim stub Config — finalized/validated in Task 2.1 (Appendix C).

Generic attribute-holder sufficient for the test world (tests/conftest.py).
Task 2.1 replaces this with the full validated schema.
"""

from __future__ import annotations


class Config:
    """Attribute-holder config; unknown keys stored as attributes (non-breaking)."""

    def __init__(
        self,
        version: int,
        defaults: dict[str, object],
        backends: dict[str, object],
        content_type_mapping: dict[str, object],
        **extra: object,
    ) -> None:
        self.version = version
        self.defaults = defaults
        self.backends = backends
        self.content_type_mapping = content_type_mapping
        for key, value in extra.items():
            setattr(self, key, value)
