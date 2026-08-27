# kgent Service Packaging Design Spec

**Date**: 2026-08-26  
**Status**: Draft  
**Version**: 1.0

## Executive Summary

This document defines the architecture for packaging the kgent knowledge management service through three interface layers: **MCP tools**, **CLI**, and **Skills**. The system supports **federated multi-backend operations** across multiple platforms (Lark, DingTalk, Confluence, kgent-hosted) with intelligent routing, capability-aware fallbacks, and human-in-the-loop orchestration.

### Key Design Principles

1. **Federated Multi-Backend**: Operations can target multiple platforms simultaneously
2. **Capability-Based Composition**: Skills orchestrate via capability interfaces, backends are swappable
3. **Self-Disambiguation First**: Gather context and resolve ambiguity automatically before asking users
4. **Update-First Bias**: Always suggest updating existing knowledge over creating new
5. **Config as Hard Rule**: Configuration defines routing, but skills interpret intelligently
6. **Always Ask Before Writing**: Never silently execute write operations

---

## 1. Architecture Overview

### 1.1 Three-Layer Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Skills Layer                          │
│  - Orchestrates complex workflows                       │
│  - Intent clarification and disambiguation              │
│  - Human-in-the-loop approval                           │
│  - Backend-agnostic orchestration                       │
└────────────────┬────────────────────────────────────────┘
                 │ calls capability interfaces
                 ▼
┌─────────────────────────────────────────────────────────┐
│              Capability Router Layer                     │
│  - Routes operations to backends                        │
│  - Fans out to multiple backends                        │
│  - Aggregates results                                   │
│  - Handles capability-aware fallbacks                   │
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
- Always ask for user approval before write operations
- Backend-agnostic: only call capability interfaces

