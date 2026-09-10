"""Behavior tests for tools/artifact-smoke.sh manifest parsing.

Regression: on Windows checkouts (core.autocrlf) the manifest lands with CRLF
line endings; the probe loop then passes ``--help\\r`` to the CLI and argparse
rejects it (exit 2) — 17/18 probes failed while every command was healthy
(hit 2026-09-09). The script must tolerate CRLF manifest line endings.

Each test runs a COPY of the script in a hermetic tmp tree against a stub
artifact that mimics argparse strictness: any argument containing ``\\r`` is
an unrecognized-argument failure (exit 2).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "tools" / "artifact-smoke.sh"


def _find_bash() -> str | None:
    found = shutil.which("bash")
    if found:
        return found
    for candidate in (
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
    ):
        if Path(candidate).exists():
            return candidate
    return None


BASH = _find_bash()

pytestmark = pytest.mark.skipif(BASH is None, reason="bash is required to run artifact-smoke.sh")


def _run_smoke(tmp_path: Path, manifest_text: str) -> subprocess.CompletedProcess[str]:
    """Copy the script into a tmp tree, write the given manifest next to it,
    and run it with a strict stub artifact at $HOME/.local/bin/kgent."""
    tree = tmp_path / "tools"
    tree.mkdir()
    shutil.copy2(SCRIPT, tree / "artifact-smoke.sh")
    (tree / "surface-manifest.txt").write_text(manifest_text, encoding="utf-8", newline="")

    home = tmp_path / "home"
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    stub = bin_dir / "kgent"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "# strict like argparse: a CR inside any token is an unrecognized arg\n"
        'for a in "$@"; do\n'
        "  case \"$a\" in *$'\\r'*) exit 2 ;; esac\n"
        "done\n"
        "exit 0\n",
        encoding="utf-8",
    )

    env = dict(os.environ)
    env["HOME"] = str(home)
    return subprocess.run(
        [BASH, str(tree / "artifact-smoke.sh")],  # type: ignore[list-item]
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


MANIFEST_LINES = "route --help\nsearch --help\ndoctor --help\n"


def test_crlf_manifest_probes_pass(tmp_path: Path) -> None:
    """A CRLF-checkout manifest must not poison probe arguments."""
    result = _run_smoke(tmp_path, MANIFEST_LINES.replace("\n", "\r\n"))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "3/3 surface probes passed" in result.stdout


def test_lf_manifest_probes_pass(tmp_path: Path) -> None:
    """Sanity: the stub rejects CR args — an LF manifest must pass."""
    result = _run_smoke(tmp_path, MANIFEST_LINES)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "3/3 surface probes passed" in result.stdout
