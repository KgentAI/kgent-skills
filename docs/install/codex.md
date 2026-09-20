# Codex (OpenAI)

Codex scans `.agents/skills` directories **including the user hub**
`$HOME/.agents/skills` — exactly where the installer puts kgent skills — and
follows symlinked skill folders while scanning. No Codex-specific mirror is
needed.

Source: [Build skills — OpenAI Codex docs](https://developers.openai.com/codex/skills)

| Scope | Path scanned by Codex |
|---|---|
| USER | `$HOME/.agents/skills` |
| REPO | `$CWD/.agents/skills`, `$CWD/../.agents/skills`, `$REPO_ROOT/.agents/skills` |
| ADMIN | `/etc/codex/skills` |
| SYSTEM | bundled with Codex |

Skill requirements: a directory with a `SKILL.md` whose frontmatter declares
`name` and `description` (both kgent-provided; kgent directory names already
match their `name:` fields).

## Install

```bash
bash tools/install-skills.sh
```

That's the whole story for Codex: the script builds `$HOME/.agents/skills`,
which Codex scans natively.

### Install gate

Platform integration skills (`lark/dingtalk/wecom-integration`) install only
when that platform is enabled (`backends.<platform>.enabled: true` in
`~/.kgent/config.yaml`); the lanes and `local-fs-integration` always install.
After enabling a backend run `bash tools/install-skills.sh --sync` (it also
removes skills whose platform you later disable; `--keep` opts out).
`kgent doctor` reports an enabled backend whose integration skill is missing.
Codex is hub-native, so it is not a valid `--agents` value — the hub serves
it unconditionally (see [the install gate](README.md#the-install-gate)).

## Manual fallback (no script)

Populate the hub yourself (junction on Windows needs no admin):

```bash
# POSIX
ln -sfn "$(pwd)/skills/ingest-knowledge" ~/.agents/skills/ingest-knowledge

# Windows
cmd /c mklink /J "%USERPROFILE%\.agents\skills\ingest-knowledge" "%CD%\skills\ingest-knowledge"
```

## Verify

- Non-interactive (no login needed) — render the model-visible prompt and
  check the skill list; the hub appears as a skill root and all six kgent
  skills should be named (verified on codex-cli 0.153.4):

  ```bash
  codex debug prompt-input "hello" | grep -E "ingest-knowledge|query-knowledge|wiki-setup|dingtalk-integration|lark-integration|wecom-integration"
  ```

- In the Codex REPL: run `/skills` (or type `$` to open the skill selector).
- Explicit invocation: `$ingest-knowledge`, or just describe a matching task
  (implicit invocation is on by default).

## Update / Uninstall

- Update: re-run `bash tools/install-skills.sh`.
- Uninstall: `bash tools/install-skills.sh --uninstall` empties the hub,
  which removes Codex's view of the skills.

## Troubleshooting

- **Skills not in `/skills`** — confirm the hub is populated
  (`ls ~/.agents/skills`) and restart Codex; directories are scanned at
  startup.
- **Same skill listed twice** — Codex does not merge same-named skills from
  different scopes (e.g. a repo `.agents/skills` copy shadows the user hub
  entry); remove the duplicate scope.
- **Skill triggers but `kgent` fails** — the skills require the `kgent` CLI
  (installed by the script) and a configured backend (`~/.kgent/config.yaml`).
