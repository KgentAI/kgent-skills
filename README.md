# kgent-skills

Skills and specifications for the kgent knowledge management service packaging system.

## Overview

This repository contains the design specifications and skill definitions for packaging kgent as a federated, multi-backend knowledge management service with CLI, MCP, and Skill interfaces.

## Contents

- `specs/` - Design specifications and architecture documents
  - [2026-08-26-kgent-packaging-design.md](specs/2026-08-26-kgent-packaging-design.md) - Core architecture and design principles (v1.4)

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

```
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
