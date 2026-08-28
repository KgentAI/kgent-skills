"""Skills layer — orchestration primitives for kgent workflows.

Skills are backend-agnostic: they call the Router primitives (resolve_intent,
execute, search) and never touch adapters directly (S65).
"""

from __future__ import annotations

__all__: list[str] = []