**Capability Router Layer:**
- Route operations to appropriate backends
- Fan out to multiple backends when configured
- Aggregate and deduplicate results
- Handle capability mismatches (e.g., backend doesn't support semantic search)
- Implement fallback strategies

**Backend Implementation Layer:**
- Provide concrete implementations of capabilities
- Each backend declares what it supports
- Handle platform-specific APIs and authentication
- Expose via MCP tools, CLI commands, or skill invocations

---

## 2. Configuration System

### 2.1 Configuration File Structure

Location: `~/.kgent/config.yaml` or project-local `.kgent-config.yaml`

```yaml
version: 1

# Global routing settings
defaults:
  routing_mode: configured  # explicit | configured | smart
  default_backends: [lark, kgent]

# Backend configurations
backends:
  lark:
    enabled: true
    type: skill  # skill | cli | mcp
    skill_name: lark-doc
    
    # Detailed capability declaration
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
      
      approval_flow:
        supported: true
        features:
          - request_approval
          - check_status
          - execute_approved
    
    auth:
      type: user_login
      status: authenticated
    
    content_types:
      - internal_docs
      - team_wiki
      - meeting_notes
    priority: 1
  
  dingtalk:
    enabled: true
    type: cli
    cli_name: dingtalk-cli
    
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
        fallback:
          search_by_semantics: search_by_keywords
        limits:
          max_results: 50
      
      approval_flow:
        supported: false
    
    auth:
      type: user_login
      status: authenticated
    
    content_types:
      - external_docs
    priority: 2
  
  kgent:
    enabled: true
    type: mcp
    mcp_url: https://kgent.example.com/mcp
    
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
      
      approval_flow:
        supported: true
        features:
          - request_approval
          - check_status
          - execute_approved
    
    auth:
      type: remote_mcp
      status: authenticated
    
    content_types:
      - archived_docs
    priority: 3

# Smart routing rules (when routing_mode: smart)
routing_rules:
  - match:
      content_type: meeting_notes
      tags: [internal]
    backends: [lark]
  
  - match:
      content_type: external_docs
    backends: [dingtalk, kgent]
  
  - match:
      content_type: archived
      older_than: 90d
    backends: [kgent]
  
  - default: [lark]

# Content type mapping
content_type_mapping:
  meeting_notes:
    primary: lark
    replicas: [kgent]
  
  api_docs:
    primary: confluence
    replicas: []
  
  team_wiki:
    primary: lark
    replicas: []
  
  research_papers:
    primary: kgent
    replicas: [lark]
  
  default:
    primary: lark
    replicas: [kgent]
```

### 2.2 Auto-Discovery Setup

The `kgent-setup` skill automatically detects available backends and their capabilities:

**Detection Process:**

1. **Discover available skills**
   - Scan `~/.claude/skills/` for `lark-*`, `dingtalk-*`, etc.
   - Read skill documentation to extract capabilities
   - Test functionality with sample operations

2. **Discover available CLIs**
   - Check PATH for `kgent-cli`, `dingtalk-cli`, `confluence-cli`
   - Run `--version` to verify installation
   - Parse `--help` output to extract available commands
   - Test with sample operations

3. **Discover MCP servers**
   - Check Claude Desktop config for MCP server entries
   - Query MCP server for available tools
   - Test connection and capabilities

4. **Generate initial config**
   - Create `config.yaml` with detected backends
   - Mark all as `enabled: false` by default
   - User reviews and enables desired backends

5. **Validate authentication**
   - For each enabled backend, test auth
   - Prompt user to authenticate if needed
   - Store credentials securely

**Setup Output Example:**

```
$ kgent-setup

🔍 Detecting available backends...

✅ Found Lark skill (lark-doc)
   Capabilities:
   - document_storage: ✅ (create, read, update, delete, list)
   - vector_search: ✅ (keyword ✅, semantic ✅, hybrid ✅)
   - approval_flow: ✅ (request, check, execute)
   Auth: ✅ authenticated (alice@company.com)

✅ Found DingTalk CLI (dingtalk-cli v1.2.3)
   Capabilities:
   - document_storage: ✅ (create, read, update, delete)
   - vector_search: ⚠️ (keyword ✅, semantic ❌, hybrid ❌)
     → Semantic search will fallback to keyword search
   - approval_flow: ❌ not available
   Auth: ✅ authenticated

❌ Confluence CLI not found
   → Install from: https://confluence.com/cli

✅ Found kgent MCP server (https://kgent.example.com/mcp)
   Capabilities:
   - document_storage: ✅ (create, read, update, delete, list)
   - vector_search: ✅ (keyword ✅, semantic ✅, hybrid ✅)
   - approval_flow: ✅ (request, check, execute)
   Auth: ✅ authenticated

📝 Generated config: ~/.kgent/config.yaml
   - 3 backends detected, 2 authenticated
   - Capabilities auto-detected
   - Please review and enable desired backends

🎯 Configure content routing?
   - [1] Use smart routing (recommended)
   - [2] Manual configuration
   - [3] Skip for now
```

---

## 3. Capability System

### 3.1 Core Capabilities

**document_storage:**
```python
- create_document(title: str, content: str, metadata: dict) → document_id
- read_document(document_id: str) → Document
- update_document(document_id: str, content: str, metadata: dict) → success
- delete_document(document_id: str) → success
- list_documents(filters: dict, limit: int) → list[DocumentMetadata]
```

**vector_search:**
```python
# Keyword search (exact/partial text match)
- search_by_keywords(
    query: str,
    filters: dict = None,
    top_k: int = 10,
    fields: list[str] = None
  ) → list[SearchResult]

# Semantic search (vector similarity)
- search_by_semantics(
    query: str,
    filters: dict = None,
    top_k: int = 10,
    similarity_threshold: float = 0.7
  ) → list[SearchResult]

# Hybrid search (both, merged)
- search_hybrid(
    query: str,
    filters: dict = None,
    top_k: int = 10,
    keyword_weight: float = 0.3,
    semantic_weight: float = 0.7,
    similarity_threshold: float = 0.7
  ) → list[SearchResult]
```

**approval_flow (optional):**
```python
- request_approval(document_id: str, approvers: list[str]) → approval_id
- check_approval(approval_id: str) → ApprovalStatus
- execute_approved(document_id: str) → success
```

### 3.2 Capability Declaration

Each backend declares its capabilities in the config:

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
    fallback:
      search_by_semantics: search_by_keywords
```

### 3.3 Capability-Aware Routing

The router uses capability info to make smart decisions:

```python
async def search_knowledge(query, mode="hybrid", backends="all"):
    targets = resolve_backends(backends)
    results = []
    
    for backend in targets:
        backend_caps = backend.capabilities.vector_search
        
        # Check if requested mode is supported
        if mode == "hybrid" and not backend_caps.features.search_hybrid:
            # Fallback to semantic if available, else keyword
            if backend_caps.features.search_by_semantics:
                actual_mode = "semantic"
            else:
                actual_mode = "keyword"
            log(f"Backend {backend.name}: hybrid → {actual_mode} (fallback)")
        
        elif mode == "semantic" and not backend_caps.features.search_by_semantics:
            # Use fallback if defined
            if "fallback" in backend_caps.features:
                actual_mode = backend_caps.features.fallback.search_by_semantics
                log(f"Backend {backend.name}: semantic → {actual_mode} (fallback)")
            else:
                log(f"Backend {backend.name}: semantic not supported, skipping")
                continue
        else:
            actual_mode = mode
        
        # Execute search
        backend_results = await backend.search(query, mode=actual_mode)
        results.extend(backend_results)
    
    # Aggregate and rank
    return aggregate_results(results)
```

---

## 4. Routing Modes

### 4.1 Explicit Mode

User specifies backends per command:

```bash
kgent store --backends lark,dingtalk --title "X" --content "Y"
kgent search --backends kgent --query "Z"
```

### 4.2 Configured Mode (Default)

Use config defaults:

```bash
kgent store --title "X" --content "Y"
# Uses default_backends from config, or content_type_mapping
```

### 4.3 Smart Mode

Rule-based routing from config:

```bash
kgent store --title "X" --content "Y" --routing smart
# Applies routing_rules based on content analysis
```

---

## 5. Intent Clarification System

### 5.1 Self-Disambiguation First

Before asking questions, gather context from multiple sources:

```python
async def gather_context(user_request, intent):
    context = {}
    
    # 1. Conversation context
    context['conversation'] = get_recent_conversation_context()
    
    # 2. Existing knowledge
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
5. **Existing knowledge**
6. **Common sense heuristics** (lowest)

### 5.3 Clarification Flow

```python
async def resolve_intent_with_context(user_request):
    # 1. Initial intent parsing
    initial_intent = parse_intent(user_request)
    
    # 2. Gather all available context
    context = await gather_context(user_request, initial_intent)
    
    # 3. Try to resolve using context (in priority order)
    resolved_intent = initial_intent
    
    if resolved_intent.confidence < 0.9:
        resolved_intent = resolve_from_conversation(resolved_intent, context['conversation'])
    
    if resolved_intent.confidence < 0.9:
        resolved_intent = resolve_from_existing_knowledge(resolved_intent, context['existing_knowledge'])
    
    if resolved_intent.confidence < 0.9:
        resolved_intent = resolve_from_preferences(resolved_intent, context['user_preferences'])
    
    if resolved_intent.confidence < 0.9:
        resolved_intent = resolve_from_learnings(resolved_intent, context['learnings'])
    
    if resolved_intent.confidence < 0.9:
        resolved_intent = resolve_from_heuristics(resolved_intent, context['heuristics'])
    
    # 4. Check final confidence
    if resolved_intent.confidence >= 0.9:
        return resolved_intent  # No need to ask
    else:
        # Only ask about remaining ambiguities
        remaining_ambiguities = resolved_intent.remaining_ambiguities
        return await ask_clarifying_questions(remaining_ambiguities, context)
```

### 5.4 Example: Smart Disambiguation

```
User: "Save this"

Skill gathers context:
1. Conversation: just discussed "API design guidelines v2"
2. Existing: found "API Design Guidelines v1" in Lark (85% similar)
3. Preferences: default_backend=lark, update-first bias
4. Learnings: user had duplicate issues before

Skill resolves:
- Intent: UPDATE (not create)
- Target: "API Design Guidelines v1" in Lark
- Content: the discussion we just had

Skill proposes:
┌─────────────────────────────────────────────────┐
│ Based on our discussion, I'll update            │
│ "API Design Guidelines v1" in Lark with the     │
│ new v2 info we just covered.                    │
│                                                 │
│ Proceed? [yes/no/edit]                          │
└─────────────────────────────────────────────────┘

ZERO questions asked!
```

---

## 6. Write Operation Orchestration

### 6.1 Update-First Bias

**Rule: Always suggest updating existing knowledge over creating new.**

```python
async def handle_save_knowledge(user_request):
    # 1. Clarify intent
    intent = await clarify_intent(user_request)
    
    # 2. Extract content
    content = await extract_content(intent)
    
    # 3. ALWAYS search for existing knowledge first
    existing = await search_knowledge(
        query=content.title,
        backends="all_configured",
        top_k=10,
        similarity_threshold=0.7  # Lower threshold for duplicate detection
    )
    
    # 4. Decision tree
    if existing:
        return await propose_update_existing(existing, content)
    else:
        return await propose_create_new(content)
```

### 6.2 UPDATE Flow

```python
async def handle_update(content):
    # Search for existing
    existing = await search_existing(content.title)
    
    if len(existing) == 0:
        # Not found → propose create
        return propose_create_new(content)
    
    elif len(existing) == 1:
        # Found in one place → propose update
        return propose_update_single(existing[0], content)
    
    else:
        # Found in multiple places → propose options
        return propose_update_multiple(existing, content)
```

**Example: Multiple Locations**

```
User: "Update the API design guidelines"

Skill finds:
  - Lark: "API Design Guidelines v1" (updated: 2024-01-15)
  - kgent: "API Design Guidelines" (updated: 2024-01-10)

Skill proposes:
┌─────────────────────────────────────────────────┐
│ Found "API Design Guidelines" in 2 places:      │
│                                                 │
│ 1. Lark (primary)                               │
│    - Title: API Design Guidelines v1            │
│    - Last updated: 2024-01-15                   │
│                                                 │
│ 2. kgent (archive)                              │
│    - Title: API Design Guidelines               │
│    - Last updated: 2024-01-10                   │
│                                                 │
│ Options:                                        │
│ [a] Update Lark only (recommended)              │
│ [b] Update kgent only                           │
│ [c] Update both                                 │
│ [d] Merge into one (keep Lark, archive kgent)   │
│ [e] Something else                              │
└─────────────────────────────────────────────────┘
```

### 6.3 CREATE Flow

```python
async def handle_create(content):
    # Check for duplicates first
    duplicates = await search_similar(content)
    if duplicates:
        return propose_duplicate_detected(duplicates, content)
    
    # Determine where to store
    content_type = analyze_content_type(content)
    routing = get_routing(content_type)
    
    return propose_storage_location(routing, content)
```

**Example: Smart Suggestion**

```
User: "Save this meeting notes"

Skill analyzes:
  - content_type: "meeting_notes"
  - Checks routing → primary: lark, replicas: [kgent]

Skill proposes:
┌─────────────────────────────────────────────────┐
│ I'll save this meeting notes to:                │
│                                                 │
│ 📝 Primary: Lark                                │
│    - Location: Team Wiki > Meeting Notes        │
│                                                 │
│ 📦 Archive: kgent                               │
│    - For long-term searchability                │
│                                                 │
│ Proceed? [yes/no/edit]                          │
└─────────────────────────────────────────────────┘
```

### 6.4 Multi-Backend Write Operations

**Strategies:**

1. **Best-effort**: Try all backends, report which succeeded/failed
2. **Transactional**: If any fails, roll back all (harder with 3rd-party APIs)

**Recommendation: Best-effort with detailed reporting**

```bash
$ kgent store --backends lark,dingtalk,confluence --title "X"
✅ Stored to Lark: https://lark.com/doc/abc123
✅ Stored to DingTalk: https://dingtalk.com/doc/def456
❌ Failed to store to Confluence: Authentication expired
```

### 6.5 Deduplication Strategy

When storing to multiple backends:

1. Generate **content fingerprint** (hash of title + content)
2. Store fingerprint in backend metadata
3. When searching, use fingerprint to detect duplicates across backends
4. Optionally show "also available in: [other backends]"

---

## 7. Search Aggregation

### 7.1 Multi-Backend Search

```python
async def search_knowledge(query, backends="all", mode="hybrid"):
    targets = resolve_backends(backends)
    
    # Fan out search to all backends concurrently
    results = await asyncio.gather(*[
        backend.search(query, mode=mode) for backend in targets
    ])
    
    # Aggregate and deduplicate
    merged = merge_and_deduplicate(results)
    
    # Rank by relevance across all sources
    ranked = rank_by_relevance(merged)
    
    return ranked
```

### 7.2 Result Aggregation

```python
def merge_and_deduplicate(results_from_backends):
    """
    Merge results from multiple backends, deduplicate by content fingerprint.
    """
    seen_fingerprints = set()
    merged = []
    
    for backend_results in results_from_backends:
        for result in backend_results:
            fingerprint = result.content_fingerprint
            
            if fingerprint in seen_fingerprints:
                # Duplicate found - add backend to "also available in"
                existing = next(r for r in merged if r.content_fingerprint == fingerprint)
                existing.also_available_in.append(result.backend)
            else:
                seen_fingerprints.add(fingerprint)
                merged.append(result)
    
    return merged
```

### 7.3 Ranking Strategy

```python
def rank_by_relevance(results):
    """
    Rank results by relevance across all backends.
    """
    # Factors:
    # - Relevance score from backend
    # - Backend priority (from config)
    # - Recency (last updated)
    # - Content type match
    
    scored = []
    for result in results:
        score = (
            result.relevance_score * 0.5 +
            result.backend_priority * 0.2 +
            result.recency_score * 0.2 +
            result.content_type_match * 0.1
        )
        scored.append((score, result))
    
    scored.sort(reverse=True)
    return [result for score, result in scored]
```

---

## 8. Error Handling

### 8.1 Backend Failure Strategies

**Read operations (search):**
- **Partial success**: Return results from successful backends
- Log failures for debugging
- Inform user which backends failed

**Write operations (create/update):**
- **Best-effort**: Try all backends, report status per backend
- Allow user to retry failed backends
- Suggest alternatives if primary backend fails

### 8.2 Error Reporting

```bash
$ kgent store --backends lark,dingtalk,confluence --title "X"

✅ Stored to Lark: https://lark.com/doc/abc123
✅ Stored to DingTalk: https://dingtalk.com/doc/def456
❌ Failed to store to Confluence: Authentication expired
   → Run `confluence-cli auth` to re-authenticate
   → Retry: `kgent store --backends confluence --title "X"`
```

### 8.3 Fallback Chains

```yaml
# In config
fallback_chains:
  document_storage:
    primary: lark
    fallbacks: [dingtalk, confluence, kgent]
  
  vector_search:
    primary: kgent
    fallbacks: [lark]
```

If primary backend fails, automatically try fallbacks (with user permission for writes).

---

## 9. Implementation Plan

### Phase 1: Core Infrastructure

1. **Capability Router Layer**
   - Implement capability interfaces
   - Backend registry and configuration loading
   - Basic routing logic

2. **Backend Adapters**
   - kgent-cli adapter (primary)
   - lark-cli adapter (via lark-doc skill)
   - Capability detection and declaration

3. **Configuration System**
   - Config file schema
   - Auto-discovery setup script
   - Capability detection

### Phase 2: Skills Layer

4. **Knowledge Storage Skill**
   - Intent clarification system
   - Self-disambiguation logic
   - Update-first bias implementation
   - Multi-backend orchestration

5. **Question Answering Skill**
   - Multi-backend search aggregation
   - Result ranking and deduplication
   - Capability-aware search mode selection

6. **Wiki Setup Skill**
   - Orchestrate knowledge storage across backends
   - Handle approval flows

### Phase 3: Advanced Features

7. **Smart Routing**
   - Content type analysis
   - Rule-based routing engine
   - User preference learning

8. **Deduplication**
   - Content fingerprinting
   - Cross-backend duplicate detection
   - Merge suggestions

9. **Monitoring & Observability**
   - Operation logging
   - Backend health checks
   - Performance metrics

---

## 10. Future Extensions

### 10.1 Additional Backends

Easy to add new backends by implementing capability interfaces:

- **Notion**: `notion-cli` adapter
- **Google Docs**: `gdocs-cli` adapter
- **SharePoint**: `sharepoint-cli` adapter

### 10.2 Advanced Capabilities

- **Knowledge Graph**: Relationships between documents
- **Versioning**: Track document history across backends
- **Access Control**: Fine-grained permissions per backend
- **Offline Mode**: Queue operations when backends unavailable

### 10.3 AI Enhancements

- **Auto-tagging**: Automatically classify content types
- **Smart summaries**: Generate summaries for search results
- **Conflict resolution**: AI-powered merge suggestions
- **Learning**: Improve routing based on user behavior

---

## 11. Success Criteria

1. **Modularity**: Skills can switch between backends without code changes
2. **Flexibility**: Support multiple backends simultaneously
3. **User Experience**: Minimal clarifying questions, smart suggestions
4. **Reliability**: Graceful degradation when backends fail
5. **Extensibility**: Easy to add new backends and capabilities

---

## Appendix A: Glossary

- **Backend**: A platform or service that provides knowledge management capabilities (Lark, DingTalk, Confluence, kgent-hosted)
- **Capability**: A specific feature or operation (document_storage, vector_search, approval_flow)
- **Skill**: An orchestration layer that coordinates complex workflows using capabilities
- **Router**: Middleware that routes operations to appropriate backends
- **Routing Mode**: How backends are selected (explicit, configured, smart)

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
    mcp_url: https://kgent.example.com/mcp
    capabilities:
      document_storage:
        supported: true
      vector_search:
        supported: true
    auth:
      type: remote_mcp
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
    capabilities:
      document_storage: {supported: true}
      vector_search: {supported: true}
    content_types: [archived_docs]

routing_rules:
  - match:
      content_type: meeting_notes
    backends: [lark]
  
  - match:
      content_type: archived
    backends: [kgent]
  
  - default: [lark, kgent]
```

---

**End of Specification**
