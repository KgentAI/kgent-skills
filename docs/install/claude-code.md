# Claude Code

Claude Code discovers skills only from its **own** skills directory — it does
not read the `~/.agents/skills` hub — so the installer mirrors every skill
into it.

- User scope: `~/.claude/skills/<name>/SKILL.md`
- Project scope: `<repo>/.claude/skills/<name>/SKILL.md`

## Install

```bash
bash tools/install-skills.sh
```

The script links each repo skill into the hub, then links
`~/.claude/skills/<name>` → `~/.agents/skills/<name>`. The mirror is created
only when `~/.claude` already exists (i.e. Claude Code is installed).

## Manual fallback (no script)

```bash
# POSIX
ln -sfn "$(pwd)/skills/ingest-knowledge" ~/.agents/skills/ingest-knowledge
ln -sfn ~/.agents/skills/ingest-knowledge ~/.claude/skills/ingest-knowledge

# Windows (junctions — no admin required)
cmd /c mklink /J "%USERPROFILE%\.agents\skills\ingest-knowledge" "%CD%\skills\ingest-knowledge"
cmd /c mklink /J "%USERPROFILE%\.claude\skills\ingest-knowledge" "%USERPROFILE%\.agents\skills\ingest-knowledge"
```

Repeat per skill (see `skills/` for the full list). Link to the hub, not the
repo, so `--copy` mode still has a single source of truth.

## Verify

1. The installer's health check prints one line per skill:

   ```
   OK   ingest-knowledge (hub)
   OK   ingest-knowledge (claude)
   ```

2. Start a new Claude Code session (skills are scanned at startup) and check
   that the kgent skills appear — e.g. ask "what skills do you have" or use
   natural language: "Save this to the knowledge base" should trigger
   `ingest-knowledge`.

## Update / Uninstall

- Update: re-run `bash tools/install-skills.sh` (the re-run is the update).
- Uninstall: `bash tools/install-skills.sh --uninstall` removes the hub and
  `~/.claude/skills` entries.

## Troubleshooting

- **Skills not showing after install** — restart the session; Claude Code
  scans skill directories at startup only.
- **`FAIL <name>: claude entry broken`** — the mirror link exists but does
  not resolve; re-run the installer to replace it.
- **Skill triggers but `kgent` fails** — the skills require the `kgent` CLI
  (installed by the script) and a configured backend (`~/.kgent/config.yaml`).
