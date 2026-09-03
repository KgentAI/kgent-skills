# 0001 — `kgent setup` merges `config.yaml` on rerun instead of overwriting

`kgent setup` regenerates `config.yaml` on every run, but users hand-edit that
file (`enabled: true`, `defaults.workspace_domain`, timeouts, sensitivity
floors). We decided setup is merge-on-rerun: existing backend entries keep
their keys verbatim and gain only missing keys from the discovery report, new
backends are appended `enabled: false`, configured-but-undiscovered backends
are kept, and non-backend sections are preserved as parsed. Two safety rails
ride along: an unparseable existing config aborts the run untouched (never
truncate what we cannot read back), and any rewrite first writes a timestamped
`config.yaml.bak-<ts>` (same `int(time.time())` convention as
`kgent config migrate`).

## Considered Options

- **Merge + backup (chosen, spec 方案 A+C)** — matches user expectations;
  requires a key-level merge contract (shallow, backend top-level only).
- **Refuse + write `config.generated.yaml` companion (B)** — simplest, but
  breaks "setup is repeatable".
- **Backup-then-overwrite alone (C)** — user still silently loses config;
  only acceptable as a supplement to A.

## Consequences

- The merge contract is user-facing: once shipped, changing the semantics
  again is what breaks users, so the shallow-merge rule (user keys win, no
  deep merge) is deliberate and load-bearing.
- Every setup rerun leaves a `.bak-<ts>` file; cleanup is left to the user.

Implemented in `kgent.capabilities.setup_config` (spec
`specs/2026-09-02-setup-config-overwrite.md`).
