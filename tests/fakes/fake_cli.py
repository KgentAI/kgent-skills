"""Fake backend CLI: Task 7.2 document wire protocol v1 + the S40 argv recorder.

Two behaviors, selected by the invocation:

1. **argv recorder (S40, Task 7.1)**: when ``FAKE_CLI_ARGV_OUT`` is set in the
   environment, ``sys.argv`` is written verbatim to that JSON path and the
   script exits 0 — document state is untouched. Preserves
   :mod:`tests.test_injection` byte-for-byte.

2. **document CLI (conformance, Task 7.2)**: invoked as
   ``python fake_cli.py --state <path> <backend> <subcommand> ... --json`` it
   implements the wire protocol v1 (§8.5) with per-backend state persisted to
   ``<path>``. Each call is a fresh subprocess, so the state file is the only
   cross-call memory: every invocation loads it, mutates, saves it back.

   Protocol (stdout is always a single JSON object; ``--json`` is accepted as
   a trailing marker and never part of the payload):

       documents create --title <t> --content <c>      → {"id": "<native-id>"}
       documents read <native-id>                       → {"id","title","content",
                                                           "updated_at","version","archived"}
       documents update <native-id> --content <c>
                       [--version <rev>]                → {"ok": true}
       documents delete|archive|unarchive <native-id>   → {"ok": true}
       search --query <q> --keyword --top-k <n>         → {"results":[{id,title,snippet,rank}]}
       version                                          → {"ok": true, "version": "1.0.0"}

   Failures print ``{"error": "<message>"}`` to **stderr** and exit nonzero
   (the adapter's ``normalize_error`` turns that into :class:`AdapterError`).
   Updating with a stale ``--version`` exits 3 with ``version conflict:
   expected <E> found <F>`` — the adapter surfaces the normalized error; the
   optimistic-concurrency ``VersionConflict`` encoding lives in the router's
   ``FakeBackend`` unit tests instead (see ``tests/test_adapters.py``).

   Per-backend state file layout::

       {"<backend>": {"seq": int, "docs": {native_id: {
           "id", "title", "content", "updated_at", "version", "archived"}}}}
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

ARGV_OUT_ENV = "FAKE_CLI_ARGV_OUT"

#: Backend names recognized as the state bucket after ``--state <path>``.
KNOWN_BACKENDS = ("lark", "dingtalk", "wecom")


# ---------------------------------------------------------------------------
# entry
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)

    # Task 7.1 behavior: pure argv recorder (no --state support).
    out = os.environ.get(ARGV_OUT_ENV)
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({"argv": args}, fh)
        return 0

    state_path, backend, rest = _parse_invocation(args)
    if state_path is None:
        return _fail("missing --state <path>", 2)
    if backend is None:
        return _fail("missing backend name (lark|dingtalk|wecom)", 2)
    state = _load_state(state_path)
    bucket = state.setdefault(backend, {"seq": 0, "docs": {}})
    exit_code = _dispatch(bucket, rest)
    _save_state(state_path, state)
    return exit_code


# ---------------------------------------------------------------------------
# invocation parsing
# ---------------------------------------------------------------------------


def _parse_invocation(args: list[str]) -> tuple[str | None, str | None, list[str]]:
    """Walk ``--state <path>`` and the backend token; the remainder is the
    subcommand (``--json`` marker tokens are stripped)."""
    state_path: str | None = None
    backend: str | None = None
    rest: list[str] = []
    i = 1  # skip the script path
    while i < len(args):
        token = args[i]
        if token == "--state":
            state_path = args[i + 1] if i + 1 < len(args) else None
            i += 2
        elif backend is None and token in KNOWN_BACKENDS:
            backend = token
            i += 1
        else:
            rest = args[i:]
            break
    return state_path, backend, [t for t in rest if t != "--json"]


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------


def _dispatch(bucket: dict[str, Any], rest: list[str]) -> int:
    if not rest:
        return _fail("empty subcommand", 2)
    if rest == ["version"]:
        print(json.dumps({"ok": True, "version": "1.0.0"}))
        return 0
    if rest[0] == "documents" and len(rest) >= 2:
        return _documents(bucket, rest[1], rest[2:])
    if rest[0] == "search":
        return _search(bucket, rest[1:])
    return _fail(f"unknown subcommand: {' '.join(rest)}", 2)


def _documents(bucket: dict[str, Any], op: str, args: list[str]) -> int:
    docs: dict[str, Any] = bucket["docs"]
    seq: int = bucket["seq"]

    if op == "create":
        title = _opt(args, "--title")
        content = _opt(args, "--content")
        if title is None or content is None:
            return _fail("documents create requires --title and --content", 2)
        seq += 1
        bucket["seq"] = seq
        native = f"doc{seq}"
        docs[native] = {
            "id": native,
            "title": title,
            "content": content,
            "updated_at": _now(),
            "version": "v1",
            "archived": False,
        }
        print(json.dumps({"id": native}))
        return 0

    native = args[0] if args else None
    if native is None:
        return _fail(f"documents {op} requires <native-id>", 2)
    doc = docs.get(native)

    if op == "read":
        if doc is None:
            return _fail(f"document not found: {native}")
        if doc["archived"]:
            return _fail(f"document archived: {native}")
        print(
            json.dumps(
                {k: doc[k] for k in ("id", "title", "content", "updated_at", "version", "archived")}
            )
        )
        return 0

    if doc is None:
        return _fail(f"document not found: {native}")

    if op == "update":
        content = _opt(args, "--content")
        if content is None:
            return _fail("documents update requires --content", 2)
        expected = _opt(args, "--version")
        if expected is not None and expected != doc["version"]:
            return _fail(f"version conflict: expected {expected} found {doc['version']}", 3)
        doc["content"] = content
        _bump_version(doc)
        print(json.dumps({"ok": True}))
        return 0

    if op == "delete":
        del docs[native]
        print(json.dumps({"ok": True}))
        return 0

    if op == "archive":
        doc["archived"] = True
        print(json.dumps({"ok": True}))
        return 0

    if op == "unarchive":
        doc["archived"] = False
        print(json.dumps({"ok": True}))
        return 0

    return _fail(f"unknown documents op: {op}", 2)


def _search(bucket: dict[str, Any], args: list[str]) -> int:
    query = _opt(args, "--query")
    if query is None:
        return _fail("search requires --query", 2)
    if "--keyword" not in args:
        return _fail("search mode --keyword required (v1 protocol)", 2)
    try:
        top_k = int(_opt(args, "--top-k") or "10")
    except ValueError:
        return _fail("search --top-k must be an integer", 2)
    matches = [
        doc
        for doc in bucket["docs"].values()
        if not doc["archived"] and (query in doc["title"] or query in doc["content"])
    ]
    results = [
        {"id": doc["id"], "title": doc["title"], "snippet": doc["content"][:120], "rank": i}
        for i, doc in enumerate(matches[:top_k], start=1)
    ]
    print(json.dumps({"results": results}))
    return 0


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _opt(args: list[str], flag: str) -> str | None:
    for i, token in enumerate(args):
        if token == flag and i + 1 < len(args):
            return args[i + 1]
    return None


def _bump_version(doc: dict[str, Any]) -> None:
    current = str(doc["version"])
    n = 2
    if current.startswith("v"):
        try:
            n = int(current[1:]) + 1
        except ValueError:
            n = 2
    doc["version"] = f"v{n}"
    doc["updated_at"] = _now()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fail(message: str, exit_code: int = 1) -> int:
    print(json.dumps({"error": message}), file=sys.stderr)
    return exit_code


def _load_state(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _save_state(path: str, state: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False)


if __name__ == "__main__":
    sys.exit(main())
