# kgent Service Packaging Design Spec

**Date**: 2026-08-26
**Last Revised**: 2026-08-26 (v1.1 — security/UX/consistency review applied)
**Status**: Draft
**Version**: 1.4.1

## Changes in v1.4.1

- Added cross-references to the companion executable acceptance specification ([2026-08-26-kgent-packaging-acceptance.md](2026-08-26-kgent-packaging-acceptance.md)), authored per the old-coder methodology: Tier-3 calibration, failure model, 50 executable scenarios (S1–S50), 14 negative constraints (N1–N14), 7 property invariants (P1–P7), adversarial pass, and authorized setup plan. No design semantics changed.

## Changes in v1.4

Post-review sweep — residual gaps found in v1.3, now closed:

- **`older_than` age basis**: measured on `updated_at` (last activity), not `created_at` (§4.3, §12).
- **Undo safety for archives**: undo verifies the archived copy is unchanged before deleting it; post-archive edits are never silently lost (§6.8).
- **Whole-`~/.kgent` protection**: 0700 dir / 0600 files for all local state, not just journal/audit (§6.7).
- **Approver policy**: resolved platform identities; self-approval allowed by default only for documents the requester owns (§3.4).
- **Metrics privacy**: observability is local-only (§9).
- **Exit code 4** for version conflicts (§12).

## Changes in v1.3

Second design-review pass (fixes 1–17):

- **Schemas defined**: `DocumentMetadata`, `Document`, `SearchResult`, `ApprovalStatus` (§3.8), informed by agent-service's `KnowledgeReference` / suggested-operation models.
- **`top_k` is a total** across backends: per-backend fetch, truncate after ranking (§3.7, §7.3).
- **`all` selector** is now an alias of `all_enabled` (§4.2).
- **Fingerprint-identical copies** collapse into one update option (§6.2).
- **Optimistic concurrency**: `expected_version` on update/delete; conflicts abort and re-propose, never clobber (§3.9).
- **Content representation & fidelity**: canonical markdown + native blob; lossy-conversion warnings (§6.9).
- **Rate limits**: `Retry-After` honored; queueing is separate from error retries (§8.1).
- **Content size limits**: `limits.max_content_bytes`, preflied before proposals (§3.7).
- **Approval lifecycle**: TTL/expiry, per-target approvals for fan-out writes, `--yes` never bypasses platform gates (§3.4, §12).
- **Query-language escaping** required in adapters (§8.5).
- **Local file protection**: 0600 perms, schema-versioned journal/audit, opt-in journal encryption (§6.7, §8.4).
- **Sensitivity fails safe**: uncertainty raises the tier; per-content_type floors (§2.5).
- **Batch ops & cancellation** semantics (§12 rule 8).
- **Read-path staleness**: targets verified before proposals; denied/stale results flagged (§8.6).
- **Secrets fallback**: encrypted-file fallback with warning when no OS keychain exists (§2.4).

## Changes in v1.2

- **Replica concept removed**: documents are written to exactly one backend per operation (plus explicit multi-backend fan-out when the user or config requests it). No automatic copies, no `replicas` config, no `replication:` policy block, no `--cascade`/`--propagate`. Cross-backend duplicates are handled purely by detection + confirmed merge (§6.2, §6.5).
- **Archive-first delete (§6.8)**: delete proposals recommend moving the document to an archive backend whenever one is available; an archive is a journaled, undoable *move* whose source deletion only executes after the archive write succeeds.

## Changes in v1.1

This revision applies the security, UX, and consistency review. Major changes:

- **Security**: config trust model (§2.3), secrets management (§2.4), sensitivity tiers and query-data leakage policy (§2.5), prompt-injection defenses (§5.5), router-enforced approval flow (§3.4), read-only auto-discovery (§2.2), audit log (§8.4), transport/CLI hardening (§8.5).
- **UX**: zero-wrong-writes success metric (§11), mandatory proposal display for all writes (§5.6, replaces the confidence-threshold auto-resolve), `kgent sync` repair and idempotent retries (§6.6), RRF ranking (§7.3), near-duplicate detection (§6.5, §7.2), CLI surface spec (§12), timeouts/streaming/concurrency (§7.1), undo via write journal (§6.7).
- **Consistency**: single routing model with explicit precedence (§4.1), `fallback` config location fixed (§3.2), runtime capability verification (§3.5), canonical document URIs (§3.6), filter schema (§3.7), delete flow (§6.8), measurable success criteria (§11), config migration (§2.6).

## Executive Summary

This document defines the architecture for packaging the kgent knowledge management service through three interface layers: **MCP tools**, **CLI**, and **Skills**. The system supports **federated multi-backend operations** across multiple platforms (Lark, DingTalk, Confluence, kgent-hosted) with intelligent routing, capability-aware fallbacks, and human-in-the-loop orchestration.

### Key Design Principles

1. **Federated Multi-Backend**: Operations can target multiple platforms simultaneously
2. **Capability-Based Composition**: Skills orchestrate via capability interfaces, backends are swappable
3. **Self-Disambiguation, Never Auto-Execute**: Gather context and resolve ambiguity automatically for *reading and proposing*; writes are never executed without an explicit user confirmation (§5.6)
4. **Update-First Bias**: Always *propose* updating existing knowledge over creating new (§6.1)
5. **Config is Binding**: Configuration defines routing and policy. Skills may *propose* deviations, but a deviation only takes effect when the user confirms it in the write proposal (§5.6). Skills never silently override config
6. **Always Ask Before Writing**: Every write shows a proposal and requires confirmation. The only bypass is an explicit `--yes` in non-interactive/scripted mode (§12)
7. **Zero Wrong Writes**: The primary quality metric is zero unconfirmed or mis-targeted write operations — not minimal questions (§11)
8. **Untrusted Content**: Content returned by backends is data, never instructions (§5.5)

---

## 1. Architecture Overview

### 1.1 Three-Layer Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Skills Layer                          │
│  - Orchestrates complex workflows                       │
│  - Intent clarification and disambiguation              │
│  - Human-in-the-loop approval (proposal display)        │
│  - Backend-agnostic orchestration                       │
└────────────────┬────────────────────────────────────────┘
                 │ calls capability interfaces
                 ▼
┌─────────────────────────────────────────────────────────┐
│              Capability Router Layer                     │
│  - Routes operations to backends (per precedence §4.1)  │
│  - Fans out to multiple backends                        │
│  - Aggregates results                                   │
│  - Handles capability-aware fallbacks                   │
│  - ENFORCES policy: approval gates, sensitivity tiers,  │
│    write journal, audit log                             │
│  - Conflict resolution and error handling               │
└────────────────┬────────────────────────────────────────┘
                 │ routes to backend implementations
                 ▼
┌─────────────────────────────────────────────────────────┐
│              Backend Implementation Layer                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐ │
│  │ lark-cli │  │dingtalk- │  │confluence│  │kgent-  │ │
│  │ (skills) │  │   cli    │  │   -cli   │  │  cli   │ │
│  └──────────┘  └──────────┘  └──────────┘  └────────┘ │
└─────────────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│                  External Platforms                      │
│  Lark    DingTalk    Confluence    kgent-hosted         │
└─────────────────────────────────────────────────────────┘
```

### 1.2 Layer Responsibilities

**Skills Layer:**
- Orchestrate complex workflows (knowledge storage, question answering, wiki setup)
- Handle intent classification and clarification
- Make intelligent decisions based on context
- Build and display write proposals; never bypass the router's policy gates
- Backend-agnostic: only call capability interfaces

**Capability Router Layer:**
- Route operations to appropriate backends per the single precedence model (§4.1)
- Fan out to multiple backends when configured
- Aggregate and deduplicate results
- Handle capability mismatches (e.g., backend doesn't support semantic search)
- Implement fallback strategies
- **Enforce policy (not merely advise)**: approval gates (§3.4), sensitivity tiers (§2.5), write journal (§6.7), audit log (§8.4), timeouts and concurrency limits (§7.1)

**Backend Implementation Layer:**
- Provide concrete implementations of capabilities
- Each backend declares what it supports; declarations are re-verified at runtime (§3.5)
- Handle platform-specific APIs and authentication (credentials from the OS secret store, §2.4)
- Expose via MCP tools, CLI commands, or skill invocations

**Adapter type semantics.** `type: skill | cli | mcp` adapters are *not* interchangeable beyond the capability interface. Adapters must normalize:

| Property | skill | cli | mcp |
|---|---|---|---|
| Invocation | agent-mediated tool call | subprocess, argv array (never shell string interpolation) | JSON-RPC over TLS |
| Latency budget | high | medium | medium |
| Error propagation | structured error object | exit code + parsed stderr | JSON-RPC error |
| Auth source | skill's own session | CLI's own config/keychain | API key from OS secret store (§2.4) |

---

## 2. Configuration System

### 2.1 Configuration File Structure

Locations (see §2.3 for precedence and trust):

- **Global**: `~/.kgent/config.yaml`
- **Project-local**: `.kgent-config.yaml` (restricted fields; requires explicit trust, §2.3)

```yaml
version: 1

