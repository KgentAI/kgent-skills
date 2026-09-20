# Installing kgent skills per agent

`bash tools/install-skills.sh` is the one command that installs everything:
all `skills/*/SKILL.md` are linked into the cross-agent hub
`~/.agents/skills`, the `kgent` CLI is installed, and the whole chain is
health-checked (`install OK`).

How each agent then finds the skills differs — four agents read the hub
natively, two need a mirror (the installer creates it when the agent is
present):

| Agent | Where it discovers skills | Installer work | Guide |
|---|---|---|---|
| Claude Code | `~/.claude/skills` (own directory) | mirror hop | [claude-code.md](claude-code.md) |
| Codex (OpenAI) | `~/.agents/skills` (the hub) | none | [codex.md](codex.md) |
| OpenCode | `~/.agents/skills` (the hub) | none | [opencode.md](opencode.md) |
| OpenClaw | `~/.agents/skills` (the hub) | none | [openclaw.md](openclaw.md) |
| pi | `~/.agents/skills` (the hub) | none | [pi.md](pi.md) |
| Workbuddy (CodeBuddy CLI) | `~/.codebuddy/skills` (own directory) | mirror hop | [codebuddy.md](codebuddy.md) |

Shared mechanics (update = re-run the script, `--copy`, `--backup`,
`--uninstall`, the `kgent` CLI backend chain) are documented once in the
[main README](../../README.md#installation) — the per-agent guides only cover
what is specific to that agent: discovery paths, manual fallback, and how to
verify the skills are actually visible.

## The install gate

Platform integration skills (`lark/dingtalk/wecom-integration`) install only
when that platform is enabled — `backends.<platform>.enabled: true` in
`~/.kgent/config.yaml` (ADR 0010; the config is the only gate signal, native
skills on disk are never probed). The lanes and `local-fs-integration` always
install. The plain installer never removes; `--sync` converges both ways
(`--keep` opts out), `--force` ignores the gate, and `--agents claude` (or
`codebuddy`) scopes the mirror hops — the hub is always populated, so
hub-native agents (Codex, OpenCode, OpenClaw, pi) are not valid `--agents`
values. `kgent doctor` reports an enabled backend whose integration skill is
missing; `kgent setup` points at `--sync`.
