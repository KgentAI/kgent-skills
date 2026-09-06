"""CLI entry point: argparse subcommands → primitives → exit codes (§12).

``main(argv)`` parses ``argv`` (default ``sys.argv[1:]``), loads the effective
config from ``KGENT_HOME``/``~/.kgent``, builds a :class:`~kgent.router.core.Router`
from the adapter registry, and dispatches to the matching command handler.

Every handler returns an ``int`` exit code (0 ok · 2 partial · 1 failure ·
3 policy-rejected · 4 version conflict). ``KgentError`` subclasses are caught
at the top level and mapped to their ``.exit_code``. ``--json`` switches
output to schema-versioned JSON.

Non-interactive sessions (stdin not a TTY — tests, pipes) auto-confirm writes
when ``--backends`` is explicit and content is non-empty (S3: ``--yes``
bypass still requires both). Interactive terminals prompt for confirmation
unless ``--yes`` is passed.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

from kgent.adapters import registry
from kgent.capabilities.detect import setup as detect_setup
from kgent.config import _yaml
from kgent.config.loader import load_effective_config
from kgent.config.migrate import migrate_config
from kgent.config.schema import Config
from kgent.config.trusted import trust_directory
from kgent.config.validate import doctor, validate_config
from kgent.errors import ConfigError, KgentError, PolicyError, VersionConflict
from kgent.router.audit import AuditLog
from kgent.router.core import Router
from kgent.router.journal import Journal
from kgent.router.journal import undo as journal_undo
from kgent.router.policy import confirm
from kgent.search.fanout import build_footer, exit_code_for_failures, truncate
from kgent.search.rank import rrf
from kgent.types import SearchResult, WriteProposal
from kgent.uri import parse_uri

__all__ = ["main"]

_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Router construction
# ---------------------------------------------------------------------------


def _home() -> Path:
    return Path(os.environ.get("KGENT_HOME", str(Path.home() / ".kgent")))


def _load_config() -> tuple[Config, list[str]]:
    """Load the effective global config (no project dir for CLI — §2.3)."""
    home = _home()
    config_path = home / "config.yaml"
    # Use load_effective_config with cwd as project dir (so trust still works)
    from pathlib import Path as _P

    try:
        project_dir = _P.cwd()
    except OSError:
        project_dir = home
    return load_effective_config(config_path, project_dir, {})


def _build_router() -> tuple[Router, Config]:
    """Build a Router from KGENT_HOME config + the adapter registry."""
    config, _warnings = _load_config()
    backends: dict[str, Any] = {}
    for name in config.backends:
        try:
            adapter = registry.get(name)
        except ConfigError:
            continue  # backend configured but no adapter registered; skip silently
        backends[name] = adapter
        # Enrich config backend spec with the adapter's capabilities so
        # resolve_intent can gate on them (S59 adapter preference).
        caps = getattr(adapter, "capabilities", None)
        if caps and isinstance(caps, dict):
            config.backends[name]["capabilities"] = caps
    journal = Journal(_home())
    audit = AuditLog(
        path=_home() / "audit.ndjson",
        redact_queries=bool(config.audit.get("redact_queries", True)),
    )
    return Router(config=config, backends=backends, journal=journal, audit=audit), config


def _confirmation_mode(args: argparse.Namespace) -> str:
    """Resolve the confirmation mode from CLI flags + TTY state."""
    if getattr(args, "yes", False):
        return "--yes"
    if not sys.stdin.isatty():
        return "--yes"
    return "interactive"


def _json_out(data: dict[str, Any]) -> None:
    data.setdefault("schema_version", _SCHEMA_VERSION)
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _text_out(text: str) -> None:
    print(text)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def _cmd_create(args: argparse.Namespace) -> int:
    router, _config = _build_router()
    wiki_space = getattr(args, "wiki_space", None)
    parent_token = getattr(args, "parent_node_token", None)
    if parent_token is not None and wiki_space is None:
        raise PolicyError("--parent-node-token requires --wiki-space")
    backends_list = _target_backends(args, router)
    if wiki_space is not None:
        # §6.10/§12 rule 9 (S79): reject wiki flags on backends without a
        # knowledge-space product BEFORE any write — exit 3 (policy-rejected).
        _require_wiki_backends(router, backends_list)
    proposal = WriteProposal(
        operation="create",
        targets=[(b, None) for b in backends_list],
        title=args.title,
        content=args.content or "",
        content_type=getattr(args, "content_type", None),
        sensitivity=getattr(args, "sensitivity", "internal"),
        wiki_space=wiki_space,
        parent_node_token=parent_token,
    )
    mode = _confirmation_mode(args)
    explicit = bool(getattr(args, "backends", None))
    confirmation = confirm(proposal, mode, explicit_backends=explicit)
    if confirmation == "rejected":
        _text_out("rejected: write not confirmed")
        return 3
    # ``execute`` is the router write gate (confirmed-write API), not SQL
    # pi-lens-ignore: python-sql-injection
    result = router.execute(proposal, confirmation=confirmation)
    if getattr(args, "json", False):
        targets = _as_str_list(result.journal_entry.get("targets", []))
        out: dict[str, Any] = {
            "operation": "create",
            "op_id": result.op_id,
            "status": result.status,
            "targets": targets,
        }
        if wiki_space is not None:
            # §6.10: the JSON output reports node_token + position (S77).
            out["node_type"] = "wiki_node"
            out["node_token"] = targets[0].rsplit("/", 1)[-1] if targets else None
            out["space_id"] = wiki_space
            out["parent_node_token"] = parent_token
        else:
            out["node_type"] = "doc"
        _json_out(out)
    return result.exit_code


def _cmd_update(args: argparse.Namespace) -> int:
    router, _config = _build_router()
    doc_uri = args.doc_uri
    proposal = WriteProposal(
        operation="update",
        targets=[(_backend_for_uri(doc_uri), doc_uri)],
        title=getattr(args, "title", None),
        content=args.content or "",
        sensitivity=getattr(args, "sensitivity", "internal"),
        expected_version=getattr(args, "expected_version", None),
    )
    mode = _confirmation_mode(args)
    explicit = True  # update always targets a concrete doc_uri
    confirmation = confirm(proposal, mode, explicit_backends=explicit)
    if confirmation == "rejected":
        _text_out("rejected: write not confirmed")
        return 3
    # ``execute`` is the router write gate (confirmed-write API), not SQL
    # pi-lens-ignore: python-sql-injection
    result = router.execute(proposal, confirmation=confirmation)
    if result.status == "conflict":
        _text_out(f"conflict: {result.error}")
    if getattr(args, "json", False):
        _json_out(
            {
                "operation": "update",
                "op_id": result.op_id,
                "status": result.status,
                "targets": _as_str_list(result.journal_entry.get("targets", [])),
            }
        )
    return result.exit_code


def _cmd_store(args: argparse.Namespace) -> int:
    """Update-first store workflow: search for a matching title, then create or update."""
    router, _config = _build_router()
    title = args.title
    content = args.content or ""
    backends_list = _target_backends(args, router)

    # Update-first: search each target backend for a doc with the same title
    existing_uri: str | None = None
    for backend_name in backends_list:
        try:
            backend = router.backends[backend_name]
        except KeyError:
            continue
        # Try to search for existing documents with this title
        try:
            # For real adapters, use search to find existing docs (kw search
            # covers wiki nodes + flat docs by default — §6.10).
            if hasattr(backend, "search"):
                results = backend.search(title, mode="keyword", top_k=10, timeout=10.0)
                for result in results:
                    if result.metadata.title == title:
                        existing_uri = result.doc_uri
                        break
            # For FakeBackend (tests), use docs dict
            elif hasattr(backend, "docs"):
                for uri, doc in backend.docs.items():
                    if doc.title == title:
                        existing_uri = uri
                        break
        except Exception as exc:  # noqa: BLE001 — adapter boundary; best-effort lookup
            # N10 (§8.2): never silently drop a failed update-first lookup — surface
            # it on stderr, then proceed with the create proposal (update-first is
            # best-effort, §6.1).
            print(f"update-first: search failed on {backend_name}: {exc}", file=sys.stderr)
        if existing_uri:
            break

    if existing_uri is not None:
        # Update the existing document
        proposal = WriteProposal(
            operation="update",
            targets=[(_backend_for_uri(existing_uri), existing_uri)],
            title=title,
            content=content,
            sensitivity=getattr(args, "sensitivity", "internal"),
        )
    else:
        proposal = WriteProposal(
            operation="create",
            targets=[(b, None) for b in backends_list],
            title=title,
            content=content,
            sensitivity=getattr(args, "sensitivity", "internal"),
        )

    mode = _confirmation_mode(args)
    explicit = bool(getattr(args, "backends", None)) or existing_uri is not None
    confirmation = confirm(proposal, mode, explicit_backends=explicit)
    if confirmation == "rejected":
        _text_out("rejected: write not confirmed")
        return 3

    # --dry-run: show what would happen without writing or journaling.
    if getattr(args, "dry_run", False):
        plan = {
            "operation": proposal.operation,
            "targets": [t for t, _ in proposal.targets],
            "title": proposal.title,
            "update_first": existing_uri is not None,
            "dry_run": True,
        }
        if getattr(args, "json", False):
            _json_out(plan)
        else:
            _text_out(f"dry-run: {proposal.operation} {plan['targets']}")
        return 0

    caller_op_id = getattr(args, "op_id", None)
    try:
        # ``execute`` is the router write gate (confirmed-write API), not SQL
        # pi-lens-ignore: python-sql-injection
        result = router.execute(proposal, confirmation=confirmation, op_id=caller_op_id)
    except Exception as exc:  # noqa: BLE001  — adapters are a platform boundary
        # Backend error during execution: journal what we can, report partial
        _text_out(f"error: {exc}")
        return 2
    if getattr(args, "json", False):
        _json_out(
            {
                "operation": "store",
                "op_id": result.op_id,
                "status": result.status,
                "targets": _as_str_list(result.journal_entry.get("targets", [])),
                "update_first": existing_uri is not None,
            }
        )
    return result.exit_code


def _cmd_search(args: argparse.Namespace) -> int:
    router, _config = _build_router()
    selection = getattr(args, "backends", None)
    top_k = getattr(args, "top_k", 10) or 10
    successes, failures, _clamps = router.search_sync(
        args.query,
        mode="keyword",
        top_k=top_k,
        selection=selection,
    )
    # RRF ranking
    per_backend: dict[str, list[SearchResult]] = {}
    for r in successes:
        per_backend.setdefault(r.metadata.backend, []).append(r)
    ranked_lists = list(per_backend.values())
    fused = rrf(ranked_lists) if ranked_lists else []
    fused = truncate(fused, top_k)

    footer = build_footer(failures)
    exit_code = exit_code_for_failures(failures)

    if getattr(args, "json", False):
        _json_out(
            {
                "results": [
                    {
                        "doc_uri": r.doc_uri,
                        "title": r.metadata.title,
                        "rank": i + 1,
                        "snippet": r.snippet,
                        "backend": r.metadata.backend,
                        "also_available_in": r.also_available_in,
                        # §7.2: node_type discriminates doc | wiki_node; wiki results
                        # additionally carry their space + parent position.
                        "node_type": r.node_type,
                        "space_id": r.space_id,
                        "parent_node_token": r.parent_node_token,
                    }
                    for i, r in enumerate(fused)
                ],
                "failures": failures,
                "footer": footer,
            }
        )
    else:
        for i, r in enumerate(fused, 1):
            snippet = (r.snippet or "")[:80]
            _text_out(f"  {i}. [{r.metadata.backend}] {r.metadata.title} — {snippet}")
            _text_out(f"     {r.doc_uri}")
        if footer:
            _text_out(f"\n({footer})")
    return exit_code


def _cmd_read(args: argparse.Namespace) -> int:
    router, _config = _build_router()
    doc_uri = args.doc_uri
    backend_name = _backend_for_uri(doc_uri)
    try:
        backend = router.backends[backend_name]
    except KeyError:
        _text_out(f"error: backend {backend_name!r} not available")
        return 1
    try:
        doc = backend.read_document(doc_uri)
    except LookupError:
        _text_out(f"error: document {doc_uri!r} not found")
        return 1
    if getattr(args, "json", False):
        _json_out(
            {
                "doc_uri": doc.doc_uri,
                "title": doc.title,
                "content": doc.content,
                "backend": doc.metadata.backend,
                "version": doc.metadata.version,
                "node_type": doc.metadata.node_type,
                "space_id": doc.metadata.space_id,
                "parent_node_token": doc.metadata.parent_node_token,
            }
        )
    else:
        _text_out(f"# {doc.title}\n\n{doc.content}")
    return 0


def _cmd_delete(args: argparse.Namespace) -> int:
    router, _config = _build_router()
    doc_uri = args.doc_uri
    backend_name = _backend_for_uri(doc_uri)
    try:
        backend = router.backends[backend_name]
    except KeyError:
        _text_out(f"error: backend {backend_name!r} not available")
        return 1

    # Offer archive first (S8: delete offers archive first)
    if not getattr(args, "yes", False) and sys.stdin.isatty():
        _text_out(f"Archive on {backend_name} is RECOMMENDED over delete.")
        _text_out("Use 'kgent archive' instead, or pass --yes to confirm delete.")

    try:
        backend.delete_document(doc_uri, None, f"delete-{doc_uri}", None)
    except Exception as exc:  # noqa: BLE001  — adapter boundary
        _text_out(f"error: {exc}")
        return 1

    # Journal the delete
    router.journal.append(
        {
            "schema_version": 1,
            "op_id": f"del-{doc_uri}",
            "ts": _now_iso(),
            "operation": "delete",
            "targets": [doc_uri],
            "idempotency_key": f"del-{doc_uri}",
            "snapshot": {},
            "proposal_hash": "",
            "confirmation": _confirmation_mode(args),
            "sensitivity": "internal",
            "status": "ok",
        }
    )
    if getattr(args, "json", False):
        _json_out({"operation": "delete", "status": "ok", "targets": [doc_uri]})
    return 0


def _cmd_archive(args: argparse.Namespace) -> int:
    router, _config = _build_router()
    doc_uri = args.doc_uri
    backend_name = _backend_for_uri(doc_uri)
    try:
        backend = router.backends[backend_name]
    except KeyError:
        _text_out(f"error: backend {backend_name!r} not available")
        return 1
    try:
        backend.archive_document(doc_uri, None, f"archive-{doc_uri}")
    except Exception as exc:  # noqa: BLE001  — adapter boundary
        _text_out(f"error: {exc}")
        return 1
    router.journal.append(
        {
            "schema_version": 1,
            "op_id": f"archive-{doc_uri}",
            "ts": _now_iso(),
            "operation": "archive",
            "targets": [doc_uri],
            "idempotency_key": f"archive-{doc_uri}",
            "snapshot": {},
            "proposal_hash": "",
            "confirmation": "archive",
            "sensitivity": "internal",
            "status": "ok",
        }
    )
    if getattr(args, "json", False):
        _json_out({"operation": "archive", "status": "ok", "targets": [doc_uri]})
    return 0


def _cmd_unarchive(args: argparse.Namespace) -> int:
    router, _config = _build_router()
    doc_uri = args.doc_uri
    backend_name = _backend_for_uri(doc_uri)
    try:
        backend = router.backends[backend_name]
    except KeyError:
        _text_out(f"error: backend {backend_name!r} not available")
        return 1
    try:
        backend.unarchive_document(doc_uri, None, f"unarchive-{doc_uri}")
    except Exception as exc:  # noqa: BLE001  — adapter boundary
        _text_out(f"error: {exc}")
        return 1
    if getattr(args, "json", False):
        _json_out({"operation": "unarchive", "status": "ok", "targets": [doc_uri]})
    return 0


def _entry_backend_name(entry: dict[str, Any] | None) -> str | None:
    """entry 的 backend 名：显式 ``backend`` 优先，否则 ``targets[0]`` 经 parse_uri。

    台账 begin entry 自带 ``backend``；legacy 写 entry 只有 ``targets``——
    解析方式与 ``journal.undo`` 的既有路径一致。
    """
    if not entry:
        return None
    backend = entry.get("backend")
    if isinstance(backend, str) and backend:
        return backend
    targets = [t for t in (entry.get("targets") or []) if isinstance(t, str)]
    if not targets:
        return None
    try:
        backend_name, _ = parse_uri(targets[0])
    except ConfigError:
        return None
    return backend_name


def _ledger_begin_entry(journal: Journal, op_id: str) -> dict[str, Any] | None:
    """台账登记过的 op 的 ``kind == "begin"`` entry（ADR 0005 分流依据）。

    legacy 写 entry（``build_entry`` 形态，无 ``kind``）→ ``None``：它们不走
    计划分支，仍由既有 best-effort undo 处理（B12 基线不变量）。
    """
    for entry in journal.entries:
        if entry.get("op_id") == op_id and entry.get("kind") == "begin":
            return entry
    return None


def _cmd_undo(args: argparse.Namespace) -> int:
    router, _config = _build_router()
    op_id = args.op_id
    # ADR 0005：台账登记过的 op（begin/end）只产补偿计划，执行归 integration
    # skill；其余（legacy 写 entry、未知 op_id）走既有 best-effort undo 不变。
    backend = _entry_backend_name(_ledger_begin_entry(router.journal, op_id))
    if backend is not None:
        from kgent.router.ledger import INTEGRATION_SKILL_BACKENDS, compensation_plan

        if backend in INTEGRATION_SKILL_BACKENDS:
            plan = compensation_plan(op_id, backends=router.backends, journal=router.journal)
            if getattr(args, "json", False):
                _json_out(plan)
            else:
                text = (
                    f"{plan['status']}: {plan['plan']['mechanism']} via "
                    f"{plan['integration_skill']}"
                )
                if plan["status"] == "rejected":
                    text += f"\n  reason: {plan['reason']}"
                _text_out(text)
            return 0 if plan["status"] == "ok" else 1
    result = journal_undo(
        op_id, backends=router.backends, journal=router.journal, audit=router.audit
    )
    if getattr(args, "json", False):
        _json_out(
            {
                "operation": "undo",
                "op_id": result.op_id,
                "status": result.status,
                "error": result.error,
            }
        )
    elif result.error:
        _text_out(f"undo: {result.error}")
    return result.exit_code


# ---------------------------------------------------------------------------
# Ledger commands (journal; ADR 0005)
# ---------------------------------------------------------------------------


def _cmd_journal_begin(args: argparse.Namespace) -> int:
    """B2: register a logical write op in the ledger."""
    from kgent.router.ledger import begin

    revision = int(args.revision_before) if args.revision_before else None
    entry = begin(
        Journal(_home()),  # 台账只依赖 home，不需要已配置的 backends
        operation=args.operation,
        backend=args.backend,
        target_uri=args.doc_uri,
        revision_before=revision,
        content=args.snapshot_content,
    )
    if getattr(args, "json", False):
        _json_out({"operation": "journal-begin", "entry": entry})
    else:
        _text_out(f"begin {entry['op_id']}")
    return 0


def _cmd_journal_end(args: argparse.Namespace) -> int:
    """B2: finalize a ledger op; unknown op id → exit 1 (fail closed)."""
    from kgent.router.ledger import LedgerError, end

    revision = int(args.revision_after) if args.revision_after else None
    try:
        entry = end(Journal(_home()), args.op_id, status=args.status, revision_after=revision)
    except LedgerError as exc:
        if getattr(args, "json", False):
            _json_out({"operation": "journal-end", "status": "failed", "error": str(exc)})
        else:
            _text_out(f"journal end failed: {exc}")
        return 1
    if getattr(args, "json", False):
        _json_out({"operation": "journal-end", "entry": entry})
    else:
        _text_out(f"end {args.op_id} {args.status}")
    return 0


def _cmd_journal(args: argparse.Namespace) -> int:
    """Dispatch ``kgent journal begin|end`` (subparsers set ``args.func``)."""
    func: Callable[[argparse.Namespace], int] | None = getattr(args, "func", None)
    if func is None:
        _text_out("unknown journal command")
        return 1
    return func(args)


def _cmd_sync(args: argparse.Namespace) -> int:
    """Sync/repair partial fan-outs (S29, S30)."""
    router, _config = _build_router()
    repair_op = getattr(args, "repair", None)
    if repair_op:
        from kgent.router.repair import sync_repair

        result = sync_repair(repair_op, journal=router.journal, backends=router.backends)
        if getattr(args, "json", False):
            _json_out(
                {
                    "operation": "sync",
                    "op_id": repair_op,
                    "status": result.journal_entry.get("status"),
                    "repaired_targets": result.journal_entry.get("repaired_targets", []),
                }
            )
        else:
            if result.exit_code == 0:
                _text_out(f"repaired {repair_op}")
            else:
                _text_out(f"repair failed: {result.error}")
        return result.exit_code
    # Status: list failed/partial ops
    from kgent.router.repair import sync_status

    statuses = sync_status(router.journal)
    if getattr(args, "json", False):
        _json_out({"operations": statuses})
    else:
        for s in statuses:
            failed = s.get("failed_targets", [])
            _text_out(f"{s['status']}: {s['op_id']} ({s['operation']}) failed={failed}")
        if not statuses:
            _text_out("no failed or partial operations")
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    home = _home()
    audit_path = home / "audit.ndjson"
    if not audit_path.exists():
        if getattr(args, "json", False):
            _json_out({"entries": []})
        else:
            _text_out("no audit log")
        return 0
    entries: list[dict[str, Any]] = []
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    op_filter = getattr(args, "op", None)
    if op_filter:
        entries = [e for e in entries if e.get("operation") == op_filter]
    if getattr(args, "json", False):
        _json_out({"entries": entries})
    else:
        for e in entries:
            _text_out(json.dumps(e, ensure_ascii=False))
    return 0


def _cmd_auth(args: argparse.Namespace) -> int:
    sub = getattr(args, "auth_action", "status")
    if sub == "status":
        if getattr(args, "json", False):
            _json_out({"auth": "no OS secret store configured; encrypted-file fallback"})
        else:
            _text_out("auth status: no credentials configured")
        return 0
    _text_out(f"auth {sub}: not yet implemented")
    return 0


def _cmd_setup(args: argparse.Namespace) -> int:
    home = _home()
    report, code = detect_setup(home)
    if getattr(args, "json", False):
        _json_out(
            {
                "backends": {
                    n: {"auth": e.get("auth"), "found_via": e.get("found_via")}
                    for n, e in report.backends.items()
                },
                "exit_code": code,
            }
        )
    else:
        if report.backends:
            for name, entry in report.backends.items():
                _text_out(
                    f"  {name}: found via {entry.get('found_via')} (auth: {entry.get('auth')})"
                )
        else:
            _text_out("no backends detected")
    return code


def _cmd_trust(args: argparse.Namespace) -> int:
    home = _home()
    trusted_path = home / "trusted.json"
    dir_path = Path(args.directory)
    if not dir_path.is_dir():
        _text_out(f"error: {args.directory!r} is not a directory")
        return 1
    trust_directory(dir_path, trusted_path)
    if getattr(args, "json", False):
        _json_out({"trusted": str(dir_path.resolve())})
    else:
        _text_out(f"trusted: {dir_path.resolve()}")
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    home = _home()
    findings, code = doctor(home)
    if getattr(args, "json", False):
        _json_out({"findings": findings, "exit_code": code})
    else:
        if findings:
            for f in findings:
                _text_out(f"  - {f}")
        else:
            _text_out("healthy")
    return code


def _cmd_wiki(args: argparse.Namespace) -> int:
    """§6.10/§12: ``kgent wiki`` — the first nested command group."""
    wiki_action = getattr(args, "wiki_action", None)
    if wiki_action == "spaces":
        spaces_action = getattr(args, "spaces_action", None)
        if spaces_action == "list":
            return _cmd_wiki_spaces_list(args)
        if spaces_action == "create":
            return _cmd_wiki_spaces_create(args)
        _text_out(f"unknown wiki spaces action: {spaces_action}")
        return 1
    _text_out(f"unknown wiki action: {wiki_action}")
    return 1


def _cmd_wiki_spaces_list(args: argparse.Namespace) -> int:
    """§6.10/§12 (S82): list knowledge spaces; only backends with one (rule 9)."""
    router, _config = _build_router()
    spaces: list[dict[str, Any]] = []
    for backend_name in _target_backends(args, router):
        if not _backend_supports_wiki(router, backend_name):
            continue  # §12 rule 9: list only backends with a knowledge space
        backend = router.backends[backend_name]
        try:
            for space in backend.list_wiki_spaces():
                item = dict(space)
                item.setdefault("backend", backend_name)
                spaces.append(item)
        except Exception as exc:  # noqa: BLE001 — N10: failures are surfaced, never dropped
            spaces.append({"backend": backend_name, "error": str(exc)})
    if getattr(args, "json", False):
        _json_out({"spaces": spaces})
    else:
        for space in spaces:
            _text_out(
                f"  {space.get('space_id', '?')} — {space.get('name', '?')} "
                f"({space.get('backend', '?')})"
            )
        if not spaces:
            _text_out("no knowledge spaces found")
    return 0


def _cmd_wiki_spaces_create(args: argparse.Namespace) -> int:
    """§6.10/§12 (S82): create a knowledge space; journaled like any write."""
    router, _config = _build_router()
    backends_list = _target_backends(args, router)
    _require_wiki_backends(router, backends_list)
    proposal = WriteProposal(
        operation="wiki_space_create",
        targets=[(b, None) for b in backends_list],
        title=args.name,
        content=args.name or "",
        sensitivity="internal",
    )
    mode = _confirmation_mode(args)
    explicit = bool(getattr(args, "backends", None))
    confirmation = confirm(proposal, mode, explicit_backends=explicit)
    if confirmation == "rejected":
        _text_out("rejected: write not confirmed")
        return 3
    # ``execute`` is the router write gate (confirmed-write API), not SQL
    # pi-lens-ignore: python-sql-injection
    result = router.execute(proposal, confirmation=confirmation)
    if getattr(args, "json", False):
        _json_out(
            {
                "operation": "wiki_space_create",
                "op_id": result.op_id,
                "status": result.status,
                "space_ids": _as_str_list(result.journal_entry.get("targets", [])),
                "backends": backends_list,
            }
        )
    return result.exit_code


def _cmd_config(args: argparse.Namespace) -> int:
    sub = getattr(args, "config_action", "validate")
    home = _home()
    if sub == "validate":
        config_path = home / "config.yaml"
        if not config_path.exists():
            _text_out("no config file")
            return 0
        try:
            raw = _yaml.parse(config_path.read_text(encoding="utf-8"))
            from kgent.config.schema import load_config_dict

            cfg = load_config_dict(raw if isinstance(raw, dict) else {})
            findings = validate_config(cfg)
        except KgentError as exc:
            findings = [str(exc)]
        if getattr(args, "json", False):
            _json_out({"findings": findings, "exit_code": 1 if findings else 0})
        else:
            if findings:
                for f in findings:
                    _text_out(f"  - {f}")
            else:
                _text_out("config valid")
        return 1 if findings else 0
    elif sub == "migrate":
        config_path = home / "config.yaml"
        try:
            migrate_config(config_path)
            _text_out("migration complete (or no migration needed)")
        except KgentError as exc:
            _text_out(f"migration error: {exc}")
            return 1
        return 0
    elif sub == "show-effective":
        try:
            cfg, warnings = _load_config()
        except KgentError as exc:
            _text_out(f"error: {exc}")
            return 1
        data = {
            "version": cfg.version,
            "defaults": cfg.defaults,
            "backends": {
                n: {k: v for k, v in s.items() if v is not None} for n, s in cfg.backends.items()
            },
            "content_type_mapping": cfg.content_type_mapping,
            "sensitivity_floors": cfg.sensitivity_floors,
            "warnings": warnings,
        }
        if getattr(args, "json", False):
            _json_out(data)
        else:
            _text_out(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    elif sub == "set-workspace-domain":
        return _cmd_config_set_workspace_domain(args)
    _text_out(f"unknown config action: {sub}")
    return 1


def _cmd_config_set_workspace_domain(args: argparse.Namespace) -> int:
    """Set ``defaults.workspace_domain`` — surgically, one key only (S75)."""
    from kgent.config.workspace_domain import discover_and_set, set_workspace_domain, validate_domain

    home = _home()
    config_path = home / "config.yaml"
    domain = getattr(args, "domain", None)
    try:
        if domain:
            previous, workspace_domain = set_workspace_domain(
                config_path, validate_domain(domain)
            )
            source = "explicit --domain"
        else:
            previous, workspace_domain = discover_and_set(config_path)
            source = "lark-cli drive +search probe"
    except KgentError as exc:
        if getattr(args, "json", False):
            _json_out({"ok": False, "error": str(exc)})
        else:
            _text_out(f"error: {exc}")
        return 1
    if getattr(args, "json", False):
        _json_out(
            {
                "ok": True,
                "workspace_domain": workspace_domain,
                "previous": previous,
                "source": source,
            }
        )
    else:
        _text_out(f"workspace_domain: {previous!r} -> {workspace_domain!r} ({source})")
    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _backend_supports_wiki(router: Router, backend_name: str) -> bool:
    """True when the backend declares the §6.10 wiki (knowledge space) capability."""
    backend = router.backends.get(backend_name)
    caps = getattr(backend, "capabilities", None)
    wiki = caps.get("wiki") if isinstance(caps, dict) else None
    return bool(isinstance(wiki, dict) and wiki.get("supported"))


def _require_wiki_backends(router: Router, backends_list: list[str]) -> None:
    """Reject ``--wiki-space``/``kgent wiki spaces`` on backends without a
    knowledge-space product, BEFORE any write — exit 3 (S79, §12 rule 9)."""
    for backend_name in backends_list:
        if not _backend_supports_wiki(router, backend_name):
            raise PolicyError(f"--wiki-space is not supported on backend '{backend_name}'")


def _as_str_list(value: Any) -> list[str]:
    """Coerce a journal entry value to a list of strings (type narrowing)."""
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return []


def _target_backends(args: argparse.Namespace, router: Router) -> list[str]:
    """Resolve target backend names from --backends flag or config defaults."""
    selection = getattr(args, "backends", None)
    if selection:
        return [b.strip() for b in selection.split(",") if b.strip()]
    # Fall back to config defaults
    defaults = router.config.defaults
    raw = defaults.get("default_backends") or []
    if not isinstance(raw, (list, tuple)):
        raw = [raw]
    return [str(b) for b in raw]


def _backend_for_uri(doc_uri: str) -> str:
    """Extract backend name from a kgent:// URI."""
    from kgent.uri import parse_uri

    backend, _ = parse_uri(doc_uri)
    return backend


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kgent", description="Federated knowledge management CLI")
    parser.add_argument("--json", action="store_true", default=False, help="JSON output")
    # Shared parent for flags that apply to every subcommand
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=False, help="JSON output")
    sub = parser.add_subparsers(dest="command")

    # create
    p_create = sub.add_parser("create", help="Create a document", parents=[common])
    p_create.add_argument("--title", required=True)
    p_create.add_argument("--content", default="")
    p_create.add_argument("--backends", default=None)
    p_create.add_argument("--content-type", dest="content_type", default=None)
    p_create.add_argument("--sensitivity", default="internal")
    p_create.add_argument(
        "--wiki-space",
        dest="wiki_space",
        default=None,
        help="Create a wiki node inside this knowledge space (§6.10)",
    )
    p_create.add_argument(
        "--parent-node-token",
        dest="parent_node_token",
        default=None,
        help="Place the wiki node under this existing parent (§6.10)",
    )
    p_create.add_argument("--yes", action="store_true", default=False)

    # wiki (knowledge space) — first nested command group (§6.10/§12)
    p_wiki = sub.add_parser("wiki", help="Wiki (knowledge space) management", parents=[common])
    wiki_sub = p_wiki.add_subparsers(dest="wiki_action")
    p_spaces = wiki_sub.add_parser("spaces", help="Knowledge-space primitives", parents=[common])
    spaces_sub = p_spaces.add_subparsers(dest="spaces_action")
    p_spaces_list = spaces_sub.add_parser(
        "list", help="List knowledge spaces accessible to the user", parents=[common]
    )
    p_spaces_list.add_argument("--backends", default=None)
    p_spaces_create = spaces_sub.add_parser(
        "create", help="Create a knowledge space", parents=[common]
    )
    p_spaces_create.add_argument("--name", required=True)
    p_spaces_create.add_argument("--backends", default=None)
    p_spaces_create.add_argument("--yes", action="store_true", default=False)

    # update
    p_update = sub.add_parser("update", help="Update a document", parents=[common])
    p_update.add_argument("doc_uri")
    p_update.add_argument("--content", default="")
    p_update.add_argument("--title", default=None)
    p_update.add_argument("--sensitivity", default="internal")
    p_update.add_argument("--expected-version", dest="expected_version", default=None)
    p_update.add_argument("--yes", action="store_true", default=False)

    # store (update-first)
    p_store = sub.add_parser("store", help="Store (update-first)", parents=[common])
    p_store.add_argument("--title", required=True)
    p_store.add_argument("--content", default="")
    p_store.add_argument("--backends", default=None)
    p_store.add_argument("--sensitivity", default="internal")
    p_store.add_argument("--yes", action="store_true", default=False)
    p_store.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=False,
        help="Show what would happen without writing or journaling",
    )
    p_store.add_argument(
        "--op-id",
        dest="op_id",
        default=None,
        help="Reuse a caller-supplied op_id for the journal entry",
    )

    # search
    p_search = sub.add_parser("search", help="Search documents", parents=[common])
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--backends", default=None)
    p_search.add_argument("--top-k", dest="top_k", type=int, default=10)

    # read
    p_read = sub.add_parser("read", help="Read a document", parents=[common])
    p_read.add_argument("doc_uri")

    # delete
    p_delete = sub.add_parser("delete", help="Delete a document", parents=[common])
    p_delete.add_argument("doc_uri")
    p_delete.add_argument("--yes", action="store_true", default=False)

    # archive
    p_archive = sub.add_parser("archive", help="Archive a document", parents=[common])
    p_archive.add_argument("doc_uri")

    # unarchive
    p_unarchive = sub.add_parser("unarchive", help="Unarchive a document", parents=[common])
    p_unarchive.add_argument("doc_uri")

    # undo
    p_undo = sub.add_parser("undo", help="Undo an operation", parents=[common])
    p_undo.add_argument("op_id")

    # journal（台账，ADR 0005）
    p_journal = sub.add_parser("journal", help="Ledger (op lifecycle)", parents=[common])
    journal_sub = p_journal.add_subparsers(dest="journal_cmd", required=True)
    p_begin = journal_sub.add_parser("begin", help="Register a logical write op", parents=[common])
    p_begin.add_argument("--operation", required=True, choices=["create", "update", "delete"])
    p_begin.add_argument("--backend", required=True)
    p_begin.add_argument("--doc-uri", dest="doc_uri", required=True)
    p_begin.add_argument("--revision-before", dest="revision_before", default=None)
    p_begin.add_argument("--snapshot-content", dest="snapshot_content", default=None)
    p_begin.set_defaults(func=_cmd_journal_begin)
    p_end = journal_sub.add_parser("end", help="Finalize a ledger op", parents=[common])
    p_end.add_argument("--op-id", dest="op_id", required=True)
    p_end.add_argument("--status", required=True, choices=["ok", "failed"])
    p_end.add_argument("--revision-after", dest="revision_after", default=None)
    p_end.set_defaults(func=_cmd_journal_end)

    # sync
    p_sync = sub.add_parser("sync", help="Sync / repair partial operations", parents=[common])
    p_sync.add_argument("--repair", default=None)

    # audit
    p_audit = sub.add_parser("audit", help="Show audit log", parents=[common])
    p_audit.add_argument("--op", default=None)

    # auth
    p_auth = sub.add_parser("auth", help="Authentication management", parents=[common])
    p_auth.add_argument(
        "auth_action", nargs="?", default="status", choices=["status", "login", "logout"]
    )

    # setup
    sub.add_parser("setup", help="Discover backends + generate config", parents=[common])

    # trust
    p_trust = sub.add_parser("trust", help="Trust a project directory", parents=[common])
    p_trust.add_argument("directory")

    # doctor
    sub.add_parser("doctor", help="Validate config + environment", parents=[common])

    # config
    p_config = sub.add_parser("config", help="Config management", parents=[common])
    p_config.add_argument(
        "config_action",
        nargs="?",
        default="validate",
        choices=["validate", "migrate", "show-effective", "set-workspace-domain"],
    )
    p_config.add_argument(
        "--domain",
        default=None,
        help="Explicit workspace domain (omit to auto-discover via lark-cli probe)",
    )

    # status (alias for auth status)
    sub.add_parser("status", help="Show status (alias for auth status)", parents=[common])

    # login/logout (aliases)
    sub.add_parser("login", help="Login (stub)", parents=[common])
    sub.add_parser("logout", help="Logout (stub)", parents=[common])

    return parser


