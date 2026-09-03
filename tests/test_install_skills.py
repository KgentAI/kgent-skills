"""Behavior tests for tools/install-skills.sh (seams S1-S7, confirmed design).

The seam is the script's public interface: ``bash tools/install-skills.sh
[flags]`` + observable filesystem state + exit codes. Every test runs
hermetically in a temp ``$HOME`` sandbox (the script's contract: all paths
derive from ``$HOME``). Backend binaries (uv) are faked via a recording stub
on the sandbox PATH - no network, no real installs, and the real
``~/.agents`` / ``~/.claude`` are never touched.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "tools" / "install-skills.sh"
EXPECTED_SKILLS = ("knowledge-storage", "question-answering", "wiki-setup")


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

pytestmark = pytest.mark.skipif(BASH is None, reason="bash is required to run the installer script")


def _coreutils_dir() -> str | None:
    """Git's usr/bin holds the POSIX coreutils the script needs (mkdir, ln...)."""
    bash_dir = Path(BASH).parent  # type: ignore[arg-type]
    candidates = [bash_dir, bash_dir.parent / "usr" / "bin"]
    for cand in candidates:
        if (cand / ("mkdir.exe" if os.name == "nt" else "mkdir")).exists():
            return str(cand)
    return None


def _run(
    home: Path,
    *args: str,
    extra_path: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["HOME"] = str(home)
    coreutils = _coreutils_dir()
    if coreutils:
        sep = ";" if os.name == "nt" else ":"
        env["PATH"] = coreutils + sep + env.get("PATH", "")
    if extra_path:
        sep = ";" if os.name == "nt" else ":"
        env["PATH"] = extra_path + sep + env.get("PATH", "")
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [BASH, str(SCRIPT), *args],  # type: ignore[list-item]
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def _write_fake_uv(bin_dir: Path) -> Path:
    """A recording uv stub (extensionless bash script - its consumer is bash,
    and `command -v uv` does not see .cmd files). It logs argv next to itself
    (via $0 - a Windows path embedded here would be mangled by bash escapes)
    and simulates install/uninstall by placing/removing a kgent stub that
    answers --help like the real CLI."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    log = bin_dir / "uv-calls.log"
    uv = bin_dir / "uv"
    lines = [
        "#!/usr/bin/env bash",
        'dir="$(cd "$(dirname "$0")" && pwd)"',
        'echo "$@" >> "$dir/uv-calls.log"',
        'if [ "$1" = "tool" ] && [ "$2" = "install" ]; then',
        "  {",
        "    echo '#!/usr/bin/env bash'",
        "    echo 'echo usage: kgent wiki search create'",
        '  } > "$dir/kgent"',
        "fi",
        'if [ "$1" = "tool" ] && [ "$2" = "uninstall" ] && [ -f "$dir/kgent" ]; then rm -f "$dir/kgent"; fi',
    ]
    uv.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
    return log


@pytest.fixture
def fake_uv(tmp_path: Path) -> Path:
    """Returns the log path; the stub dir is meant for extra_path."""
    return _write_fake_uv(tmp_path / "fakebin")


def _assert_live_link(entry: Path, repo_skill: Path) -> None:
    """The entry resolves to the repo skill (not a copy): realpath equality."""
    assert (entry / "SKILL.md").exists(), f"SKILL.md missing through {entry}"
    assert Path(os.path.realpath(entry)) == Path(os.path.realpath(repo_skill)), (
        f"{entry} does not resolve to {repo_skill} (got {os.path.realpath(entry)})"
    )


# ---------------------------------------------------------------------------
# S2 - idempotent update + stale-copy migration
# ---------------------------------------------------------------------------


def test_s2a_rerun_is_idempotent_and_repo_safe(tmp_path: Path, fake_uv: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").mkdir()

    assert _run(home, extra_path=str(fake_uv.parent)).returncode == 0
    result = _run(home, extra_path=str(fake_uv.parent))  # second run IS the update
    assert result.returncode == 0, result.stdout + result.stderr

    for name in EXPECTED_SKILLS:
        _assert_live_link(home / ".agents" / "skills" / name, REPO_ROOT / "skills" / name)
    # safety: replacing a junction must never touch the repo through the link
    for name in EXPECTED_SKILLS:
        assert (REPO_ROOT / "skills" / name / "SKILL.md").exists(), f"repo skill {name} damaged!"


def test_s2b_stale_copy_replaced_with_live_link(tmp_path: Path, fake_uv: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").mkdir()
    stale = home / ".agents" / "skills" / "knowledge-storage"
    stale.mkdir(parents=True)
    (stale / "SKILL.md").write_text("# stale junk", encoding="utf-8")

    result = _run(home, extra_path=str(fake_uv.parent))

    assert result.returncode == 0, result.stdout + result.stderr
    _assert_live_link(stale, REPO_ROOT / "skills" / "knowledge-storage")
    assert "replacing" in (result.stdout + result.stderr).lower()


def test_s2c_backup_preserves_replaced_dir(tmp_path: Path, fake_uv: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").mkdir()
    stale = home / ".agents" / "skills" / "wiki-setup"
    stale.mkdir(parents=True)
    (stale / "SKILL.md").write_text("# old content", encoding="utf-8")

    result = _run(home, "--backup", extra_path=str(fake_uv.parent))

    assert result.returncode == 0, result.stdout + result.stderr
    _assert_live_link(stale, REPO_ROOT / "skills" / "wiki-setup")
    backups = home / ".agents" / "skills-backups"
    saved = list(backups.rglob("SKILL.md"))
    assert saved, "no backup of the replaced dir was kept"
    assert "# old content" in saved[0].read_text(encoding="utf-8")
    # backups live OUTSIDE the skills dir so agents never index them
    assert backups.parent == home / ".agents"


# ---------------------------------------------------------------------------
# S3 - --copy mode (frozen install) and mode switching
# ---------------------------------------------------------------------------


def test_s3_copy_mode_frozen_then_link_mode_replaces(tmp_path: Path, fake_uv: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").mkdir()
    hub = home / ".agents" / "skills"

    result = _run(home, "--copy", extra_path=str(fake_uv.parent))
    assert result.returncode == 0, result.stdout + result.stderr
    for name in EXPECTED_SKILLS:
        entry = hub / name
        assert (entry / "SKILL.md").exists()
        # frozen: does NOT resolve to the repo
        assert Path(os.path.realpath(entry)) != Path(os.path.realpath(REPO_ROOT / "skills" / name))
        # content matches the repo at copy time
        assert (entry / "SKILL.md").read_text(encoding="utf-8") == (
            REPO_ROOT / "skills" / name / "SKILL.md"
        ).read_text(encoding="utf-8")

    # link mode replaces the frozen copy
    result = _run(home, extra_path=str(fake_uv.parent))
    assert result.returncode == 0, result.stdout + result.stderr
    for name in EXPECTED_SKILLS:
        _assert_live_link(hub / name, REPO_ROOT / "skills" / name)

    # and back again
    result = _run(home, "--copy", extra_path=str(fake_uv.parent))
    assert result.returncode == 0, result.stdout + result.stderr
    for name in EXPECTED_SKILLS:
        assert Path(os.path.realpath(hub / name)) != Path(
            os.path.realpath(REPO_ROOT / "skills" / name)
        )


# ---------------------------------------------------------------------------
# S4 - uninstall (skills + CLI via recorded backend)
# ---------------------------------------------------------------------------


def test_s4_uninstall_removes_entries_and_cli_via_backend(tmp_path: Path, fake_uv: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").mkdir()
    bin_dir = fake_uv.parent

    result = _run(home, extra_path=str(bin_dir))
    assert result.returncode == 0, result.stdout + result.stderr
    install_log = fake_uv.read_text(encoding="utf-8")
    assert "tool install --force" in install_log
    assert (home / ".kgent" / "install-backend.txt").read_text(encoding="utf-8").strip() == "uv"

    result = _run(home, "--uninstall", extra_path=str(bin_dir))
    assert result.returncode == 0, result.stdout + result.stderr
    for name in EXPECTED_SKILLS:
        assert not (home / ".agents" / "skills" / name).exists()
        assert not (home / ".claude" / "skills" / name).exists()
    # the CLI is torn down through the SAME backend that installed it
    uninstall_log = fake_uv.read_text(encoding="utf-8")
    assert "tool uninstall kgent" in uninstall_log
    # and the repo is never touched through the removed links
    for name in EXPECTED_SKILLS:
        assert (REPO_ROOT / "skills" / name / "SKILL.md").exists()


def test_s4b_uninstall_without_prior_install_is_graceful(tmp_path: Path, fake_uv: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").mkdir()

    result = _run(home, "--uninstall", extra_path=str(fake_uv.parent))
    assert result.returncode == 0, result.stdout + result.stderr
    # no recorded provenance -> the CLI leg is left alone entirely
    assert not fake_uv.exists() or fake_uv.read_text(encoding="utf-8").strip() == ""


# ---------------------------------------------------------------------------
# S5 - CLI backend dispatch: --no-cli skips; forced-none fails loudly
# ---------------------------------------------------------------------------


def test_s5a_no_cli_skips_backend(tmp_path: Path, fake_uv: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").mkdir()

    result = _run(home, "--no-cli", extra_path=str(fake_uv.parent))

    assert result.returncode == 0, result.stdout + result.stderr
    # the backend was never invoked
    assert not fake_uv.exists() or fake_uv.read_text(encoding="utf-8").strip() == ""
    # skills are still installed
    for name in EXPECTED_SKILLS:
        _assert_live_link(home / ".agents" / "skills" / name, REPO_ROOT / "skills" / name)
    # and no CLI provenance was recorded
    assert not (home / ".kgent" / "install-backend.txt").exists()


def test_s5b_backend_none_fails_loudly(tmp_path: Path) -> None:
    """CLI requested but disabled -> skills install, health check gates, exit
    is non-zero and the failure is named (S7 gating)."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").mkdir()

    result = _run(home, extra_env={"KGENT_CLI_BACKEND": "none"})

    assert result.returncode != 0
    assert "KGENT_CLI_BACKEND=none" in (result.stdout + result.stderr)
    # the failure is ONLY the CLI leg - skills are fine
    for name in EXPECTED_SKILLS:
        _assert_live_link(home / ".agents" / "skills" / name, REPO_ROOT / "skills" / name)


# ---------------------------------------------------------------------------
# S7 - health check: summary on the healthy path (the gating branch is
# exercised by S5b: CLI requested but missing -> non-zero, failure named)
# ---------------------------------------------------------------------------


def test_s7_healthy_run_prints_summary(tmp_path: Path, fake_uv: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").mkdir()

    result = _run(home, extra_path=str(fake_uv.parent))

    assert result.returncode == 0, result.stdout + result.stderr
    for name in EXPECTED_SKILLS:
        assert name in result.stdout
    assert "install OK" in result.stdout


# ---------------------------------------------------------------------------
# S1 - install, happy path
# ---------------------------------------------------------------------------


def test_s1_install_creates_hub_and_claude_links(tmp_path: Path, fake_uv: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").mkdir()  # Claude Code present -> claude hop expected

    result = _run(home, extra_path=str(fake_uv.parent))

    assert result.returncode == 0, result.stdout + result.stderr
    hub = home / ".agents" / "skills"
    for name in EXPECTED_SKILLS:
        _assert_live_link(hub / name, REPO_ROOT / "skills" / name)
        # claude hop: resolvable through both links
        _assert_live_link(home / ".claude" / "skills" / name, REPO_ROOT / "skills" / name)
