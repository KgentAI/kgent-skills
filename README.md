# kgent-skills

Skills and specifications for the kgent knowledge management service packaging system.

## Overview

This repository contains the design specifications and skill definitions for packaging kgent as a federated, multi-backend knowledge management service with CLI, MCP, and Skill interfaces.

## Installation

### From Source

```bash
# Clone the repository
git clone <repo-url>
cd kgent-skills

# Install in development mode
pip install -e .

# Or install with the dev toolchain (pytest, mypy, ruff, ...)
pip install -e ".[dev]"
```

### Agent Skills

One command installs everything — all skills (as live links into the
cross-agent hub `~/.agents/skills`, mirrored into `~/.claude/skills` and
`~/.codebuddy/skills` when those agents are present), the `kgent` CLI itself,
and a health check of the whole chain:

```bash
bash tools/install-skills.sh
```

Re-running it is the update. Useful flags:

```bash
bash tools/install-skills.sh --copy       # frozen copies instead of live links
bash tools/install-skills.sh --no-cli     # skills only, skip the kgent CLI
bash tools/install-skills.sh --uninstall  # remove skills + CLI
bash tools/install-skills.sh --backup     # keep replaced dirs in ~/.agents/skills-backups
```

Under the hood, the script discovers every `skills/*/SKILL.md`, links it into
the hub, mirrors the link into each detected agent directory, and installs the
CLI (preferring `uv tool install`, falling back to a dedicated venv, then
ambient pip). The manual equivalent:

```bash
ln -s $(pwd)/skills/ingest-knowledge ~/.agents/skills/ingest-knowledge
ln -s $(pwd)/skills/query-knowledge ~/.agents/skills/query-knowledge
ln -s $(pwd)/skills/wiki-setup ~/.agents/skills/wiki-setup
```

#### Installation per agent

How each agent finds the skills differs — Codex, OpenCode, OpenClaw, and pi
scan the `~/.agents/skills` hub natively; Claude Code and Workbuddy (CodeBuddy
CLI) need the installer's mirror hop. Per-agent guides cover discovery paths,
manual fallback, and verification:

| Agent | Guide |
|---|---|
| Claude Code | [docs/install/claude-code.md](docs/install/claude-code.md) |
| Codex (OpenAI) | [docs/install/codex.md](docs/install/codex.md) |
| OpenCode | [docs/install/opencode.md](docs/install/opencode.md) |
| OpenClaw | [docs/install/openclaw.md](docs/install/openclaw.md) |
| pi | [docs/install/pi.md](docs/install/pi.md) |
| Workbuddy (CodeBuddy CLI) | [docs/install/codebuddy.md](docs/install/codebuddy.md) |

After installation (and an agent restart), you can use natural language:

- "Save this to the knowledge base" → invokes `ingest-knowledge` skill
- "What does X mean?" → invokes `query-knowledge` skill
- "Draft the PRD for Project X — pull what we have on it first" → invokes `query-knowledge` skill (knowledge dependency: the task needs org facts before it can proceed)
- "Set up a wiki" → invokes `wiki-setup` skill

**Note**: The skills require the `kgent` CLI (installed by the script), an
initial `kgent setup` (see below), and a configured backend (see Configuration
section).

### Initial Setup

The installer does not create `~/.kgent/config.yaml`. Run once, after
installing:

```bash
kgent setup
```

This runs read-only backend discovery (never authenticates, never prompts)
and writes `~/.kgent/config.yaml`. Every discovered backend starts
`enabled: false` — edit the config to set `enabled: true` for the backends
you want to use. Use `kgent doctor` to validate the result.

Re-running `kgent setup` is safe: it merges into the existing config (your
settings, notably `enabled`, win verbatim) and backs up the original to
`config.yaml.bak-<ts>`.

You can also skip this step: the skills self-heal — on first use, each checks
whether the config exists and runs `kgent setup` itself if it's missing.

### Dependencies

