# pi

pi (the `pi` coding harness) implements the
[Agent Skills standard](https://agentskills.io) and scans the user hub
`~/.agents/skills` among its global locations — exactly where the installer
puts kgent skills. No pi-specific mirror is needed.

Source: `pi` docs — Skills (`docs/skills.md` in the
`@earendil-works/pi-coding-agent` package).

| Scope | Paths scanned by pi |
|---|---|
| Global | `~/.pi/agent/skills/`, `~/.agents/skills/` |
| Project (trusted projects only) | `.pi/skills/`, `.agents/skills/` in `cwd` and ancestors up to the git root |
| Packages / CLI | package `skills/` dirs; `--skill <path>` (repeatable) |

pi is lenient about standard violations (e.g. it allows a `name:` differing
from the directory name), so kgent skills load cleanly.

## Install

```bash
bash tools/install-skills.sh
```

The script builds `~/.agents/skills`, which pi scans natively.

## Manual fallback (no script)

Populate the hub yourself (junction on Windows needs no admin):

```bash
# POSIX
ln -sfn "$(pwd)/skills/knowledge-storage" ~/.agents/skills/knowledge-storage

# Windows
cmd /c mklink /J "%USERPROFILE%\.agents\skills\knowledge-storage" "%CD%\skills\knowledge-storage"
```

## Verify

- Non-interactive (needs a configured pi provider): ask the model to read its
  own system prompt — all six kgent skills should come back:

  ```bash
  pi -p --no-session "List the exact names of the skills you have available. Reply with ONLY the comma-separated names."
  ```

- The interactive startup header lists loaded skills, and skills register as
  `/skill:name` commands: run `/skill:knowledge-storage` to force-load one.
- After changing skills on disk, `/reload` rescans without restarting.

## Update / Uninstall

- Update: re-run `bash tools/install-skills.sh`, then `/reload` in pi.
- Uninstall: `bash tools/install-skills.sh --uninstall` empties the hub,
  which removes pi's view of the skills.

## Troubleshooting

- **Skill not auto-triggering** — pi puts only descriptions in context;
  models don't always load on match. Use `/skill:name` to force it.
- **Project skills not loading** — project-level locations require the
  project to be trusted (`~/.pi/agent/trust.json`); global hub skills are not
  affected.
- **Skill loads but `kgent` fails** — the skills require the `kgent` CLI
  (installed by the script) and a configured backend (`~/.kgent/config.yaml`).
