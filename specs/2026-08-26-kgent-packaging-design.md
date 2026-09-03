# kgent Service Packaging Design Spec

**Date**: 2026-08-26
**Last Revised**: 2026-08-31 (v1.8 — wiki / knowledge-space support)
**Status**: Draft
**Version**: 1.8

## Changes in v1.8

Wiki (knowledge space) support across the CLI and skills:

- **Wiki node creation** (§6.10): `kgent create --wiki-space <space_id>` creates a wiki node inside a knowledge space (hierarchical, platform-owned structure) rather than a flat Drive doc. `--parent-node-token` places the node under an existing parent.
- **Wiki space management** (§12): `kgent wiki spaces list` and `kgent wiki spaces create` expose knowledge-space operations as primitives.
- **Search covers wiki by default** (§7.2): `kgent search` returns wiki nodes alongside flat docs. Results carry `node_type` (`doc` | `wiki_node`) and wiki position metadata (space, parent). No separate wiki search.
- **Updates keep wiki position** (§6.2, §6.10): updating a wiki node URI modifies content in place; the node stays in its hierarchy position.
- **Native URLs for wiki nodes** (§1.7): Lark wiki nodes map to `https://<workspace_domain>/wiki/<node_token>`; docs map to `/docx/<token>`. Skills must match the URL path to the node type — a mismatched path is a broken link.
- **Skill layer** (§5.2): knowledge-storage asks the user wiki-vs-doc when all other factors are equal, and places new wiki nodes under a topically-fitting parent (never guessed tokens). question-answering treats wiki hits as first-class results. wiki-setup uses kgent primitives for space management, node creation, and search.

## Changes in v1.7

Skill packaging and native URL presentation gaps closed:

- **Skill packaging format** (§1.6): skills are packaged as Claude Code SKILL.md files with frontmatter (name, description, metadata), installable via symlink to ~/.claude/skills/ or .claude/skills/.
- **Native URL presentation** (§1.7): skills MUST convert canonical URIs (kgent://...) to native platform URLs (https://workspace/docx/token) when presenting results to users. workspace_domain is configured in defaults.workspace_domain.
- **Installation instructions**: README documents skill installation via symlink or copy to Claude Code skill directories.
- **Acceptance scenarios**: F19–F20, S70–S76, N20–N21 verify skill packaging, installation, and native URL presentation.

## Changes in v1.6

Second PR #1 review round (1 comment):

- **Routing intent + adapter preference**: the router returns a structured `RoutingIntent` (operation, resolved backends + adapter, required capabilities, policy gates, proposal) to the agent loop, which then invokes the resolved platform skill/CLI. Adapter resolution prefers a platform skill (e.g., `lark-doc`) over the CLI when both satisfy the required capability (§1.2, §1.4, §1.5, §3.8). Lark/Feishu integrates via the `lark-doc` skill with `lark-cli` as fallback (§1.3, §2.1, §2.2, §9).

## Changes in v1.5

PR #1 review applied (11 reviewer comments). Design semantics that changed:

- **Initial backend scope**: Lark/Feishu, DingTalk, and WeCom (all with official CLIs) are the initial-phase backends; the kgent-hosted backend lands in a later phase (the `kgent` CLI itself is still built in Phase 1 to power kgent skill setup). Confluence moves to future extensions (§1.3, §9, §10.1).
- **`vector_search` → `document_search`**: the capability is document search; "vector" is only the semantic sub-mode (§2.1, §3.1–§3.3, §8.3).
- **Lazy authentication**: discovery never prompts for credentials; auth is established lazily at first invocation (§2.2, §2.4).
- **`kgent doctor`**: config + environment health check command, non-interactive (§2.6, §12).
- **Snippet-level deduplication + conflict resolution**: duplication detection covers content snippets, not just whole documents; conflicting search results are surfaced with a configurable resolution strategy (link / correct / archive / comment-owner) (§2.1, §6.5, §7.5).
- **Journal confidentiality guard**: with `journal.encrypt: false`, confidential-tier snapshots and secrets are never persisted to the journal (§6.7).
- **Archive is platform-native**: archiving is the source platform's own archive operation, not a cross-backend move to kgent (§3.1, §4.3, §6.8, §6.9).
- **Complex query decomposition**: compound queries decompose into sub-queries, fanned out in parallel (§7.4).
- **Router form factor + LLM boundary**: the router is an in-process library and is deterministic; LLM assistance lives in the skill layer (§1.4).
- **CLI primitives vs. skills**: the CLI exposes primitive operations; the judgment-heavy `store` workflow is skill-orchestrated (§1.2, §12).
- **Full config schema reference**: routing-mode behavior table (§4.3) and complete config schema (Appendix C).

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

This document defines the architecture for packaging the kgent knowledge management service through three interface layers: **MCP tools**, **CLI**, and **Skills**. The system supports **federated multi-backend operations** across multiple platforms (Lark/Feishu, DingTalk, WeCom — all with official CLIs; kgent-hosted in a later phase, §1.3) with intelligent routing, capability-aware fallbacks, and human-in-the-loop orchestration.

### Key Design Principles

1. **Federated Multi-Backend**: Operations can target multiple platforms simultaneously. Initial phase: Lark/Feishu, DingTalk, WeCom (official CLIs); kgent-hosted later (§1.3)
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
│  │lark-doc │  │dingtalk- │  │ wecom-   │  │kgent-  │ │
│  │ (skill) │  │   cli    │  │  cli     │  │  cli   │ │
│  └──────────┘  └──────────┘  └──────────┘  └────────┘ │
└─────────────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│                  External Platforms                      │
│  Lark/Feishu  DingTalk  WeCom  kgent-hosted (later)     │
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
- Return a structured routing intent to the agent loop and guide it to the resolved platform skill/CLI (§1.5)
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

### 1.3 Initial Backend Scope

**Initial phase backends** (all have official CLIs; integrated via their platform skill where available, else the CLI — §1.5):

- **Lark / Feishu** (same platform family; integrated via the `lark-doc` skill, `lark-cli` fallback)
- **DingTalk** (CLI)
- **WeCom** (CLI)

The **kgent-hosted backend** is supported in a **later phase**; however, the `kgent` CLI itself is developed in the initial phase because it powers kgent skill setup (`kgent setup`, discovery, config, doctor). Confluence, Notion, Google Docs, and SharePoint are future extensions (§10.1).

### 1.4 Router Form Factor and LLM Boundary

**The router is an in-process library**, not a separate server and not a shell script:

- It ships as a Python package embedded in the `kgent` CLI process and imported by skills/MCP tools. There is **no network hop** between the skills layer and the router — skills call capability interfaces that the router implements locally.
- **The router is deterministic.** Routing precedence (§4.1), policy enforcement (approval §3.4, sensitivity §2.5, journal §6.7, audit §8.4), deduplication, and ranking (§7.3) are pure code — **the router never invokes an LLM**.
- **Smart routing's LLM assistance lives in the skill layer.** Content-type and sensitivity classification (§4.3, §6.3), query decomposition (§7.4), and conflict detection (§7.5) are computed by skills (or the CLI's skill-backed `store` workflow), then passed to the router as *inputs*. The router validates and enforces; it never reasons.
- Skills may call the router's deterministic `resolve_backends()` and policy checks directly; classification results always appear in the write proposal and are user-correctable (§5.6).
- The router's primary interface is `resolve_intent(...) → RoutingIntent` (§1.5): it returns structured intent the agent loop consumes, rather than only executing operations itself.