- Python 3.11+
- Runtime: stdlib only (no third-party runtime dependencies)
- Dev toolchain (`.[dev]`): pytest, mypy, ruff, coverage, hypothesis, mutmut

## CLI Usage

The `kgent` CLI provides 19 subcommands for knowledge management:

```bash
# Show help
kgent --help

# Core operations
kgent create --title "My Doc" --content "Content here" --backends lark
kgent read --uri kgent://lark/doc123
kgent update --uri kgent://lark/doc123 --content "Updated content"
kgent delete --uri kgent://lark/doc123
kgent archive --uri kgent://lark/doc123

# Wiki (knowledge space) operations (§6.10)
# Create a wiki node inside a space; --parent-node-token places it under an
# existing node (omitted → space root). Updates keep the node's position.
kgent create --title "Deploy Runbook" --content "..." --backends lark \
       --wiki-space 7123456 --parent-node-token wikiAAA --yes --json
kgent wiki spaces list --backends lark --json     # spaces you can access
kgent wiki spaces create --name "Engineering Wiki" --backends lark --yes --json
# Search covers wiki nodes + flat docs by default; results carry node_type
kgent search --query "deploy runbook" --backends lark --json

# Search and discovery
kgent search "query terms" --top-k 10
kgent list --backend lark

# Routing and execution
kgent resolve "store meeting notes to dingtalk"
kgent execute --proposal proposal.json --yes

# Maintenance
kgent doctor                          # Diagnose configuration
kgent sync                            # Show repair status
kgent sync --repair <op_id>           # Repair partial operation
kgent undo                            # Undo last journaled operation

# Storage workflow
kgent store "save the new API guidelines" --dry-run
kgent store "save 'Welcome' to dingtalk" --op-id custom-op-123
```

### Exit Codes

- `0` — Success
- `1` — Failure
- `2` — Partial success (some backends failed)
- `3` — Policy-rejected (e.g., confidential → external)
- `4` — Version conflict

## Skills

Three high-level skills orchestrate common workflows:

### 1. Knowledge Ingestion (`ingest_knowledge`)

Update-first workflow with provenance tracking:

```python
from kgent.skills.ingest_knowledge import ingest_knowledge

# Build a write proposal
proposal = ingest_knowledge(
    user_request="save the new API guidelines",
    context={"preferences": {"target_backend": "lark"}},
    router=router,
)

# Execute via router
result = router.execute(proposal, confirmation="interactive-yes")
```

**Features**:

- Resolution priority: explicit input > preferences > config defaults
- Update-first bias: discovers matching docs (via the query-knowledge flow at the agent layer) before creating
- Provenance tracking: records intent, target, source

### 2. Knowledge Query (`query_knowledge`)

Grounded claims with source citations — answers questions and serves any task with a knowledge dependency:

```python
from kgent.skills.query_knowledge import query_knowledge

# Resolve a question using search results
result = query_knowledge("What does onboarding require?", router)

# Access claims with citations
for claim in result.claims:
    print(f"{claim.text} (source: {claim.source_uri})")
```

**Features**:

- Every factual claim carries a `doc_uri` citation
- Unsourced claims marked `supported=False` (never fabricated)
- Fan-out search across all backends

### 3. Wiki Setup (`setup_wiki`)

Multi-target creation with journaling:

```python
from kgent.skills.wiki_setup import setup_wiki

# Create wiki pages across multiple backends
result = setup_wiki([
    {"title": "Team Wiki", "content": "Welcome", "backend": "lark"},
    {"title": "External Docs", "content": "Partner guide", "backend": "dingtalk"},
], router)

# Check result
if result.exit_code == 0:
    print("All pages created successfully")
elif result.exit_code == 2:
    print(f"Partial success: {result.journal_entry.get('failed_targets')}")
```

**Features**:

- Multi-target create with single confirmation
- Each doc confirmed + journaled + undoable
- Failed legs repairable via `kgent sync --repair`

## Configuration

