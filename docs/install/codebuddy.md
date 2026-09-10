# Workbuddy (CodeBuddy CLI)

The Workbuddy desktop agent client uses the CodeBuddy CLI
(`codebuddy`, alias `cbc`; npm package `@tencent-ai/codebuddy-code`,
Node.js 18+) as its terminal agent. CodeBuddy discovers skills only from its
**own** skills directory — it does not read the `~/.agents/skills` hub — so
the installer mirrors every skill into it.

Source: [Skills — CodeBuddy CLI docs](https://www.codebuddy.ai/docs/cli/skills)

- User scope: `~/.codebuddy/skills/<name>/SKILL.md`
- Project scope: `<repo>/.codebuddy/skills/<name>/SKILL.md` (takes priority
  over user scope on name conflicts)

## Install

```bash
# once: make CodeBuddy's presence visible to the installer
# (running the CLI once also creates ~/.codebuddy)
mkdir -p ~/.codebuddy

bash tools/install-skills.sh
```

The script links each repo skill into the hub, then links
`~/.codebuddy/skills/<name>` → `~/.agents/skills/<name>`. The mirror is
created only when `~/.codebuddy` already exists.

## Manual fallback (no script)

```bash
# POSIX
ln -sfn "$(pwd)/skills/knowledge-storage" ~/.agents/skills/knowledge-storage
ln -sfn ~/.agents/skills/knowledge-storage ~/.codebuddy/skills/knowledge-storage

# Windows (junctions — no admin required)
cmd /c mklink /J "%USERPROFILE%\.agents\skills\knowledge-storage" "%CD%\skills\knowledge-storage"
cmd /c mklink /J "%USERPROFILE%\.codebuddy\skills\knowledge-storage" "%USERPROFILE%\.agents\skills\knowledge-storage"
```

Repeat per skill (see `skills/` for the full list). Link to the hub, not the
repo, so `--copy` mode still has a single source of truth.

## Verify

1. The installer's health check prints one line per skill:

   ```
   OK   knowledge-storage (hub)
   OK   knowledge-storage (codebuddy)
   ```

2. In a logged-in CodeBuddy session, run `/skills` — the panel lists user,
   project, and plugin skills; the six kgent skills should appear with their
   token counts. (A model-mediated check via `codebuddy -p` requires
   `/login` first; the installer's own verify above already proves the
   SKILL.md files resolve through the mirror.)

## Update / Uninstall

- Update: re-run `bash tools/install-skills.sh` (the re-run is the update).
- Uninstall: `bash tools/install-skills.sh --uninstall` removes the hub and
  `~/.codebuddy/skills` entries.

## Troubleshooting

- **Installer skipped the mirror ("claude-style" hop missing)** — the mirror
  is only created when `~/.codebuddy` exists; `mkdir -p ~/.codebuddy` and
  re-run.
- **Skill not in `/skills`** — restart the CodeBuddy session; skills are
  scanned at startup.
- **Skill triggers but `kgent` fails** — the skills require the `kgent` CLI
  (installed by the script) and a configured backend (`~/.kgent/config.yaml`).