# Global routing settings
defaults:
  routing_mode: configured  # explicit | configured | smart
  default_backends: [lark, kgent]
  approval_ttl_hours: 24    # platform approval expiry (§3.4)
  timeouts:
    search_seconds: 10      # per-backend search timeout (§7.1)
    write_seconds: 30       # per-backend write timeout
  concurrency:
    max_parallel_backends: 4

# Backend configurations
backends:
  lark:
    enabled: true
    type: skill  # skill | cli | mcp (see §1.2 adapter semantics)
    skill_name: lark-doc

    # Trust zone for data-leakage policy (§2.5)
    trust_zone: internal   # internal | external

    # Detailed capability declaration (OVERRIDES ONLY; ground truth is
    # runtime-detected, §3.5)
    capabilities:
      document_storage:
        supported: true
        features:
          - create
          - read
          - update
          - delete
          - list

      vector_search:
        supported: true
        features:
          search_by_keywords: true
          search_by_semantics: true
          search_hybrid: true
        limits:
          max_results: 100
          max_query_length: 500
          max_content_bytes: 2_000_000   # preflied before proposals (§3.7)
        # Similarity thresholds are NOT comparable across backends;
        # each backend declares its own calibrated default (§3.1)
        defaults:
          similarity_threshold: 0.7

      approval_flow:
        supported: true
        features:
          - request_approval
          - check_status
          - execute_approved

    # NOTE: no auth status here. Auth state is runtime-only (§2.4).

    content_types:
      - internal_docs
      - team_wiki
      - meeting_notes
    priority: 1   # tiebreaker in ranking only (§7.3), never relevance input

  dingtalk:
    enabled: true
    type: cli
    cli_name: dingtalk-cli
    trust_zone: external

    capabilities:
      document_storage:
        supported: true
        features:
          - create
          - read
          - update
          - delete

      vector_search:
        supported: true
        features:
          search_by_keywords: true
          search_by_semantics: false
          search_hybrid: false
        # fallback is a SIBLING of `features`, never nested inside it (§3.2)
        fallback:
          search_by_semantics: search_by_keywords
        limits:
          max_results: 50
        defaults:
          similarity_threshold: 0.6   # backend-specific calibration

      approval_flow:
        supported: false

    content_types:
      - external_docs
    priority: 2

  kgent:
    enabled: true
    type: mcp
    mcp_url: https://kgent.example.com/mcp
    # TLS verification is mandatory; server identity pinned on first
    # successful verification (§8.5). No plaintext http:// allowed.
    trust_zone: internal

    capabilities:
      document_storage:
        supported: true
        features:
          - create
          - read
          - update
          - delete
          - list

      vector_search:
        supported: true
        features:
          search_by_keywords: true
          search_by_semantics: true
          search_hybrid: true
        limits:
          max_results: 200
        defaults:
          similarity_threshold: 0.7

      approval_flow:
        supported: true
        features:
          - request_approval
          - check_status
          - execute_approved

    content_types:
      - archived_docs
    priority: 3

# Smart routing rules (when routing_mode: smart).
# Precedence with content_type_mapping and default_backends: §4.1.
routing_rules:
  - match:
      content_type: meeting_notes
      tags: [internal]
    backends: [lark]

  - match:
      content_type: external_docs
    backends: [dingtalk, kgent]

  # `older_than` applies ONLY to archive/migration operations
  # (`kgent archive`), never at store time (§4.3)
  - match:
      operation: archive
      older_than: 90d
    backends: [kgent]

  - default: [lark]

# Content type mapping (used in configured mode; §4.1 precedence).
# Each content type resolves to exactly ONE write target (no replicas — v1.2).
content_type_mapping:
  meeting_notes: lark
  api_docs: confluence
  team_wiki: lark
  research_papers: kgent
  default: lark

# Write journal (§6.7)
journal:
  retention_days: 30
  encrypt: false            # opt-in encryption at rest (§6.7)

# Audit log (§8.4)
audit:
  enabled: true
  path: ~/.kgent/audit.ndjson
```

### 2.2 Auto-Discovery Setup

The `kgent-setup` skill automatically detects available backends and their capabilities.

**Hard rule: discovery is strictly read-only.** No sample writes, no document mutations, no approval requests. Permitted probes: `--version`, capability introspection endpoints, read-only `list(limit=1)` / health checks. Capability detection parses *structured* metadata (skill manifests, MCP tool listings) only — never free-form `--help` prose, to avoid treating untrusted text as configuration input.

**Detection Process:**

1. **Discover available skills**
   - Scan `~/.claude/skills/` for `lark-*`, `dingtalk-*`, etc.
   - Read skill *manifest metadata* (not arbitrary doc prose) to extract capabilities
   - Probe with read-only operations only

2. **Discover available CLIs**
   - Check PATH for `kgent-cli`, `dingtalk-cli`, `confluence-cli`
   - Run `--version` to verify installation
   - Query a structured `capabilities`/`--describe` output if available; otherwise mark capabilities as *unverified* rather than parsing help text
   - Probe with read-only operations only

3. **Discover MCP servers**
   - Check Claude Desktop config for MCP server entries
   - Query MCP server for available tools (read-only `tools/list`)
   - Verify TLS and server identity (§8.5) before trusting any result

4. **Generate initial config**
   - Create `config.yaml` with detected backends
   - Mark all as `enabled: false` by default
   - User reviews and enables desired backends
   - Detected capabilities are stored in a separate **cache file** (`~/.kgent/capabilities.cache.yaml`), not in the user config; the config holds only user overrides (§3.5)

5. **Validate authentication**
   - For each enabled backend, test auth at runtime
   - Prompt user to authenticate if needed
   - Store credentials in the OS secret store (§2.4) — never in config files

**Setup Output Example:**

```
$ kgent-setup

🔍 Detecting available backends (read-only probes)...

✅ Found Lark skill (lark-doc)
   Capabilities (verified):
   - document_storage: ✅ (create, read, update, delete, list)
   - vector_search: ✅ (keyword ✅, semantic ✅, hybrid ✅)
   - approval_flow: ✅ (request, check, execute)
   Auth: ✅ authenticated (alice@company.com) [keychain]

✅ Found DingTalk CLI (dingtalk-cli v1.2.3)
   Capabilities (verified):
   - document_storage: ✅ (create, read, update, delete)
   - vector_search: ⚠️ (keyword ✅, semantic ❌, hybrid ❌)
     → Semantic search will fallback to keyword search
   - approval_flow: ❌ not available
   Auth: ✅ authenticated [keychain]

❌ Confluence CLI not found
   → Install from: https://confluence.com/cli

