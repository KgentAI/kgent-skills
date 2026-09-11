# OpenCode

OpenCode loads skills from six locations, one of which is the user hub
`~/.agents/skills` — exactly where the installer puts kgent skills. No
OpenCode-specific mirror is needed.

Source: [Skills — OpenCode docs](https://opencode.ai/docs/skills/)

| Scope | Paths scanned by OpenCode |
|---|---|
| Project | `.opencode/skills/`, `.claude/skills/`, `.agents/skills/` (walked up to the git worktree) |
| Global | `~/.config/opencode/skills/`, `~/.claude/skills/`, `~/.agents/skills/` |

Format requirements OpenCode enforces: `SKILL.md` (all caps) with `name` and
`description` frontmatter; the name must match the directory name and match
`^[a-z0-9]+(-[a-z0-9]+)*$` — all kgent skills comply.

## Install

```bash
bash tools/install-skills.sh
```

The script builds `~/.agents/skills`, which OpenCode scans natively.

## Manual fallback (no script)

Populate the hub yourself (junction on Windows needs no admin):

```bash
# POSIX
ln -sfn "$(pwd)/skills/ingest-knowledge" ~/.agents/skills/ingest-knowledge

# Windows
cmd /c mklink /J "%USERPROFILE%\.agents\skills\ingest-knowledge" "%CD%\skills\ingest-knowledge"
```

(If you prefer OpenCode's own directory, target
`~/.config/opencode/skills/ingest-knowledge` instead — but the hub is shared
with Codex / OpenClaw / pi, so prefer the hub.)

## Verify

OpenCode has a non-interactive listing command:

```bash
opencode debug skill
```

All six kgent skills should appear. (Inside a session they also show up in
the `skill` tool's `<available_skills>` block.)

## Update / Uninstall

- Update: re-run `bash tools/install-skills.sh`.
- Uninstall: `bash tools/install-skills.sh --uninstall` empties the hub,
  which removes OpenCode's view of the skills.

## Troubleshooting

- **`opencode debug skill` shows nothing** — confirm the hub is populated
  (`ls ~/.agents/skills`) and restart OpenCode; skills are scanned at startup.
- **Skill hidden from the agent** — skills with `deny` permissions are hidden
  entirely; check the project's permission config.
- **Skill triggers but `kgent` fails** — the skills require the `kgent` CLI
  (installed by the script) and a configured backend (`~/.kgent/config.yaml`).