### 1.5 Routing Intent (Router → Agent Loop)

The router does not only execute; it also **returns a structured intent** to the agent loop, which the agent uses to invoke the resolved platform skill or CLI.

- **Adapter preference**: when a backend has both a platform skill (e.g., `lark-doc`) and an official CLI, the router resolves the **platform skill** when it satisfies the required capabilities, otherwise the CLI. The resolved adapter is named explicitly in the intent.
- **`RoutingIntent`** (structured data):

```python
RoutingIntent:
  operation: str                    # create | update | delete | archive | unarchive | read | search
  doc_uri: str | None               # canonical URI (§3.6) for single-document ops
  query: str | None                 # for search
  targets: list[BackendResolution]  # resolved backends + adapters
  proposal: WriteProposal | None    # for writes (§5.6)
  policy_gates: list[PolicyGate]    # approval (§3.4), sensitivity (§2.5), journal/audit — enforced
  provenance: dict[str, str]        # which source decided each field (§5.3)

BackendResolution:
  backend: str                      # e.g. "lark"
  adapter_type: str                 # skill | cli | mcp (§1.2)
  adapter_name: str                 # e.g. "lark-doc" or "lark-cli"
  capabilities_needed: list[str]    # e.g. ["document_storage.update"]
```

- The agent loop consumes the intent and invokes the named platform skill/CLI; the router still **enforces** policy gates around any write (approval, sensitivity, journal, audit — §1.2). Enforcement is never delegated to the agent.
- `kgent --dry-run` and `kgent config show-effective` expose the same intent as JSON for scripts (§12).

### 1.6 Skill Packaging and Installation

**Skills are packaged as Claude Code skill files (SKILL.md)**, not just Python modules. Each skill must be deployable to Claude Code's skill directories for natural language invocation.

**Skill file format:**

```yaml
---
name: <skill-name>
description: "<one-line description for Claude Code skill listing>"
metadata:
  requires:
    bins: ["python"]  # or other required executables
---

# Skill Title

<skill instructions, workflow, examples>
```

**Installation:**

Skills are installed by symlinking or copying the skill directory to Claude Code's skill directory:

```bash
# Option 1: User-level installation (recommended)
ln -s $(pwd)/skills/<skill-name> ~/.claude/skills/<skill-name>

# Option 2: Project-level installation
ln -s $(pwd)/skills/<skill-name> .claude/skills/<skill-name>

# Option 3: Copy for distribution
cp -r skills/<skill-name> ~/.claude/skills/
```

**Discovery:**

Claude Code automatically discovers skills in `~/.claude/skills/` and `.claude/skills/` by scanning for SKILL.md files. Skills are available for natural language invocation based on their `description` field.

### 1.7 Native URL Presentation