✅ Found kgent MCP server (https://kgent.example.com/mcp)
   TLS: ✅ verified, identity pinned
   Capabilities (verified):
   - document_storage: ✅ (create, read, update, delete, list)
   - vector_search: ✅ (keyword ✅, semantic ✅, hybrid ✅)
   - approval_flow: ✅ (request, check, execute)
   Auth: ✅ authenticated [OS secret store]

📝 Generated config: ~/.kgent/config.yaml
   - 3 backends detected, 2 authenticated
   - Capabilities cached to ~/.kgent/capabilities.cache.yaml
   - Please review and enable desired backends

🎯 Configure content routing?
   - [1] Use smart routing (recommended)
   - [2] Manual configuration
   - [3] Skip for now
```

### 2.3 Config Precedence and Trust Model

**Precedence (highest wins):**

1. Explicit CLI flags / tool arguments (`--backends`, `--routing`, …)
2. Project-local `.kgent-config.yaml` — **trusted fields only** (see below), and only after the directory has been explicitly trusted
3. Global `~/.kgent/config.yaml`

**Project-local config trust.** A project-local config can be used for repo-specific routing preferences, but it is untrusted input until the user runs `kgent trust` in that directory (recorded by directory hash in `~/.kgent/trusted.json`). Until trusted, it is ignored with a warning.

**Forbidden keys in project-local config.** Project-local config may ONLY contain: `defaults.routing_mode`, `defaults.default_backends`, `routing_rules`, `content_type_mapping` (restricted to already-enabled, already-configured backends). It may NEVER contain or modify:

- `backends.*.auth` or anything credential-related
- `backends.*.skill_name`, `backends.*.cli_name`, `backends.*.mcp_url`, `backends.*.type` (target-selection fields — overriding these would let a repo redirect writes or invoke arbitrary skills/servers)
- `backends.*.enabled` for backends not in the global config
- `trust_zone` downgrades (a project may raise sensitivity requirements, never lower them)

Any forbidden key in a project-local config is rejected with an error naming the offending key.

### 2.4 Secrets and Credential Management

- Credentials (OAuth tokens, MCP API keys) are stored in the **OS secret store** (macOS Keychain / Windows Credential Manager / libsecret on Linux). Config files contain **no secrets and no auth status fields**.
- Auth state is runtime-only: `kgent auth status` queries each backend live. Stale-state failure modes surface as actionable errors (`confluence-cli auth` hint), never as silent success.
- Tokens are requested with the **minimum scopes** needed for declared capabilities (e.g., read scopes for search-only backends).
- The router re-checks auth lazily before writes; an expired token aborts that backend's write and is reported per-backend (§8.2) — it never silently falls back to a different backend for a write without user confirmation (§8.3).
- **Fallback when no OS secret store exists** (e.g., headless Linux): credentials go to an encrypted file (`~/.kgent/credentials.enc`, 0600, machine-local key). kgent warns prominently at startup and on every `auth` use that the fallback is active. Plaintext storage is never an option — if encryption is also unavailable, auth setup fails closed with instructions.

### 2.5 Sensitivity Tiers and Data-Leakage Policy

Content and backends both carry trust labels; the router enforces the combination:

**Backend trust zones** (`trust_zone`): `internal` (company-controlled) or `external` (third-party hosted, different organization boundary).

**Content sensitivity** (assigned at write time; default `internal`): `public | internal | confidential`.

**Routing rules enforced by the router:**

1. `confidential` content may only be written to `trust_zone: internal` backends. A rule or flag attempting otherwise is rejected and reported, not silently rerouted.
2. **Query leakage**: search queries may themselves contain sensitive content. In multi-backend fan-out, the router warns (once per session) when a query is sent to `external` backends; `kgent search --backends` and config `trust_zone` can restrict fan-out. Query text is never persisted by kgent itself beyond the audit log (§8.4), and audit entries redact query bodies by default (`audit.redact_queries: true`).
3. Sensitivity assignment is best-effort classification (§6.3) and is shown in the write proposal so the user can correct it before confirming.
4. **Fail-safe classification**: `analyze_sensitivity()` uncertainty resolves to the *higher* tier, never the lower one. Config may set per-content_type floors, enforced as minimums:

```yaml
sensitivity_floors:
  meeting_notes: confidential
  research_papers: internal
```

### 2.6 Config Versioning and Migration

- `version` is required and validated. Unknown future versions are rejected with a pointer to `kgent config migrate`.
- `kgent config migrate` upgrades older versions in place, writing a timestamped backup (`config.yaml.bak-<ts>`) first.
- Schema validation errors name the exact key and expected type.

---

## 3. Capability System

### 3.1 Core Capabilities

All identifiers exchanged with the router are **canonical document URIs** (§3.6), e.g. `kgent://lark/docxABC123`. Backend-native IDs never cross adapter boundaries.

**document_storage:**
```python
- create_document(title: str, content: str, metadata: DocumentMetadata) → doc_uri
- read_document(doc_uri: str) → Document
- update_document(doc_uri: str, content: str, metadata: DocumentMetadata,
                  approval_token: str | None, idempotency_key: str,
                  expected_version: str | None) → success   # §3.9
- delete_document(doc_uri: str, approval_token: str | None,
                  idempotency_key: str,
                  expected_version: str | None) → success   # §3.9
- list_documents(filters: FilterSpec, limit: int) → list[DocumentMetadata]
```

**vector_search:**
```python
# Keyword search (exact/partial text match)
- search_by_keywords(
    query: str,
    filters: FilterSpec = None,
    top_k: int = 10,           # per-backend fetch; user-facing top_k is a TOTAL (§3.7)
    fields: list[str] = None
  ) → list[SearchResult]

# Semantic search (vector similarity)
- search_by_semantics(
    query: str,
    filters: FilterSpec = None,
    top_k: int = 10,
    similarity_threshold: float | None = None
    # None → backend's own calibrated default from
    # capabilities.vector_search.defaults.similarity_threshold.
    # Thresholds are backend-specific and never compared across backends.
  ) → list[SearchResult]

# Hybrid search (both, merged)
- search_hybrid(
    query: str,
    filters: FilterSpec = None,
    top_k: int = 10,
    keyword_weight: float = 0.3,
    semantic_weight: float = 0.7,
    similarity_threshold: float | None = None
  ) → list[SearchResult]
```

**approval_flow (optional, router-enforced — §3.4):**
```python
- request_approval(doc_uri: str, approvers: list[str],
                   operation: "update" | "delete" | "create") → approval_id
- check_approval(approval_id: str) → ApprovalStatus
- execute_approved(doc_uri: str, approval_id: str) → success
# approval_id binds the approval decision to exactly one doc_uri + operation;
# execute_approved rejects mismatched pairs.
# Approvals carry a TTL: check_approval returns `expired` after expires_at (§3.4).
```

### 3.2 Capability Declaration

Each backend's capabilities are **runtime-detected** and cached (§3.5); the config holds only user overrides. `fallback` is always a **sibling** of `features`, never nested inside it:

```yaml
capabilities:
  document_storage:
    supported: true
    features: [create, read, update, delete, list]

  vector_search:
    supported: true
    features:
      search_by_keywords: true
      search_by_semantics: false
      search_hybrid: false
    fallback:                                    # sibling of features
      search_by_semantics: search_by_keywords
```

### 3.3 Capability-Aware Routing

The router uses capability info to make smart decisions. Fallback resolution is uniform: config `fallback` entries are consulted for any unsupported mode; if none is defined, the built-in chain is `hybrid → semantic → keyword`:

```python
BUILTIN_FALLBACK = {"hybrid": "semantic", "semantic": "keyword"}

async def search_knowledge(query, mode="hybrid", backends="all"):
    targets = resolve_backends(backends)   # selection grammar: §4.2
    results = []

    for backend in targets:
        caps = backend.capabilities.vector_search

        actual_mode = mode
        # Uniform fallback: config overrides, then built-in chain
        while not caps.supports(actual_mode):
            actual_mode = (
                caps.fallback.get(actual_mode)          # config fallback
                or BUILTIN_FALLBACK.get(actual_mode)    # built-in chain
            )
            if actual_mode is None:
                log(f"Backend {backend.name}: no supported mode, skipping")
                break
        if actual_mode is None:
            continue
        if actual_mode != mode:
            log(f"Backend {backend.name}: {mode} → {actual_mode} (fallback)")

        backend_results = await backend.search(
            query, mode=actual_mode,
            top_k=min(top_k, caps.limits.max_results),   # clamp (§3.7)
            timeout=cfg.defaults.timeouts.search_seconds,
        )
        results.extend(backend_results)

    # Aggregate, rank (RRF — §7.3), truncate to the top_k TOTAL (§3.7)
    return aggregate_results(results)[:top_k]
```

### 3.4 Approval Enforcement (Router Layer)

Approval is **enforced by the router, not advisory**:

1. If the target backend declares `approval_flow.supported: true` and the write operation matches a backend policy requiring approval (e.g., update/delete of shared docs), the router **blocks** the direct `update_document`/`delete_document` call.
2. The router drives `request_approval → check_approval → execute_approved` and passes the resulting `approval_token` into the write call. Backends reject writes that require approval but carry no valid token.
3. `approval_id` is cryptographically bound to `(doc_uri, operation, content_fingerprint)`; `execute_approved` verifies the binding, so an approval cannot be replayed against different content.
4. Skills cannot bypass this gate because the capability interfaces exposed to the skills layer require the token for gated operations.
5. Backends without approval flow fall back to the standard user-confirmation proposal (§5.6); the proposal states that no platform-side approval exists.
6. **Approvals expire.** Every approval carries `expires_at` (default: `defaults.approval_ttl_hours`). An expired approval is treated as rejected — the write does not execute and a fresh approval must be requested with user confirmation.
7. **Fan-out writes are approved per target.** A multi-backend write (§6.4) touching several gated backends creates one approval per target; the proposal lists all of them. `--yes` (§12) never bypasses platform approvals — it bypasses only kgent's interactive confirmation.
8. **Approver policy.** Approvers must be resolved platform identities (resolved through the backend's directory, never free text passed through verbatim). **Self-approval** — the requester also approving — is allowed by default **only when the target document is owned by the requester** (`DocumentMetadata.owner`, §3.8); for shared documents owned by others, self-approval is denied and at least one other approver is required. If ownership cannot be determined, the router fails closed (self-approval denied). Backends may tighten or loosen this via `approval.self_approval: deny | owned_only | always` (default `owned_only`).

### 3.5 Runtime Capability Verification

- Detection results live in `~/.kgent/capabilities.cache.yaml` with a per-backend `detected_at` timestamp.
- The cache is refreshed: on `kgent-setup`, on backend version change, when TTL expires (default 7 days), or on first capability mismatch error.
- **Effective capability = intersection(cache-detected, config-declared).** Config may only *narrow* detected capabilities (e.g., disable a feature), never assert a capability the backend does not actually provide. If config asserts an unsupported capability, the router warns and treats it as unsupported.
- On a runtime capability error, the affected backend is marked dirty, the cache entry is invalidated, and the operation proceeds with remaining backends per §8.1.

### 3.6 Canonical Document URIs

All cross-layer references use URIs of the form:

```
kgent://<backend>/<backend-native-id>
examples:
  kgent://lark/docxABC123
  kgent://kgent/kb_9f8e7d
```

- Adapters translate URI ↔ native ID at the boundary.
- Search results, the write journal (§6.7), audit log (§8.4), and deduplication records all use URIs.
- A registry (`~/.kgent/idmap.json`) maps content fingerprints → URIs across backends to support cross-backend dedupe (§6.5) and `also_available_in`.

### 3.7 Filter Schema and Clamping

`FilterSpec` is a typed object, not a free-form dict:

```python
FilterSpec:
  tags: list[str] = []
  content_type: str | None
  created_after: date | None
  created_before: date | None
  updated_after: date | None
  updated_before: date | None
  owner: str | None
```

- Filters supported natively by a backend are pushed down; unsupported filters are applied **post-filter** by the adapter (documented in the adapter), and the result set is refilled up to `top_k` where the backend supports pagination.
- `top_k` is always clamped to the backend's `limits.max_results`; the clamped value is reported in result metadata so ranking knows true coverage.
- `max_query_length` violations are truncated with an explicit warning, never silently.
- **`top_k` is a total across backends.** The user-facing `top_k` bounds the *final merged* result list: the router fetches `min(top_k, limits.max_results)` per backend, ranks (§7.3), then truncates to `top_k`. Adapters never silently return more than the fetch size.
- **Content size limits.** Backends declare `limits.max_content_bytes`. Writes are preflighted against every target's limit *before* the proposal is shown; oversized content is rejected with the actual size vs. limit and suggestions (split, or archive the raw file instead). Fan-out writes check all targets up front.

### 3.8 Core Data Types

Normative schemas shared by all adapters. Field naming draws on the existing agent-service models (`KnowledgeReference`, suggested operations) for continuity.

```python
DocumentMetadata:
  doc_uri: str                     # canonical URI (§3.6)
  title: str
  backend: str                     # backend name, e.g. "lark"
  location_url: str | None         # direct URL on the source platform
  location_description: str | None # human-readable path from root,
                                   # e.g. "Team Wiki > Meeting Notes"
  content_type: str | None         # per routing model (§4)
  sensitivity: str                 # public | internal | confidential (§2.5)
  tags: list[str] = []
  owner: str | None
  created_at: datetime             # UTC ISO-8601
  updated_at: datetime
  version: str | None              # backend revision token/etag (§3.9); None if unsupported
  content_fingerprint: str | None  # §6.5
  size_bytes: int | None

SearchResult:
  doc_uri: str
  metadata: DocumentMetadata
  snippet: str | None              # match excerpt — untrusted content (§5.5)
  rank: int                        # 1-based position in the source backend's list
  score_native: float | None       # backend-native score; NEVER compared across backends (§7.3)
  mode_used: str                   # actual search mode after fallback (§3.3)
  also_available_in: list[str] = []  # doc_uris of fingerprint-identical copies (§7.2)
  access: str = "ok"               # ok | denied | stale — read-path verification (§8.6)

ApprovalStatus:
  approval_id: str
  state: str                       # pending | approved | rejected | expired
  requested_at: datetime
  decided_at: datetime | None
  expires_at: datetime | None      # TTL (§3.4)
  approvers: list[ApproverDecision]
  binding:                         # cryptographic binding (§3.4)
    doc_uri: str
    operation: str                 # create | update | delete
    content_fingerprint: str

ApproverDecision:
  approver: str
  decision: str                    # accept | reject | pending
  decided_at: datetime | None
```

### 3.9 Optimistic Concurrency Control

Update-first bias makes concurrent editors (another session, the platform UI) realistic. Silent clobbers are forbidden:

1. `read_document` returns `metadata.version` — the backend's revision token (etag / revision number). Backends without tokens return `version: None`.
2. Proposals record the version at read time; `update_document`/`delete_document` pass it as `expected_version`.
3. Adapters must fail with a `VersionConflict` error when the backend's current version differs from `expected_version`. The router turns a conflict into a **re-read + fresh proposal** ("document changed on-platform at … — review and retry"), never an auto-merge or overwrite.
4. Backends without revision tokens fall back to `updated_at` comparison, and the proposal must carry the warning "no hard concurrency protection on \<backend\>".
5. Conflicts are journaled with `status: conflict` and count toward §11 (zero stale overwrites).

---

## 4. Routing Model (Single Precedence Chain)

### 4.1 Precedence

Exactly one mechanism selects backends for any operation, evaluated in this order — the first match wins, later mechanisms are not consulted:

1. **Explicit selection**: `--backends` flag / tool argument (§4.2). Overrides everything, including config.
2. **Smart rules** (only when `routing_mode: smart`): first matching `routing_rules` entry, evaluated on operation + metadata (§4.3).
3. **Content-type mapping** (when `routing_mode: configured`, or smart rules didn't match): `content_type_mapping[content_type]`, else `content_type_mapping.default`. Resolves to exactly one write target backend (no replicas — v1.2).
4. **Defaults**: `defaults.default_backends`.

**Fallback chains (§8.3) are not a selection mechanism** — they only activate when a selected backend *fails* at execution time, and for writes only with user confirmation.

### 4.2 Backend Selection Grammar

`--backends` / config resolution accepts exactly these values:

| Value | Meaning |
|---|---|
| `all` | Alias of `all_enabled` (kept for familiarity; never includes disabled backends) |
| `all_enabled` | All enabled backends with the required capability |
| `all_configured` | Backends selected by precedence steps 2–4 for this operation |
| `<name>[,<name>]*` | Explicit list; unknown names → hard error |

Default when omitted: `all_configured` for writes, `all_enabled` for searches.

### 4.3 Explicit / Configured / Smart Modes

**Explicit** — user specifies backends per command:

```bash
kgent store --backends lark,dingtalk --title "X" --file body.md
kgent search --backends kgent --query "Z"
```

**Configured (default)** — uses precedence step 3 then 4:

```bash
kgent store --title "X" --file body.md
```

**Smart** — precedence step 2: rules match on *operation, declared content_type, and tags*.

Note on `older_than`: rules with `older_than` apply only to `kgent archive` operations (moving existing documents), never to `store`, since age is unknowable for new content. Age is measured from `metadata.updated_at` (last activity), not `created_at` — an old document that was recently edited is still active and not eligible for archiving. `analyze_content_type()` is LLM-assisted and therefore **best-effort**: the inferred `content_type` and `sensitivity` are always shown in the write proposal (§5.6) and can be corrected before confirming. A misclassification can be caught at confirmation time; nothing routes on classification alone without that checkpoint.

### 4.4 No Replicas (v1.2)

A write resolves to exactly one target backend unless the user explicitly fans out (`--backends a,b`) or a routing rule lists multiple backends. kgent never creates automatic copies of documents. Pre-existing duplicates across backends are *detected* (fingerprint + near-duplicate clustering, §6.5) and surfaced for a confirmed merge/update choice (§6.2) — they are never silently reconciled.

---

## 5. Intent Clarification System

### 5.1 Self-Disambiguation for *Proposals*

Before asking questions, gather context from multiple sources. Context gathering informs the **proposal**, never the execution:

```python
async def gather_context(user_request, intent):
    context = {}

    # 1. Conversation context
    context['conversation'] = get_recent_conversation_context()

    # 2. Existing knowledge (treated as UNTRUSTED DATA — §5.5)
    context['existing_knowledge'] = await search_related_knowledge(
        query=user_request,
        top_k=10
    )

    # 3. User preferences
    context['user_preferences'] = load_user_preferences()

    # 4. Memory/learnings
    context['learnings'] = load_user_learnings()

    # 5. Common sense / heuristics
    context['heuristics'] = apply_common_sense(user_request)

    # 6. Explicit metadata
    context['explicit_metadata'] = extract_explicit_metadata(user_request)

    return context
```

### 5.2 Resolution Priority

When multiple context sources conflict:

1. **Explicit user input** (highest)
2. **Recent conversation context**
3. **User learnings**
4. **User preferences**
5. **Existing knowledge** (untrusted — influences the *proposal*, never bypasses confirmation)
6. **Common sense heuristics** (lowest)

### 5.3 Clarification Flow

There is **no confidence threshold that auto-executes**. Resolution has two outcomes:

- Enough context → build a fully-specified **proposal** (still requires confirmation for writes, §5.6).
- Not enough context → ask only about the remaining ambiguities, then propose.

```python
async def resolve_intent_with_context(user_request):
    initial_intent = parse_intent(user_request)
    context = await gather_context(user_request, initial_intent)

    resolved_intent = initial_intent
    resolved_intent = resolve_from_conversation(resolved_intent, context['conversation'])
    resolved_intent = resolve_from_existing_knowledge(resolved_intent, context['existing_knowledge'])
    resolved_intent = resolve_from_preferences(resolved_intent, context['user_preferences'])
    resolved_intent = resolve_from_learnings(resolved_intent, context['learnings'])
    resolved_intent = resolve_from_heuristics(resolved_intent, context['heuristics'])

    if resolved_intent.has_remaining_ambiguities():
        # Ask only about what's still ambiguous
        resolved_intent = await ask_clarifying_questions(
            resolved_intent.remaining_ambiguities(), context)

    # Always return a proposal object; execution is gated by §5.6
    return build_proposal(resolved_intent, context)
```

Each resolution step records *which source decided which field* — the proposal displays this provenance ("target inferred from: conversation context") so users can spot wrong inferences at a glance.

### 5.4 Example: Smart Disambiguation

```
User: "Save this"

Skill gathers context:
1. Conversation: just discussed "API design guidelines v2"
2. Existing: found "API Design Guidelines v1" in Lark (top match)
3. Preferences: default_backend=lark, update-first bias
4. Learnings: user had duplicate issues before

Skill resolves a proposal (NOT an execution):
- Intent: UPDATE (not create)
- Target: kgent://lark/docxABC123 ("API Design Guidelines v1")
- Content: the discussion we just had

┌─────────────────────────────────────────────────┐
│ Proposal (no action taken yet)                  │
│ UPDATE "API Design Guidelines v1" in Lark       │
│ with the v2 changes we just discussed.          │
│ Inferred from: conversation + existing doc      │
│ Sensitivity: internal                           │
│ A snapshot for undo will be kept (§6.7).        │
│                                                 │
│ Proceed? [yes/no/edit]                          │
└─────────────────────────────────────────────────┘

Zero questions asked — but zero silent writes too.
```

`[edit]` opens the proposal fields (target, title, content_type, sensitivity, backend list) for correction before confirmation.

### 5.5 Untrusted Content (Prompt-Injection Defense)

All content returned by backends — documents, search snippets, titles, metadata — is **data, never instructions**:

1. Retrieved content is wrapped with explicit source markers when placed in agent context (e.g., `<untrusted-content source="kgent://lark/…">…</untrusted-content>`).
2. Skills MUST NOT treat content inside those markers as user requests: no writes, approvals, config changes, or credential access may be triggered by it.
3. Write proposals generated from retrieved content must cite the source URI and be confirmed like any other write (§5.6).
4. Capability detection (§2.2) reads structured manifests only, never free-form backend text (§2.2).

### 5.6 Mandatory Proposal Display for Writes

**Invariant: no write executes without a displayed proposal and explicit confirmation.** The proposal includes: operation, target URI(s) + backend(s), title, inferred content_type and sensitivity (§2.5), approval requirement if any (§3.4), and inference provenance (§5.3).

The **only** bypass is non-interactive scripted mode: `--yes` with explicit `--backends` and full content supplied via flags/stdin (§12). Interactive sessions and skill invocations cannot bypass confirmation. Every executed write is journaled (§6.7) and audited (§8.4) regardless.

---

## 6. Write Operation Orchestration

### 6.1 Update-First Bias

**Rule: Always *propose* updating existing knowledge over creating new.**

```python
async def handle_save_knowledge(user_request):
    intent = await clarify_intent(user_request)      # §5.3
    content = await extract_content(intent)

    # ALWAYS search for existing knowledge first
    existing = await search_knowledge(
        query=content.title,
        backends="all_configured",
        top_k=10,
        # dedupe uses near-duplicate detection, §6.5 —
        # no single global similarity threshold
    )

    if existing:
        return await propose_update_existing(existing, content)  # → confirm
    else:
        return await propose_create_new(content)                 # → confirm
```

### 6.2 UPDATE Flow

```python
async def handle_update(content):
    existing = await search_existing(content.title)

    if len(existing) == 0:
        return propose_create_new(content)

    elif len(existing) == 1:
        return propose_update_single(existing[0], content)

    else:
        return propose_update_multiple(existing, content)
```

**Example: Multiple Locations**

```
User: "Update the API design guidelines"

Skill finds (near-duplicate match, §6.5):
  - kgent://lark/docxAAA  "API Design Guidelines v1" (updated 2024-01-15)
  - kgent://kgent/kb_BBB  "API Design Guidelines"    (updated 2024-01-10)

┌─────────────────────────────────────────────────┐
│ Found "API Design Guidelines" in 2 places:      │
│                                                 │
│ 1. Lark                                         │
│    - kgent://lark/docxAAA                       │
│    - Last updated: 2024-01-15                   │
│                                                 │
│ 2. kgent                                        │
│    - kgent://kgent/kb_BBB                       │
│    - Last updated: 2024-01-10                   │
│                                                 │
│ Options:                                        │
│ [a] Update Lark only (most recent — recommended)│
│ [b] Update kgent only                           │
│ [c] Update both                                 │
│ [d] Merge into one (keep Lark, delete the       │
│     kgent copy — confirmed separately)          │
│ [e] Something else                              │
└─────────────────────────────────────────────────┘
```

**Copy grouping.** Copies with *identical* fingerprints — e.g., created by an explicit fan-out write (§6.4) — collapse into a single option: "Update all N copies (identical content)", executed under one op id with per-backend reporting. Only near-duplicates (different fingerprints) stay separate options, since they can have diverged (§6.5).

### 6.3 CREATE Flow

```python
async def handle_create(content):
    duplicates = await search_similar(content)     # near-dup, §6.5
    if duplicates:
        return propose_duplicate_detected(duplicates, content)

    content_type = analyze_content_type(content)   # best-effort, shown in proposal
    sensitivity = analyze_sensitivity(content)     # best-effort, §2.5
    routing = resolve_routing(content_type)        # §4.1 precedence
    enforce_zone_rules(routing, sensitivity)       # §2.5, hard reject

    return propose_storage_location(routing, content)  # includes [edit]
```

### 6.4 Multi-Backend Write Operations

**Strategy: best-effort with journaling and repair** (transactional rollback is infeasible across third-party APIs; instead, failures are journaled and repaired by `kgent sync`, §6.6):

```bash
$ kgent store --backends lark,dingtalk,confluence --title "X" --file body.md
✅ Stored to Lark:      kgent://lark/docxABC123
✅ Stored to DingTalk:  kgent://dingtalk/d_456
❌ Failed on Confluence: Authentication expired
   → Run `confluence-cli auth` to re-authenticate
   → Repair: `kgent sync --repair op-20260826-01`
(op id: op-20260826-01 — journaled for retry/undo)
```

All legs of a multi-backend write share one **idempotency key** (op id); retrying a failed leg will not duplicate content on backends that already succeeded (§6.6).

**Cancellation.** Interrupting a multi-backend operation aborts unstarted legs; legs already written stay written and are journaled (`status: partial`). There is no rollback of completed legs — repair is `kgent sync --status` (§6.6) and reversal is `kgent undo` (§6.7).

### 6.5 Deduplication Strategy

Two layers:

1. **Exact fingerprint** (hash of normalized title+content) stored in backend metadata and in `~/.kgent/idmap.json`; catches byte-identical copies and powers `also_available_in`.
2. **Near-duplicate detection** for everything else: title-similarity (edit distance/embedding) + structural similarity, run at search-aggregation time (§7.2) and in update-first lookups (§6.1). Near-duplicate clusters are shown grouped with per-member provenance; no automatic merging — merging is always a confirmed user action.

No global similarity threshold: matching decisions are per-backend calibrated or rank-based, and cluster boundaries are shown to the user in proposals.

### 6.6 Repair: `kgent sync`

```bash
kgent sync --status              # list failed legs of multi-backend operations
kgent sync --repair <op-id>      # retry failed legs (idempotent via op id)
kgent sync --repair-all          # all outstanding journal entries
```

- Reads the write journal (§6.7); every retry is idempotent (idempotency key) and re-confirmed only if content would differ from the original proposal.

### 6.7 Write Journal and Undo

Every executed write appends to `~/.kgent/journal/` (NDJSON, append-only):

```json
{"schema_version": 1, "op_id": "op-20260826-01", "ts": "…", "operation": "update",
 "targets": ["kgent://lark/docxAAA"], "idempotency_key": "…",
 "snapshot": {"content_before": "…", "metadata_before": "…"},
 "proposal_hash": "…", "confirmation": "interactive-yes",
 "sensitivity": "internal", "status": "ok"}
```

- Snapshots of pre-update/pre-delete content are kept locally (default retention 30 days, configurable) to support undo.
- Journal and snapshot files are created **0600** (user-only). Entries carry `schema_version` for forward migration. In fact, the entire `~/.kgent` directory is created **0700** and all files within it (journal, snapshots, idmap, capability cache, trusted.json, config) **0600** — local state protection is directory-wide, not per-file.
- **Encryption at rest is opt-in**: `journal.encrypt: true` encrypts snapshots with a key held in the OS secret store (§2.4). Default is `false` (favoring recoverability); kgent states plainly in proposals when unencrypted snapshots contain `confidential`-tier content.
- `kgent undo <op-id>` restores the snapshotted state on every target of that operation (best-effort across backends, with the same per-backend reporting as §6.4).
- Journal entries also drive `kgent sync` (§6.6) and feed the audit log (§8.4).

### 6.8 DELETE Flow (Archive-First)

Delete was previously unspecified; it is now first-class, and **archive-first: if an archive target is available, the delete proposal always recommends archiving over hard deletion.**

**Archive availability.** An archive target is *available* for a document when all hold:

1. `routing_rules` matches `operation: archive` for this document (§4.3), or a valid backend declares `archived_docs` in its `content_types`;
2. that target is a different backend than the document's source;
3. the target satisfies the document's sensitivity zone (§2.5).

```python
async def handle_delete(doc_uri):
    doc = await read_document(doc_uri)
    archive_target = resolve_archive_target(doc_uri)   # None if unavailable

    return propose_delete(
        target=doc_uri,
        archive_recommended=archive_target,  # shown as recommended option when present
        snapshot=True,                       # content snapshotted pre-delete (§6.7)
        approval=approval_required(doc_uri), # §3.4 gate
    )
```

```
$ kgent delete kgent://lark/docxAAA

┌─────────────────────────────────────────────────┐
│ Delete "API Design Guidelines v1" (Lark)?       │
│                                                 │
│ [a] Archive to kgent (RECOMMENDED)              │
│     Moves it to kgent-hosted, then removes      │
│     it from Lark                                │
│ [b] Hard delete from Lark                       │
│ [c] Cancel                                      │
└─────────────────────────────────────────────────┘
```

**Archive is a move, journaled as one operation.** Option [a] (or `kgent archive` directly) executes two legs under a single op id: (1) write the content to the archive backend, (2) delete the source — the delete leg runs **only after the archive write succeeds**, so a failed archive never loses the document. Both legs are journaled (§6.7); `kgent undo <op-id>` restores the source document and removes the archived copy. The archived copy includes the source's native-format export for lossless restore (§6.9).

```bash
kgent delete kgent://lark/docxAAA            # proposal recommends archive when available
kgent archive kgent://lark/docxAAA           # direct move; same confirmation + journaling
kgent undo <op-id>                           # restore from snapshot
```

- When no archive target is available (none configured, only candidate is the source backend itself, or rejected by zone rules), the proposal falls back to plain hard delete and states why archive was not offered.
- Deleting near-duplicate copies that exist on other backends is never implicit: they are listed in the proposal as "similar documents elsewhere" and deleting any of them requires its own confirmation.
- Deletes are always confirmed (§5.6), snapshotted (§6.7), and audited (§8.4).
- Platform-side trash/retention behavior of each backend is surfaced in the proposal where known ("Lark moves this to trash for 30 days").
- **Undo safety**: `kgent undo` of an archive operation first verifies the archived copy is unchanged (fingerprint matches what the archive leg wrote). If the copy was edited after archiving, undo aborts for that leg and asks the user to choose — keep the edited archive, or force-restore. Post-archive edits are never silently deleted.

### 6.9 Content Representation & Fidelity

Cross-backend moves (archive §6.8, fan-out §6.4) change formats; fidelity loss is declared, never silent:

- **Canonical format**: kgent's interchange format is Markdown body + `DocumentMetadata` sidecar (§3.8). Adapters convert native ↔ canonical at the boundary; `kgent read` returns canonical by default, `--native` fetches the backend-native format.
- **Fidelity classes**: each adapter declares `fidelity: lossless | lossy` per direction (e.g., lark → canonical is lossy for embeds, votes, comment threads).
- **Warn on lossy paths**: when a write/archive traverses a lossy conversion, the proposal lists what will degrade ("3 elements have no Markdown equivalent: vote block, diagram, comment thread") and requires confirmation like any other write.
- **Native blob preservation**: archive moves store the source's native export alongside the canonical Markdown, so `kgent undo` to the same backend type restores losslessly (§6.8). The blob counts against size limits (§3.7).
- **Never fabricate, never silently drop**: conversions must not invent content; unsupported elements become explicit placeholders (`[unsupported: vote block]`) that the user sees in the proposal diff.

---

## 7. Search Aggregation

### 7.1 Multi-Backend Search with Timeouts and Streaming

```python
async def search_knowledge(query, backends="all_enabled", mode="hybrid"):
    targets = resolve_backends(backends)          # §4.2
    warn_if_query_leaks_to_external(targets)      # §2.5, once per session

    # Fan out with per-backend timeout; slow backends degrade, don't block
    tasks = [
        asyncio.wait_for(
            backend.search(query, mode=resolve_mode(backend, mode)),  # §3.3
            timeout=cfg.defaults.timeouts.search_seconds,
        )
        for backend in targets
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    partial = collect_successes(results)
    failures = collect_failures(results)          # reported to user (§8.2)
    # Concurrency bounded by defaults.concurrency.max_parallel_backends

    merged = merge_and_deduplicate(partial)       # §7.2
    return rank(merged, top_k)                    # §7.3 RRF, truncated to top_k total (§3.7)
```

- Backends that time out are reported in the result footer ("2 backends timed out — results partial"), never silently dropped.
- Results stream to the CLI as backends complete (`--stream`), so the slowest backend doesn't gate first output.

### 7.2 Result Aggregation

```python
def merge_and_deduplicate(results_from_backends):
    """
    Merge results; dedupe exact fingerprints, cluster near-duplicates (§6.5).
    """
    seen_fingerprints = set()
    merged = []
    clusters = near_duplicate_index()   # title/structure similarity, §6.5

    for backend_results in results_from_backends:
        for result in backend_results:
            fp = result.content_fingerprint
            if fp in seen_fingerprints:
                existing = next(r for r in merged if r.content_fingerprint == fp)
                existing.also_available_in.append(result.doc_uri)
                continue
            seen_fingerprints.add(fp)

            cluster = clusters.match(result)
            if cluster:
                cluster.members.append(result)   # shown grouped, never auto-merged
            else:
                merged.append(result)

    return merged
```

### 7.3 Ranking: Reciprocal Rank Fusion

Backend relevance scores are not comparable across engines, so ranking uses **rank-based fusion**, not score mixing:

```python
def rank(results_per_backend, top_k, k=60):
    """RRF over per-backend ranked lists. No raw score comparison."""
    scores = defaultdict(float)
    for backend, ranked_list in results_per_backend.items():
        for rank, result in enumerate(ranked_list, start=1):
            scores[result.doc_uri] += 1.0 / (k + rank)

    fused = sorted(scores.items(), key=lambda kv: -kv[1])

    # Tiebreakers only (never primary signals):
    # 1. recency within same RRF score band
    # 2. backend priority from config
    ranked = apply_tiebreakers(fused)

    # top_k is a TOTAL across backends (§3.7): truncate after fusion
    return ranked[:top_k]
```

---

## 8. Error Handling

### 8.1 Backend Failure Strategies

**Read operations (search):**
- **Partial success**: return results from successful backends within the timeout budget
- Failures/timeouts are reported in the result footer, never silently dropped
- Capability errors invalidate the capability cache (§3.5)

**Write operations (create/update/delete):**
- **Best-effort with journaling**: try all backends, record per-backend status in the write journal (§6.7)
- Failed legs are repaired via `kgent sync` (§6.6) with idempotency keys — never by re-running the whole store
- Transient errors (network, 5xx) get bounded retries with backoff (3 attempts); auth and permission errors are not retried
- **Rate limits are budgeted, not retried**: adapters track per-backend request budgets and honor `Retry-After`; rate-limited requests are queued until the operation timeout, and queueing never counts against the 3-attempt retry budget

### 8.2 Error Reporting

```bash
$ kgent store --backends lark,dingtalk,confluence --title "X" --file body.md

✅ Stored to Lark:      kgent://lark/docxABC123
✅ Stored to DingTalk:  kgent://dingtalk/d_456
❌ Failed on Confluence: Authentication expired
   → Run `confluence-cli auth` to re-authenticate
   → Repair: `kgent sync --repair op-20260826-01`
(op id: op-20260826-01)
```

### 8.3 Fallback Chains

```yaml
fallback_chains:
  document_storage:
    preferred: lark
    fallbacks: [dingtalk, confluence, kgent]

  vector_search:
    preferred: kgent
    fallbacks: [lark]
```

- **Searches**: fallbacks engage automatically on failure/timeout.
- **Writes**: fallbacks engage **only with explicit user confirmation** ("Lark is down — store to DingTalk instead?"). A failed write is never silently redirected to another backend, and §2.5 zone rules still apply to the fallback target.

### 8.4 Audit Log

Append-only `~/.kgent/audit.ndjson` records, for every operation:

```json
{"ts": "…", "op_id": "…", "actor": "user|skill:<name>", "operation": "update",
 "targets": ["kgent://lark/docxAAA"], "routing_decision": {"mechanism": "content_type_mapping",
 "matched": "meeting_notes"}, "confirmation": "interactive-yes|--yes", "approval_id": "…",
 "sensitivity": "internal", "outcome": "ok|partial|failed", "redacted_query": true}
```

- Written by the router, not skills — skills cannot skip it.
- Files are created 0600 (user-only). Entries carry `schema_version` for forward migration.
- Queries are redacted by default; `audit.redact_queries: false` is an opt-in with a warning.
- `kgent audit --since 7d [--op write]` inspects it.

### 8.5 Transport and Invocation Hardening

- MCP endpoints require TLS with certificate verification; server identity (cert SPKI pin) is recorded on first verified connection and mismatch aborts with a clear warning (no silent TOFU downgrade).
- CLI adapters invoke subprocesses with **argv arrays only** — no shell interpolation. Titles, content, and user-supplied strings are passed as discrete arguments; adapters validate argument shape before exec.
- Config parsing rejects unknown top-level keys (typo/injection defense) unless `version` indicates a newer schema.
- Backend query languages (Confluence CQL, Lark search syntax, filter DSLs) are built with parameterization/escaping only — raw interpolation of user query strings is forbidden.

### 8.6 Read-Path Staleness

Search indexes lie: documents get deleted or moved externally, and permissions get revoked.

- **Verify before proposing**: update-first (§6.2), delete/archive (§6.8), and undo targets are re-read immediately before the proposal is built. Search snippets alone are never sufficient basis for a write proposal.
- **Classified read failures**: `not_found` → the URI is marked `stale` in the idmap (§3.6) and excluded from update-first candidates until rediscovered; `permission_denied` → actionable error with the platform's access-request path; neither is retried.
- **Search results**: verification failures set `SearchResult.access` to `denied`/`stale` (§3.8); such results are demoted and visibly flagged, never silently dropped.
- **Bulk staleness**: if more than 20% of a backend's results fail verification, the router refreshes that backend's capability cache (§3.5) and warns.

---

## 9. Implementation Plan

### Phase 1: Core Infrastructure

1. **Capability Router Layer**
   - Capability interfaces with canonical URIs (§3.6) and core data schemas (§3.8)
   - Backend registry, config loading + trust model (§2.3)
   - Single routing precedence chain (§4.1)
   - Policy enforcement points: approval gate (§3.4), sensitivity rules (§2.5), write journal (§6.7), audit log (§8.4), optimistic concurrency (§3.9)

2. **Backend Adapters**
   - kgent-cli adapter (primary), lark-cli adapter (via lark-doc skill)
   - Adapter contract incl. argv safety, timeouts, error normalization (§1.2, §8.5), fidelity classes (§6.9)

3. **Configuration System**
   - Schema + validation + migration (§2.6)
   - OS secret store integration (§2.4)
   - Read-only auto-discovery + capability cache (§2.2, §3.5)

### Phase 2: Skills Layer

4. **Knowledge Storage Skill**
   - Context gathering + provenance tracking (§5.1, §5.3)
   - Update-first proposals (§6.1)
   - Mandatory proposal display + confirmation (§5.6)
   - Multi-backend orchestration with idempotency keys (§6.4)

5. **Question Answering Skill**
   - Multi-backend search with timeouts/streaming (§7.1)
   - RRF ranking + near-duplicate clustering (§7.2, §7.3)
   - Untrusted-content wrapping (§5.5)

6. **Wiki Setup Skill**
   - Orchestrate knowledge storage across backends
   - Drive approval flows via router gate (§3.4)

### Phase 3: Advanced Features

7. **Smart Routing**
   - Content type + sensitivity classification (best-effort, confirmed in proposals)
   - Rule engine restricted to §4.3 semantics
   - User preference learning (proposal-level only; never changes enforcement)

8. **Deduplication & Repair**
   - Fingerprint index + near-duplicate detection (§6.5)
   - `kgent sync` repair workflows (§6.6)
   - Undo via write journal (§6.7)
   - Content fidelity conversion + native-blob preservation (§6.9)

9. **Monitoring & Observability**
   - Audit log tooling (§8.4)
   - Backend health checks, capability-cache staleness reports
   - Performance metrics (p95 per-backend latency, partial-result rates)
   - Privacy guarantee: metrics are local-only — no content, queries, or document URIs leave the machine

---

## 10. Future Extensions

### 10.1 Additional Backends

Easy to add new backends by implementing capability interfaces:

- **Notion**: `notion-cli` adapter
- **Google Docs**: `gdocs-cli` adapter
- **SharePoint**: `sharepoint-cli` adapter

Each new backend starts as `trust_zone: external` until explicitly reclassified by the user.

### 10.2 Advanced Capabilities

- **Knowledge Graph**: Relationships between documents
- **Versioning**: Backend-side version tracking complementing the local write journal
- **Access Control**: Per-user ACLs and multi-user config (current design is single-user)
- **Offline Mode**: Queue operations when backends unavailable (journal-backed)

### 10.3 AI Enhancements

- **Auto-tagging**: Automatically classify content types (always confirmed via proposal)
- **Smart summaries**: Generate summaries for search results
- **Conflict resolution**: AI-powered merge suggestions (proposals only; merges are confirmed user actions)
- **Learning**: Improve routing suggestions based on user confirmations/edits — learning may change *default proposals*, never enforcement rules

---

## 11. Success Criteria (Measurable)

These criteria are operationalized as executable acceptance scenarios in the companion acceptance spec ([2026-08-26-kgent-packaging-acceptance.md](2026-08-26-kgent-packaging-acceptance.md)): each criterion below maps to named scenarios (S-ids), negative constraints (N-ids), and gauntlet layers there. Implementation is gated on approval of that spec.

1. **Zero wrong writes**: in the e2e test suite, no write executes without a recorded confirmation matching the executed targets (`journal.confirmation` present and consistent). Target: 0 violations.
2. **Zero silent failures**: every backend failure/timeout surfaces in user-visible output; measured by fault-injection tests across search and write paths.
3. **Proposal accuracy**: ≥90% of write proposals are confirmed without `[edit]` corrections (measures disambiguation quality without incentivizing silence).
4. **Repairability**: 100% of partial multi-backend writes recoverable via `kgent sync` without manual platform operations (fault-injection test).
5. **Search latency**: p95 aggregated search ≤ slowest-enabled-backend timeout + 2s; first streamed result ≤ 3s on reference workloads.
6. **Ranking quality**: RRF top-3 contains the human-judged best result in ≥80% of a labeled evaluation set.
7. **Modularity**: adding a new backend requires only an adapter + capability cache entry; verified by a conformance test suite run against every adapter.
8. **Security regression**: config-injection test suite (forbidden project-local keys, untrusted dirs, malicious skill_name/mcp_url overrides) passes on every build.
9. **Zero stale overwrites**: concurrent-edit fault injection yields 0 silent clobbers — every version conflict surfaces as a re-read proposal (§3.9).
10. **Zero archive data loss**: archive-move fault injection (kill mid-move, fail the archive write) never loses content; source deletes only after a verified archive write (§6.8).
11. **No silent fidelity loss**: every lossy cross-backend conversion is warned and confirmed in the proposal (§6.9); measured across the adapter conformance suite.

---

## 12. CLI Surface

All commands support a common flag set; behaviors below are normative.

```bash
kgent store   [--title T] (--file F | --stdin | --content C)
              [--backends SEL] [--content-type CT] [--sensitivity S]
              [--routing explicit|configured|smart]
              [--dry-run] [--yes] [--json]

kgent search  --query Q [--backends SEL] [--mode keyword|semantic|hybrid]
              [--top-k N] [--stream] [--json]

kgent read    <doc-uri> [--native] [--json]
kgent delete  <doc-uri> [--yes] [--json]
kgent archive <doc-uri|--older-than 90d> [--backends SEL] [--json]
              # --older-than measured on updated_at (§4.3)

kgent sync    --status | --repair <op-id> | --repair-all
kgent undo    <op-id>
kgent audit   [--since 7d] [--op read|write|delete] [--json]
kgent auth    status | login <backend> | logout <backend>
kgent setup   [--read-only]          # §2.2 discovery, read-only guaranteed
kgent trust   [--revoke]             # §2.3 project-config trust
kgent config  validate | migrate | show-effective [--json]
```

**Rules:**

1. **Content input**: long content goes via `--file` or `--stdin`; `--content` exists but is not required for any flow. Nothing ever requires shell-quoting large bodies.
2. **`--dry-run`**: resolves routing, runs duplicate/update-first lookup, and prints the exact proposal that would be shown — then exits without any write or journal entry.
3. **`--yes`**: bypasses interactive confirmation ONLY when combined with explicit `--backends` and fully-specified content; ignored (with warning) in interactive/TTY sessions invoked through skills. It never bypasses platform approval gates (§3.4). Every `--yes` write is still journaled and audited with `confirmation: "--yes"`.
4. **`--json`**: stable machine-readable output (schema-versioned) for every command; success/failure is also reflected in exit codes (0 = ok, 2 = partial success, 1 = failure, 3 = rejected by policy, 4 = version conflict §3.9).
5. **Doc URIs**: all commands accepting documents take canonical URIs (§3.6); bare native IDs are rejected with a hint, not guessed.
6. **Idempotency**: `store`/`update`/`delete` accept `--op-id` to reuse an existing operation id (safe retries, §6.6); omitted → new op id generated and printed.
7. **Archive-first delete**: `kgent delete` always presents archive as the recommended option when an archive target is available (§6.8); hard delete remains an explicit choice. `kgent archive` performs the same confirmed, journaled move directly.
8. **Batch operations & cancellation**: multi-document operations (`kgent archive --older-than`, any bulk selector) show one batch proposal — count, per-document targets, total size — and one confirmation covers the batch; `--dry-run` lists every item; each item is individually journaled and undoable. Interrupting a running operation aborts unstarted legs; completed legs stay journaled (`status: partial`) and are inspectable via `kgent sync --status` — nothing is silently rolled back (§6.4).

---

## Appendix A: Glossary

- **Backend**: A platform or service that provides knowledge management capabilities (Lark, DingTalk, Confluence, kgent-hosted)
- **Capability**: A specific feature or operation (document_storage, vector_search, approval_flow)
- **Skill**: An orchestration layer that coordinates complex workflows using capabilities
- **Router**: Middleware that routes operations to appropriate backends and *enforces* policy gates (approval, sensitivity, journaling, audit)
- **Routing Mode**: How backends are selected (explicit, configured, smart) — single precedence chain, §4.1
- **Canonical URI**: `kgent://<backend>/<native-id>` — the only identifier form that crosses adapter boundaries
- **Write Journal**: Append-only local record of executed writes, enabling `kgent sync`, `kgent undo`, and audit
- **Trust Zone**: Backend classification (`internal`/`external`) used by the data-leakage policy (§2.5)
- **Proposal**: A fully-specified, user-confirmable plan for a write operation; the mandatory precursor to execution
- **Canonical Format**: Markdown body + `DocumentMetadata` sidecar — kgent's interchange representation; adapters convert native ↔ canonical at boundaries (§6.9)
- **Optimistic Concurrency**: `expected_version` checks ensuring updates never clobber external edits; conflicts re-propose instead (§3.9)
- **Approval TTL**: Approvals expire (`expires_at`); expired approvals are treated as rejected (§3.4)

---

## Appendix B: Configuration Examples

### Minimal Config (Single Backend)

```yaml
version: 1
defaults:
  routing_mode: configured
  default_backends: [kgent]

backends:
  kgent:
    enabled: true
    type: mcp
    mcp_url: https://kgent.example.com/mcp   # TLS required (§8.5)
    trust_zone: internal
    capabilities:
      document_storage:
        supported: true
      vector_search:
        supported: true
    # No auth block: credentials live in the OS secret store (§2.4)
```

### Multi-Backend with Smart Routing

```yaml
version: 1
defaults:
  routing_mode: smart

backends:
  lark:
    enabled: true
    type: skill
    skill_name: lark-doc
    trust_zone: internal
    capabilities:
      document_storage: {supported: true}
      vector_search:
        supported: true
        features:
          search_by_keywords: true
          search_by_semantics: true
          search_hybrid: true
    content_types: [internal_docs, meeting_notes]

  kgent:
    enabled: true
    type: mcp
    mcp_url: https://kgent.example.com/mcp
    trust_zone: internal
    capabilities:
      document_storage: {supported: true}
      vector_search: {supported: true}
    content_types: [archived_docs]

routing_rules:
  - match:
      content_type: meeting_notes
    backends: [lark]

  - match:
      operation: archive       # older_than rules: archive ops only (§4.3)
      older_than: 90d
    backends: [kgent]

  - default: [lark, kgent]

audit:
  enabled: true
  redact_queries: true
```

---

**End of Specification**
