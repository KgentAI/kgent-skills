# kgent-skills

Skills and specifications for the kgent knowledge management service packaging system.

## Overview

This repository contains the design specifications and skill definitions for packaging kgent as a federated, multi-backend knowledge management service with CLI, MCP, and Skill interfaces.

## Contents

- `specs/` - Design specifications and architecture documents
  - [kgent-packaging-design.md](specs/2026-08-26-kgent-packaging-design.md) - Core architecture and design principles

## Key Design Principles

1. **Federated Multi-Backend**: Operations can target multiple platforms simultaneously (Lark, DingTalk, Confluence, kgent-hosted)
2. **Capability-Based Composition**: Skills orchestrate via capability interfaces, backends are swappable
3. **Self-Disambiguation First**: Gather context and resolve ambiguity automatically before asking users
4. **Update-First Bias**: Always suggest updating existing knowledge over creating new
5. **Config as Hard Rule**: Configuration defines routing, but skills interpret intelligently
6. **Always Ask Before Writing**: Never silently execute write operations

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

🚧 **Early Design Phase** - This repository is in active development.

## License

Private - kgentai organization