_DISPATCH: dict[str, Callable[[argparse.Namespace], int]] = {
    "create": _cmd_create,
    "wiki": _cmd_wiki,
    "update": _cmd_update,
    "store": _cmd_store,
    "search": _cmd_search,
    "read": _cmd_read,
    "delete": _cmd_delete,
    "archive": _cmd_archive,
    "unarchive": _cmd_unarchive,
    "undo": _cmd_undo,
    "journal": _cmd_journal,
    "sync": _cmd_sync,
    "audit": _cmd_audit,
    "auth": _cmd_auth,
    "setup": _cmd_setup,
    "trust": _cmd_trust,
    "doctor": _cmd_doctor,
    "config": _cmd_config,
}


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns an exit code (0/1/2/3/4)."""
    # Output is UTF-8 by contract (JSON consumers decode utf-8; skills print
    # non-ASCII content). A Windows console with a legacy codepage (cp1252,
    # GBK, ...) would otherwise crash on the first non-ASCII character.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        with contextlib.suppress(ValueError, OSError):  # detached/closed stream
            reconfigure(encoding="utf-8")
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse exits 0 for --help/-h and 2 for usage errors; help must
        # stay 0 (tools/install-skills.sh's pipefail'd health check greps
        # `kgent --help`), everything else maps to the CLI's failure code 1.
        return 0 if exc.code in (None, 0) else 1
    command = args.command

    if command is None:
        parser.print_help()
        return 1

    # Aliases
    if command == "status":
        args.auth_action = "status"
        return _cmd_auth(args)
    if command == "login":
        _text_out("login: not yet implemented (use encrypted-file fallback)")
        return 0
    if command == "logout":
        _text_out("logout: not yet implemented")
        return 0

    handler = _DISPATCH.get(command)
    if handler is None:
        _text_out(f"unknown command: {command}")
        return 1

    try:
        return handler(args)
    # VersionConflict is a KgentError subclass — specific-first, general-second is
    # the correct ordering; pi-lens's positional "earlier except catches all"
    # heuristic can't see the subtype relationship and misfires here.
    # pi-lens-ignore: unreachable-except
    except VersionConflict as exc:
        if getattr(args, "json", False):
            _json_out({"error": str(exc), "exit_code": exc.exit_code})
        else:
            _text_out(f"error: {exc}")
        return exc.exit_code
    except KgentError as exc:
        if getattr(args, "json", False):
            _json_out({"error": str(exc), "exit_code": exc.exit_code})
        else:
            _text_out(f"error: {exc}")
        return exc.exit_code
    except SystemExit:
        # argparse calls sys.exit on usage errors; map to exit 1 (failure)
        return 1
