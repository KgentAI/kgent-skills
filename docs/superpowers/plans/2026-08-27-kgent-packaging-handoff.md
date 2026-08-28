# kgent Packaging Implementation — Hand-off Notes

**Dated:** 2026-08-28 (mid-implementation).
**Plan:** `docs/superpowers/plans/2026-08-27-kgent-packaging-implementation.md`
**Companion to the SDD ledger** (`.superpowers/sdd/...` — git-ignored and was
wiped once; THIS file is tracked so it survives). Git history is authoritative
for what is done; the plan checkboxes show task status.

This document is the controller→implementer context that task briefs cannot
know: what exists, decisions already made, rulings, and deferred items.

---

## Status

**22 / 34 tasks complete, review-clean.** Phases 0–4 (scaffold, foundations,
config, capabilities, routing) and **Phase 5 (policy enforcement — the
FM1–FM12 enforcement core) are DONE** and committed on branch
`impl/kgent-packaging`.

Remaining:

- **Phase 6** (search): 6.1 fanout/timeouts (S33), 6.2 clamp+preflight (S31/S32/S48), 6.3 RRF (S34), 6.4 dedupe/staleness (S35–S38/S55/S56), 6.5 decompose (S57)
- **Phase 7** (adapters): 7.1 argv-safety+rate budget (S40/S41/S47/N13), 7.2 lark/dingtalk/wecom, 7.3 fidelity (S49)
- **Phase 8** (CLI): 8.1 CLI+exit codes, 8.2 store workflow, 8.3 delete/archive/undo/sync (S8–S12/S29/S30/S50), 8.4 auth+secrets (S46)
- **Phase 9** (skills): 9.1 knowledge-storage (S60–S64), 9.2 skill↔router contract (S65–S67), 9.3 QA+wiki-setup (S68/S69), 9.4 CLI e2e, 9.5 skill e2e
- **Phase 10**: 10.1 negatives N1–N19, 10.2 properties P1–P7, 10.3 adversarial §5, 10.4 gauntlet+EVIDENCE.md

---

## Environment facts (NOT in the plan)

