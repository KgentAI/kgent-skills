"""CLI transport for backend adapters (§8.5): argv-array subprocess invocation.

Backend CLIs are invoked with argv arrays only — **never** a shell string
(S40, FM10). User-supplied strings travel as discrete arguments; argument
shape is validated before exec (N12). Timeouts normalize to
:class:`AdapterTimeoutError` and spawn failures to :class:`SubprocessError`
(§8.1). Backend DSLs are built with :func:`kgent.adapters.base.escape_query` —
raw user query interpolation is forbidden (S41).
"""

from __future__ import annotations

import subprocess
from typing import NamedTuple

from kgent.adapters.base import _validate_argv
from kgent.errors import AdapterTimeoutError, SubprocessError

__all__ = ["SubprocessResult", "run_cli"]


class SubprocessResult(NamedTuple):
    """Normalized subprocess outcome: exit status + captured streams."""

    returncode: int
    stdout: str
    stderr: str


def run_cli(
    argv: list[str],
    timeout: float,
    *,
    env: dict[str, str] | None = None,
) -> SubprocessResult:
    """Run a backend CLI via an argv array with a hard timeout (§8.5).

    - ``shell=False`` is explicit: argv is never joined into a shell string
      (S40); metacharacters in user data stay inert.
    - ``timeout`` bounds the whole subprocess; :class:`AdapterTimeoutError`
      on expiry.
    - ``env=None`` inherits the parent environment; a provided ``env`` is
      passed verbatim to the subprocess.
    - Spawn failures (missing executable, etc.) raise :class:`SubprocessError`.
    """
    _validate_argv(argv)
    if timeout <= 0:
        raise ValueError(f"timeout must be positive, got {timeout}")
    try:
        proc = subprocess.run(
            argv,
            timeout=timeout,
            capture_output=True,
            text=True,
            shell=False,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise AdapterTimeoutError(f"adapter CLI timed out after {timeout:.1f}s") from exc
    except OSError as exc:
        raise SubprocessError(f"failed to start adapter CLI: {exc}") from exc
    return SubprocessResult(proc.returncode, proc.stdout, proc.stderr)
