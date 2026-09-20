# OpenClaw

OpenClaw indexes the user skills hub `~/.agents/skills` (shown as source
`agents-skills-personal` in its skill tooling) — exactly where the installer
puts kgent skills. No OpenClaw-specific mirror is needed.

Skills docs: <https://docs.openclaw.ai/cli/skills>

## Install

```bash
bash tools/install-skills.sh
```

The script builds `~/.agents/skills`, which OpenClaw indexes natively.

### Install gate

Platform integration skills (`lark/dingtalk/wecom-integration`) install only
when that platform is enabled (`backends.<platform>.enabled: true` in
`~/.kgent/config.yaml`); the lanes and `local-fs-integration` always install.
After enabling a backend run `bash tools/install-skills.sh --sync` (it also
removes skills whose platform you later disable; `--keep` opts out).
`kgent doctor` reports an enabled backend whose integration skill is missing.
OpenClaw is hub-native, so it is not a valid `--agents` value — the hub
serves it unconditionally (see [the install gate](README.md#the-install-gate)).

## Manual fallback (no script)

Populate the hub yourself (junction on Windows needs no admin):

```bash
# POSIX
ln -sfn "$(pwd)/skills/ingest-knowledge" ~/.agents/skills/ingest-knowledge

# Windows
cmd /c mklink /J "%USERPROFILE%\.agents\skills\ingest-knowledge" "%CD%\skills\ingest-knowledge"
```

(Avoid `openclaw skills install` from a local directory for this repo — it
copies, freezing today's content; the hub link tracks the repo.)

## Verify

```bash
openclaw skills list                # all six kgent skills should show ✓ ready
openclaw skills info ingest-knowledge   # Source: agents-skills-personal
```

`openclaw skills check` additionally reports which skills are missing
requirements.

## Update / Uninstall

- Update: re-run `bash tools/install-skills.sh`.
- Uninstall: `bash tools/install-skills.sh --uninstall` empties the hub,
  which removes OpenClaw's view of the skills.

## Troubleshooting

- **Skills listed but not "ready"** — OpenClaw runs skills from its own
  gateway agents; those agents need `kgent` on PATH and
  `~/.kgent/config.yaml` present for the *user* the agent runs as. Re-run the
  installer as that user.
- **Stale descriptions after a repo edit** — restart the gateway / re-run
  `openclaw skills list`; indexing happens at startup.
- **Skill triggers but `kgent` fails** — the skills require the `kgent` CLI
  (installed by the script) and a configured backend (`~/.kgent/config.yaml`).
