"""Invocation hardening (§8.5; S40, S41, N12): argv-array subprocess invocation
(never shell interpolation), query-language escaping, and the Adapter base
(capability dispatch, error normalization, argv-shape validation).

Backend CLIs are invoked with argv arrays only — titles, content, and any
user-supplied string travel as discrete arguments, so shell metacharacters are
inert (S40, FM10). Backend filter DSLs are built with escaping only — raw
interpolation of user query strings is forbidden (S41). The Adapter ABC
provides the shared transport helpers every adapter needs (§1.2, §3.1, §8.5).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from kgent.adapters.base import Adapter, escape_query
from kgent.adapters.cli_adapter import SubprocessResult, run_cli
from kgent.errors import AdapterError, AdapterTimeoutError, SubprocessError

FAKE_CLI = Path(__file__).resolve().parent / "fakes" / "fake_cli.py"


def _record_argv(
    tmp_path: Path, *args: str, env: dict[str, str] | None = None
) -> tuple[list[str], SubprocessResult]:
    """Run ``fake_cli.py`` with ``args`` and return (recorded argv, result).

    The fake records ``sys.argv`` verbatim, so ``recorded[0]`` is the script
    path and ``recorded[i]`` for ``i >= 1`` are the discrete args given to the
    subprocess (the brief's ``argv[3]`` is the 4th element, i.e. the title).
    """
    out = tmp_path / "argv.json"
    run_env = dict(os.environ)
    if env:
        run_env.update(env)
    run_env["FAKE_CLI_ARGV_OUT"] = str(out)
    result = run_cli([sys.executable, str(FAKE_CLI), *args], timeout=30, env=run_env)
    recorded = json.loads(out.read_text(encoding="utf-8"))
    return recorded["argv"], result


# ---------------------------------------------------------------------------
# S40 — shell metacharacters arrive as one inert argv element (FM10)
# ---------------------------------------------------------------------------


def test_s40_shell_metacharacters_in_title_arrive_inert(tmp_path):
    """'; … ; #' stays inside a SINGLE argv element; nothing is executed."""
    title = f"; touch {(tmp_path / 'pwned').as_posix()}; #"
    argv, result = _record_argv(tmp_path, "store", "--title", title)

    assert result.returncode == 0
    assert len(argv) == 4  # [script, store, --title, title]
    assert argv[3] == title  # one discrete arg, byte-identical — never split
    assert ";" in argv[3] and "#" in argv[3]
    assert not (tmp_path / "pwned").exists()


def test_s40_injection_payload_never_touches_disk(tmp_path):
    """Brief payload ('; touch <path>; #') is inert data, no file created."""
    payload = f"; touch {(tmp_path / 'pwned').as_posix()}; #"
    argv, result = _record_argv(tmp_path, "store", "--title", payload)

    assert result.returncode == 0
    assert argv[2] == "--title" and argv[3] == payload
    assert not (tmp_path / "pwned").exists()


def test_s40_shell_false_by_construction_passes_args_verbatim(tmp_path):
    """Multiple metacharacter-packed args each survive as their own element."""
    argv, _ = _record_argv(
        tmp_path,
        "title;x",
        "$(rm -rf /)",
        "a b & c | d > e",
        "`backtick`",
    )
    # [script, title;x, $(rm -rf /), a b & c | d > e, `backtick`]
    assert argv[1:] == ["title;x", "$(rm -rf /)", "a b & c | d > e", "`backtick`"]


def test_s40_exit_code_stdout_stderr_surfaced():
    """Non-zero exits and captured streams flow back through SubprocessResult."""
    probe = "import sys; print('out-line'); print('err-line', file=sys.stderr); sys.exit(7)"
    result = run_cli([sys.executable, "-c", probe], timeout=30)

    assert result.returncode == 7
    assert "out-line" in result.stdout
    assert "err-line" in result.stderr


# ---------------------------------------------------------------------------
# N12 — argument-shape validation before exec (§8.5)
# ---------------------------------------------------------------------------


def test_n12_run_cli_rejects_non_string_argv_before_exec():
    """Non-str argv elements are rejected by validation, not by the OS."""
    with pytest.raises(AdapterError, match="argv\\[1\\] must be str"):
        run_cli([sys.executable, 42], timeout=1)  # type: ignore[list-item]


def test_n12_run_cli_rejects_non_list_argv():
    with pytest.raises(AdapterError, match="argv must be a list"):
        run_cli("echo hi", timeout=1)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# S41 — query-language escaping (filter DSL built by escaping, never raw)
# ---------------------------------------------------------------------------


def test_s41_query_language_injection_escaped():
    """Raw user query never appears unescaped in the request (S41)."""
    q = 'title ~ "%" AND creator != currentUser()'
    sent = escape_query(q)

    assert '"%"' not in sent  # the dangerous literal is gone
    assert q not in sent  # raw string absent in any unescaped form
    # escaping is meaningful: quote and percent get backslash-escaped
    assert '\\"\\%\\"' in sent
    assert sent.count("\\") == 3  # \" and \% and \" — no other backslashes


def test_s41_backslash_escaping_is_order_safe():
    """A user backslash must not turn our escapes into plain chars."""
    q = r'path\* AND "a\"b" AND 50%'
    sent = escape_query(q)

    assert q not in sent
    # user backslashes are doubled first, so every escape stays a pure escape
    assert "\\*" in sent and "\\%" in sent and "\\\\" in sent
    assert "path*" not in sent and "50%" not in sent and 'a"b' not in sent
    assert sent.count('\\"') == 3  # opening, inner user-escape, closing


def test_s41_generic_escapes_wildcards_and_quotes():
    q = 'a * b % c " d'
    sent = escape_query(q)

    assert sent == 'a \\* b \\% c \\" d'


def test_s41_dsl_specific_escape_sets():
    """Per-DSL sets: lark only quotes/backslash; generic is the safe default."""
    q = 'a "b" % c'
    lark = escape_query(q, dsl="lark")
    generic = escape_query(q, dsl="generic")

    assert '\\"' in lark  # lark escapes quotes
    assert "%" in lark  # lark leaves % alone (raw)
    assert "\\%" not in lark and "\\%" in generic  # generic escapes %
    assert escape_query(q, dsl="unknown-dialect") == generic  # safe default


def test_s41_plain_query_unchanged():
    assert escape_query("meeting notes") == "meeting notes"


# ---------------------------------------------------------------------------
# Adapter base — capability dispatch, error normalization, argv validation
# ---------------------------------------------------------------------------


class _DummyAdapter(Adapter):
    name = "dummy"

    def create_document(self, title: str, content: str, metadata: object) -> str:
        return f"kgent://dummy/{title}"


def test_adapter_invoke_dispatches_to_capability():
    adapter = _DummyAdapter()
    assert adapter.invoke("create_document", title="Retro", content="body", metadata=None) == (
        "kgent://dummy/Retro"
    )


def test_adapter_invoke_unknown_method_raises_adapter_error():
    with pytest.raises(AdapterError, match="no capability 'frobnicate'"):
        _DummyAdapter().invoke("frobnicate")


def test_adapter_unimplemented_capability_raises_not_implemented():
    adapter = _DummyAdapter()
    with pytest.raises(NotImplementedError):
        adapter.invoke("read_document", doc_uri="kgent://dummy/doc1")


def test_adapter_normalize_error_nonzero_exit_uses_stderr():
    err = _DummyAdapter().normalize_error(3, "\n  permission denied for token xyz\n")
    assert isinstance(err, AdapterError)
    assert err.exit_code == 1
    assert "exit code 3" in str(err)
    assert "permission denied" in str(err)
    assert "xyz" in str(err)  # normalized message is stderr-derived


def test_adapter_normalize_error_accepts_bare_nonzero():
    err = _DummyAdapter().normalize_error(2, "   ")
    assert isinstance(err, AdapterError)
    assert "exit code 2" in str(err)


def test_adapter_normalize_error_rejects_success_exit():
    with pytest.raises(ValueError, match="successful exit"):
        _DummyAdapter().normalize_error(0, "")


def test_adapter_check_argv_rejects_non_string():
    with pytest.raises(AdapterError, match="argv\\[3\\] must be str"):
        _DummyAdapter()._check_argv(["a", "b", "c", 1])  # type: ignore[list-item]


def test_adapter_check_argv_rejects_non_list():
    with pytest.raises(AdapterError, match="argv must be a list"):
        _DummyAdapter()._check_argv("abc")  # type: ignore[arg-type]


def test_adapter_check_argv_accepts_string_list():
    _DummyAdapter()._check_argv(["store", "--title", "x; y"])  # no raise


# ---------------------------------------------------------------------------
# run_cli — timeout and spawn errors normalize to the AdapterError family
# ---------------------------------------------------------------------------


def test_run_cli_timeout_raises_adapter_timeout_error():
    with pytest.raises(AdapterTimeoutError, match="timed out after 0.3"):
        run_cli([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.3)


def test_run_cli_missing_executable_raises_subprocess_error(tmp_path):
    with pytest.raises(SubprocessError, match="failed to start adapter CLI"):
        run_cli([str(tmp_path / "no-such-exe"), "arg"], timeout=5)


def test_adapter_error_family_exit_codes_and_hierarchy():
    assert AdapterError("x").exit_code == 1
    assert AdapterTimeoutError("x").exit_code == 1
    assert SubprocessError("x").exit_code == 1
    assert isinstance(AdapterTimeoutError("x"), AdapterError)
    assert isinstance(SubprocessError("x"), AdapterError)