**Canonical URIs (kgent://...) are internal only.** Skills MUST convert canonical URIs to native platform URLs when presenting results to users.

**URL conversion:**

The URL path must match the node type (§7.2 `node_type`). Using the wrong path produces a broken link.

- **Lark docs**: `kgent://lark/<token>` → `https://<workspace_domain>/docx/<token>`
- **Lark wiki nodes**: `kgent://lark/<node_token>` → `https://<workspace_domain>/wiki/<node_token>`
- **DingTalk**: `kgent://dingtalk/<id>` → `https://<workspace_domain>/...`
- **WeCom**: `kgent://wecom/<id>` → `https://<workspace_domain>/...`

**Workspace domain configuration:**

The workspace domain is configured in `~/.kgent/config.yaml`:

```yaml
defaults:
  workspace_domain: "mycompany.larksuite.com"
```

Skills read this config to construct native URLs. If not configured, skills prompt the user to set it.

**User-facing output:**

All skill confirmations, citations, and results display native URLs, never canonical URIs:

```
✅ Created document: https://mycompany.larksuite.com/docx/abc123
```

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
  routing_mode: configured  # explicit | configured | smart (behaviors: §4.3; full schema: Appendix C)
  default_backends: [lark, kgent]
  approval_ttl_hours: 24    # platform approval expiry (§3.4)
  timeouts:
    search_seconds: 10      # per-backend search timeout (§7.1)
    write_seconds: 30       # per-backend write timeout
  concurrency:
    max_parallel_backends: 4

# Backend configurations
backends:
  lark:            # Lark / Feishu (same platform family)
    enabled: true
    type: skill    # skill | cli | mcp (see §1.2 adapter semantics)
    skill_name: lark-doc
    # Platform skill preferred (§1.5); CLI alternative is lark-cli.

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
          - archive        # platform-native archive (§6.8)
          - unarchive

      document_search:
        supported: true
        features:
          search_by_keywords: true
          search_by_semantics: true   # "semantic" == vector similarity
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
          - archive
          - unarchive

      document_search:
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

  wecom:
    enabled: true
    type: cli
    cli_name: wecom-cli
    trust_zone: external

    capabilities:
      document_storage:
        supported: true
        features:
          - create
          - read
          - update
          - delete
          - archive
          - unarchive

      document_search:
        supported: true
        features:
          search_by_keywords: true
          search_by_semantics: false
          search_hybrid: false
        fallback:
          search_by_semantics: search_by_keywords
        limits:
          max_results: 50
        defaults:
          similarity_threshold: 0.6

      approval_flow:
        supported: false

    content_types:
      - external_docs
    priority: 3

  kgent:
    enabled: false       # future phase (§1.3)
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
          - archive
          - unarchive

      document_search:
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
      - research_papers
    priority: 9

# Smart routing rules (when routing_mode: smart).
# Precedence with content_type_mapping and default_backends: §4.1.
routing_rules:
  - match:
      content_type: meeting_notes
      tags: [internal]
    backends: [lark]

  - match:
      content_type: external_docs
    backends: [dingtalk, wecom]

  # `older_than` applies ONLY to archive selection (`kgent archive`),
  # never at store time (§4.3). Archiving is platform-native (§6.8):
  # matched documents are archived on their own source backend, so no
  # `backends` target is set here.
  - match:
      operation: archive
      older_than: 90d

  - default: [lark]

# Content type mapping (used in configured mode; §4.1 precedence).
# Each content type resolves to exactly ONE write target (no replicas — v1.2).
content_type_mapping:
  meeting_notes: lark
  team_wiki: lark
  external_docs: dingtalk
  research_papers: kgent    # future phase (§1.3)
  default: lark

# Conflict resolution (§7.5): when search results contradict each other,
# kgent surfaces the conflict and recommends a resolution strategy.
conflict_resolution:
  enabled: true
  strategies: [link, comment, archive, correct]   # preference order
  require_confirmation: true                       # never act without a confirmed proposal (§5.6)

# Write journal (§6.7)
journal:
  retention_days: 30
  encrypt: false            # opt-in encryption at rest; confidential snapshots require it (§6.7)

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
   - Scan `~/.claude/skills/` for `lark-*`, `dingtalk-*`, `wecom-*`, etc.
   - Read skill *manifest metadata* (not arbitrary doc prose) to extract capabilities
   - Probe with read-only operations only

2. **Discover available CLIs**
   - Check PATH for `dingtalk-cli`, `wecom-cli`, and `lark-cli` (Lark's CLI fallback when the skill is unavailable, §1.5)
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

5. **Defer authentication (no prompts during discovery)**
   - Discovery never authenticates and never prompts for credentials.
   - Credentials are established lazily, at the first invocation that needs them (CLI call or API) (§2.4), and stored in the OS secret store — never in config files.

**Setup Output Example:**

```
$ kgent-setup

🔍 Detecting available backends (read-only probes)...

✅ Found Lark skill (lark-doc)
   Capabilities (verified):
   - document_storage: ✅ (create, read, update, delete, list, archive, unarchive)
   - document_search: ✅ (keyword ✅, semantic ✅, hybrid ✅)
   - approval_flow: ✅ (request, check, execute)
   Auth: deferred (checked on first use)
   Note: lark-cli also available; platform skill preferred (§1.5)

✅ Found DingTalk CLI (dingtalk-cli v1.2.3)
   Capabilities (verified):
   - document_storage: ✅ (create, read, update, delete, archive, unarchive)
   - document_search: ⚠️ (keyword ✅, semantic ❌, hybrid ❌)
     → Semantic search will fallback to keyword search
   - approval_flow: ❌ not available
   Auth: deferred (checked on first use)

✅ Found WeCom CLI (wecom-cli v1.0.4)
   Capabilities (verified):
   - document_storage: ✅ (create, read, update, delete, archive, unarchive)
   - document_search: ⚠️ (keyword ✅, semantic ❌, hybrid ❌)
   - approval_flow: ❌ not available
   Auth: deferred (checked on first use)

✅ Found kgent MCP server (https://kgent.example.com/mcp)
   TLS: ✅ verified, identity pinned
   Capabilities (verified):
   - document_storage: ✅ (create, read, update, delete, list, archive, unarchive)
   - document_search: ✅ (keyword ✅, semantic ✅, hybrid ✅)
   - approval_flow: ✅ (request, check, execute)
   Auth: deferred (checked on first use)

📝 Generated config: ~/.kgent/config.yaml
   - 4 backends detected (kgent-hosted: future phase, §1.3)
   - Capabilities cached to ~/.kgent/capabilities.cache.yaml
   - Auth deferred to first use; please review and enable desired backends

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
- Auth state is runtime-only: `kgent auth status` queries each backend live. Stale-state failure modes surface as actionable errors (`wecom-cli auth` hint), never as silent success.
- Tokens are requested with the **minimum scopes** needed for declared capabilities (e.g., read scopes for search-only backends).
- The router re-checks auth lazily before writes; an expired token aborts that backend's write and is reported per-backend (§8.2) — it never silently falls back to a different backend for a write without user confirmation (§8.3).
- **Discovery never authenticates.** `kgent setup` runs read-only probes and defers all auth to first invocation (§2.2); `kgent auth login` is the only interactive path that prompts for credentials.
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

### 2.6 Config Versioning, Validation, and `kgent doctor`

- `version` is required and validated. Unknown future versions are rejected with a pointer to `kgent config migrate`.
- `kgent config migrate` upgrades older versions in place, writing a timestamped backup (`config.yaml.bak-<ts>`) first.
- Schema validation errors name the exact key and expected type.
- **`kgent doctor`** validates the full config file and the local environment, non-interactively: schema + version, forbidden project-local keys (§2.3), trust records, backend declarations (zone/floor/capability consistency), capability-cache freshness (§3.5), and backend reachability via read-only probes. It performs **no writes and no auth prompts** (§2.2) and reports findings with exit codes (0 healthy, 1 findings). This is the first thing to run when routing or writes misbehave.

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
- archive_document(doc_uri: str, approval_token: str | None,
                   idempotency_key: str) → success          # platform-native archive (§6.8)
- unarchive_document(doc_uri: str, approval_token: str | None,
                     idempotency_key: str) → success        # restore from platform archive (§6.8)
- list_documents(filters: FilterSpec, limit: int) → list[DocumentMetadata]
```

**document_search:**
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
    # capabilities.document_search.defaults.similarity_threshold.
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

  document_search:
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
        caps = backend.capabilities.document_search

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
  kgent://lark/docxABC123        # flat doc (Drive)
  kgent://lark/wikiXYZ789        # wiki node (knowledge space) — §6.10
  kgent://kgent/kb_9f8e7d
```

- Adapters translate URI ↔ native ID at the boundary.
- A URI's backend-native-id identifies the node type implicitly; search results and reads carry an explicit `node_type` (`doc` | `wiki_node`) so consumers don't parse tokens.
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

`RoutingIntent` and `BackendResolution` — the router's structured output to the agent loop — are defined in §1.5.

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
kgent search --backends lark --query "Z"
```

**Configured (default)** — uses precedence step 3 then 4:

```bash
kgent store --title "X" --file body.md
```

**Smart** — precedence step 2: rules match on *operation, declared content_type, and tags*.

**Routing-mode behavior summary:**

| Mode | Selection path (§4.1) | Needs classification? | Typical use |
|---|---|---|---|
| `explicit` | step 1 only (`--backends`) | no | scripts, one-off targets |
| `configured` | step 3 then 4 (mapping → defaults) | no (content_type from user/metadata) | deterministic day-to-day writes |
| `smart` | step 2 (rules), then 3/4 fallback | yes (LLM-assisted, shown in proposal) | assistant-driven routing |

Note on `older_than`: rules with `older_than` apply only to `kgent archive` — which archives documents on their **own source platform** (§6.8) — never to `store`, since age is unknowable for new content. Age is measured from `metadata.updated_at` (last activity), not `created_at` — an old document that was recently edited is still active and not eligible for archiving. `analyze_content_type()` is LLM-assisted and therefore **best-effort**: the inferred `content_type` and `sensitivity` are always shown in the write proposal (§5.6) and can be corrected before confirming. A misclassification can be caught at confirmation time; nothing routes on classification alone without that checkpoint.

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
$ kgent store --backends lark,dingtalk,wecom --title "X" --file body.md
✅ Stored to Lark:      kgent://lark/docxABC123
✅ Stored to DingTalk:  kgent://dingtalk/d_456
❌ Failed on WeCom: Authentication expired
   → Run `wecom-cli auth` to re-authenticate
   → Repair: `kgent sync --repair op-20260826-01`
(op id: op-20260826-01 — journaled for retry/undo)
```

All legs of a multi-backend write share one **idempotency key** (op id); retrying a failed leg will not duplicate content on backends that already succeeded (§6.6).

**Cancellation.** Interrupting a multi-backend operation aborts unstarted legs; legs already written stay written and are journaled (`status: partial`). There is no rollback of completed legs — repair is `kgent sync --status` (§6.6) and reversal is `kgent undo` (§6.7).

### 6.5 Deduplication Strategy

Two layers:

1. **Exact fingerprint** (hash of normalized title+content) stored in backend metadata and in `~/.kgent/idmap.json`; catches byte-identical copies and powers `also_available_in`.
2. **Near-duplicate detection** for everything else: title-similarity (edit distance/embedding) + structural similarity, run at search-aggregation time (§7.2) and in update-first lookups (§6.1). Near-duplicate clusters are shown grouped with per-member provenance; no automatic merging — merging is always a confirmed user action.
3. **Snippet-level duplication**: duplication is not limited to whole documents — two documents (or two passages within documents) can duplicate each other only in part. Snippet-level matching compares content fragments (paragraphs/sections) in addition to whole-document fingerprints, so a copy-pasted section is flagged as related even when the surrounding documents differ. Snippet matches are shown as "overlapping content" in the proposal, never auto-merged.

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
- **Encryption at rest is opt-in**: `journal.encrypt: true` encrypts snapshots with a key held in the OS secret store (§2.4). Default is `false` (favoring recoverability).
- **Confidentiality guard**: when `journal.encrypt: false`, `confidential`-tier snapshot bodies and any secret/credential material are **never persisted** to the journal. The write is still journaled, but the entry omits the `snapshot.content_before` body (metadata only), undo of confidential content is unavailable, and the proposal states this and recommends enabling encryption. Secrets never enter the journal regardless of the encryption setting.
- `kgent undo <op-id>` restores the snapshotted state on every target of that operation (best-effort across backends, with the same per-backend reporting as §6.4).
- Journal entries also drive `kgent sync` (§6.6) and feed the audit log (§8.4).

### 6.8 DELETE Flow (Archive-First, Platform-Native)

Delete is first-class, and **archive-first: archiving is the source platform's own archive operation — the document stays on its platform, in an archived state.** It is **not** a cross-backend move to kgent.

**Archive availability.** Archiving is *available* for a document when its source backend supports `archive_document` (§3.1). A backend without archive support (or with no archive/trash concept) offers hard delete only.

```python
async def handle_delete(doc_uri):
    doc = await read_document(doc_uri)
    can_archive = backend_supports(doc.backend, "archive_document")

    return propose_delete(
        target=doc_uri,
        archive_recommended=can_archive,  # recommended option when supported
        snapshot=True,                    # content snapshotted pre-delete (§6.7)
        approval=approval_required(doc_uri), # §3.4 gate
    )
```

```
$ kgent delete kgent://lark/docxAAA

┌─────────────────────────────────────────────────┐
│ Delete "API Design Guidelines v1" (Lark)?       │
│                                                 │
│ [a] Archive on Lark (RECOMMENDED)               │
│     Marks it archived on Lark (kept on-platform,│
│     recoverable via kgent unarchive)            │
│ [b] Hard delete from Lark                       │
│ [c] Cancel                                      │
└─────────────────────────────────────────────────┘
```

**Archive is a single platform operation, journaled.** Option [a] (or `kgent archive` directly) invokes the source backend's native `archive_document` under one op id. `kgent undo <op-id>` reverses it via `unarchive_document`, restoring the document to active state on the same platform. Both directions are journaled (§6.7) and audited (§8.4).

```bash
kgent delete kgent://lark/docxAAA            # proposal recommends archive when available
kgent archive kgent://lark/docxAAA           # direct archive; same confirmation + journaling
kgent unarchive kgent://lark/docxAAA         # explicit restore to active
kgent undo <op-id>                           # reverse the archive via journal
```

- When the source backend has no archive support, the proposal falls back to plain hard delete and states why archive was not offered.
- **Bulk archive**: `kgent archive --older-than 90d` selects documents whose `updated_at` is older than the age (§4.3) and archives each on its own source backend; the batch proposal lists every item (§12 rule 8).
- Deleting near-duplicate copies that exist on other backends is never implicit: they are listed in the proposal as "similar documents elsewhere" and deleting any of them requires its own confirmation.
- Deletes and archives are always confirmed (§5.6), snapshotted (§6.7), and audited (§8.4).
- Platform-side trash/retention behavior of each backend is surfaced in the proposal where known ("Lark moves this to trash for 30 days").
- **Undo safety**: `kgent undo` of an archive first verifies the archived document is unchanged (fingerprint matches what the archive recorded). If it was edited while archived, undo aborts for that document and asks the user to choose — keep the edited archived version, or force-restore. Post-archive edits are never silently discarded.

### 6.9 Content Representation & Fidelity

Cross-backend fan-out (§6.4) changes formats; fidelity loss is declared, never silent:

- **Canonical format**: kgent's interchange format is Markdown body + `DocumentMetadata` sidecar (§3.8). Adapters convert native ↔ canonical at the boundary; `kgent read` returns canonical by default, `--native` fetches the backend-native format.
- **Fidelity classes**: each adapter declares `fidelity: lossless | lossy` per direction (e.g., lark → canonical is lossy for embeds, votes, comment threads).
- **Warn on lossy paths**: when a write/fan-out traverses a lossy conversion, the proposal lists what will degrade ("3 elements have no Markdown equivalent: vote block, diagram, comment thread") and requires confirmation like any other write.
- **Fan-out fidelity**: multi-backend fan-out (§6.4) still converts native ↔ canonical across backends; lossy directions are warned and confirmed. Platform-native archive (§6.8) never converts — the document stays in its native format on its own platform, so archive/undo is inherently lossless.
- **Never fabricate, never silently drop**: conversions must not invent content; unsupported elements become explicit placeholders (`[unsupported: vote block]`) that the user sees in the proposal diff.

### 6.10 Wiki (Knowledge Space) Node Operations

Backends with a knowledge-base product (e.g., Lark Wiki) expose a second document kind: **wiki nodes** — hierarchical pages inside a knowledge space, with space-level permissions, as distinct from flat docs in Drive. kgent treats wiki nodes as first-class write/search targets through the same primitives.

**Creation:**

```bash
# wiki node in a space (hierarchical)
kgent create --title T --content C --backends lark --wiki-space <space_id> \
             [--parent-node-token <parent>] --yes --json

# flat doc in Drive (unchanged behavior)
kgent create --title T --content C --backends lark --yes --json
```

- `--wiki-space` routes the create to a wiki node; without it, the create is a flat doc.
- `--parent-node-token` places the node under an existing parent; omitted → space root.
- The JSON output carries the created `node_token` (for native URL construction, §1.7) and the node's position (space, parent).

**Updates keep position.** Updating a wiki node URI (`kgent update kgent://lark/wikiXYZ789`) modifies content in place — the node never moves within the hierarchy as a side effect of an update. Moving a node is a separate, confirmed operation (platform-native move, treated like other writes: proposed, journaled, undoable).

**Space management primitives:**

```bash
kgent wiki spaces list   [--backends SEL] [--json]   # spaces accessible to the user
kgent wiki spaces create --name N [--backends SEL] [--yes] [--json]
```

Space list/create are primitives; choosing *which* space and *where in the hierarchy* a node belongs is skill-layer judgment (§5.2).

**Skill-layer placement rules (normative for skills):**

1. Skills inspect the space structure before proposing a create; a new node is proposed under a **topically-fitting parent**, not silently at the space root.
2. **Parent tokens are never guessed** — only tokens returned by search or space listing are used. If no fitting parent is found, the skill places the node at the root and says so in the proposal.
3. The proposed parent is shown in the proposal so the user can correct it before execution.
4. **Wiki vs doc preference** (§5.2): when all other resolution factors are equal (no explicit user mention, no match dictating the target, no config preference), the skill asks the user wiki-node vs flat-doc rather than silently choosing. Provenance records which factor determined the target when it was not asked.

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

**Search covers wiki nodes and flat docs by default** (§6.10). A single `kgent search` fans out across backends and returns both kinds; results carry an explicit `node_type` field:

```json
{
  "doc_uri": "kgent://lark/wikiXYZ789",
  "title": "Deploy Runbook",
  "node_type": "wiki_node",
  "space_id": "7123456",
  "parent_node_token": "wikiAAA",
  "snippet": "…",
  "content_fingerprint": "…"
}
```

Flat docs carry `node_type: "doc"` (no space/parent fields). Consumers (skills, QA citation rendering, §1.7 URL conversion) use `node_type` to pick the correct native-URL path — they never parse tokens to infer type. Wiki hits rank by the same position-based fusion as docs (§7.3); node kind is not a ranking input.

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

### 7.4 Complex Query Decomposition

A compound query ("what changed in the onboarding policy and where is it referenced?") is decomposed into simpler sub-queries by the skill layer (LLM-assisted), each answerable by a single backend search:

```python
sub_queries = decompose_query(query)          # skill layer, LLM-assisted
# e.g. ["onboarding policy changes", "onboarding policy references"]

# Sub-queries fan out in parallel for speed; each respects §7.1 timeouts
results_by_subquery = await asyncio.gather(*[
    search_knowledge(sub, backends=backends, mode=mode)
    for sub in sub_queries
])
```

- Decomposition happens **only for queries that are genuinely compound**; simple queries are searched as-is.
- Each sub-query result set is ranked independently (§7.3) and returned grouped by sub-query so the skill can answer each part and cite sources; no cross-sub-query fusion that would obscure provenance.
- Decomposition is shown to the user ("searching 3 sub-queries: …") — transparent, never hidden.

### 7.5 Conflict Detection and Resolution

Search results — including snippet-level matches (§6.5) — can contradict each other (two documents stating different current owners, duplicated-but-diverged copies, stale vs. fresh versions). kgent **surfaces the conflict and asks for a resolution decision**; it never silently picks one.

- **Detection**: during aggregation (§7.2), the skill compares results and flags contradictions: same fingerprint with different content (diverged), overlapping snippets with conflicting facts, or `stale` results contradicting live ones (§8.6).
- **Recommendation**: for each conflict, kgent recommends a resolution strategy, in config preference order (§2.1 `conflict_resolution.strategies`):
  - `link` — cross-reference the documents instead of choosing one;
  - `correct` — propose an update to reconcile them (goes through the write proposal §5.6);
  - `archive` — propose archiving the superseded copy (§6.8);
  - `comment` — leave a comment for the document owner on the platform.
- **Always confirmed**: no resolution action executes without a user-confirmed proposal (§5.6); `conflict_resolution.require_confirmation: true` is the default and may not be disabled silently.

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
$ kgent store --backends lark,dingtalk,wecom --title "X" --file body.md

✅ Stored to Lark:      kgent://lark/docxABC123
✅ Stored to DingTalk:  kgent://dingtalk/d_456
❌ Failed on WeCom: Authentication expired
   → Run `wecom-cli auth` to re-authenticate
   → Repair: `kgent sync --repair op-20260826-01`
(op id: op-20260826-01)
```

### 8.3 Fallback Chains

```yaml
fallback_chains:
  document_storage:
    preferred: lark
    fallbacks: [dingtalk, wecom]

  document_search:
    preferred: lark
    fallbacks: [dingtalk]
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
- Backend query languages (Lark/DingTalk/WeCom search syntax, filter DSLs) are built with parameterization/escaping only — raw interpolation of user query strings is forbidden.

### 8.6 Read-Path Staleness

Search indexes lie: documents get deleted or moved externally, and permissions get revoked.

- **Verify before proposing**: update-first (§6.2), delete/archive (§6.8), and undo targets are re-read immediately before the proposal is built. Search snippets alone are never sufficient basis for a write proposal.
- **Classified read failures**: `not_found` → the URI is marked `stale` in the idmap (§3.6) and excluded from update-first candidates until rediscovered; `permission_denied` → actionable error with the platform's access-request path; neither is retried.
- **Search results**: verification failures set `SearchResult.access` to `denied`/`stale` (§3.8); such results are demoted and visibly flagged, never silently dropped.
- **Bulk staleness**: if more than 20% of a backend's results fail verification, the router refreshes that backend's capability cache (§3.5) and warns.

---

## 9. Implementation Plan

### Phase 1: Core Infrastructure

1. **Capability Router Layer** (in-process library, §1.4)
   - Capability interfaces with canonical URIs (§3.6) and core data schemas (§3.8)
   - Backend registry, config loading + trust model (§2.3)
   - Single routing precedence chain (§4.1)
   - Policy enforcement points: approval gate (§3.4), sensitivity rules (§2.5), write journal (§6.7), audit log (§8.4), optimistic concurrency (§3.9)

2. **Backend Adapters** (initial phase, §1.3)
   - `lark-doc` skill adapter (preferred) with `lark-cli` fallback; `dingtalk-cli`, `wecom-cli` adapters
   - Adapter contract incl. argv safety, timeouts, error normalization (§1.2, §8.5), fidelity classes (§6.9)
   - kgent-hosted MCP adapter in a later phase

3. **Configuration System**
   - Schema + validation + migration + `kgent doctor` (§2.6)
   - OS secret store integration + lazy auth (§2.4)
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
   - Complex query decomposition (§7.4)
   - Conflict detection & resolution (§7.5)
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
   - Fingerprint index + near-duplicate + snippet-level detection (§6.5)
   - `kgent sync` repair workflows (§6.6)
   - Undo via write journal (§6.7)
   - Content fidelity conversion for fan-out (§6.9)

9. **Monitoring & Observability**
   - Audit log tooling (§8.4)
   - Backend health checks, capability-cache staleness reports
   - Performance metrics (p95 per-backend latency, partial-result rates)
   - Privacy guarantee: metrics are local-only — no content, queries, or document URIs leave the machine

---

## 10. Future Extensions

### 10.1 Additional Backends

Easy to add new backends by implementing capability interfaces:

- **Confluence**: `confluence-cli` adapter
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
10. **Zero archive data loss**: platform-native archive fault injection (fail the archive op mid-flight) never loses content — a failed archive leaves the document active, and hard delete is only ever proposed separately (§6.8).
11. **No silent fidelity loss**: every lossy cross-backend conversion is warned and confirmed in the proposal (§6.9); measured across the adapter conformance suite.

---

## 12. CLI Surface

All commands support a common flag set; behaviors below are normative.

```bash
# Primitive operations (one capability call each; skills orchestrate the
# judgment-heavy workflows — §1.2, §1.4)
kgent create  [--title T] (--file F | --stdin | --content C)
              [--backends SEL] [--content-type CT] [--sensitivity S]
              [--wiki-space SPACE_ID] [--parent-node-token TOKEN]   # §6.10
              [--dry-run] [--yes] [--json]

kgent update  <doc-uri> [--file F | --stdin | --content C]
              [--expected-version V] [--yes] [--json]
              # wiki node URIs update in place; position never changes (§6.10)

kgent wiki    spaces list [--backends SEL] [--json]
              spaces create --name N [--backends SEL] [--yes] [--json]

# `store` is the skill-backed convenience command: it performs the
# update-first search ("does this knowledge already exist?"), then proposes
# create or update (§6.1). It runs the same workflow as the
# knowledge-storage skill, exposed for interactive/scripted CLI use.
kgent store   [--title T] (--file F | --stdin | --content C)
              [--backends SEL] [--content-type CT] [--sensitivity S]
              [--routing explicit|configured|smart]
              [--dry-run] [--yes] [--json]

kgent search  --query Q [--backends SEL] [--mode keyword|semantic|hybrid]
              [--top-k N] [--stream] [--json]

kgent read    <doc-uri> [--native] [--json]
kgent delete  <doc-uri> [--yes] [--json]
kgent archive <doc-uri|--older-than 90d> [--json]
              # platform-native archive (§6.8); --older-than measured on updated_at (§4.3)
kgent unarchive <doc-uri> [--json]     # restore an archived doc to active (§6.8)

kgent sync    --status | --repair <op-id> | --repair-all
kgent undo    <op-id>
kgent audit   [--since 7d] [--op read|write|delete] [--json]
kgent auth    status | login <backend> | logout <backend>
kgent setup   [--read-only]          # §2.2 discovery, read-only, no auth prompts
kgent trust   [--revoke]             # §2.3 project-config trust
kgent doctor  [--json]               # config + environment health check (§2.6)
kgent config  validate | migrate | show-effective [--json]
```

**Primitive vs. skill.** The CLI exposes *primitive* operations (create/update/read/search/delete/archive/unarchive/undo/sync/audit/auth/doctor/config/setup/trust) that map 1:1 to capability calls. `kgent store` is the one *judgment-heavy* convenience command: deciding "does this knowledge already exist?" requires agent judgment, so `store` runs the same workflow as the knowledge-storage skill (search → update-first proposal → confirm, §6.1) and is a thin CLI entry point into it. Skills perform the orchestration and invoke primitives (§1.4).

**Rules:**

1. **Content input**: long content goes via `--file` or `--stdin`; `--content` exists but is not required for any flow. Nothing ever requires shell-quoting large bodies.
2. **`--dry-run`**: resolves routing, runs duplicate/update-first lookup, and prints the exact proposal that would be shown — then exits without any write or journal entry.
3. **`--yes`**: bypasses interactive confirmation ONLY when combined with explicit `--backends` and fully-specified content; ignored (with warning) in interactive/TTY sessions invoked through skills. It never bypasses platform approval gates (§3.4). Every `--yes` write is still journaled and audited with `confirmation: "--yes"`.
4. **`--json`**: stable machine-readable output (schema-versioned) for every command; success/failure is also reflected in exit codes (0 = ok, 2 = partial success, 1 = failure, 3 = rejected by policy, 4 = version conflict §3.9).
5. **Doc URIs**: all commands accepting documents take canonical URIs (§3.6); bare native IDs are rejected with a hint, not guessed.
6. **Idempotency**: `store`/`update`/`delete` accept `--op-id` to reuse an existing operation id (safe retries, §6.6); omitted → new op id generated and printed.
7. **Archive-first delete**: `kgent delete` always presents archive as the recommended option when the source backend supports native archiving (§6.8); hard delete remains an explicit choice. `kgent archive` performs the same confirmed, journaled platform-native archive directly.
8. **Batch operations & cancellation**: multi-document operations (`kgent archive --older-than`, any bulk selector) show one batch proposal — count, per-document targets, total size — and one confirmation covers the batch; `--dry-run` lists every item; each item is individually journaled and undoable. Interrupting a running operation aborts unstarted legs; completed legs stay journaled (`status: partial`) and are inspectable via `kgent sync --status` — nothing is silently rolled back (§6.4).
9. **Wiki flags are backend-conditional** (§6.10): `--wiki-space`/`--parent-node-token` are rejected with a clear error on backends without a knowledge-space product (dingtalk, wecom in the initial scope), and `kgent wiki spaces …` lists only backends that have one. Wiki node writes are journaled, undoable, and sensitivity-gated exactly like doc writes.

---

## Appendix A: Glossary

- **Backend**: A platform or service that provides knowledge management capabilities (Lark/Feishu, DingTalk, WeCom initially; kgent-hosted later)
- **Capability**: A specific feature or operation (document_storage, document_search, approval_flow)
- **Skill**: An orchestration layer that coordinates complex workflows using capabilities
- **Router**: Middleware that routes operations to appropriate backends and *enforces* policy gates (approval, sensitivity, journaling, audit)
- **Routing Mode**: How backends are selected (explicit, configured, smart) — single precedence chain, §4.1
- **Canonical URI**: `kgent://<backend>/<native-id>` — the only identifier form that crosses adapter boundaries
- **Write Journal**: Append-only local record of executed writes, enabling `kgent sync`, `kgent undo`, and audit
- **Trust Zone**: Backend classification (`internal`/`external`) used by the data-leakage policy (§2.5)
- **Proposal**: A fully-specified, user-confirmable plan for a write operation; the mandatory precursor to execution
- **Canonical Format**: Markdown body + `DocumentMetadata` sidecar — kgent's interchange representation; adapters convert native ↔ canonical at boundaries (§6.9)
- **Archive**: The source platform's native archive operation — a document is marked archived and kept on-platform, reversible via `kgent unarchive` (§6.8)
- **Optimistic Concurrency**: `expected_version` checks ensuring updates never clobber external edits; conflicts re-propose instead (§3.9)
- **Approval TTL**: Approvals expire (`expires_at`); expired approvals are treated as rejected (§3.4)

---

## Appendix B: Configuration Examples

### Minimal Config (Single Backend)

```yaml
version: 1
defaults:
  routing_mode: configured
  default_backends: [lark]

backends:
  lark:
    enabled: true
    type: skill
    skill_name: lark-doc     # platform skill preferred (§1.5)
    trust_zone: internal
    capabilities:
      document_storage:
        supported: true
      document_search:
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
    skill_name: lark-doc     # platform skill preferred (§1.5)
    trust_zone: internal
    capabilities:
      document_storage: {supported: true}
      document_search:
        supported: true
        features:
          search_by_keywords: true
          search_by_semantics: true
          search_hybrid: true
    content_types: [internal_docs, meeting_notes]

  dingtalk:
    enabled: true
    type: cli
    cli_name: dingtalk-cli
    trust_zone: external
    capabilities:
      document_storage: {supported: true}
      document_search: {supported: true}
    content_types: [external_docs]

routing_rules:
  - match:
      content_type: meeting_notes
    backends: [lark]

  - match:
      operation: archive       # platform-native archive selection (§4.3, §6.8)
      older_than: 90d

  - default: [lark, dingtalk]

audit:
  enabled: true
  redact_queries: true
```

---

## Appendix C: Complete Configuration Schema Reference

Full schema for `version: 1`. Type, default, and allowed values. Unknown top-level keys are rejected (§2.3, §8.5); future `version` values are rejected with a migrate hint (§2.6).

### Top level

| Key | Type | Default | Notes |
|---|---|---|---|
| `version` | int | required | must be `1`; future versions rejected (§2.6) |
| `defaults` | object | — | global defaults |
| `backends` | object (name → backend) | required | backend declarations |
| `routing_rules` | list | `[]` | smart-routing rules (§4.3) |
| `content_type_mapping` | object | `{}` | configured-mode mapping (§4.1) |
| `sensitivity_floors` | object | `{}` | per-content_type minimum tier (§2.5) |
| `fallback_chains` | object | `{}` | failure fallbacks (§8.3) |
| `conflict_resolution` | object | see below | conflict handling (§7.5) |
| `journal` | object | see below | write journal (§6.7) |
| `audit` | object | see below | audit log (§8.4) |

### `defaults`

| Key | Type | Default | Allowed |
|---|---|---|---|
| `routing_mode` | string | `configured` | `explicit` \| `configured` \| `smart` (§4.3) |
| `default_backends` | list[string] | `[]` | enabled backend names (§4.2 grammar) |
| `workspace_domain` | string | `""` | platform workspace domain for native URL construction (§1.7) |
| `approval_ttl_hours` | int | 24 | > 0 (§3.4) |
| `timeouts.search_seconds` | int | 10 | > 0 (§7.1) |
| `timeouts.write_seconds` | int | 30 | > 0 |
| `concurrency.max_parallel_backends` | int | 4 | ≥ 1 (§7.1) |

### `backends.<name>`

| Key | Type | Default | Notes |
|---|---|---|---|
| `enabled` | bool | `false` | disabled backends are never selected |
| `type` | string | required | `skill` \| `cli` \| `mcp` (§1.2) |
| `skill_name` / `cli_name` / `mcp_url` | string | per type | target-selection fields; forbidden in project-local config (§2.3) |
| `trust_zone` | string | `external` | `internal` \| `external`; new backends default external (§10.1) |
| `capabilities` | object | runtime-detected | overrides only narrow detection (§3.5) |
| `content_types` | list[string] | `[]` | declared document kinds |
| `priority` | int | — | ranking tiebreaker only (§7.3) |

`capabilities` sub-objects: `document_storage` (features incl. `archive`/`unarchive`, §3.1), `document_search` (features `search_by_keywords`/`search_by_semantics`/`search_hybrid`, `fallback` sibling, `limits`, `defaults`, §3.2), `approval_flow` (§3.4). `fallback` is a sibling of `features`, never nested (§3.2).

### `journal`

| Key | Type | Default | Notes |
|---|---|---|---|
| `retention_days` | int | 30 | snapshot retention (§6.7) |
| `encrypt` | bool | `false` | confidential snapshots require `true` (§6.7) |

### `audit`

| Key | Type | Default | Notes |
|---|---|---|---|
| `enabled` | bool | `true` | §8.4 |
| `path` | string | `~/.kgent/audit.ndjson` | §8.4 |
| `redact_queries` | bool | `true` | opt-out with warning (§8.4) |

### `conflict_resolution`

| Key | Type | Default | Notes |
|---|---|---|---|
| `enabled` | bool | `true` | §7.5 |
| `strategies` | list[string] | `[link, comment, archive, correct]` | preference order; values from §7.5 |
| `require_confirmation` | bool | `true` | resolution always via confirmed proposal (§5.6) |

### Routing-mode behavior

| Mode | Selection path (§4.1) | Needs classification? | Typical use |
|---|---|---|---|
| `explicit` | step 1 only (`--backends`) | no | scripts, one-off targets |
| `configured` | step 3 then 4 (mapping → defaults) | no | deterministic day-to-day writes |
| `smart` | step 2 (rules), then 3/4 fallback | yes (LLM-assisted, shown in proposal) | assistant-driven routing |

---

**End of Specification**