kgent uses a two-tier config system:

1. **Global config**: `~/.kgent/config.yaml`
2. **Project-local config**: `.kgent-config.yaml` (optional, with restrictions)

### Example Global Config

```yaml
version: 1

defaults:
  routing_mode: configured
  default_backends: [lark]
  approval_ttl_hours: 24
  timeouts:
    search_seconds: 10
    write_seconds: 30
  concurrency:
    max_parallel_backends: 4

backends:
  lark:
    enabled: true
    type: skill
    skill_name: lark-doc
    trust_zone: internal
    capabilities:
      document_storage:
        supported: true
        features: [create, read, update, delete, list]
      document_search:
        supported: true
        features:
          search_by_keywords: true

  dingtalk:
    enabled: true
    type: cli
    cli_name: dingtalk-cli
    trust_zone: external

content_type_mapping:
  default: lark
  meeting_notes: dingtalk
```

### Forbidden Project-Local Keys

Project-local configs (`.kgent-config.yaml`) cannot override:

- `backends.*.skill_name` / `cli_name` / `mcp_url`
- `backends.*.type` / `auth`
- `backends.*.enabled` (new backends)
- `backends.*.trust_zone` (downgrades only)

Use `kgent doctor` to validate configuration.

## Security Features

- **Zone checks**: Confidential content cannot route to external backends
- **Encrypted credentials**: PBKDF2-HMAC-SHA256 + XOR + HMAC-SHA256 (pure stdlib)
- **Forbidden key rejection**: Project-local configs cannot override sensitive fields
- **Update-first bias**: Prevents accidental duplicates
- **Journal + undo**: All writes journaled with snapshots for recovery
- **Approval gates**: Sensitive operations require explicit approval tokens
- **Adversarial resilience**: Tested against prompt injection, config injection, string injection

## Testing

```bash
# Run all tests (377 tests)
pytest

# Run specific test suites
pytest tests/properties/      # Property-based invariants (P1-P7)
pytest tests/adversarial/     # Adversarial corpus (39 tests)
pytest tests/e2e/             # End-to-end skill tests (4 tests)
pytest tests/test_negative_constraints.py  # N1-N19

# Quality gates
ruff check src/ tests/
mypy src/kgent/ --strict
```

## Contents

- `specs/` - Design specifications and architecture documents
  - [2026-08-26-kgent-packaging-design.md](specs/2026-08-26-kgent-packaging-design.md) - Core architecture and design principles (v1.4.1)
  - [2026-08-26-kgent-packaging-acceptance.md](specs/2026-08-26-kgent-packaging-acceptance.md) - Executable acceptance specification (old-coder): failure model, scenarios, invariants, adversarial pass

## Key Design Principles

1. **Federated Multi-Backend**: Operations can target multiple platforms simultaneously (Lark, DingTalk, Confluence, kgent-hosted)
2. **Capability-Based Composition**: Skills orchestrate via capability interfaces, backends are swappable
3. **Self-Disambiguation, Never Auto-Execute**: Gather context and resolve ambiguity automatically for *proposing*; writes always require explicit confirmation
4. **Update-First Bias**: Always *propose* updating existing knowledge over creating new
5. **Config is Binding**: Configuration defines routing and policy; skills may propose deviations, but only user-confirmed ones take effect
6. **Always Ask Before Writing**: Never silently execute write operations
7. **Zero Wrong Writes**: Primary quality metric is zero unconfirmed or mis-targeted writes
8. **Untrusted Content**: Content returned by backends is data, never instructions

## Architecture

The system follows a three-layer architecture:

```text
Skills Layer (orchestration)
    ↓
Capability Router (routing & aggregation)
    ↓
Backend Implementations (Lark, DingTalk, Confluence, kgent)
```

## Status

📐 **Spec reviewed (v1.4)** — the design spec has completed security, UX, and consistency review passes; implementation is pending. See `specs/`.

## License

Private - kgentai organization