- `python` = 3.11.9 (some shells resolve 3.12.10 — fine, pyproject requires ≥3.11). `python -m pytest` works.
- All dev deps installed: pytest 8.4.2, mypy, ruff, hypothesis, pytest-randomly, coverage, diff-cover, mutmut.
- **Model quotas:** opencode-go `deepseek-v4-pro` hit a 5-hour usage 429 (resets ~hourly); `deepseek-v4-flash` works. The `anthropic` provider has NO valid auth token (401). → Use `--model deepseek-v4-flash` for implementers/reviewers.
- **Subagents:** pi has no native subagents — dispatch via `pi -p "<prompt>" --model deepseek-v4-flash --session-dir <workspace>/sessions --session-id <id>`. For fix rounds, resume the SAME `--session-id`. Verify a run completed by its stdout status line; implementers write full reports to the workspace (may be wiped) — treat commit SHAs + the reply status as authoritative.
- The SDD workspace (`.superpowers/sdd/2026-08-27-kgent-packaging-implementation/`) is **git-ignored and was wiped once mid-session**. Never rely on it for durable state — re-derive from `git log`; keep briefs/reports regenerable via `scripts/task-brief` + the tracked plan.
- Shim scripts live in `.superpowers/sdd/2026-08-27-kgent-packaging-implementation/checkoff.sh` (flips a task's `- [ ]` steps to `- [x]` in the plan; restore from git if wiped).

---

## Live code you will build on (all mypy-strict clean, 95 tests green)

- `src/kgent/types.py` — §3.8/§1.5 frozen dataclasses: `DocumentMetadata` (version lives HERE, authoritative), `Document` (doc_uri/title/content/metadata — NO version field), `SearchResult` (rank defaults 0, access="ok"), `ApproverDecision`, `ApprovalStatus` (binding: `ApprovalBinding` frozen dataclass {doc_uri, operation, content_fingerprint}), `FilterSpec`, `BackendResolution`, `RoutingIntent` (operation/doc_uri/query/targets/proposal/policy_gates/provenance), `PolicyGate` (name, details), `WriteProposal` (minimal; Task 5.2 refines).
- `src/kgent/errors.py` — `KgentError.exit_code`; `ConfigError`=1, `VersionConflict`=4 (init `(doc_uri, expected, found)` + defaults), `PolicyError`=3, `ApprovalRequired`=3, `ApprovalBindingMismatch`=3, `PartialFailure`=2.
- `src/kgent/uri.py` — `parse_uri(s)->(backend, native_id)` (rejects bare ids/queries/fragments/extra segments; raises ConfigError), `format_uri` (no validation — roundtrip enforced at parse).
- `src/kgent/fingerprint.py` — `normalize` (per-field whitespace collapse to avoid \x1f boundary collision), `content_fingerprint` (sha256 hex), `fingerprints_equal`.
- `src/kgent/config/` — `schema.py` (`Config` dataclass + `load_config_dict`, `dict[str, object]` defaults; exact-key ConfigErrors), `loader.py` (`load_effective_config(global_path, project_dir, cli_overrides)->(Config, warnings)`; precedence CLI>trusted project>global; `FORBIDDEN_PROJECT_KEYS`), `trusted.py` (`trust_directory`/`is_trusted`, dir-hash→trusted.json), `validate.py` (`validate_config`, `doctor(home)->(findings, exit_code)` — **flags forbidden patterns in GLOBAL config, ruling below**), `migrate.py`, `_yaml.py` (restricted YAML-subset parser; anchors/tags → ConfigError; empty flow `{}` OK).
- `src/kgent/capabilities/` — `interface.py` (Protocols `DocumentStorage`/`DocumentSearch`/`ApprovalFlow`, `BUILTIN_FALLBACK`, `resolve_mode`), `declaration.py` (`CapabilityDeclaration.supports`), `cache.py` (`effective_capabilities` intersection — config only narrows; `read_cache`/`write_cache` on `~/.kgent/capabilities.cache.yaml` 0600/0700), `detect.py` (`discover(home, env)->DiscoveryReport{backends: dict[str,dict] keys: auth/capabilities/found_via/adapter_name}`, `setup(home)->(report, int)`, structured-manifests-only = N12).
- `src/kgent/router/` — `resolve.py` (`resolve_backends` + `resolve_intent` + shared `capabilities_needed`; N17 guard), `sensitivity.py` (`TIER_ORDER`, `analyze_sensitivity`, `enforce_floor`, `enforce_zone(..., fallback_chain=False)`, `warn_query_leakage` once-per-session), **`policy.py`** (`confirm(proposal, mode, *, answer, explicit_backends) → "interactive-yes"|"--yes"|"rejected"`; `execute_confirmed(prop, confirmation, *, backends, journal, audit) -> OpResult(op_id, exit_code=0/2/3/4, journal_entry, status="ok"|"partial"|"blocked"|"conflict", error)` — zone preflight before ANY write, N1 executed==journaled targets, op_id=`op-<yyyymmdd>-<seq>` module counter, approval gate, snapshot capture, audit writes), **`concurrency.py`** (`check_version` token/updated_at paths, `no_token_warning`), **`journal.py`** (`Journal.append/.get/.list_failed/.list_partial`, `build_entry` schema-allowlist + S51 nested-snapshot confidentiality guard, `undo(op_id)`, `prune_older_than`; NDJSON `~/.kgent/journal/journal.ndjson` 0700/0600), **`audit.py`** (`AuditLog.append` allowlist + S45 query redaction, `redact_query`, `AUDIT_REDACT_QUERY_WARNING`), **`approval.py`** (`bind_approval` HMAC, `request_approval`/`check_approval`/`decide`/`execute_approved` with TTL + binding mismatch, `self_approval_allowed(owner, requester, policy)`, `fanout_approvals`; `SECRET_KEY`/`DEFAULT_TTL_HOURS` placeholders → Task 8.4).
- `tests/` — `conftest.py` (`tmp_home` via KGENT_HOME, `test_world` = lark internal+full via **FakeBackend** with `write_calls`+`fault()` hook, dingtalk/wecom external keyword-only; config dicts), `tests/fakes/fake_backend.py` (`FakeBackend` implements capability interface; uses `dataclasses.replace` on metadata for version bumps).
- **Router facade** `src/kgent/router/core.py` with `Router(config, backends, journal, audit, session)` is authored in plan Task 9.4 — NOT yet created; Tasks 5.2–5.6 currently stand alone until then.

---

## Decisions & rulings (binding for later tasks)

8. **Approval gate is router-enforced:** `execute_confirmed` verifies each gated target's token via `execute_approved` before any adapter call; blocked legs journal `status "blocked"` (exit 3), mixed success `"partial"` (exit 2). `OpResult.status` ∈ {ok, partial, blocked, conflict}. Partial ops journal two entries under one op_id — `journal.get` returns the blocked one; Task 8.3 (sync/undo) must handle this (empty-snapshot risk).
9. **Write proposal lives in types.py** (frozen) with `content`, `expected_version`, `expected_updated_at` fields; `execute_confirmed` currently wires create+update (delete/archive/unarchive = warned no-ops until Task 8.3).
10. **S52 guarantee implemented as schema-allowlist** in journal/audit `build_entry` (unknown kwargs silently dropped) — do NOT add free-form pass-through fields later.

1. **Doctor global-vs-project forbidden keys (Task 9.4 + final review):** `doctor(home)` applies `FORBIDDEN_PROJECT_KEYS` patterns to whatever config it reads — forced by the committed S54 test (writes the forbidden key INTO global config.yaml and expects a finding). Consequence: a REAL global config with `backends.<name>.type/skill_name/trust_zone` is flagged unhealthy. **Ruling:** Task 9.4's e2e doctor test asserts `main(["doctor"]) == 0` against a MINIMAL clean config (`version: 1\nbackends: {}`), and asserts exit 1 + `backends.lark.skill_name` finding against a config WITH the pattern. Never assert doctor==0 on the standard-world config (it contains skill_name/trust_zone). A future refinement may add project_dir context, but the committed S54 test semantics must be preserved.
2. **Capability checks use declared caps only** (runtime-detected intersection is the owner of live wiring in 7.x). All `resolve_*` logic is deterministic, no LLM.
3. **`capabilities_needed` granularity:** shared single calculator; update→`["document_storage"]` etc. Spec's literal `"document_storage.update"` example is NOT used (line-level; changing it = one map edit if finer gating is wanted).
4. **Adapter-name resolution:** `resolve_intent` picks `(skill, skill_name)` if declared caps satisfy; else `(cli, cli_name)`; else `(mcp, mcp_url)`; unknown → ConfigError (N17). Actual adapter OBJECTS are Task 7.x (adapters/) — 5.2–5.6 must call into a pluggable backends dict / registry rather than hardcoding.
5. **Policy gates in intent are descriptors** (`PolicyGate(name="journal"|"audit"|"sensitivity"|"approval")`); Task 5.6 turns approval into real gate objects.
6. **Interim stubs are gone** — 1.1/1.2/2.1 each owned and replaced theirs. Don't add new stubs; implement for real.
7. **`--yes` semantics (S3/S4):** requires explicit `--backends` + fully-specified content; journal/audit record `confirmation: "--yes"`. Bypasses kgent's interactive confirm only — never platform approvals.
8. **Confirmation string values** used by S1–S4: `"interactive-yes"`, `"--yes"`, `"rejected"` (for no/timeout/EOF). Version conflicts journal with `status: "conflict"`.

## Deferred minors (final review triage)

- `*.egg-info/` not in .gitignore (editable install residue; delete `src/kgent.egg-info/` when seen).
- `tools/mutants.py` has unused `import subprocess` (brief-verbatim; ruff F401 would flag if tools/ linted).
- SearchResult.rank default 0 vs §3.8 "1-based int" (brief test forced).
- `test_uri.py` lacks a query/fragment rejection case (code rejects them; test absent).
- `enforce_zone.fallback_chain` kwarg (deliberate N4 extension) untested.
- `capabilities_needed("read")==[]` in degenerate all_enabled corner.
- S53 test leaks real HOME (PATH-only monkeypatch).
- content_type_mapping unknown-backend enforcement deferred (Task 4.x/doctor/5.x closure).
- `_walk_paths` in loader/validate duplicated; doesn't descend into list items.

## Getting started for a continuation session

1. `git fetch && git checkout impl/kgent-packaging && git log --oneline -5`.
2. Read this file + the plan's Phase/Global Constraints.
3. Continue at the first unchecked task (plan checkboxes): Task 5.2.
4. Per task: `scripts/task-brief <PLAN> <N>` → dispatch implementer on `deepseek-v4-flash` → verify via git + `pytest tests/ -q` + `mypy src` + `ruff check src tests` → `scripts/review-package <PLAN> <BASE> <HEAD>` → dispatch reviewer → fix loop if needed → append ledger → `checkoff.sh <N>` → commit plan.
5. Enforce: `confirmation` journal invariants, exact spec message strings, exit codes 0/2/1/3/4, `~/.kgent` 0700/0600, no telemetry off-machine, argv-array-only subprocess.